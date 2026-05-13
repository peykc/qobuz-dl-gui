import logging
import os
from pathlib import Path

from flask import Response, jsonify, request


def _resolve(value):
    return value() if callable(value) else value


def register_utility_routes(
    app,
    *,
    event_hub,
    qobuz_db,
    audio_path_allowed_for_lyrics_attach,
    reveal_file_in_os,
) -> None:
    @app.route("/api/clipboard-text", methods=["GET"])
    def api_clipboard_text():
        """Return the system clipboard as UTF-8 text (localhost-only; used by GUI paste)."""
        try:
            import pyperclip
        except ImportError:
            return jsonify(
                ok=False,
                error="pyperclip is not installed",
            ), 501
        try:
            raw = pyperclip.paste()
            if raw is None:
                raw = ""
            return jsonify(ok=True, text=str(raw))
        except Exception as e:
            logging.warning("clipboard read failed: %s", e)
            return jsonify(ok=False, error=str(e)), 500

    @app.route("/api/session-logs", methods=["GET"])
    def api_session_logs():
        """Recent GUI log lines (plain text) for optional feedback attachment."""
        text = event_hub.session_log_text()
        return Response(
            text + ("\n" if text and not text.endswith("\n") else ""),
            mimetype="text/plain; charset=utf-8",
        )

    @app.route("/api/reveal-in-folder", methods=["POST"])
    def api_reveal_in_folder():
        """Reveal a downloaded track in the OS file manager."""
        data = request.get_json(silent=True) or {}
        audio_path = (data.get("audio_path") or data.get("path") or "").strip()
        if not audio_path:
            return jsonify({"ok": False, "error": "audio_path required"}), 400
        if not audio_path_allowed_for_lyrics_attach(audio_path):
            return jsonify({"ok": False, "error": "invalid or disallowed path"}), 400
        try:
            reveal_file_in_os(Path(audio_path))
        except Exception as e:
            logging.error("reveal-in-folder: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True})

    @app.route("/api/purge", methods=["POST"])
    def api_purge():
        try:
            os.remove(_resolve(qobuz_db))
            logging.info("Download database purged.")
            return jsonify({"ok": True})
        except FileNotFoundError:
            return jsonify({"ok": True, "note": "Database did not exist"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/stream")
    def api_stream():
        return Response(
            event_hub.stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
