# Qobuz-DL-GUI

Search, queue, and download music from Qobuz in a desktop app built for library management, metadata, synced lyrics, and repeatable workflows.

> **Requires an active Qobuz streaming subscription.** Free accounts, region-locked content, and purchase-only releases may not be streamable or downloadable.

![Search, queue, and download albums](assets/main.gif)

[View the full visual feature guide](docs/FEATURES.md)

## Download Latest

| Platform | File | Notes |
| --- | --- | --- |
| Windows | [![Download for Windows](https://img.shields.io/badge/DOWNLOAD-038a87?style=for-the-badge&logo=data:image/svg%2Bxml%3Bbase64%2CPD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0iVVRGLTgiPz4KPHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHhtbG5zOmNjPSJodHRwOi8vY3JlYXRpdmVjb21tb25zLm9yZy9ucyMiIHhtbG5zOmRjPSJodHRwOi8vcHVybC5vcmcvZGMvZWxlbWVudHMvMS4xLyIgeG1sbnM6aW5rc2NhcGU9Imh0dHA6Ly93d3cuaW5rc2NhcGUub3JnL25hbWVzcGFjZXMvaW5rc2NhcGUiIHhtbG5zOnJkZj0iaHR0cDovL3d3dy5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyIgeG1sbnM6c29kaXBvZGk9Imh0dHA6Ly9zb2RpcG9kaS5zb3VyY2Vmb3JnZS5uZXQvRFREL3NvZGlwb2RpLTAuZHRkIiB4bWxuczpzdmc9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIiBoZWlnaHQ9IjUxMiIgaWQ9IkxheWVyXzEiIHZlcnNpb249IjEuMSIgdmlld0JveD0iMCAwIDUxMi4wMDAwMyA1MTIiIHdpZHRoPSI1MTIiIHhtbDpzcGFjZT0icHJlc2VydmUiPgogIDxkZWZzIGlkPSJkZWZzNyI%2BPC9kZWZzPgogIDxnIGlkPSJnNDQ5MiIgdHJhbnNmb3JtPSJ0cmFuc2xhdGUoMTM2LjE3ODYsMTA4LjI1MDAxKSI%2BCiAgICA8cGF0aCBkPSJtIC03MzMuNjIzMjksNzIuMjY3OTQ0IGMgMCwyMDMuODA0ODc2IC0xNjUuMjE2NDksMzY5LjAyMTM2NiAtMzY5LjAyMTQxLDM2OS4wMjEzNjYgLTIwMy44MDQ4LDAgLTM2OS4wMjEzLC0xNjUuMjE2NDkgLTM2OS4wMjEzLC0zNjkuMDIxMzY2IDAsLTIwMy44MDQ4NzQgMTY1LjIxNjUsLTM2OS4wMjEzNjQgMzY5LjAyMTMsLTM2OS4wMjEzNjQgMjAzLjgwNDkyLDAgMzY5LjAyMTQxLDE2NS4yMTY0OSAzNjkuMDIxNDEsMzY5LjAyMTM2NCB6IiBpZD0icGF0aDUwMjIiIHN0eWxlPSJmaWxsOiMwMDAwMDA7ZmlsbC1vcGFjaXR5OjE7ZmlsbC1ydWxlOm5vbnplcm87c3Ryb2tlOm5vbmUiIHRyYW5zZm9ybT0ibWF0cml4KDAuNjkzNzI2ODIsMCwwLDAuNjkzNzI2ODIsODg0Ljc1NTU4LDk3LjYxNTc4MikiPjwvcGF0aD4KICAgIDxnIGlkPSJnNDM5MCIgdHJhbnNmb3JtPSJtYXRyaXgoMS4xOTI5MTcsMCwwLDEuMTkyOTE3LC0yMTM2LjU3NjYsLTE3NTkuOTM1KSI%2BCiAgICAgIDxwb2x5Z29uIGlkPSJwb2x5Z29uMTU0NjciIHBvaW50cz0iMTUsMTUgMTUsMi41IDMyLDAgMzIsMTUgIiBzdHlsZT0iZmlsbDojZmZmZmZmO2ZpbGwtb3BhY2l0eToxIiB0cmFuc2Zvcm09Im1hdHJpeCg4LjkwNjczOTIsMCwwLDguOTA2NzM5MiwxNzMxLjMyNTIsMTQ1Ni42Njg5KSI%2BPC9wb2x5Z29uPgogICAgICA8cG9seWdvbiBpZD0icG9seWdvbjE1NDY5IiBwb2ludHM9IjAsMTUgMCw0LjcwMyAxMywyLjc5NyAxMywxNSAiIHN0eWxlPSJmaWxsOiNmZmZmZmY7ZmlsbC1vcGFjaXR5OjEiIHRyYW5zZm9ybT0ibWF0cml4KDguOTA2NzM5MiwwLDAsOC45MDY3MzkyLDE3MzEuMzI1MiwxNDU2LjY2ODkpIj48L3BvbHlnb24%2BCiAgICAgIDxwb2x5Z29uIGlkPSJwb2x5Z29uMTU0NzEiIHBvaW50cz0iMTUsMTcgMTUsMjkuNSAzMiwzMiAzMiwxNyAiIHN0eWxlPSJmaWxsOiNmZmZmZmY7ZmlsbC1vcGFjaXR5OjEiIHRyYW5zZm9ybT0ibWF0cml4KDguOTA2NzM5MiwwLDAsOC45MDY3MzkyLDE3MzEuMzI1MiwxNDU2LjY2ODkpIj48L3BvbHlnb24%2BCiAgICAgIDxwb2x5Z29uIGlkPSJwb2x5Z29uMTU0NzMiIHBvaW50cz0iMCwxNyAwLDI3LjI5NyAxMywyOS4yMDMgMTMsMTcgIiBzdHlsZT0iZmlsbDojZmZmZmZmO2ZpbGwtb3BhY2l0eToxIiB0cmFuc2Zvcm09Im1hdHJpeCg4LjkwNjczOTIsMCwwLDguOTA2NzM5MiwxNzMxLjMyNTIsMTQ1Ni42Njg5KSI%2BPC9wb2x5Z29uPgogICAgPC9nPgogIDwvZz4KPC9zdmc%2BCg==&logoColor=white)](https://github.com/peykc/qobuz-dl-gui/releases/latest/download/Qobuz-DL-GUI-Windows-x64.exe) | Portable EXE. In-app updates are supported. |
| Linux | [![Download for Linux](https://img.shields.io/badge/DOWNLOAD-038a87?style=for-the-badge&logo=linux&logoColor=white)](https://github.com/peykc/qobuz-dl-gui/releases/latest/download/Qobuz-DL-GUI-Linux-x64) | Run `chmod +x Qobuz-DL-GUI-Linux-x64`. In-app updates are supported. |
| macOS | [![Download for macOS](https://img.shields.io/badge/DOWNLOAD-038a87?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/peykc/qobuz-dl-gui/releases/latest/download/Qobuz-DL-GUI-macOS-x64.zip) | Unzip and open the app. Unsigned builds may require right-click -> Open. |

![Total Downloads](https://img.shields.io/github/downloads/peykc/qobuz-dl-gui/total)

Older builds and release notes are available on [GitHub Releases](https://github.com/peykc/qobuz-dl-gui/releases).

## What It Does

**Search and queue quickly.** Find music in Qobuz, paste URLs, or drag releases from the Qobuz website into the app.

**Download cleanly.** Save lossless and Hi-Res audio with artwork, metadata, naming templates, and duplicate awareness.

**Handle the messy parts.** Preview synced lyrics, replace unavailable tracks, or create `.missing.txt` placeholders for purchase-only songs.


## Product Tour

### Queue From Qobuz

Drag albums or tracks from the Qobuz website directly into the app.

![Drag Qobuz albums into the app](assets/drag.gif)

### Synced Lyrics

Download a track, find synced lyrics, preview them against audio playback, and attach the result.

![Find and preview synced lyrics](assets/lyric.gif)

### Replacement Tracks

When a release has an unavailable track, search for a streamable replacement or create a `.missing.txt` placeholder.

![Replace an unavailable track](assets/replace.gif)

## Documentation

- [Feature guide](docs/FEATURES.md)
- [Desktop install and build notes](docs/DESKTOP.md)
- [Command line interface](CLI.md)

## Install From Source

```bash
pip install git+https://github.com/peykc/qobuz-dl-gui.git
qobuz-dl-gui
```

The desktop GUI uses pywebview when available. To open in your system browser instead:

```bash
QOBUZ_DL_GUI_BROWSER=1 qobuz-dl-gui
```

## Disclaimer

Qobuz-DL-GUI is not affiliated with Qobuz. Use it responsibly and respect the [Qobuz API Terms of Use](https://static.qobuz.com/apps/api/QobuzAPI-TermsofUse.pdf).

## Support

**GUI development (Monero)**

[![Donate Monero](https://img.shields.io/badge/Donate-Monero-orange.svg)](https://peykc.github.io/pktree/?pay=monero)

**Original CLI project (PayPal)**

[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=VZWSWVGZGJRMU&source=url)
