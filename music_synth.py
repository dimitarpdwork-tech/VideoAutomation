"""Original background music, composed in code: no licences, no Content ID claims.

  story_drone  a very low, slowly breathing drone with a faint high tone that comes
               and goes: tension under the narration, never a melody to follow.
  host_box     a bright little music-box tune for the channel host's intro and
               sign-off: cheerful, with a few notes ever so slightly out of tune.

Both are seamless loops, saved once in output/shared/music/ and reused.
Your own tracks always win: put them in the channel folder's music/story and
music/host folders (WAV, MP3, M4A, OGG or FLAC).

    python music_synth.py      # (re)create both and print where they are
"""
import math
import random
import struct
import wave
from pathlib import Path

RATE = 24000
FADE = 2.0   # seconds overlapped at the loop point, so the loop has no seam


def _write(path, samples):
    peak = max(1e-9, max(abs(s) for s in samples))
    scale = 0.6 * 32767 / peak
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.part')
    with wave.open(str(temporary), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        audio.writeframes(b''.join(struct.pack('<h', int(s * scale)) for s in samples))
    temporary.replace(path)
    return path


def _loop(samples, seconds):
    """Cross-fade the extra tail into the start, giving exactly `seconds` that loop cleanly."""
    length, overlap = int(seconds * RATE), int(FADE * RATE)
    body = samples[:length]
    for i in range(overlap):
        mix = i / overlap
        body[i] = body[i] * mix + samples[length + i] * (1 - mix)
    return body


def story_drone(seconds=48.0, seed=7):
    rng = random.Random(seed)
    total = int((seconds + FADE) * RATE)
    tau = 2 * math.pi / RATE
    # (frequency, level, breathing period in seconds, phase)
    layers = [(55.0, 1.0, 24.0, 0.0), (55.18, 0.35, 31.0, 1.3), (82.4, 0.45, 19.0, 2.1),
              (110.2, 0.25, 27.0, 0.7), (164.6, 0.12, 13.0, 1.9)]
    high = (932.3, 0.035, 16.0)   # a thin tone, a tritone-ish shimmer above, fading in and out
    out, noise = [0.0] * total, 0.0
    for n in range(total):
        t = n / RATE
        value = 0.0
        for frequency, level, period, phase in layers:
            value += level * (0.65 + 0.35 * math.sin(2 * math.pi * t / period + phase)) * math.sin(tau * frequency * n)
        swell = max(0.0, math.sin(2 * math.pi * t / high[2])) ** 3
        value += high[1] * swell * math.sin(tau * high[0] * n + 0.3 * math.sin(2 * math.pi * t * 0.2))
        noise = 0.995 * noise + 0.005 * (rng.random() * 2 - 1)   # dark rumble: heavily filtered noise
        value += noise * 2.2
        out[n] = value
    return _loop(out, seconds)


# An original tune: (semitones above middle C, beats). None is a rest. 100 bpm, 4 bars.
TUNE = [(12, .5), (16, .5), (19, .5), (16, .5), (24, .5), (19, .5), (16, .5), (19, .5),
        (17, .5), (21, .5), (24, .5), (21, .5), (19, .5), (16, .5), (12, .5), (16, .5),
        (14, .5), (17, .5), (21, .5), (17, .5), (11, .5), (14, .5), (19, .5), (17, .5),
        (16, .5), (19, .5), (24, 1), (12, 1), (None, 1)]
BASS = [(-12, 4), (-7, 4), (-5, 4), (-12, 4)]
BPM = 100


def _note(out, start, semitones, beats, level, detune=0.0):
    frequency = 261.63 * 2 ** ((semitones + detune) / 12)
    first, length = int(start * RATE), int(min(beats * 60 / BPM * 2.5, 2.5) * RATE)
    tau = 2 * math.pi * frequency / RATE
    for i in range(length):
        if first + i >= len(out):
            break
        t = i / RATE
        envelope = min(1.0, i / 60) * math.exp(-t * 3.2)
        # Music-box tine: a pure tone plus a quick metallic overtone.
        out[first + i] += level * envelope * (math.sin(tau * i) + 0.35 * math.exp(-t * 12) * math.sin(tau * 4.02 * i)
                                              + 0.12 * math.sin(tau * 2 * i))


def host_box(seed=3):
    beat = 60 / BPM
    seconds = 16 * beat
    out = [0.0] * int((seconds + FADE) * RATE + RATE * 3)
    position = 0.0
    for number, (pitch, beats) in enumerate(TUNE):
        if pitch is not None:
            # Every fifth note is a few cents flat: cheerful, but not quite right.
            _note(out, position, pitch, beats, 0.5, detune=-0.18 if number % 5 == 4 else 0.0)
        position += beats * beat
    position = 0.0
    for pitch, beats in BASS:
        _note(out, position, pitch, beats, 0.3)
        position += beats * beat
    # The tail of the last notes rings into the loop start.
    tail = int(seconds * RATE)
    for i in range(len(out) - tail):
        out[i] += out[tail + i]
    return out[:int(seconds * RATE)]


def ensure(folder):
    """Paths of the two generated tracks, creating any that are missing."""
    folder = Path(folder)
    drone, box = folder / 'story_drone.wav', folder / 'host_box.wav'
    if not drone.is_file():
        _write(drone, story_drone())
    if not box.is_file():
        _write(box, host_box())
    return drone, box


if __name__ == '__main__':
    from channel_config import SHARED
    target = SHARED / 'music'
    for path in (target / 'story_drone.wav', target / 'host_box.wav'):
        path.unlink(missing_ok=True)
    for path in ensure(target):
        print(path)
