"""Application version and GitHub Releases source for in-app updates."""

import os

__version__ = "1.1.2"

# In-app update checks use:
#   GET https://api.github.com/repos/{GITHUB_RELEASE_REPO}/releases/latest
# Override with env QOBUZ_DL_UPDATE_REPO=owner/repo if needed.
# Releases must include a Windows asset whose name contains "Qobuz-DL-GUI" and ends with ".exe".
GITHUB_RELEASE_REPO = os.environ.get(
    "QOBUZ_DL_UPDATE_REPO",
    "peykc/qobuz-dl-gui",
).strip()
