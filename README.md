# Qobuz-DL-GUI

Search, queue, and download music from Qobuz in a desktop app built for library management, metadata, synced lyrics, and repeatable workflows.

> **Requires an active Qobuz streaming subscription.** Free accounts, region-locked content, and purchase-only releases may not be streamable or downloadable.

![Search, queue, and download albums](assets/main.gif)

[View the full visual feature guide](docs/FEATURES.md)

## Built For

| Workflow | What you get |
| --- | --- |
| Fast queue building | Search Qobuz, drag links from the website, or paste URLs into one download queue. |
| Clean library output | Lossless and Hi-Res downloads with artwork, Qobuz metadata, naming templates, and duplicate awareness. |
| Lyrics that match | Find, preview, and attach synced LRCLIB lyrics while listening against the downloaded track. |
| Imperfect releases | Replace unavailable tracks or create clear `.missing.txt` placeholders when Qobuz marks songs purchase-only. |
| Day-to-day maintenance | OAuth login, in-app update checks, settings tooltips, and built-in feedback reporting. |

## Download

Get the latest build from [GitHub Releases](https://github.com/peykc/qobuz-dl-gui/releases).

| Platform | File | Notes |
| --- | --- | --- |
| Windows | `Qobuz-DL-GUI-Windows-x64.exe` | Portable EXE. In-app updates are supported. |
| Linux | `Qobuz-DL-GUI-Linux-x64` | Run `chmod +x Qobuz-DL-GUI-Linux-x64`. In-app updates are supported. |
| macOS | `Qobuz-DL-GUI-macOS-x64.zip` | Unzip and open the app. Unsigned builds may require right-click -> Open. |

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

More workflows are covered in the [feature guide](docs/FEATURES.md).

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
