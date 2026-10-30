@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0\.."

echo ========================================================
echo       PhotoSwipe - Build Eseguibile Windows (.exe)
echo ========================================================

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERRORE] Python non trovato nel PATH.
    echo Scarica e installa Python 3.13 da https://www.python.org/
    echo e assicurati di spuntare "Add python.exe to PATH".
    pause
    exit /b 1
)

if not exist "build\venv\Scripts\python.exe" (
    echo [1/4] Creazione virtualenv in build\venv...
    python -m venv build\venv
    if %errorlevel% neq 0 exit /b %errorlevel%
)

echo [2/4] Installazione dipendenze di build...
build\venv\Scripts\pip install --upgrade pip
build\venv\Scripts\pip install -r requirements.txt
build\venv\Scripts\pip install pyinstaller pillow

echo [3/4] Generazione icone Windows...
build\venv\Scripts\python packaging\make_icon.py

echo [4/4] Creazione PhotoSwipe.exe con PyInstaller...
build\venv\Scripts\pyinstaller --noconfirm --clean --windowed --name PhotoSwipe ^
    --icon packaging\PhotoSwipe.ico ^
    --collect-binaries imageio_ffmpeg ^
    --collect-all rawpy ^
    --collect-all pi_heif ^
    --add-data "engines\windows;engines\windows" ^
    --add-data "data;data" ^
    --add-data "THIRD_PARTY_NOTICES.txt;." ^
    --add-data "packaging\licenses;licenses" ^
    --exclude-module pytest ^
    --exclude-module tkinter ^
    --distpath dist\PhotoSwipe-Windows ^
    app.py

if %errorlevel% neq 0 (
    echo.
    echo [ERRORE] Creazione eseguibile fallita.
    pause
    exit /b %errorlevel%
)

copy /y packaging\LEGGIMI_WINDOWS.txt dist\PhotoSwipe-Windows\PhotoSwipe\LEGGIMI.txt >nul
copy /y THIRD_PARTY_NOTICES.txt dist\PhotoSwipe-Windows\PhotoSwipe\ >nul

echo.
echo ========================================================
echo  BUILD COMPLETATA!
echo  Troverai l'applicazione pronta in:
echo  dist\PhotoSwipe-Windows\PhotoSwipe\PhotoSwipe.exe
echo ========================================================
pause
