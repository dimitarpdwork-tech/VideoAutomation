"""Produce a batch of story videos and mark successfully rendered stories used.

Formats (channel setting "video_format"):
  shorts  one vertical Short per story.
  funnel  per story, a full horizontal video plus a vertical teaser Short that
          stops at the cliffhanger and sends viewers to the full video.

Stories that need an editor's attention (repeated passages, too long) are set
aside as <id>_review.json and the batch carries on.

Run: .venv-tts python produce_batch.py --channel main --count 10
"""
import argparse
import json
import random
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import delivery
import image_picker
import metadata as video_metadata
import narrate
import persona as narrator_persona
import speech
import variety
import voice_worker
from channel_config import (paths, load_channel, lock, SHARED, read_json, write_json, update_json,
                            story_fingerprint, venv_python, CHANNELS)
from voice_selection import select_clip, select_voice

ROOT = Path(__file__).resolve().parent
SHORTS_LIMIT = 179
FULL_ENDING = 3.5   # make_video.END_HOLD: full videos end with a few seconds of music and a fade
MAX_SPEEDUP = 1.2
WORDS_PER_SECOND = 2.6
WORD_RE = r"\b\w+(?:['’\-]\w+)*\b"
# Fields other programs write into batch.json while a batch is still rendering.
EXTERNAL_FIELDS = ('full_video_id', 'full_publish_at', 'review', 'reviewed_at', 'review_note', 'title', 'tiktok')


def safe_name(text, limit=60):
    """File-name-safe slug: letters, digits, _ and - only."""
    return re.sub(r'[^A-Za-z0-9_-]+', '_', text).strip('_')[:limit] or 'story'


def write_plan(plan_path, plan):
    """Save the plan, keeping fields the uploader or the review screen wrote meanwhile."""
    def merge(on_disk):
        by_name = {row.get('name'): row for row in on_disk or []}
        for item in plan:
            disk = by_name.get(item.get('name'), {})
            for field in EXTERNAL_FIELDS:
                if field in disk and disk[field] != item.get(field):
                    item[field] = disk[field]
        return plan
    update_json(plan_path, merge, [])


class NeedsReview(Exception):
    """The story cannot be produced automatically; a person should edit it."""


def python():
    return str(venv_python('.venv') if (ROOT / '.venv').exists() else Path(sys.executable))


def word_count(text):
    return len(re.findall(WORD_RE, text))


def limits(config):
    if config.get('video_format') in ('funnel', 'long'):
        return config['full_min_words'], config['full_max_words']
    return config['min_words'], config['max_words']


def eligible_story(path, story, config):
    """Return the story's word count if it can be produced, otherwise None."""
    if path.stem.endswith(('_used', '_review')):
        return None
    # Feed previews can be cut off mid-story; everything else (scraped post
    # pages, generated stories, stories you wrote yourself) is accepted.
    if story.get('text_source') == 'feed_preview' or not story.get('text', '').strip():
        return None
    # Collected Reddit stories are concept sources for the story generator, not
    # scripts, unless the channel is set to narrate them (with permission).
    if story.get('text_source') == 'post_page' and config.get('collected_stories', 'rewrite') != 'narrate':
        return None
    title = story.get('title', '').strip()
    if not title or len(title) > 100 or any(c in title for c in '<>'):
        return None
    count = word_count(title + ' ' + delivery.strip(story['text']))
    low, high = limits(config)
    return count if low <= count <= high else None


def teaser_text(story, config, cta=None):
    """Opening of the story up to a cliffhanger, plus the call to action."""
    text = re.sub(r'\s+', ' ', speech.strip_meta(story['text'])).strip()
    sentences = [s for s in re.split(r'(?<=[.!?…])\s+', text) if s]
    total = word_count(text)
    cta = cta or config.get('teaser_cta', '')
    budget = max(25, config.get('teaser_seconds', 45) * WORDS_PER_SECOND
                 - word_count(cta) - word_count(story.get('title', '')))
    if story.get('teaser_sentences'):
        # The writer's cliffhanger, but never past the length budget or most of the story.
        chosen, count = [], 0
        for sentence in sentences[:max(1, int(story['teaser_sentences']))]:
            words = word_count(sentence)
            if chosen and (count + words > budget * 1.25 or count + words > total * 0.6):
                break
            chosen.append(sentence)
            count += words
    else:
        chosen, count = [], 0
        for sentence in sentences:
            words = word_count(sentence)
            if chosen and (count + words > budget * 1.25 or count + words > total * 0.6):
                break
            chosen.append(sentence)
            count += words
            if count >= budget * 0.75:
                break
    teaser = ' '.join(chosen).rstrip()
    if not teaser.endswith(('.', '!', '?', '…', '"', '”')):
        teaser += '.'
    return (teaser + ' ' + cta).strip()


