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
    """Remove leftover .old from a previous auto-update (Windows) in a background thread."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return
    current = os.path.abspath(sys.executable)
    app_dir = os.path.dirname(current)
    prefix = os.path.basename(current) + ".old"
    old_paths = [
        os.path.join(app_dir, name)
        for name in os.listdir(app_dir)
        if name == prefix or name.startswith(prefix + ".")
    ]
    if not old_paths:
        return

    def _wait_and_clean():
        # The parent process takes a moment to exit. We retry indefinitely
        # (every 3 seconds) until the lock is released or the file is gone.
        while True:
            time.sleep(3.0)
            remaining = [path for path in old_paths if os.path.isfile(path)]
            if not remaining:
                break
            for old in remaining:
                try:
                    os.remove(old)
                    logging.info("Cleaned up stale update backup: %s", old)
                except OSError:
                    pass

    threading.Thread(target=_wait_and_clean, daemon=True).start()


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell_exe() -> str:
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    bundled = os.path.join(
        system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"
    )
    if os.path.isfile(bundled):
        return bundled
    return "powershell.exe"


def _write_windows_update_helper(current_exe: str, downloaded_exe: str) -> str:
    """Create a hidden PowerShell helper that performs the update after exit."""
    parent_pid = os.getpid()
    fd, helper = tempfile.mkstemp(suffix=".ps1", prefix="qobuz_gui_update_")
    os.close(fd)
    helper_q = _ps_quote(helper)
    current_q = _ps_quote(current_exe)
    update_q = _ps_quote(downloaded_exe)
    workdir_q = _ps_quote(os.path.dirname(current_exe) or os.getcwd())
    log_q = _ps_quote(os.path.join(tempfile.gettempdir(), "qobuz_gui_update.log"))
    script = [
        "$ErrorActionPreference = 'Stop'",
        f"$log = {log_q}",
        "function Log([string]$Message) {",
        "    $ts = [DateTimeOffset]::Now.ToString('yyyy-MM-dd HH:mm:ss.fff zzz')",
        "    Add-Content -LiteralPath $log -Value \"$ts $Message\" -Encoding UTF8",
        "}",
        "Log 'helper-start'",
        "[Environment]::SetEnvironmentVariable('PYINSTALLER_RESET_ENVIRONMENT', '1', 'Process')",
        f"$parentPid = {parent_pid}",
        f"$exe = {current_q}",
        f"$update = {update_q}",
        f"$workdir = {workdir_q}",
        "$backupBase = $exe + '.old'",
        "Log \"waiting-for-parent pid=$parentPid\"",
        "try {",
        "    Wait-Process -Id $parentPid -Timeout 45 -ErrorAction SilentlyContinue",
        "} catch {",
        "    Log \"wait-error $($_.Exception.Message)\"",
        "}",
        "Start-Sleep -Milliseconds 300",
        "Log \"paths exe=$exe update=$update backup=$backupBase\"",
        "if (-not (Test-Path -LiteralPath $update)) {",
        "    Log 'missing-update-file'",
        f"    Remove-Item -LiteralPath {helper_q} -Force -ErrorAction SilentlyContinue",
        "    exit 1",
        "}",
        "for ($i = 0; $i -lt 40 -and (Test-Path -LiteralPath $exe); $i++) {",
        "    try {",
        "        $stream = [System.IO.File]::Open($exe, 'Open', 'ReadWrite', 'None')",
        "        $stream.Close()",
        "        break",
        "    } catch {",
        "        Start-Sleep -Milliseconds 250",
        "    }",
        "}",
        "if (Test-Path -LiteralPath $backupBase) {",
        "    Log 'removing-stale-backup'",
        "    Remove-Item -LiteralPath $backupBase -Force -ErrorAction SilentlyContinue",
        "}",
        "$backup = $backupBase",
        "if (Test-Path -LiteralPath $backup) {",
        "    $backup = $backupBase + '.' + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()",
        "    Log \"using-numbered-backup backup=$backup\"",
        "}",
        "$installed = $false",
        "try {",
        "    Log 'moving-current-to-backup'",
        "    Move-Item -LiteralPath $exe -Destination $backup -Force",
        "    Log 'moving-update-into-place'",
        "    Move-Item -LiteralPath $update -Destination $exe -Force",
        "    $installed = $true",
        "    Log 'install-move-complete'",
        "} catch {",
        "    Log \"install-error $($_.Exception.Message)\"",
        "    if ((-not (Test-Path -LiteralPath $exe)) -and (Test-Path -LiteralPath $backup)) {",
        "        Log 'rolling-back-backup'",
        "        Move-Item -LiteralPath $backup -Destination $exe -Force",
        "    }",
        "}",
        "$ErrorActionPreference = 'SilentlyContinue'",
        "if ($installed) {",
        "    Log 'starting-updated-app'",
        "    Start-Process -FilePath $exe -WorkingDirectory $workdir",
        "    for ($i = 0; $i -lt 80 -and (Test-Path -LiteralPath $backup); $i++) {",
        "        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue",
        "        if (Test-Path -LiteralPath $backup) { Start-Sleep -Milliseconds 250 }",
        "    }",
        "    if (Test-Path -LiteralPath $backup) { Log \"backup-still-present backup=$backup\" }",
        "    else { Log 'backup-cleaned' }",
        "} else {",
        "    Log 'install-not-completed-cleaning-update'",
        "    Remove-Item -LiteralPath $update -Force -ErrorAction SilentlyContinue",
        "}",
        "Log 'helper-end'",
        f"Remove-Item -LiteralPath {helper_q} -Force -ErrorAction SilentlyContinue",
    ]
    with open(helper, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(script) + "\r\n")
    return helper


def _write_windows_restart_helper(current_exe: str, backup_exe: str | None) -> str:
    """Create a hidden PowerShell helper for legacy already-swapped restarts."""
    parent_pid = os.getpid()
    fd, helper = tempfile.mkstemp(suffix=".ps1", prefix="qobuz_gui_restart_")
    os.close(fd)
    helper_q = _ps_quote(helper)
    current_q = _ps_quote(current_exe)
    workdir_q = _ps_quote(os.path.dirname(current_exe) or os.getcwd())
    backup_q = _ps_quote(backup_exe) if backup_exe else "$null"
    script = [
        "$ErrorActionPreference = 'SilentlyContinue'",
        "[Environment]::SetEnvironmentVariable('PYINSTALLER_RESET_ENVIRONMENT', '1', 'Process')",
        f"$parentPid = {parent_pid}",
        f"$exe = {current_q}",
        f"$workdir = {workdir_q}",
        f"$backup = {backup_q}",
        "while (Get-Process -Id $parentPid -ErrorAction SilentlyContinue) {",
        "    Start-Sleep -Milliseconds 250",
        "}",
        "Start-Sleep -Milliseconds 300",
        "Start-Process -FilePath $exe -WorkingDirectory $workdir",
        "if ($backup) {",
        "    for ($i = 0; $i -lt 80 -and (Test-Path -LiteralPath $backup); $i++) {",
        "        Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue",
        "        if (Test-Path -LiteralPath $backup) { Start-Sleep -Milliseconds 250 }",
        "    }",
        "}",
        f"Remove-Item -LiteralPath {helper_q} -Force -ErrorAction SilentlyContinue",
    ]
    with open(helper, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\r\n".join(script) + "\r\n")
    return helper


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _write_linux_update_helper(current_exe: str, downloaded_exe: str) -> str:
    """Create a shell helper that performs the update after the Linux app exits."""
    parent_pid = os.getpid()
    fd, helper = tempfile.mkstemp(suffix=".sh", prefix="qobuz_gui_update_")
    os.close(fd)
    log_path = os.path.join(tempfile.gettempdir(), "qobuz_gui_update.log")
    script = [
        "#!/usr/bin/env sh",
        "set +e",
        f"LOG={_sh_quote(log_path)}",
        "log() { printf '%s %s\\n' \"$(date '+%Y-%m-%d %H:%M:%S %z')\" \"$1\" >> \"$LOG\"; }",
        "log helper-start",
        f"PARENT_PID={parent_pid}",
        f"EXE={_sh_quote(current_exe)}",
        f"UPDATE={_sh_quote(downloaded_exe)}",
        'BACKUP="$EXE.old"',
        "log \"waiting-for-parent pid=$PARENT_PID\"",
        "i=0",
        "while kill -0 \"$PARENT_PID\" 2>/dev/null && [ \"$i\" -lt 180 ]; do",
        "  i=$((i + 1))",
        "  sleep 0.25",
        "done",
        "sleep 0.3",
        "log \"paths exe=$EXE update=$UPDATE backup=$BACKUP\"",
        "if [ ! -f \"$UPDATE\" ]; then",
        "  log missing-update-file",
        "  rm -f \"$0\"",
        "  exit 1",
        "fi",
        "chmod +x \"$UPDATE\" 2>/dev/null",
        "if [ -e \"$BACKUP\" ]; then",
        "  log removing-stale-backup",
        "  rm -f \"$BACKUP\" 2>/dev/null",
        "fi",
        "if [ -e \"$BACKUP\" ]; then",
        '  BACKUP="$BACKUP.$(date +%s)"',
        "  log \"using-numbered-backup backup=$BACKUP\"",
        "fi",
        "log moving-current-to-backup",
        "mv \"$EXE\" \"$BACKUP\"",
        "if [ \"$?\" -ne 0 ]; then",
        "  log install-error-move-current",
        "  rm -f \"$UPDATE\"",
        "  rm -f \"$0\"",
        "  exit 1",
        "fi",
        "log moving-update-into-place",
        "mv \"$UPDATE\" \"$EXE\"",
        "if [ \"$?\" -ne 0 ]; then",
        "  log install-error-move-update",
        "  if [ ! -e \"$EXE\" ] && [ -e \"$BACKUP\" ]; then mv \"$BACKUP\" \"$EXE\"; fi",
        "  rm -f \"$0\"",
        "  exit 1",
        "fi",
        "chmod +x \"$EXE\" 2>/dev/null",
        "log install-move-complete",
        "log starting-updated-app",
        'cd "$(dirname "$EXE")" 2>/dev/null',
        'PYINSTALLER_RESET_ENVIRONMENT=1 nohup "$EXE" >/dev/null 2>&1 &',
        "i=0",
        "while [ -e \"$BACKUP\" ] && [ \"$i\" -lt 80 ]; do",
        "  rm -f \"$BACKUP\" 2>/dev/null",
        "  [ -e \"$BACKUP\" ] && sleep 0.25",
        "  i=$((i + 1))",
        "done",
        "if [ -e \"$BACKUP\" ]; then log \"backup-still-present backup=$BACKUP\"; else log backup-cleaned; fi",
        "log helper-end",
        "rm -f \"$0\"",
    ]
    with open(helper, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(script) + "\n")
    os.chmod(helper, 0o700)
    return helper


def _launch_hidden_powershell(helper: str, cwd: str | None = None) -> None:
    creation = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation |= subprocess.CREATE_NO_WINDOW

    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    log_path = os.path.join(tempfile.gettempdir(), "qobuz_gui_update.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} python-launch {helper}\n")
    except OSError:
        pass
    proc = subprocess.Popen(
        [
            _powershell_exe(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            helper,
        ],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation,
        close_fds=True,
        shell=False,
    )
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} python-launched pid={proc.pid}\n")
    except OSError:
        pass


def _launch_linux_helper(helper: str, cwd: str | None = None) -> None:
    log_path = os.path.join(tempfile.gettempdir(), "qobuz_gui_update.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} python-launch {helper}\n")
    except OSError:
        pass
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    proc = subprocess.Popen(
        ["/bin/sh", helper],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} python-launched pid={proc.pid}\n")
    except OSError:
        pass


def stage_update_and_exit(downloaded_exe: str) -> None:
    """Hand update work to a detached helper, then exit to release file locks."""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-install is only for frozen desktop builds")

    _verify_update_file(downloaded_exe)
    current = os.path.abspath(sys.executable)
    if sys.platform == "win32":
        helper = _write_windows_update_helper(current, downloaded_exe)
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass
        _launch_hidden_powershell(helper, os.path.dirname(current) or None)
    elif sys.platform.startswith("linux"):
        helper = _write_linux_update_helper(current, downloaded_exe)
        _launch_linux_helper(helper, os.path.dirname(current) or None)
    else:
        raise RuntimeError("Automatic install is not available for this platform yet.")
    os._exit(0)


def schedule_stage_update_and_exit(downloaded_exe: str, delay: float = 0.25) -> None:
    """Let the HTTP response flush before handing off update work and exiting."""

    def run():
        time.sleep(delay)
        try:
            stage_update_and_exit(downloaded_exe)
        except Exception as e:
            logging.error("Update handoff failed: %s", e)

    threading.Thread(target=run, daemon=True).start()


def _windows_backup_path(current_exe: str) -> str:
    old = current_exe + ".old"
    if not os.path.exists(old):
        return old
    try:
        os.remove(old)
        return old
    except OSError:
        pass

    base = f"{old}.{int(time.time())}"
    for i in range(100):
        candidate = base if i == 0 else f"{base}.{i}"
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError(
        "Could not prepare an update backup path. Close other instances and "
        "remove stale .old files next to the application."
    )


def _releases_download_prefix(repo: str) -> str:
    r = repo.strip().strip("/")
    return f"https://github.com/{r}/releases/download/".lower()


def _asset_allowed_suffixes() -> tuple[str, ...]:
    if sys.platform == "win32":
        return (".exe",)
    if sys.platform == "darwin":
        return (".zip",)
    if sys.platform.startswith("linux"):
        return ("", ".appimage")
    return ()


def _asset_matches_platform(name: str) -> bool:
    n = (name or "").lower().replace("_", "-")
    if "qobuz-dl-gui" not in n:
        return False
    if sys.platform == "win32":
        return n.endswith(".exe") and ("windows" in n or "win" in n)
    if sys.platform == "darwin":
        return n.endswith(".zip") and ("macos" in n or "darwin" in n or "mac" in n)
    if sys.platform.startswith("linux"):
        return "linux" in n and (not n.endswith(".zip")) and (not n.endswith(".exe"))
    return False


def is_safe_release_asset_url(url: str, repo: str) -> bool:
    # TODO: REMOVE BEFORE PUSH TO MAIN
    if os.environ.get("QOBUZ_TEST_UPDATE") == "1" and url.startswith("http://127.0.0.1:"):
        return True

    if not url or not repo:
        return False
    u = url.strip().lower()
    suffixes = _asset_allowed_suffixes()
    if not suffixes:
        return False
    asset_name = u.rstrip("/").rsplit("/", 1)[-1]
    if sys.platform.startswith("linux") and not _asset_matches_platform(asset_name):
        return False
    if "" not in suffixes and not u.endswith(suffixes):
        return False
    return u.startswith(_releases_download_prefix(repo))


def pick_platform_asset(assets: list, repo: str) -> tuple[str | None, str | None]:
    prefix = _releases_download_prefix(repo)
    candidates: list[tuple[str, str]] = []
    for a in assets or []:
        url = a.get("browser_download_url") or ""
        name = a.get("name") or ""
        if not url.lower().startswith(prefix):
            continue
        if not _asset_matches_platform(name):
            continue
        candidates.append((url, name))
    if candidates:
        return candidates[0]
    return None, None


def pick_exe_asset(assets: list, repo: str) -> tuple[str | None, str | None]:
    return pick_platform_asset(assets, repo)


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
    # TODO: REMOVE BEFORE PUSH TO MAIN
    if os.environ.get("QOBUZ_TEST_UPDATE") == "1":
        return {
            "ok": True,
            "skipped": False,
            "current_version": __version__,
            "latest_version": "99.99.99",
            "tag_name": "v99.99.99",
            "update_available": True,
            "release_page": "http://127.0.0.1:8000",
            "download_url": "http://127.0.0.1:8000/test_update.exe",
            "asset_name": "test_update.exe",
            "can_auto_install": getattr(sys, "frozen", False)
            and os.name == "nt",
            "frozen": getattr(sys, "frozen", False),
            "test_mode": True,
        }

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

    dl_url, asset_name = pick_platform_asset(data.get("assets") or [], repo)
    html_url = data.get("html_url") or ""

    frozen_win = bool(getattr(sys, "frozen", False) and os.name == "nt")
    frozen_linux = bool(getattr(sys, "frozen", False) and sys.platform.startswith("linux"))
    can_auto = bool(update_available and dl_url and (frozen_win or frozen_linux))
    platform_name = (
        "windows"
        if sys.platform == "win32"
        else "macos"
        if sys.platform == "darwin"
        else "linux"
        if sys.platform.startswith("linux")
        else sys.platform
    )

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
        "platform": platform_name,
        "test_mode": False,
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


def _verify_linux_executable(path: str) -> None:
    try:
        sz = os.path.getsize(path)
    except OSError as e:
        raise RuntimeError(f"Cannot read downloaded update: {e}") from e
    if sz < 512 * 1024:
        raise RuntimeError(
            f"Downloaded file is too small ({sz} bytes) to be a valid Linux build."
        )
    try:
        with open(path, "rb") as f:
            sig = f.read(4)
    except OSError as e:
        raise RuntimeError(f"Cannot read downloaded update: {e}") from e
    if sig != b"\x7fELF" and sig != b"AI\x02\x00":
        raise RuntimeError("Downloaded file is not a valid Linux executable/AppImage.")


def _verify_update_file(path: str) -> None:
    if sys.platform == "win32":
        _verify_windows_pe(path)
    elif sys.platform.startswith("linux"):
        _verify_linux_executable(path)
    elif sys.platform == "darwin":
        try:
            if os.path.getsize(path) < 512 * 1024:
                raise RuntimeError("Downloaded macOS update is too small to be valid.")
        except OSError as e:
            raise RuntimeError(f"Cannot read downloaded update: {e}") from e
    else:
        raise RuntimeError("Unsupported update platform.")


def download_update_to_temp(url: str) -> str:
    headers = {"User-Agent": f"Qobuz-DL-GUI/{__version__}"}
    with requests.get(url, headers=headers, timeout=180, stream=True) as r:
        r.raise_for_status()
        suffix = ".exe" if sys.platform == "win32" else ".zip" if sys.platform == "darwin" else ""
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="qobuz_gui_upd_")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
            _verify_update_file(path)
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
    old = _windows_backup_path(current)

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
    """Restart after an in-place swap without launching the new app over the old one."""
    creation = 0
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        creation |= subprocess.CREATE_NO_WINDOW
    if hasattr(subprocess, "DETACHED_PROCESS"):
        creation |= subprocess.DETACHED_PROCESS

    # PyInstaller onefile (6.9+): a child that outlives this process must unpack
    # independently. Without this, the new exe may inherit _MEIPASS / DLL search
    # state and block cleanup — "[PYI-…] Failed to remove temporary directory".
    # https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass

    try:
        if sys.platform == "win32":
            helper = _write_windows_restart_helper(current_exe, backup_exe)
            subprocess.Popen(
                [
                    _powershell_exe(),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-WindowStyle",
                    "Hidden",
                    "-File",
                    helper,
                ],
                cwd=os.path.dirname(current_exe) or None,
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation,
                close_fds=True,
                shell=False,
            )
        else:
            subprocess.Popen(
                [current_exe],
                cwd=os.path.dirname(current_exe) or None,
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation,
                close_fds=True,
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
