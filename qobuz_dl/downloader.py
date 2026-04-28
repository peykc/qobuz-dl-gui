import logging
import os
import re
import concurrent.futures
import subprocess
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
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.utils import get_album_artist

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


def _qobuz_purchase_open_url(track_meta: dict, album_meta: dict = None) -> str:
    """Qobuz purchase-only items require buying the album; link to the album store page."""
    if album_meta and isinstance(album_meta, dict):
        aid = album_meta.get("id")
        if aid:
            return _qobuz_album_open_url(aid)
    if track_meta and isinstance(track_meta, dict):
        alb = track_meta.get("album")
        if isinstance(alb, dict) and alb.get("id"):
            return _qobuz_album_open_url(alb["id"])
    return _qobuz_track_open_url((track_meta or {}).get("id"))


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
    if (artist or "").strip() or (album or "").strip() or int(duration_sec or 0) > 0:
        a = _safe_marker_value(artist)
        al = _safe_marker_value(album)
        d = int(duration_sec or 0)
        e = 1 if track_explicit else 0
        logger.info(f"[TRACK_START] {num}|{title_s}|{cov}|{a}|{al}|{d}|{e}")
    else:
        logger.info(f"[TRACK_START] {num}|{title_s}|{cov}")


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


def _emit_track_marker(
    marker: str,
    track_num,
    title: str,
    status: str,
    detail: str = "",
    queue_url: str = "",
    local_path: str = "",
    lyric_album: str = "",
):
    num = f"{int(track_num):02d}" if str(track_num).isdigit() else _safe_marker_value(track_num)
    base = f"[{marker}] {num}|{_safe_marker_value(title)}|{_safe_marker_value(status)}|{_safe_marker_value(detail)}"
    qu = _safe_marker_value(queue_url) if queue_url else ""
    lp = _safe_marker_value(local_path) if (local_path or "").strip() else ""
    alb = _safe_marker_value(lyric_album) if (lyric_album or "").strip() else ""
    if lp:
        if alb:
            logger.info(f"{base}|{qu}|{lp}|{alb}")
        else:
            logger.info(f"{base}|{qu}|{lp}")
    elif qu:
        logger.info(f"{base}|{qu}")
    else:
        logger.info(base)