def plan_batch(args, config, channel_paths, backgrounds, usage):
    candidates, seen = [], set()
    only = getattr(args, 'story', None)
    for path in sorted(channel_paths['stories'].glob('*.json')):
        if only and path.name != only:
            continue
        try:
            story = json.loads(path.read_text(encoding='utf-8-sig'))
        except (OSError, json.JSONDecodeError) as exc:
            print(f'Skipping unreadable story {path.name}: {exc}', flush=True)
            continue
        if not isinstance(story, dict) or not isinstance(story.get('text'), str):
            print(f'Skipping {path.name}: not a story file (needs "title" and "text").', flush=True)
            continue
        count = eligible_story(path, story, config)
        if count is None:
            continue
        fingerprint = story_fingerprint(story['text'])
        story_id = story.get('id', path.stem)
        # Only finished stories block reuse; a "reserved" row left by a crashed run is
        # stale, because planning only happens while holding the production lock.
        done = {h: r for h, r in usage.items() if r.get('status') == 'complete'}
        if fingerprint in done or fingerprint in seen or any(r.get('story_id') == story_id for r in done.values()):
            continue
        seen.add(fingerprint)
        candidates.append((count, path.name, story))
    # Generated and original stories first, then shortest first.
    rank = {'generated': 0, 'original': 0}
    selected = sorted(candidates, key=lambda c: (rank.get(c[2].get('text_source'), 1), c[0], c[1]))[:args.count]
    if only and not selected:
        low, high = limits(config)
        raise RuntimeError(f'The story {only} cannot be used: it was already made into a video, or it is not '
                           f'{low}-{high} words long. Write a new story.')
    if len(selected) < args.count:
        low, high = limits(config)
        raise RuntimeError(f'Only {len(selected)} eligible complete, unused stories of {low}-{high} words; '
                           f'requested {args.count}. Add or generate stories, or lower the count.')
    video_format = config.get('video_format') if config.get('video_format') in ('funnel', 'long') else 'shorts'
    funnel = video_format == 'funnel'
    rng = random.Random()
    ctas = [c for c in (config.get('teaser_ctas') or []) if c.strip()] or [config.get('teaser_cta', '')]
    recent = variety.recent_items(args.channel)
    plan = []
    for i, (count, name, story) in enumerate(selected):
        meta = video_metadata.build(story, config, {'funnel': 'teaser', 'long': 'full'}.get(video_format, 'short'))
        item = {'story': name, 'title': meta['title'], 'words': count,
                'format': video_format,
                'description': meta['description'], 'tags': meta['tags'],
                'generated': story.get('text_source') == 'generated',
                'background': backgrounds[i % len(backgrounds)].name if backgrounds else None,
                'story_hash': story_fingerprint(story['text']),
                'name': f'{i + 1:02d}_{safe_name(Path(name).stem)}', 'status': 'pending',
                'review': 'pending', 'synthetic_realistic': bool(story.get('synthetic_realistic'))}
        if config.get('voice_engine') == 'chatterbox':
            item['voice_clip'], item['voice_reason'] = select_clip(story, config.get('voice_clip') or '',
                                                                   config.get('voice_clip_male'), config.get('voice_clip_female'))
            item['voice'] = 'chatterbox:' + (Path(item['voice_clip']).stem if item['voice_clip'] else 'built-in')
        else:
            item['voice'], item['voice_reason'] = select_voice(story, config['voice'], config.get('voice_male'),
                                                               config.get('voice_female'))
        if video_format in ('funnel', 'long'):
            item['full_description'] = video_metadata.build(story, config, 'full')['description']
        if funnel:
            item['cta'] = rng.choice(ctas)
        item['opening'] = variety.first_sentence(delivery.strip(speech.strip_meta(story['text'])))
        item['variety_warnings'] = variety.check(item['title'], item['opening'], recent)
        slow = variety.hook_problem(story['text'])
        if slow:
            item['variety_warnings'].append(f'Weak hook: {slow}. Viewers decide in the first seconds.')
        recent.append({'title': item['title'], 'opening': item['opening']})
        plan.append(item)
    return plan


