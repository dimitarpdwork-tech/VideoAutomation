"""Render a narration over a background clip or a still image, with automatic captions.

Vertical (1080x1920) for Shorts or landscape (1920x1080) for full videos.
With --image, one photo is slowly panned (a "Ken Burns" move) under a soft
vignette: the classic look of narrated horror and sleep channels.
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
    """A track: the file itself, or a random one from a folder."""
    if folder and Path(folder).is_file() and Path(folder).suffix.lower() in MUSIC_TYPES:
        return Path(folder)
    if not folder or not Path(folder).is_dir():
        return None
    tracks = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in MUSIC_TYPES)
    return rng.choice(tracks) if tracks else None


def _grade(contrast=1.0, lift=0, saturation=1.0, blue=0, red=0):
    """One lookup table in YUV: contrast, saturation and a colour tint.

    About 4x faster than FFmpeg's colorbalance, which converts every frame to RGB and back.
    """
    def chroma(shift):
        return f"'clip((val-128)*{saturation}+128{shift:+d},0,255)'"
    return f"lutyuv=y='clip((val-128)*{contrast}+128{lift:+d},0,255)':u={chroma(blue)}:v={chroma(red)}"


GRADE_FILTERS = {
    'none': '',
    'cold': _grade(contrast=1.05, saturation=0.85, blue=7, red=-5),
    'warm': _grade(saturation=0.95, blue=-6, red=6),
    'faded': _grade(contrast=0.9, lift=8, saturation=0.8),
    'noir': _grade(contrast=1.2, saturation=0),
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
                   font='Arial Black', word_colour='#FFD400', phrase_colour='#FFFFFF',
                   end_text=None, end_seconds=4.0, duration=None, host_spans=None, host_name=None):
    """Return ASS subtitle text for the narration timings.

    end_text: a card for the last end_seconds (e.g. "Part 2 is on my profile").
    host_spans: [start, end] seconds where the channel host speaks: their words get
    their own quieter style, and host_name is shown as a card, so nobody mistakes
    the host for the story's narrator.
    """
    host_spans = host_spans or []

    def hosting(seconds):
        return any(a - 0.05 <= seconds <= b + 0.05 for a, b in host_spans)
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
        if current and hosting(word['start']) != hosting(current[-1]['start']):
            phrases.append(current)
            current = []
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
    host_style = (f'Style: Host,{font},{56 if layout == "landscape" else 64},&H00D8D2C8,&H00D8D2C8,&H00101010,&H80000000,'
                  f'0,-1,0,0,100,100,1,0,1,3,2,2,160,160,{80 if layout == "landscape" else 520},1')
    card_style = (f'Style: Card,{font},{96 if layout == "landscape" else 88},&H00F0F0F0,&H00F0F0F0,&H00000000,&H00000000,'
                  f'-1,0,0,0,100,100,14,0,1,0,6,5,60,60,0,1')
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
{host_style}
{card_style}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    if title and title_seconds > 0:
        top = 330 if layout == 'vertical' else 150
        fade = r'{\fad(150,250)\pos(%d,%d)}' % (width // 2, top)
        events.append(f'Dialogue: 1,{ass_time(0)},{ass_time(title_seconds)},Title,,0,0,0,,{fade}{caption_text(title)}')
    if end_text and duration and end_seconds > 0:
        top = 330 if layout == 'vertical' else 150
        fade = r'{\fad(250,0)\pos(%d,%d)}' % (width // 2, top)
        events.append(f'Dialogue: 1,{ass_time(max(0, duration - end_seconds))},{ass_time(duration + 1)},Title,,0,0,0,,'
                      f'{fade}{caption_text(end_text)}')
    if host_name:
        for a, b in host_spans:
            place = r'{\fad(700,500)\pos(%d,%d)}' % (width // 2, round(height * (0.14 if layout == 'landscape' else 0.1)))
            events.append(f'Dialogue: 2,{ass_time(max(0, a - 0.6))},{ass_time(b + 0.5)},Card,,0,0,0,,'
                          f'{place}{caption_text(host_name.upper())}')
    for phrase in phrases:
        start, end = phrase[0]['start'], phrase[-1]['end']
        host = hosting(start)
        events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{'Host' if host else 'Default'},,0,0,0,,"
                      f"{'' if host else position}{caption_text(' '.join(w['word'] for w in phrase))}")
    return header + '\n'.join(events) + '\n', len(phrases)


IMAGE_FPS = {'vertical': 30, 'landscape': 30}
PUSH_IN = {'vertical': 1.18, 'landscape': 1.25}  # how far the camera moves in over the whole video


def prepare_image(image, layout, destination, rng=random):
    """Crop the photo to the frame's exact shape and size, and draw a vignette.

    Returns (image path, size, vignette path). Doing this here, not in FFmpeg,
    keeps the per-frame work to one zoom and an overlay (FFmpeg's own vignette
    filter doubled the render time).
    """
    from PIL import Image
    width, height = SIZES[layout]
    token = rng.randrange(10**8)
    target = (width, height)
    with Image.open(image) as picture:
        picture = picture.convert('RGB')
        scale = max(target[0] / picture.width, target[1] / picture.height)
        resized = picture.resize((max(target[0], round(picture.width * scale)), max(target[1], round(picture.height * scale))),
                                 Image.LANCZOS)
        left, top = (resized.width - target[0]) // 2, (resized.height - target[1]) // 2
        prepared = destination / f'_bg_{token}.jpg'
        from PIL import ImageFilter
        resized.crop((left, top, left + target[0], top + target[1])).filter(
            ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2)).save(prepared, quality=95)
    # Transparent centre, edges darkened by up to ~55%.
    gradient = Image.radial_gradient('L').resize((width, height), Image.BILINEAR)
    shade = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    shade.putalpha(gradient.point(lambda v: max(0, min(140, int((v - 105) * 1.1)))))
    vignette = destination / f'_vignette_{token}.png'
    shade.save(vignette)
    return prepared, target, vignette


def image_pan(layout, size, duration=60.0, rng=random):
    """A slow, steady push forward into the photo, as if walking toward it.

    The zoom grows exponentially, so the move feels the same speed from start to
    end, and stays centred: no sideways drift, no back-and-forth.
    """
    frames = max(1, round(duration * IMAGE_FPS[layout]))
    # FFmpeg's zoompan and crop move in whole pixels, which judders on a slow move;
    # perspective samples between pixels, so every frame moves by the same tiny step.
    shrink = f'pow({PUSH_IN[layout]},-in/{frames})'
    lo, hi = f'(1-{shrink})', f'(1+{shrink})'
    corners = [('W', lo), ('H', lo), ('W', hi), ('H', lo), ('W', lo), ('H', hi), ('W', hi), ('H', hi)]
    points = ':'.join(f"{axis}{i // 2}='{side}/2*{edge}'" for i, (side, edge) in enumerate(corners)
                      for axis in ['xy'[i % 2]])
    return f'perspective={points}:interpolation=linear:eval=frame,setsar=1'


SCENE_FADE = 0.6


def default_host_scene(layout, destination, rng=random):
    """A closed door in a dark room, light leaking around its edges: the channel's scene when none is supplied."""
    from PIL import Image, ImageDraw, ImageFilter
    width, height = SIZES[layout]
    unit = min(width, height)
    door_w = round(unit * (0.30 if layout == 'landscape' else 0.42))
    door_h = round(door_w * 1.85)
    left = (width - door_w) // 2
    floor = round(height * (0.84 if layout == 'landscape' else 0.62))
    top = floor - door_h
    scene = Image.new('RGB', (width, height), (5, 6, 8))
    # Light leaking around the frame, strongest under the door, spreading across the floor.
    light = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(light)
    draw.rectangle((left - 6, top - 6, left + door_w + 6, floor), outline=150, width=5)
    draw.rectangle((left, floor - 10, left + door_w, floor), fill=255)
    sharp = light.filter(ImageFilter.GaussianBlur(1.5))
    spill = Image.new('L', (width, height), 0)
    ImageDraw.Draw(spill).ellipse((left - door_w * 0.5, floor - unit * 0.01, left + door_w * 1.5, floor + unit * 0.12), fill=70)
    spill.paste(light, (0, 0), light)
    halo = spill.filter(ImageFilter.GaussianBlur(unit * 0.045))
    combined = Image.eval(Image.blend(halo, sharp, 0.35), lambda v: min(255, int(v * 1.5)))
    scene = Image.composite(Image.new('RGB', (width, height), (255, 196, 120)), scene, combined)
    # The door itself, a shade lighter than the wall so its shape reads in the dark.
    door = ImageDraw.Draw(scene)
    door.rectangle((left, top, left + door_w, floor - 10), fill=(13, 13, 15))
    knob = (left + door_w * 0.84, top + door_h * 0.55)
    door.ellipse((knob[0] - 7, knob[1] - 7, knob[0] + 7, knob[1] + 7), fill=(60, 52, 40))
    path = destination / f'_scene_{rng.randrange(10**8)}.jpg'
    scene.save(path, quality=95)
    return path


