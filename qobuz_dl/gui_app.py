import sys
import os
import platform
import subprocess

from pathlib import Path

import configparser
import hashlib
import logging
import queue
import re
import shutil
import threading
import time
import socket
import webbrowser

from typing import Optional

from flask import Flask, Response, jsonify, request, send_file, send_from_directory

# ---------------------------------------------------------------------------
# Paths (mirrors cli.py)
# ---------------------------------------------------------------------------
if os.name == "nt":
    OS_CONFIG = os.environ.get("APPDATA")
else:
    OS_CONFIG = os.path.join(os.environ["HOME"], ".config")

CONFIG_PATH = os.path.join(OS_CONFIG, "qobuz-dl")
CONFIG_FILE = os.path.join(CONFIG_PATH, "config.ini")
QOBUZ_DB = os.path.join(CONFIG_PATH, "qobuz_dl.db")


def _gui_static_dir():
    """Resolve bundled `gui/` for PyInstaller onefile/onedir and normal installs."""
    base = os.path.dirname(os.path.abspath(__file__))
    gui = os.path.join(base, "gui")
    if os.path.isdir(gui):
        return gui
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        alt = os.path.join(sys._MEIPASS, "qobuz_dl", "gui")
        if os.path.isdir(alt):
            return alt
    return gui


GUI_DIR = _gui_static_dir()

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=GUI_DIR)

# ---------------------------------------------------------------------------
# SSE log queue – a list so multiple consumers can drain independently
# ---------------------------------------------------------------------------
_log_queues: list[queue.Queue] = []
_log_lock = threading.Lock()


class _QueueHandler(logging.Handler):
    """Puts every log record into every registered SSE queue."""

    def emit(self, record):
        msg = self.format(record)
        # Track whether an error was logged during the current URL's download
        if record.levelno >= logging.ERROR:
            _ctx_mark_error()

        # Strip ANSI colour codes for processing
        clean = re.sub(r"\x1b\[[0-9;]*m", "", msg).strip()

        # Intercept [TRACK_START] markers | emit a structured SSE event AND
        # replace the raw marker with a human-readable log line.
        if clean.startswith("[TRACK_START] "):
            payload = clean[len("[TRACK_START] ") :]
            if "|" in payload:
                parts = payload.split("|")
                track_no = parts[0].strip()
                title = parts[1].strip() if len(parts) > 1 else ""
                cover_url = parts[2].strip() if len(parts) > 2 else ""
                ev_data = {
                    "type": "track_start",
                    "track_no": track_no,
                    "title": title,
                    "cover_url": cover_url,
                }
                if len(parts) >= 6:
                    ev_data["lyric_artist"] = parts[3].strip()
                    ev_data["lyric_album"] = parts[4].strip()
                    try:
                        ev_data["duration_sec"] = int(parts[5].strip() or 0)
                    except ValueError:
                        ev_data["duration_sec"] = 0
                    if len(parts) >= 7:
                        ev_data["track_explicit"] = parts[6].strip() in (
                            "1",
                            "true",
                            "True",
                        )
                _emit_event(ev_data)
                display = f"  \u2193 {track_no}. {title}".strip()
            else:
                _emit_event({"type": "track_start", "title": payload})
                display = f"  \u2193 {payload}"
            with _log_lock:
                for q in _log_queues:
                    try:
                        q.put_nowait(display)
                    except queue.Full:
                        pass
            return

        if clean.startswith("[TRACK_RESULT] "):
            payload = clean[len("[TRACK_RESULT] ") :]
            parts = payload.split("|")
            if len(parts) >= 4:
                track_no, title, status, detail = (
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                )
                queue_url = ""
                audio_path = ""
                lyric_album = ""
                if len(parts) >= 7:
                    queue_url = parts[4]
                    audio_path = parts[5]
                    lyric_album = parts[6].strip()
                elif len(parts) >= 6:
                    queue_url = parts[4]
                    audio_path = parts[5]
                elif len(parts) >= 5:
                    queue_url = parts[4]
                # Do not _ctx_mark_error() for purchase_only: it is a per-track outcome
                # (queue card shows purchase count); URL-level url_error should reflect
                # album/connection failures (e.g. Not streamable), not purchasable tracks.
                ev = {
                    "type": "track_result",
                    "track_no": track_no,
                    "title": title,
                    "status": status,
                    "detail": detail,
                }
                if queue_url:
                    ev["source_url"] = queue_url
                if audio_path:
                    ev["audio_path"] = audio_path
                if lyric_album:
                    ev["lyric_album"] = lyric_album
                _emit_event(ev)
            return

        if clean.startswith("[TRACK_LYRICS] "):
            payload = clean[len("[TRACK_LYRICS] ") :]
            parts = payload.split("|")
            if len(parts) >= 4:
                track_no, title, lyric_type, provider = (
                    parts[0],
                    parts[1],
                    parts[2],
                    parts[3],
                )
                confidence = parts[4] if len(parts) >= 5 else ""
                audio_path_lyrics = parts[5].strip() if len(parts) >= 6 else ""
                ev_ly = {
                    "type": "track_lyrics",
                    "track_no": track_no,
                    "title": title,
                    "lyric_type": lyric_type,
                    "provider": provider,
                    "confidence": confidence,
                }
                if audio_path_lyrics:
                    ev_ly["audio_path"] = audio_path_lyrics
                _emit_event(ev_ly)
            return

        with _log_lock:
            for q in _log_queues:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass


_queue_handler = _QueueHandler()
_queue_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_queue_handler)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def _emit_event(event_data: dict):
    """Push a structured JSON status event to all SSE consumers."""
    with _log_lock:
        for q in _log_queues:
            try:
                q.put_nowait(event_data)  # dict, not str
            except queue.Full:
                pass


# Inject into core to allow it to update the UI
import qobuz_dl.core
qobuz_dl.core.ui_emitter = _emit_event


# ---------------------------------------------------------------------------
# QobuzDL client singleton
# ---------------------------------------------------------------------------
_client_lock = threading.Lock()
_qobuz_client = None  # QobuzDL instance
_cancel_download = threading.Event()  # set by /api/cancel
_download_active = False  # True while a download thread is running
_url_ctx_lock = threading.Lock()
_url_ctx = {"tracking": False, "had_error": False}  # cross-thread URL error tracking


def _ctx_start_url():
    with _url_ctx_lock:
        _url_ctx["tracking"] = True
        _url_ctx["had_error"] = False


def _ctx_mark_error():
    with _url_ctx_lock:
        if _url_ctx["tracking"]:
            _url_ctx["had_error"] = True


def _ctx_finish_url() -> bool:
    with _url_ctx_lock:
        had_error = bool(_url_ctx["had_error"])
        _url_ctx["tracking"] = False
        _url_ctx["had_error"] = False
        return had_error


def _get_qobuz():
    return _qobuz_client


def _as_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    sval = str(value).strip().lower()
    if sval in {"1", "true", "yes", "on"}:
        return True
    if sval in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)


def _as_int(value, default=0):
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except Exception:
        return int(default)


