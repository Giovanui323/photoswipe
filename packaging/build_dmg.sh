#!/bin/bash
# Crea dist/PhotoSwipe-<versione>-arm64.dmg (Mac con chip Apple, macOS 12 Monterey o successivo)
# Il venv di build si prepara una volta con: packaging/setup_build_venv.sh
set -euo pipefail
cd "$(dirname "$0")/.."
SETUP_HINT="  packaging/setup_build_venv.sh   (versioni esatte in packaging/requirements-build.txt)"
# il venv di build deve avere tutto quello che usa l'app: senza rawpy i DNG non hanno anteprima,
# senza pi_heif niente HEIC (l'errore sarebbe silenzioso nell'app impacchettata)
build/venv/bin/python -c "import rawpy, pi_heif, numpy, PIL, imageio_ffmpeg, PySide6.QtMultimedia" || {
  echo "ERRORE: nel venv di build manca un pacchetto. Prepara il venv con:"; echo "$SETUP_HINT"
  exit 1
}
# versioni esattamente quelle fissate (niente PySide6 mescolati, niente aggiornamenti non voluti)
if ! diff <(grep -v '^#' packaging/requirements-build.txt | sort -f) \
          <(build/venv/bin/pip list --format=freeze 2>/dev/null | grep -v '^pip==' | sort -f); then
  echo "ERRORE: build/venv non corrisponde a packaging/requirements-build.txt (differenze sopra). Riallinea con:"
  echo "$SETUP_HINT"
  exit 1
fi
# nessuna libreria del venv deve chiedere più di macOS 12 (es. numpy macosx_14_0 con Accelerate)
SP=$(build/venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
VENV_MINOS=$(packaging/macos_minos.sh "$SP" -v)
[ "$VENV_MINOS" = "12.0" ] || {
  echo "ERRORE: nel venv di build ci sono librerie per macOS $VENV_MINOS (sopra): l'app non partirebbe su macOS 12."
  echo "$SETUP_HINT"
  exit 1
}
# Versione: sale di 1 a ogni build, a decine (1.1.5 -> 1.1.6 ... 1.1.9 -> 1.2.0), scritta in app.py
OLD=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' app.py)
# contatore a decine: 1.0.9 -> 1.1.0, 1.9.9 -> 2.0.0
VER=$(echo "$OLD" | awk -F. '{ma=$1; mi=$2; pa=$3+1; if (pa>9){pa=0; mi++}; if (mi>9){mi=0; ma++}; printf "%d.%d.%d", ma, mi, pa}')
sed -i '' "s/^APP_VERSION = \".*\"/APP_VERSION = \"$VER\"/" app.py
# build fallita: la versione torna quella di prima (niente numeri saltati)
trap 'sed -i "" "s/^APP_VERSION = \".*\"/APP_VERSION = \"$OLD\"/" app.py; echo "Build fallita: versione rimessa a $OLD"' ERR
sed -i '' "s/version-[0-9.]*-blue/version-$VER-blue/" README.md
echo "Versione: $OLD -> $VER"
rm -rf build/work build/dist build/dmg
build/venv/bin/pyinstaller --noconfirm --clean --windowed --name PhotoSwipe \
  --icon "$PWD/packaging/PhotoSwipe.icns" --osx-bundle-identifier io.github.giovanui323.photoswipe \
  --collect-binaries imageio_ffmpeg --collect-all rawpy --collect-all pi_heif --add-data "$PWD/engines/macos:engines/macos" --add-data "$PWD/THIRD_PARTY_NOTICES.txt:." --add-data "$PWD/packaging/licenses:licenses" --exclude-module pytest \
  --exclude-module tkinter --distpath build/dist --workpath build/work --specpath build "$PWD/app.py"
APP=build/dist/PhotoSwipe.app
plutil -replace CFBundleShortVersionString -string "$VER" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$VER" "$APP/Contents/Info.plist"
# macOS minimo = il più alto richiesto dai binari inclusi (.so, .dylib, framework Qt, ffmpeg), almeno 12
MINOS=$(packaging/macos_minos.sh "$APP" -v)
echo "macOS minimo: $MINOS"
if [ "$MINOS" != "12.0" ]; then   # LEGGIMI e README promettono macOS 12: meglio fermarsi che mentire
  echo "ERRORE: i binari elencati sopra richiedono macOS $MINOS. Riallinea il venv: $SETUP_HINT"; false
fi
plutil -replace LSMinimumSystemVersion -string "$MINOS" "$APP/Contents/Info.plist"
# firma ad-hoc (nessun certificato Apple, niente notarizzazione): binari annidati, framework, poi l'app;
# va fatta dopo ogni modifica a Info.plist. Lo script verifica con codesign --verify --deep --strict
packaging/adhoc_sign.sh "$APP"
mkdir -p build/dmg dist
cp -R "$APP" build/dmg/
ln -s /Applications build/dmg/Applicazioni
cp packaging/LEGGIMI.txt build/dmg/ 2>/dev/null || true
cp THIRD_PARTY_NOTICES.txt build/dmg/   # licenze dei componenti inclusi: vanno distribuite insieme
cp -R packaging/licenses build/dmg/licenses   # testi completi LGPL/GPL citati nelle note
DMG="dist/PhotoSwipe-$VER-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname "PhotoSwipe $VER" -srcfolder build/dmg -ov -format UDZO "$DMG"
echo "DMG: $DMG"
