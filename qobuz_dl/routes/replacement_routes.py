import configparser
import logging
import os
import threading
from pathlib import Path

from flask import jsonify, request


def _resolve_attach_album_track(client, album_id_post: str, slot_id: str):
    """Return (album_meta, slot_track_dict, dl_album_id) or (None,)*3."""
    try:
        if album_id_post:
            album_meta = client.get_album_meta(album_id_post)
            slot_final = None
            for tr in (album_meta.get("tracks") or {}).get("items") or []:
                if isinstance(tr, dict) and str(tr.get("id")) == str(slot_id):
                    slot_final = tr
                    break
            if slot_final is None:
                slot_final = client.get_track_meta(slot_id)
        else:
            slot_api = client.get_track_meta(slot_id)
            alb_wrap = slot_api.get("album") or {}
            album_id_resolved = str(alb_wrap.get("id") or "").strip()
            if not album_id_resolved:
                return None, None, None
            album_meta = client.get_album_meta(album_id_resolved)
            slot_final = None
            for tr in (album_meta.get("tracks") or {}).get("items") or []:
                if isinstance(tr, dict) and str(tr.get("id")) == str(slot_id):
                    slot_final = tr
                    break
            if slot_final is None:
                slot_final = slot_api

        dl_album_id = str(album_meta.get("id") or album_id_post or "").strip()
        if not dl_album_id:
            return None, None, None
        return album_meta, slot_final, dl_album_id
    except Exception as exc:
        logging.error("_resolve_attach_album_track: %s", exc)
        return None, None, None


def _build_downloader(tmp, dl_album_id, queue_src=""):
    from qobuz_dl.downloader import Download as DLCls

    return DLCls(
        tmp.client,
        dl_album_id,
        tmp.directory,
        int(tmp.quality),
        tmp.embed_art,
        tmp.ignore_singles_eps,
        tmp.quality_fallback,
        tmp.cover_og_quality,
        tmp.no_cover,
        tmp.lyrics_enabled,
        tmp.folder_format,
        tmp.track_format,
        cancel_event=None,
        source_queue_url=queue_src,
        tag_options=tmp.tag_options,
        multiple_disc_prefix=tmp.multiple_disc_prefix,
        multiple_disc_one_dir=tmp.multiple_disc_one_dir,
        multiple_disc_track_format=tmp.multiple_disc_track_format,
        max_workers=tmp.max_workers,
        delay_seconds=0,
        segmented_fallback=tmp.segmented_fallback,
        no_credits=tmp.no_credits,
        tag_title_from_track_format=tmp.tag_title_from_track_format,
        tag_album_from_folder_format=tmp.tag_album_from_folder_format,
        native_lang=bool(tmp.native_lang),
        lyrics_embed_metadata=tmp.lyrics_embed_metadata,
    )


