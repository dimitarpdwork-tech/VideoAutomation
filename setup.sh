#!/usr/bin/env bash
# One-time setup for macOS and Linux. Windows users: double-click setup.cmd.
# Optional: ./setup.sh /path/to/python3.12
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${1:-python3.12}"
fail() { echo "Setup stopped: $1"; echo "Install Python 3.12, Node.js 20.9+ and FFmpeg-compatible system libraries; see README.md."; exit 1; }
command -v "$PYTHON" >/dev/null 2>&1 || fail "$PYTHON not found (Kokoro needs Python 3.12)."
"$PYTHON" -c "import sys; assert sys.version_info[:2] == (3, 12)" 2>/dev/null || fail "Python 3.12 is required."
command -v npm >/dev/null 2>&1 || fail "npm not found."
if [[ "$(uname)" == "Linux" ]] && ! ldconfig -p 2>/dev/null | grep -q libespeak-ng; then
  echo "Note: if narration fails, install espeak-ng (e.g. sudo apt install espeak-ng)."
fi
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
"$PYTHON" -m venv .venv-tts
.venv-tts/bin/python -m pip install -r requirements-tts.txt
.venv/bin/python initialize.py
(cd dashboard && npm ci && npm run build)
# The human-sounding Chatterbox voice; optional, so a failure here does not stop setup.
"$PYTHON" setup_voice.py || echo "Note: Chatterbox voice setup did not finish; run ./setup_voice.sh later. Kokoro narration works."
echo "Setup complete. Read README.md to add your credentials and backgrounds, then run ./start_dashboard.sh"
