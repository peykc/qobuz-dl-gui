import logging
import os
import re
import concurrent.futures
import subprocess
import threading
import time
from html import unescape
from typing import Optional, Tuple

import requests
import urllib3
from pathvalidate import sanitize_filename, sanitize_filepath
from tqdm import tqdm

import qobuz_dl.metadata as metadata
from qobuz_dl import lyrics
from qobuz_dl.color import CYAN, GREEN, OFF, RED, YELLOW
from qobuz_dl.download.placeholders import (
    missing_placeholder_line as _missing_ph_line,
    missing_placeholder_quality_line as _missing_ph_quality_line,
    qobuz_purchase_store_url as _qobuz_purchase_store_url,
    qobuz_store_slug_from_cms_or_default as _qobuz_store_slug_from_cms_or_default,
    qobuz_www_album_product_url as _qobuz_www_album_product_url,
    qobuz_www_track_product_url as _qobuz_www_track_product_url,
)
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.utils import get_album_artist
from qobuz_dl.version import __version__ as QOBUZ_DL_GUI_VERSION

QL_DOWNGRADE = "FormatRestrictedByFormatAvailability"


# used in case of error
DEFAULT_FORMATS = {
    "MP3": [
        "{artist}/{album} ({year})",
        "{tracknumber} - {tracktitle}",
    ],
    "Unknown": [
        "{artist}/{album}",
        "{tracknumber} - {tracktitle}",
    ],
}

DEFAULT_FOLDER = "{artist}/{album}"
DEFAULT_TRACK = "{tracknumber} - {tracktitle}"
DEFAULT_MULTIPLE_DISC_TRACK = "{disc_number_unpadded}{track_number} - {tracktitle}"

logger = logging.getLogger(__name__)


def _strip_html_to_text(raw: str) -> str:
    if not raw:
        return ""
    t = re.sub(r"<[^>]+>", " ", str(raw))
    t = unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _genre_line_from_album_meta(meta: dict) -> str:
    g = meta.get("genre")
    if isinstance(g, dict):
        name = (g.get("name") or "").strip()
        if name:
            return name
    gl = meta.get("genres_list")
    if gl and isinstance(gl, list):
        try:
            from qobuz_dl.metadata import _format_genres

            return _format_genres(gl)
        except Exception:
            return ", ".join(str(x) for x in gl if x)
    return ""


def _write_digital_booklet(meta: dict, dirn: str) -> None:
    """Write Digital Booklet.txt (editorial, credits context, tracklist) next to audio files."""
    path = os.path.join(dirn, "Digital Booklet.txt")
    if os.path.isfile(path):
        return

    lines = []
    title = _get_title(meta)
    artist = _safe_get(meta, "artist", "name") or ""
    lines.append(title)
    lines.append("=" * min(max(len(title), 8), 72))
    lines.append("")
    if artist:
        lines.append(f"Artist: {artist}")
    rd = meta.get("release_date_original") or meta.get("release_date") or ""
    if rd:
        lines.append(f"Release date: {rd}")
    label = meta.get("label")
    if isinstance(label, dict):
        label = label.get("name") or ""
    if label:
        lines.append(f"Label: {label}")
    upc = meta.get("upc") or meta.get("barcode")
    if upc:
        lines.append(f"UPC: {upc}")
    genre = _genre_line_from_album_meta(meta)
    if genre:
        lines.append(f"Genre: {genre}")
    cl = meta.get("catchline") or meta.get("product_line")
    if cl:
        lines.append("")
        lines.append(_strip_html_to_text(str(cl)))
    desc = meta.get("description")
    if desc:
        lines.append("")
        lines.append("--- Description ---")
        lines.append(_strip_html_to_text(str(desc)))
    articles = meta.get("articles")
    if isinstance(articles, list):
        for art in articles:
            if not isinstance(art, dict):
                continue
            at = (art.get("title") or "").strip()
            ac = art.get("content") or art.get("text") or ""
            body = _strip_html_to_text(str(ac))
            if not at and not body:
                continue
            lines.append("")
            lines.append(f"--- {at} ---" if at else "--- Editorial ---")
            if body:
                lines.append(body)
    cr = meta.get("copyright")
    if cr:
        lines.append("")
        lines.append("--- Copyright ---")
        lines.append(_strip_html_to_text(str(cr)))

    tracks = list((meta.get("tracks") or {}).get("items") or [])
    if tracks:
        lines.append("")
        lines.append("--- Tracklist ---")
        for t in tracks:
            tn = t.get("track_number", 0)
            try:
                tn_s = f"{int(tn):02d}"
            except (TypeError, ValueError):
                tn_s = str(tn)
            tt = _get_title(t) if isinstance(t, dict) else ""
            lines.append(f"{tn_s}. {tt}")

    body = "\n".join(lines).strip()
    if len(body) < 12:
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    logger.info(f"{CYAN}[+] Wrote Digital Booklet.txt{OFF}")


def _safe_marker_value(value) -> str:
    return str(value or "").replace("|", "/").strip()


def _qobuz_track_open_url(track_id) -> str:
    tid = str(track_id or "").strip()
    return f"https://play.qobuz.com/track/{tid}" if tid else ""


def _qobuz_album_open_url(album_id) -> str:
    aid = str(album_id or "").strip()
    return f"https://play.qobuz.com/album/{aid}" if aid else ""


def _album_cover_thumb(meta: dict) -> str:
    """Best small cover URL for UI (album dict or track dict with nested album)."""
    if not meta or not isinstance(meta, dict):
        return ""
    img = meta.get("image")
    if not img and isinstance(meta.get("album"), dict):
        img = meta["album"].get("image")
    if not img or not isinstance(img, dict):
        return ""
    return (
        str(img.get("thumbnail") or img.get("small") or img.get("large") or "").strip()
    )


def _album_cover_large_fetch_url(album_meta: dict) -> str:
    """HTTPS URL to fetch album artwork for ``cover.jpg``; empty if API omitted art."""
    if not album_meta or not isinstance(album_meta, dict):
        return ""
    img = album_meta.get("image")
    if not isinstance(img, dict):
        return ""
    u = img.get("large") or img.get("medium") or img.get("small") or img.get("thumbnail")
    return str(u).strip() if u else ""


