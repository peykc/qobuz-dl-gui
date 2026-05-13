from flask import jsonify, request

from qobuz_dl.services.qobuz_session import as_bool


def register_history_routes(
    app,
    *,
    download_history_audio_path_accepted,
    audio_path_allowed_for_lyrics_attach,
) -> None:
    @app.route("/api/download-history", methods=["GET"])
    def api_download_history():
        from qobuz_dl import db as _qdb

        items = _qdb.list_gui_download_history()
        safe = [
            it
            for it in items
            if download_history_audio_path_accepted(it.get("audio_path") or "")
        ]
        return jsonify({"ok": True, "items": safe})

    @app.route("/api/download-history/upsert", methods=["POST"])
    def api_download_history_upsert():
        from qobuz_dl import db as _qdb

        data = request.get_json(silent=True) or {}
        audio_path = (data.get("audio_path") or "").strip()
        if not audio_path:
            return jsonify({"ok": False, "error": "audio_path required"}), 400
        if not download_history_audio_path_accepted(audio_path):
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
        raw_attach = data.get("attach_search_eligible")
        attach_search_kw = None
        if raw_attach is not None and raw_attach != "":
            attach_search_kw = 1 if as_bool(raw_attach) else 0
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
            lyric_destination=str(data.get("lyric_destination") or ""),
            slot_track_id=str(data.get("slot_track_id") or ""),
            release_album_id=str(data.get("release_album_id") or ""),
            pending_slot_cleanup_id=str(data.get("pending_slot_cleanup_id") or ""),
            attach_search_eligible=attach_search_kw,
        )
        return jsonify({"ok": True})

    @app.route("/api/download-history/lyrics", methods=["POST"])
    def api_download_history_lyrics():
        from qobuz_dl import db as _qdb

        data = request.get_json(silent=True) or {}
        audio_path = (data.get("audio_path") or "").strip()
        if not audio_path:
            return jsonify({"ok": False, "error": "audio_path required"}), 400
        if not audio_path_allowed_for_lyrics_attach(audio_path):
            return jsonify({"ok": False, "error": "invalid or disallowed audio path"}), 400
        lyric_type = (data.get("lyric_type") or "").strip()
        if not lyric_type:
            return jsonify({"ok": False, "error": "lyric_type required"}), 400
        _qdb.update_gui_download_history_lyrics(
            audio_path,
            lyric_type=lyric_type,
            lyric_provider=str(data.get("lyric_provider") or ""),
            lyric_confidence=str(data.get("lyric_confidence") or ""),
            lyric_destination=str(data.get("lyric_destination") or ""),
        )
        return jsonify({"ok": True})

    @app.route("/api/download-history/clear", methods=["POST"])
    def api_download_history_clear():
        from qobuz_dl import db as _qdb

        _qdb.clear_gui_download_history()
        return jsonify({"ok": True})