def register_replacement_routes(
    app,
    *,
    get_qobuz,
    config_file,
    build_qobuz_from_config,
    download_roots_for_lyrics_allow,
) -> None:
    @app.route("/api/download_attach_track", methods=["POST"])
    def api_download_attach_track():
        qobuz = get_qobuz()
        if not qobuz or not qobuz.client:
            return jsonify({"ok": False, "error": "Not connected"}), 400

        data = request.json or {}
        slot_id = str(data.get("slot_track_id") or "").strip()
        sub_id = str(data.get("substitute_track_id") or "").strip()
        album_id_post = str(data.get("album_id") or "").strip()
        queue_src = str(data.get("queue_source_url") or "").strip()
        if not slot_id or not sub_id:
            return jsonify(
                {"ok": False, "error": "slot_track_id and substitute_track_id required"}
            ), 400

        def run():
            try:
                cfg = configparser.ConfigParser()
                cfg.read(config_file())
                tmp = build_qobuz_from_config(cfg)
                tmp.client = qobuz.client
                tmp.client.set_language_headers(tmp.native_lang)

                album_meta, slot_final, dl_album_id = _resolve_attach_album_track(
                    tmp.client,
                    album_id_post,
                    slot_id,
                )
                if not album_meta or not slot_final or not dl_album_id:
                    logging.error(
                        "attach: could not resolve album/slot (%s %s)",
                        album_id_post,
                        slot_id,
                    )
                    return

                dloader = _build_downloader(tmp, dl_album_id, queue_src)
                dloader.download_substitute_for_slot(album_meta, slot_final, sub_id)
            except Exception as e:
                logging.error("download_attach_track worker: %s", e, exc_info=True)

        threading.Thread(target=run, daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/api/write_missing_track_placeholder", methods=["POST"])
    def api_write_missing_track_placeholder():
        qobuz = get_qobuz()
        if not qobuz or not qobuz.client:
            return jsonify({"ok": False, "error": "Not connected"}), 400

        data = request.json or {}
        slot_id = str(data.get("slot_track_id") or "").strip()
        album_id_post = str(data.get("album_id") or "").strip()
        queue_src = str(data.get("queue_source_url") or "").strip()
        skip_lyrics = bool(data.get("skip_lyrics"))

        if not slot_id:
            return jsonify({"ok": False, "error": "slot_track_id required"}), 400

        try:
            cfg = configparser.ConfigParser()
            cfg.read(config_file())
            tmp = build_qobuz_from_config(cfg)
            if skip_lyrics:
                tmp.lyrics_enabled = False
                tmp.lyrics_embed_metadata = False
            tmp.client = qobuz.client
            tmp.client.set_language_headers(tmp.native_lang)

            album_meta, slot_final, dl_album_id = _resolve_attach_album_track(
                tmp.client,
                album_id_post,
                slot_id,
            )
            if not album_meta or not slot_final:
                return jsonify(
                    {"ok": False, "error": "Could not resolve album or track metadata."}
                ), 400

            dloader = _build_downloader(tmp, dl_album_id, queue_src)
            ok, detail = dloader.write_missing_track_placeholder(
                album_meta,
                slot_final,
                native_lang=bool(tmp.native_lang),
            )
            if not ok:
                return jsonify({"ok": False, "error": detail}), 400
            basename = os.path.basename(detail)
            return jsonify({"ok": True, "saved_path": detail, "basename": basename})
        except Exception as e:
            logging.error(
                "write_missing_track_placeholder failed: %s",
                e,
                exc_info=True,
            )
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/api/delete_track_resolution_file", methods=["POST"])
    def api_delete_track_resolution_file():
        data = request.json or {}
        file_path = str(data.get("file_path") or "").strip()
        if not file_path:
            return jsonify({"ok": False, "error": "file_path required"}), 400

        try:
            p = Path(file_path).expanduser().resolve()
        except (OSError, ValueError) as e:
            return jsonify({"ok": False, "error": f"Invalid path: {e}"}), 400

        allowed_exts = {
            ".missing.txt",
            ".flac",
            ".mp3",
            ".m4a",
            ".alac",
            ".wav",
            ".wma",
            ".ogg",
            ".aac",
        }
        ext_lower = "".join(p.suffixes).lower()
        if not ext_lower.endswith(".missing.txt"):
            ext_lower = p.suffix.lower()
        if ext_lower not in allowed_exts:
            return jsonify(
                {
                    "ok": False,
                    "error": f"File extension not permitted for deletion: {ext_lower}",
                }
            ), 400

        in_root = False
        for root in download_roots_for_lyrics_allow():
            try:
                p.relative_to(root)
                in_root = True
                break
            except ValueError:
                continue
        if not in_root:
            return jsonify({"ok": False, "error": "File is outside the download root"}), 403

        try:
            if p.exists():
                p.unlink()

            stem_path = p.with_suffix("")
            if ext_lower == ".missing.txt":
                stem_path = p.parent / p.name[:-12]

            lrc_path = stem_path.with_suffix(".lrc")
            if lrc_path.exists():
                lrc_path.unlink()

            lrclib_path = stem_path.with_suffix(".lrclib_id")
            if lrclib_path.exists():
                lrclib_path.unlink()

            return jsonify({"ok": True})
        except Exception as e:
            logging.error("delete_track_resolution_file: %s", e, exc_info=True)
            return jsonify({"ok": False, "error": str(e)}), 500