def host_scene_graph(index, layout, spans, is_video):
    """Filters that turn input `index` into one faded, flickering stream per host span,
    overlaid on [story] only while the host speaks. Returns (graph, output label)."""
    width, height = SIZES[layout]
    cover = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1'
    source = f'fps=30,{cover}' if is_video else \
        f'format=yuv420p,loop=loop=-1:size=1:start=0,setpts=N/30/TB,{cover}'
    # A light that is not quite steady, and film grain, so the scene feels alive.
    flicker = "eq=brightness='-0.07*gt(sin(t*13)*sin(t*7.7)*sin(t*2.3)\\,0.45)':eval=frame,noise=alls=9:allf=t"
    labels = [f's{n}' for n in range(len(spans))]
    graph = f';[{index}:v]{source},{flicker},format=yuv420p' + (f',split={len(spans)}' if len(spans) > 1 else '') + \
        ''.join(f'[{label}]' for label in labels)
    current = 'story'
    for n, (label, (a, b)) in enumerate(zip(labels, spans)):
        start, end = max(0.0, a - SCENE_FADE), b + SCENE_FADE
        graph += (f';[{label}]fade=t=in:st={start:.3f}:d={SCENE_FADE},fade=t=out:st={end - SCENE_FADE:.3f}:d={SCENE_FADE}[f{n}]'
                  f";[{current}][f{n}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'[h{n}]")
        current = f'h{n}'
    return graph, current