_WORKER = None


def chatterbox():
    """The batch's Chatterbox narrator (started on first use, closed by main)."""
    global _WORKER
    if _WORKER is None:
        _WORKER = voice_worker.VoiceWorker()
    return _WORKER


def close_worker():
    global _WORKER
    if _WORKER is not None:
        _WORKER.close()
        _WORKER = None


def run_narration(source, output, config, voice=None, clip=None, item=None, body_only=False):
    if config.get('voice_engine') == 'chatterbox':
        if clip is None:
            clip = config.get('voice_clip') or ''
        chatterbox().model = config.get('chatterbox_model') or 'standard'
        try:
            meta = chatterbox().narrate(story_path=source, output=output, clip=clip, speed=config['speed'],
                                        period_pause=config['period_pause'], clean=config.get('clean_language', True),
                                        expressiveness=config.get('expressiveness', 0.5), body_only=body_only)
        except voice_worker.VoiceError as exc:
            if exc.needs_review:
                raise NeedsReview(str(exc)) from exc
            raise
        if item is not None and meta.get('quality_warnings'):
            # Shown in Review next to the video, so you listen to those lines.
            item.setdefault('narration_warnings', []).extend(meta['quality_warnings'])
        return meta
    sys.argv = ['narrate.py', str(source), '--output', str(output), '--voice', voice or config['voice'],
                '--speed', str(config['speed']), '--period-pause', str(config['period_pause'])]
    if voice:
        sys.argv.append('--fixed-voice')
    if config.get('clean_language', True):
        sys.argv.append('--clean-language')
    try:
        narrate.main()
    except RuntimeError as exc:
        raise NeedsReview(str(exc)) from exc
    return read_json(output / 'metadata.json')


# Seconds of silence around the host, so it is always clear where the story stops and starts:
# the music swaps during these silences.
BEFORE_INTRO, AFTER_INTRO, BEFORE_OUTRO = 2.0, 1.8, 3.2
HOST_GAP = BEFORE_INTRO   # kept for older callers


