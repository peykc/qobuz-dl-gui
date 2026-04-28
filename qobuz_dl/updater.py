"""GitHub Releases: check for updates; Windows frozen EXE in-place swap."""

from __future__ import annotations

import ctypes
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

import requests

from qobuz_dl.version import GITHUB_RELEASE_REPO, __version__

LAST_CHECK_FILE = "last_update_check_ts"
CHECK_INTERVAL_SEC = 24 * 3600


def cleanup_stale_exe_backup() -> None:
    """Remove leftover .old from a previous auto-update (Windows)."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    old = os.path.abspath(sys.executable) + ".old"
    if os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass


def _releases_download_prefix(repo: str) -> str:
    r = repo.strip().strip("/")
    return f"https://github.com/{r}/releases/download/".lower()


def is_safe_release_asset_url(url: str, repo: str) -> bool:
    if not url or not repo:
        return False
    u = url.strip().lower()
    if not u.endswith(".exe"):
        return False
    return u.startswith(_releases_download_prefix(repo))


def pick_exe_asset(assets: list, repo: str) -> tuple[str | None, str | None]:
    prefix = _releases_download_prefix(repo)
    candidates: list[tuple[str, str]] = []
    for a in assets or []:
        url = a.get("browser_download_url") or ""
        name = a.get("name") or ""
        if not url.lower().startswith(prefix):
            continue
        if not name.lower().endswith(".exe"):
            continue
        candidates.append((url, name))
    for url, name in candidates:
        if "qobuz-dl-gui" in name.lower().replace("_", "-"):
            return url, name
    if candidates:
        return candidates[0]
    return None, None


def tag_to_version(tag: str) -> str:
    return re.sub(r"^v+", "", (tag or "").strip(), flags=re.I)


def should_hit_network(config_dir: str, force: bool, interval: float = CHECK_INTERVAL_SEC) -> bool:
    if force:
        return True
    path = os.path.join(config_dir, LAST_CHECK_FILE)
    try:
        if not os.path.isfile(path):
            return True
        with open(path, encoding="utf-8") as f:
            last = float(f.read().strip())
        return time.time() - last >= interval
    except Exception:
        return True


def record_check(config_dir: str) -> None:
    try:
        os.makedirs(config_dir, exist_ok=True)
        path = os.path.join(config_dir, LAST_CHECK_FILE)
        with open(path, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def fetch_latest_release(repo: str) -> dict:
    api = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"Qobuz-DL-GUI/{__version__}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    r = requests.get(api, headers=headers, timeout=25)
    r.raise_for_status()
    return r.json()


def check_for_update(config_dir: str, *, force: bool = False) -> dict:
    repo = GITHUB_RELEASE_REPO.strip()
    if not repo or "/" not in repo:
        return {
            "ok": True,
            "skipped": True,
            "reason": "repo_not_configured",
            "current_version": __version__,
        }

    if not should_hit_network(config_dir, force):
        return {
            "ok": True,
            "skipped": True,
            "reason": "throttled",
            "current_version": __version__,
        }

    try:
        data = fetch_latest_release(repo)
    except Exception as e:
        logging.warning("Update check failed: %s", e)
        return {"ok": False, "error": str(e), "current_version": __version__}

    record_check(config_dir)

    tag = data.get("tag_name") or ""
    latest_ver = tag_to_version(tag)
    try:
        from packaging.version import parse as vparse

        update_available = vparse(latest_ver) > vparse(__version__)
    except Exception:
        update_available = latest_ver != __version__

    dl_url, asset_name = pick_exe_asset(data.get("assets") or [], repo)
    html_url = data.get("html_url") or ""

    frozen_win = bool(getattr(sys, "frozen", False) and os.name == "nt")
    can_auto = bool(update_available and dl_url and frozen_win)

    return {
        "ok": True,
        "skipped": False,
        "current_version": __version__,
        "latest_version": latest_ver,
        "tag_name": tag,
        "update_available": update_available,
        "release_page": html_url,
        "download_url": dl_url if update_available else None,
        "asset_name": asset_name,
        "can_auto_install": can_auto,
        "frozen": getattr(sys, "frozen", False),
    }


def _verify_windows_pe(path: str) -> None:
    """Reject truncated or non-EXE downloads before swapping the running binary."""
    try:
        sz = os.path.getsize(path)
    except OSError as e:
        raise RuntimeError(f"Cannot read downloaded update: {e}") from e
    if sz < 512 * 1024:
        raise RuntimeError(
            f"Downloaded file is too small ({sz} bytes) to be a valid installer."
        )
    try:
        with open(path, "rb") as f:
            sig = f.read(2)
    except OSError as e:
        raise RuntimeError(f"Cannot read downloaded update: {e}") from e
    if sig != b"MZ":
        raise RuntimeError("Downloaded file is not a valid Windows executable (missing MZ header).")


def download_update_to_temp(url: str) -> str:
    headers = {"User-Agent": f"Qobuz-DL-GUI/{__version__}"}
    with requests.get(url, headers=headers, timeout=180, stream=True) as r:
        r.raise_for_status()
        fd, path = tempfile.mkstemp(suffix=".exe", prefix="qobuz_gui_upd_")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
            _verify_windows_pe(path)
            return path
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise


def swap_windows_exe_inplace(downloaded_exe: str) -> tuple[str, str]:
    """Rename running exe to ``.old``, copy ``downloaded_exe`` into place, verify PE.

    Returns ``(current_exe_path, old_exe_path)``. Does not launch or exit.
    """
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-install is only for the frozen Windows EXE")

    _verify_windows_pe(downloaded_exe)

    current = os.path.abspath(sys.executable)
    old = current + ".old"

    if os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass

    try:
        os.rename(current, old)
    except OSError as e:
        raise RuntimeError(
            "Could not rename the running executable (close other instances or "
            "install updates manually from GitHub Releases)."
        ) from e
    try:
        shutil.copy2(downloaded_exe, current)
        _verify_windows_pe(current)
    except Exception:
        try:
            if os.path.isfile(current):
                os.remove(current)
        except OSError:
            pass
        try:
            os.rename(old, current)
        except OSError:
            logging.error(
                "Update failed and could not restore previous exe; reinstall from "
                "https://github.com/%s/releases",
                GITHUB_RELEASE_REPO,
            )
        raise

    return current, old


def restart_after_swap(current_exe: str, backup_exe: str | None) -> None:
    """Start the new exe detached, pause, then terminate this process."""
    creation = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation |= subprocess.DETACHED_PROCESS

    # PyInstaller onefile (6.9+): a child that outlives this process must unpack
    # independently. Without this, the new exe may inherit _MEIPASS / DLL search
    # state and block cleanup — "[PYI-…] Failed to remove temporary directory".
    # https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass

    try:
        subprocess.Popen(
            [current_exe],
            cwd=os.path.dirname(current_exe) or None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
            shell=False,
        )
    except OSError as e:
        if backup_exe and os.path.isfile(backup_exe):
            try:
                if os.path.isfile(current_exe):
                    os.remove(current_exe)
                os.rename(backup_exe, current_exe)
            except OSError:
                logging.error(
                    "Could not roll back after failed restart; reinstall from "
                    "https://github.com/%s/releases",
                    GITHUB_RELEASE_REPO,
                )
        raise RuntimeError(f"Could not start updated application: {e}") from e

    time.sleep(1.6)
    os._exit(0)


def apply_update_windows(downloaded_exe: str) -> None:
    """Swap on disk, then spawn new process and exit (used by tests or manual calls)."""
    current, old = swap_windows_exe_inplace(downloaded_exe)
    restart_after_swap(current, old)


def schedule_restart_only(
    current_exe: str, backup_exe: str | None, delay: float = 0.25
) -> None:
    """After swap succeeded and HTTP responded: spawn new EXE and exit this process."""

    def run():
        time.sleep(delay)
        try:
            restart_after_swap(current_exe, backup_exe)
        except Exception as e:
            logging.error("Restart after update failed: %s", e)

    threading.Thread(target=run, daemon=True).start()
