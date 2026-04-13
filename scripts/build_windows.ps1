# Build Qobuz-DL-GUI.exe with PyInstaller (run from repository root).
# Requires Python 3.10+ recommended (3.6+ per package may work).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Installing dependencies + PyInstaller..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

Write-Host "Building one-file EXE (close any running Qobuz-DL-GUI.exe first)..."
python -m PyInstaller --noconfirm qobuz_dl_gui.spec

$exe = Join-Path $Root "dist\Qobuz-DL-GUI.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "OK: $exe"
} else {
    Write-Error "Build failed: $exe not found"
}
