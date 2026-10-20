#!/bin/bash
# Stampa la versione minima di macOS richiesta da un .app (o da una cartella qualsiasi):
# il "minos" più alto fra tutti i binari Mach-O dentro (.so, .dylib, eseguibili, framework Qt),
# mai meno di 12.0. Uso: packaging/macos_minos.sh <percorso> [-v]
#   -v  elenca anche i binari che chiedono più di 12.0
set -euo pipefail
ROOT="${1:?uso: $0 <app-o-cartella> [-v]}"
VERBOSE="${2:-}"
MAX=12.0
while IFS= read -r -d '' f; do
  file -b "$f" | grep -q 'Mach-O' || continue
  # LC_BUILD_VERSION -> "minos X"; i binari vecchi usano LC_VERSION_MIN_MACOSX -> "version X"
  m=$(otool -l "$f" 2>/dev/null | awk '
      /cmd LC_BUILD_VERSION/ {b=1} /cmd LC_VERSION_MIN_MACOSX/ {v=1}
      b && / minos / {print $2; b=0}
      v && / version / {print $2; v=0}' | sort -V | tail -1)
  [ -n "$m" ] || continue
  if [ "$(printf '%s\n%s\n' "$MAX" "$m" | sort -V | tail -1)" != "$MAX" ]; then MAX=$m; fi
  if [ "$VERBOSE" = "-v" ] && [ "$(printf '%s\n12.0\n' "$m" | sort -V | tail -1)" != "12.0" ]; then
    echo "  $m  ${f#"$ROOT"/}" >&2
  fi
done < <(find "$ROOT" -type f \( -name '*.so' -o -name '*.dylib' -o -perm +111 \) -print0)
echo "$MAX"
