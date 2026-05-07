"""Application version and GitHub Releases source for in-app updates."""

import os

__version__ = "1.2.2"

# In-app update checks use:
#   GET https://api.github.com/repos/{GITHUB_RELEASE_REPO}/releases/latest
# Override with env QOBUZ_DL_UPDATE_REPO=owner/repo if needed.
# Releases should include platform assets named like:
#   Qobuz-DL-GUI-Windows-x64.exe
#   Qobuz-DL-GUI-Linux-x64
#   Qobuz-DL-GUI-macOS-x64.zip
GITHUB_RELEASE_REPO = os.environ.get(
    "QOBUZ_DL_UPDATE_REPO",
    "peykc/qobuz-dl-gui",
).strip()
