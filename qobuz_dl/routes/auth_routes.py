import configparser
import hashlib
import logging
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from flask import jsonify, request

from qobuz_dl.config_defaults import apply_common_defaults


def _write_config(path, cfg):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        cfg.write(f)


def _set_connected(client_lock, set_qobuz, qobuz):
    with client_lock:
        set_qobuz(qobuz)


def register_auth_routes(
    app,
    *,
    config_file,
    build_qobuz_from_config,
    client_lock,
    set_qobuz,
) -> None:
    @app.route("/api/setup", methods=["POST"])
    def api_setup():
        data = request.json or {}
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        folder = data.get("default_folder", "Qobuz Downloads").strip()
        folder = folder or "Qobuz Downloads"
        quality = data.get("default_quality", "27")

        if not email or not password:
            return jsonify({"ok": False, "error": "Email and password are required"}), 400

        try:
            from qobuz_dl.bundle import Bundle

            logging.info("Fetching Qobuz tokens, please wait…")
            bundle = Bundle()
            app_id = str(bundle.get_app_id())
            secrets = ",".join(bundle.get_secrets().values())

            cfg = configparser.ConfigParser()
            cfg["DEFAULT"]["email"] = email
            cfg["DEFAULT"]["password"] = hashlib.md5(
                password.encode("utf-8")
            ).hexdigest()
            cfg["DEFAULT"]["default_folder"] = folder
            cfg["DEFAULT"]["default_quality"] = str(quality)
            cfg["DEFAULT"]["app_id"] = app_id
            cfg["DEFAULT"]["secrets"] = secrets
            cfg["DEFAULT"]["private_key"] = bundle.get_private_key() or ""
            cfg["DEFAULT"]["user_id"] = ""
            cfg["DEFAULT"]["user_auth_token"] = ""
            apply_common_defaults(cfg["DEFAULT"], no_database="true")
            _write_config(config_file(), cfg)

            qobuz = build_qobuz_from_config(cfg)
            secrets_list = [s for s in secrets.split(",") if s]
            qobuz.initialize_client(email, cfg["DEFAULT"]["password"], app_id, secrets_list)
            _set_connected(client_lock, set_qobuz, qobuz)

            logging.info("Login successful.")
            return jsonify({"ok": True})
        except Exception as e:
            logging.error("Setup failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/connect", methods=["POST"])
    def api_connect():
        if not os.path.isfile(config_file()):
            return jsonify(
                {"ok": False, "error": "No config file found. Please set up first."}
            ), 400
        try:
            cfg = configparser.ConfigParser()
            cfg.read(config_file())
            app_id = cfg["DEFAULT"].get("app_id", "")
            secrets_list = [s for s in cfg["DEFAULT"].get("secrets", "").split(",") if s]
            user_id = cfg["DEFAULT"].get("user_id", "").strip()
            user_auth_token = cfg["DEFAULT"].get("user_auth_token", "").strip()
            email = cfg["DEFAULT"].get("email", "").strip()
            password = cfg["DEFAULT"].get("password", "").strip()

            qobuz = build_qobuz_from_config(cfg)
            if user_id and user_auth_token:
                qobuz.initialize_client_with_token(
                    user_id,
                    user_auth_token,
                    app_id,
                    secrets_list,
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

            _set_connected(client_lock, set_qobuz, qobuz)
            logging.info("Connected successfully.")
            return jsonify({"ok": True})
        except Exception as e:
            logging.error("Connect failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/oauth/start", methods=["POST"])
    def api_oauth_start():
        try:
            from qobuz_dl.bundle import Bundle

            bundle = Bundle()
            app_id = str(bundle.get_app_id())
            secrets_list = [s for s in bundle.get_secrets().values() if s]
            private_key = bundle.get_private_key() or ""

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                port = s.getsockname()[1]

            oauth_url = (
                f"https://www.qobuz.com/signin/oauth"
                f"?ext_app_id={app_id}"
                f"&redirect_url=http://127.0.0.1:{port}"
            )

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
                        self.wfile.write(
                            b"<html><body><h2>Login failed</h2></body></html>"
                        )

                def log_message(self, format, *args):
                    pass

            OAuthHandler.code = None

            def _run_oauth():
                try:
                    server = HTTPServer(("127.0.0.1", port), OAuthHandler)
                    logging.info("OAuth: waiting for browser redirect on port %s…", port)
                    server.handle_request()
                    server.server_close()

                    if not OAuthHandler.code:
                        logging.error("OAuth: no code received.")
                        return

                    cfg_read = configparser.ConfigParser()
                    cfg_read.read(config_file())
                    qobuz = build_qobuz_from_config(cfg_read)
                    qobuz.app_id = app_id
                    qobuz.secrets = secrets_list
                    qobuz.private_key = private_key
                    qobuz.initialize_client_with_oauth(
                        OAuthHandler.code,
                        app_id,
                        secrets_list,
                        private_key,
                    )

                    cfg_write = configparser.ConfigParser()
                    cfg_write.read(config_file())
                    cfg_write["DEFAULT"]["app_id"] = app_id
                    cfg_write["DEFAULT"]["secrets"] = ",".join(secrets_list)
                    cfg_write["DEFAULT"]["private_key"] = private_key
                    cfg_write["DEFAULT"]["user_auth_token"] = (
                        qobuz.oauth_user_auth_token or ""
                    )
                    cfg_write["DEFAULT"]["user_id"] = str(qobuz.oauth_user_id or "")
                    cfg_write["DEFAULT"]["email"] = ""
                    cfg_write["DEFAULT"]["password"] = ""
                    apply_common_defaults(cfg_write["DEFAULT"], no_database="true")
                    _write_config(config_file(), cfg_write)

                    _set_connected(client_lock, set_qobuz, qobuz)
                    logging.info("OAuth login complete. You are now connected.")
                except Exception as ex:
                    logging.error("OAuth error: %s", ex)

            threading.Thread(target=_run_oauth, daemon=True).start()
            webbrowser.open(oauth_url)
            logging.info("Opened browser for OAuth login. Waiting for redirect…")
            return jsonify({"ok": True, "url": oauth_url})
        except Exception as e:
            logging.error("OAuth start failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/token_login", methods=["POST"])
    def api_token_login():
        data = request.json or {}
        user_id = data.get("user_id", "").strip()
        user_auth_token = data.get("user_auth_token", "").strip()
        folder = data.get("default_folder", "Qobuz Downloads").strip()
        folder = folder or "Qobuz Downloads"
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

            cfg = configparser.ConfigParser()
            cfg["DEFAULT"]["email"] = ""
            cfg["DEFAULT"]["password"] = ""
            cfg["DEFAULT"]["user_id"] = user_id
            cfg["DEFAULT"]["user_auth_token"] = user_auth_token
            cfg["DEFAULT"]["default_folder"] = folder
            cfg["DEFAULT"]["default_quality"] = quality
            cfg["DEFAULT"]["app_id"] = app_id
            cfg["DEFAULT"]["secrets"] = ",".join(secrets_list)
            cfg["DEFAULT"]["private_key"] = private_key
            apply_common_defaults(cfg["DEFAULT"], no_database="true")
            _write_config(config_file(), cfg)

            qobuz = build_qobuz_from_config(cfg)
            qobuz.initialize_client_with_token(
                user_id,
                user_auth_token,
                app_id,
                secrets_list,
            )
            _set_connected(client_lock, set_qobuz, qobuz)

            logging.info("Token login successful.")
            return jsonify({"ok": True})
        except Exception as e:
            logging.error("Token login failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
