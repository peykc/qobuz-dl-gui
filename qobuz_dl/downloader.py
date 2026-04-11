import logging
import os
import time
from typing import Tuple

import requests
import urllib3
from pathvalidate import sanitize_filename, sanitize_filepath
from tqdm import tqdm

import qobuz_dl.metadata as metadata
from qobuz_dl.color import CYAN, GREEN, OFF, RED, YELLOW
from qobuz_dl.exceptions import NonStreamable

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

DEFAULT_FOLDER = "{artist}/{album} ({year})"
DEFAULT_TRACK = "{tracknumber} - {tracktitle}"

logger = logging.getLogger(__name__)


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
        folder_format=None,
        track_format=None,
        cancel_event=None,
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
        self.folder_format = folder_format or DEFAULT_FOLDER
        self.track_format = track_format or DEFAULT_TRACK
        self.cancel_event = cancel_event

    def download_id_by_type(self, track=True):
        if not track:
            self.download_release()
        else:
            self.download_track()

    def download_release(self):
        count = 0
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
        media_numbers = [track["media_number"] for track in meta["tracks"]["items"]]
        is_multiple = True if len([*{*media_numbers}]) > 1 else False
        failed_tracks = []
        for i in meta["tracks"]["items"]:
            if self.cancel_event and self.cancel_event.is_set():
                logger.info(f"Download cancelled. id={id(self.cancel_event)}")
                return
            parse = self.client.get_track_url(i["id"], fmt_id=self.quality)
            if "sample" not in parse and parse["sampling_rate"]:
                _track_name = _get_title(i)
                _track_num = i.get("track_number", count)
                logger.info(f"[TRACK_START] {int(_track_num):02d}. {_track_name}")
                is_mp3 = True if int(self.quality) == 5 else False
                try:
                    self._download_and_tag(
                        dirn,
                        count,
                        parse,
                        i,
                        meta,
                        False,
                        is_mp3,
                        i["media_number"] if is_multiple else None,
                    )
                except Exception as e:
                    track_title = i.get("title", f"track {count}")
                    logger.error(f"{RED}Failed to download {track_title}: {e}")
                    failed_tracks.append(track_title)
                time.sleep(1)  # brief pause between tracks
            else:
                logger.info(f"{OFF}Demo. Skipping")
            count = count + 1
        if failed_tracks:
            logger.warning(
                f"{YELLOW}{len(failed_tracks)} track(s) failed: "
                + ", ".join(failed_tracks)
            )
        logger.info(f"{GREEN}Completed")

    def download_track(self):
        parse = self.client.get_track_url(self.item_id, self.quality)

        if self.cancel_event and self.cancel_event.is_set():
            return

        if "sample" not in parse and parse["sampling_rate"]:
            meta = self.client.get_track_meta(self.item_id)
            track_title = _get_title(meta)
            artist = _safe_get(meta, "performer", "name")
            logger.info(f"\n{YELLOW}Downloading: {artist} - {track_title}")
            logger.info(f"[TRACK_START] 01. {track_title}")
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
                meta, track_title, bit_depth, sampling_rate
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
        else:
            logger.info(f"{OFF}Demo. Skipping")
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
            logger.info(f"{OFF}Track not available for download")
            return

        if multiple:
            root_dir = os.path.join(root_dir, f"Disc {multiple}")
            os.makedirs(root_dir, exist_ok=True)

        filename = os.path.join(root_dir, f".{tmp_count:02}.tmp")

        # Determine the filename
        track_title = track_metadata.get("title")
        artist = _safe_get(track_metadata, "performer", "name")
        filename_attr = self._get_filename_attr(artist, track_metadata, track_title)

        # track_format is a format string
        # e.g. '{tracknumber}. {artist} - {tracktitle}'
        formatted_path = sanitize_filename(self.track_format.format(**filename_attr))
        final_file = os.path.join(root_dir, formatted_path)[:250] + extension

        if os.path.isfile(final_file):
            logger.info(f"{OFF}{track_title} was already downloaded")
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
                tqdm_download(url_fn, filename, filename, cancel_event=self.cancel_event)
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
            )
        except Exception as e:
            logger.error(f"{RED}Error tagging the file: {e}", exc_info=True)

    @staticmethod
    def _get_filename_attr(artist, track_metadata, track_title):
        return {
            "artist": artist,
            "albumartist": _safe_get(
                track_metadata, "album", "artist", "name", default=artist
            ),
            "bit_depth": track_metadata["maximum_bit_depth"],
            "sampling_rate": track_metadata["maximum_sampling_rate"],
            "tracktitle": track_title,
            "version": track_metadata.get("version"),
            "tracknumber": f"{track_metadata['track_number']:02}",
        }

    @staticmethod
    def _get_track_attr(meta, track_title, bit_depth, sampling_rate):
        return {
            "album": sanitize_filename(meta["album"]["title"]),
            "artist": sanitize_filename(meta["album"]["artist"]["name"]),
            "tracktitle": track_title,
            "year": meta["album"]["release_date_original"].split("-")[0],
            "bit_depth": bit_depth,
            "sampling_rate": sampling_rate,
        }

    @staticmethod
    def _get_album_attr(meta, album_title, file_format, bit_depth, sampling_rate):
        return {
            "artist": sanitize_filename(meta["artist"]["name"]),
            "album": sanitize_filename(album_title),
            "year": meta["release_date_original"].split("-")[0],
            "format": file_format,
            "bit_depth": bit_depth,
            "sampling_rate": sampling_rate,
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


def _dl_streaming(url, fname, desc, headers, cancel_event=None):
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
    r.close()

    if total > 0 and written < total:
        raise IOError(f"Streaming incomplete: {written}/{total}")
    if written == 0:
        raise IOError("Streaming got 0 bytes")
    return written


def _dl_non_streaming(url, fname, desc, headers, cancel_event=None):
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
    return len(data)


def _dl_urllib(url, fname, desc, headers, cancel_event=None):
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

    if total > 0 and written < total:
        raise IOError(f"urllib incomplete: {written}/{total}")
    if written == 0:
        raise IOError("urllib got 0 bytes")
    return written


def tqdm_download(url_getter, fname, desc, max_retries=2, cancel_event=None):
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

    for attempt in range(max_retries):
        if cancel_event and cancel_event.is_set():
            return
        url = url_getter() if callable(url_getter) else url_getter
        strat_name, strat_fn = strategies[min(attempt, len(strategies) - 1)]

        try:
            logger.debug(f"[dl] attempt {attempt} strategy={strat_name}")
            strat_fn(url, fname, desc, headers, cancel_event=cancel_event)
            return  # Success
        except Exception as e:
            logger.debug(f"[dl] {strat_name} failed: {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                wait = 1
                logger.debug(
                    f"[dl] waiting {wait}s before retry {attempt + 1}/{max_retries}..."
                )
                time.sleep(wait)
            else:
                raise ConnectionError(
                    f"File download failed after {max_retries} attempts "
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
