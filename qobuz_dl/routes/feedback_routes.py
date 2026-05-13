import logging

from flask import jsonify, request

from qobuz_dl.services.feedback_service import (
    load_feedback_history,
    save_feedback_history,
)


def _resolve(value):
    return value() if callable(value) else value


def register_feedback_routes(app, *, config_path, feedback_history_json) -> None:
    @app.route("/api/feedback-history", methods=["GET", "POST"])
    def api_feedback_history():
        """Persist feedback history on disk (pywebview localStorage can be ephemeral)."""
        path = _resolve(feedback_history_json)
        if request.method == "GET":
            return jsonify({"ok": True, "items": load_feedback_history(path)})
        try:
            body = request.get_json(silent=True) or {}
            items = body.get("items")
            if not isinstance(items, list):
                return jsonify({"ok": False, "error": "items must be a list"}), 400
            save_feedback_history(path, _resolve(config_path), items)
            return jsonify({"ok": True})
        except Exception as e:
            logging.warning("feedback-history save failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
