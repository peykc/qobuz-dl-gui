# Qobuz-DL-GUI: modern search, queue, and download

**Version 1.1.2** · Desktop app for lossless and Hi-Res downloads from Qobuz: rich metadata, OAuth login, synced lyrics, and a dense UI built for real libraries.

---

## Main: search and download in the app

Use the sidebar search to find albums and tracks, inspect quality and metadata, add releases to the queue, and run downloads while watching progress and download history inside the app.

![Search, queue, and download in Qobuz-DL-GUI](https://raw.githubusercontent.com/peykc/qobuz-dl-gui/master/assets/main.gif)

---

## Drag: queue from the browser

Drag album or track URLs from the Qobuz web player (or tabs) into the app to mass-queue links without copy-paste, ideal when you are browsing and want to batch everything into one session.

![Drag URLs from the browser into the app for mass queueing](https://raw.githubusercontent.com/peykc/qobuz-dl-gui/master/assets/drag.gif)

---

## Settings: configuration tour

Open settings to walk quality tiers, folder/track naming templates, duplicate checks, synced lyrics options, and other behavior so your library layout and tags stay consistent release after release.

![Tour of settings and configuration](https://raw.githubusercontent.com/peykc/qobuz-dl-gui/master/assets/settings.gif)

---

## Lyrics: download → match → preview

After tracks download, open lyric search (LRCLIB), review matches, attach `.lrc` sidecars next to your files, and preview synced playback so you know what hits your folder before you leave the app.

![From download through lyric search and lyric playback](https://raw.githubusercontent.com/peykc/qobuz-dl-gui/master/assets/lyric.gif)

---

## Highlights

- **High-density visuals:** Album art, explicit tags, Hi-Res cues, and technical detail from the Qobuz API on results and queue rows.
- **Unified queue:** Multiple URLs and releases with live status (bit depth, sample rate, tracks, year).
- **OAuth:** Sign in through the official Qobuz site; no manual token hunting.
- **Naming templates:** Folder and track patterns with variables such as `{artist}`, `{album}`, `{year}`, `{bit_depth}`.
- **Library database:** Optional duplicate awareness so you do not re-grab the same rips blindly.
- **Synced lyrics:** Optional `.lrc` via the public [LRCLIB](https://lrclib.net) API (`/api/get`, `/api/search`).
- **Lucky queue:** Pick how many releases to add at random from search, then start when you are ready (no separate GIF; use it from the search panel).

---

## Getting started

### Install

```bash
pip install git+https://github.com/peykc/qobuz-dl-gui.git
```

Or from PyPI when published:

```bash
pip install --upgrade qobuz-dl
```

### Launch

**Windows:** run `launch_gui.bat`, or:

```bash
qobuz-dl-gui
```

**Linux / macOS:**

```bash
./launch_gui.sh
# or
qobuz-dl-gui
```

The GUI uses [pywebview](https://github.com/r0x0r/pywebview) (on Windows, **Edge WebView2**). Set `QOBUZ_DL_GUI_BROWSER=1` to open in your system browser at `http://127.0.0.1` instead.

### Pre-built binaries ([Releases](https://github.com/peykc/qobuz-dl-gui/releases))

| Platform | Artifact | Notes |
|----------|----------|--------|
| **Windows** | `Qobuz-DL-GUI-Windows-x64.exe` | No Python install. [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) if the shell does not render. In-app updates expect this asset name pattern. |
| **Linux** | `Qobuz-DL-GUI-Linux-x64` | `chmod +x`. Needs WebKitGTK/GTK per [pywebview Linux notes](https://pywebview.flowrl.com/guide/installation.html#linux). |
| **macOS** | `Qobuz-DL-GUI-macOS-x64.zip` | Unzip and open `Qobuz-DL-GUI.app`. Unsigned: right-click → **Open** if Gatekeeper warns. |

Pushing a Git tag `v*` runs [.github/workflows/build-desktop.yml](.github/workflows/build-desktop.yml) and attaches builds to that release. **Actions → Build desktop → Run workflow** produces the same artifacts without a release.

---

## CLI

The original terminal workflow is still shipped for scripting and automation.

[CLI documentation](CLI.md)

---

## Disclaimer

- For educational use. Respect the [Qobuz API Terms of Use](https://static.qobuz.com/apps/api/QobuzAPI-TermsofUse.pdf).
- **qobuz-dl** / **Qobuz-DL-GUI** are not affiliated with Qobuz.

---

### Support

**GUI (Monero)**  
[![Donate Monero](https://img.shields.io/badge/Donate-Monero-orange.svg)](https://peykc.github.io/pktree/?pay=monero)

**CLI upstream (PayPal)**  
[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=VZWSWVGZGJRMU&source=url)

