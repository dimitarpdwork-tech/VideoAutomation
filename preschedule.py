"""Upload several queued videos now and let YouTube publish them on schedule.

Each video goes up as private with a publish time taken from the channel's
schedule (time zone + daily times in Settings). YouTube makes it public at that
time, so this computer can be off. Slots already given to earlier scheduled
uploads are skipped.

Run: python preschedule.py --channel main --count 7
Preview the slots without uploading: add --dry-run
"""
import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import upload_next
from channel_config import ROOT, load_channel, lock, paths, read_json

MIN_LEAD = timedelta(minutes=30)   # YouTube needs time to process before publishing.
MAX_DAYS_AHEAD = 60


def taken_slots(channel):
    history = read_json(paths(channel)['credentials'] / 'upload_history.json', {})
    return {row['publish_at'] for row in history.values()
            if row.get('publish_at') and row.get('status') in ('uploaded', 'uploading')}


def upcoming_slots(schedule, taken, count, now=None):
    """Next `count` free publish times (UTC ISO strings) from the daily schedule."""
    now = now or datetime.now(timezone.utc)
    zone = ZoneInfo(schedule['timezone'])
    times = sorted({tuple(int(part) for part in t.split(':')) for t in schedule['times']})
    if not times:
        raise ValueError('The channel schedule has no daily times.')
    day = now.astimezone(zone).date()
    slots = []
    for _ in range(MAX_DAYS_AHEAD):
        for hour, minute in times:
            local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            stamp = local.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            if local.astimezone(timezone.utc) >= now + MIN_LEAD and stamp not in taken:
                slots.append(stamp)
                if len(slots) == count:
                    return slots
        day += timedelta(days=1)
    return slots


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--count', type=int, default=7)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.count <= 50:
        parser.error('count must be between 1 and 50')
    config = load_channel(args.channel)
    slots = upcoming_slots(config['schedule'], taken_slots(args.channel), args.count)
    zone = ZoneInfo(config['schedule']['timezone'])
    print(f"Scheduling up to {len(slots)} video(s) for {config['name']} ({config['schedule']['timezone']}).", flush=True)
    scheduled = 0
    with lock('upload', wait=0 if args.dry_run else 120):
        for slot in slots:
            local = datetime.fromisoformat(slot.replace('Z', '+00:00')).astimezone(zone)
            print(f"\n== Slot {local:%a %d %b %H:%M} ==", flush=True)
            try:
                result = upload_next.run(args.channel, args.dry_run, slot)
            except upload_next.DailyCapReached as exc:
                print(f'{exc} Moving on to the next slot.', flush=True)
                continue
            except Exception as exc:
                # Never retry automatically; upload_next says whether it is safe to run again.
                print(f'Stopped: {exc}', flush=True)
                return 1
            if result is None:
                print('No more approved videos; review and approve more to fill later slots.', flush=True)
                break
            scheduled += 1
            if args.dry_run:
                print('(Dry run previews the same next video for every slot.)', flush=True)
                break
    print(f'\nDone: {scheduled} video(s) {"previewed" if args.dry_run else "scheduled"}.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f'Scheduling stopped: {exc}')
