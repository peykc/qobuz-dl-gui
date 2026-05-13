import sys
import os

from pathlib import Path

import configparser
import hashlib
import logging
import threading
import time
import socket
import webbrowser

from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from qobuz_dl.app.events import GuiEventHub, GuiQueueHandler
from qobuz_dl.app.path_security import (
    audio_path_allowed_for_lyrics_attach as _path_allowed_for_lyrics_attach,
    reveal_file_in_os as _reveal_file_in_os,
)
from qobuz_dl.config_defaults import apply_common_defaults
from qobuz_dl.config_paths import (
    CONFIG_FILE,
    CONFIG_PATH,
    DOWNLOAD_QUEUE_JSON,
    GUI_FEEDBACK_HISTORY_JSON,
    QOBUZ_DB,
)
from qobuz_dl.routes.config_routes import register_config_routes
from qobuz_dl.routes.download_routes import register_download_routes
from qobuz_dl.routes.feedback_routes import register_feedback_routes
from qobuz_dl.routes.history_routes import register_history_routes
from qobuz_dl.routes.lyrics_routes import register_lyrics_routes
from qobuz_dl.routes.queue_routes import register_queue_routes
from qobuz_dl.routes.replacement_routes import register_replacement_routes
from qobuz_dl.routes.search_routes import register_search_routes
from qobuz_dl.routes.status_routes import register_status_routes
from qobuz_dl.routes.update_routes import register_update_routes
from qobuz_dl.routes.utility_routes import register_utility_routes
from qobuz_dl.services.qobuz_session import (
    build_qobuz_from_config as _build_qobuz_from_config,
)


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

_event_hub = GuiEventHub(session_log_limit=600)

# Last resolved download root (matches QobuzDL.directory for the active UI folder).
# Lyrics/stream endpoints allow paths under this OR under config default_folder, so
# features work when directory override differs from saved config (e.g. before autosave).
_session_download_root_lock = threading.Lock()
_session_download_root_resolved: Optional[Path] = None


def _emit_event(event_data: dict):
    """Push a structured JSON status event to all SSE consumers."""
    _event_hub.emit_event(event_data)


# Import core for monkey-patched GUI hooks (see assignments after URL context helpers).
import qobuz_dl.core


# ---------------------------------------------------------------------------
# QobuzDL client singleton
# ---------------------------------------------------------------------------
_client_lock = threading.Lock()
_qobuz_client = None  # QobuzDL instance
_cancel_download = threading.Event()  # graceful stop signal (pause or cancel share this)
_abort_byte_streams = (
    threading.Event()
)  # cancel-only — interrupt FLAC/cover HTTP chunks (pause lets bytes finish)
_download_active = False  # True while a download thread is running
_graceful_dl_stop: Optional[str] = None  # "pause" | "cancel" while stop requested; unset at run start/end
_download_state = {"download_active": False, "graceful_stop": None}
_url_ctx_lock = threading.Lock()
_url_ctx = {
    "tracking": False,
    "had_error": False,
    "url_error_detail": None,
}  # cross-thread URL error tracking


def _ctx_start_url():
    with _url_ctx_lock:
        _url_ctx["tracking"] = True
        _url_ctx["had_error"] = False
        _url_ctx["url_error_detail"] = None


def _ctx_mark_error():
    with _url_ctx_lock:
        if _url_ctx["tracking"]:
            _url_ctx["had_error"] = True


_queue_handler = GuiQueueHandler(_event_hub, on_error=_ctx_mark_error)
_queue_handler.setFormatter(logging.Formatter("%(message)s"))
logging.getLogger().addHandler(_queue_handler)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.ERROR)


def _ctx_finish_url() -> tuple[bool, Optional[str]]:
    with _url_ctx_lock:
        had_error = bool(_url_ctx["had_error"])
        detail = _url_ctx.get("url_error_detail")
        _url_ctx["tracking"] = False
        _url_ctx["had_error"] = False
        _url_ctx["url_error_detail"] = None
        return had_error, detail if isinstance(detail, str) and detail else None


def _note_streaming_blocked_release():
    """Downloader hook: album metadata marks the release as not streamable on Qobuz."""
    with _url_ctx_lock:
        if _url_ctx["tracking"]:
            _url_ctx["url_error_detail"] = "non_streamable"


qobuz_dl.core.ui_emitter = _emit_event
qobuz_dl.core.note_streaming_blocked_release = _note_streaming_blocked_release


def _get_qobuz():
    return _qobuz_client


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(GUI_DIR, "index.html")


@app.route("/gui/<path:filename>")
def gui_static(filename):
    return send_from_directory(GUI_DIR, filename)


register_status_routes(
    app,
    config_file=lambda: CONFIG_FILE,
    ready=lambda: _qobuz_client is not None,
)


register_feedback_routes(
    app,
    config_path=lambda: CONFIG_PATH,
    feedback_history_json=lambda: GUI_FEEDBACK_HISTORY_JSON,
)


# ---------------------------------------------------------------------------
# API: updates (GitHub Releases)
# ---------------------------------------------------------------------------
register_update_routes(app, config_path=lambda: CONFIG_PATH)


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
        cfg["DEFAULT"]["app_id"] = app_id
        cfg["DEFAULT"]["secrets"] = secrets
        cfg["DEFAULT"]["private_key"] = bundle.get_private_key() or ""
        cfg["DEFAULT"]["user_id"] = ""
        cfg["DEFAULT"]["user_auth_token"] = ""
        apply_common_defaults(cfg["DEFAULT"], no_database="true")

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
                    "lyrics_embed_metadata",
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
                    "tag_title_from_track_format",
                    "tag_album_from_folder_format",
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
                            "lyrics_embed_metadata": "false",
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
                            "tag_title_from_track_format": "true",
                            "tag_album_from_folder_format": "true",
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
        cfg["DEFAULT"]["lyrics_embed_metadata"] = "false"
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
        cfg["DEFAULT"]["tag_title_from_track_format"] = "true"
        cfg["DEFAULT"]["tag_album_from_folder_format"] = "true"
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


