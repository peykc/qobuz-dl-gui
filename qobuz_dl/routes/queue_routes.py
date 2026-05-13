import logging
import os

from flask import jsonify, request

from qobuz_dl.services.queue_service import (
    build_download_queue_document,
    load_download_queue,
    save_download_queue,
)


def _resolve(value):
    return value() if callable(value) else value


def register_queue_routes(app, *, config_path: str, queue_json: str) -> None:
    @app.route("/api/download-queue", methods=["GET", "POST"])
    def api_download_queue():
        config_path_value = _resolve(config_path)
        queue_json_value = _resolve(queue_json)
        os.makedirs(config_path_value, exist_ok=True)
        if request.method == "GET":
            try:
                return jsonify(load_download_queue(queue_json_value))
            except Exception as e:
                logging.warning("download-queue load: %s", e)
                return jsonify(load_download_queue(""))

        payload = request.get_json(silent=True) or {}
        try:
            out_doc = build_download_queue_document(payload)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        except TypeError as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        try:
            save_download_queue(queue_json_value, out_doc)
        except Exception as e:
            logging.error("download-queue save: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True})
