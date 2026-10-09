#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"
source ./_python.sh

if [[ ! -d ".venv" ]]; then
  "$(find_python)" -m venv .venv
fi

source .venv/bin/activate
if ! python -c 'import tkinter' 2>/dev/null; then
  echo "O .venv foi criado com um Python sem tkinter. Apague a pasta .venv e rode de novo." >&2
  exit 1
fi
python -m pip install -r requirements.txt
python app.py