def _lyric_ctx_for_ui(track_meta: dict, album_meta: Optional[dict]) -> Tuple[str, str, int, bool]:
    """Artist, album title, duration (sec), and Qobuz explicit flag for the GUI."""
    album_meta = album_meta if isinstance(album_meta, dict) else None
    if not album_meta and isinstance((track_meta or {}).get("album"), dict):
        album_meta = track_meta["album"]
    album_meta = album_meta or {}
    artist = (
        _safe_get(track_meta, "performer", "name")
        or get_album_artist(album_meta)
        or _safe_get(album_meta, "artist", "name", default="")
        or ""
    )
    album_title = _get_title(album_meta) if album_meta else ""
    try:
        dur = int((track_meta or {}).get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0
    explicit = lyrics.qobuz_track_is_explicit(track_meta or {})
    return str(artist).strip(), str(album_title).strip(), dur, explicit


def _emit_track_start(
    track_num,
    track_title: str,
    cover_url: str = "",
    *,
    artist: str = "",
    album: str = "",
    duration_sec: int = 0,
    track_explicit: bool = False,
) -> None:
    num = (
        f"{int(track_num):02d}"
        if str(track_num).isdigit()
        else _safe_marker_value(track_num)
    )
    title_s = _safe_marker_value(track_title)
    cov = _safe_marker_value(cover_url)
    a = _safe_marker_value(artist)
    al = _safe_marker_value(album)
    d = int(duration_sec or 0)
    e = 1 if track_explicit else 0
    logger.info(f"[TRACK_START] {num}|{title_s}|{cov}|{a}|{al}|{d}|{e}")


def _album_title_for_track_marker(
    is_track: bool, track_metadata: dict, album_or_track_metadata
) -> str:
    """Album title for GUI / history disambiguation (same track title on different releases)."""
    try:
        if not is_track and isinstance(album_or_track_metadata, dict):
            return _get_title(album_or_track_metadata)
        if is_track:
            am = (track_metadata or {}).get("album")
            if isinstance(am, dict):
                return _get_title(am)
    except (KeyError, TypeError, AttributeError):
        pass
    return ""


def _track_explicit_flag(track_dict: Optional[dict]) -> bool:
    if not track_dict or not isinstance(track_dict, dict):
        return False
    return bool(
        track_dict.get("parental_warning")
        or track_dict.get("explicit")
        or track_dict.get("parental_advisory")
    )


def _emit_track_marker(
    marker: str,
    track_num,
    title: str,
    status: str,
    detail: str = "",
    queue_url: str = "",
    local_path: str = "",
    lyric_album: str = "",
    slot_track_id: str = "",
    album_release_id: str = "",
    *,
    substitute_attach: bool = False,
):
    num = f"{int(track_num):02d}" if str(track_num).isdigit() else _safe_marker_value(track_num)
    base = f"[{marker}] {num}|{_safe_marker_value(title)}|{_safe_marker_value(status)}|{_safe_marker_value(detail)}"
    qu = _safe_marker_value(queue_url) if (queue_url or "").strip() else ""
    lp = _safe_marker_value(local_path) if (local_path or "").strip() else ""
    alb = _safe_marker_value(lyric_album) if (lyric_album or "").strip() else ""
    sid = _safe_marker_value(slot_track_id) if str(slot_track_id or "").strip() else ""
    aid = (
        _safe_marker_value(album_release_id)
        if str(album_release_id or "").strip()
        else ""
    )
    tail_needed = bool(qu or lp or alb or sid or aid or substitute_attach)
    sub_flag = "1" if substitute_attach else "-"
    if tail_needed:
        qz = qu if qu else "-"
        logger.info(f"{base}|{qz}|{lp}|{alb}|{sid}|{aid}|{sub_flag}")
    else:
        logger.info(base)


def _emit_lyrics_marker(
    track_num,
    title: str,
    lyric_type: str,
    provider: str,
    confidence=None,
    audio_path: str = "",
    lyric_destination: str = "",
):
    num = f"{int(track_num):02d}" if str(track_num).isdigit() else _safe_marker_value(track_num)
    conf = (
        ""
        if confidence is None
        else str(max(0, min(100, int(round(float(confidence))))))
    )
    ap = _safe_marker_value(audio_path) if (audio_path or "").strip() else ""
    line = (
        f"[TRACK_LYRICS] {num}|{_safe_marker_value(title)}|"
        f"{_safe_marker_value(lyric_type)}|{_safe_marker_value(provider)}|{_safe_marker_value(conf)}"
    )
    if ap:
        line += f"|{ap}"
        dest = _safe_marker_value(lyric_destination) if (lyric_destination or "").strip() else ""
        if dest:
            line += f"|{dest}"
    logger.info(line)
    lt = str(lyric_type or "").strip().lower()
    ap_raw = str(audio_path or "").strip()
    if lt and lt != "loading" and ap_raw:
        from qobuz_dl import db as _db

        conf_str = (
            ""
            if confidence is None
            else str(max(0, min(100, int(round(float(confidence))))))
        )
        _db.update_gui_download_history_lyrics(
            ap_raw,
            lyric_type=lt,
            lyric_provider=str(provider or ""),
            lyric_confidence=conf_str,
            lyric_destination=str(lyric_destination or ""),
        )


def _make_throttled_download_progress(
    track_metadata: dict,
    tmp_count,
    track_title: str,
    *,
    is_track: bool = True,
    album_or_track_metadata=None,
):
    """Emit SSE track_download_progress while bytes stream in (throttled).

    lyric_album must match track_start / track_result (see _album_title_for_track_marker).
    Album downloads use is_track=False and pass the release album dict — progress must not
    rely only on track_metadata[\"album\"] or the GUI row key will not match.
    """
    import qobuz_dl.core as _core

    track_num = track_metadata.get("track_number", tmp_count)
    title = track_title or _get_title(track_metadata)
    state = {"last_t": 0.0, "last_pct": -1}

    def cb(received: int, total: int) -> None:
        emit = getattr(_core, "ui_emitter", None)
        if not emit or total <= 0:
            return
        received = int(max(0, min(received, total)))
        now = time.monotonic()
        pct = int(100 * received / total)
        force_final = received >= total
        if (
            not force_final
            and (now - state["last_t"] < 0.18)
            and (pct == state["last_pct"])
        ):
            return
        state["last_t"] = now
        state["last_pct"] = pct
        num = (
            f"{int(track_num):02d}"
            if str(track_num).isdigit()
            else _safe_marker_value(track_num)
        )
        alb = _album_title_for_track_marker(
            is_track,
            track_metadata or {},
            album_or_track_metadata,
        )
        emit(
            {
                "type": "track_download_progress",
                "track_no": num,
                "title": _safe_marker_value(title),
                "lyric_album": _safe_marker_value(alb),
                "received": received,
                "total": total,
            }
        )

    return cb


class Download:
    def __init__(
        self,
        client,
        item_id: str,
        path: str,
        quality: int,
        embed_art: bool = False,
        albums_only: bool = False,
        downgrade_quality: bool = False,
        cover_og_quality: bool = False,
        no_cover: bool = False,
        lyrics_enabled: bool = False,
        folder_format=None,
        track_format=None,
        cancel_event=None,
        abort_stream_event=None,
        source_queue_url: str = "",
        *,
        tag_options=None,
        multiple_disc_prefix: str = "Disc",
        multiple_disc_one_dir: bool = False,
        multiple_disc_track_format: str = DEFAULT_MULTIPLE_DISC_TRACK,
        max_workers: int = 1,
        delay_seconds: int = 0,
        segmented_fallback: bool = True,
        no_credits: bool = False,
        tag_title_from_track_format: bool = True,
        tag_album_from_folder_format: bool = True,
        native_lang: bool = False,
        lyrics_embed_metadata: bool = False,
    ):
        self.client = client
        self.item_id = item_id
        self.path = path
        self.quality = quality
        self.albums_only = albums_only
        self.embed_art = embed_art
        self.downgrade_quality = downgrade_quality
        self.cover_og_quality = cover_og_quality
        self.no_cover = no_cover
        self.lyrics_enabled = bool(lyrics_enabled)
        self.lyrics_embed_metadata = bool(lyrics_embed_metadata)
        self.lyrics_any_enabled = self.lyrics_enabled or self.lyrics_embed_metadata
        self.folder_format = folder_format or DEFAULT_FOLDER
        self.track_format = track_format or DEFAULT_TRACK
        self.cancel_event = cancel_event
        self.abort_stream_event = abort_stream_event
        self.source_queue_url = (source_queue_url or "").strip()
        self.tag_options = tag_options or {}
        self.multiple_disc_prefix = (multiple_disc_prefix or "Disc").strip() or "Disc"
        self.multiple_disc_one_dir = bool(multiple_disc_one_dir)
        self.multiple_disc_track_format = (
            multiple_disc_track_format or DEFAULT_MULTIPLE_DISC_TRACK
        )
        self.max_workers = max(1, int(max_workers or 1))
        self.delay_seconds = max(0, int(delay_seconds or 0))
        self.segmented_fallback = bool(segmented_fallback)
        self.no_credits = bool(no_credits)
        self.tag_title_from_track_format = bool(tag_title_from_track_format)
        self.tag_album_from_folder_format = bool(tag_album_from_folder_format)
        self.native_lang = bool(native_lang)

    def _purchase_open_url(self, track_meta: dict, album_meta: Optional[dict] = None) -> str:
        return _qobuz_purchase_store_url(
            track_meta,
            album_meta,
            native_lang=self.native_lang,
        )

    def _stream_abort_evt(self):
        """Event that aborts chunked HTTP downloads (tracks, cover, segmented fallback).

        GUI sets ``abort_stream_event`` separately from cooperative ``cancel_event`` so Pause
        can finish bytes for in-flight streams while still using ``cancel_event`` to skip
        tracks that have not started yet (thread-pool jobs). CLI leaves ``abort_stream_event``
        unset and falls back to ``cancel_event`` for both behaviours.
        """
        if self.abort_stream_event is not None:
            return self.abort_stream_event
        return self.cancel_event

    def _stream_abort_is_set(self) -> bool:
        e = self._stream_abort_evt()
        return e is not None and e.is_set()

    def _cooperative_stop_is_set(self) -> bool:
        """True when pause/cancel asked to stop scheduling new work (without aborting active bytes)."""
        return self.cancel_event is not None and self.cancel_event.is_set()

    def download_id_by_type(self, track=True):
        if not track:
            self.download_release()
        else:
            self.download_track()

    def download_release(self):
        count = 1
        meta = self.client.get_album_meta(self.item_id)

        if self._cooperative_stop_is_set():
            return

        if not meta.get("streamable"):
            import qobuz_dl.core as _qcore

            note = getattr(_qcore, "note_streaming_blocked_release", None)
            if callable(note):
                note()
            raise NonStreamable("This release is not streamable")

        if self.albums_only and (
            meta.get("release_type") != "album"
            or meta.get("artist").get("name") == "Various Artists"
        ):
            logger.info(f"{OFF}Ignoring Single/EP/VA: {meta.get('title', 'n/a')}")
            return

        album_title = _get_title(meta)

        format_info = self._get_format(meta)
        file_format, quality_met, bit_depth, sampling_rate = format_info

        if not self.downgrade_quality and not quality_met:
            logger.info(
                f"{OFF}Skipping {album_title} as it doesn't meet quality requirement"
            )
            return

        logger.info(
            f"\n{YELLOW}Downloading: {album_title}\nQuality: {file_format}"
            f" ({bit_depth}/{sampling_rate})\n"
        )
        album_attr = self._get_album_attr(
            meta, album_title, file_format, bit_depth, sampling_rate
        )
        folder_format, track_format = _clean_format_str(
            self.folder_format, self.track_format, file_format
        )
        sanitized_title = sanitize_filepath(folder_format.format(**album_attr))
        dirn = os.path.join(self.path, sanitized_title)
        
        if self._cooperative_stop_is_set():
            return

        os.makedirs(dirn, exist_ok=True)

        if self.no_cover:
            logger.info(f"{OFF}Skipping cover")
        else:
            cover_url = _album_cover_large_fetch_url(meta)
            if cover_url:
                _get_extra(
                    cover_url,
                    dirn,
                    og_quality=self.cover_og_quality,
                    cancel_event=self._stream_abort_evt(),
                )

        if "goodies" in meta:
            try:
                _get_extra(
                    meta["goodies"][0]["url"],
                    dirn,
                    "booklet.pdf",
                    cancel_event=self._stream_abort_evt(),
                )
            except:  # noqa
                pass
        if not self.no_credits:
            try:
                _write_digital_booklet(meta, dirn)
            except Exception as exc:
                logger.debug("Digital Booklet.txt: %s", exc)
        tracks = list((meta.get("tracks") or {}).get("items") or [])
        media_numbers = [track.get("media_number", 1) for track in tracks]
        is_multiple = len(set(media_numbers)) > 1
        failed_tracks = []

        active_workers = 1 if self.delay_seconds > 0 else self.max_workers
        if active_workers > 1:
            logger.info(
                "%sParallel track download enabled (%s workers)%s",
                YELLOW,
                active_workers,
                OFF,
            )

        album_lyrics_ex: Optional[concurrent.futures.ThreadPoolExecutor] = None
        album_lyrics_sidecar_ex: Optional[concurrent.futures.ThreadPoolExecutor] = None
        album_lyrics_pending = []
        album_lyrics_lock = threading.Lock()
        if self.lyrics_any_enabled and tracks:
            album_lyrics_ex = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, active_workers)
            )
            album_lyrics_sidecar_ex = concurrent.futures.ThreadPoolExecutor(
                max_workers=max(1, active_workers)
            )

        try:
            if active_workers > 1 and len(tracks) > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=active_workers) as ex:
                    futures = []
                    for i in tracks:
                        tmp_count = count
                        count += 1
                        futures.append(
                            ex.submit(
                                self._download_release_track,
                                dirn,
                                tmp_count,
                                i,
                                meta,
                                is_multiple,
                                True,
                                lyrics_executor=album_lyrics_ex,
                                lyrics_sidecar_executor=album_lyrics_sidecar_ex,
                                lyrics_pending=album_lyrics_pending,
                                lyrics_pending_lock=album_lyrics_lock,
                            )
                        )
                    for fut in concurrent.futures.as_completed(futures):
                        failed = fut.result()
                        if failed:
                            failed_tracks.append(failed)
            else:
                for i in tracks:
                    failed = self._download_release_track(
                        dirn,
                        count,
                        i,
                        meta,
                        is_multiple,
                        False,
                        lyrics_executor=album_lyrics_ex,
                        lyrics_sidecar_executor=album_lyrics_sidecar_ex,
                        lyrics_pending=album_lyrics_pending,
                        lyrics_pending_lock=album_lyrics_lock,
                    )
                    if failed:
                        failed_tracks.append(failed)
                    count += 1
        finally:
            self._drain_deferred_lyrics(album_lyrics_pending, album_lyrics_lock)
            if album_lyrics_ex is not None:
                album_lyrics_ex.shutdown(wait=True)
            if album_lyrics_sidecar_ex is not None:
                album_lyrics_sidecar_ex.shutdown(wait=True)

        if failed_tracks:
            logger.warning(
                f"{YELLOW}{len(failed_tracks)} track(s) failed: "
                + ", ".join(failed_tracks)
            )
        logger.info(f"{GREEN}Completed")

    def _download_release_track(
        self,
        dirn: str,
        tmp_count: int,
        track_meta: dict,
        album_meta: dict,
        is_multiple: bool,
        parallel_mode: bool,
        *,
        lyrics_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
        lyrics_sidecar_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
        lyrics_pending: Optional[list] = None,
        lyrics_pending_lock=None,
    ):
        # Cooperative pause/cancel: do not begin a new track's URL resolution / FLAC job
        # (in-flight byte streams check _stream_abort_is_set in tqdm / _dl_* only).
        if self._cooperative_stop_is_set():
            logger.info(
                "Skipping track before start (pause/cancel): %s id=%s",
                _get_title(track_meta),
                id(self.cancel_event),
            )
            return None

        track_title = _get_title(track_meta)
        track_num = track_meta.get("track_number", tmp_count)
        la, alb, dura, tr_ex = _lyric_ctx_for_ui(track_meta, album_meta)
        try:
            parse = self.client.get_track_url(track_meta["id"], fmt_id=self.quality)
        except Exception as exc:
            logger.error("%sFailed to resolve %s: %s", RED, track_title, exc)
            alb_fail = _album_title_for_track_marker(False, track_meta, album_meta)
            _emit_track_marker(
                "TRACK_RESULT",
                track_num,
                track_title,
                "failed",
                str(exc),
                lyric_album=alb_fail,
                slot_track_id=str(track_meta.get("id") or ""),
                album_release_id=str(self.item_id),
            )
            return track_title

        if "sample" in parse or not parse.get("sampling_rate"):
            if self._cooperative_stop_is_set():
                return None
            _emit_track_start(
                track_num,
                track_title,
                _album_cover_thumb(album_meta),
                artist=la,
                album=alb,
                duration_sec=dura,
                track_explicit=tr_ex,
            )
            _emit_track_marker(
                "TRACK_RESULT",
                track_num,
                track_title,
                "purchase_only",
                self._purchase_open_url(track_meta, album_meta),
                queue_url=self.source_queue_url,
                lyric_album=_album_title_for_track_marker(False, track_meta, album_meta),
                slot_track_id=str(track_meta.get("id") or ""),
                album_release_id=str(self.item_id),
            )
            logger.info(f"{OFF}Track not available for download (no stream URL)")
            return None

        if self._cooperative_stop_is_set():
            return None

        _emit_track_start(
            track_num,
            track_title,
            _album_cover_thumb(album_meta),
            artist=la,
            album=alb,
            duration_sec=dura,
            track_explicit=tr_ex,
        )
        is_mp3 = int(self.quality) == 5
        try:
            self._download_and_tag(
                dirn,
                tmp_count,
                parse,
                track_meta,
                album_meta,
                False,
                is_mp3,
                track_meta.get("media_number") if is_multiple else None,
                lyrics_executor=lyrics_executor,
                lyrics_sidecar_executor=lyrics_sidecar_executor,
                lyrics_pending=lyrics_pending,
                lyrics_pending_lock=lyrics_pending_lock,
            )
        except Exception as exc:
            logger.error(f"{RED}Failed to download {track_title}: {exc}")
            alb_fail = _album_title_for_track_marker(False, track_meta, album_meta)
            _emit_track_marker(
                "TRACK_RESULT",
                track_num,
                track_title,
                "failed",
                str(exc),
                lyric_album=alb_fail,
                slot_track_id=str(track_meta.get("id") or ""),
                album_release_id=str(self.item_id),
            )
            return track_title

        if self.delay_seconds > 0 and not parallel_mode:
            time.sleep(self.delay_seconds)
        return None

    def _album_folder_for_meta(self, meta: dict) -> Tuple[str, bool]:
        album_title = _get_title(meta)
        format_info = self._get_format(meta)
        file_format, _quality_met, bit_depth, sampling_rate = format_info
        folder_format, _unused_tf = _clean_format_str(
            self.folder_format, self.track_format, file_format
        )
        album_attr = self._get_album_attr(
            meta, album_title, file_format, bit_depth, sampling_rate
        )
        sanitized_title = sanitize_filepath(folder_format.format(**album_attr))
        dirn = os.path.join(self.path, sanitized_title)
        tracks = list((meta.get("tracks") or {}).get("items") or [])
        media_numbers = [tr.get("media_number", 1) for tr in tracks]
        is_multiple = len(set(media_numbers)) > 1
        return dirn, is_multiple

    def download_substitute_for_slot(
        self,
        album_meta: dict,
        slot_track_meta: dict,
        substitute_track_id: str,
    ) -> bool:
        """Stream audio from another release ID but tag/path as *slot_track_meta* on *album_meta*."""
        sid = str(substitute_track_id or "").strip()
        track_title = _get_title(slot_track_meta)
        track_num = slot_track_meta.get("track_number", 1)
        alb_mark = _album_title_for_track_marker(False, slot_track_meta, album_meta)
        sid_slot = str(slot_track_meta.get("id") or "")

        def _fail(msg: str) -> bool:
            logger.warning("%sAttach substitute failed: %s", OFF, msg)
            _emit_track_marker(
                "TRACK_RESULT",
                track_num,
                track_title,
                "failed",
                msg,
                queue_url=self.source_queue_url,
                lyric_album=alb_mark,
                slot_track_id=sid_slot,
                album_release_id=str(self.item_id),
            )
            return False

        if not sid:
            return _fail("Missing substitute track id")
        dirn, is_multiple = self._album_folder_for_meta(album_meta)
        os.makedirs(dirn, exist_ok=True)

        try:
            tc = int(slot_track_meta.get("track_number") or 1)
        except (TypeError, ValueError):
            tc = 1

        try:
            sub_chk = self.client.get_track_meta(sid)
        except Exception as exc:
            return _fail(str(exc))

        if _track_explicit_flag(sub_chk) != _track_explicit_flag(slot_track_meta):
            return _fail(
                "Explicit/clean mismatch — pick a track with the same content rating."
            )

        try:
            parse = self.client.get_track_url(sid, fmt_id=self.quality)
        except Exception as exc:
            return _fail(str(exc))

        if "sample" in parse or not parse.get("sampling_rate"):
            return _fail("That track is not streamable here (purchase-only or sample).")

        la, alb, dura, tr_ex = _lyric_ctx_for_ui(slot_track_meta, album_meta)
        _emit_track_start(
            track_num,
            track_title,
            _album_cover_thumb(album_meta),
            artist=la,
            album=alb,
            duration_sec=dura,
            track_explicit=tr_ex,
        )
        is_mp3 = int(self.quality) == 5
        try:
            self._download_and_tag(
                dirn,
                tc,
                parse,
                slot_track_meta,
                album_meta,
                False,
                is_mp3,
                slot_track_meta.get("media_number") if is_multiple else None,
                stream_track_id=sid,
                lyrics_track_meta=sub_chk,
            )
        except Exception as exc:
            logger.error("%sAttach download failed: %s", RED, exc)
            return _fail(str(exc))
        return True

    def write_missing_track_placeholder(
        self,
        album_meta: dict,
        slot_track_meta: dict,
        *,
        native_lang: bool = False,
    ) -> Tuple[bool, str]:
        """Write `{stem}.missing.txt` using the same naming rules as a real rip (no audio)."""
        try:
            track_title = _get_title(slot_track_meta)
            artist = _safe_get(slot_track_meta, "performer", "name")
            dirn, is_multiple = self._album_folder_for_meta(album_meta)
            os.makedirs(dirn, exist_ok=True)

            multiple = slot_track_meta.get("media_number") if is_multiple else None
            root_dir = dirn
            if multiple is not None and not self.multiple_disc_one_dir:
                try:
                    d_num = int(multiple)
                except (ValueError, TypeError):
                    d_num = 1
                root_dir = os.path.join(dirn, f"{self.multiple_disc_prefix} {d_num:02d}")
                os.makedirs(root_dir, exist_ok=True)

            filename_attr = self._get_filename_attr(
                artist, slot_track_meta, track_title
            )
            if multiple:
                formatted_path = sanitize_filename(
                    self.multiple_disc_track_format.format(**filename_attr)
                )
            else:
                formatted_path = sanitize_filename(
                    self.track_format.format(**filename_attr)
                )
            stem = formatted_path[:250]
            missing_path = os.path.join(root_dir, f"{stem}.missing.txt")

            try:
                dur_s = int(slot_track_meta.get("duration") or 0)
            except (TypeError, ValueError):
                dur_s = 0

            hid = str(slot_track_meta.get("id") or "")
            alb_id_e = (
                album_meta.get("id")
                if isinstance(album_meta, dict)
                else slot_track_meta.get("album_id")
            )

            alb_title = ""
            try:
                alb_title = _get_title(album_meta) if isinstance(album_meta, dict) else ""
            except (KeyError, TypeError):
                alb_title = ""

            bd = slot_track_meta.get("maximum_bit_depth")
            sr_raw = slot_track_meta.get("maximum_sampling_rate")

            qlid = int(self.quality)
            qlabel_fb = (
                {
                    5: "MP3 (~320 kbps)",
                    6: "CD FLAC (~16-bit / 44.1 kHz)",
                    7: "24-bit FLAC (selected depth/rate varies)",
                    27: "Best available FLAC / hires (according to subscription)",
                }.get(
                    qlid,
                    str(qlid),
                )
            )
            ext_expect = ".mp3" if qlid == 5 else ".flac"

            alb_cms_url = ""
            if isinstance(album_meta, dict):
                alb_cms_url = str(album_meta.get("url") or "").strip()
            slug = _qobuz_store_slug_from_cms_or_default(native_lang, alb_cms_url)
            www_album = ""
            www_track = ""
            if alb_id_e:
                www_album = _qobuz_www_album_product_url(slug, alb_id_e)
            if hid:
                www_track = _qobuz_www_track_product_url(slug, hid)
            play_album = ""
            play_track = ""
            if alb_id_e:
                play_album = _qobuz_album_open_url(alb_id_e)
            if hid:
                play_track = _qobuz_track_open_url(hid)

            tn = slot_track_meta.get("track_number", "")
            dnum = slot_track_meta.get("media_number", "")
            dur_mm = dur_s // 60
            dur_ss = dur_s % 60

            rel_folder = "(see Full path below)"
            try:
                dl_root_abs = os.path.abspath(self.path or "")
                root_abs = os.path.abspath(root_dir)
                nl = os.path.normcase(dl_root_abs)
                nr = os.path.normcase(root_abs)
                if self.path and (nr == nl or nr.startswith(nl + os.sep)):
                    rel_folder = os.path.relpath(root_dir, self.path)
            except (ValueError, OSError):
                pass

            explicit_flag = _track_explicit_flag(slot_track_meta)
            explicit_txt = "Yes" if explicit_flag else "No"
            tn_disp = str(tn).strip() if str(tn).strip() != "" else "?"
            disc_disp = str(dnum).strip() if str(dnum).strip() != "" else "1"
            isrc_s = (slot_track_meta.get("isrc") or "").strip()
            album_id_s = str(alb_id_e or "").strip()
            track_id_s = str(hid or "").strip()
            artist_s = (artist or "").strip()
            album_title_s = (alb_title or "").strip()
            abs_missing = os.path.abspath(missing_path)
            would_name = f"{stem}{ext_expect}"
            quality_human = _missing_ph_quality_line(qlid, qlabel_fb, bd, sr_raw)

            def _url_or_dash(u: str) -> str:
                u = (u or "").strip()
                return u if u else "(not available)"

            txt_lines = [
                "MISSING TRACK PLACEHOLDER",
                f"Created by Qobuz-DL-GUI v{QOBUZ_DL_GUI_VERSION}",
                "",
                "This track could not be downloaded (removed from streaming / "
                "purchase-only / no replacement available).",
                "The file below shows exactly what the track would have been named "
                "and where it would have gone.",
                "",
                "--- Track Info ---",
                _missing_ph_line("Title", _get_title(slot_track_meta)),
                _missing_ph_line("Artist", artist_s or "(unknown)"),
                _missing_ph_line("Explicit", explicit_txt),
                _missing_ph_line(
                    "Duration",
                    f"{dur_mm}:{dur_ss:02d} ({dur_s} seconds)" if dur_s else "0:00 (0 seconds)",
                ),
                _missing_ph_line("Track #", tn_disp),
                _missing_ph_line("Disc #", disc_disp),
                "",
                "--- Album ---",
                _missing_ph_line("Album Title", album_title_s or "(unknown)"),
                _missing_ph_line("Qobuz Album ID", album_id_s or "(unknown)"),
                "",
                "--- Links (click to open) ---",
                _missing_ph_line("Store (album)", _url_or_dash(www_album)),
                _missing_ph_line("Store (track)", _url_or_dash(www_track)),
                _missing_ph_line("Play (album)", _url_or_dash(play_album)),
                _missing_ph_line("Play (track)", _url_or_dash(play_track)),
                "",
                "--- Technical Details ---",
                _missing_ph_line("Quality", quality_human),
                _missing_ph_line("Qobuz Track ID", track_id_s or "(unknown)"),
                _missing_ph_line("ISRC", isrc_s or "(unknown)"),
                "",
                "--- Naming Used ---",
                _missing_ph_line("Would have been", would_name),
                _missing_ph_line(
                    "Folder",
                    rel_folder.replace("/", os.sep) if rel_folder else "(unknown)",
                ),
                _missing_ph_line("Full path", abs_missing),
                "",
                "Configured track naming pattern:",
                f"  {(self.multiple_disc_track_format if multiple else self.track_format)}",
                "",
            ]
            payload = ("\n".join(txt_lines)).encode("utf-8")
            with open(missing_path, "wb") as fh:
                fh.write(payload)

            missing_abs = os.path.abspath(missing_path)
            canonical_audio_anchor = os.path.join(root_dir, f"{stem}{ext_expect}")

            cov = (
                _album_cover_thumb(slot_track_meta)
                or (
                    _album_cover_thumb(album_meta)
                    if isinstance(album_meta, dict)
                    else ""
                )
            )
            la, alb_tl, dura, tr_ex = _lyric_ctx_for_ui(
                slot_track_meta,
                album_meta if isinstance(album_meta, dict) else None,
            )
            _emit_track_start(
                slot_track_meta.get("track_number", 1),
                track_title,
                cov,
                artist=la,
                album=alb_tl,
                duration_sec=dura,
                track_explicit=tr_ex,
            )
            _emit_track_marker(
                "TRACK_RESULT",
                slot_track_meta.get("track_number", 1),
                track_title,
                "downloaded",
                os.path.basename(missing_path),
                queue_url=self.source_queue_url or "",
                local_path=missing_abs,
                lyric_album=_album_title_for_track_marker(
                    True, slot_track_meta, album_meta
                ),
                slot_track_id=str(slot_track_meta.get("id") or ""),
                album_release_id=str(
                    (album_meta.get("id") if isinstance(album_meta, dict) else "")
                    or self.item_id
                    or "",
                ),
            )

            if self.lyrics_enabled:
                try:
                    lyrics_ui_title = track_title
                    explicit_pre = bool(
                        slot_track_meta.get("parental_warning")
                        or slot_track_meta.get("parental_advisory")
                        or slot_track_meta.get("explicit")
                        or _safe_get(slot_track_meta, "album", "parental_warning")
                        or _safe_get(slot_track_meta, "album", "parental_advisory")
                        or _safe_get(slot_track_meta, "album", "explicit")
                    )
                    track_for_lyrics = _track_dict_for_lrclib(
                        slot_track_meta,
                        album_meta if isinstance(album_meta, dict) else None,
                    )
                    _emit_lyrics_marker(
                        slot_track_meta.get("track_number"),
                        lyrics_ui_title,
                        "loading",
                        "searching",
                        None,
                        missing_abs,
                    )
                    result = lyrics.fetch_synced_lyrics_with_search_fallback(
                        track_for_lyrics,
                        prefer_explicit=explicit_pre,
                        timeout_sec=12.0,
                        max_fallback_candidates=5,
                    )
                    if not result:
                        _emit_lyrics_marker(
                            slot_track_meta.get("track_number"),
                            lyrics_ui_title,
                            "none",
                            "not-found",
                            0,
                            missing_abs,
                        )
                    else:
                        lyric_type = str(result.get("lyrics_type", "synced"))
                        conf = result.get("confidence")
                        lyrics_body = (result.get("lyrics") or "").strip()
                        if lyric_type == "instrumental" and not lyrics_body:
                            lyrics_body = lyrics.instrumental_placeholder_lrc()
                        if not lyrics_body:
                            _emit_lyrics_marker(
                                slot_track_meta.get("track_number"),
                                lyrics_ui_title,
                                "none",
                                result.get("provider", "none"),
                                conf,
                                missing_abs,
                            )
                        else:
                            # Sidecar basename matches would-be FLAC/MP3 stem (see write_lrc_sidecar).
                            out = lyrics.write_lrc_sidecar(
                                canonical_audio_anchor,
                                result["lyrics"],
                                overwrite=False,
                            )
                            if not out:
                                _emit_lyrics_marker(
                                    slot_track_meta.get("track_number"),
                                    lyrics_ui_title,
                                    result.get("lyrics_type", "unknown"),
                                    "already-exists",
                                    conf,
                                    missing_abs,
                                    "lrc",
                                )
                            else:
                                lid = result.get("lrclib_id")
                                if lid is not None:
                                    try:
                                        lyrics.write_lrclib_id_sidecar(
                                            missing_abs, int(lid)
                                        )
                                    except (
                                        TypeError,
                                        ValueError,
                                        OSError,
                                    ):
                                        pass
                                provider = result.get("provider", "provider")
                                _emit_lyrics_marker(
                                    slot_track_meta.get("track_number"),
                                    lyrics_ui_title,
                                    lyric_type,
                                    provider,
                                    conf,
                                    missing_abs,
                                    "lrc",
                                )
                except Exception as le:
                    logger.warning(
                        "%sLyrics fetch for missing placeholder failed: %s",
                        YELLOW,
                        le,
                    )
                    try:
                        _emit_lyrics_marker(
                            slot_track_meta.get("track_number"),
                            track_title,
                            "error",
                            str(le),
                            0,
                            missing_abs,
                        )
                    except Exception:
                        pass

            logger.info("%sSaved missing-placeholder: %s", OFF, missing_path)
            return True, missing_abs
        except KeyError as e:
            logger.warning("%smissing-placeholder format error: %s", YELLOW, e)
            return (
                False,
                f"Track format pattern refers to unknown field: {e}. Check Settings -> Track format.",
            )
        except OSError as e:
            logger.warning("%smissing-placeholder I/O error: %s", YELLOW, e)
            return False, str(e)
        except Exception as e:
            logger.warning("%smissing-placeholder failed: %s", YELLOW, e, exc_info=True)
            return False, str(e)

    def download_track(self):
        parse = self.client.get_track_url(self.item_id, self.quality)

        if self._cooperative_stop_is_set():
            return

        if "sample" not in parse and parse["sampling_rate"]:
            meta = self.client.get_track_meta(self.item_id)
            track_title = _get_title(meta)
            track_num = meta.get("track_number", 1)
            artist = _safe_get(meta, "performer", "name")
            logger.info(f"\n{YELLOW}Downloading: {artist} - {track_title}")
            la, alb, dura, tr_ex = _lyric_ctx_for_ui(meta, None)
            _emit_track_start(
                track_num,
                track_title,
                _album_cover_thumb(meta),
                artist=la,
                album=alb,
                duration_sec=dura,
                track_explicit=tr_ex,
            )
            format_info = self._get_format(meta, is_track_id=True, track_url_dict=parse)
            file_format, quality_met, bit_depth, sampling_rate = format_info

            folder_format, track_format = _clean_format_str(
                self.folder_format, self.track_format, str(bit_depth)
            )

            if not self.downgrade_quality and not quality_met:
                logger.info(
                    f"{OFF}Skipping {track_title} as it doesn't "
                    "meet quality requirement"
                )
                return
            track_attr = self._get_track_attr(
                meta, track_title, bit_depth, sampling_rate, file_format
            )
            sanitized_title = sanitize_filepath(folder_format.format(**track_attr))

            dirn = os.path.join(self.path, sanitized_title)

            if self._cooperative_stop_is_set():
                return

            os.makedirs(dirn, exist_ok=True)
            if self.no_cover:
                logger.info(f"{OFF}Skipping cover")
            else:
                cover_url = _album_cover_large_fetch_url(meta.get("album") or {})
                if cover_url:
                    _get_extra(
                        cover_url,
                        dirn,
                        og_quality=self.cover_og_quality,
                        cancel_event=self._stream_abort_evt(),
                    )
            is_mp3 = True if int(self.quality) == 5 else False
            try:
                self._download_and_tag(
                    dirn,
                    1,
                    parse,
                    meta,
                    meta,
                    True,
                    is_mp3,
                    False,
                )
            except Exception as e:
                logger.error(f"{RED}Failed to download {track_title}: {e}")
                _emit_track_marker("TRACK_RESULT", meta.get("track_number", 1), track_title, "failed", str(e))
        else:
            try:
                meta = self.client.get_track_meta(self.item_id)
            except Exception:
                meta = {}
            track_title = _get_title(meta) if meta else f"track {self.item_id}"
            track_num = meta.get("track_number", 1) if meta else 1
            thumb = _album_cover_thumb(meta) if meta else ""
            la, alb, dura, tr_ex = _lyric_ctx_for_ui(meta if meta else {}, None)
            _emit_track_start(
                track_num,
                track_title,
                thumb,
                artist=la,
                album=alb,
                duration_sec=dura,
                track_explicit=tr_ex,
            )
            _emit_track_marker(
                "TRACK_RESULT",
                track_num,
                track_title,
                "purchase_only",
                self._purchase_open_url(meta, meta.get("album")),
                queue_url=self.source_queue_url,
                lyric_album=_album_title_for_track_marker(True, meta, meta.get("album")),
                slot_track_id=str(meta.get("id") or ""),
                album_release_id="",
            )
            logger.info(f"{OFF}Track not available for download (no stream URL)")
        logger.info(f"{GREEN}Completed")

    def _download_and_tag(
        self,
        root_dir,
        tmp_count,
        track_url_dict,
        track_metadata,
        album_or_track_metadata,
        is_track,
        is_mp3,
        multiple=None,
        *,
        stream_track_id=None,
        lyrics_track_meta=None,
        lyrics_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
        lyrics_sidecar_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None,
        lyrics_pending: Optional[list] = None,
        lyrics_pending_lock=None,
    ):
        if self._stream_abort_is_set():
            return
        
        extension = ".mp3" if is_mp3 else ".flac"

        try:
            initial_url = track_url_dict["url"]
        except KeyError:
            turl = self._purchase_open_url(
                track_metadata,
                album_or_track_metadata if not is_track else None,
            )
            _emit_track_marker(
                "TRACK_RESULT",
                track_metadata.get("track_number", tmp_count),
                track_metadata.get("title", "track"),
                "purchase_only",
                turl,
                queue_url=self.source_queue_url,
                lyric_album=_album_title_for_track_marker(
                    is_track, track_metadata, album_or_track_metadata
                ),
                slot_track_id=str(track_metadata.get("id") or ""),
                album_release_id="" if is_track else str(self.item_id),
            )
            logger.info(f"{OFF}Track not available for download")
            return

        if multiple and not self.multiple_disc_one_dir:
            try:
                d_num = int(multiple)
            except (ValueError, TypeError):
                d_num = 1
            root_dir = os.path.join(root_dir, f"{self.multiple_disc_prefix} {d_num:02d}")
            os.makedirs(root_dir, exist_ok=True)

        filename = os.path.join(root_dir, f".{tmp_count:02}.tmp")

        # Determine the filename
        track_title = _get_title(track_metadata)
        artist = _safe_get(track_metadata, "performer", "name")
        filename_attr = self._get_filename_attr(artist, track_metadata, track_title)

        # track_format is a format string
        # e.g. '{tracknumber}. {artist} - {tracktitle}'
        if multiple:
            formatted_path = sanitize_filename(
                self.multiple_disc_track_format.format(**filename_attr)
            )
        else:
            formatted_path = sanitize_filename(self.track_format.format(**filename_attr))
        final_file = os.path.join(root_dir, formatted_path)[:250] + extension

        if os.path.isfile(final_file):
            logger.info(f"{OFF}{track_title} was already downloaded")
            _emit_track_marker(
                "TRACK_RESULT",
                track_metadata.get("track_number", tmp_count),
                track_title,
                "downloaded",
                "already-exists",
                queue_url=self.source_queue_url,
                local_path=final_file,
                lyric_album=_album_title_for_track_marker(
                    is_track, track_metadata, album_or_track_metadata
                ),
                slot_track_id=str(track_metadata.get("id") or ""),
                album_release_id="" if is_track else str(self.item_id),
                substitute_attach=bool(stream_track_id),
            )
            return

        if is_track:
            lyrics_release_album = (
                (album_or_track_metadata or {}).get("album")
                if isinstance(album_or_track_metadata, dict)
                else None
            )
        else:
            lyrics_release_album = album_or_track_metadata

        lyrics_ex: Optional[concurrent.futures.ThreadPoolExecutor] = None
        lyrics_fut: Optional[concurrent.futures.Future] = None
        _t_lrc_start: Optional[float] = None
        defer_lyrics_sidecar = (
            lyrics_sidecar_executor is not None and lyrics_pending is not None
        )
        if self.lyrics_any_enabled:
            l_meta = lyrics_track_meta or track_metadata
            try:
                lyrics_ui_title_pre = _get_title(l_meta)
            except Exception:
                lyrics_ui_title_pre = str((l_meta or {}).get("title") or "track")
            explicit_pre = bool(
                l_meta.get("parental_warning")
                or l_meta.get("parental_advisory")
                or l_meta.get("explicit")
                or _safe_get(l_meta, "album", "parental_warning")
                or _safe_get(l_meta, "album", "parental_advisory")
                or _safe_get(l_meta, "album", "explicit")
            )
            
            l_album_meta = l_meta.get("album") if lyrics_track_meta else lyrics_release_album
            track_for_lyrics = _track_dict_for_lrclib(
                l_meta, l_album_meta
            )
            _emit_lyrics_marker(
                track_metadata.get("track_number"),
                lyrics_ui_title_pre,
                "loading",
                "searching",
                None,
                final_file,
            )
            _t_lrc_start = time.monotonic()
            logger.info(
                "[LRC_TIMING] sidecar FETCH_START title=%s (parallel with download)",
                lyrics_ui_title_pre,
            )
            run_lyrics_ex = lyrics_executor
            if run_lyrics_ex is None:
                lyrics_ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                run_lyrics_ex = lyrics_ex
            lyrics_fut = run_lyrics_ex.submit(
                lyrics.fetch_synced_lyrics_with_search_fallback,
                track_for_lyrics,
                prefer_explicit=explicit_pre,
                timeout_sec=12.0,
                max_fallback_candidates=5,
            )

        def get_fresh_url(quality_override=None):
            fmt = quality_override or self.quality
            tid_for_url = stream_track_id or track_metadata.get("id")
            try:
                res = self.client.get_track_url(tid_for_url, fmt_id=fmt)
                new_url = res.get("url")
                if new_url:
                    return new_url
                logger.warning("get_track_url returned no URL, using initial")
                return initial_url
            except Exception as exc:
                logger.warning(f"get_track_url failed ({exc}), using initial URL")
                return initial_url

        try:
            # Try at requested quality first; on failure, try lower qualities
            qualities_to_try = _quality_fallback_chain(int(self.quality))
            download_ok = False
            for q in qualities_to_try:
                url_fn = (lambda qual: lambda: get_fresh_url(qual))(q)
                try:
                    if q != int(self.quality):
                        logger.info(
                            f"{YELLOW}Retrying {track_title} at quality {q} "
                            f"(original: {self.quality})..."
                        )
                    tqdm_download(
                        url_fn,
                        filename,
                        filename,
                        cancel_event=self._stream_abort_evt(),
                        segmented_fallback=self.segmented_fallback and not is_mp3,
                        remux_flac=not is_mp3,
                        progress_callback=_make_throttled_download_progress(
                            track_metadata,
                            tmp_count,
                            track_title,
                            is_track=is_track,
                            album_or_track_metadata=album_or_track_metadata,
                        ),
                    )
                    download_ok = True
                    break
                except ConnectionError as e:
                    logger.warning(
                        f"{YELLOW}Quality {q} failed for {track_title}: {e}"
                    )
                    continue

            if not download_ok:
                raise ConnectionError(
                    f"All quality levels failed for {track_title}"
                )
            tag_display_title = (
                _track_metadata_display_title(track_metadata)
                if self.tag_title_from_track_format
                else None
            )
            tag_display_album = (
                self._album_tag_from_folder_format(
                    track_metadata,
                    album_or_track_metadata,
                    is_track,
                    track_url_dict,
                )
                if self.tag_album_from_folder_format
                else None
            )
            tag_function = metadata.tag_mp3 if is_mp3 else metadata.tag_flac
            try:
                tag_function(
                    filename,
                    root_dir,
                    final_file,
                    track_metadata,
                    album_or_track_metadata,
                    is_track,
                    self.embed_art,
                    tag_options=self.tag_options,
                    tag_display_title=tag_display_title,
                    tag_display_album=tag_display_album,
                )
            except Exception as e:
                logger.error(f"{RED}Error tagging the file: {e}", exc_info=True)

            _emit_track_marker(
                "TRACK_RESULT",
                track_metadata.get("track_number", tmp_count),
                track_title,
                "downloaded",
                os.path.basename(final_file),
                queue_url=self.source_queue_url,
                local_path=final_file,
                lyric_album=_album_title_for_track_marker(
                    is_track, track_metadata, album_or_track_metadata
                ),
                slot_track_id=str(track_metadata.get("id") or ""),
                album_release_id="" if is_track else str(self.item_id),
                substitute_attach=bool(stream_track_id),
            )
            if lyrics_fut is not None and defer_lyrics_sidecar:
                sidecar_fut = self._schedule_deferred_lyrics_sidecar(
                    lyrics_sidecar_executor,
                    final_file,
                    track_metadata,
                    lyrics_release_album,
                    lyrics_fut,
                    _t_lrc_start,
                    lyrics_track_meta,
                )
                if lyrics_pending_lock is not None:
                    with lyrics_pending_lock:
                        lyrics_pending.append(sidecar_fut)
                else:
                    lyrics_pending.append(sidecar_fut)
            else:
                self._write_track_lyrics_sidecar(
                    final_file,
                    track_metadata,
                    lyrics_release_album,
                    lyrics_fetch_future=lyrics_fut,
                    lyrics_fetch_started_at=_t_lrc_start,
                    lyrics_track_meta=lyrics_track_meta,
                )
        finally:
            if lyrics_ex is not None:
                lyrics_ex.shutdown(wait=True)

    def _schedule_deferred_lyrics_sidecar(
        self,
        sidecar_executor: concurrent.futures.ThreadPoolExecutor,
        final_file,
        track_metadata,
        release_album_meta,
        lyrics_fetch_future: concurrent.futures.Future,
        lyrics_fetch_started_at,
        lyrics_track_meta,
    ) -> concurrent.futures.Future:
        done_future: concurrent.futures.Future = concurrent.futures.Future()

        def _copy_sidecar_result(sidecar_future: concurrent.futures.Future) -> None:
            try:
                sidecar_future.result()
            except Exception as exc:
                if not done_future.done():
                    done_future.set_exception(exc)
            else:
                if not done_future.done():
                    done_future.set_result(None)

        def _submit_sidecar(_fetch_future: concurrent.futures.Future) -> None:
            if done_future.done():
                return
            try:
                sidecar_future = sidecar_executor.submit(
                    self._write_track_lyrics_sidecar,
                    final_file,
                    track_metadata,
                    release_album_meta,
                    lyrics_fetch_future=_fetch_future,
                    lyrics_fetch_started_at=lyrics_fetch_started_at,
                    lyrics_track_meta=lyrics_track_meta,
                )
            except Exception as exc:
                if not done_future.done():
                    done_future.set_exception(exc)
                return
            sidecar_future.add_done_callback(_copy_sidecar_result)

        lyrics_fetch_future.add_done_callback(_submit_sidecar)
        return done_future

    def _drain_deferred_lyrics(self, pending_lyrics, pending_lock=None):
        if not pending_lyrics:
            return
        if pending_lock is not None:
            with pending_lock:
                jobs = list(pending_lyrics)
                pending_lyrics.clear()
        else:
            jobs = list(pending_lyrics)
            pending_lyrics.clear()
        if not jobs:
            return
        waiting = [fut for fut in jobs if not fut.done()]
        if waiting:
            logger.info(
                "%sFinishing album lyrics (%s pending)%s",
                YELLOW,
                len(waiting),
                OFF,
            )
        logger.info(
            "[LRC_TIMING] album lyrics DRAIN_START pending=%s total=%s",
            len(waiting),
            len(jobs),
        )
        for fut in concurrent.futures.as_completed(jobs):
            try:
                fut.result()
            except Exception as exc:
                logger.warning("%sLyrics sidecar job failed: %s", YELLOW, exc)
        logger.info(
            "[LRC_TIMING] album lyrics DRAIN_DONE pending=%s total=%s",
            0,
            len(jobs),
        )

    def _write_track_lyrics_sidecar(
        self,
        final_file,
        track_metadata,
        release_album_meta: Optional[dict] = None,
        *,
        lyrics_fetch_future: Optional[concurrent.futures.Future] = None,
        lyrics_fetch_started_at: Optional[float] = None,
        lyrics_track_meta: Optional[dict] = None,
    ):
        if not self.lyrics_any_enabled:
            return
        # Finish lyrics for this file even if the user cancelled the queue: the
        # track is already saved, so skipping here would leave .lrc missing when
        # "Synced Lyrics" is enabled.
        if not os.path.isfile(final_file):
            return
        try:
            lyrics_ui_title = _get_title(track_metadata)
        except Exception:
            lyrics_ui_title = str((track_metadata or {}).get("title") or "track")

        result = None
        if lyrics_fetch_future is None:
            _emit_lyrics_marker(
                track_metadata.get("track_number"),
                lyrics_ui_title,
                "loading",
                "searching",
                None,
                final_file,
            )
            l_meta = lyrics_track_meta or track_metadata
            explicit = bool(
                l_meta.get("parental_warning")
                or l_meta.get("parental_advisory")
                or l_meta.get("explicit")
                or _safe_get(l_meta, "album", "parental_warning")
                or _safe_get(l_meta, "album", "parental_advisory")
                or _safe_get(l_meta, "album", "explicit")
            )
            try:
                l_album_meta = l_meta.get("album") if lyrics_track_meta else release_album_meta
                track_for_lyrics = _track_dict_for_lrclib(
                    l_meta, l_album_meta
                )
                _t_sidecar_lrc = time.monotonic()
                logger.info(
                    "[LRC_TIMING] sidecar FETCH_START title=%s", lyrics_ui_title
                )
                result = lyrics.fetch_synced_lyrics_with_search_fallback(
                    track_for_lyrics,
                    prefer_explicit=explicit,
                    timeout_sec=12.0,
                    max_fallback_candidates=5,
                )
                logger.info(
                    "[LRC_TIMING] +%dms sidecar FETCH_DONE title=%s hit=%s fallback=%s",
                    int((time.monotonic() - _t_sidecar_lrc) * 1000),
                    lyrics_ui_title,
                    bool(result),
                    bool(result.get("search_fallback_used"))
                    if isinstance(result, dict)
                    else False,
                )
            except Exception as e:
                logger.warning(
                    f"{YELLOW}Lyrics fetch failed for {track_metadata.get('title', 'track')}: {e}"
                )
                _emit_lyrics_marker(
                    track_metadata.get("track_number"),
                    lyrics_ui_title,
                    "error",
                    str(e),
                    0,
                    final_file,
                )
                return
        else:
            try:
                result = lyrics_fetch_future.result()
            except Exception as e:
                logger.warning(
                    f"{YELLOW}Lyrics fetch failed for {track_metadata.get('title', 'track')}: {e}"
                )
                _emit_lyrics_marker(
                    track_metadata.get("track_number"),
                    lyrics_ui_title,
                    "error",
                    str(e),
                    0,
                    final_file,
                )
                return
            t0 = lyrics_fetch_started_at or time.monotonic()
            logger.info(
                "[LRC_TIMING] +%dms sidecar FETCH_DONE title=%s hit=%s fallback=%s "
                "(wall time from prefetch start; overlapped with download)",
                int((time.monotonic() - t0) * 1000),
                lyrics_ui_title,
                bool(result),
                bool(result.get("search_fallback_used"))
                if isinstance(result, dict)
                else False,
            )

        try:
            if not result:
                logger.info(
                    f"{OFF}No synced lyrics found for {track_metadata.get('title', 'track')}"
                )
                _emit_lyrics_marker(
                    track_metadata.get("track_number"),
                    lyrics_ui_title,
                    "none",
                    "not-found",
                    0,
                    final_file,
                )
                return
            lyric_type = str(result.get("lyrics_type", "synced"))
            conf = result.get("confidence")
            lyrics_body = (result.get("lyrics") or "").strip()
            if lyric_type == "instrumental" and not lyrics_body:
                lyrics_body = lyrics.instrumental_placeholder_lrc()
            if not lyrics_body:
                logger.info(
                    f"{OFF}No lyrics file written for {track_metadata.get('title', 'track')}"
                )
                _emit_lyrics_marker(
                    track_metadata.get("track_number"),
                    lyrics_ui_title,
                    "none",
                    result.get("provider", "none"),
                    conf,
                    final_file,
                )
                return
            out = None
            metadata_written = False
            if self.lyrics_enabled:
                out = lyrics.write_lrc_sidecar(
                    final_file,
                    lyrics_body,
                    overwrite=False,
                )
            if self.lyrics_embed_metadata:
                metadata_written = metadata.write_lyrics_metadata(final_file, lyrics_body)
            dest_code = (
                "both"
                if self.lyrics_enabled and self.lyrics_embed_metadata
                else "lrc"
                if self.lyrics_enabled
                else "embed"
                if self.lyrics_embed_metadata
                else ""
            )
            if not out and not metadata_written:
                logger.info(
                    f"{OFF}Lyrics already attached or no lyric destination written for {track_metadata.get('title', 'track')}"
                )
                _emit_lyrics_marker(
                    track_metadata.get("track_number"),
                    lyrics_ui_title,
                    result.get("lyrics_type", "unknown"),
                    "already-exists",
                    conf,
                    final_file,
                    dest_code,
                )
                return
            lid = result.get("lrclib_id")
            if lid is not None:
                try:
                    lyrics.write_lrclib_id_sidecar(final_file, int(lid))
                except (TypeError, ValueError, OSError):
                    pass
            provider = result.get("provider", "provider")
            dest = []
            if out:
                dest.append(os.path.basename(out))
            if metadata_written:
                dest.append("metadata")
            dest_label = " + ".join(dest) if dest else "lyrics"
            if lyric_type == "instrumental":
                logger.info(
                    f"{GREEN}Instrumental lyrics saved via {provider}: {dest_label}"
                )
            elif result.get("search_fallback_used"):
                logger.info(
                    f"{YELLOW}Synced lyrics saved via {provider} (search fallback): {dest_label}"
                )
            elif result.get("fallback_used"):
                logger.info(
                    f"{YELLOW}Synced lyrics saved via {provider} (explicit fallback used): {dest_label}"
                )
            else:
                logger.info(
                    f"{GREEN}Synced lyrics saved via {provider}: {dest_label}"
                )
            _emit_lyrics_marker(
                track_metadata.get("track_number"),
                lyrics_ui_title,
                lyric_type,
                provider,
                conf,
                final_file,
                dest_code,
            )
        except Exception as e:
            logger.warning(
                f"{YELLOW}Lyrics fetch failed for {track_metadata.get('title', 'track')}: {e}"
            )
            _emit_lyrics_marker(
                track_metadata.get("track_number"),
                lyrics_ui_title,
                "error",
                str(e),
                0,
                final_file,
            )

    @staticmethod
    def _get_filename_attr(artist, track_metadata, track_title):
        album_meta = track_metadata.get("album") or {}
        album_artist = get_album_artist(album_meta) or _safe_get(
            album_meta, "artist", "name", default=artist
        )
        release_date = (
            track_metadata.get("release_date_original")
            or album_meta.get("release_date_original")
            or ""
        )
        year = release_date.split("-")[0] if release_date else ""
        label = _safe_get(album_meta, "label", "name", default="")
        track_number = int(track_metadata.get("track_number") or 0)
        disc_number = int(track_metadata.get("media_number") or 1)
        return {
            "artist": artist,
            "albumartist": album_artist,
            "album_artist": album_artist,
            "album": _get_title(album_meta) if album_meta else "",
            "album_title": _get_title(album_meta) if album_meta else "",
            "album_title_base": album_meta.get("title", ""),
            "bit_depth": track_metadata.get("maximum_bit_depth"),
            "sampling_rate": track_metadata.get("maximum_sampling_rate"),
            "tracktitle": track_title,
            "track_title": track_title,
            "track_title_base": _track_title_base_with_feat(
                track_metadata.get("title") or ""
            ),
            "track_artist": artist,
            "track_composer": _safe_get(track_metadata, "composer", "name", default=""),
            "track_id": track_metadata.get("id", ""),
            "track_number": f"{track_number:02d}",
            "version": track_metadata.get("version"),
            "tracknumber": f"{track_number:02d}",
            "disc_number": f"{disc_number:02d}",
            "discnumber": f"{disc_number:02d}",
            "disc_number_unpadded": str(disc_number),
            "isrc": track_metadata.get("isrc", ""),
            "year": year,
            "release_date": release_date,
            "album_id": album_meta.get("id", ""),
            "album_url": album_meta.get("url", ""),
            "label": label,
            "barcode": album_meta.get("upc", ""),
            "upc": album_meta.get("upc", ""),
            "media_type": (album_meta.get("product_type") or "").upper(),
            "disc_count": album_meta.get("media_count", ""),
            "track_count": album_meta.get("tracks_count", ""),
        }

    @staticmethod
    def _get_track_attr(meta, track_title, bit_depth, sampling_rate, file_format):
        album_meta = meta.get("album", {})
        album_artist = get_album_artist(album_meta) or _safe_get(
            meta, "performer", "name", default=""
        )
        release_date = album_meta.get("release_date_original", "")
        year = release_date.split("-")[0] if release_date else ""
        track_number = int(meta.get("track_number") or 0)
        disc_number = int(meta.get("media_number") or 1)
        return {
            "album": sanitize_filename(_get_title(album_meta)),
            "artist": sanitize_filename(album_artist),
            "albumartist": sanitize_filename(album_artist),
            "album_artist": sanitize_filename(album_artist),
            "tracktitle": track_title,
            "track_title": track_title,
            "track_title_base": _track_title_base_with_feat(meta.get("title") or ""),
            "track_artist": _safe_get(meta, "performer", "name", default=album_artist),
            "track_composer": _safe_get(meta, "composer", "name", default=""),
            "tracknumber": f"{track_number:02d}",
            "track_number": f"{track_number:02d}",
            "discnumber": f"{disc_number:02d}",
            "disc_number": f"{disc_number:02d}",
            "isrc": meta.get("isrc", ""),
            "album_id": album_meta.get("id", ""),
            "album_url": album_meta.get("url", ""),
            "album_title": _get_title(album_meta),
            "album_title_base": album_meta.get("title", ""),
            "album_genre": _safe_get(album_meta, "genre", "name", default=""),
            "album_composer": _safe_get(album_meta, "composer", "name", default=""),
            "label": _safe_get(album_meta, "label", "name", default=""),
            "copyright": album_meta.get("copyright", ""),
            "upc": album_meta.get("upc", ""),
            "barcode": album_meta.get("upc", ""),
            "release_date": release_date,
            "year": year,
            "media_type": (album_meta.get("product_type") or "").upper(),
            "format": file_format,
            "bit_depth": bit_depth,
            "sampling_rate": sampling_rate,
            "album_version": album_meta.get("version", ""),
            "disc_count": album_meta.get("media_count", ""),
            "track_count": album_meta.get("tracks_count", ""),
        }

    @staticmethod
    def _get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate):
        album_artist = get_album_artist(meta) or _safe_get(meta, "artist", "name", default="")
        release_date = meta.get("release_date_original", "")
        year = release_date.split("-")[0] if release_date else ""
        return {
            "artist": sanitize_filename(meta["artist"]["name"]),
            "album": sanitize_filename(album_title),
            "albumartist": sanitize_filename(album_artist),
            "album_artist": sanitize_filename(album_artist),
            "album_id": meta.get("id", ""),
            "album_url": meta.get("url", ""),
            "album_title": sanitize_filename(album_title),
            "album_title_base": sanitize_filename(meta.get("title", "")),
            "album_genre": _safe_get(meta, "genre", "name", default=""),
            "album_composer": _safe_get(meta, "composer", "name", default=""),
            "label": _safe_get(meta, "label", "name", default=""),
            "copyright": meta.get("copyright", ""),
            "upc": meta.get("upc", ""),
            "barcode": meta.get("upc", ""),
            "release_date": release_date,
            "year": year,
            "media_type": (meta.get("product_type") or "").upper(),
            "format": file_format,
            "bit_depth": bit_depth,
            "sampling_rate": sampling_rate,
            "album_version": meta.get("version", ""),
            "disc_count": meta.get("media_count", ""),
            "track_count": meta.get("tracks_count", ""),
        }

    def _get_format(self, item_dict, is_track_id=False, track_url_dict=None):
        quality_met = True
        if int(self.quality) == 5:
            return ("MP3", quality_met, None, None)
        track_dict = item_dict
        if not is_track_id:
            track_dict = item_dict["tracks"]["items"][0]

        try:
            if self._cooperative_stop_is_set():
                return ("Unknown", True, None, None)
                
            new_track_dict = (
                self.client.get_track_url(track_dict["id"], fmt_id=self.quality)
                if not track_url_dict
                else track_url_dict
            )
            restrictions = new_track_dict.get("restrictions")
            if isinstance(restrictions, list):
                if any(
                    restriction.get("code") == QL_DOWNGRADE
                    for restriction in restrictions
                ):
                    quality_met = False

            return (
                "FLAC",
                quality_met,
                new_track_dict["bit_depth"],
                new_track_dict["sampling_rate"],
            )
        except (KeyError, requests.exceptions.HTTPError):
            return ("Unknown", quality_met, None, None)

    def _album_tag_from_folder_format(
        self,
        track_metadata: dict,
        album_or_track_metadata: dict,
        is_track: bool,
        track_url_dict: dict,
    ) -> Optional[str]:
        """Basename of folder-format path for ALBUM tag (matches release folder naming)."""
        try:
            if is_track:
                meta = track_metadata
                t_title = _get_title(meta)
                fmt_res = self._get_format(
                    meta, is_track_id=True, track_url_dict=track_url_dict
                )
                file_format, _, bit_depth, sampling_rate = fmt_res
                bd_key = (
                    str(bit_depth)
                    if bit_depth is not None
                    else (file_format if file_format else "FLAC")
                )
                folder_fmt, _ = _clean_format_str(
                    self.folder_format, self.track_format, bd_key
                )
                attrs = self._get_track_attr(
                    meta, t_title, bit_depth, sampling_rate, file_format
                )
            else:
                meta = album_or_track_metadata
                alb_title = _get_title(meta)
                fmt_res = self._get_format(meta, is_track_id=False)
                file_format, _, bit_depth, sampling_rate = fmt_res
                folder_fmt, _ = _clean_format_str(
                    self.folder_format, self.track_format, file_format
                )
                attrs = self._get_album_attr(
                    meta, alb_title, file_format, bit_depth, sampling_rate
                )
            rel = sanitize_filepath(folder_fmt.format(**attrs))
            base = os.path.basename(os.path.normpath(rel))
            return base.strip() if base.strip() else None
        except Exception:
            logger.debug(
                "album tag from folder format: fallback to Qobuz album title",
                exc_info=True,
            )
            return None


