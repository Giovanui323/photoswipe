# PhotoSwipe - Script di build PowerShell per Windows
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "      PhotoSwipe - Build Eseguibile Windows (.exe)      " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python non trovato nel PATH. Installa Python 3.13 con 'Add to PATH'."
}

if (-not (Test-Path "build\venv\Scripts\python.exe")) {
    Write-Host "[1/4] Creazione virtualenv in build\venv..." -ForegroundColor Yellow
    python -m venv build\venv
}

Write-Host "[2/4] Installazione dipendenze di build..." -ForegroundColor Yellow
& build\venv\Scripts\python.exe -m pip install --upgrade pip
& build\venv\Scripts\pip.exe install -r requirements.txt
& build\venv\Scripts\pip.exe install pyinstaller pillow

Write-Host "[3/4] Generazione icone Windows..." -ForegroundColor Yellow
& build\venv\Scripts\python.exe packaging\make_icon.py

Write-Host "[4/4] Creazione PhotoSwipe.exe con PyInstaller..." -ForegroundColor Yellow
& build\venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name PhotoSwipe `
    --icon packaging\PhotoSwipe.ico `
    --collect-binaries imageio_ffmpeg `
    --collect-all rawpy `
    --collect-all pi_heif `
    --add-data "engines\windows;engines\windows" `
    --add-data "data;data" `
    --add-data "THIRD_PARTY_NOTICES.txt;." `
    --add-data "packaging\licenses;licenses" `
    --exclude-module pytest `
    --exclude-module tkinter `
    --distpath dist\PhotoSwipe-Windows `
    app.py

Copy-Item "packaging\LEGGIMI_WINDOWS.txt" "dist\PhotoSwipe-Windows\PhotoSwipe\LEGGIMI.txt"
Copy-Item "THIRD_PARTY_NOTICES.txt" "dist\PhotoSwipe-Windows\PhotoSwipe\"

Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host " BUILD COMPLETATA!" -ForegroundColor Green
Write-Host " Percorso applicazione: dist\PhotoSwipe-Windows\PhotoSwipe\PhotoSwipe.exe" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
