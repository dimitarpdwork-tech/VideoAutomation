"""Install the Chatterbox narrator in its own environment (.venv-voice).

Run once, with Python 3.12:  setup_voice.cmd  (Windows)  or  ./setup_voice.sh
The main setup runs it for you; run it again if it was skipped or failed.

- With an NVIDIA graphics card it installs the GPU build of PyTorch, which makes
  narration 10-30x faster than on the processor. RTX 50-series cards get the
  newer build they need.
- Then it downloads the voice model (about 3 GB) and the caption aligner, so
  the first batch does not wait for downloads.
It changes nothing outside this folder.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv-voice'
PYTHON = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
CHATTERBOX = 'chatterbox-tts==0.1.7'
# chatterbox-tts 0.1.7's own requirements minus PyTorch, gradio (its demo UI) and
# the Chinese/Japanese text tools it only imports for other languages.
CHATTERBOX_DEPS = ['librosa==0.11.0', 's3tokenizer', 'transformers==5.2.0', 'diffusers==0.29.0',
                   'resemble-perth>=1.0.0', 'conformer==0.3.2', 'safetensors==0.5.3', 'pyloudnorm', 'omegaconf',
                   'numpy>=1.24,<2', 'huggingface_hub']
# setuptools: Chatterbox's audio watermarker imports pkg_resources, which new Python 3.12
# environments lack (without it the model fails to load with "'NoneType' object is not callable").
EXTRAS = ['setuptools<81', 'soundfile', 'num2words', 'imageio-ffmpeg>=0.5,<1']
MODEL_FILES = ['ve.safetensors', 't3_cfg.safetensors', 's3gen.safetensors', 'tokenizer.json', 'conds.pt']


def run(*command):
    print('>', ' '.join(str(c) for c in command), flush=True)
    subprocess.run([str(c) for c in command], check=True)


def nvidia_card():
    """(name, compute capability major) of the first NVIDIA card, or None."""
    tool = shutil.which('nvidia-smi')
    if not tool:
        return None
    try:
        out = subprocess.run([tool, '--query-gpu=name,compute_cap', '--format=csv,noheader'],
                             capture_output=True, text=True, timeout=20).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not out:
        return None
    name, _, capability = out[0].partition(',')
    try:
        major = int(float(capability.strip()))
    except ValueError:  # older drivers cannot report it; RTX 50 cards are the ones that matter
        major = 12 if re.search(r'RTX\s*50\d\d', name) else 8
    return name.strip(), major


def pip(*args):
    run(PYTHON, '-m', 'pip', 'install', '--disable-pip-version-check', *args)


def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit('Run this with Python 3.12 (Windows: py -3.12 setup_voice.py).')
    if not PYTHON.exists():
        run(sys.executable, '-m', 'venv', ENV)
    pip('--upgrade', 'pip')
    card = nvidia_card()
    if card and card[1] >= 12:
        print(f'Found {card[0]} (RTX 50 series): installing PyTorch 2.7 for CUDA 12.8.', flush=True)
        pip('torch==2.7.1', 'torchaudio==2.7.1', '--index-url', 'https://download.pytorch.org/whl/cu128')
        pip('--no-deps', CHATTERBOX)
        pip(*CHATTERBOX_DEPS)
    elif card:
        print(f'Found {card[0]}: installing PyTorch with CUDA support.', flush=True)
        pip('torch==2.6.0', 'torchaudio==2.6.0', '--index-url', 'https://download.pytorch.org/whl/cu124')
        pip('--no-deps', CHATTERBOX)
        pip(*CHATTERBOX_DEPS)
    else:
        print('No NVIDIA card found: installing the standard PyTorch build '
              '(Apple Silicon uses its graphics chip; other computers use the processor, which is slow).', flush=True)
        pip('--no-deps', CHATTERBOX)
        pip('torch==2.6.0', 'torchaudio==2.6.0', *CHATTERBOX_DEPS)
    pip(*EXTRAS)
    print('(pip may warn that gradio, pykakasi and spacy-pkuseg are missing: they are left out on purpose, '
          'because English narration does not use them.)', flush=True)

    env = {**os.environ, 'HF_HOME': str(ROOT / '.model-cache' / 'huggingface')}
    check = ('import torch, chatterbox; '
             'print("PyTorch", torch.__version__, "| graphics card:", torch.cuda.get_device_name(0) '
             'if torch.cuda.is_available() else "none (processor)")')
    subprocess.run([str(PYTHON), '-c', check], check=True, env=env)
    if '--no-download' not in sys.argv:
        print('Downloading the voice model (about 3 GB) and the caption aligner...', flush=True)
        download = ('from huggingface_hub import hf_hub_download\n'
                    f'for name in {MODEL_FILES!r}: hf_hub_download(repo_id="ResembleAI/chatterbox", filename=name)\n'
                    'import torchaudio; torchaudio.pipelines.MMS_FA.get_model(with_star=False)\n'
                    'print("Models ready.")')
        subprocess.run([str(PYTHON), '-c', download], check=True, env=env, cwd=ROOT)
    print('\nChatterbox is ready. In the dashboard: Settings > Voice > "Make voice samples" to hear the narrators.')


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f'Voice setup stopped at: {" ".join(map(str, exc.cmd))}\n'
                         'Check your internet connection and run setup_voice again. Kokoro narration still works.')
