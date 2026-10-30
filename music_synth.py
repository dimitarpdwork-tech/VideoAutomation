"""Original background music, composed in code: no licences, no Content ID claims.

  story_music  slow, dark background music for the narration: soft minor-key chord
               pads, a low bass and sparse echoing piano notes.
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


# A slow minor-key progression, 8 seconds per chord: A minor, F, D minor, E (the E major
# chord pulls back to A minor, so the loop never quite settles). Semitones from middle C.
CHORDS = [(-27, [-3, 0, 4]), (-31, [-7, -3, 0]), (-34, [-10, -7, -3]), (-32, [-8, -4, -1])]
CHORD_SECONDS = 8.0
# Sparse, echoing piano notes: (seconds into the loop, semitones from middle C).
PIANO = [(1.0, 16), (5.2, 12), (9.4, 9), (13.1, 12), (17.6, 14), (21.0, 17), (25.4, 11), (29.2, 8)]


def _tone(semitones):
    return 261.63 * 2 ** (semitones / 12)


def story_drone(seed=7):
    """Dark, slow background music: soft chord pads, a low bass, sparse echoing piano notes."""
    rng = random.Random(seed)
    seconds = CHORD_SECONDS * len(CHORDS)
    total = int((seconds + FADE + 4) * RATE)
    out = [0.0] * total
    tau = 2 * math.pi / RATE
    for index, (bass, notes) in enumerate(CHORDS):
        start = index * CHORD_SECONDS
        length = CHORD_SECONDS + 3.0                     # each chord rings into the next one
        first = int(start * RATE)
        voices = [(_tone(bass), 0.55, 0.0)] + [(_tone(n) * detune, 0.16, rng.random() * 6)
                                                for n in notes for detune in (0.9994, 1.0006)]
        for i in range(int(length * RATE)):
            t = i / RATE
            # Slow swell in, long fade out: pads, not plucks.
            envelope = min(1.0, t / 2.5) * (min(1.0, (length - t) / 3.0) if t > length - 3.0 else 1.0)
            breath = 0.85 + 0.15 * math.sin(2 * math.pi * t / 5.5)
            value = 0.0
            for frequency, level, phase in voices:
                value += level * math.sin(tau * frequency * i + phase)
            target = first + i
            if target < total:
                out[target] += value * envelope * breath
    for at, pitch in PIANO:
        frequency, first = _tone(pitch), int(at * RATE)
        for echo, level in ((0.0, 0.32), (0.42, 0.12), (0.84, 0.05)):
            begin = first + int(echo * RATE)
            for i in range(int(4.0 * RATE)):
                if begin + i >= total:
                    break
                t = i / RATE
                envelope = min(1.0, i / 90) * math.exp(-t * 1.4)
                out[begin + i] += level * envelope * (math.sin(tau * frequency * i) + 0.35 * math.sin(tau * 2 * frequency * i)
                                                      + 0.1 * math.sin(tau * 3 * frequency * i))
    # The tail of the last chord and notes rings into the loop start.
    length = int(seconds * RATE)
    for i in range(total - length):
        out[i] += out[length + i]
    return out[:length]


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
    drone, box = folder / 'story_music.wav', folder / 'host_box.wav'
    if not drone.is_file():
        _write(drone, story_drone())
    if not box.is_file():
        _write(box, host_box())
    return drone, box


if __name__ == '__main__':
    from channel_config import SHARED
    target = SHARED / 'music'
    for path in (target / 'story_music.wav', target / 'host_box.wav'):
        path.unlink(missing_ok=True)
    for path in ensure(target):
        print(path)
