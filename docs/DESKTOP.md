# Desktop Install And Build Notes

## Subscription Requirement

Qobuz-DL-GUI requires an active Qobuz streaming subscription. Free accounts and unavailable/purchase-only releases may not be eligible to stream or download.

## Prebuilt Releases

Download desktop builds from [GitHub Releases](https://github.com/peykc/qobuz-dl-gui/releases).

| Platform | Artifact | Notes |
| --- | --- | --- |
| Windows | `Qobuz-DL-GUI-Windows-x64.exe` | Portable EXE. In-app updates can replace this EXE automatically. |
| Linux | `Qobuz-DL-GUI-Linux-x64` | Run `chmod +x Qobuz-DL-GUI-Linux-x64`. Uses pywebview when GTK/WebKitGTK is available; otherwise opens in the system browser. In-app updates can replace this binary automatically. |
| macOS | `Qobuz-DL-GUI-macOS-x64.zip` | Unzip and open `Qobuz-DL-GUI.app`. Unsigned builds may require right-click -> Open. In-app checks link to the correct release asset; auto-install is not enabled yet. |

## Install From Source

```bash
pip install git+https://github.com/peykc/qobuz-dl-gui.git
qobuz-dl-gui
```

When published to PyPI:

```bash
pip install --upgrade qobuz-dl
qobuz-dl-gui
```

## Launch Scripts

Windows:

```powershell
launch_gui.bat
```

Linux/macOS:

```bash
./launch_gui.sh
```

## Browser Mode

The app normally opens in an embedded pywebview window. To use your system browser instead:

```bash
QOBUZ_DL_GUI_BROWSER=1 qobuz-dl-gui
```

On Windows PowerShell:

```powershell
$env:QOBUZ_DL_GUI_BROWSER="1"
qobuz-dl-gui
```

## Build From Source

Install dependencies and run PyInstaller on the target OS. Cross-compiling desktop builds is not supported.

Windows:

```powershell
.\scripts\build_windows.ps1
```

Linux:

```bash
./scripts/build_linux.sh
```

macOS:

```bash
./scripts/build_macos.sh
```

## Release Workflow

Pushing a Git tag matching `v*` runs `.github/workflows/build-desktop.yml` and attaches the Windows, Linux, and macOS artifacts to a draft GitHub release. You can also run **Actions -> Build desktop -> Run workflow** to produce artifacts without publishing a release.