def _quality_fallback_chain(quality):
    """Return a list of quality IDs to try, starting from the requested one."""
    all_qualities = [27, 7, 6, 5]
    try:
        idx = all_qualities.index(quality)
    except ValueError:
        idx = 0
    return all_qualities[idx:]


def _dl_streaming(url, fname, desc, headers, cancel_event=None, progress_callback=None):
    """Strategy 1: streaming download with iter_content."""
    r = requests.get(
        url,
        allow_redirects=True,
        stream=True,
        headers=headers,
        timeout=(15, 180),
    )
    logger.debug(
        f"[dl-stream] status={r.status_code} len={r.headers.get('content-length')}"
    )
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))

    with (
        open(fname, "wb") as f,
        tqdm(
            total=total,
            unit="iB",
            unit_scale=True,
            unit_divisor=1024,
            desc=desc,
            bar_format=CYAN + "{n_fmt}/{total_fmt} /// {desc}",
        ) as bar,
    ):
        written = 0
        for chunk in r.iter_content(chunk_size=1024 * 32):
            if cancel_event and cancel_event.is_set():
                r.close()
                raise ConnectionAbortedError("Streaming cancelled by user.")
            if not chunk:
                break
            size = f.write(chunk)
            bar.update(size)
            written += size
            if progress_callback and total > 0:
                progress_callback(written, total)
    r.close()

    if total > 0 and written < total:
        raise IOError(f"Streaming incomplete: {written}/{total}")
    if written == 0:
        raise IOError("Streaming got 0 bytes")
    return written