def _build_qobuz_from_config(cfg, overrides=None):
    """Instantiate QobuzDL from config + optional overrides dict."""
    from qobuz_dl.core import QobuzDL

    o = overrides or {}
    directory = o.get("directory") or cfg.get(
        "DEFAULT", "default_folder", fallback="Qobuz Downloads"
    )
    quality = _as_int(
        o.get("quality"), _as_int(cfg.get("DEFAULT", "default_quality", fallback="27"), 27)
    )
    embed_art = _as_bool(
        o.get("embed_art"), cfg.getboolean("DEFAULT", "embed_art", fallback=False)
    )
    albums_only = _as_bool(
        o.get("albums_only"), cfg.getboolean("DEFAULT", "albums_only", fallback=False)
    )
    no_m3u = _as_bool(
        o.get("no_m3u"), cfg.getboolean("DEFAULT", "no_m3u", fallback=False)
    )
    no_fallback = _as_bool(
        o.get("no_fallback"),
        cfg.getboolean("DEFAULT", "no_fallback", fallback=False),
    )
    og_cover = _as_bool(
        o.get("og_cover"), cfg.getboolean("DEFAULT", "og_cover", fallback=False)
    )
    no_cover = _as_bool(
        o.get("no_cover"), cfg.getboolean("DEFAULT", "no_cover", fallback=False)
    )
    lyrics_enabled = _as_bool(
        o.get("lyrics_enabled"),
        cfg.getboolean("DEFAULT", "lyrics_enabled", fallback=False),
    )
    no_database = _as_bool(
        o.get("no_db"), cfg.getboolean("DEFAULT", "no_database", fallback=True)
    )
    smart_discography = _as_bool(
        o.get("smart_discography"),
        cfg.getboolean("DEFAULT", "smart_discography", fallback=False),
    )
    folder_format = o.get("folder_format") or cfg.get(
        "DEFAULT",
        "folder_format",
        fallback="{artist}/{album}",
    )
    track_format = o.get("track_format") or cfg.get(
        "DEFAULT", "track_format", fallback="{tracknumber} - {tracktitle}"
    )
    fix_md5s = _as_bool(
        o.get("fix_md5s"), cfg.getboolean("DEFAULT", "fix_md5s", fallback=False)
    )
    multiple_disc_prefix = o.get("multiple_disc_prefix") or cfg.get(
        "DEFAULT", "multiple_disc_prefix", fallback="Disc"
    )
    multiple_disc_one_dir = _as_bool(
        o.get("multiple_disc_one_dir"),
        cfg.getboolean("DEFAULT", "multiple_disc_one_dir", fallback=False),
    )
    multiple_disc_track_format = o.get("multiple_disc_track_format") or cfg.get(
        "DEFAULT",
        "multiple_disc_track_format",
        fallback="{disc_number_unpadded}{track_number} - {tracktitle}",
    )
    max_workers = max(
        1,
        _as_int(
            o.get("max_workers"), _as_int(cfg.get("DEFAULT", "max_workers", fallback="1"), 1)
        ),
    )
    delay_seconds = max(
        0,
        _as_int(
            o.get("delay_seconds"),
            _as_int(cfg.get("DEFAULT", "delay_seconds", fallback="0"), 0),
        ),
    )
    segmented_fallback = _as_bool(
        o.get("segmented_fallback"),
        cfg.getboolean("DEFAULT", "segmented_fallback", fallback=True),
    )
    no_credits = _as_bool(
        o.get("no_credits"),
        cfg.getboolean("DEFAULT", "no_credits", fallback=False),
    )
    native_lang = _as_bool(
        o.get("native_lang"),
        cfg.getboolean("DEFAULT", "native_lang", fallback=False),
    )

    qobuz = QobuzDL(
        directory=directory,
        quality=quality,
        embed_art=embed_art,
        ignore_singles_eps=albums_only,
        no_m3u_for_playlists=no_m3u,
        quality_fallback=not no_fallback,
        cover_og_quality=og_cover,
        no_cover=no_cover,
        lyrics_enabled=lyrics_enabled,
        downloads_db=None if no_database else QOBUZ_DB,
        folder_format=folder_format,
        track_format=track_format,
        smart_discography=smart_discography,
        fix_md5s=fix_md5s,
        multiple_disc_prefix=multiple_disc_prefix,
        multiple_disc_one_dir=multiple_disc_one_dir,
        multiple_disc_track_format=multiple_disc_track_format,
        max_workers=max_workers,
        delay_seconds=delay_seconds,
        segmented_fallback=segmented_fallback,
        no_credits=no_credits,
        native_lang=native_lang,
        no_album_artist_tag=_as_bool(
            o.get("no_album_artist_tag"),
            cfg.getboolean("DEFAULT", "no_album_artist_tag", fallback=False),
        ),
        no_album_title_tag=_as_bool(
            o.get("no_album_title_tag"),
            cfg.getboolean("DEFAULT", "no_album_title_tag", fallback=False),
        ),
        no_track_artist_tag=_as_bool(
            o.get("no_track_artist_tag"),
            cfg.getboolean("DEFAULT", "no_track_artist_tag", fallback=False),
        ),
        no_track_title_tag=_as_bool(
            o.get("no_track_title_tag"),
            cfg.getboolean("DEFAULT", "no_track_title_tag", fallback=False),
        ),
        no_release_date_tag=_as_bool(
            o.get("no_release_date_tag"),
            cfg.getboolean("DEFAULT", "no_release_date_tag", fallback=False),
        ),
        no_media_type_tag=_as_bool(
            o.get("no_media_type_tag"),
            cfg.getboolean("DEFAULT", "no_media_type_tag", fallback=False),
        ),
        no_genre_tag=_as_bool(
            o.get("no_genre_tag"),
            cfg.getboolean("DEFAULT", "no_genre_tag", fallback=False),
        ),
        no_track_number_tag=_as_bool(
            o.get("no_track_number_tag"),
            cfg.getboolean("DEFAULT", "no_track_number_tag", fallback=False),
        ),
        no_track_total_tag=_as_bool(
            o.get("no_track_total_tag"),
            cfg.getboolean("DEFAULT", "no_track_total_tag", fallback=False),
        ),
        no_disc_number_tag=_as_bool(
            o.get("no_disc_number_tag"),
            cfg.getboolean("DEFAULT", "no_disc_number_tag", fallback=False),
        ),
        no_disc_total_tag=_as_bool(
            o.get("no_disc_total_tag"),
            cfg.getboolean("DEFAULT", "no_disc_total_tag", fallback=False),
        ),
        no_composer_tag=_as_bool(
            o.get("no_composer_tag"),
            cfg.getboolean("DEFAULT", "no_composer_tag", fallback=False),
        ),
        no_explicit_tag=_as_bool(
            o.get("no_explicit_tag"),
            cfg.getboolean("DEFAULT", "no_explicit_tag", fallback=False),
        ),
        no_copyright_tag=_as_bool(
            o.get("no_copyright_tag"),
            cfg.getboolean("DEFAULT", "no_copyright_tag", fallback=False),
        ),
        no_label_tag=_as_bool(
            o.get("no_label_tag"),
            cfg.getboolean("DEFAULT", "no_label_tag", fallback=False),
        ),
        no_upc_tag=_as_bool(
            o.get("no_upc_tag"),
            cfg.getboolean("DEFAULT", "no_upc_tag", fallback=False),
        ),
        no_isrc_tag=_as_bool(
            o.get("no_isrc_tag"),
            cfg.getboolean("DEFAULT", "no_isrc_tag", fallback=False),
        ),
    )
    return qobuz


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(GUI_DIR, "index.html")


@app.route("/gui/<path:filename>")
def gui_static(filename):
    return send_from_directory(GUI_DIR, filename)


