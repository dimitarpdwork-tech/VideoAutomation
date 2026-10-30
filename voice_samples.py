"""Make narrator samples to choose a channel's voice by ear.

1. Creates starter narrator clips in voices/ with Kokoro. These voices belong to
   nobody, so cloning them raises no rights questions. Your own clips (5-30 s of
   clean speech you have the rights to) can sit next to them.
2. Reads the same short horror passage with each Kokoro starter voice and, when
   Chatterbox is installed, with every clip in voices/ cloned by Chatterbox.

Results: output/shared/voice_samples/*.wav and index.json (the dashboard lists them).
Run with the .venv-tts interpreter: python voice_samples.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import chatterbox_narrator as cb  # stdlib-only at import time: shares the texts and folders
import voice_worker
from channel_config import ROOT, venv_python, write_json

# name, Kokoro voice, what it sounds like
STARTERS = [
    ('deep_male', 'am_onyx', 'Deep, low American male: classic late-night horror narrator'),
    ('warm_male', 'am_michael', 'Warm American male: storytime and drama'),
    ('british_male', 'bm_george', 'Older British male: calm, documentary-like'),
    ('soft_female', 'af_nicole', 'Soft, breathy American female: intimate, unsettling'),
    ('british_female', 'bf_emma', 'Gentle British female: sleep stories and history'),
]
# Neutral, even reading: a clip should show the voice, not a performance.
REFERENCE_TEXT = ('I have always liked the quiet hours, when the house settles and the street outside goes still. '
                  'There is a kind of honesty in that silence, and I find it easier to remember things clearly.')


def kokoro(text, voice, folder):
    """Narrate text with Kokoro into folder; return the wav path."""
    import narrate
    folder.mkdir(parents=True, exist_ok=True)
    story = folder / 'story.json'
    story.write_text(json.dumps({'title': '', 'text': text}), encoding='utf-8')
    argv = sys.argv
    sys.argv = ['narrate.py', str(story), '--output', str(folder / voice), '--voice', voice, '--fixed-voice',
                '--body-only', '--period-pause', '0.3']
    try:
        narrate.main()
    finally:
        sys.argv = argv
    return folder / voice / 'narration.wav'


def main():
    cb.VOICES.mkdir(exist_ok=True)
    cb.SAMPLES.mkdir(parents=True, exist_ok=True)
    index = []
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        for name, voice, description in STARTERS:
            clip = cb.VOICES / f'starter_{name}.wav'
            if not clip.exists():
                print(f'Creating starter narrator clip {clip.name} ({voice})', flush=True)
                shutil.copyfile(kokoro(REFERENCE_TEXT, voice, folder / 'ref'), clip)
            print(f'Kokoro sample: {voice}', flush=True)
            sample = cb.SAMPLES / f'kokoro_{voice}.wav'
            shutil.copyfile(kokoro(cb.SAMPLE_TEXT, voice, folder / 'sample'), sample)
            index.append({'file': sample.name, 'engine': 'kokoro', 'voice': voice, 'label': f'Kokoro · {voice}',
                          'description': description})
    if voice_worker.installed():
        print('Chatterbox samples (each clip in voices/, plus the built-in voice)...', flush=True)
        result = subprocess.run([str(venv_python('.venv-voice')), '-u', str(ROOT / 'chatterbox_narrator.py'), '--samples'],
                                cwd=ROOT)
        if result.returncode:
            print('Chatterbox samples stopped early; the ones finished are listed.', flush=True)
        descriptions = {f'starter_{name}': description for name, _, description in STARTERS}
        for wav in sorted(cb.SAMPLES.glob('chatterbox_*.wav')):
            stem = wav.stem[len('chatterbox_'):]
            clip = next((p.name for p in cb.clips() if p.stem == stem), '')
            if stem != 'built-in' and not clip:
                continue  # the clip was deleted since
            index.append({'file': wav.name, 'engine': 'chatterbox', 'clip': clip,
                          'label': 'Chatterbox · ' + ('built-in voice' if stem == 'built-in' else stem.replace('_', ' ')),
                          'description': descriptions.get(stem, 'Your clip' if clip else 'Chatterbox default narrator')})
    else:
        print('Chatterbox is not installed, so only Kokoro samples were made. Run setup_voice to add it.', flush=True)
    # Chatterbox first: those are the ones to choose from.
    index.sort(key=lambda row: (row['engine'] != 'chatterbox', row['label']))
    write_json(cb.SAMPLES / 'index.json', index)
    print(f'{len(index)} voice samples ready. Listen in the dashboard: Settings > Voice.', flush=True)


if __name__ == '__main__':
    main()
