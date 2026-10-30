#!/usr/bin/env bash
# Install the voice designer (.venv-design). Optional: ./setup_voice_designer.sh /path/to/python3.12
set -euo pipefail
cd "$(dirname "$0")"
"${1:-python3.12}" setup_voice_designer.py "${@:2}"
