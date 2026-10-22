#!/bin/bash
# Firma ad-hoc (senza certificato Apple) di un .app, dall'interno verso l'esterno,
# al posto del deprecato "codesign --deep": prima ogni binario annidato (.so, .dylib,
# eseguibili come ffmpeg/realesrgan), poi i .framework, infine l'app. Poi verifica.
# Uso: packaging/adhoc_sign.sh build/dist/PhotoSwipe.app
set -euo pipefail
APP="${1:?uso: $0 <percorso.app>}"
MAIN="$APP/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist")"
sign() {
  local out
  out=$(codesign --force --sign - --timestamp=none "$@" 2>&1) || { echo "$out" >&2; return 1; }
}
# per profondità decrescente: un contenitore va firmato dopo il suo contenuto
by_depth() { awk -F/ '{print NF "\t" $0}' | sort -rn | cut -f2-; }
n=0
while IFS= read -r f; do
  [ "$f" = "$MAIN" ] && continue
  [[ $(file -b "$f") == *Mach-O* ]] || continue   # senza pipe: con pipefail grep -q darebbe 141
  sign "$f"; n=$((n+1))
done < <(find "$APP/Contents" -type f \( -name '*.so' -o -name '*.dylib' -o -perm +111 \) | by_depth)
while IFS= read -r fw; do
  sign "$fw"; n=$((n+1))
done < <(find "$APP/Contents" -type d -name '*.framework' | by_depth)
sign "$APP"
echo "Firmati $n componenti + l'app (ad-hoc)"
codesign --verify --deep --strict --verbose=1 "$APP"