# ---------------------------------------------------------------------------
# API: status
# ---------------------------------------------------------------------------
@app.route("/api/status")
def api_status():
    has_config = os.path.isfile(CONFIG_FILE)
    ready = _qobuz_client is not None
    config_data = {}
    if has_config:
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE)
        try:
            config_data = {
                "email": cfg["DEFAULT"].get("email", ""),
                "default_folder": cfg["DEFAULT"].get(
                    "default_folder", "Qobuz Downloads"
                ),
                "default_quality": cfg["DEFAULT"].get("default_quality", "27"),
                "no_m3u": cfg["DEFAULT"].get("no_m3u", "false"),
                "albums_only": cfg["DEFAULT"].get("albums_only", "false"),
                "no_fallback": cfg["DEFAULT"].get("no_fallback", "false"),
                "og_cover": cfg["DEFAULT"].get("og_cover", "false"),
                "embed_art": cfg["DEFAULT"].get("embed_art", "false"),
                "no_cover": cfg["DEFAULT"].get("no_cover", "false"),
                "lyrics_enabled": cfg["DEFAULT"].get("lyrics_enabled", "false"),
                "no_database": cfg["DEFAULT"].get("no_database", "false"),
                "smart_discography": cfg["DEFAULT"].get("smart_discography", "false"),
                "fix_md5s": cfg["DEFAULT"].get("fix_md5s", "false"),
                "multiple_disc_prefix": cfg["DEFAULT"].get(
                    "multiple_disc_prefix", "Disc"
                ),
                "multiple_disc_one_dir": cfg["DEFAULT"].get(
                    "multiple_disc_one_dir", "false"
                ),
                "multiple_disc_track_format": cfg["DEFAULT"].get(
                    "multiple_disc_track_format",
                    "{disc_number_unpadded}{track_number} - {tracktitle}",
                ),
                "max_workers": cfg["DEFAULT"].get("max_workers", "1"),
                "delay_seconds": cfg["DEFAULT"].get("delay_seconds", "0"),
                "segmented_fallback": cfg["DEFAULT"].get(
                    "segmented_fallback", "true"
                ),
                "no_credits": cfg["DEFAULT"].get("no_credits", "false"),
                "native_lang": cfg["DEFAULT"].get("native_lang", "false"),
                "folder_format": cfg["DEFAULT"].get(
                    "folder_format",
                    "{artist}/{album}",
                ),
                "track_format": cfg["DEFAULT"].get(
                    "track_format", "{tracknumber} - {tracktitle}"
                ),
                "no_album_artist_tag": cfg["DEFAULT"].get(
                    "no_album_artist_tag", "false"
                ),
                "no_album_title_tag": cfg["DEFAULT"].get(
                    "no_album_title_tag", "false"
                ),
                "no_track_artist_tag": cfg["DEFAULT"].get(
                    "no_track_artist_tag", "false"
                ),
                "no_track_title_tag": cfg["DEFAULT"].get(
                    "no_track_title_tag", "false"
                ),
                "no_release_date_tag": cfg["DEFAULT"].get(
                    "no_release_date_tag", "false"
                ),
                "no_media_type_tag": cfg["DEFAULT"].get(
                    "no_media_type_tag", "false"
                ),
                "no_genre_tag": cfg["DEFAULT"].get("no_genre_tag", "false"),
                "no_track_number_tag": cfg["DEFAULT"].get(
                    "no_track_number_tag", "false"
                ),
                "no_track_total_tag": cfg["DEFAULT"].get(
                    "no_track_total_tag", "false"
                ),
                "no_disc_number_tag": cfg["DEFAULT"].get(
                    "no_disc_number_tag", "false"
                ),
                "no_disc_total_tag": cfg["DEFAULT"].get(
                    "no_disc_total_tag", "false"
                ),
                "no_composer_tag": cfg["DEFAULT"].get("no_composer_tag", "false"),
                "no_explicit_tag": cfg["DEFAULT"].get("no_explicit_tag", "false"),
                "no_copyright_tag": cfg["DEFAULT"].get(
                    "no_copyright_tag", "false"
                ),
                "no_label_tag": cfg["DEFAULT"].get("no_label_tag", "false"),
                "no_upc_tag": cfg["DEFAULT"].get("no_upc_tag", "false"),
                "no_isrc_tag": cfg["DEFAULT"].get("no_isrc_tag", "false"),
            }
        except Exception:
            pass
    from qobuz_dl.version import __version__ as app_ver

    return jsonify(
        {
            "has_config": has_config,
            "ready": ready,
            "config": config_data,
            "app_version": app_ver,
            "frozen": getattr(sys, "frozen", False),
            "capabilities": {
                "flac_cli": bool(shutil.which("flac")),
                "ffmpeg_cli": bool(shutil.which("ffmpeg")),
            },
        }
    )


# ---------------------------------------------------------------------------
# API: updates (GitHub Releases)
# ---------------------------------------------------------------------------
@app.route("/api/update/check")
def api_update_check():
    from qobuz_dl import updater

    force = request.args.get("force") == "1"
    return jsonify(updater.check_for_update(CONFIG_PATH, force=force))


