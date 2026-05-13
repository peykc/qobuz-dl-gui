import configparser
import logging
import sys
import threading
import time

from flask import jsonify, request


def _download_overrides(data):
    return {
        "quality": data.get("quality"),
        "directory": data.get("directory"),
        "embed_art": data.get("embed_art", False),
        "lyrics_enabled": data.get("lyrics_enabled", False),
        "lyrics_embed_metadata": data.get("lyrics_embed_metadata", False),
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
        "tag_title_from_track_format": data.get("tag_title_from_track_format", True),
        "tag_album_from_folder_format": data.get("tag_album_from_folder_format", True),
    }


def register_download_routes(
    app,
    *,
    get_qobuz,
    config_file,
    build_qobuz_from_config,
    client_lock,
    cancel_event,
    abort_stream_event,
    state,
    event_hub,
    update_session_download_root,
    emit_event,
    ctx_start_url,
    ctx_mark_error,
    ctx_finish_url,
) -> None:
    @app.route("/api/download", methods=["POST"])
    def api_download():
        qobuz = get_qobuz()
        if not qobuz:
            return jsonify(
                {"ok": False, "error": "Not connected. Please set up or connect first."}
            ), 400
        if state["download_active"]:
            return jsonify({"ok": False, "error": "A download is already running."}), 400

        data = request.json or {}
        raw_urls = data.get("urls", "")
        urls = [u.strip() for u in raw_urls.splitlines() if u.strip()]
        if not urls:
            return jsonify({"ok": False, "error": "No URLs provided"}), 400

        overrides = _download_overrides(data)

        def run():
            state["download_active"] = True
            cancel_event.clear()
            abort_stream_event.clear()
            state["graceful_stop"] = None
            cfg = configparser.ConfigParser()
            cfg.read(config_file())
            try:
                update_session_download_root(cfg, overrides)
                tmp = build_qobuz_from_config(cfg, overrides)
                with client_lock:
                    tmp.client = qobuz.client
                tmp.client.set_language_headers(tmp.native_lang)
                print(f"DEBUG: Worker thread starting. cancel_event id={id(cancel_event)}")
                tmp.cancel_event = cancel_event
                tmp.abort_stream_event = abort_stream_event
                logging.info("Starting download of %d URL(s)…", len(urls))
                for url in urls:
                    if cancel_event.is_set():
                        logging.info("Download cancelled by user.")
                        break
                    emit_event({"type": "url_start", "url": url})
                    ctx_start_url()
                    try:
                        tmp.handle_url(url)
                    except Exception as e:
                        logging.error("Error downloading %s: %s", url, e)
                        ctx_mark_error()
                    had_error, url_err_detail = ctx_finish_url()
                    if cancel_event.is_set():
                        break
                    if had_error:
                        ev_ue = {"type": "url_error", "url": url}
                        if url_err_detail:
                            ev_ue["detail"] = url_err_detail
                        emit_event(ev_ue)
                    else:
                        emit_event({"type": "url_done", "url": url})
                if not cancel_event.is_set():
                    logging.info("All downloads complete.")
            except Exception as e:
                logging.error("Download error: %s", e)
            finally:
                was_stop = cancel_event.is_set()
                mode = state["graceful_stop"]
                paused = was_stop and mode == "pause"
                cancelled = was_stop and mode != "pause"
                emit_event(
                    {
                        "type": "dl_complete",
                        "cancelled": cancelled,
                        "paused": paused,
                    }
                )
                state["graceful_stop"] = None
                state["download_active"] = False

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True, "queued": len(urls)})

    @app.route("/api/cancel", methods=["POST"])
    def api_cancel():
        if state["download_active"]:
            print(f"DEBUG: api_cancel hit. setting id={id(cancel_event)}")
            sys.stdout.flush()
            state["graceful_stop"] = "cancel"
            cancel_event.set()
            abort_stream_event.set()
            logging.info("Cancelling | current item will finish then stop…")

            def purge():
                event_hub.drain_queues()

            purge()

            def delayed_purge():
                time.sleep(0.5)
                purge()

            threading.Thread(target=delayed_purge, daemon=True).start()

        return jsonify({"ok": True})

    @app.route("/api/pause", methods=["POST"])
    def api_pause():
        if state["download_active"]:
            state["graceful_stop"] = "pause"
            cancel_event.set()
            logging.info("Pause requested | in-flight downloads will finish then worker stops.")
        return jsonify({"ok": True})

    @app.route("/api/lucky", methods=["POST"])
    def api_lucky():
        qobuz = get_qobuz()
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
                cfg.read(config_file())
                tmp = build_qobuz_from_config(cfg)
                with client_lock:
                    tmp.client = qobuz.client
                tmp.cancel_event = cancel_event
                tmp.abort_stream_event = abort_stream_event
                tmp.lucky_type = lucky_type
                tmp.lucky_limit = number
                logging.info('Lucky download: "%s" (%s, top %s)', query, lucky_type, number)
                tmp.lucky_mode(query)
                logging.info("Lucky download complete.")
            except Exception as e:
                logging.error("Lucky error: %s", e)

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True})
