#!/usr/bin/env bash
# Starts the dashboard at http://127.0.0.1:3000 (macOS/Linux). Keep this window open.
set -euo pipefail
cd "$(dirname "$0")"
.venv/bin/python initialize.py
cd dashboard
node build-if-needed.mjs
echo "Open http://127.0.0.1:3000 in your browser. Press Ctrl+C to stop."
npm run start
