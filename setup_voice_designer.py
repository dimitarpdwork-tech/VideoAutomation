"""Install the voice designer (Qwen3-TTS VoiceDesign) in its own environment (.venv-design).

Run once, with Python 3.12:  setup_voice_designer.cmd  (Windows)  or  ./setup_voice_designer.sh
Needs an NVIDIA graphics card. Downloads PyTorch (about 2.5 GB) and the designer
model (about 4.5 GB), then makes one short test take to prove it works.
It has its own environment because it needs different library versions than
Chatterbox. It changes nothing outside this folder.
"""
import os
import subprocess
import sys
from pathlib import Path

import setup_voice

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv-design'
PYTHON = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
# qwen-tts 0.1.1's requirements minus gradio (its demo UI).
DEPS = ['transformers==4.57.3', 'accelerate==1.12.0', 'librosa', 'soundfile', 'sox', 'onnxruntime', 'einops',
        'numpy<2.3', 'huggingface_hub', 'setuptools<81']


def pip(*args):
    setup_voice.run(PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', *args)


def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit('Run this with Python 3.12 (Windows: py -3.12 setup_voice_designer.py).')
    card = setup_voice.nvidia_card()
    if not card:
        raise SystemExit('The voice designer needs an NVIDIA graphics card, and none was found.')
    if not PYTHON.exists():
        setup_voice.run(sys.executable, '-m', 'venv', ENV)
    pip('--upgrade', 'pip')
    if card[1] >= 12:
        pip('torch==2.7.1', 'torchaudio==2.7.1', '--index-url', 'https://download.pytorch.org/whl/cu128')
    else:
        pip('torch==2.6.0', 'torchaudio==2.6.0', '--index-url', 'https://download.pytorch.org/whl/cu124')
    pip('--no-deps', 'qwen-tts==0.1.1')
    pip(*DEPS)
    print('(pip may warn that gradio is missing: it is left out on purpose.)', flush=True)
    env = {**os.environ, 'HF_HOME': str(ROOT / '.model-cache' / 'huggingface')}
    if '--no-test' not in sys.argv:
        print('Downloading the designer model (about 4.5 GB) and making a short test take...', flush=True)
        test = ('import voice_designer as v\n'
                'rows = v.design("A calm, deep male narrator in his fifties, speaking slowly.", count=1, seed=7)\n'
                'print("Voice designer works." if rows else "The test take failed.")\n')
        subprocess.run([str(PYTHON), '-c', test], check=True, env=env, cwd=ROOT)
    print('\nThe voice designer is ready. In the dashboard: Narrator > Design a new voice.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f'Voice designer setup stopped at: {" ".join(map(str, exc.cmd))}\n'
                         'Check your internet connection and run setup_voice_designer again. Everything else still works.')
