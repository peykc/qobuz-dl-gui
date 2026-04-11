# Qobuz-DL: Command Line Interface Documentation

While the modern Web GUI is the recommended way to use **qobuz-dl**, the powerful Command Line Interface (CLI) is still fully supported for advanced users, script integration, and headless environments.

## Installation

### Linux / macOS
```bash
pip3 install --upgrade qobuz-dl
```

### Windows
```powershell
pip3 install windows-curses
pip3 install --upgrade qobuz-dl
```

## CLI Modes

### 1. Download Mode (`dl`)
Download specific URLs or local text files containing lists of URLs.

**Basic usage:**
```bash
qobuz-dl dl [URL] [OPTIONS]
```

**Examples:**
* Download in 24-bit/96kHz quality:
  `qobuz-dl dl https://play.qobuz.com/album/qxjbxh1dc3xyb -q 7`
* Download multiple URLs to a custom directory:
  `qobuz-dl dl URL1 URL2 -d "My Downloads"`
* Download from a text file:
  `qobuz-dl dl urls.txt`
* Download a label and embed art:
  `qobuz-dl dl https://play.qobuz.com/label/7526 --embed-art`
* Download artist discography (excluding singles/EPs):
  `qobuz-dl dl https://play.qobuz.com/artist/2528676 --albums-only`

### 2. Interactive Mode (`fun`)
Search and explore Qobuz directly from your terminal.

```bash
qobuz-dl fun -l 10
```
This will open an interactive search where you can select specific releases to download.

### 3. Lucky Mode (`lucky`)
Download the first result for a search query immediately.

```bash
qobuz-dl lucky "playboi carti die lit"
qobuz-dl lucky "eric dolphy" --type artist -n 3
```

## Global Options & Usage

```text
usage: qobuz-dl [-h] [-r] {fun,dl,lucky} ...

optional arguments:
  -h, --help      show this help message and exit
  -r, --reset     create/reset config file
  -p, --purge     purge/delete downloaded-IDs database

commands:
  fun           interactive mode
  dl            input mode
  lucky         lucky mode
```

## Module Usage (Python API)

You can use `qobuz-dl` directly in your own Python scripts:

```python
import logging
from qobuz_dl.core import QobuzDL

logging.basicConfig(level=logging.INFO)

qobuz = QobuzDL()
qobuz.get_tokens() 
qobuz.initialize_client("email", "password", qobuz.app_id, qobuz.secrets)

qobuz.handle_url("https://play.qobuz.com/album/va4j3hdlwaubc")
```

---
*For the modern visual experience, use the [Web GUI](README.md).*
