#!/usr/bin/env bash
# One-command start for macOS / Linux.
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "FFmpeg is not installed. macOS: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt

[ -f .env ] || cp .env.example .env
python scripts/download_models.py hq
echo ""
echo "SurSplit is starting → http://127.0.0.1:${PORT:-8000}"
python -m app.main