def _dl_non_streaming(url, fname, desc, headers, cancel_event=None, progress_callback=None):
    """Strategy 2: non-streaming (entire body at once, no iter_content)."""
    if cancel_event and cancel_event.is_set():
        return 0
    r = requests.get(
        url,
        allow_redirects=True,
        stream=False,
        headers=headers,
        timeout=(15, 300),
    )
    logger.debug(f"[dl-full] status={r.status_code} len={len(r.content)}")
    r.raise_for_status()

    data = r.content
    if not data:
        raise IOError("Non-streaming got 0 bytes")

    with open(fname, "wb") as f:
        f.write(data)
    logger.debug(f"[dl-full] wrote {len(data)} bytes")
    if progress_callback:
        hdr_total = int(r.headers.get("content-length", 0) or 0)
        total = hdr_total if hdr_total > 0 else len(data)
        if total > 0:
            progress_callback(len(data), total)
    return len(data)


def _dl_urllib(url, fname, desc, headers, cancel_event=None, progress_callback=None):
    """Strategy 3: stdlib urllib (completely different HTTP stack)."""
    if cancel_event and cancel_event.is_set():
        return 0
    import urllib.request

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        logger.debug(f"[dl-urllib] status={resp.status} len={total}")
        with (
            open(fname, "wb") as f,
            tqdm(
                total=total,
                unit="iB",
                unit_scale=True,
                unit_divisor=1024,
                desc=desc,
                bar_format=CYAN + "{n_fmt}/{total_fmt} /// {desc}",
            ) as bar,
        ):
            written = 0
            while True:
                if cancel_event and cancel_event.is_set():
                    raise ConnectionAbortedError("urllib cancelled by user.")
                chunk = resp.read(1024 * 32)
                if not chunk:
                    break
                size = f.write(chunk)
                bar.update(size)
                written += size
                if progress_callback and total > 0:
                    progress_callback(written, total)

    if total > 0 and written < total:
        raise IOError(f"urllib incomplete: {written}/{total}")
    if written == 0:
        raise IOError("urllib got 0 bytes")
    return written


