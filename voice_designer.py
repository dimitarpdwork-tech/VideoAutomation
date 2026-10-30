r"""Design a brand-new narrator voice from a written description (Qwen3-TTS VoiceDesign).

The voice belongs to nobody: it is invented from your words, so it can be used
on monetised videos without anyone's permission. Each run makes a few takes;
keep the one you like in the dashboard and it becomes a narrator clip that
Chatterbox narrates every story with.

Runs in its own environment (.venv-design; install with setup_voice_designer).
Needs an NVIDIA graphics card (about 6-8 GB of graphics memory).

    .venv-design\Scripts\python voice_designer.py --description "A very deep, slow male voice..." --count 3
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault('HF_HOME', str(ROOT / '.model-cache' / 'huggingface'))
os.environ.setdefault('TQDM_DISABLE', '1')
DESIGNS = ROOT / 'output' / 'shared' / 'voice_designs'
MODEL = 'Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign'
# Read in the new voice. Chatterbox copies the voice and the manner of the reading,
# so this is quiet and slow, with a pause: the delivery a horror narrator needs.
REFERENCE_TEXT = ("I have lived in this house for eleven years. In all that time, I never once heard anyone on the "
                  "stairs at night. Not until last winter. And now I hear them every night, just after three, "
                  "always stopping at my door.")
MAX_DESCRIPTION = 500


def write_index(rows):
    DESIGNS.mkdir(parents=True, exist_ok=True)
    temporary = DESIGNS / 'index.json.tmp'
    temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temporary, DESIGNS / 'index.json')


def read_index():
    try:
        return json.loads((DESIGNS / 'index.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return []


def design(description, count=3, seed=None, model=None, log=print):
    import numpy as np
    import soundfile as sf
    import torch
    if model is None:
        if not torch.cuda.is_available():
            raise SystemExit('The voice designer needs an NVIDIA graphics card, and none was found.')
        from qwen_tts import Qwen3TTSModel
        log(f'Loading the voice designer on {torch.cuda.get_device_name(0)} (the first run downloads about 4.5 GB)...')
        model = Qwen3TTSModel.from_pretrained(MODEL, device_map='cuda:0', dtype=torch.bfloat16)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    rows = read_index()
    made = []
    base_seed = seed if seed is not None else int.from_bytes(os.urandom(2), 'big')
    for take in range(1, count + 1):
        take_seed = base_seed + take * 101
        torch.manual_seed(take_seed)
        log(f'Take {take} of {count}...')
        wavs, rate = model.generate_voice_design(text=REFERENCE_TEXT, instruct=description, language='English')
        audio = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        seconds = len(audio) / rate
        if seconds < 6:
            log(f'  Take {take} came out too short ({seconds:.1f} s); skipped.')
            continue
        peak = float(np.max(np.abs(audio))) or 1.0
        audio = audio * min(1.0, 0.95 / peak)
        name = f'design_{stamp}_{take}.wav'
        DESIGNS.mkdir(parents=True, exist_ok=True)
        sf.write(DESIGNS / name, audio, rate, subtype='PCM_16')
        row = {'file': name, 'description': description, 'seed': take_seed, 'seconds': round(seconds, 1),
               'created': datetime.now(timezone.utc).isoformat()}
        rows.append(row)
        made.append(row)
        log(f'  Saved take {take} ({seconds:.1f} s).')
    write_index(rows[-60:])
    log(f'{len(made)} voice take(s) ready. Listen in the dashboard and keep the one you like.')
    return made


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--description', required=True, help='What the voice sounds like, in plain words')
    parser.add_argument('--count', type=int, default=3)
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    description = re.sub(r'\s+', ' ', args.description).strip()
    if not 10 <= len(description) <= MAX_DESCRIPTION:
        parser.error(f'describe the voice in 10-{MAX_DESCRIPTION} characters')
    if not 1 <= args.count <= 5:
        parser.error('count must be between 1 and 5')
    if not design(description, args.count, args.seed, log=lambda m: print(m, flush=True)):
        sys.exit(1)


if __name__ == '__main__':
    main()
