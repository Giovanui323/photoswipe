#!/bin/bash
# Doppio clic per avviare PhotoSwipe su macOS
cd "$(dirname "$0")"
# installa (o aggiorna) i pacchetti se manca il venv, se un'installazione era fallita a metà
# o se requirements.txt è cambiato: il segno si scrive solo a installazione riuscita.
# Solo i pacchetti dell'app (requirements.txt); pytest e gli strumenti di sviluppo stanno in requirements-dev.txt
if [ ! -x .venv/bin/python ] || ! cmp -s requirements.txt .venv/.requirements-ok; then
  [ -x .venv/bin/python ] || python3 -m venv .venv || { echo "Serve Python 3 (python.org)"; read -r; exit 1; }
  if .venv/bin/pip install -r requirements.txt; then
    cp requirements.txt .venv/.requirements-ok
  else
    echo "Installazione dei pacchetti non riuscita (vedi sopra). Premi Invio per chiudere."; read -r; exit 1
  fi
fi
exec .venv/bin/python app.py "$@"