def narrate_framed(story, base, config, item, host_clip):
    """Narrate each part with its speaker's voice and join them into base/full.

    The metadata gets 'host_spans' ([start, end] seconds), so the video can cut to
    the channel's scene and caption style while the host speaks.
    """
    import wave
    output = base / 'full'
    output.mkdir(parents=True, exist_ok=True)
    words, chunks, spans, script, frames = [], [], [], [], []
    offset, params, first_meta = 0.0, None, None
    parts = narrator_persona.segments(story)
    for number, (speaker, text) in enumerate(parts):
        part_story, part_dir = base / f'part_{number}.json', base / f'part_{number}'
        write_json(part_story, {**{k: v for k, v in story.items() if k not in ('intro', 'outro')}, 'text': text})
        clip = host_clip if speaker == 'host' else item.get('voice_clip')
        meta = run_narration(part_story, part_dir, config, item.get('voice'), clip, item, body_only=number > 0)
        first_meta = first_meta or meta
        if number:
            last = number == len(parts) - 1
            gap = (BEFORE_OUTRO if speaker == 'host' and last and number > 1 else BEFORE_INTRO if speaker == 'host'
                   else AFTER_INTRO if chunks and chunks[-1].get('speaker') == 'host' else 0.6)
            frames.append(gap)
            offset += gap
        with wave.open(str(part_dir / 'narration.wav'), 'rb') as audio:
            params = params or audio.getparams()
            data = audio.readframes(audio.getnframes())
            length = audio.getnframes() / audio.getframerate()
        frames.append(data)
        for word in read_json(part_dir / 'timings.json', []):
            words.append({**word, 'start': round(word['start'] + offset, 4), 'end': round(word['end'] + offset, 4)})
        for chunk in read_json(part_dir / 'chunks.json', []):
            chunks.append({**chunk, 'start': round(chunk['start'] + offset, 4), 'end': round(chunk['end'] + offset, 4),
                           'speaker': speaker})
        if speaker == 'host':
            spans.append([round(offset, 3), round(offset + length, 3)])
        script.append((part_dir / 'script.txt').read_text(encoding='utf-8'))
        offset += length
    with wave.open(str(output / 'narration.wav'), 'wb') as joined:
        joined.setparams(params)
        for piece in frames:
            joined.writeframes(b'\x00' * (round(piece * params.framerate) * params.sampwidth * params.nchannels)
                               if isinstance(piece, float) else piece)
    duration = sum(len(p) for p in frames if isinstance(p, bytes)) / (params.framerate * params.sampwidth * params.nchannels) + \
        sum(p for p in frames if isinstance(p, float))
    write_json(output / 'timings.json', words)
    write_json(output / 'chunks.json', chunks)
    (output / 'script.txt').write_text('\n\n'.join(script), encoding='utf-8')
    metadata = {**first_meta, 'duration_seconds': round(duration, 3), 'timestamp_count': len(words),
                'word_count': sum(len(s.split()) for s in script), 'host_spans': spans, 'host_voice_clip': host_clip,
                'quality_warnings': (item or {}).get('narration_warnings', [])[:5]}
    write_json(output / 'metadata.json', metadata)
    print(f'Joined narrator and host voices ({duration:.1f}s, host speaks {len(spans)} time(s)).', flush=True)
    return metadata


def fit_to_shorts(narration, meta):
    """Keep a Short under the 3-minute limit without cutting the story."""
    if meta['duration_seconds'] <= SHORTS_LIMIT:
        return
    factor = meta['duration_seconds'] / SHORTS_LIMIT
    if factor > MAX_SPEEDUP:
        raise NeedsReview(f"Narration is {meta['duration_seconds']:.0f}s; shorten the story to fit "
                          f'{SHORTS_LIMIT}s (a {factor:.2f}x speed-up would be needed).')
    subprocess.run([python(), str(ROOT / 'fit_narration.py'), str(narration), '--seconds', str(SHORTS_LIMIT)], check=True)


