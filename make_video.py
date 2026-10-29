"""Render a narration over a background clip with automatic captions.

Vertical (1080x1920) for Shorts or landscape (1920x1080) for full videos.
Optional extras: a hook title card for the first seconds, a progress bar, and
background music that automatically ducks under the narration.
"""
import argparse
import json
import os
import random
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent
MUSIC_TYPES = ('.mp3', '.m4a', '.aac', '.wav', '.ogg', '.flac')
SIZES = {'vertical': (1080, 1920), 'landscape': (1920, 1080)}


def ass_time(seconds):
    ticks = round(seconds * 100)
    return f'{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}'


def probe(path):
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-i', str(path)],
                            capture_output=True, text=True, errors='replace')
    return result.stderr


def media_duration(path):
    """Duration in seconds from FFmpeg's header probe, or None if unknown."""
    match = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', probe(path))
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def video_size(path):
    match = re.search(r'Video:.*?(\d{2,5})x(\d{2,5})', probe(path))
    return (int(match[1]), int(match[2])) if match else None


def background_offset(background, duration, rng=random):
    """Start somewhere random in long clips so reused backgrounds look different."""
    length = media_duration(background)
    if not length or length <= duration + 1:
        return 0.0
    return round(rng.uniform(0, length - duration - 0.5), 2)


def pick_music(folder, rng=random):
    if not folder or not Path(folder).is_dir():
        return None
    tracks = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in MUSIC_TYPES)
    return rng.choice(tracks) if tracks else None


GRADE_FILTERS = {
    'none': '',
    'cold': 'colorbalance=rs=-0.04:bs=0.08:bm=0.04,eq=saturation=0.85:contrast=1.05',
    'warm': 'colorbalance=rs=0.06:rm=0.03:bs=-0.05,eq=saturation=0.95',
    'faded': 'eq=contrast=0.9:saturation=0.8:brightness=0.03',
    'noir': 'hue=s=0,eq=contrast=1.2',
}


def ass_colour(hex_colour, alpha=0):
    """'#RRGGBB' to ASS '&HAABBGGRR'."""
    value = hex_colour.lstrip('#')
    if not re.fullmatch(r'[0-9A-Fa-f]{6}', value):
        value = 'FFFFFF'
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f'&H{alpha:02X}{b}{g}{r}'.upper()


def safe_font(name):
    return re.sub(r'[^A-Za-z0-9 \-]', '', name or '')[:40] or 'Arial'


def caption_text(text):
    return text.replace('\\', '').replace('{', '').replace('}', '')


