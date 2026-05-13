import logging

from flask import jsonify, request


def _attach_explicit_flag(track_dict):
    if not track_dict or not isinstance(track_dict, dict):
        return False
    return bool(
        track_dict.get("parental_warning")
        or track_dict.get("explicit")
        or track_dict.get("parental_advisory")
    )


def _attach_track_quality_fields(track_dict):
    """Best-effort tier + specs from track/search items."""
    from qobuz_dl.utils import normalize_sampling_rate_hz

    if not isinstance(track_dict, dict):
        return ("LOSSLESS", None, None)
    alb = track_dict.get("album") if isinstance(track_dict.get("album"), dict) else {}
    bd_t = track_dict.get("maximum_bit_depth")
    sr_t = track_dict.get("maximum_sampling_rate")
    bd_a = alb.get("maximum_bit_depth")
    sr_a = alb.get("maximum_sampling_rate")
    try:
        bit_depth = int(bd_t if bd_t is not None else bd_a or 0) or None
    except (TypeError, ValueError):
        bit_depth = None
    hz_t = normalize_sampling_rate_hz(sr_t)
    hz_a = normalize_sampling_rate_hz(sr_a)
    hz = hz_t if hz_t is not None else hz_a
    sample_rate = int(round(hz)) if hz is not None else None

    hires = bool(track_dict.get("hires_streamable") or alb.get("hires_streamable"))
    mime = str(track_dict.get("mime_type") or "").lower()
    aq = track_dict.get("audio_quality")

    tier = "LOSSLESS"
    if hires or (bit_depth and bit_depth > 16) or (sample_rate and sample_rate > 48000):
        tier = "HI-RES"
    elif "mpeg" in mime or aq == 5 or str(aq).strip().lower() == "mp3":
        tier = "MP3"

    return (tier, bit_depth, sample_rate)


