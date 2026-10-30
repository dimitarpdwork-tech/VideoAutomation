"""Export approved videos for TikTok: vertical parts of a little over a minute.

TikTok pays (Creator Rewards) only for videos longer than one minute, and long
stories do best there as a numbered series. For each approved video this makes:

  videos/<batch>/tiktok/<name>_part1.mp4, _part2.mp4, ...  vertical 1080x1920
  videos/<batch>/tiktok/<name>_part1.txt, ...               caption to paste
  videos/<batch>/tiktok/HOW_TO_POST.txt                    posting checklist

Full videos are re-cut from their narration, at sentence ends, into parts of
about the channel's "TikTok part length" (never under 61 seconds), with a
"Part N" title card and a "Part N+1 is on my profile" end card. Shorts are
copied as they are. Teasers are skipped: TikTok gets the whole story.

Posting stays manual: TikTok's posting API only allows private posts until
TikTok approves an app, and posting by hand is safest for a new account.

Run: python tiktok_export.py --channel main
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

import metadata as video_metadata
import produce_batch
from channel_config import ROOT, load_channel, lock, paths, read_json, update_json, write_json

MIN_PART = 61.0          # TikTok's Creator Rewards count videos over one minute
SENTENCE_END = re.compile(r'[.!?…]["”\')]*$')
HOW_TO = """How to post these on TikTok
===========================

1. Post the parts of a story in order (part 1 first). Posting one part a day, or
   all parts within an hour, both work; add them to a TikTok playlist named after
   the story so viewers can binge.
2. Paste the caption from the matching .txt file.
3. AI label: TikTok asks creators to label realistic AI-generated audio or video.
   The narration is an AI voice, so switch on "AI-generated content" under
   "More options" when you post. It shows only a small "Creator labeled as AI-
   generated" tag, and labelled videos are not penalised; unlabelled AI content
   that TikTok detects can be removed or limited.
4. Creator Rewards need: 18+, 10,000 followers, 100,000 views in the last 30
   days, an eligible country, and videos over one minute (every part here is).
