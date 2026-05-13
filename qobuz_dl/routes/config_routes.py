import configparser
import hashlib
import os

from flask import jsonify, request


def _resolve(value):
    return value() if callable(value) else value


def register_config_routes(app, *, config_file, on_config_updated) -> None:
    @app.route("/api/config", methods=["GET", "POST"])
    def api_config():
        config_file_value = _resolve(config_file)
        if not os.path.isfile(config_file_value):
            return jsonify({"ok": False, "error": "No config file"}), 400

        cfg = configparser.ConfigParser()
        cfg.read(config_file_value)

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
        with open(config_file_value, "w") as f:
            cfg.write(f)
        on_config_updated(cfg)
        return jsonify({"ok": True})