def pick_image(story, config, item, orientation):
    """Find the story's photo. Pillow lives in .venv; production may run in the voice environment without it."""
    channel, key = config.get('id') or 'main', Path(item['story']).stem
    try:
        import PIL  # noqa: F401
    except ImportError:
        source = SHARED / 'images' / f'_{key}_story.json'
        write_json(source, story)
        try:
            result = subprocess.run([python(), str(ROOT / 'image_picker.py'), '--channel', channel, '--story', str(source),
                                     '--key', key, '--orientation', orientation], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', cwd=ROOT)
        finally:
            source.unlink(missing_ok=True)
        if result.stderr.strip():
            print(result.stderr.strip(), flush=True)
        lines = [line for line in result.stdout.splitlines() if line.startswith('{')]
        if result.returncode or not lines:
            raise image_picker.NoImage(f'the image search stopped ({(result.stderr or result.stdout).strip()[-300:]})')
        reply = json.loads(lines[-1])
        if reply.get('error'):
            raise image_picker.NoImage(reply['error'])
        return Path(reply['path'])
    return image_picker.pick(story, config, channel, key, orientation, log=lambda m: print(m, flush=True))


def ensure_image(item, config, story):
    """Pick the story's background photo (image mode); fall back to a clip if none is found."""
    if config.get('background_mode') != 'image':
        return
    if item.get('image') and (ROOT / item['image']).is_file():
        return
    orientation = 'portrait' if item.get('format', 'shorts') == 'shorts' else 'landscape'
    try:
        path = pick_image(story, config, item, orientation)
    except image_picker.NoImage as exc:
        if item.get('background'):
            item.setdefault('variety_warnings', []).append(f'No image found, so a background clip was used: {exc}')
            return
        raise
    item['image'] = path.relative_to(ROOT).as_posix()
    credit = image_picker.credit_line(path)
    if credit:
        for field in ('description', 'full_description'):
            if item.get(field) and credit not in item[field]:
                item[field] = item[field].rstrip() + '\n\n' + credit


def background_args(item):
    if item.get('image'):
        return ['--image', str(ROOT / item['image'])]
    if not item.get('background'):
        raise RuntimeError('No background: add clips to backgrounds/ or set the channel to use images.')
    return ['--background', str(ROOT / 'backgrounds' / item['background'])]


SCENE_TYPES = ('.mp4', '.mov', '.webm', '.mkv', '.m4v', '.jpg', '.jpeg', '.png', '.webp')


def host_scene(config):
    """The channel's own scene for the host's lines: a file named host_scene.* in the channel folder."""
    folder = CHANNELS / (config.get('id') or 'main')
    for path in sorted(folder.glob('host_scene.*')) if folder.is_dir() else []:
        if path.suffix.lower() in SCENE_TYPES:
            return path
    return None


MUSIC_TYPES = ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac')
DARK_THEMES = ('horror', 'scary', 'creepy', 'nosleep', 'paranormal', 'true crime', 'mystery')


def _has_tracks(folder):
    return folder.is_dir() and any(p.suffix.lower() in MUSIC_TYPES for p in folder.iterdir())


def music_for(config):
    """(story music, host music): a folder or file each, or None.

    Your own tracks come first: the channel folder's music/story and music/host,
    then the shared music folder for the story. Dark channels otherwise get the
    built-in tension drone and music box (music_synth.py).
    """
    if config.get('music_volume', 0) <= 0:
        return None, None
    own = CHANNELS / (config.get('id') or 'main') / 'music'
    for sub in ('story', 'host'):
        try:
            (own / sub).mkdir(parents=True, exist_ok=True)   # so you can see where your tracks go
        except OSError:
            pass
    story = own / 'story' if _has_tracks(own / 'story') else (ROOT / 'music' if _has_tracks(ROOT / 'music') else None)
    host = own / 'host' if _has_tracks(own / 'host') else None
    dark = any(word in (config.get('story_category') or '').lower() for word in DARK_THEMES)
    if dark and (story is None or host is None):
        import music_synth
        drone, box = music_synth.ensure(SHARED / 'music')
        story, host = story or drone, host or box
    return story, host


def render(narration, item, config, dest, filename, layout):
    command = [python(), str(ROOT / 'make_video.py'), '--narration', str(narration), *background_args(item),
               '--destination', str(dest), '--name', item['name'], '--format', layout,
               '--caption-style', config['caption_style']]
    if filename:
        command += ['--filename', filename]
    if config.get('title_card', True):
        command += ['--title-card', item['title'], '--title-seconds', str(config.get('title_card_seconds', 3))]
    if layout == 'vertical' and config.get('progress_bar', True):
        command.append('--progress-bar')
    command += ['--font', config.get('caption_font') or 'Arial Black',
                '--word-color', config.get('caption_color') or '#FFD400',
                '--phrase-color', config.get('phrase_color') or '#FFFFFF',
                '--grade', config.get('color_grade') or 'none',
                '--voice-character', config.get('voice_character') or 'natural',
                '--host-name', config.get('name') or '']
    scene = host_scene(config)
    if scene:
        command += ['--host-scene', str(scene)]
    story_music, host_music = music_for(config)
    if story_music or host_music:
        command += ['--music-volume', str(config['music_volume'])]
    if story_music:
        command += ['--music', str(story_music)]
    if host_music:
        command += ['--host-music', str(host_music)]
    subprocess.run(command, check=True)
    output = filename or (item['name'] + ('_yellow_words' if config['caption_style'] == 'words' and layout == 'vertical' else '') + '.mp4')
    marker = Path(dest) / (output + '.voice-fallback')
    if marker.exists():
        warning = (f'The "{marker.read_text(encoding="utf-8").strip()}" voice character failed on this video, so it uses '
                   'the natural voice. Listen before approving.')
        if warning not in item.setdefault('variety_warnings', []):
            item['variety_warnings'].append(warning)
        marker.unlink(missing_ok=True)


_FFMPEG = None


def ffmpeg_exe():
    """FFmpeg's path. Production may run in the voice environment, which lacks imageio-ffmpeg: ask .venv then."""
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    try:
        import imageio_ffmpeg
        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        result = subprocess.run([python(), '-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'],
                                capture_output=True, text=True, check=True)
        _FFMPEG = result.stdout.strip().splitlines()[-1]
    return _FFMPEG


def validate(video, expected_seconds=None):
    """Quick integrity check of a finished file: every packet readable, length as expected."""
    ffmpeg = ffmpeg_exe()
    check = subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-i', str(video), '-c', 'copy', '-f', 'null', '-'],
                           capture_output=True, text=True, errors='replace')
    if check.returncode:
        raise RuntimeError(f'{video.name} failed its integrity check: {check.stderr.strip()[:300]}')
    if expected_seconds:
        probe = subprocess.run([ffmpeg, '-hide_banner', '-i', str(video)], capture_output=True, text=True, errors='replace')
        found = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', probe.stderr)
        length = int(found[1]) * 3600 + int(found[2]) * 60 + float(found[3]) if found else 0
        if abs(length - expected_seconds) > 2:
            raise RuntimeError(f'{video.name} is {length:.1f}s long; expected {expected_seconds:.1f}s.')


