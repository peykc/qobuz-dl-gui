import logging
import os
import sys

from flask import jsonify, request


def _resolve(value):
    return value() if callable(value) else value


def register_update_routes(app, *, config_path) -> None:
    @app.route("/api/update/check")
    def api_update_check():
        from qobuz_dl import updater

        force = request.args.get("force") == "1"
        return jsonify(updater.check_for_update(_resolve(config_path), force=force))

    @app.route("/api/update/install", methods=["POST"])
    def api_update_install():
        from qobuz_dl import updater
        from qobuz_dl.version import GITHUB_RELEASE_REPO

        data = request.json or {}
        url = (data.get("download_url") or "").strip()
        if not updater.is_safe_release_asset_url(url, GITHUB_RELEASE_REPO.strip()):
            return jsonify({"ok": False, "error": "Invalid or untrusted download URL"}), 400
        auto_platform = os.name == "nt" or sys.platform.startswith("linux")
        if not getattr(sys, "frozen", False) or not auto_platform:
            return jsonify(
                {
                    "ok": False,
                    "error": "Automatic install is only available for Windows and Linux frozen builds.",
                }
            ), 400
        try:
            path = updater.download_update_to_temp(url)
        except Exception as e:
            logging.error("Update download failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

        updater.schedule_stage_update_and_exit(path)
        return jsonify({"ok": True, "restarting": True})
