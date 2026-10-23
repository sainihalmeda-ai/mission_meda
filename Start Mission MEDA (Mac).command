#!/bin/bash
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python is not installed. Opening the download page..."
  echo "Install it, then double-click this file again."
  open https://www.python.org/downloads/
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
  echo "First-time setup: installing Mission MEDA. This takes a minute or two..."
  python3 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
fi
.venv/bin/python run.py "$@"