def _dl_segmented_remux(
    url,
    fname,
    desc,
    headers,
    cancel_event=None,
    *,
    remux_flac=False,
    segment_bytes=4 * 1024 * 1024,
    max_workers=6,
    progress_callback=None,
):
    """Fallback segmented downloader for throttled CDN responses."""
    if cancel_event and cancel_event.is_set():
        return 0

    logger.info(
        "%sAkamai-style block detected. Trying segmented fallback...%s", YELLOW, OFF
    )

    head = requests.head(url, allow_redirects=True, headers=headers, timeout=(10, 45))
    head.raise_for_status()
    total = int(head.headers.get("content-length", 0))
    if total <= 0:
        raise IOError("Segmented fallback requires Content-Length")

    ranges = []
    start = 0
    while start < total:
        end = min(start + segment_bytes - 1, total - 1)
        ranges.append((start, end))
        start = end + 1

    def _fetch_range(idx, byte_range):
        if cancel_event and cancel_event.is_set():
            raise ConnectionAbortedError("Segmented fallback cancelled.")
        s, e = byte_range
        h = dict(headers)
        h["Range"] = f"bytes={s}-{e}"
        r = requests.get(
            url,
            allow_redirects=True,
            stream=True,
            headers=h,
            timeout=(10, 90),
        )
        if r.status_code not in (200, 206):
            raise IOError(f"Segment request failed: HTTP {r.status_code}")
        data = r.content
        if not data:
            raise IOError(f"Segment {idx} empty")
        return idx, data

    chunks = [None] * len(ranges)
    completed_bytes = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(ranges))) as ex:
        futures = [ex.submit(_fetch_range, i, br) for i, br in enumerate(ranges)]
        for fut in concurrent.futures.as_completed(futures):
            idx, data = fut.result()
            chunks[idx] = data
            completed_bytes += len(data)
            if progress_callback:
                progress_callback(completed_bytes, total)

    tmp = fname + ".seg.tmp"
    with open(tmp, "wb") as out:
        for part in chunks:
            if cancel_event and cancel_event.is_set():
                raise ConnectionAbortedError("Segmented fallback cancelled.")
            if not part:
                raise IOError("Missing segment data")
            out.write(part)

    if remux_flac:
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            tmp,
            "-c:a",
            "copy",
            "-f",
            "flac",
            fname,
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            logger.warning("ffmpeg not found; saving segmented stream without remux.")
            os.replace(tmp, fname)
            return total

        if proc.returncode != 0:
            logger.warning("ffmpeg remux failed; saving segmented stream as-is.")
            os.replace(tmp, fname)
            return total

        try:
            os.remove(tmp)
        except OSError:
            pass
        return total

    os.replace(tmp, fname)
    return total


