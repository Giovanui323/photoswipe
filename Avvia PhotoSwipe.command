#!/bin/bash
# Doppio clic per avviare PhotoSwipe su macOS
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
exec .venv/bin/python app.py "$@"
