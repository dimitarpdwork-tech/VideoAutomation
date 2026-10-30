"""One button: generate stories and produce the videos, ready for your review.

1. Generates new stories with the Claude API (skipped without an API key,
   or with --no-generate; then existing stories are used).
2. Produces videos for as many eligible stories as requested.
3. Stops. Every video waits in the review queue until you approve it; only
   approved videos can be uploaded or scheduled.

Run: python autopilot.py --channel main --count 5
To run it every week, add it to Windows Task Scheduler / cron.
"""
import argparse
import json
import subprocess
import sys

import produce_batch
import story_generator
from channel_config import ROOT, load_channel, paths, read_json, SHARED, story_fingerprint, venv_python, story_usage


def eligible_count(channel, config):
    usage = story_usage()
    used_ids = {row.get('story_id') for row in usage.values()}
    count, seen = 0, set()
    for path in paths(channel)['stories'].glob('*.json'):
        try:
            story = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError):
            continue
        if produce_batch.eligible_story(path, story, config) is None:
            continue
        fingerprint = story_fingerprint(story['text'])
        if fingerprint in usage or fingerprint in seen or story.get('id', path.stem) in used_ids:
            continue
        seen.add(fingerprint)
        count += 1
    return count


def run(command, label):
    print(f'\n== {label} ==', flush=True)
    return subprocess.run(command, cwd=ROOT).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--count', type=int, default=5, help='Stories to turn into videos')
    parser.add_argument('--no-generate', action='store_true', help='Use existing stories only')
    args = parser.parse_args()
    if not 1 <= args.count <= 30:
        parser.error('count must be between 1 and 30')
    config = load_channel(args.channel)
    funnel = config.get('video_format') == 'funnel'

    if args.no_generate:
        print('Story generation skipped (--no-generate).', flush=True)
    elif not story_generator.api_key():
        print('No Claude API key saved, so no new stories are generated; using existing stories.', flush=True)
    else:
        print(f'\n== Generating {args.count} stories ==', flush=True)
        try:
            story_generator.generate(args.channel, args.count, log=lambda m: print(m, flush=True))
        except Exception as exc:
            print(f'Story generation failed ({exc}); continuing with existing stories.', flush=True)

    available = eligible_count(args.channel, config)
    count = min(args.count, available)
    if not count:
        raise SystemExit('No eligible stories to produce. Add or generate stories, or check the word limits in Settings.')
    if count < args.count:
        print(f'Only {available} eligible stories; producing {count}.', flush=True)
    tts = venv_python('.venv-tts') if (ROOT / '.venv-tts').exists() else sys.executable
    if run([str(tts), '-u', str(ROOT / 'produce_batch.py'), '--channel', args.channel, '--count', str(count)],
           f'Producing {count} {"full videos + teasers" if funnel else "Shorts"}'):
        raise SystemExit('Production stopped; see the messages above.')

    print('\nDone. The new videos are waiting in the review queue; approve them, then schedule.', flush=True)


if __name__ == '__main__':
    main()