def _emit_lyrics_marker(
    track_num,
    title: str,
    lyric_type: str,
    provider: str,
    confidence=None,
    audio_path: str = "",
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
    logger.info(line)


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
        self.lyrics_enabled = lyrics_enabled
        self.folder_format = folder_format or DEFAULT_FOLDER
        self.track_format = track_format or DEFAULT_TRACK
        self.cancel_event = cancel_event
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

    def download_id_by_type(self, track=True):
        if not track:
            self.download_release()
        else:
            self.download_track()

    def download_release(self):
        count = 1
        meta = self.client.get_album_meta(self.item_id)

        if self.cancel_event and self.cancel_event.is_set():
            return

        if not meta.get("streamable"):
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
        
        if self.cancel_event and self.cancel_event.is_set():
            return

        os.makedirs(dirn, exist_ok=True)

        if self.no_cover:
            logger.info(f"{OFF}Skipping cover")
        else:
            _get_extra(
                meta["image"]["large"],
                dirn,
                og_quality=self.cover_og_quality,
                cancel_event=self.cancel_event,
            )

        if "goodies" in meta:
            try:
                _get_extra(
                    meta["goodies"][0]["url"],
                    dirn,
                    "booklet.pdf",
                    cancel_event=self.cancel_event,
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
                        )
                    )
                for fut in concurrent.futures.as_completed(futures):
                    failed = fut.result()
                    if failed:
                        failed_tracks.append(failed)
        else:
            for i in tracks:
                failed = self._download_release_track(
                    dirn, count, i, meta, is_multiple, False
                )
                if failed:
                    failed_tracks.append(failed)
                count += 1

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
    ):
        if self.cancel_event and self.cancel_event.is_set():
            logger.info("Download cancelled. id=%s", id(self.cancel_event))
            return None

        track_title = _get_title(track_meta)
        track_num = track_meta.get("track_number", tmp_count)
        la, alb, dura, tr_ex = _lyric_ctx_for_ui(track_meta, album_meta)
        try:
            parse = self.client.get_track_url(track_meta["id"], fmt_id=self.quality)
        except Exception as exc:
            logger.error("%sFailed to resolve %s: %s", RED, track_title, exc)
            _emit_track_marker(
                "TRACK_RESULT",
                track_num,
                track_title,
                "failed",
                str(exc),
            )
            return track_title

        if "sample" in parse or not parse.get("sampling_rate"):
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
                _qobuz_purchase_open_url(track_meta, album_meta),
                queue_url=self.source_queue_url,
            )
            logger.info(f"{OFF}Track not available for download (no stream URL)")
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
            )
        except Exception as exc:
            logger.error(f"{RED}Failed to download {track_title}: {exc}")
            _emit_track_marker(
                "TRACK_RESULT",
                track_num,
                track_title,
                "failed",
                str(exc),
            )
            return track_title

        if self.delay_seconds > 0 and not parallel_mode:
            time.sleep(self.delay_seconds)
        return None

    def download_track(self):
        parse = self.client.get_track_url(self.item_id, self.quality)

        if self.cancel_event and self.cancel_event.is_set():
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

            if self.cancel_event and self.cancel_event.is_set():
                return

            os.makedirs(dirn, exist_ok=True)
            if self.no_cover:
                logger.info(f"{OFF}Skipping cover")
            else:
                _get_extra(
                    meta["album"]["image"]["large"],
                    dirn,
                    og_quality=self.cover_og_quality,
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
                _qobuz_purchase_open_url(meta, meta.get("album")),
                queue_url=self.source_queue_url,
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
    ):
        if self.cancel_event and self.cancel_event.is_set():
            return
        
        extension = ".mp3" if is_mp3 else ".flac"

        try:
            initial_url = track_url_dict["url"]
        except KeyError:
            turl = _qobuz_purchase_open_url(
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
            )
            return

        def get_fresh_url(quality_override=None):
            fmt = quality_override or self.quality
            try:
                res = self.client.get_track_url(track_metadata["id"], fmt_id=fmt)
                new_url = res.get("url")
                if new_url:
                    return new_url
                logger.warning("get_track_url returned no URL, using initial")
                return initial_url
            except Exception as exc:
                logger.warning(f"get_track_url failed ({exc}), using initial URL")
                return initial_url

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
                    cancel_event=self.cancel_event,
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
                logger.warning(f"{YELLOW}Quality {q} failed for {track_title}: {e}")
                continue

        if not download_ok:
            raise ConnectionError(f"All quality levels failed for {track_title}")
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
        )
        if is_track:
            lyrics_release_album = (
                (album_or_track_metadata or {}).get("album")
                if isinstance(album_or_track_metadata, dict)
                else None
            )
        else:
            lyrics_release_album = album_or_track_metadata
        self._write_track_lyrics_sidecar(
            final_file, track_metadata, lyrics_release_album
        )

    def _write_track_lyrics_sidecar(
        self, final_file, track_metadata, release_album_meta: Optional[dict] = None
    ):
        if not self.lyrics_enabled:
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
        _emit_lyrics_marker(
            track_metadata.get("track_number"),
            lyrics_ui_title,
            "loading",
            "searching",
            None,
            final_file,
        )
        explicit = bool(
            track_metadata.get("parental_warning")
            or track_metadata.get("parental_advisory")
            or track_metadata.get("explicit")
            or _safe_get(track_metadata, "album", "parental_warning")
            or _safe_get(track_metadata, "album", "parental_advisory")
            or _safe_get(track_metadata, "album", "explicit")
        )
        try:
            track_for_lyrics = _track_dict_for_lrclib(track_metadata, release_album_meta)
            result = lyrics.fetch_synced_lyrics_with_search_fallback(
                track_for_lyrics,
                prefer_explicit=explicit,
                timeout_sec=12.0,
                max_fallback_candidates=5,
            )
            if not result:
                logger.info(f"{OFF}No synced lyrics found for {track_metadata.get('title', 'track')}")
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
            if lyric_type == "instrumental":
                logger.info(
                    f"{OFF}No lyrics file written (instrumental) for {track_metadata.get('title', 'track')}"
                )
                _emit_lyrics_marker(
                    track_metadata.get("track_number"),
                    lyrics_ui_title,
                    lyric_type,
                    result.get("provider", "none"),
                    conf,
                    final_file,
                )
                return
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
            out = lyrics.write_lrc_sidecar(
                final_file,
                result["lyrics"],
                overwrite=False,
            )
            if not out:
                logger.info(f"{OFF}Lyrics sidecar already exists for {track_metadata.get('title', 'track')}")
                _emit_lyrics_marker(
                    track_metadata.get("track_number"),
                    lyrics_ui_title,
                    result.get("lyrics_type", "unknown"),
                    "already-exists",
                    conf,
                    final_file,
                )
                return
            lid = result.get("lrclib_id")
            if lid is not None:
                try:
                    lyrics.write_lrclib_id_sidecar(final_file, int(lid))
                except (TypeError, ValueError, OSError):
                    pass
            provider = result.get("provider", "provider")
            if result.get("search_fallback_used"):
                logger.info(
                    f"{YELLOW}Synced lyrics saved via {provider} (search fallback): {os.path.basename(out)}"
                )
            elif result.get("fallback_used"):
                logger.info(
                    f"{YELLOW}Synced lyrics saved via {provider} (explicit fallback used): {os.path.basename(out)}"
                )
            else:
                logger.info(
                    f"{GREEN}Synced lyrics saved via {provider}: {os.path.basename(out)}"
                )
            _emit_lyrics_marker(
                track_metadata.get("track_number"),
                lyrics_ui_title,
                lyric_type,
                provider,
                conf,
                final_file,
            )
        except Exception as e:
            logger.warning(f"{YELLOW}Lyrics fetch failed for {track_metadata.get('title', 'track')}: {e}")
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
            "track_title_base": track_metadata.get("title", ""),
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
            "track_title_base": meta.get("title", ""),
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
            if self.cancel_event and self.cancel_event.is_set():
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
    alb = track.get("album")
    if isinstance(alb, dict) and (alb.get("title") or "").strip():
        return track
    if not release_album_meta or not isinstance(release_album_meta, dict):
        return track
    try:
        title = _get_title(release_album_meta)
    except (KeyError, TypeError):
        return track
    if not (title or "").strip():
        return track
    out = dict(track)
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
    extra_file = os.path.join(dirn, extra)
    if os.path.isfile(extra_file):
        logger.info(f"{OFF}{extra} was already downloaded")
        return
    tqdm_download(
        item.replace("_600.", "_org.") if og_quality else item,
        extra_file,
        extra,
        cancel_event=cancel_event,
    )


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
