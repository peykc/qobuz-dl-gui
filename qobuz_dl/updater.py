"""GitHub Releases: check for updates; Windows frozen EXE in-place swap."""

from __future__ import annotations

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
            return path
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise


def apply_update_windows(downloaded_exe: str) -> None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-install is only for the frozen Windows EXE")

    current = os.path.abspath(sys.executable)
    old = current + ".old"

    if os.path.isfile(old):
        try:
            os.remove(old)
        except OSError:
            pass

    os.rename(current, old)
    shutil.copy2(downloaded_exe, current)

    creation = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation |= subprocess.DETACHED_PROCESS

    subprocess.Popen(
        [current],
        close_fds=True,
        creationflags=creation,
        cwd=os.path.dirname(current) or None,
    )
    os._exit(0)


def schedule_apply_update(downloaded_exe: str, delay: float = 0.35) -> None:
    def run():
        time.sleep(delay)
        try:
            apply_update_windows(downloaded_exe)
        except Exception as e:
            logging.error("Apply update failed: %s", e)

    threading.Thread(target=run, daemon=True).start()