def build_captions(words, layout, caption_style, title=None, title_seconds=3.0,
                   font='Arial Black', word_colour='#FFD400', phrase_colour='#FFFFFF'):
    """Return ASS subtitle text for the narration timings."""
    font, word_c, phrase_c = safe_font(font), ass_colour(word_colour), ass_colour(phrase_colour)
    width, height = SIZES[layout]
    merged = []
    for word in words:
        if not re.search(r'\w', word['word']) and merged:
            merged[-1] = {**merged[-1], 'word': merged[-1]['word'] + word['word'], 'end': word['end']}
        else:
            merged.append(dict(word))
    if layout == 'landscape':
        caption_style = 'phrases'  # word-by-word pop captions are a Shorts style
    limit = (4, 30) if layout == 'vertical' else (8, 52)
    phrases, current = [], []
    for word in merged:
        current.append(word)
        text = ' '.join(w['word'] for w in current)
        if len(current) >= limit[0] or len(text) >= limit[1] or re.search(r'[.!?]$', word['word']):
            phrases.append(current)
            current = []
    if current:
        phrases.append(current)
    if caption_style == 'words':
        phrases = [[word] for word in merged]
        default = f'Style: Default,{font},112,{word_c},{word_c},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,10,2,5,110,110,0,1'
        position = r'{\pos(540,960)\fscx92\fscy92\t(0,65,\fscx100\fscy100)}'
    elif layout == 'vertical':
        default = f'Style: Default,{font},72,{phrase_c},{phrase_c},&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,5,110,150,0,1'
        position = r'{\pos(540,1000)}'
    else:
        default = f'Style: Default,{font},64,{phrase_c},{phrase_c},&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,2,160,160,80,1'
        position = ''
    title_size = 74 if layout == 'vertical' else 78
    title_style = (f'Style: Title,{font},{title_size},&H00FFFFFF,&H00FFFFFF,&H18161616,&H18161616,'
                   f'-1,0,0,0,100,100,0,0,3,26,0,8,90,90,0,1')
    header = f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{default}
{title_style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    if title and title_seconds > 0:
        top = 330 if layout == 'vertical' else 150
        fade = r'{\fad(150,250)\pos(%d,%d)}' % (width // 2, top)
        events.append(f'Dialogue: 1,{ass_time(0)},{ass_time(title_seconds)},Title,,0,0,0,,{fade}{caption_text(title)}')
    for phrase in phrases:
        start, end = phrase[0]['start'], phrase[-1]['end']
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{position}"
                      f"{caption_text(' '.join(w['word'] for w in phrase))}")
    return header + '\n'.join(events) + '\n', len(phrases)


def video_filter(layout, background_size, captions_name, duration, progress_bar, grade='none'):
    width, height = SIZES[layout]
    cover = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1'
    portrait_source = background_size and background_size[1] > background_size[0]
    # Drop to 30 fps first so every later filter handles half the frames of a 60 fps source.
    if layout == 'landscape' and portrait_source:
        # Vertical clip in a horizontal frame: a blurred fill behind the sharp clip.
        # Blurring a small copy and scaling it up looks the same and is ~7x faster.
        graph = ('[0:v]fps=30,split[a][b];'
                 '[a]scale=240:135:force_original_aspect_ratio=increase,crop=240:135,boxblur=4:1,'
                 f'scale={width}:{height},eq=brightness=-0.12[back];'
                 f'[b]scale=-2:{height},setsar=1[front];[back][front]overlay=(W-w)/2:0')
    else:
        graph = f'[0:v]fps=30,{cover}'
    if GRADE_FILTERS.get(grade):
        graph += ',' + GRADE_FILTERS[grade]
    graph += f',ass={captions_name}'
    if progress_bar:
        # drawbox reads its width once, so the bar is a strip that slides in instead.
        bar = 12 if layout == 'vertical' else 8
        graph += (f'[base];color=c=0xFFD400:s={width}x{bar}:r=30[bar];'
                  f"[base][bar]overlay=x='-w+w*min(t/{duration:.3f},1)':y=H-h:eval=frame")
    return graph + '[v]'


def audio_filter(music_volume, has_music):
    voice = '[1:a]aresample=48000,aformat=channel_layouts=stereo'
    if not has_music:
        return voice + ',loudnorm=I=-14:TP=-1.5:LRA=11[a]'
    # Gentle ducking: music dips under speech without pumping back up in every pause.
    return (f'{voice},asplit[v1][v2];'
            f'[2:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_volume:.3f}[m];'
            f'[m][v1]sidechaincompress=threshold=0.05:ratio=4:attack=20:release=600[duck];'
            f'[v2][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]')


_ENCODER = None


def pick_encoder(choice='auto'):
    """NVIDIA/Intel/Apple hardware encoder when it works on this machine, else libx264."""
    global _ENCODER
    if choice != 'auto':
        return choice
    if _ENCODER:
        return _ENCODER
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    listed = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True, text=True, errors='replace').stdout
    for name in ('h264_nvenc', 'h264_videotoolbox', 'h264_qsv', 'h264_amf'):
        if name not in listed:
            continue
        test = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                               'color=black:s=256x256:d=0.1', '-c:v', name, '-f', 'null', '-'],
                              capture_output=True)
        if test.returncode == 0:
            _ENCODER = name
            return name
    _ENCODER = 'libx264'
    return _ENCODER


