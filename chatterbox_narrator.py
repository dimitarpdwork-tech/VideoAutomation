r"""Narrate stories with Chatterbox: a human-sounding voice cloned from a short clip.

Runs in its own environment (.venv-voice; install it with setup_voice.cmd or
./setup_voice.sh). Production starts it once per batch in --serve mode, so the
model loads one time. You can also run it by hand:

    .venv-voice\Scripts\python chatterbox_narrator.py stories\1nspy0i.json --clip voices\my_voice.wav
    .venv-voice\Scripts\python chatterbox_narrator.py --samples

Output matches narrate.py (Kokoro): narration.wav, timings.json (word timings
for captions), script.txt, chunks.json, cleanup.json and metadata.json.

How it works
- The script is cleaned exactly like Kokoro's (shared code in narrate.py).
- Delivery cues in the story ([tense], [whisper], [pause] ...) change how each
  sentence is read; see delivery.py.
- It speaks a sentence or two at a time. Every piece is checked; a piece that
  comes out far too short or too long (skipped or invented words) is spoken
  again, up to three times. If none is right, the best one is kept and the
  video gets a warning in Review.
- Word timings come from a forced aligner (torchaudio MMS_FA), so captions
  follow the voice. If the aligner is unavailable, timings are estimated.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('TQDM_DISABLE', '1')            # no progress-bar spam in the dashboard log
os.environ.setdefault('TRANSFORMERS_VERBOSITY', 'error')

import delivery  # noqa: E402
import narrate   # noqa: E402  (also points HF_HOME at .model-cache)

ROOT = Path(__file__).resolve().parent
VOICES = ROOT / 'voices'
SAMPLES = ROOT / 'output' / 'shared' / 'voice_samples'
CLIP_TYPES = ('.wav', '.mp3', '.flac', '.m4a', '.ogg')
SAMPLE_RATE = 24000
MAX_CHARS = 260          # longer pieces make Chatterbox drift or skip words
PAUSE_SECONDS = 0.9      # [pause]
SOFT_GAP = 0.12          # between pieces that end mid-sentence
ATTEMPTS = 3
# Seconds per spoken word that count as a plausible reading at normal speed.
MIN_SPW, MAX_SPW = 0.16, 1.05
# How each cue shifts expressiveness (Chatterbox "exaggeration") and pacing (cfg_weight:
# lower is slower and more deliberate).
STYLE = {None: (0.0, 0.5), 'tense': (0.25, 0.3), 'whisper': (-0.2, 0.3), 'urgent': (0.4, 0.6), 'calm': (-0.15, 0.45)}
WHISPER_GAIN = 0.5       # about -6 dB: Chatterbox cannot whisper, so hushed lines are quieter
SAMPLE_TEXT = (
    "The Night Shift. I took the job because it paid double and nobody else wanted it. "
    "The building was empty after ten, they said. Just me, the cameras, and the hum of the lights. "
    "[pause] On my third night, the elevator started moving on its own. "
    "[tense] It stopped on the fourth floor, the one that has been sealed since the fire. "
    "I watched the monitor and waited for the doors to open. [pause] "
    "[whisper] When they did, someone on the screen was already looking back at me.")


def log(message):
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Text

def say_numbers(text):
    """Write numbers as words, so the voice and the caption aligner agree."""
    try:
        from num2words import num2words
    except ImportError:
        return text

    def money(match):
        return f'{match.group(1)} dollars'

    def number(match):
        raw = match.group(0)
        digits = re.match(r'[\d,]+(?:\.\d+)?', raw).group(0).replace(',', '')
        try:
            if re.search(r'(?:st|nd|rd|th)$', raw, re.I):
                spoken = num2words(int(digits), to='ordinal')
            elif '.' in digits:
                spoken = num2words(float(digits))
            elif len(digits) == 4 and ',' not in raw and 1100 <= int(digits) <= 2099:
                spoken = num2words(int(digits), to='year')
            else:
                spoken = num2words(int(digits))
        except (ValueError, OverflowError, NotImplementedError):
            return raw
        return spoken.replace(',', '')

    def clock(match):
        hours, minutes = int(match.group(1)), int(match.group(2))
        if hours > 24 or minutes > 59:
            return match.group(0)
        spoken = num2words(hours)
        if minutes:
            spoken += (' oh ' if minutes < 10 else ' ') + num2words(minutes)
        return spoken

    def decade(match):  # "1990s" -> "nineteen nineties", "1800s" -> "eighteen hundreds"
        spoken = num2words(int(match.group(1)), to='year').replace(',', '')
        return spoken[:-1] + 'ies' if spoken.endswith('y') else spoken + 's'

    text = re.sub(r'\b(\d{1,2}):(\d{2})\b', clock, text)
    text = re.sub(r'\b(1[1-9]\d0|20[0-9]0)s\b', decade, text)
    text = re.sub(r'\$(\d[\d,]*(?:\.\d+)?)', money, text)
    text = re.sub(r'(?<=\d)\s?%', ' percent', text)
    return re.sub(r'\d[\d,]*(?:\.\d+)?(?:st|nd|rd|th)?\b', number, text)


def _split_long(sentence, limit):
    if len(sentence) <= limit:
        return [sentence]
    parts, current = [], ''
    for clause in re.split(r'(?<=[,;:])\s+', sentence):
        while len(clause) > limit:  # one enormous clause: cut between words
            cut = clause.rfind(' ', 0, limit)
            cut = cut if cut > 0 else limit
            if current:
                parts.append(current)
                current = ''
            parts.append(clause[:cut].strip())
            clause = clause[cut:].strip()
        if current and len(current) + len(clause) + 1 > limit:
            parts.append(current)
            current = clause
        else:
            current = f'{current} {clause}'.strip()
    return parts + ([current] if current else [])


def pieces(script, limit=MAX_CHARS):
    """[(cue, text, pause_before)] small enough for Chatterbox to read reliably."""
    result = []
    for cue, sentence, pause in delivery.segments(script):
        for index, part in enumerate(_split_long(sentence, limit)):
            first = index == 0
            previous = result[-1] if result else None
            if (first and not pause and previous and previous[0] == cue
                    and re.search(r'[.!?…"”]$', previous[1]) and len(previous[1]) + len(part) + 1 <= limit):
                result[-1] = (cue, previous[1] + ' ' + part, previous[2])
            else:
                result.append((cue, part, pause and first))
    return result


def align_word(word):
    """Lower-case letters and apostrophes: what the aligner can match."""
    return re.sub(r"[^a-z']", '', word.lower().replace('’', "'")).strip("'")


# ---------------------------------------------------------------------------
# Audio helpers (numpy only)

def trim(wav, threshold=0.01, keep=0.06):
    """Drop silence and breath noise at both ends; keep a short natural margin."""
    import numpy as np
    loud = np.flatnonzero(np.abs(wav) > threshold)
    if not len(loud):
        return wav
    margin = int(keep * SAMPLE_RATE)
    return wav[max(0, loud[0] - margin): min(len(wav), loud[-1] + margin)]


def silence(seconds):
    import numpy as np
    return np.zeros(int(round(seconds * SAMPLE_RATE)), dtype=np.float32)


def estimate_timings(wav, words):
    """Fallback word timings: spread words over the voiced span by length."""
    import numpy as np
    loud = np.flatnonzero(np.abs(wav) > 0.01)
    start = loud[0] / SAMPLE_RATE if len(loud) else 0.0
    end = loud[-1] / SAMPLE_RATE if len(loud) else len(wav) / SAMPLE_RATE
    weights = [len(align_word(w)) + 2 for w in words]
    total, cursor, result = sum(weights) or 1, start, []
    for word, weight in zip(words, weights):
        length = (end - start) * weight / total
        result.append((cursor, cursor + length * 0.92))
        cursor += length
    return result


# ---------------------------------------------------------------------------
# Forced alignment for captions

class Aligner:
    def __init__(self, device):
        self.device, self.ready, self.failed = device, False, False

    def _load(self):
        import torch
        import torchaudio
        bundle = torchaudio.pipelines.MMS_FA
        self.model = bundle.get_model(with_star=False).to(self.device).eval()
        self.tokenizer, self.aligner = bundle.get_tokenizer(), bundle.get_aligner()
        self.labels = set(bundle.get_dict())
        self.torch, self.torchaudio = torch, torchaudio
        self.ready = True

    def align(self, wav, words):
        """[(start, end)] per word in seconds, or None if alignment is not possible."""
        if self.failed:
            return None
        try:
            if not self.ready:
                self._load()
        except Exception as exc:  # no internet on first use, old torchaudio, ...
            self.failed = True
            log(f'Caption aligner unavailable ({exc}); word timings will be estimated.')
            return None
        keys = [''.join(c for c in align_word(w) if c in self.labels) for w in words]
        index = [i for i, key in enumerate(keys) if key]
        if not index:
            return None
        torch = self.torch
        try:
            waveform = torch.from_numpy(wav).float().unsqueeze(0)
            waveform = self.torchaudio.functional.resample(waveform, SAMPLE_RATE, 16000).to(self.device)
            with torch.inference_mode():
                emission, _ = self.model(waveform)
                spans = self.aligner(emission[0], self.tokenizer([keys[i] for i in index]))
        except Exception as exc:  # e.g. the audio is shorter than the text needs
            log(f'Alignment failed for one piece ({exc}); estimating its timings.')
            return None
        ratio = waveform.size(1) / emission.size(1) / 16000
        found = {i: (span[0].start * ratio, span[-1].end * ratio) for i, span in zip(index, spans)}
        # Words without letters (dashes, symbols) take the gap after the previous word.
        result, last = [], 0.0
        for i in range(len(words)):
            start, end = found.get(i, (last, last))
            result.append((start, max(end, start + 0.02)))
            last = end
        return result


# ---------------------------------------------------------------------------
# The narrator

class Narrator:
    def __init__(self, model='standard', device=None):
        self.kind, self.device, self.model = model, device, None
        self.conditionals = {}

    def load(self):
        if self.model is not None:
            return
        import torch
        if not self.device:
            self.device = 'cuda' if torch.cuda.is_available() else (
                'mps' if getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available() else 'cpu')
        log(f'Loading Chatterbox ({self.kind}) on {self.device}; the first run downloads the model (about 3 GB).')
        if self.kind == 'turbo':
            from chatterbox.tts_turbo import ChatterboxTurboTTS as Model
        else:
            from chatterbox.tts import ChatterboxTTS as Model
        self.model = Model.from_pretrained(device=self.device)
        self.builtin = self.model.conds
        self.aligner = Aligner(self.device if self.device != 'mps' else 'cpu')
        if self.device == 'cpu':
            log('No graphics card found: Chatterbox runs on the processor, which is slow '
                '(expect several minutes per minute of audio).')

    def use_voice(self, clip, exaggeration):
        """Switch to a reference clip ('' = the built-in voice). Cached per clip."""
        if not clip:
            if self.builtin is None:
                raise RuntimeError('This Chatterbox model has no built-in voice; choose a narrator clip in Settings.')
            self.model.conds = self.builtin
            return
        path = Path(clip)
        key = (str(path), path.stat().st_mtime)
        if key not in self.conditionals:
            self.model.prepare_conditionals(str(path), exaggeration=exaggeration)
            self.conditionals[key] = self.model.conds
        self.model.conds = self.conditionals[key]

    def _generate(self, text, cue, base, seed):
        import torch
        torch.manual_seed(seed)
        if self.kind == 'turbo':
            wav = self.model.generate(text)
        else:
            shift, cfg = STYLE.get(cue, STYLE[None])
            exaggeration = min(2.0, max(0.25, base + shift))
            wav = self.model.generate(text, exaggeration=exaggeration, cfg_weight=cfg)
        return wav.squeeze(0).detach().cpu().numpy().astype('float32')

    def speak(self, text, cue, base, seed):
        """(audio, word timings, warning or None) for one piece, retried if implausible."""
        words = text.split()
        spoken = sum(1 for w in words if align_word(w)) or 1
        best = None
        for attempt in range(ATTEMPTS):
            wav = trim(self._generate(text, cue, base, seed + attempt * 7919))
            per_word = len(wav) / SAMPLE_RATE / spoken
            timings = self.aligner.align(wav, words)
            if timings:
                # Anything well after the last word is noise or invented speech: cut it.
                tail = int((timings[-1][1] + 0.25) * SAMPLE_RATE)
                if tail < len(wav) - int(0.8 * SAMPLE_RATE):
                    wav = wav[:tail]
                    per_word = len(wav) / SAMPLE_RATE / spoken
            plausible = MIN_SPW <= per_word <= MAX_SPW
            score = abs(per_word - 0.4)
            if best is None or (plausible and not best[3]) or (plausible == best[3] and score < best[4]):
                best = (wav, timings, attempt, plausible, score)
            if plausible:
                break
            log(f'  Piece read at {per_word:.2f}s per word (expected {MIN_SPW}-{MAX_SPW}); trying again.')
        wav, timings, attempt, plausible, _ = best
        timings = timings or estimate_timings(wav, words)
        warning = None if plausible else f'Check the line "{text[:80]}…": the voice may have skipped or added words.'
        return wav, timings, warning

    def narrate(self, story_path, output, clip='', speed=1.0, period_pause=0.25, clean=True,
                body_only=False, expressiveness=0.5, seed=1234):
        import numpy as np
        import soundfile as sf
        self.load()
        story_path, output = Path(story_path), Path(output)
        story = json.loads(story_path.read_text(encoding='utf-8-sig'))
        if not story.get('text', '').strip():
            raise ValueError('story has no text')
        script, removed, title_present = narrate.build_script(story, not body_only, clean)
        output.mkdir(parents=True, exist_ok=True)
        narrate.check_script(script, output, removed, title_present)
        script = say_numbers(script)
        clip_path = resolve_clip(clip)
        self.use_voice(clip_path, expressiveness)

        parts, words, chunks, warnings = [], [], [], []
        offset = 0.0
        plan = pieces(script)
        for number, (cue, text, pause) in enumerate(plan, 1):
            if pause and parts:
                parts.append(silence(PAUSE_SECONDS))
                offset += PAUSE_SECONDS
            wav, timings, warning = self.speak(text, cue, expressiveness, seed + number)
            if cue == 'whisper':
                wav = wav * WHISPER_GAIN
            if warning:
                warnings.append(warning)
            for word, (start, end) in zip(text.split(), timings):
                words.append({'word': word, 'start': round(offset + start, 4), 'end': round(offset + end, 4)})
            duration = len(wav) / SAMPLE_RATE
            chunks.append({'text': text, 'cue': cue, 'start': round(offset, 4), 'end': round(offset + duration, 4)})
            parts.append(wav)
            offset += duration
            gap = period_pause + 0.15 if re.search(r'[.!?…"”]$', text) else SOFT_GAP
            if number < len(plan):
                parts.append(silence(gap))
                offset += gap
            if number % 10 == 0 or number == len(plan):
                print(f'Spoke {number}/{len(plan)} pieces; {offset:.1f} seconds so far.', file=sys.stderr, flush=True)
        if not parts:
            raise RuntimeError('Chatterbox returned no audio.')
        audio = np.concatenate(parts).astype('float32')
        peak = float(np.max(np.abs(audio))) or 1.0
        if peak > 0.99:
            audio = audio * (0.97 / peak)
        sf.write(output / 'narration.wav', audio, SAMPLE_RATE, subtype='PCM_16')
        duration = len(audio) / SAMPLE_RATE
        if abs(speed - 1.0) > 0.01:
            duration = change_speed(output / 'narration.wav', words, chunks, speed)
        plain = delivery.remove_marks(script)
        (output / 'script.txt').write_text(plain, encoding='utf-8')
        (output / 'timings.json').write_text(json.dumps(words, ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'chunks.json').write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding='utf-8')
        metadata = {
            'story_file': str(story_path.resolve()), 'source_url': story.get('url'),
            'engine': 'chatterbox', 'model': self.kind, 'device': self.device,
            'voice': f'chatterbox:{Path(clip_path).stem if clip_path else "built-in"}',
            'voice_clip': Path(clip_path).name if clip_path else None,
            'speed': speed, 'sample_rate': SAMPLE_RATE, 'expressiveness': expressiveness,
            'duration_seconds': duration,
            'word_count': len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", plain)),
            'timestamp_count': len(words), 'includes_title': not body_only,
            'timing_source': 'forced alignment (MMS_FA)' if not self.aligner.failed else 'estimated from audio',
            'delivery_cues': sum(1 for c in chunks if c['cue']),
            'quality_warnings': warnings[:5],
            'removed_duplicate_passages': len(removed),
        }
        (output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        log(f'Saved narration to {output} ({duration:.1f}s)')
        return metadata


def change_speed(wav_path, words, chunks, speed):
    """Tempo change without pitch change (FFmpeg atempo); shifts the timings to match."""
    import imageio_ffmpeg
    import soundfile as sf
    temporary = wav_path.with_name('narration_speed.wav')
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-loglevel', 'error', '-y', '-i', str(wav_path),
                    '-af', f'atempo={speed:.4f}', '-ar', str(SAMPLE_RATE), '-c:a', 'pcm_s16le', str(temporary)], check=True)
    os.replace(temporary, wav_path)
    for row in words + chunks:
        row['start'], row['end'] = round(row['start'] / speed, 4), round(row['end'] / speed, 4)
    return sf.info(str(wav_path)).duration


def resolve_clip(clip):
    """A clip name from voices/ or a path; '' means the built-in voice."""
    if not clip:
        return ''
    path = Path(clip)
    if not path.is_absolute() and not path.exists():
        path = VOICES / clip
    if not path.is_file() or path.suffix.lower() not in CLIP_TYPES:
        raise FileNotFoundError(f'Narrator clip "{clip}" not found in the voices folder.')
    return str(path.resolve())


def clips():
    return sorted(p for p in VOICES.glob('*') if p.is_file() and p.suffix.lower() in CLIP_TYPES) if VOICES.is_dir() else []


def make_samples(narrator, only=None):
    """Read the same short horror passage with every clip in voices/ and the built-in voice."""
    SAMPLES.mkdir(parents=True, exist_ok=True)
    targets = [('built-in', '')] + [(p.stem, p.name) for p in clips()]
    if only:
        targets = [t for t in targets if t[0] in only]
    with tempfile.TemporaryDirectory() as folder:
        story = Path(folder) / 'sample.json'
        story.write_text(json.dumps({'title': '', 'text': SAMPLE_TEXT}), encoding='utf-8')
        for name, clip in targets:
            log(f'Voice sample: {name}')
            try:
                narrator.narrate(story, Path(folder) / name, clip=clip, period_pause=0.3, body_only=True)
            except Exception as exc:  # one bad clip should not stop the others
                log(f'  Skipped {name}: {exc}')
                continue
            shutil.copyfile(Path(folder) / name / 'narration.wav', SAMPLES / f'chatterbox_{name}.wav')
    print(f'Voice samples saved in {SAMPLES}', flush=True)


def serve(narrator):
    """JSON lines on stdin; one '@@RESULT {...}' line per request on stdout."""
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        if request.get('cmd') == 'quit':
            break
        try:
            metadata = narrator.narrate(**request['args'])
            reply = {'ok': True, 'metadata': metadata}
        except RuntimeError as exc:
            # Script problems (repeats, over-aggressive cleanup) need a person, like Kokoro's.
            reply = {'ok': False, 'error': str(exc), 'needs_review': 'review' in str(exc).lower()
                     or 'cleanup kept' in str(exc).lower()}
        except Exception as exc:
            reply = {'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'needs_review': False}
        print('@@RESULT ' + json.dumps(reply), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('story', nargs='?', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--clip', default='', help='Reference clip in voices/ (5-30 s of clean speech); empty = built-in voice')
    parser.add_argument('--model', choices=['standard', 'turbo'], default='standard')
    parser.add_argument('--device', help='cuda, mps or cpu (default: best available)')
    parser.add_argument('--speed', type=float, default=1.0)
    parser.add_argument('--period-pause', type=float, default=0.25)
    parser.add_argument('--expressiveness', type=float, default=0.5)
    parser.add_argument('--body-only', action='store_true')
    parser.add_argument('--serve', action='store_true', help='Read narration requests from stdin (used by production)')
    parser.add_argument('--samples', action='store_true', help='Make voice samples for every clip in voices/')
    args = parser.parse_args()
    narrator = Narrator(args.model, args.device)
    if args.serve:
        return serve(narrator)
    if args.samples:
        return make_samples(narrator)
    if not args.story:
        parser.error('give a story file, --samples or --serve')
    output = args.output or ROOT / 'narrations' / args.story.stem / 'chatterbox'
    narrator.narrate(args.story, output, clip=args.clip, speed=args.speed, period_pause=args.period_pause,
                     body_only=args.body_only, expressiveness=args.expressiveness)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(1)
