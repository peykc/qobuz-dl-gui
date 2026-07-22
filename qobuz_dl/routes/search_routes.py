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

    @app.route("/api/artist_releases")
    def api_artist_releases():
        """Return an artist's albums for browse-from-search.

        Sort follows the ``sort`` query param: ``relevance`` (default) or ``newest``.
        """
        qobuz = get_qobuz()
        if not qobuz or not qobuz.client:
            return jsonify({"ok": False, "error": "Not connected"}), 400

        artist_id = (request.args.get("id") or "").strip()
        if not artist_id:
            return jsonify({"ok": False, "error": "Missing artist id"}), 400
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        limit = max(1, min(limit, 100))
        sort_mode = (request.args.get("sort") or "relevance").strip().lower()
        if sort_mode not in ("newest", "relevance"):
            sort_mode = "relevance"
        # Qobuz getReleasesList: release_date for newest; popularity for catalog/relevance.
        api_sort = "release_date" if sort_mode == "newest" else "popularity"
        api_order = "desc"

        from qobuz_dl.utils import (
            format_sampling_rate_specs,
            sampling_rate_khz_for_chip,
        )

        def _as_str(val, default="") -> str:
            if val is None:
                return default
            if isinstance(val, str):
                return val.strip()
            if isinstance(val, (int, float, bool)):
                return str(val)
            if isinstance(val, dict):
                for key in ("name", "title", "label", "value", "text"):
                    inner = val.get(key)
                    if isinstance(inner, str) and inner.strip():
                        return inner.strip()
                return default
            try:
                return str(val).strip()
            except Exception:
                return default

        def _cover_url(album: dict) -> str:
            image = album.get("image")
            if isinstance(image, dict):
                return _as_str(
                    image.get("large") or image.get("small") or image.get("thumbnail")
                )
            if isinstance(image, str):
                return image.strip()
            return ""

        def _album_from_release_item(it: dict):
            if not isinstance(it, dict):
                return None
            for key in ("album", "release"):
                nested = it.get(key)
                if isinstance(nested, dict) and nested.get("id") is not None:
                    return nested
            if it.get("id") is not None and (
                it.get("title") is not None or it.get("tracks_count") is not None
            ):
                return it
            return None

        def _album_row(album: dict, artist_name: str = "") -> dict:
            aid = _as_str(album.get("id"))
            title = _as_str(album.get("title"))
            artist_field = album.get("artist")
            if isinstance(artist_field, dict):
                artist = _as_str(artist_field.get("name"), artist_name)
            else:
                artist = _as_str(artist_field, artist_name)
            release_date_val = album.get("release_date_original") or album.get(
                "release_date_stream"
            )
            if not isinstance(release_date_val, str):
                release_date_val = _as_str(release_date_val)
            release_year = ""
            if (
                release_date_val
                and len(release_date_val) >= 4
                and release_date_val[:4].isdigit()
            ):
                release_year = release_date_val[:4]
            hires = bool(album.get("hires_streamable"))
            quality = "HI-RES" if hires else "LOSSLESS"
            cover = _cover_url(album)
            return {
                "text": f"{artist} - {title}" if artist else title,
                "display_title": title,
                "display_subtitle": artist,
                "release_year": release_year,
                "release_date": release_date_val,
                "url": f"https://play.qobuz.com/album/{aid}" if aid else "",
                "cover": cover,
                "type": "album",
                "badge": "",
                "quality": quality,
                "explicit": bool(
                    album.get("parental_warning")
                    or album.get("parental_advisory")
                    or album.get("explicit")
                ),
                "tracks": album.get("tracks_count"),
                "bit_depth": album.get("maximum_bit_depth"),
                "sample_rate": sampling_rate_khz_for_chip(
                    album.get("maximum_sampling_rate")
                ),
                "quality_label": (
                    f"{album.get('maximum_bit_depth', '?')}bit / "
                    f"{format_sampling_rate_specs(album.get('maximum_sampling_rate'))}"
                ),
            }

        try:
            artist_name = ""
            albums = []
            try:
                raw = qobuz.client.get_artist_releases(
                    artist_id,
                    limit=limit,
                    offset=0,
                    sort=api_sort,
                    order=api_order,
                )
                items = (raw or {}).get("items") or []
                for it in items:
                    album = _album_from_release_item(it)
                    if album is not None:
                        albums.append(album)
            except Exception:
                logging.debug(
                    "getReleasesList failed; falling back to artist/get",
                    exc_info=True,
                )
                albums = []

            if not albums:
                meta = qobuz.client.api_call(
                    "artist/get", id=artist_id, offset=0
                )
                artist_name = _as_str((meta or {}).get("name"))
                album_items = ((meta or {}).get("albums") or {}).get("items") or []
                albums = [a for a in album_items if isinstance(a, dict) and a.get("id")]
                if sort_mode == "newest":
                    albums.sort(
                        key=lambda a: _as_str(
                            a.get("release_date_original")
                            or a.get("release_date_stream")
                        ),
                        reverse=True,
                    )
                albums = albums[:limit]
            else:
                try:
                    meta = qobuz.client.api_call(
                        "artist/get", id=artist_id, offset=0
                    )
                    artist_name = _as_str((meta or {}).get("name"), artist_name)
                except Exception:
                    pass

            results = [
                _album_row(a, artist_name)
                for a in albums
                if isinstance(a, dict) and a.get("id") is not None
            ]
            return jsonify(
                {
                    "ok": True,
                    "artist_id": artist_id,
                    "artist_name": artist_name,
                    "results": results,
                }
            )
        except Exception as e:
            logging.error("artist_releases failed: %s", e, exc_info=True)
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/check_discography", methods=["POST"])
    def api_check_discography():
        qobuz = get_qobuz()
        if not qobuz or not qobuz.client:
            return jsonify({"ok": False, "error": "Not connected."}), 400

        data = request.json or {}
        url = data.get("url", "")
        try:
            from qobuz_dl.core import get_url_info
            from qobuz_dl.utils import smart_discography_filter

            url_type, item_id = get_url_info(url)
            if url_type != "artist":
                return jsonify({"ok": False, "error": "URL is not an artist"}), 400

            content = list(qobuz.client.get_artist_meta(item_id))
            all_albums_raw = []
            raw_albums = 0
            raw_tracks = 0
            for item in content:
                albums_chunk = item.get("albums", {}).get("items", [])
                all_albums_raw.extend(albums_chunk)
                raw_albums += len(albums_chunk)
                for album in albums_chunk:
                    raw_tracks += album.get("tracks_count", 0)

            if all_albums_raw:
                print(
                    f"ALBUM DUMP [{all_albums_raw[0].get('title')}]: "
                    f"{all_albums_raw[0]}",
                    flush=True,
                )

            def calc_stats(album_list):
                return len(album_list), sum(
                    a.get("tracks_count", 0) for a in album_list
                )

            sd_items = smart_discography_filter(
                content,
                save_space=True,
                skip_extras=True,
            )
            sd_albums, sd_tracks = calc_stats(sd_items)

            ao_items = [
                a
                for a in all_albums_raw
                if a.get("release_type") == "album"
                and a.get("artist", {}).get("name") != "Various Artists"
            ]
            ao_albums, ao_tracks = calc_stats(ao_items)

            both_items = [
                a
                for a in sd_items
                if a.get("release_type") == "album"
                and a.get("artist", {}).get("name") != "Various Artists"
            ]
            both_albums, both_tracks = calc_stats(both_items)

            return jsonify(
                {
                    "ok": True,
                    "result": {
                        "raw_albums": raw_albums,
                        "raw_tracks": raw_tracks,
                        "sd_filtered_albums": sd_albums,
                        "sd_filtered_tracks": sd_tracks,
                        "ao_filtered_albums": ao_albums,
                        "ao_filtered_tracks": ao_tracks,
                        "both_filtered_albums": both_albums,
                        "both_filtered_tracks": both_tracks,
                        "diff_sd": raw_albums - sd_albums,
                        "diff_ao": raw_albums - ao_albums,
                        "diff_both": raw_albums - both_albums,
                    },
                }
            )
        except Exception as e:
            import traceback

            traceback.print_exc()
            logging.error("check_discography failed: %s", e)
            return jsonify({"ok": False, "error": str(e)}), 500