def register_search_routes(app, *, get_qobuz) -> None:
    @app.route("/api/resolve", methods=["POST"])
    def api_resolve():
        qobuz = get_qobuz()
        if not qobuz:
            return jsonify({"ok": False, "error": "Not connected"}), 400

        data = request.json or {}
        url = (data.get("url") or "").strip()
        if not url:
            return jsonify({"ok": False, "error": "No URL"}), 400

        try:
            from qobuz_dl.utils import (
                format_sampling_rate_specs,
                get_url_info,
                sampling_rate_khz_for_chip,
            )

            url_type, item_id = get_url_info(url)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid Qobuz URL"}), 400

        try:
            if url_type == "album":
                meta = qobuz.client.get_album_meta(item_id)
                result = {
                    "type": "album",
                    "title": meta.get("title", ""),
                    "artist": meta.get("artist", {}).get("name", ""),
                    "cover": meta.get("image", {}).get("large", ""),
                    "tracks": meta.get("tracks_count", 0),
                    "year": (meta.get("release_date_original") or "")[:4],
                    "release_date": meta.get("release_date_original", ""),
                    "bit_depth": meta.get("maximum_bit_depth"),
                    "sample_rate": sampling_rate_khz_for_chip(
                        meta.get("maximum_sampling_rate")
                    ),
                    "quality": (
                        f"{meta.get('maximum_bit_depth', '?')}bit / "
                        f"{format_sampling_rate_specs(meta.get('maximum_sampling_rate'))}"
                    ),
                    "explicit": bool(
                        meta.get("parental_warning") or meta.get("explicit")
                    ),
                    "url": url,
                    "release_album_id": str(item_id).strip(),
                }
            elif url_type == "track":
                meta = qobuz.client.get_track_meta(item_id)
                album = meta.get("album", {})
                result = {
                    "type": "track",
                    "title": meta.get("title", ""),
                    "artist": meta.get("performer", {}).get("name", ""),
                    "cover": album.get("image", {}).get("large", ""),
                    "album": album.get("title", ""),
                    "year": (album.get("release_date_original") or "")[:4],
                    "bit_depth": album.get("maximum_bit_depth"),
                    "sample_rate": sampling_rate_khz_for_chip(
                        album.get("maximum_sampling_rate")
                    ),
                    "quality": (
                        f"{album.get('maximum_bit_depth', '?')}bit / "
                        f"{format_sampling_rate_specs(album.get('maximum_sampling_rate'))}"
                    ),
                    "url": url,
                }
            elif url_type == "artist":
                meta = qobuz.client.api_call("artist/get", id=item_id, offset=0)
                if not meta:
                    return jsonify(
                        {"ok": False, "error": "Artist metadata not found"}
                    ), 404
                image = meta.get("image") or {}
                cover = (
                    image.get("large")
                    or meta.get("picture_large")
                    or meta.get("picture")
                    or image.get("medium")
                    or ""
                )
                result = {
                    "type": "artist",
                    "title": meta.get("name", ""),
                    "artist": meta.get("name", ""),
                    "cover": cover,
                    "albums": meta.get("albums_count", 0),
                    "url": url,
                }
            elif url_type == "playlist":
                meta = list(qobuz.client.get_plist_meta(item_id))[0]
                result = {
                    "type": "playlist",
                    "title": meta.get("name", ""),
                    "artist": meta.get("owner", {}).get("name", ""),
                    "cover": meta.get("images300", [None])[0]
                    if meta.get("images300")
                    else "",
                    "tracks": meta.get("tracks_count", 0),
                    "url": url,
                }
            else:
                result = {
                    "type": url_type,
                    "title": item_id,
                    "artist": "",
                    "cover": "",
                    "url": url,
                }

            return jsonify({"ok": True, "result": result})
        except Exception as e:
            logging.error("Resolve failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/search_tracks_attach", methods=["POST"])
    def api_search_tracks_attach():
        qobuz = get_qobuz()
        if not qobuz or not qobuz.client:
            return jsonify({"ok": False, "error": "Not connected"}), 400

        data = request.json or {}
        query = (data.get("query") or "").strip()
        if len(query) < 2:
            return jsonify({"ok": False, "error": "Query too short"}), 400

        anchor_explicit = data.get("anchor_explicit")
        if anchor_explicit is not None:
            anchor_explicit = bool(anchor_explicit)

        try:
            raw = qobuz.client.search_tracks(query, limit=48, offset=0)
            items = (raw.get("tracks") or {}).get("items") or []
            out = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                exp = _attach_explicit_flag(it)
                if anchor_explicit is True and not exp:
                    continue
                if anchor_explicit is False and exp:
                    continue
                tid = str(it.get("id") or "").strip()
                if not tid:
                    continue
                alb = it.get("album") or {}
                try:
                    dur = int(it.get("duration") or 0)
                except (TypeError, ValueError):
                    dur = 0
                tier, q_bd, q_sr = _attach_track_quality_fields(it)
                out.append(
                    {
                        "id": tid,
                        "title": it.get("title") or "",
                        "artist": (it.get("performer") or {}).get("name") or "",
                        "album_title": alb.get("title") or "",
                        "explicit": exp,
                        "duration_sec": dur,
                        "quality_tier": tier,
                        "maximum_bit_depth": q_bd,
                        "maximum_sampling_rate": q_sr,
                    }
                )
            return jsonify({"ok": True, "tracks": out})
        except Exception as e:
            logging.error("search_tracks_attach failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/search")
    def api_search():
        qobuz = get_qobuz()
        if not qobuz:
            return jsonify({"ok": False, "error": "Not connected"}), 400

        query = request.args.get("q", "").strip()
        item_type = request.args.get("type", "album")
        try:
            limit = int(request.args.get("limit", 10))
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 50))

        if len(query) < 3:
            return jsonify({"ok": False, "error": "Query too short (min 3 chars)"}), 400

        try:
            results = qobuz.search_by_type(query, item_type, limit)
            return jsonify({"ok": True, "results": results or []})
        except Exception as e:
            logging.error("Search error: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
