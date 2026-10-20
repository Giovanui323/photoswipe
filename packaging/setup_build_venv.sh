#!/bin/bash
# Prepara (o riallinea) build/venv, il venv usato da packaging/build_dmg.sh,
# con le versioni esatte di packaging/requirements-build.txt.
# Uso: packaging/setup_build_venv.sh        (PYTHON=/percorso/python3.13 per scegliere l'interprete)
set -euo pipefail
cd "$(dirname "$0")/.."
VENV=build/venv
if [ ! -x "$VENV/bin/python" ]; then
  # di default il Python "standalone" in build/pythons (minos 11.0), se c'è
  PY="${PYTHON:-$(ls -d build/pythons/cpython-3.13*/bin/python3.13 2>/dev/null | tail -1)}"
  PY="${PY:-python3.13}"
  echo "Creo $VENV con $PY"
  "$PY" -m venv "$VENV"
fi
PIP="$VENV/bin/pip"
"$PIP" install -r packaging/requirements-build.txt
# niente moduli PySide6 opzionali di altre versioni (es. PySide6_WebEngine/Pdf 6.12): l'app non li usa
for extra in $("$PIP" list --format=freeze | sed -n 's/^\(PySide6_[A-Za-z]*\)==.*/\1/p'); do
  case "$extra" in PySide6_Essentials|PySide6_Addons) ;; *) "$PIP" uninstall -y "$extra" ;; esac
done
# numpy: la wheel macosx_14_0 (Accelerate) non parte su macOS 12-13 -> forzo quella macosx_11_0 (OpenBLAS)
NUMPY_VER=$(sed -n 's/^numpy==//p' packaging/requirements-build.txt)
PYVER=$("$VENV/bin/python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
WHEELS=$(mktemp -d)
trap 'rm -rf "$WHEELS"' EXIT
"$PIP" download "numpy==$NUMPY_VER" --no-deps --only-binary=:all: \
  --platform macosx_11_0_arm64 --python-version "$PYVER" -d "$WHEELS"
"$PIP" install --force-reinstall --no-deps "$WHEELS"/numpy-*macosx_11_0_arm64.whl
"$PIP" check
SP=$("$VENV/bin/python" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
MINOS=$(packaging/macos_minos.sh "$SP" -v)
echo "macOS minimo richiesto dai pacchetti del venv: $MINOS"
[ "$MINOS" = "12.0" ] || { echo "ERRORE: qualche libreria richiede macOS $MINOS (> 12.0), vedi sopra"; exit 1; }
echo "OK: $VENV pronto"
