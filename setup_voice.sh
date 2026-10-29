#!/usr/bin/env bash
# Install the Chatterbox narrator (.venv-voice). Optional: ./setup_voice.sh /path/to/python3.12
set -euo pipefail
cd "$(dirname "$0")"
"${1:-python3.12}" setup_voice.py "${@:2}"