"""


def split(words, total, target):
    """[(start, end)] cut points at sentence ends; every part at least MIN_PART seconds."""
    # Possible cuts: the middle of the pause after each sentence.
    cuts = [round((word['end'] + (words[i + 1]['start'] if i + 1 < len(words) else total)) / 2, 3)
            for i, word in enumerate(words) if SENTENCE_END.search(word['word'].strip())]
    parts, start = [], 0.0
    while total - start > target * 1.4 and total - start >= MIN_PART * 2:
        # Both sides must stay over a minute; among those, the cut nearest the target length.
        fitting = [cut for cut in cuts if cut - start >= MIN_PART and total - cut >= MIN_PART]
        if not fitting:
            break
        cut = min(fitting, key=lambda c: abs((c - start) - target))
        parts.append((start, cut))
        start = cut
    parts.append((start, total))
    return parts


def cut_part(narration, part_dir, start, end, words):
    part_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y',
                    '-ss', f'{start:.3f}', '-to', f'{end:.3f}', '-i', str(narration / 'narration.wav'),
                    '-c:a', 'pcm_s16le', str(part_dir / 'narration.wav')], check=True)
    shifted = [{**w, 'start': round(max(0.0, w['start'] - start), 4), 'end': round(min(end, w['end']) - start, 4)}
               for w in words if start <= w['start'] < end]
    write_json(part_dir / 'timings.json', [w for w in shifted if w['end'] > w['start']])
    write_json(part_dir / 'metadata.json', {'duration_seconds': round(end - start, 3), 'source': str(narration)})


def caption(item, story, config, number, count):
    title = item['title'] + (f' (Part {number}/{count})' if count > 1 else '')
    hook = video_metadata.hook(story) if story else ''
    tags = video_metadata.normalize_hashtags((config.get('tiktok_hashtags') or []) +
                                             [t for t in config.get('hashtags') or [] if t.lower() != '#shorts'])
    lines = [title, '', hook if number == 1 else f'Part {number} of {count}.', '', ' '.join(tags[:6])]
    return '\n'.join(line for line in lines).strip() + '\n'


def render_part(part_dir, item, config, dest, filename, title, end_text):
    command = [produce_batch.python(), str(ROOT / 'make_video.py'), '--narration', str(part_dir),
               *produce_batch.background_args(item), '--destination', str(dest), '--filename', filename,
               '--format', 'vertical', '--caption-style', config['caption_style'],
               '--title-card', title, '--title-seconds', str(config.get('title_card_seconds', 3) or 3),
               '--progress-bar', '--font', config.get('caption_font') or 'Arial Black',
               '--word-color', config.get('caption_color') or '#FFD400',
               '--phrase-color', config.get('phrase_color') or '#FFFFFF', '--grade', config.get('color_grade') or 'none',
               '--voice-character', config.get('voice_character') or 'natural']
    if end_text:
        command += ['--end-text', end_text]
    if (ROOT / 'music').is_dir() and config.get('music_volume', 0) > 0:
        command += ['--music', str(ROOT / 'music'), '--music-volume', str(config['music_volume'])]
    subprocess.run(command, check=True)


def export_item(item, batch, config, channel_paths, log=print):
    """Make the TikTok files for one finished video; return [{'file', 'duration'}]."""
    folder = channel_paths['videos'] / batch
    dest = folder / 'tiktok'
    dest.mkdir(exist_ok=True)
    story_file = channel_paths['stories'] / item.get('used_story', '')
    story = read_json(story_file, None) if item.get('used_story') else None
    exported = []
    if item.get('format', 'shorts') == 'shorts':
        source = folder / item['video']
        if not source.exists():
            source = source.with_stem(source.stem + '_used')
        name = f"{item['name']}_part1"
        shutil.copyfile(source, dest / f'{name}.mp4')
        (dest / f'{name}.txt').write_text(caption(item, story, config, 1, 1), encoding='utf-8')
        return [{'file': f'tiktok/{name}.mp4', 'duration': item.get('duration_seconds')}]
    narration = channel_paths['narrations'] / Path(item['story']).stem / batch / 'full'
    timings = read_json(narration / 'timings.json', None)
    meta = read_json(narration / 'metadata.json', None)
    if not timings or not meta:
        raise RuntimeError(f"The narration for {item['name']} is missing (was the narrations folder cleaned?).")
    total = meta['duration_seconds']
    target = max(MIN_PART + 4, float(config.get('tiktok_part_seconds') or 75))
    parts = split(timings, total, target)
    log(f"{item['name']}: {total / 60:.1f} min -> {len(parts)} part(s)")
    for number, (start, end) in enumerate(parts, 1):
        name = f"{item['name']}_part{number}"
        part_dir = narration.parent / 'tiktok' / f'part{number}'
        cut_part(narration, part_dir, start, end, timings)
        title = item['title'] if len(parts) == 1 else f"{item['title']} · Part {number}"
        end_text = f'Part {number + 1} is on my profile' if number < len(parts) else None
        render_part(part_dir, item, config, dest, f'{name}.mp4', title, end_text)
        produce_batch.validate(dest / f'{name}.mp4', end - start)
        (dest / f'{name}.txt').write_text(caption(item, story, config, number, len(parts)), encoding='utf-8')
        exported.append({'file': f'tiktok/{name}.mp4', 'duration': round(end - start, 2)})
    return exported


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--batch', help='Only this batch')
    parser.add_argument('--include-unreviewed', action='store_true', help='Also export videos not approved yet')
    parser.add_argument('--again', action='store_true', help='Export videos that were exported before')
    args = parser.parse_args()
    config = load_channel(args.channel)
    channel_paths = paths(args.channel)
    done = failed = 0
    for plan in sorted(channel_paths['videos'].glob('*/batch.json')):
        batch = plan.parent.name
        if args.batch and batch != args.batch:
            continue
        settings = {**config, **read_json(plan.parent / 'settings.json', {}),
                    **{k: config[k] for k in ('tiktok_part_seconds', 'tiktok_hashtags')}}
        for item in read_json(plan, []):
            if item.get('status') != 'complete' or (item.get('tiktok') and not args.again):
                continue
            if item.get('review') != 'approved' and not args.include_unreviewed:
                continue
            try:
                exported = export_item(item, batch, settings, channel_paths, log=lambda m: print(m, flush=True))
            except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
                failed += 1
                print(f"Could not export {item['name']}: {exc}", flush=True)
                continue

            def record(rows, name=item['name'], exported=exported):
                for row in rows:
                    if row.get('name') == name:
                        row['tiktok'] = exported
            update_json(plan, record, [])
            (plan.parent / 'tiktok' / 'HOW_TO_POST.txt').write_text(HOW_TO, encoding='utf-8')
            done += 1
    if not done and not failed:
        print('Nothing to export: approve videos in Review first (already exported videos are skipped).', flush=True)
    else:
        print(f'TikTok export finished: {done} video(s) exported' + (f', {failed} failed' if failed else '') +
              '. Files are in each batch folder under tiktok/.', flush=True)
    if failed and not done:
        sys.exit(1)


if __name__ == '__main__':
    with lock('production'):
        main()
