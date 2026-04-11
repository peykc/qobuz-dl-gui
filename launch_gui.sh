#!/bin/bash
echo "Starting Qobuz-DL GUI..."

# Check if qobuz-dl-gui command is available (installed via pip)
if command -v qobuz-dl-gui &> /dev/null
then
    qobuz-dl-gui
else
    # Fallback to running the script directly
    python3 -m qobuz_dl.gui_app
fi
