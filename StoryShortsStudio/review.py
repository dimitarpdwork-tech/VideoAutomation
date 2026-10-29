"""Review finished videos before they can be uploaded.

Nothing uploads until it is approved. Approve or reject one video, or a whole
batch at once (the dashboard's bulk review does the same).

  python review.py --channel main list
  python review.py --channel main approve 01_gen_x            (one story)
  python review.py --channel main approve --batch batch_2026  (everything pending in a batch)
  python review.py --channel main reject 01_gen_x --note "weak ending"
"""
import argparse
from datetime import datetime, timezone

from channel_config import paths, read_json, update_json

DECISIONS = ('approved', 'rejected', 'pending')


def pending(channel):
    rows = []
    for plan in sorted(paths(channel)['videos'].glob('*/batch.json')):
        for item in read_json(plan, []) or []:
            if item.get('status') == 'complete' and item.get('review', 'pending') == 'pending':
                rows.append((plan.parent.name, item))
    return rows


def decide(channel, batch, names, decision, note=None):
    """Set the review decision for the named items (all pending ones if names is empty)."""
    if decision not in DECISIONS:
        raise ValueError(f'Decision must be one of {DECISIONS}.')
    plan = paths(channel)['videos'] / batch / 'batch.json'
    if not plan.exists():
        raise ValueError(f'No batch {batch!r} for this channel.')
    changed = []

    def change(rows):
        for row in rows:
            if row.get('status') != 'complete':
                continue
            if names and row.get('name') not in names:
                continue
            if not names and row.get('review', 'pending') != 'pending':
                continue
            row.update(review=decision, reviewed_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
            if note is not None:
                row['review_note'] = note[:500]
            changed.append(row.get('name'))
    update_json(plan, change, [])
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('action', choices=['list', 'approve', 'reject', 'reset'])
    parser.add_argument('names', nargs='*', help='Item names, e.g. 01_gen_x')
    parser.add_argument('--batch', help='Batch folder name (default: the batch containing each name)')
    parser.add_argument('--note')
    args = parser.parse_args()
    if args.action == 'list':
        rows = pending(args.channel)
        for batch, item in rows:
            warn = ' | '.join(item.get('variety_warnings') or [])
            print(f"{batch}  {item['name']}  {item['title']}" + (f'   [!] {warn}' if warn else ''))
        print(f'{len(rows)} video(s) waiting for review.')
        return
    decision = {'approve': 'approved', 'reject': 'rejected', 'reset': 'pending'}[args.action]
    batches = [args.batch] if args.batch else sorted({b for b, item in pending(args.channel) if item['name'] in args.names}
                                                     | {p.parent.name for p in paths(args.channel)['videos'].glob('*/batch.json')
                                                        if any(r.get('name') in args.names for r in read_json(p, []) or [])})
    if not batches:
        raise SystemExit('Name a video or pass --batch.')
    total = []
    for batch in batches:
        total += decide(args.channel, batch, args.names, decision, args.note)
    print(f'{decision.capitalize()}: {len(total)} video(s).')


if __name__ == '__main__':
    main()
