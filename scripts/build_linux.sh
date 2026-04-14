#!/usr/bin/env bash
# Build Linux one-file binary (run on Linux only).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m pip install -r requirements.txt -r requirements-build.txt
python3 -m PyInstaller --noconfirm qobuz_dl_gui.spec
chmod +x dist/Qobuz-DL-GUI
echo "Output: dist/Qobuz-DL-GUI"