def tqdm_download(
    url_getter,
    fname,
    desc,
    max_retries=2,
    cancel_event=None,
    *,
    segmented_fallback=False,
    remux_flac=False,
    progress_callback=None,
):
    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    headers = {"User-Agent": _UA, "Connection": "close"}

    strategies = [
        ("streaming", _dl_streaming),
        ("non-streaming", _dl_non_streaming),
        ("urllib", _dl_urllib),
    ]
    if segmented_fallback:
        strategies.append(
            (
                "segmented-remux",
                lambda u, f, d, h, cancel_event=None, progress_callback=None: _dl_segmented_remux(
                    u,
                    f,
                    d,
                    h,
                    cancel_event=cancel_event,
                    remux_flac=remux_flac,
                    progress_callback=progress_callback,
                ),
            )
        )

    attempts = max(max_retries, len(strategies))
    for attempt in range(attempts):
        if cancel_event and cancel_event.is_set():
            return
        url = url_getter() if callable(url_getter) else url_getter
        strat_name, strat_fn = strategies[min(attempt, len(strategies) - 1)]

        try:
            logger.debug(f"[dl] attempt {attempt} strategy={strat_name}")
            strat_fn(
                url,
                fname,
                desc,
                headers,
                cancel_event=cancel_event,
                progress_callback=progress_callback,
            )
            return  # Success
        except Exception as e:
            logger.debug(f"[dl] {strat_name} failed: {type(e).__name__}: {e}")
            if attempt < attempts - 1:
                wait = 1
                logger.debug(
                    f"[dl] waiting {wait}s before retry {attempt + 1}/{attempts}..."
                )
                time.sleep(wait)
            else:
                raise ConnectionError(
                    f"File download failed after {attempts} attempts "
                    f"for {fname}: {e}"
                )


