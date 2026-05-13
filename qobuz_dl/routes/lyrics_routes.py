import configparser
import logging
from pathlib import Path

from flask import jsonify, request, send_file

from qobuz_dl.services.qobuz_session import as_bool


def _resolve(value):
    return value() if callable(value) else value


def register_lyrics_routes(
    app,
    *,
    config_file,
    audio_path_allowed_for_lyrics_attach,
    lyrics_explicit_tag_enabled,
) -> None:
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

    @app.route("/api/lyrics/local", methods=["GET"])
    def api_lyrics_local():
        from qobuz_dl import lyrics as lyrics_mod

        audio_path = (request.args.get("audio_path") or "").strip()
        if not audio_path:
            return jsonify({"ok": False, "error": "audio_path required"}), 400
        if not audio_path_allowed_for_lyrics_attach(audio_path):
            return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
        p = Path(audio_path).expanduser().resolve()
        lrc_path = p.with_suffix(".lrc")
        if not lrc_path.is_file():
            return jsonify({"ok": False, "error": "local lyrics not found"}), 404
        try:
            body = lrc_path.read_text(encoding="utf-8-sig").strip()
        except UnicodeDecodeError:
            body = lrc_path.read_text(encoding="utf-8", errors="replace").strip()
        lyrics_explicit = lyrics_mod.lyrics_text_indicates_explicit(body) if body else False
        is_synced = lyrics_mod._is_synced_lrc(body)
        return jsonify(
            {
                "ok": True,
                "record": {
                    "syncedLyrics": body if is_synced else "",
                    "plainLyrics": "" if is_synced else body,
                },
                "lyrics_explicit": lyrics_explicit,
                "source": "local",
            }
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
        if not audio_path_allowed_for_lyrics_attach(audio_path):
            return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
        cfg = configparser.ConfigParser()
        cfg.read(_resolve(config_file))
        write_sidecar = as_bool(
            data.get("write_sidecar"),
            cfg.getboolean("DEFAULT", "lyrics_enabled", fallback=False),
        )
        write_metadata = as_bool(
            data.get("write_metadata"),
            cfg.getboolean("DEFAULT", "lyrics_embed_metadata", fallback=False),
        )
        if not write_sidecar and not write_metadata:
            return jsonify({"ok": False, "error": "enable .lrc or embedded lyrics first"}), 400
        try:
            out, lyrics_explicit, tag_applied, metadata_written = (
                lyrics_mod.attach_lrclib_id_to_audio(
                    audio_path,
                    lrclib_id,
                    overwrite=True,
                    timeout_sec=18.0,
                    update_explicit_tag=lyrics_explicit_tag_enabled(),
                    write_sidecar=write_sidecar,
                    write_metadata=write_metadata,
                )
            )
        except Exception as e:
            logging.error("Lyrics attach error: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
        if not out and not metadata_written:
            return jsonify({"ok": False, "error": "no lyrics to write"}), 400
        return jsonify(
            {
                "ok": True,
                "lrc_path": out,
                "metadata_written": metadata_written,
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
        if not audio_path_allowed_for_lyrics_attach(audio_path):
            return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
        rid = lyrics_mod.read_lrclib_id_sidecar(audio_path)
        return jsonify({"ok": True, "attached_lrclib_id": rid})

    @app.route("/api/lyrics/stream-audio", methods=["GET"])
    def api_lyrics_stream_audio():
        """Stream a local track for lyric preview (same path rules as attach)."""
        audio_path = (request.args.get("path") or "").strip()
        if not audio_path:
            return jsonify({"ok": False, "error": "path required"}), 400
        if not audio_path_allowed_for_lyrics_attach(audio_path):
            return jsonify({"ok": False, "error": "invalid or disallowed path"}), 403
        p = Path(audio_path).expanduser().resolve()
        if not p.is_file():
            return jsonify({"ok": False, "error": "not found"}), 404
        try:
            return send_file(p, conditional=True, download_name=p.name)
        except FileNotFoundError:
            return jsonify({"ok": False, "error": "not found"}), 404