def encoder_args(encoder):
    return {
        'h264_nvenc': ['-c:v', 'h264_nvenc', '-preset', 'p5', '-rc', 'vbr', '-cq', '21', '-b:v', '0'],
        'h264_videotoolbox': ['-c:v', 'h264_videotoolbox', '-q:v', '65'],
        'h264_qsv': ['-c:v', 'h264_qsv', '-global_quality', '21'],
        'h264_amf': ['-c:v', 'h264_amf', '-quality', 'quality', '-rc', 'cqp', '-qp_i', '21', '-qp_p', '21'],
    }.get(encoder, ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caption-style', choices=['phrases', 'words'], default='phrases')
    parser.add_argument('--narration', type=Path, required=True, help='Folder written by narrate.py')
    parser.add_argument('--background', type=Path, default=ROOT / 'backgrounds/background_000.mp4')
    parser.add_argument('--destination', type=Path, default=ROOT / 'videos' / 'manual')
    parser.add_argument('--name', default='story_short')
    parser.add_argument('--filename', help='Exact output file name (overrides --name and style suffix)')
    parser.add_argument('--format', choices=sorted(SIZES), default='vertical')
    parser.add_argument('--start', type=float, help='Background start time in seconds (default: random)')
    parser.add_argument('--title-card', help='Text shown in a box during the first seconds (the hook)')
    parser.add_argument('--title-seconds', type=float, default=3.0)
    parser.add_argument('--progress-bar', action='store_true')
    parser.add_argument('--music', type=Path, help='Folder of music tracks; one is picked at random')
    parser.add_argument('--music-volume', type=float, default=0.12)
    parser.add_argument('--font', default='Arial Black')
    parser.add_argument('--word-color', default='#FFD400')
    parser.add_argument('--phrase-color', default='#FFFFFF')
    parser.add_argument('--grade', choices=sorted(GRADE_FILTERS), default='none')
    parser.add_argument('--encoder', default='auto', help='auto, libx264, h264_nvenc, h264_videotoolbox, h264_qsv, h264_amf')
    args = parser.parse_args()
    narration = args.narration.resolve()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    words = json.loads((narration / 'timings.json').read_text(encoding='utf-8'))
    duration = json.loads((narration / 'metadata.json').read_text(encoding='utf-8'))['duration_seconds']
    background = args.background.resolve()

    ass, phrase_count = build_captions(words, args.format, args.caption_style, args.title_card, args.title_seconds,
                                       args.font, args.word_color, args.phrase_color)
    suffix = '_yellow_words' if args.caption_style == 'words' and args.format == 'vertical' else ''
    output = destination / (args.filename or f'{args.name}{suffix}.mp4')
    # A plain file name: commas, quotes or brackets would break FFmpeg's filter syntax.
    captions = destination / (re.sub(r'[^A-Za-z0-9_-]', '_', output.stem) + '_captions.ass')
    captions.write_text(ass, encoding='utf-8')
    start = args.start if args.start is not None else background_offset(background, duration)
    track = pick_music(args.music.resolve() if args.music else None) if args.music_volume > 0 else None
    encoder = pick_encoder(args.encoder)
    partial = output.with_name(output.name + '.partial')

    inputs = ['-stream_loop', '-1', '-ss', f'{start:.2f}', '-i', str(background),
              '-i', str(narration / 'narration.wav')]
    if track:
        inputs += ['-stream_loop', '-1', '-ss', f'{background_offset(track, duration):.2f}', '-i', str(track)]
    graph = video_filter(args.format, video_size(background), captions.name, duration, args.progress_bar, args.grade)
    graph += ';' + audio_filter(args.music_volume, bool(track))

    def command(chosen):
        return [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y', *inputs,
                '-filter_complex', graph, '-map', '[v]', '-map', '[a]',
                '-t', f'{duration:.3f}', *encoder_args(chosen),
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
                '-movflags', '+faststart', '-f', 'mp4', str(partial)]

    # Render under a temporary name; a crash never leaves a file that looks finished.
    try:
        subprocess.run(command(encoder), cwd=destination, check=True)
    except subprocess.CalledProcessError:
        if encoder == 'libx264':
            partial.unlink(missing_ok=True)
            raise
        print(f'{encoder} failed; retrying with the CPU encoder.', flush=True)
        encoder = 'libx264'
        try:
            subprocess.run(command(encoder), cwd=destination, check=True)
        except subprocess.CalledProcessError:
            partial.unlink(missing_ok=True)
            raise
    os.replace(partial, output)
    extras = ', '.join(filter(None, [args.format, encoder, f'music {track.name}' if track else '',
                                     'title card' if args.title_card else '',
                                     'progress bar' if args.progress_bar else '']))
    print(f'Saved {output}; {phrase_count} caption phrases; {duration:.3f} seconds; '
          f'background from {start:.1f}s; {extras}', flush=True)


if __name__ == '__main__':
    main()
