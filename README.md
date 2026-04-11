# Qobuz-DL: The Modern Music Experience

![Qobuz-DL GUI Hero](C:/Users/peyto/.gemini/antigravity/brain/7a7177d4-39b8-43fb-b2d3-8f9934e90ba7/qobuz_dl_gui_hero_1775882161603.png)

### Search, explore, and download Lossless and Hi-Res music from Qobuz with a beautiful, high-density interface.

---

## A Complete GUI Overhaul

This fork of **qobuz-dl** transforms the reliable downloader into a premium desktop-grade web application. Forget the terminal—experience your music collection with rich metadata, visual badges, and a streamlined workflow.

### Key Features
*   **High-Density Visuals**: View album art, "Explicit" content tags, and "Hi-Res" quality badges at a glance.
*   **Unified Download Queue**: Track multiple downloads in real-time with detailed metadata (Bit Depth, Sample Rate, Track Count, and Release Year).
*   **Advanced Metadata Resolution**: Every search result and queue item is enriched with granular technical details pulled directly from the Qobuz API.
*   **Native OAuth Support**: Seamlessly login using the official Qobuz website—no more manual token digging.
*   **Pro Configuration**: Manage your naming templates (Folder/Track) with interactive tooltips and instant examples.

---

## Getting Started

### 1. Installation
Install the package and its requirements via pip:

```bash
pip install --upgrade qobuz-dl
```

### 2. Launch the Interface
**Windows:**
Simply run the included `launch_gui.bat` or type:
```bash
qobuz-dl-gui
```

**Linux / macOS:**
Run the included `launch_gui.sh` or type:
```bash
qobuz-dl-gui
```

The app will automatically open your browser to `http://127.0.0.1:5000`.

---

## Advanced Settings
The GUI provides a full **Configuration Manager** where you can:
- **Set Quality**: Toggle between MP3, CD Lossless, and Hi-Res (up to 24-bit/192kHz).
- **Custom Naming**: Use variables like `{artist}`, `{album}`, `{year}`, and `{bit_depth}` to organize your library exactly how you want.
- **Library Database**: Built-in duplicate checking ensures you never download the same track twice.

---

## Command Line Interface (CLI)
For power users who prefer the terminal or want to automate downloads via scripting, the full original CLI is still available.

[View CLI Documentation](CLI.md)

---

## ⚖️ Disclaimer
* This tool is for educational purposes. Please respect the [Qobuz API Terms of Use](https://static.qobuz.com/apps/api/QobuzAPI-TermsofUse.pdf).
* **qobuz-dl** is not affiliated with Qobuz.

---

### Support the Project

**Donate to GUI dev (Monero)**
[![Donate Monero](https://img.shields.io/badge/Donate-Monero-orange.svg)](monero:8BuFrF3pnaFDXZLkzNX3NKG7hdMr1YqZaAvasSyfSbJnLadCUgXuJQQVigeBBAZdL5NTRiUcPYNVTV2gUWa7zuhuMRVNwt9)
[![QR Code](https://img.shields.io/badge/QR_Code-orange.svg)](https://raw.githubusercontent.com/peykc/qobuz-dl-gui/blob/master/qobuz_dl/gui/monero_qr.png)

**Donate to CLI dev (PayPal)**
[![Donate PayPal](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=VZWSWVGZGJRMU&source=url)
