#!/bin/bash
# Crea dist/PhotoSwipe-<versione>-arm64.dmg (Mac con chip Apple, macOS 11+ per Python)
set -euo pipefail
cd "$(dirname "$0")/.."
# Versione: sale di 1 a ogni build, a decine (1.1.5 -> 1.1.6 ... 1.1.9 -> 1.2.0), scritta in app.py
OLD=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' app.py)
# contatore a decine: 1.0.9 -> 1.1.0, 1.9.9 -> 2.0.0
VER=$(echo "$OLD" | awk -F. '{ma=$1; mi=$2; pa=$3+1; if (pa>9){pa=0; mi++}; if (mi>9){mi=0; ma++}; printf "%d.%d.%d", ma, mi, pa}')
sed -i '' "s/^APP_VERSION = \".*\"/APP_VERSION = \"$VER\"/" app.py
sed -i '' "s/^Versione \*\*[0-9.]*\*\*.*$/Versione **$VER** — il numero è nel titolo della finestra./" README.md
echo "Versione: $OLD -> $VER"
rm -rf build/work build/dist build/dmg
build/venv/bin/pyinstaller --noconfirm --clean --windowed --name PhotoSwipe \
  --icon "$PWD/packaging/PhotoSwipe.icns" --osx-bundle-identifier io.github.giovanui323.photoswipe \
  --collect-binaries imageio_ffmpeg --add-data "$PWD/engines/macos:engines/macos" --add-data "$PWD/THIRD_PARTY_NOTICES.txt:." --exclude-module pytest \
  --exclude-module tkinter --distpath build/dist --workpath build/work --specpath build "$PWD/app.py"
APP=build/dist/PhotoSwipe.app
plutil -replace CFBundleShortVersionString -string "$VER" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$VER" "$APP/Contents/Info.plist"
plutil -replace LSMinimumSystemVersion -string "12.0" "$APP/Contents/Info.plist"
codesign --force --deep -s - "$APP"
mkdir -p build/dmg dist
cp -R "$APP" build/dmg/
ln -s /Applications build/dmg/Applicazioni
cp packaging/LEGGIMI.txt build/dmg/ 2>/dev/null || true
cp THIRD_PARTY_NOTICES.txt build/dmg/   # licenze dei componenti inclusi: vanno distribuite insieme
DMG="dist/PhotoSwipe-$VER-arm64.dmg"
rm -f "$DMG"
hdiutil create -volname "PhotoSwipe $VER" -srcfolder build/dmg -ov -format UDZO "$DMG"
echo "DMG: $DMG"
