#!/usr/bin/env bash
# Build macOS .app bundle (run on macOS only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m pip install -r requirements.txt -r requirements-build.txt
python3 -m PyInstaller --noconfirm qobuz_dl_gui.spec
cd dist && zip -ry ../Qobuz-DL-GUI-macOS-x64.zip Qobuz-DL-GUI.app
cd ..
echo "Output: dist/Qobuz-DL-GUI.app and Qobuz-DL-GUI-macOS-x64.zip"