_PAREN_OR_BRACKET_CHUNK = re.compile(r"\([^)]*\)|\[[^\]]*\]")


def _paren_is_feat_credit(inner: str) -> bool:
    inner = (inner or "").strip()
    # Avoid \\b after "feat." — the dot breaks word-boundary rules vs a following space.
    return bool(
        re.match(
            r"(feat\.(\s+.+|[^\s]+)|featuring\s+|ft\.(\s+.+|[^\s]+))",
            inner,
            flags=re.IGNORECASE,
        )
    )


def _track_title_base_with_feat(raw_title: str) -> str:
    """Strip edition/remaster-style bracket segments; keep only feat./ft./featuring credits."""
    if not (raw_title or "").strip():
        return ""
    s = raw_title.strip()
    feat_segments: list[str] = []
    out_chunks: list[str] = []
    idx = 0
    for m in _PAREN_OR_BRACKET_CHUNK.finditer(s):
        out_chunks.append(s[idx : m.start()])
        seg = m.group(0)
        inner = seg[1:-1]
        if _paren_is_feat_credit(inner):
            feat_segments.append(seg.strip())
        idx = m.end()
    out_chunks.append(s[idx:])
    core = "".join(out_chunks)
    core = re.sub(r"\s+", " ", core).strip()
    suffix = (" " + " ".join(feat_segments)).strip() if feat_segments else ""
    return (core + (" " + suffix if suffix else "")).strip()