def video_filter(layout, background_size, captions_name, duration, progress_bar, grade='none', image_pan_filter=None,
                 vignette_input=None, scene=None):
    """scene: (input index, host spans, is video) to cut to the channel's scene while the host speaks."""
    width, height = SIZES[layout]
    cover = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1'
    portrait_source = background_size and background_size[1] > background_size[0]
    # Drop to 30 fps first so every later filter handles half the frames of a 60 fps source.
    if image_pan_filter:
        # One decoded frame, repeated (decoding the photo for every frame was the slow part).
        fps = IMAGE_FPS[layout]
        still = f'format=yuv420p,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB'
        graph = f'[0:v]{still},{image_pan_filter}'
        if vignette_input is not None:
            graph += (f'[pan];[{vignette_input}:v]format=yuva420p,loop=loop=-1:size=1:start=0,setpts=N/{fps}/TB[shade];'
                      '[pan][shade]overlay=0:0')
    elif layout == 'landscape' and portrait_source:
        # Vertical clip in a horizontal frame: a blurred fill behind the sharp clip.
        # Blurring a small copy and scaling it up looks the same and is ~7x faster.
        graph = ('[0:v]fps=30,split[a][b];'
                 '[a]scale=240:135:force_original_aspect_ratio=increase,crop=240:135,boxblur=4:1,'
                 f'scale={width}:{height},eq=brightness=-0.12[back];'
                 f'[b]scale=-2:{height},setsar=1[front];[back][front]overlay=(W-w)/2:0')
    else:
        graph = f'[0:v]fps=30,{cover}'
    if scene and scene[1]:
        extra, label = host_scene_graph(scene[0], layout, scene[1], scene[2])
        graph += '[story]' + extra + f';[{label}]null'
    if GRADE_FILTERS.get(grade):
        graph += ',' + GRADE_FILTERS[grade]
    graph += f',ass={captions_name}'
    if progress_bar:
        # drawbox reads its width once, so the bar is a strip that slides in instead.
        bar = 12 if layout == 'vertical' else 8
        graph += (f'[base];color=c=0xFFD400:s={width}x{bar}:r=30[bar];'
                  f"[base][bar]overlay=x='-w+w*min(t/{duration:.3f},1)':y=H-h:eval=frame")
    return graph + '[v]'


