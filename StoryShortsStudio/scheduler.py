"""Publish from each enabled channel's queue at its configured local times.

Run manually to enable the worker. It must remain running; a time that passed
while the computer was off is not replayed, but a slot reached up to 15 minutes
late (for example while another channel was uploading) still runs.
To publish on schedule without keeping this computer on, use preschedule.py instead.
"""
import argparse
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import upload_next
from channel_config import CHANNELS, SHARED, load_channel, lock, read_json, token_status, write_json

CATCH_UP = timedelta(minutes=15)
KEEP_DAYS = 14


def due_slots(schedule, now):
    """Today's local times in [now - CATCH_UP, now], as (key suffix, local datetime)."""
    zone = ZoneInfo(schedule['timezone'])
    local_now = now.astimezone(zone)
    for value in schedule['times']:
        try:
            hour, minute = (int(part) for part in value.split(':'))
        except ValueError:
            continue
        local = datetime(local_now.year, local_now.month, local_now.day, hour, minute, tzinfo=zone)
        if local <= local_now < local + CATCH_UP:
            yield f'{local.date()}:{hour:02d}:{minute:02d}', local


def tick(dry_run=False, now=None):
    now = now or datetime.now(timezone.utc)
    ledger = read_json(SHARED / 'schedule_runs.json', {})
    for file in sorted(CHANNELS.glob('*/config.json')):
        channel = file.parent.name
        try:
            config = load_channel(channel)
            schedule = config['schedule']
            if not schedule.get('enabled'):
                continue
            for suffix, local in due_slots(schedule, now):
                key = f'{channel}:{suffix}'
                if key in ledger:
                    continue
                if dry_run:
                    print(f"Due: {config['name']} at {local:%H:%M} ({schedule['timezone']})", flush=True)
                    continue
                if token_status(channel) != 'ok':
                    print(f"{config['name']}: not connected or sign-in expired; skipping {local:%H:%M}.", flush=True)
                    ledger[key] = {'status': 'skipped', 'reason': 'not connected', 'at': now.isoformat()}
                    write_json(SHARED / 'schedule_runs.json', ledger)
                    continue
                ledger[key] = {'status': 'started', 'started_at': now.isoformat()}
                write_json(SHARED / 'schedule_runs.json', ledger)
                try:
                    with lock('upload', wait=600):
                        video = upload_next.run(channel)
                    ledger[key]['status'] = 'finished' if video else 'nothing_ready'
                except Exception as exc:
                    ledger[key].update(status='needs_attention', error=str(exc)[:300])
                    print(f"{config['name']}: {exc}", flush=True)
                write_json(SHARED / 'schedule_runs.json', ledger)
        except Exception as exc:  # one broken profile must not stop the others
            print(f'Channel {channel}: {exc}', flush=True)
    # Forget old slots so the file does not grow forever.
    cutoff = (now - timedelta(days=KEEP_DAYS)).date().isoformat()
    old = [key for key in ledger if key.split(':')[1] < cutoff]
    if old:
        for key in old:
            ledger.pop(key)
        write_json(SHARED / 'schedule_runs.json', ledger)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        with lock('scheduler'):
            while True:
                try:
                    tick(args.dry_run)
                except Exception as exc:  # keep the worker alive; log and try again next tick
                    print(f'Scheduler error: {exc}', flush=True)
                if args.once:
                    break
                time.sleep(20)
    except KeyboardInterrupt:
        print('Scheduler stopped.')
