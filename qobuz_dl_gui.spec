# -*- mode: python ; coding: utf-8 -*-
# One-file GUI (Flask + pywebview). Build on the target OS only:
#   pip install -r requirements.txt -r requirements-build.txt
#   pyinstaller --noconfirm qobuz_dl_gui.spec
#
# Outputs:
#   Windows: dist/Qobuz-DL-GUI.exe   (close running EXE before rebuild)
#   Linux:   dist/Qobuz-DL-GUI       (chmod +x; needs WebKitGTK at runtime)
#   macOS:   dist/Qobuz-DL-GUI.app  (bundle; may need Gatekeeper override)
import os
import sys

block_cipher = None

spec_root = os.path.dirname(os.path.abspath(SPEC))
is_darwin = sys.platform == "darwin"
is_win = sys.platform == "win32"

gui_dir = os.path.join(spec_root, "qobuz_dl", "gui")
datas = [(gui_dir, "qobuz_dl/gui")]

a = Analysis(
    [os.path.join(spec_root, "qobuz_dl", "gui_app.py")],
    pathex=[spec_root],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "qobuz_dl",
        "qobuz_dl.bundle",
        "qobuz_dl.cli",
        "qobuz_dl.color",
        "qobuz_dl.commands",
        "qobuz_dl.core",
        "qobuz_dl.db",
        "qobuz_dl.downloader",
        "qobuz_dl.exceptions",
        "qobuz_dl.metadata",
        "qobuz_dl.qopy",
        "qobuz_dl.utils",
        "qobuz_dl.version",
        "qobuz_dl.updater",
        "qobuz_dl.lyrics",
        "packaging",
        "packaging.version",
        "bottle",
        "proxy_tools",
        "webview",
        "webview.http",
        "webview.platforms",
        "pyperclip",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Qobuz-DL-GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=is_darwin,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if is_darwin:
    app = BUNDLE(
        exe,
        name="Qobuz-DL-GUI.app",
        icon=None,
        bundle_identifier="com.github.peykc.qobuz-dl-gui",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleName": "Qobuz-DL-GUI",
            "CFBundleDisplayName": "Qobuz-DL",
        },
    )