def _pitch(ratio):
    """Lower (ratio < 1) or raise the pitch without changing the length, so captions stay in sync."""
    return f'asetrate=48000*{ratio},aresample=48000,atempo={1 / ratio:.5f}'


# A channel's signature sound, applied to the narration of every video.
VOICE_CHARACTERS = {
    'natural': 'As recorded',
    'deep': 'Deep & close: a little lower, warmer, right next to you',
    'uncanny': 'Uncanny: lower, with a faint second voice an octave below',
    'tape': 'Old tape: narrow, faint hiss and wobble, like a found recording',
    'room': 'Empty room: a small, cold room around the voice',
}


def voice_character(character, source='[1:a]', output='[voice]'):
    """Filter graph from the narration input to a labelled, treated voice."""
    base = f'{source}aresample=48000,aformat=channel_layouts=stereo'
    if character == 'deep':
        return (f'{base},{_pitch(0.94)},bass=g=3:f=110:w=0.7,'
                f'acompressor=threshold=0.125:ratio=2.5:attack=10:release=250:makeup=1.4{output}')
    if character == 'uncanny':
        return (f'{base},{_pitch(0.95)},asplit=2[u1][u2];'
                f'[u2]{_pitch(0.5)},lowpass=f=700,volume=0.16[undertone];'
                f'[u1][undertone]amix=inputs=2:duration=first:normalize=0,aecho=0.9:0.5:18:0.12{output}')
    if character == 'tape':
        return (f'{base},highpass=f=200,lowpass=f=4000,vibrato=f=0.7:d=0.02,acompressor=threshold=0.2:ratio=3[tape];'
                f'anoisesrc=color=pink:amplitude=0.006:sample_rate=48000,aformat=channel_layouts=stereo[hiss];'
                f'[tape][hiss]amix=inputs=2:duration=first:normalize=0{output}')
    if character == 'room':
        return f'{base},aecho=0.8:0.55:32|61|97:0.22|0.14|0.08{output}'
    return base + output


# Replaces any NaN or infinite sample with silence. One bad sample from a filter is enough for
# loudnorm to spread NaN through the rest of the track and for the AAC encoder to refuse it.
CLEAN = ("aeval=exprs='if(isnan(val(0))+isinf(val(0)),0,val(0))|if(isnan(val(1))+isinf(val(1)),0,val(1))',"
         "aformat=sample_fmts=fltp:channel_layouts=stereo")
LOUDNESS = 'loudnorm=I=-14:TP=-1.5:LRA=11'


MUSIC_FADE = 1.2        # seconds the story music and the host music take to swap
HOST_MUSIC_GAIN = 2.0   # the host's music sits a little higher than the story's tension bed


def fade_lead(start):
    """How early the host music starts before the host's first word."""
    return min(MUSIC_FADE, start)