def produce_short(item, config, channel_paths, batch, dest):
    source = channel_paths['stories'] / item['story']
    ensure_image(item, config, read_json(source))
    narration = channel_paths['narrations'] / source.stem / batch
    meta = run_narration(source, narration, config, item.get('voice'), item.get('voice_clip'), item)
    fit_to_shorts(narration, meta)
    render(narration, item, config, dest, None, 'vertical')
    output = dest / (item['name'] + ('_yellow_words' if config['caption_style'] == 'words' else '') + '.mp4')
    meta = read_json(narration / 'metadata.json')
    validate(output, meta['duration_seconds'])
    return {'video': output.name, 'duration_seconds': meta['duration_seconds']}


def produce_full(item, config, channel_paths, batch, dest):
    """Narrate and render the horizontal full video plus its thumbnail."""
    source = channel_paths['stories'] / item['story']
    story = read_json(source)
    ensure_image(item, config, story)
    base = channel_paths['narrations'] / source.stem / batch
    host_clip = config.get('host_voice_clip') or ''
    if (story.get('intro') or story.get('outro')) and host_clip and config.get('voice_engine') == 'chatterbox':
        # Cold open, the host's intro, the story, the host's sign-off, each in its own voice.
        full_meta = narrate_framed(story, base, config, item, host_clip)
    else:
        # Without a separate host voice the host stays silent: a narrator who suddenly talks
        # about the channel pulls the listener out of the story.
        plain = base / 'full_story.json'
        write_json(plain, {key: value for key, value in story.items() if key not in ('intro', 'outro')})
        full_meta = run_narration(plain, base / 'full', config, item.get('voice'), item.get('voice_clip'), item)
    limit = config.get('max_full_minutes', 15) * 60
    if full_meta['duration_seconds'] > limit:
        raise NeedsReview(f"Full narration is {full_meta['duration_seconds'] / 60:.1f} min; the limit is "
                          f"{limit / 60:.0f} min (YouTube accounts without phone verification cannot upload "
                          'videos over 15 minutes). Shorten the story or raise the limit in Settings.')
    full_name = item['name'] + '_full.mp4'
    render(base / 'full', item, config, dest, full_name, 'landscape')
    full_meta = read_json(base / 'full' / 'metadata.json')
    validate(dest / full_name, full_meta['duration_seconds'] + FULL_ENDING)
    thumb = dest / (item['name'] + '_full.jpg')
    picture = ['--image', str(ROOT / item['image'])] if item.get('image') else \
        ['--video', str(ROOT / 'backgrounds' / (item.get('background') or ''))]
    subprocess.run([python(), str(ROOT / 'thumbnail.py'), *picture, '--title', item['title'], '--out', str(thumb)], check=False)
    return full_name, thumb, full_meta


