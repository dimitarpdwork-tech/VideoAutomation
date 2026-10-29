#!/usr/bin/env bash
# Publishes videos at each channel's local schedule while this window stays open (macOS/Linux).
# To publish without keeping the computer on, use "Schedule on YouTube" in the dashboard instead.
set -euo pipefail
cd "$(dirname "$0")"
echo "Publishes videos only for channels with the local schedule enabled."
echo "Keep this window open. Press Ctrl+C to stop."
.venv/bin/python scheduler.py