def music_envelopes(spans, fade=MUSIC_FADE):
    """FFmpeg volume expressions (story, host): the story music fades out around each
    host span while the host music fades in, and back."""
    if not spans:
        return '1', '0'
    factors = [f"(1-clip(min(t-{a - fade:.3f}\\,{b + fade:.3f}-t)/{fade}\\,0\\,1))" for a, b in spans]
    story = '*'.join(factors)
    return story, f'1-{story}'


END_HOLD, END_FADE = 3.5, 2.5   # seconds of music after the last word, and the fade to black


def audio_filter(music_volume, has_music, character='natural', music_input=2, host_input=None, spans=(), fade_out_at=None):
    """Voice (with its character), then the music ducked under it, then loudness.

    music_input: the story music's input index (when has_music); host_input: the
    host music's input, faded in only during `spans` (the host's lines).
    """
    voice = voice_character(character)
    streams, music = [], ''
    story_env, host_env = music_envelopes(spans if host_input is not None else ())
    if has_music:
        music += (f";[{music_input}:a]aresample=48000,aformat=channel_layouts=stereo,volume={music_volume:.3f},"
                  f"volume='{story_env}':eval=frame[ms]")
        streams.append('[ms]')
    if host_input is not None and spans:
        # The tune starts from its first note each time the host speaks.
        pieces = ''.join(f'[h{n}]' for n in range(len(spans)))
        music += (f";[{host_input}:a]aresample=48000,aformat=channel_layouts=stereo,"
                  f"volume={music_volume * HOST_MUSIC_GAIN:.3f},asplit={len(spans)}{pieces}")
        for n, (a, b) in enumerate(spans):
            start = max(0.0, a - fade_lead(a))
            music += (f';[h{n}]atrim=0:{b - start + MUSIC_FADE + 0.5:.3f},asetpts=PTS-STARTPTS,'
                      f'adelay={round(start * 1000)}:all=1,apad[hp{n}]')
        joined = ''.join(f'[hp{n}]' for n in range(len(spans)))
        music += (f";{joined}amix=inputs={len(spans)}:duration=first:normalize=0," if len(spans) > 1 else f';{joined}') + \
            f"volume='{host_env}':eval=frame[mh]"
        streams.append('[mh]')
    pad = ',apad' if fade_out_at else ''      # silence after the last word, for the ending
    end = f',afade=t=out:st={fade_out_at:.3f}:d={END_FADE}' if fade_out_at else ''
    if not streams:
        return f'{voice};[voice]{CLEAN}{pad},{LOUDNESS},{CLEAN}{end}[a]'
    graph = f'{voice};[voice]{CLEAN}{pad},asplit[v1][v2]' + music
    if len(streams) > 1:
        graph += f";{''.join(streams)}amix=inputs={len(streams)}:duration=first:normalize=0[m]"
    else:
        graph += f';{streams[0]}anull[m]'
    # Gentle ducking: music dips under speech without pumping back up in every pause.
    return (graph + ';[m][v1]sidechaincompress=threshold=0.05:ratio=4:attack=20:release=600[duck];'
            f'[v2][duck]amix=inputs=2:duration=first:normalize=0,{LOUDNESS},{CLEAN}{end}[a]')


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
    parser.add_argument('--image', type=Path, help='A still image to pan instead of a background clip')
    parser.add_argument('--destination', type=Path, default=ROOT / 'videos' / 'manual')
    parser.add_argument('--name', default='story_short')
    parser.add_argument('--filename', help='Exact output file name (overrides --name and style suffix)')
    parser.add_argument('--format', choices=sorted(SIZES), default='vertical')
    parser.add_argument('--start', type=float, help='Background start time in seconds (default: random)')
    parser.add_argument('--title-card', help='Text shown in a box during the first seconds (the hook)')
    parser.add_argument('--title-seconds', type=float, default=3.0)
    parser.add_argument('--end-text', help='Text shown in a box during the last seconds (e.g. "Part 2 on my profile")')
    parser.add_argument('--end-seconds', type=float, default=4.0)
    parser.add_argument('--progress-bar', action='store_true')
    parser.add_argument('--host-scene', type=Path, help="Image or video shown while the channel host speaks")
    parser.add_argument('--host-name', help="Channel name shown while the host speaks")
    parser.add_argument('--music', type=Path, help='Folder of music tracks; one is picked at random')
    parser.add_argument('--music-volume', type=float, default=0.12)
    parser.add_argument('--host-music', type=Path, help="Track (or folder) played while the channel host speaks")
    parser.add_argument('--font', default='Arial Black')
    parser.add_argument('--word-color', default='#FFD400')
    parser.add_argument('--phrase-color', default='#FFFFFF')
    parser.add_argument('--grade', choices=sorted(GRADE_FILTERS), default='none')
    parser.add_argument('--voice-character', choices=sorted(VOICE_CHARACTERS), default='natural')
    parser.add_argument('--encoder', default='auto', help='auto, libx264, h264_nvenc, h264_videotoolbox, h264_qsv, h264_amf')
    args = parser.parse_args()
    narration = args.narration.resolve()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    words = json.loads((narration / 'timings.json').read_text(encoding='utf-8'))
    narration_meta = json.loads((narration / 'metadata.json').read_text(encoding='utf-8'))
    spoken = narration_meta['duration_seconds']
    # Full videos end gently: the music carries on for a few seconds while the picture fades
    # out, instead of the video stopping on the last word. Shorts loop, so they stop cleanly.
    ending = END_HOLD if args.format == 'landscape' else 0.0
    duration = spoken + ending
    host_spans = [span for span in narration_meta.get('host_spans') or [] if span[1] > span[0]]
    background = args.background.resolve()

    ass, phrase_count = build_captions(words, args.format, args.caption_style, args.title_card, args.title_seconds,
                                       args.font, args.word_color, args.phrase_color,
                                       args.end_text, args.end_seconds, duration, host_spans, args.host_name)
    suffix = '_yellow_words' if args.caption_style == 'words' and args.format == 'vertical' else ''
    output = destination / (args.filename or f'{args.name}{suffix}.mp4')
    # A plain file name: commas, quotes or brackets would break FFmpeg's filter syntax.
    captions = destination / (re.sub(r'[^A-Za-z0-9_-]', '_', output.stem) + '_captions.ass')
    captions.write_text(ass, encoding='utf-8')
    prepared = vignette = None
    if args.image:
        prepared, image_size, vignette = prepare_image(args.image.resolve(), args.format, destination)
        start = 0.0
    else:
        start = args.start if args.start is not None else background_offset(background, duration)
    track = pick_music(args.music.resolve() if args.music else None) if args.music_volume > 0 else None
    encoder = pick_encoder(args.encoder)
    partial = output.with_name(output.name + '.partial')

    if prepared:
        inputs = ['-framerate', str(IMAGE_FPS[args.format]), '-i', str(prepared),
                  '-i', str(narration / 'narration.wav')]
    else:
        inputs = ['-stream_loop', '-1', '-ss', f'{start:.2f}', '-i', str(background),
                  '-i', str(narration / 'narration.wav')]
    if track:
        inputs += ['-stream_loop', '-1', '-ss', f'{background_offset(track, duration):.2f}', '-i', str(track)]
    vignette_input = None
    if vignette:
        vignette_input = 3 if track else 2
        inputs += ['-framerate', str(IMAGE_FPS[args.format]), '-i', str(vignette)]
    scene = scene_file = None
    if host_spans:
        scene_file = args.host_scene.resolve() if args.host_scene and args.host_scene.is_file() else \
            default_host_scene(args.format, destination)
        is_video = scene_file.suffix.lower() in ('.mp4', '.mov', '.webm', '.mkv', '.m4v')
        scene = (inputs.count('-i'), host_spans, is_video)
        inputs += (['-stream_loop', '-1', '-i', str(scene_file)] if is_video
                   else ['-framerate', '30', '-i', str(scene_file)])
    host_track = host_input = None
    if host_spans and args.music_volume > 0 and args.host_music:
        host_track = pick_music(args.host_music.resolve())
        if host_track:
            host_input = inputs.count('-i')
            inputs += ['-stream_loop', '-1', '-i', str(host_track)]
    graph = video_filter(args.format, None if prepared else video_size(background), captions.name, duration,
                         args.progress_bar, args.grade, image_pan(args.format, image_size, duration) if prepared else None,
                         vignette_input, scene)
    video_graph = graph

    def command(chosen, character):
        fade = f'fade=t=out:st={duration - END_FADE:.3f}:d={END_FADE}'
        graph_v = video_graph[:-len('[v]')] + f'[vend];[vend]{fade}[v]' if ending else video_graph
        full_graph = graph_v + ';' + audio_filter(args.music_volume, bool(track), character, 2, host_input, host_spans,
                                                   duration - END_FADE if ending else None)
        return [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y', *inputs,
                '-filter_complex', full_graph, '-map', '[v]', '-map', '[a]',
                '-t', f'{duration:.3f}', *encoder_args(chosen),
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
                '-movflags', '+faststart', '-f', 'mp4', str(partial)]

    def silent(path):
        """True if the rendered audio is (near) silent: a broken voice character cleaned into nothing."""
        probe = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-i', str(path), '-map', '0:a',
                                '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True, errors='replace')
        found = re.search(r'mean_volume:\s*(-?[\d.]+|-inf) dB', probe.stderr)
        return bool(found) and (found.group(1) == '-inf' or float(found.group(1)) < -60)

    def attempt(chosen, character):
        """Run FFmpeg; return its error text ('' on success). The error is shown in the log either way."""
        result = subprocess.run(command(chosen, character), cwd=destination, stderr=subprocess.PIPE,
                                text=True, encoding='utf-8', errors='replace')
        if result.stderr.strip():
            print(result.stderr.strip()[-3000:], flush=True)
        return '' if result.returncode == 0 else (result.stderr or f'FFmpeg exit code {result.returncode}')

    # Render under a temporary name; a crash never leaves a file that looks finished.
    character = args.voice_character
    fallback = destination / (output.name + '.voice-fallback')
    fallback.unlink(missing_ok=True)
    try:
        error = attempt(encoder, character)
        if error and character != 'natural' and re.search(r'NaN|Inf|audio frame', error):
            # The voice character produced audio the encoder rejects: keep the video, with the plain voice.
            print(f'The "{character}" voice character produced invalid audio; rendering with the natural voice.', flush=True)
            fallback.write_text(character, encoding='utf-8')
            character = 'natural'
            error = attempt(encoder, character)
        if error and encoder != 'libx264':
            print(f'{encoder} failed; retrying with the CPU encoder.', flush=True)
            encoder = 'libx264'
            error = attempt(encoder, character)
        if not error and character != 'natural' and silent(partial):
            print(f'The "{character}" voice character left the video silent; rendering with the natural voice.', flush=True)
            fallback.write_text(character, encoding='utf-8')
            character = 'natural'
            error = attempt(encoder, character)
        if error:
            partial.unlink(missing_ok=True)
            raise SystemExit(f'Rendering failed: {error.strip().splitlines()[-1][:300]}')
    finally:
        for temporary in (prepared, vignette, scene_file if scene_file and scene_file.name.startswith('_scene_') else None):
            if temporary:
                temporary.unlink(missing_ok=True)
    os.replace(partial, output)
    extras = ', '.join(filter(None, [args.format, encoder, f'image {args.image.name}' if args.image else '', f'music {track.name}' if track else '', f'host music {host_track.name}' if host_track else '',
                                     'title card' if args.title_card else '',
                                     'progress bar' if args.progress_bar else '']))
    print(f'Saved {output}; {phrase_count} caption phrases; {duration:.3f} seconds; '
          + ('' if prepared else f'background from {start:.1f}s; ') + extras, flush=True)


if __name__ == '__main__':
    main()
