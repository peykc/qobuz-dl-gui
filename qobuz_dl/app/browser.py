"""Open URLs / external tools without PyInstaller library-path pollution."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import webbrowser
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_LINUX_OPENERS = ("xdg-open", "gio")


def env_for_external_process(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return an env suitable for spawning system binaries from a frozen app.

    PyInstaller injects its unpack dir into ``LD_LIBRARY_PATH``. Child processes
    like ``/bin/sh`` / ``xdg-open`` then load bundled libs (e.g. readline) and
    fail with symbol errors such as ``rl_print_keybinding``.
    """
    env = dict(base if base is not None else os.environ)
    if not sys.platform.startswith("linux"):
        return env
    if not getattr(sys, "frozen", False):
        return env

    for key in ("LD_LIBRARY_PATH", "LD_PRELOAD"):
        orig_key = f"{key}_ORIG"
        if orig_key in env:
            orig = env.pop(orig_key)
            if orig:
                env[key] = orig
            else:
                env.pop(key, None)
        else:
            env.pop(key, None)
    return env


def open_url(url: str) -> bool:
    """Open ``url`` in the system browser. Returns True if launch was attempted successfully."""
    url = (url or "").strip()
    if not url:
        return False

    if sys.platform.startswith("linux"):
        env = env_for_external_process()
        for cmd in _LINUX_OPENERS:
            if cmd == "gio":
                argv = ["gio", "open", url]
                which = shutil.which("gio")
            else:
                argv = [cmd, url]
                which = shutil.which(cmd)
            if not which:
                continue
            try:
                subprocess.Popen(
                    argv,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
                return True
            except OSError as exc:
                logger.debug("Failed to open URL with %s: %s", argv[0], exc)

    try:
        opened = bool(webbrowser.open(url))
        if not opened:
            logger.warning("Could not open browser for URL: %s", url)
        return opened
    except Exception as exc:
        logger.warning("Could not open browser for URL %s: %s", url, exc)
        return False