@app.route("/api/update/install", methods=["POST"])
def api_update_install():
    from qobuz_dl import updater
    from qobuz_dl.version import GITHUB_RELEASE_REPO

    data = request.json or {}
    url = (data.get("download_url") or "").strip()
    if not updater.is_safe_release_asset_url(url, GITHUB_RELEASE_REPO.strip()):
        return jsonify({"ok": False, "error": "Invalid or untrusted download URL"}), 400
    if not getattr(sys, "frozen", False) or os.name != "nt":
        return jsonify(
            {
                "ok": False,
                "error": "Automatic install is only available for the Windows portable EXE.",
            }
        ), 400
    try:
        path = updater.download_update_to_temp(url)
    except Exception as e:
        logging.error("Update download failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500

    try:
        current_exe, _old = updater.swap_windows_exe_inplace(path)
    except Exception as e:
        logging.error("Update install failed: %s", e)
        try:
            os.remove(path)
        except OSError:
            pass
        return jsonify({"ok": False, "error": str(e)}), 500

    try:
        os.remove(path)
    except OSError:
        pass

    updater.schedule_restart_only(current_exe, _old)
    return jsonify({"ok": True, "restarting": True})


# ---------------------------------------------------------------------------
# API: setup (save config + initialise client)
# ---------------------------------------------------------------------------
@app.route("/api/setup", methods=["POST"])
def api_setup():
    global _qobuz_client
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    folder = data.get("default_folder", "Qobuz Downloads").strip() or "Qobuz Downloads"
    quality = data.get("default_quality", "27")

    if not email or not password:
        return jsonify({"ok": False, "error": "Email and password are required"}), 400

    try:
        from qobuz_dl.bundle import Bundle

        logging.info("Fetching Qobuz tokens, please wait…")
        bundle = Bundle()
        app_id = str(bundle.get_app_id())
        secrets = ",".join(bundle.get_secrets().values())

        os.makedirs(CONFIG_PATH, exist_ok=True)
        cfg = configparser.ConfigParser()
        cfg["DEFAULT"]["email"] = email
        cfg["DEFAULT"]["password"] = hashlib.md5(password.encode("utf-8")).hexdigest()
        cfg["DEFAULT"]["default_folder"] = folder
        cfg["DEFAULT"]["default_quality"] = str(quality)
        cfg["DEFAULT"]["default_limit"] = "20"
        cfg["DEFAULT"]["no_m3u"] = "false"
        cfg["DEFAULT"]["albums_only"] = "false"
        cfg["DEFAULT"]["no_fallback"] = "false"
        cfg["DEFAULT"]["og_cover"] = "false"
        cfg["DEFAULT"]["embed_art"] = "false"
        cfg["DEFAULT"]["lyrics_enabled"] = "false"
        cfg["DEFAULT"]["no_cover"] = "false"
        cfg["DEFAULT"]["no_database"] = "true"
        cfg["DEFAULT"]["app_id"] = app_id
        cfg["DEFAULT"]["secrets"] = secrets
        cfg["DEFAULT"]["private_key"] = bundle.get_private_key() or ""
        cfg["DEFAULT"]["user_id"] = ""
        cfg["DEFAULT"]["user_auth_token"] = ""
        cfg["DEFAULT"]["folder_format"] = "{artist}/{album}"
        cfg["DEFAULT"]["track_format"] = "{tracknumber} - {tracktitle}"
        cfg["DEFAULT"]["smart_discography"] = "false"
        cfg["DEFAULT"]["fix_md5s"] = "false"
        cfg["DEFAULT"]["multiple_disc_prefix"] = "Disc"
        cfg["DEFAULT"]["multiple_disc_one_dir"] = "false"
        cfg["DEFAULT"]["multiple_disc_track_format"] = (
            "{disc_number_unpadded}{track_number} - {tracktitle}"
        )
        cfg["DEFAULT"]["max_workers"] = "1"
        cfg["DEFAULT"]["delay_seconds"] = "0"
        cfg["DEFAULT"]["segmented_fallback"] = "true"
        cfg["DEFAULT"]["no_credits"] = "false"
        cfg["DEFAULT"]["native_lang"] = "false"
        for key in (
            "no_album_artist_tag",
            "no_album_title_tag",
            "no_track_artist_tag",
            "no_track_title_tag",
            "no_release_date_tag",
            "no_media_type_tag",
            "no_genre_tag",
            "no_track_number_tag",
            "no_track_total_tag",
            "no_disc_number_tag",
            "no_disc_total_tag",
            "no_composer_tag",
            "no_explicit_tag",
            "no_copyright_tag",
            "no_label_tag",
            "no_upc_tag",
            "no_isrc_tag",
        ):
            cfg["DEFAULT"][key] = "false"

        with open(CONFIG_FILE, "w") as f:
            cfg.write(f)

        # Initialise client
        from qobuz_dl.core import QobuzDL

        qobuz = _build_qobuz_from_config(cfg)
        secrets_list = [s for s in secrets.split(",") if s]
        qobuz.initialize_client(email, cfg["DEFAULT"]["password"], app_id, secrets_list)

        with _client_lock:
            _qobuz_client = qobuz

        logging.info("Login successful.")
        return jsonify({"ok": True})
    except Exception as e:
        logging.error(f"Setup failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: connect (load existing config + init client)
# ---------------------------------------------------------------------------
@app.route("/api/connect", methods=["POST"])
def api_connect():
    global _qobuz_client
    if not os.path.isfile(CONFIG_FILE):
        return jsonify(
            {"ok": False, "error": "No config file found. Please set up first."}
        ), 400
    try:
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE)
        app_id = cfg["DEFAULT"].get("app_id", "")
        secrets_list = [s for s in cfg["DEFAULT"].get("secrets", "").split(",") if s]
        user_id = cfg["DEFAULT"].get("user_id", "").strip()
        user_auth_token = cfg["DEFAULT"].get("user_auth_token", "").strip()
        email = cfg["DEFAULT"].get("email", "").strip()
        password = cfg["DEFAULT"].get("password", "").strip()

        qobuz = _build_qobuz_from_config(cfg)

        if user_id and user_auth_token:
            qobuz.initialize_client_with_token(
                user_id, user_auth_token, app_id, secrets_list
            )
        elif email and password:
            qobuz.initialize_client(email, password, app_id, secrets_list)
        else:
            return jsonify(
                {
                    "ok": False,
                    "error": "No valid credentials in config. Use OAuth or set up with email/password.",
                }
            ), 400

        with _client_lock:
            _qobuz_client = qobuz

        logging.info("Connected successfully.")
        return jsonify({"ok": True})
    except Exception as e:
        logging.error(f"Connect failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: OAuth login (opens browser, waits for redirect)
# ---------------------------------------------------------------------------
@app.route("/api/oauth/start", methods=["POST"])
def api_oauth_start():
    """Kick off the OAuth flow in a background thread; returns the URL immediately."""
    global _qobuz_client
    import socket
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlparse

    try:
        from qobuz_dl.bundle import Bundle
        from qobuz_dl.core import QobuzDL

        bundle = Bundle()
        app_id = str(bundle.get_app_id())
        secrets_list = [s for s in bundle.get_secrets().values() if s]
        private_key = bundle.get_private_key() or ""

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            port = s.getsockname()[1]

        # Use 127.0.0.1 (not localhost) so the browser hits the IPv4 listener on Windows
        # where localhost may resolve to ::1 first.
        oauth_url = (
            f"https://www.qobuz.com/signin/oauth"
            f"?ext_app_id={app_id}"
            f"&redirect_url=http://127.0.0.1:{port}"
        )

        # Store state for the callback thread to use
        _oauth_state = {
            "app_id": app_id,
            "secrets": secrets_list,
            "private_key": private_key,
            "port": port,
            "done": False,
            "error": None,
        }

        class OAuthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                code = params.get("code", [params.get("code_autorisation", [""])[0]])[0]
                if code:
                    OAuthHandler.code = code
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body style='font-family:system-ui;text-align:center;padding:60px;background:#0d0d0d;color:#f0f0f0'><h2 style='color:#6ee7f7'>Login successful!</h2><p>You may close this tab and return to Qobuz-DL.</p></body></html>"
                    )
                else:
                    OAuthHandler.code = None
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"<html><body><h2>Login failed</h2></body></html>")

            def log_message(self, format, *args):
                pass

        OAuthHandler.code = None

        def _run_oauth():
            global _qobuz_client
            try:
                server = HTTPServer(("127.0.0.1", port), OAuthHandler)
                logging.info(f"OAuth: waiting for browser redirect on port {port}…")
                server.handle_request()
                server.server_close()

                if not OAuthHandler.code:
                    logging.error("OAuth: no code received.")
                    return

                cfg_read = configparser.ConfigParser()
                cfg_read.read(CONFIG_FILE)

                qobuz = _build_qobuz_from_config(cfg_read)
                qobuz.app_id = app_id
                qobuz.secrets = secrets_list
                qobuz.private_key = private_key
                qobuz.initialize_client_with_oauth(
                    OAuthHandler.code, app_id, secrets_list, private_key
                )

                # Persist token to config
                os.makedirs(CONFIG_PATH, exist_ok=True)
                cfg_write = configparser.ConfigParser()
                cfg_write.read(CONFIG_FILE)
                cfg_write["DEFAULT"]["app_id"] = app_id
                cfg_write["DEFAULT"]["secrets"] = ",".join(secrets_list)
                cfg_write["DEFAULT"]["private_key"] = private_key
                cfg_write["DEFAULT"]["user_auth_token"] = (
                    qobuz.oauth_user_auth_token or ""
                )
                cfg_write["DEFAULT"]["user_id"] = str(qobuz.oauth_user_id or "")
                cfg_write["DEFAULT"]["email"] = ""
                cfg_write["DEFAULT"]["password"] = ""
                for key in (
                    "default_folder",
                    "default_quality",
                    "default_limit",
                    "no_m3u",
                    "albums_only",
                    "no_fallback",
                    "og_cover",
                    "embed_art",
                    "lyrics_enabled",
                    "no_cover",
                    "no_database",
                    "folder_format",
                    "track_format",
                    "smart_discography",
                    "fix_md5s",
                    "multiple_disc_prefix",
                    "multiple_disc_one_dir",
                    "multiple_disc_track_format",
                    "max_workers",
                    "delay_seconds",
                    "segmented_fallback",
                    "no_credits",
                    "native_lang",
                    "no_album_artist_tag",
                    "no_album_title_tag",
                    "no_track_artist_tag",
                    "no_track_title_tag",
                    "no_release_date_tag",
                    "no_media_type_tag",
                    "no_genre_tag",
                    "no_track_number_tag",
                    "no_track_total_tag",
                    "no_disc_number_tag",
                    "no_disc_total_tag",
                    "no_composer_tag",
                    "no_explicit_tag",
                    "no_copyright_tag",
                    "no_label_tag",
                    "no_upc_tag",
                    "no_isrc_tag",
                ):
                    if not cfg_write.has_option("DEFAULT", key):
                        defaults = {
                            "default_folder": "Qobuz Downloads",
                            "default_quality": "27",
                            "default_limit": "20",
                            "no_m3u": "false",
                            "albums_only": "false",
                            "no_fallback": "false",
                            "og_cover": "false",
                            "embed_art": "false",
                            "lyrics_enabled": "false",
                            "no_cover": "false",
                            "no_database": "true",
                            "folder_format": "{artist}/{album}",
                            "track_format": "{tracknumber} - {tracktitle}",
                            "smart_discography": "false",
                            "fix_md5s": "false",
                            "multiple_disc_prefix": "Disc",
                            "multiple_disc_one_dir": "false",
                            "multiple_disc_track_format": "{disc_number_unpadded}{track_number} - {tracktitle}",
                            "max_workers": "1",
                            "delay_seconds": "0",
                            "segmented_fallback": "true",
                            "no_credits": "false",
                            "native_lang": "false",
                            "no_album_artist_tag": "false",
                            "no_album_title_tag": "false",
                            "no_track_artist_tag": "false",
                            "no_track_title_tag": "false",
                            "no_release_date_tag": "false",
                            "no_media_type_tag": "false",
                            "no_genre_tag": "false",
                            "no_track_number_tag": "false",
                            "no_track_total_tag": "false",
                            "no_disc_number_tag": "false",
                            "no_disc_total_tag": "false",
                            "no_composer_tag": "false",
                            "no_explicit_tag": "false",
                            "no_copyright_tag": "false",
                            "no_label_tag": "false",
                            "no_upc_tag": "false",
                            "no_isrc_tag": "false",
                        }
                        cfg_write["DEFAULT"][key] = defaults.get(key, "")
                with open(CONFIG_FILE, "w") as f:
                    cfg_write.write(f)

                with _client_lock:
                    _qobuz_client = qobuz
                logging.info("OAuth login complete. You are now connected.")
            except Exception as ex:
                logging.error(f"OAuth error: {ex}")

        t = threading.Thread(target=_run_oauth, daemon=True)
        t.start()

        webbrowser.open(oauth_url)
        logging.info(f"Opened browser for OAuth login. Waiting for redirect…")
        return jsonify({"ok": True, "url": oauth_url})
    except Exception as e:
        logging.error(f"OAuth start failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: token login (user_id + user_auth_token)
# ---------------------------------------------------------------------------
@app.route("/api/token_login", methods=["POST"])
def api_token_login():
    global _qobuz_client
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    user_auth_token = data.get("user_auth_token", "").strip()
    folder = data.get("default_folder", "Qobuz Downloads").strip() or "Qobuz Downloads"
    quality = str(data.get("default_quality", "27"))

    if not user_id or not user_auth_token:
        return jsonify(
            {"ok": False, "error": "user_id and user_auth_token are required"}
        ), 400

    try:
        from qobuz_dl.bundle import Bundle

        logging.info("Fetching Qobuz tokens for token-based login…")
        bundle = Bundle()
        app_id = str(bundle.get_app_id())
        secrets_list = [s for s in bundle.get_secrets().values() if s]
        private_key = bundle.get_private_key() or ""

        os.makedirs(CONFIG_PATH, exist_ok=True)
        cfg = configparser.ConfigParser()
        cfg["DEFAULT"]["email"] = ""
        cfg["DEFAULT"]["password"] = ""
        cfg["DEFAULT"]["user_id"] = user_id
        cfg["DEFAULT"]["user_auth_token"] = user_auth_token
        cfg["DEFAULT"]["default_folder"] = folder
        cfg["DEFAULT"]["default_quality"] = quality
        cfg["DEFAULT"]["default_limit"] = "20"
        cfg["DEFAULT"]["no_m3u"] = "false"
        cfg["DEFAULT"]["albums_only"] = "false"
        cfg["DEFAULT"]["no_fallback"] = "false"
        cfg["DEFAULT"]["og_cover"] = "false"
        cfg["DEFAULT"]["embed_art"] = "false"
        cfg["DEFAULT"]["lyrics_enabled"] = "false"
        cfg["DEFAULT"]["no_cover"] = "false"
        cfg["DEFAULT"]["no_database"] = "true"
        cfg["DEFAULT"]["app_id"] = app_id
        cfg["DEFAULT"]["secrets"] = ",".join(secrets_list)
        cfg["DEFAULT"]["private_key"] = private_key
        cfg["DEFAULT"]["folder_format"] = "{artist}/{album}"
        cfg["DEFAULT"]["track_format"] = "{tracknumber} - {tracktitle}"
        cfg["DEFAULT"]["smart_discography"] = "false"
        cfg["DEFAULT"]["fix_md5s"] = "false"
        cfg["DEFAULT"]["multiple_disc_prefix"] = "Disc"
        cfg["DEFAULT"]["multiple_disc_one_dir"] = "false"
        cfg["DEFAULT"]["multiple_disc_track_format"] = (
            "{disc_number_unpadded}{track_number} - {tracktitle}"
        )
        cfg["DEFAULT"]["max_workers"] = "1"
        cfg["DEFAULT"]["delay_seconds"] = "0"
        cfg["DEFAULT"]["segmented_fallback"] = "true"
        cfg["DEFAULT"]["no_credits"] = "false"
        cfg["DEFAULT"]["native_lang"] = "false"
        for key in (
            "no_album_artist_tag",
            "no_album_title_tag",
            "no_track_artist_tag",
            "no_track_title_tag",
            "no_release_date_tag",
            "no_media_type_tag",
            "no_genre_tag",
            "no_track_number_tag",
            "no_track_total_tag",
            "no_disc_number_tag",
            "no_disc_total_tag",
            "no_composer_tag",
            "no_explicit_tag",
            "no_copyright_tag",
            "no_label_tag",
            "no_upc_tag",
            "no_isrc_tag",
        ):
            cfg["DEFAULT"][key] = "false"
        with open(CONFIG_FILE, "w") as f:
            cfg.write(f)

        qobuz = _build_qobuz_from_config(cfg)
        qobuz.initialize_client_with_token(
            user_id, user_auth_token, app_id, secrets_list
        )

        with _client_lock:
            _qobuz_client = qobuz

        logging.info("Token login successful.")
        return jsonify({"ok": True})
    except Exception as e:
        logging.error(f"Token login failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: browse folder (Windows/Linux native dialog via tkinter)
# ---------------------------------------------------------------------------
@app.route("/api/browse_folder", methods=["POST"])
def api_browse_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", True)
        folder = filedialog.askdirectory(parent=root, title="Select Download Folder")
        root.destroy()
        if folder:
            return jsonify({"ok": True, "path": folder})
        return jsonify({"ok": False, "cancelled": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: config GET/POST
# ---------------------------------------------------------------------------
@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if not os.path.isfile(CONFIG_FILE):
        return jsonify({"ok": False, "error": "No config file"}), 400

    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)

    if request.method == "GET":
        return jsonify(
            {
                "ok": True,
                "config": {
                    k: v
                    for k, v in cfg["DEFAULT"].items()
                    if k != "genius_token"
                },
            }
        )

    data = request.json or {}
    data.pop("genius_token", None)
    for key, val in data.items():
        if key == "new_password":
            if val:
                cfg["DEFAULT"]["password"] = hashlib.md5(
                    val.encode("utf-8")
                ).hexdigest()
        else:
            cfg["DEFAULT"][key] = str(val)
    if cfg.has_option("DEFAULT", "genius_token"):
        cfg.remove_option("DEFAULT", "genius_token")
    with open(CONFIG_FILE, "w") as f:
        cfg.write(f)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: resolve URL → metadata (album art, title, artist)
# ---------------------------------------------------------------------------
@app.route("/api/resolve", methods=["POST"])
def api_resolve():
    qobuz = _get_qobuz()
    if not qobuz:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    data = request.json or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "error": "No URL"}), 400

    try:
        from qobuz_dl.utils import get_url_info

        url_type, item_id = get_url_info(url)
    except Exception:
        return jsonify({"ok": False, "error": "Invalid Qobuz URL"}), 400

    try:
        if url_type == "album":
            meta = qobuz.client.get_album_meta(item_id)
            result = {
                "type": "album",
                "title": meta.get("title", ""),
                "artist": meta.get("artist", {}).get("name", ""),
                "cover": meta.get("image", {}).get("large", ""),
                "tracks": meta.get("tracks_count", 0),
                "year": (meta.get("release_date_original") or "")[:4],
                "release_date": meta.get("release_date_original", ""),
                "bit_depth": meta.get("maximum_bit_depth"),
                "sample_rate": meta.get("maximum_sampling_rate"),
                "quality": f"{meta.get('maximum_bit_depth', '?')}bit / {meta.get('maximum_sampling_rate', '?')}kHz",
                "explicit": bool(meta.get("parental_warning") or meta.get("explicit")),
                "url": url,
            }
        elif url_type == "track":
            meta = qobuz.client.get_track_meta(item_id)
            album = meta.get("album", {})
            result = {
                "type": "track",
                "title": meta.get("title", ""),
                "artist": meta.get("performer", {}).get("name", ""),
                "cover": album.get("image", {}).get("large", ""),
                "album": album.get("title", ""),
                "year": (album.get("release_date_original") or "")[:4],
                "bit_depth": album.get("maximum_bit_depth"),
                "sample_rate": album.get("maximum_sampling_rate"),
                "quality": f"{album.get('maximum_bit_depth', '?')}bit / {album.get('maximum_sampling_rate', '?')}kHz",
                "url": url,
            }
        elif url_type == "artist":
            meta = qobuz.client.api_call("artist/get", id=item_id, offset=0)
            if not meta:
                return jsonify({"ok": False, "error": "Artist metadata not found"}), 404
            
            # Safely resolve image
            image = meta.get("image") or {}
            cover = image.get("large") or meta.get("picture_large") or meta.get("picture") or image.get("medium") or ""
            
            result = {
                "type": "artist",
                "title": meta.get("name", ""),
                "artist": meta.get("name", ""),
                "cover": cover,
                "albums": meta.get("albums_count", 0),
                "url": url,
            }
        elif url_type == "playlist":
            meta = list(qobuz.client.get_plist_meta(item_id))[0]
            result = {
                "type": "playlist",
                "title": meta.get("name", ""),
                "artist": meta.get("owner", {}).get("name", ""),
                "cover": meta.get("images300", [None])[0]
                if meta.get("images300")
                else "",
                "tracks": meta.get("tracks_count", 0),
                "url": url,
            }
        else:
            result = {
                "type": url_type,
                "title": item_id,
                "artist": "",
                "cover": "",
                "url": url,
            }

        return jsonify({"ok": True, "result": result})
    except Exception as e:
        logging.error(f"Resolve failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500



# ---------------------------------------------------------------------------
# API: check_discography (async deep resolution for artists)
# ---------------------------------------------------------------------------
@app.route("/api/check_discography", methods=["POST"])
def api_check_discography():
    qobuz = _get_qobuz()
    if not qobuz or not qobuz.client:
        return jsonify({"ok": False, "error": "Not connected."}), 400

    data = request.json or {}
    url = data.get("url", "")
    try:
        from qobuz_dl.core import get_url_info
        from qobuz_dl.utils import smart_discography_filter
        
        url_type, item_id = get_url_info(url)
        if url_type != "artist":
            return jsonify({"ok": False, "error": "URL is not an artist"}), 400

        content = list(qobuz.client.get_artist_meta(item_id))
        
        # Calculate raw counts
        all_albums_raw = []
        raw_albums = 0
        raw_tracks = 0
        for item in content:
            albums_chunk = item.get("albums", {}).get("items", [])
            all_albums_raw.extend(albums_chunk)
            raw_albums += len(albums_chunk)
            for album in albums_chunk:
                raw_tracks += album.get("tracks_count", 0)

        if all_albums_raw:
            print(f"ALBUM DUMP [{all_albums_raw[0].get('title')}]: {all_albums_raw[0]}", flush=True)
                
        def calc_stats(album_list):
            return len(album_list), sum(a.get("tracks_count", 0) for a in album_list)

        # 1. Smart Discography (SD) items
        sd_items = smart_discography_filter(content, save_space=True, skip_extras=True)
        sd_albums, sd_tracks = calc_stats(sd_items)

        # 2. Albums Only (AO) items
        ao_items = [
            a for a in all_albums_raw 
            if a.get("release_type") == "album" and a.get("artist", {}).get("name") != "Various Artists"
        ]
        ao_albums, ao_tracks = calc_stats(ao_items)

        # 3. Both (SD + AO) items
        # Just run the AO filter on the sd_items since they compound cleanly
        both_items = [
            a for a in sd_items 
            if a.get("release_type") == "album" and a.get("artist", {}).get("name") != "Various Artists"
        ]
        both_albums, both_tracks = calc_stats(both_items)

        return jsonify({
            "ok": True, 
            "result": {
                "raw_albums": raw_albums,
                "raw_tracks": raw_tracks,
                "sd_filtered_albums": sd_albums,
                "sd_filtered_tracks": sd_tracks,
                "ao_filtered_albums": ao_albums,
                "ao_filtered_tracks": ao_tracks,
                "both_filtered_albums": both_albums,
                "both_filtered_tracks": both_tracks,
                "diff_sd": raw_albums - sd_albums,
                "diff_ao": raw_albums - ao_albums,
                "diff_both": raw_albums - both_albums
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        logging.error(f"check_discography failed: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# API: download (background thread)
# ---------------------------------------------------------------------------
@app.route("/api/download", methods=["POST"])
def api_download():
    global _download_active
    qobuz = _get_qobuz()
    if not qobuz:
        return jsonify(
            {"ok": False, "error": "Not connected. Please set up or connect first."}
        ), 400
    if _download_active:
        return jsonify({"ok": False, "error": "A download is already running."}), 400

    data = request.json or {}
    raw_urls = data.get("urls", "")
    urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]
    if not urls:
        return jsonify({"ok": False, "error": "No URLs provided"}), 400

    overrides = {
        "quality": data.get("quality"),
        "directory": data.get("directory"),
        "embed_art": data.get("embed_art", False),
        "lyrics_enabled": data.get("lyrics_enabled", False),
        "albums_only": data.get("albums_only", False),
        "no_m3u": data.get("no_m3u", False),
        "no_fallback": data.get("no_fallback", False),
        "og_cover": data.get("og_cover", False),
        "no_cover": data.get("no_cover", False),
        "no_db": data.get("no_db", False),
        "smart_discography": data.get("smart_discography", False),
        "folder_format": data.get("folder_format"),
        "track_format": data.get("track_format"),
        "fix_md5s": data.get("fix_md5s", False),
        "multiple_disc_prefix": data.get("multiple_disc_prefix"),
        "multiple_disc_one_dir": data.get("multiple_disc_one_dir", False),
        "multiple_disc_track_format": data.get("multiple_disc_track_format"),
        "max_workers": data.get("max_workers"),
        "delay_seconds": data.get("delay_seconds"),
        "segmented_fallback": data.get("segmented_fallback", True),
        "no_credits": data.get("no_credits", False),
        "native_lang": data.get("native_lang", False),
        "no_album_artist_tag": data.get("no_album_artist_tag", False),
        "no_album_title_tag": data.get("no_album_title_tag", False),
        "no_track_artist_tag": data.get("no_track_artist_tag", False),
        "no_track_title_tag": data.get("no_track_title_tag", False),
        "no_release_date_tag": data.get("no_release_date_tag", False),
        "no_media_type_tag": data.get("no_media_type_tag", False),
        "no_genre_tag": data.get("no_genre_tag", False),
        "no_track_number_tag": data.get("no_track_number_tag", False),
        "no_track_total_tag": data.get("no_track_total_tag", False),
        "no_disc_number_tag": data.get("no_disc_number_tag", False),
        "no_disc_total_tag": data.get("no_disc_total_tag", False),
        "no_composer_tag": data.get("no_composer_tag", False),
        "no_explicit_tag": data.get("no_explicit_tag", False),
        "no_copyright_tag": data.get("no_copyright_tag", False),
        "no_label_tag": data.get("no_label_tag", False),
        "no_upc_tag": data.get("no_upc_tag", False),
        "no_isrc_tag": data.get("no_isrc_tag", False),
    }

    def run():
        global _download_active
        _download_active = True
        _cancel_download.clear()
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE)
        try:
            tmp = _build_qobuz_from_config(cfg, overrides)
            with _client_lock:
                tmp.client = qobuz.client
            tmp.client.set_language_headers(tmp.native_lang)
            print(f"DEBUG: Worker thread starting. cancel_event id={id(_cancel_download)}")
            tmp.cancel_event = _cancel_download
            logging.info(f"Starting download of {len(urls)} URL(s)…")
            for url in urls:
                if _cancel_download.is_set():
                    logging.info("Download cancelled by user.")
                    break
                _emit_event({"type": "url_start", "url": url})
                _ctx_start_url()
                try:
                    tmp.handle_url(url)
                except Exception as e:
                    logging.error(f"Error downloading {url}: {e}")
                    _ctx_mark_error()
                had_error = _ctx_finish_url()
                # If the user cancelled mid-item, don't mark it done or errored | leave the
                # card in its current state; dl_complete will clean up.
                if _cancel_download.is_set():
                    break
                if had_error:
                    _emit_event({"type": "url_error", "url": url})
                else:
                    _emit_event({"type": "url_done", "url": url})
            if not _cancel_download.is_set():
                logging.info("All downloads complete.")
        except Exception as e:
            logging.error(f"Download error: {e}")
        finally:
            _emit_event({"type": "dl_complete", "cancelled": _cancel_download.is_set()})
            _download_active = False

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({"ok": True, "queued": len(urls)})


# ---------------------------------------------------------------------------
# API: cancel download
# ---------------------------------------------------------------------------
@app.route("/api/cancel", methods=["POST"])
def api_cancel():
    if _download_active:
        print(f"DEBUG: api_cancel hit. setting id={id(_cancel_download)}")
        sys.stdout.flush()
        _cancel_download.set()
        logging.info("Cancelling | current item will finish then stop…")
        
        def purge():
            with _log_lock:
                for q in _log_queues:
                    while not q.empty():
                        try:
                            q.get_nowait()
                        except queue.Empty:
                            break
        
        # Immediate purge
        purge()
        
        # Second purge after a small delay to catch any lingering logs from the worker thread
        def delayed_purge():
            time.sleep(0.5)
            purge()
            # Emit final status
            _emit_event({"type": "dl_complete", "cancelled": True})
            
        threading.Thread(target=delayed_purge, daemon=True).start()
        
    return jsonify({"ok": True})


def _config_download_root_resolved() -> Path:
    folder = "Qobuz Downloads"
    if os.path.isfile(CONFIG_FILE):
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE)
        folder = cfg["DEFAULT"].get("default_folder", folder) or folder
    folder = (folder or "Qobuz Downloads").strip() or "Qobuz Downloads"
    return Path(folder).expanduser().resolve()


def _lyrics_explicit_tag_enabled_from_config() -> bool:
    """Mirror download tagging: when ``no_explicit_tag`` is false, allow ITUNESADVISORY updates."""
    if not os.path.isfile(CONFIG_FILE):
        return True
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)
    return not cfg.getboolean("DEFAULT", "no_explicit_tag", fallback=False)


def _audio_path_allowed_for_lyrics_attach(audio_path: str) -> bool:
    try:
        p = Path(audio_path).expanduser().resolve()
    except OSError:
        return False
    if not p.is_file():
        return False
    root = _config_download_root_resolved()
    try:
        p.relative_to(root)
    except ValueError:
        return False
    if p.suffix.lower() not in (
        ".flac",
        ".mp3",
        ".m4a",
        ".ogg",
        ".opus",
        ".wav",
        ".aiff",
        ".aif",
    ):
        return False
    return True


def _reveal_file_in_os(file_path: Path) -> None:
    """Open the system file manager and reveal ``file_path`` (Windows / macOS / Linux)."""
    p = file_path.expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        subprocess.Popen(["open", "-R", str(p)])
    elif system == "Windows":
        subprocess.Popen(["explorer", "/select,", str(p)])
    else:
        if shutil.which("nautilus"):
            subprocess.Popen(["nautilus", "--select", str(p)])
        elif shutil.which("dolphin"):
            subprocess.Popen(["dolphin", "--select", str(p)])
        elif shutil.which("nemo"):
            subprocess.Popen(["nemo", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p.parent)])


@app.route("/api/reveal-in-folder", methods=["POST"])
def api_reveal_in_folder():
    """Reveal a downloaded track in the OS file manager (path must be under library root)."""
    data = request.get_json(silent=True) or {}
    audio_path = (data.get("audio_path") or data.get("path") or "").strip()
    if not audio_path:
        return jsonify({"ok": False, "error": "audio_path required"}), 400
    if not _audio_path_allowed_for_lyrics_attach(audio_path):
        return jsonify({"ok": False, "error": "invalid or disallowed path"}), 400
    try:
        _reveal_file_in_os(Path(audio_path))
    except Exception as e:
        logging.error("reveal-in-folder: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: download history (SQLite; survives restarts for files still on disk)
# ---------------------------------------------------------------------------
@app.route("/api/download-history", methods=["GET"])
def api_download_history():
    from qobuz_dl import db as _qdb

    items = _qdb.list_gui_download_history()
    safe = [
        it
        for it in items
        if _audio_path_allowed_for_lyrics_attach(it.get("audio_path") or "")
    ]
    return jsonify({"ok": True, "items": safe})


@app.route("/api/download-history/upsert", methods=["POST"])
def api_download_history_upsert():
    from qobuz_dl import db as _qdb

    data = request.get_json(silent=True) or {}
    audio_path = (data.get("audio_path") or "").strip()
    if not audio_path:
        return jsonify({"ok": False, "error": "audio_path required"}), 400
    if not _audio_path_allowed_for_lyrics_attach(audio_path):
        return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
    te = data.get("track_explicit", None)
    if te is None or te == "":
        track_explicit = None
    elif isinstance(te, bool):
        track_explicit = 1 if te else 0
    elif isinstance(te, (int, float)):
        track_explicit = 1 if int(te) else 0
    else:
        s = str(te).strip().lower()
        if s in ("1", "true", "yes", "on"):
            track_explicit = 1
        elif s in ("0", "false", "no", "off"):
            track_explicit = 0
        else:
            track_explicit = None
    try:
        duration_sec = int(data.get("duration_sec") or 0)
    except (TypeError, ValueError):
        duration_sec = 0
    _qdb.upsert_gui_download_history(
        audio_path,
        track_no=str(data.get("track_no") or ""),
        title=str(data.get("title") or ""),
        cover_url=str(data.get("cover_url") or ""),
        lyric_artist=str(data.get("lyric_artist") or ""),
        lyric_album=str(data.get("lyric_album") or ""),
        duration_sec=duration_sec,
        track_explicit=track_explicit,
        download_status=str(data.get("download_status") or "downloaded"),
        download_detail=str(data.get("download_detail") or ""),
        lyric_type=str(data.get("lyric_type") or ""),
        lyric_provider=str(data.get("lyric_provider") or ""),
        lyric_confidence=str(data.get("lyric_confidence") or ""),
    )
    return jsonify({"ok": True})


@app.route("/api/download-history/lyrics", methods=["POST"])
def api_download_history_lyrics():
    from qobuz_dl import db as _qdb

    data = request.get_json(silent=True) or {}
    audio_path = (data.get("audio_path") or "").strip()
    if not audio_path:
        return jsonify({"ok": False, "error": "audio_path required"}), 400
    if not _audio_path_allowed_for_lyrics_attach(audio_path):
        return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
    lyric_type = (data.get("lyric_type") or "").strip()
    if not lyric_type:
        return jsonify({"ok": False, "error": "lyric_type required"}), 400
    _qdb.update_gui_download_history_lyrics(
        audio_path,
        lyric_type=lyric_type,
        lyric_provider=str(data.get("lyric_provider") or ""),
        lyric_confidence=str(data.get("lyric_confidence") or ""),
    )
    return jsonify({"ok": True})


@app.route("/api/download-history/clear", methods=["POST"])
def api_download_history_clear():
    from qobuz_dl import db as _qdb

    _qdb.clear_gui_download_history()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: lyrics (LRCLIB browse / attach)
# ---------------------------------------------------------------------------
@app.route("/api/lyrics/search", methods=["POST"])
def api_lyrics_search():
    from qobuz_dl import lyrics as lyrics_mod

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    artist = (data.get("artist") or "").strip()
    album = (data.get("album") or "").strip()
    try:
        duration_sec = int(data.get("duration_sec") or 0)
    except (TypeError, ValueError):
        duration_sec = 0
    if not title or not artist:
        return jsonify({"ok": False, "error": "title and artist are required"}), 400
    te = data.get("track_explicit", None)
    track_explicit: Optional[bool]
    if te is None or te == "":
        track_explicit = None
    elif isinstance(te, bool):
        track_explicit = te
    else:
        s = str(te).strip().lower()
        track_explicit = s in ("1", "true", "yes", "on")
    filter_mismatched = data.get("filter_mismatched", True)
    if isinstance(filter_mismatched, str):
        filter_mismatched = filter_mismatched.lower() in ("1", "true", "yes", "on")
    else:
        filter_mismatched = bool(filter_mismatched)
    try:
        rows = lyrics_mod.lrclib_search_candidates_for_ui(
            title,
            artist,
            album,
            duration_sec,
            timeout_sec=18.0,
            track_explicit=track_explicit,
            filter_mismatched=filter_mismatched,
        )
    except Exception as e:
        logging.error("LRCLIB search error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify(
        {"ok": True, "results": rows, "reference_duration_sec": duration_sec}
    )


@app.route("/api/lyrics/fetch", methods=["GET"])
def api_lyrics_fetch():
    from qobuz_dl import lyrics as lyrics_mod

    try:
        rid = int(request.args.get("id", ""))
    except ValueError:
        return jsonify({"ok": False, "error": "invalid id"}), 400
    rec = lyrics_mod.lrclib_get_by_id(rid, timeout_sec=18.0)
    if not rec:
        return jsonify({"ok": False, "error": "not found"}), 404
    synced = (rec.get("syncedLyrics") or "").strip()
    plain = (rec.get("plainLyrics") or "").strip()
    scan = f"{synced}\n{plain}".strip()
    lyrics_explicit = (
        lyrics_mod.lyrics_text_indicates_explicit(scan) if scan else False
    )
    return jsonify(
        {"ok": True, "record": rec, "lyrics_explicit": lyrics_explicit}
    )


@app.route("/api/lyrics/attach", methods=["POST"])
def api_lyrics_attach():
    from qobuz_dl import lyrics as lyrics_mod

    data = request.get_json(silent=True) or {}
    audio_path = (data.get("audio_path") or "").strip()
    try:
        lrclib_id = int(data.get("lrclib_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "lrclib_id required"}), 400
    if not _audio_path_allowed_for_lyrics_attach(audio_path):
        return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
    try:
        out, lyrics_explicit, tag_applied = lyrics_mod.attach_lrclib_id_to_audio(
            audio_path,
            lrclib_id,
            overwrite=True,
            timeout_sec=18.0,
            update_explicit_tag=_lyrics_explicit_tag_enabled_from_config(),
        )
    except Exception as e:
        logging.error("Lyrics attach error: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500
    if not out:
        return jsonify({"ok": False, "error": "no lyrics to write"}), 400
    return jsonify(
        {
            "ok": True,
            "lrc_path": out,
            "lyrics_explicit": lyrics_explicit,
            "explicit_tag_updated": tag_applied,
        }
    )


@app.route("/api/lyrics/attached-id", methods=["GET"])
def api_lyrics_attached_id():
    """LRCLIB id stored beside the track when lyrics were attached or auto-saved."""
    from qobuz_dl import lyrics as lyrics_mod

    audio_path = (request.args.get("audio_path") or "").strip()
    if not audio_path:
        return jsonify({"ok": False, "error": "audio_path required"}), 400
    if not _audio_path_allowed_for_lyrics_attach(audio_path):
        return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
    rid = lyrics_mod.read_lrclib_id_sidecar(audio_path)
    return jsonify({"ok": True, "attached_lrclib_id": rid})


@app.route("/api/lyrics/stream-audio", methods=["GET"])
def api_lyrics_stream_audio():
    """Stream a local track for lyric preview (same path rules as attach)."""
    audio_path = (request.args.get("path") or "").strip()
    if not audio_path:
        return jsonify({"ok": False, "error": "path required"}), 400
    if not _audio_path_allowed_for_lyrics_attach(audio_path):
        return jsonify({"ok": False, "error": "invalid or disallowed path"}), 403
    p = Path(audio_path).expanduser().resolve()
    if not p.is_file():
        return jsonify({"ok": False, "error": "not found"}), 404
    try:
        return send_file(p, conditional=True, download_name=p.name)
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "not found"}), 404


# ---------------------------------------------------------------------------
# API: search
# ---------------------------------------------------------------------------
@app.route("/api/search")
def api_search():
    qobuz = _get_qobuz()
    if not qobuz:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    query = request.args.get("q", "").strip()
    item_type = request.args.get("type", "album")
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))

    if len(query) < 3:
        return jsonify({"ok": False, "error": "Query too short (min 3 chars)"}), 400

    try:
        results = qobuz.search_by_type(query, item_type, limit)
        return jsonify({"ok": True, "results": results or []})
    except Exception as e:
        logging.error(f"Search error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500




# ---------------------------------------------------------------------------
# API: lucky download
# ---------------------------------------------------------------------------
@app.route("/api/lucky", methods=["POST"])
def api_lucky():
    qobuz = _get_qobuz()
    if not qobuz:
        return jsonify({"ok": False, "error": "Not connected"}), 400

    data = request.json or {}
    query = data.get("query", "").strip()
    lucky_type = data.get("type", "album")
    number = int(data.get("number", 1))

    if len(query) < 3:
        return jsonify({"ok": False, "error": "Query too short"}), 400

    def run():
        try:
            cfg = configparser.ConfigParser()
            cfg.read(CONFIG_FILE)
            tmp = _build_qobuz_from_config(cfg)
            with _client_lock:
                tmp.client = qobuz.client
            tmp.cancel_event = _cancel_download
            tmp.lucky_type = lucky_type
            tmp.lucky_limit = number
            logging.info(f'Lucky download: "{query}" ({lucky_type}, top {number})')
            tmp.lucky_mode(query)
            logging.info("Lucky download complete.")
        except Exception as e:
            logging.error(f"Lucky error: {e}")

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: purge database
# ---------------------------------------------------------------------------
@app.route("/api/purge", methods=["POST"])
def api_purge():
    try:
        os.remove(QOBUZ_DB)
        logging.info("Download database purged.")
        return jsonify({"ok": True})
    except FileNotFoundError:
        return jsonify({"ok": True, "note": "Database did not exist"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# SSE: log stream
# ---------------------------------------------------------------------------
@app.route("/api/stream")
def api_stream():
    def event_stream():
        q = queue.Queue(maxsize=200)
        with _log_lock:
            _log_queues.append(q)
        try:
            # Send a keep-alive immediately
            yield "data: \n\n"
            while True:
                try:
                    msg = q.get(timeout=20)
                    if isinstance(msg, dict):
                        import json as _json

                        yield f"event: status\ndata: {_json.dumps(msg)}\n\n"
                    else:
                        import re

                        clean = re.sub(r"\x1b\[[0-9;]*m", "", msg)
                        yield f"data: {clean}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with _log_lock:
                try:
                    _log_queues.remove(q)
                except ValueError:
                    pass

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


_DEV_GUI_PORT_VITE = 8765


def _listen_port() -> int:
    """Listen port: ``QOBUZ_DL_GUI_PORT``, else unpackaged default 8765 (Vite proxy), else random."""
    raw = os.environ.get("QOBUZ_DL_GUI_PORT", "").strip()
    if raw.isdigit():
        p = int(raw)
        if 1 <= p <= 65535:
            return p
    if getattr(sys, "frozen", False):
        return _pick_free_port()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", _DEV_GUI_PORT_VITE))
    except OSError:
        logging.warning(
            "Port %s is in use; using a random GUI port. For Vite, free that port or set "
            "QOBUZ_DL_GUI_PORT to the same value for Python and npm.",
            _DEV_GUI_PORT_VITE,
        )
        return _pick_free_port()
    logging.info(
        "GUI server on port %s (unpackaged default; Vite proxies here).",
        _DEV_GUI_PORT_VITE,
    )
    return _DEV_GUI_PORT_VITE


def _wait_for_port(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"Server did not accept connections on {host}:{port}")


def main():
    """Entry point for the console script."""
    global _qobuz_client

    os.makedirs(CONFIG_PATH, exist_ok=True)
    try:
        from qobuz_dl import updater

        updater.cleanup_stale_exe_backup()
    except Exception:
        pass
    try:
        from qobuz_dl import db as _qdb

        _n = _qdb.prune_lrclib_by_audio_orphans()
        if _n:
            logging.info(
                "Removed %d stale LRCLIB link(s) (audio files no longer on disk).",
                _n,
            )
        _h = _qdb.prune_gui_download_history_orphans()
        if _h:
            logging.info(
                "Removed %d stale GUI download history row(s) (audio files no longer on disk).",
                _h,
            )
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        _idx = os.path.join(GUI_DIR, "index.html")
        if not os.path.isfile(_idx):
            _msg = (
                "The application bundle is incomplete (GUI files missing).\n\n"
                f"{_idx}\n\n"
                "Re-download Qobuz-DL-GUI from GitHub Releases."
            )
            logging.critical(_msg)
            if os.name == "nt":
                try:
                    import ctypes

                    ctypes.windll.user32.MessageBoxW(0, _msg, "Qobuz-DL-GUI", 0x10)
                except Exception:
                    pass
            sys.exit(1)

    logging.info("Qobuz-DL GUI starting…")

    # Auto-connect if config already exists
    if os.path.isfile(CONFIG_FILE):
        try:
            cfg = configparser.ConfigParser()
            cfg.read(CONFIG_FILE)
            app_id = cfg["DEFAULT"].get("app_id", "")
            secrets_list = [
                s for s in cfg["DEFAULT"].get("secrets", "").split(",") if s
            ]
            user_id = cfg["DEFAULT"].get("user_id", "").strip()
            user_auth_token = cfg["DEFAULT"].get("user_auth_token", "").strip()
            email = cfg["DEFAULT"].get("email", "").strip()
            password = cfg["DEFAULT"].get("password", "").strip()

            from qobuz_dl.core import QobuzDL

            qobuz = _build_qobuz_from_config(cfg)

            if user_id and user_auth_token:
                qobuz.initialize_client_with_token(
                    user_id, user_auth_token, app_id, secrets_list
                )
                logging.info("Auto-connected via saved OAuth token.")
            elif email and password:
                qobuz.initialize_client(email, password, app_id, secrets_list)
                logging.info("Auto-connected from saved email/password config.")
            else:
                logging.info(
                    "Config found but no credentials | connect via the GUI."
                )
                qobuz = None

            if qobuz:
                _qobuz_client = qobuz
        except Exception as e:
            logging.info("Could not auto-connect: %s", e)

    port = _listen_port()
    url = f"http://127.0.0.1:{port}/"
    if os.environ.get("QOBUZ_DL_GUI_PORT", "").strip():
        logging.info("GUI server port (QOBUZ_DL_GUI_PORT): %s", port)

    def run_flask():
        app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False,
        )

    def open_browser_soon():
        time.sleep(0.4)
        webbrowser.open(url)

    use_browser = os.environ.get("QOBUZ_DL_GUI_BROWSER", "").lower() in (
        "1",
        "true",
        "yes",
    )

    if use_browser:
        logging.info("Using system browser (QOBUZ_DL_GUI_BROWSER is set).")
        threading.Thread(target=open_browser_soon, daemon=True).start()
        run_flask()
        return

    try:
        import webview
    except ImportError:
        logging.error(
            "pywebview is not installed; open %s in a browser or: pip install pywebview",
            url,
        )
        threading.Thread(target=open_browser_soon, daemon=True).start()
        run_flask()
        return

    threading.Thread(target=run_flask, daemon=True).start()
    _wait_for_port("127.0.0.1", port)

    # Open at minimum width; min height is slightly taller than before for usability.
    _win_min_w, _win_min_h = 880, 650
    webview.create_window(
        "Qobuz-DL",
        url,
        width=1030,
        height=684,
        min_size=(_win_min_w, _win_min_h),
        text_select=True,
    )
    webview.start(debug=False)
    os._exit(0)

if __name__ == "__main__":
    main()