def produce_long(item, config, channel_paths, batch, dest):
    full_name, thumb, meta = produce_full(item, config, channel_paths, batch, dest)
    return {'video': full_name, 'full_video': full_name, 'thumbnail': thumb.name if thumb.exists() else None,
            'duration_seconds': meta['duration_seconds'], 'full_duration_seconds': meta['duration_seconds']}


def produce_funnel(item, config, channel_paths, batch, dest):
    source = channel_paths['stories'] / item['story']
    story = read_json(source)
    base = channel_paths['narrations'] / source.stem / batch
    full_name, thumb, full_meta = produce_full(item, config, channel_paths, batch, dest)
    try:
        teaser_story = base / 'teaser_story.json'
        write_json(teaser_story, {**story, 'text': teaser_text(story, config, item.get('cta'))})
        teaser_meta = run_narration(teaser_story, base / 'teaser', config, item.get('voice'), item.get('voice_clip'), item)
        fit_to_shorts(base / 'teaser', teaser_meta)
        teaser_name = item['name'] + '_teaser.mp4'
        render(base / 'teaser', item, config, dest, teaser_name, 'vertical')
        validate(dest / teaser_name, read_json(base / 'teaser' / 'metadata.json')['duration_seconds'])
    except BaseException:
        # Without its teaser the full video would sit in the folder forever; remove it.
        (dest / full_name).unlink(missing_ok=True)
        thumb.unlink(missing_ok=True)
        raise
    return {'video': teaser_name, 'full_video': full_name, 'thumbnail': thumb.name if thumb.exists() else None,
            'duration_seconds': read_json(base / 'teaser' / 'metadata.json')['duration_seconds'],
            'full_duration_seconds': full_meta['duration_seconds']}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--channel', default='main')
    parser.add_argument('--count', type=int, default=10)
    parser.add_argument('--batch', help='Existing batch name to resume')
    parser.add_argument('--max-words', type=int, help='Override the word limit for this batch only')
    parser.add_argument('--story', help='Make the video from this story file only (e.g. gen_123.json)')
    args = parser.parse_args()
    if not 1 <= args.count <= 100:
        parser.error('count must be between 1 and 100')
    config = load_channel(args.channel)
    if config.get('voice_engine') == 'chatterbox' and not voice_worker.installed():
        raise SystemExit('This channel uses the Chatterbox voice, which is not installed yet. Run setup_voice.cmd '
                         '(Windows) or ./setup_voice.sh, or choose the Kokoro voice in Settings.')
    if args.max_words is not None:
        key = 'full_max_words' if config.get('video_format') == 'funnel' else 'max_words'
        if not 1 <= args.max_words <= 5000:
            parser.error('Invalid max-words override')
        config[key] = args.max_words
    channel_paths = paths(args.channel)
    batch = args.batch or ('batch_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S'))
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', batch):
        parser.error('Invalid batch name')
    dest = channel_paths['videos'] / batch
    usage = read_json(SHARED / 'story_usage.json', {})
    background_dir = ROOT / 'backgrounds'
    backgrounds = ([background_dir / name for name in config['backgrounds']] if config['backgrounds']
                   else sorted(background_dir.glob('*.mp4')))
    if any(not p.is_file() or p.resolve().parent != background_dir.resolve() for p in backgrounds):
        raise RuntimeError('A selected background clip is missing from backgrounds/; check Settings.')
    if not backgrounds and config.get('background_mode') != 'image':
        raise RuntimeError('No background clips. Add MP4s to backgrounds/, or set the channel to use one image per story.')
    dest.mkdir(parents=True, exist_ok=True)
    plan_path = dest / 'batch.json'
    if plan_path.exists():
        plan = read_json(plan_path)
        config = read_json(dest / 'settings.json', config)
    else:
        plan = plan_batch(args, config, channel_paths, backgrounds, usage)
        write_plan(plan_path, plan)
        write_json(dest / 'settings.json', config)

    for item in plan:
        if item['status'] in ('skipped', 'failed'):
            continue
        source = channel_paths['stories'] / item['story']
        if 'story_hash' not in item:
            original = source if source.exists() else source.with_stem(source.stem + '_used')
            item['story_hash'] = story_fingerprint(read_json(original)['text'])
        previous = usage.get(item['story_hash'])
        if previous and previous['channel'] != args.channel:
            raise RuntimeError('A story in this batch belongs to another channel.')
        if previous and previous.get('status') == 'complete' and previous.get('batch') not in (None, batch):
            raise RuntimeError('A story in this batch was already used by another batch.')
        usage[item['story_hash']] = {'channel': args.channel, 'batch': batch,
                                     'status': 'complete' if item['status'] == 'complete' else 'reserved',
                                     'story_id': Path(item['story']).stem}
    write_plan(plan_path, plan)
    write_json(SHARED / 'story_usage.json', usage)

    def release(item):
        row = usage.get(item.get('story_hash'))
        if row and row.get('batch') == batch and row.get('status') != 'complete':
            usage.pop(item['story_hash'], None)

    completed = skipped = failed = 0
    try:
        for item in plan:
            if item['status'] in ('skipped', 'failed'):
                skipped += item['status'] == 'skipped'
                failed += item['status'] == 'failed'
                continue
            source = channel_paths['stories'] / item['story']
            used = source.with_stem(source.stem + '_used')
            if item['status'] == 'complete' and finished_files_exist(dest, item):
                if source.exists() and not used.exists():
                    source.rename(used)
                completed += 1
                continue
            kind = item.get('format', 'shorts')
            label = {'funnel': 'full video + teaser', 'long': 'long video'}.get(kind, 'Short')
            print(f"Starting {item['name']}: {item['words']} words ({label})", flush=True)
            produce = {'funnel': produce_funnel, 'long': produce_long}.get(kind, produce_short)
            try:
                result = produce(item, config, channel_paths, batch, dest)
            except NeedsReview as exc:
                # Free the story for a later batch once someone has edited it.
                review = source.with_stem(source.stem + '_review')
                if source.exists() and not review.exists():
                    source.rename(review)
                release(item)
                item.update(status='skipped', reason=str(exc))
                write_plan(plan_path, plan)
                write_json(SHARED / 'story_usage.json', usage)
                skipped += 1
                print(f"Skipped {item['name']}: {exc}\n  Edit {review.name} and rename it back to "
                      f'{source.name} to use it in a later batch.', flush=True)
                continue
            except (subprocess.CalledProcessError, OSError, RuntimeError, KeyError, ValueError) as exc:
                # One broken story must not stop the batch or lock its story away.
                release(item)
                item.update(status='failed', reason=f'{type(exc).__name__}: {exc}'[:500])
                write_plan(plan_path, plan)
                write_json(SHARED / 'story_usage.json', usage)
                failed += 1
                print(f"Failed {item['name']}: {exc}. The story stays in the library for a later batch.", flush=True)
                continue
            item.update(status='complete', used_story=used.name, **result)
            # Save completion before renaming, so interrupted runs can recover.
            write_plan(plan_path, plan)
            if not used.exists():
                source.rename(used)
            usage[item['story_hash']].update(status='complete')
            write_json(SHARED / 'story_usage.json', usage)
            completed += 1
            print(f"Completed {item['name']}; marked {used.name}", flush=True)
    finally:
        close_worker()
        # Whatever stopped the run, unfinished stories go back to the library.
        for item in plan:
            if item['status'] not in ('complete',):
                release(item)
        write_json(SHARED / 'story_usage.json', usage)
    summary = f'Batch complete: {completed} stories for {config["name"]}.'
    if skipped:
        summary += f' {skipped} set aside for review.'
    if failed:
        summary += f' {failed} failed (see batch.json); their stories stay available.'
    print(summary, flush=True)


def finished_files_exist(dest, item):
    """True if each output of a completed item exists, uploaded (_used) or not."""
    names = [item.get('video')] + ([item.get('full_video')] if item.get('format') == 'funnel' else [])
    for name in names:
        if not name:
            return False
        path = dest / name
        if not (path.is_file() or path.with_stem(path.stem + '_used').is_file()):
            return False
    return True


if __name__ == '__main__':
    with lock('production'):
        main()