register_config_routes(
    app,
    config_file=lambda: CONFIG_FILE,
    on_config_updated=lambda cfg: _update_session_download_root(cfg),
)


register_search_routes(app, get_qobuz=_get_qobuz)


# ---------------------------------------------------------------------------
# API: download (background thread)
# ---------------------------------------------------------------------------
def _config_download_root_resolved() -> Path:
    folder = "Qobuz Downloads"
    if os.path.isfile(CONFIG_FILE):
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_FILE)
        folder = cfg["DEFAULT"].get("default_folder", folder) or folder
    folder = (folder or "Qobuz Downloads").strip() or "Qobuz Downloads"
    return Path(folder).expanduser().resolve()


def _update_session_download_root(
    cfg: configparser.ConfigParser,
    overrides: Optional[dict] = None,
) -> None:
    """Remember the resolved download directory (same rule as _build_qobuz_from_config)."""
    global _session_download_root_resolved
    o = overrides or {}
    folder = o.get("directory") or cfg.get(
        "DEFAULT", "default_folder", fallback="Qobuz Downloads"
    )
    folder = (folder or "Qobuz Downloads").strip() or "Qobuz Downloads"
    try:
        resolved = Path(folder).expanduser().resolve()
    except OSError:
        return
    with _session_download_root_lock:
        _session_download_root_resolved = resolved


def _download_roots_for_lyrics_allow() -> list[Path]:
    """Paths under any of these may stream / attach lyrics (sandbox)."""
    roots: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        key = str(p)
        if key not in seen:
            seen.add(key)
            roots.append(p)

    add(_config_download_root_resolved())
    with _session_download_root_lock:
        sr = _session_download_root_resolved
    if sr is not None:
        add(sr)
    return roots


def _lyrics_explicit_tag_enabled_from_config() -> bool:
    """Mirror download tagging: when ``no_explicit_tag`` is false, allow ITUNESADVISORY updates."""
    if not os.path.isfile(CONFIG_FILE):
        return True
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_FILE)
    return not cfg.getboolean("DEFAULT", "no_explicit_tag", fallback=False)


def _download_history_audio_path_accepted(audio_path: str) -> bool:
    """Real library files or synthetic pending-slot rows (persist purchase/failed slots)."""
    from qobuz_dl.db import is_gui_missing_placeholder_audio_path, is_gui_pending_track_key

    raw = (audio_path or "").strip()
    if is_gui_pending_track_key(raw):
        return True
    if is_gui_missing_placeholder_audio_path(raw):
        return _audio_path_allowed_for_lyrics_attach(raw)
    return _audio_path_allowed_for_lyrics_attach(raw)


def _audio_path_allowed_for_lyrics_attach(audio_path: str) -> bool:
    return _path_allowed_for_lyrics_attach(
        audio_path,
        _download_roots_for_lyrics_allow(),
    )


register_replacement_routes(
    app,
    get_qobuz=_get_qobuz,
    config_file=lambda: CONFIG_FILE,
    build_qobuz_from_config=_build_qobuz_from_config,
    download_roots_for_lyrics_allow=_download_roots_for_lyrics_allow,
)


register_utility_routes(
    app,
    event_hub=_event_hub,
    qobuz_db=lambda: QOBUZ_DB,
    audio_path_allowed_for_lyrics_attach=_audio_path_allowed_for_lyrics_attach,
    reveal_file_in_os=_reveal_file_in_os,
)


# ---------------------------------------------------------------------------
# API: download URL queue (persisted across GUI restarts)
# ---------------------------------------------------------------------------
register_queue_routes(
    app,
    config_path=lambda: CONFIG_PATH,
    queue_json=lambda: DOWNLOAD_QUEUE_JSON,
)


register_history_routes(
    app,
    download_history_audio_path_accepted=_download_history_audio_path_accepted,
    audio_path_allowed_for_lyrics_attach=_audio_path_allowed_for_lyrics_attach,
)


register_lyrics_routes(
    app,
    config_file=lambda: CONFIG_FILE,
    audio_path_allowed_for_lyrics_attach=_audio_path_allowed_for_lyrics_attach,
    lyrics_explicit_tag_enabled=_lyrics_explicit_tag_enabled_from_config,
)


register_download_routes(
    app,
    get_qobuz=_get_qobuz,
    config_file=lambda: CONFIG_FILE,
    build_qobuz_from_config=_build_qobuz_from_config,
    client_lock=_client_lock,
    cancel_event=_cancel_download,
    abort_stream_event=_abort_byte_streams,
    state=_download_state,
    event_hub=_event_hub,
    update_session_download_root=_update_session_download_root,
    emit_event=_emit_event,
    ctx_start_url=_ctx_start_url,
    ctx_mark_error=_ctx_mark_error,
    ctx_finish_url=_ctx_finish_url,
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

    try:
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
    except Exception as e:
        logging.error("pywebview failed; opening system browser instead: %s", e)
        threading.Thread(target=open_browser_soon, daemon=True).start()
        while True:
            time.sleep(3600)
    os._exit(0)

if __name__ == "__main__":
    main()