def _track_metadata_display_title(track_metadata: dict) -> str:
    """Embedded TITLE tag text: plain title (+ feat credits), no track numbers or edition parens."""
    base = _track_title_base_with_feat(track_metadata.get("title") or "")
    ver = (track_metadata.get("version") or "").strip()
    if ver and _paren_is_feat_credit(ver):
        low = base.lower()
        if ver.lower() not in low and f"({ver.lower()})" not in low:
            base = f"{base} ({ver})".strip()
    work = track_metadata.get("work")
    if work:
        base = f"{work}: {base}".strip()
    return base


def _get_description(item: dict, track_title, multiple=None):
    downloading_title = f"{track_title} "
    f"[{item['bit_depth']}/{item['sampling_rate']}]"
    if multiple:
        downloading_title = f"[Disc {multiple}] {downloading_title}"
    return downloading_title


def _get_title(item_dict):
    album_title = item_dict["title"]
    version = item_dict.get("version")
    if version:
        album_title = (
            f"{album_title} ({version})"
            if version.lower() not in album_title.lower()
            else album_title
        )
    return album_title


def _track_dict_for_lrclib(
    track: dict, release_album_meta: Optional[dict]
) -> dict:
    """Album track ``items`` from Qobuz often omit a nested ``album`` dict.

    LRCLIB confidence and ``/api/get`` need the release title; without it,
    search runs album-less (neutral album score) and the UI shows a different
    percentage than the downloader.
    """
    out = dict(track)
    try:
        full_track_title = _get_title(track)
    except (KeyError, TypeError):
        full_track_title = str(track.get("title") or "").strip()
    if full_track_title:
        out["title"] = full_track_title

    alb = track.get("album")
    if isinstance(alb, dict) and (alb.get("title") or "").strip():
        return out
    if not release_album_meta or not isinstance(release_album_meta, dict):
        return out
    try:
        title = _get_title(release_album_meta)
    except (KeyError, TypeError):
        return out
    if not (title or "").strip():
        return out
    base = dict(alb) if isinstance(alb, dict) else {}
    base["title"] = title
    for key in ("parental_warning", "parental_advisory", "explicit"):
        if key not in base and release_album_meta.get(key):
            base[key] = release_album_meta[key]
    out["album"] = base
    return out


def _get_extra(item, dirn, extra="cover.jpg", og_quality=False, cancel_event=None):
    if cancel_event and cancel_event.is_set():
        return
    if item is None or not str(item).strip():
        return
    url = str(item).strip()
    extra_file = os.path.join(dirn, extra)
    if os.path.isfile(extra_file):
        logger.info(f"{OFF}{extra} was already downloaded")
        return
    fetch_url = url.replace("_600.", "_org.") if og_quality else url
    try:
        tqdm_download(
            fetch_url,
            extra_file,
            extra,
            cancel_event=cancel_event,
        )
    except Exception as exc:
        logger.debug("Skipping optional extra %s: %s", extra, exc)


def _clean_format_str(folder: str, track: str, file_format: str) -> Tuple[str, str]:
    """Cleans up the format strings, avoids errors
    with MP3 files.
    """
    final = []
    for i, fs in enumerate((folder, track)):
        if fs.endswith(".mp3"):
            fs = fs[:-4]
        elif fs.endswith(".flac"):
            fs = fs[:-5]
        fs = fs.strip()

        # default to pre-chosen string if format is invalid
        if file_format in ("MP3", "Unknown") and (
            "bit_depth" in fs or "sampling_rate" in fs
        ):
            default = DEFAULT_FORMATS[file_format][i]
            logger.error(
                f"{RED}invalid format string for format {file_format}"
                f". defaulting to {default}"
            )
            fs = default
        final.append(fs)

    return tuple(final)


def _safe_get(d: dict, *keys, default=None):
    """A replacement for chained `get()` statements on dicts:
    >>> d = {'foo': {'bar': 'baz'}}
    >>> _safe_get(d, 'baz')
    None
    >>> _safe_get(d, 'foo', 'bar')
    'baz'
    """
    curr = d
    res = default
    for key in keys:
        res = curr.get(key, default)
        if res == default or not hasattr(res, "__getitem__"):
            return res
        else:
            curr = res
    return res
