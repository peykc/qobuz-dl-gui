import re
import string
import os
import logging
import subprocess
import time
from typing import Optional, Union

from mutagen.mp3 import EasyMP3
from mutagen.flac import FLAC

logger = logging.getLogger(__name__)

EXTENSIONS = (".mp3", ".flac")


class PartialFormatter(string.Formatter):
    def __init__(self, missing="n/a", bad_fmt="n/a"):
        self.missing, self.bad_fmt = missing, bad_fmt

    def get_field(self, field_name, args, kwargs):
        try:
            val = super(PartialFormatter, self).get_field(field_name, args, kwargs)
        except (KeyError, AttributeError, TypeError):
            val = None, field_name
        return val

    def format_field(self, value, spec):
        if not value:
            return self.missing
        try:
            return super(PartialFormatter, self).format_field(value, spec)
        except ValueError:
            if self.bad_fmt:
                return self.bad_fmt
            raise


def make_m3u(pl_directory):
    track_list = ["#EXTM3U"]
    rel_folder = os.path.basename(os.path.normpath(pl_directory))
    pl_name = rel_folder + ".m3u"
    for local, dirs, files in os.walk(pl_directory):
        dirs.sort()
        audio_rel_files = [
            os.path.join(os.path.basename(os.path.normpath(local)), file_)
            for file_ in files
            if os.path.splitext(file_)[-1] in EXTENSIONS
        ]
        audio_files = [
            os.path.abspath(os.path.join(local, file_))
            for file_ in files
            if os.path.splitext(file_)[-1] in EXTENSIONS
        ]
        if not audio_files or len(audio_files) != len(audio_rel_files):
            continue

        for audio_rel_file, audio_file in zip(audio_rel_files, audio_files):
            try:
                pl_item = (
                    EasyMP3(audio_file) if ".mp3" in audio_file else FLAC(audio_file)
                )
                title = pl_item["TITLE"][0]
                artist = pl_item["ARTIST"][0]
                length = int(pl_item.info.length)
                index = "#EXTINF:{}, {} - {}\n{}".format(
                    length, artist, title, audio_rel_file
                )
            except:  # noqa
                continue
            track_list.append(index)

    if len(track_list) > 1:
        with open(os.path.join(pl_directory, pl_name), "w", encoding="utf-8") as pl:
            pl.write("\n\n".join(track_list))


def get_album_artist(qobuz_album: dict) -> str:
    """Get the album's main artist(s) with sane fallback behavior."""
    try:
        artists = qobuz_album.get("artists") or []
        if not artists:
            return qobuz_album.get("artist", {}).get("name", "")

        main_artists = [a for a in artists if "main-artist" in (a.get("roles") or [])]
        if not main_artists:
            return qobuz_album.get("artist", {}).get("name", "")
        if len(main_artists) == 1:
            return main_artists[0].get("name", "") or qobuz_album.get("artist", {}).get(
                "name", ""
            )

        names = [a.get("name", "").strip() for a in main_artists if a.get("name")]
        if not names:
            return qobuz_album.get("artist", {}).get("name", "")
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " & " + names[-1]
    except Exception:
        return qobuz_album.get("artist", {}).get("name", "")


def flac_fix_md5s(flac_file_path: str) -> bool:
    """Recompute FLAC MD5 checksum in-place using `flac -sf8`."""
    if not os.path.isfile(flac_file_path):
        logger.error("File not found for MD5 fix: %s", flac_file_path)
        return False

    try:
        result = subprocess.run(
            ["flac", "-sf8", flac_file_path],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("FLAC binary not found; skipping MD5 fix.")
        return False
    except Exception as exc:
        logger.warning("FLAC MD5 fix failed to start: %s", exc)
        return False

    if result.returncode == 0:
        if result.stderr.strip():
            logger.debug(result.stderr.strip())
        return True

    logger.warning(
        "FLAC MD5 fix failed (%s): %s", result.returncode, result.stderr.strip()
    )
    return False


def smart_discography_filter(
    contents: list, save_space: bool = False, skip_extras: bool = False
) -> list:
    """When downloading some artists' discography, many random and spam-like
    albums can get downloaded. This helps filter those out to just get the good stuff.

    This function removes:
        * albums by other artists, which may contain a feature from the requested artist
        * duplicate albums in different qualities
        * (optionally) removes collector's, deluxe, live albums

    :param list contents: contents returned by qobuz API
    :param bool save_space: choose highest bit depth, lowest sampling rate
    :param bool remove_extras: remove albums with extra material (i.e. live, deluxe,...)
    :returns: filtered items list
    """

    # for debugging
    def print_album(album: dict) -> None:
        logger.debug(
            f"{album['title']} - {album.get('version', '~~')} "
            "({album['maximum_bit_depth']}/{album['maximum_sampling_rate']}"
            " by {album['artist']['name']}) {album['id']}"
        )

    TYPE_REGEXES = {
        "remaster": r"(?i)(re)?master(ed)?",
        "extra": r"(?i)(anniversary|deluxe|live|collector|demo|expanded)",
    }

    def is_type(album_t: str, album: dict) -> bool:
        """Check if album is of type `album_t`"""
        version = album.get("version", "")
        title = album.get("title", "")
        regex = TYPE_REGEXES[album_t]
        return re.search(regex, f"{title} {version}") is not None

    def essence(album: dict) -> str:
        """Ignore text in parens/brackets, return all lowercase.
        Used to group two albums that may be named similarly, but not exactly
        the same.
        """
        r = re.match(r"([^\(]+)(?:\s*[\(\[][^\)][\)\]])*", album)
        return r.group(1).strip().lower()

    requested_artist = contents[0]["name"]
    items = []
    for item in contents:
        items.extend(item["albums"]["items"])

    # use dicts to group duplicate albums together by title
    title_grouped = dict()
    for item in items:
        title_ = essence(item["title"])
        if title_ not in title_grouped:  # ?
            #            if (t := essence(item["title"])) not in title_grouped:
            title_grouped[title_] = []
        title_grouped[title_].append(item)

    items = []
    for albums in title_grouped.values():
        best_bit_depth = max(a["maximum_bit_depth"] for a in albums)
        get_best = min if save_space else max
        best_sampling_rate = get_best(
            a["maximum_sampling_rate"]
            for a in albums
            if a["maximum_bit_depth"] == best_bit_depth
        )
        remaster_exists = any(is_type("remaster", a) for a in albums)

        def is_valid(album: dict) -> bool:
            return (
                album["maximum_bit_depth"] == best_bit_depth
                and album["maximum_sampling_rate"] == best_sampling_rate
                and album["artist"]["name"] == requested_artist
                and not (  # states that are not allowed
                    (remaster_exists and not is_type("remaster", album))
                    or (skip_extras and is_type("extra", album))
                )
            )

        filtered = tuple(filter(is_valid, albums))
        # most of the time, len is 0 or 1.
        # if greater, it is a complete duplicate,
        # so it doesn't matter which is chosen
        if len(filtered) >= 1:
            items.append(filtered[0])

    return items


def format_duration(duration):
    return time.strftime("%H:%M:%S", time.gmtime(duration))


def normalize_sampling_rate_hz(value) -> Optional[float]:
    """Return sample rate in Hz.

    Qobuz ``maximum_sampling_rate`` is most often Hz (44100, 96000).
    Payloads sometimes use canonical kHz (44.1, 48, 96, 192) or fractional
    megahertz (0.048 → 48000 Hz). Values below ``1`` are scaled as MHz fractions;
    ``1 .. 1000`` (exclusive of full Hz ladder) scale as kilohertz.
    """

    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    if f < 1:
        f *= 1_000_000
        return f
    if f < 1000:
        f *= 1000
    return f


def sampling_rate_khz_for_chip(value) -> Union[int, float, None]:
    """Numeric catalog rate in kHz for UI chips (queue cards, resolves without ``…kHz`` typos).

    Handles the same scales as ``normalize_sampling_rate_hz``. Returns rounded ``int``
    when visually integral (96, 48), otherwise a bounded float for 44.1 / 176.4.
    """

    hz = normalize_sampling_rate_hz(value)
    if hz is None:
        return None
    k = hz / 1000.0
    nk = round(k, 12)
    if abs(nk - round(nk)) < 1e-6:
        return int(round(nk))
    return round(nk + 1e-12, 4)


def format_sampling_rate_specs(value) -> str:
    """Display string suitable for GUIs / placeholders (e.g. ``44100 Hz (44.1 kHz)``)."""

    hz = normalize_sampling_rate_hz(value)
    if hz is None:
        return "unknown"
    hz_r = round(hz)
    khz = hz / 1000.0
    if abs(khz - round(khz)) < 1e-6:
        ks = str(int(round(khz)))
    else:
        ks = f"{khz:.4g}"
    return f"{hz_r} Hz ({ks} kHz)"


def create_and_return_dir(directory):
    fix = os.path.normpath(directory)
    os.makedirs(fix, exist_ok=True)
    return fix


def get_url_info(url):
    """Returns the type of the url and the id.

    Compatible with urls of the form:
        https://www.qobuz.com/us-en/{type}/{name}/{id}
        https://open.qobuz.com/{type}/{id}
        https://play.qobuz.com/{type}/{id}
        /us-en/{type}/-/{id}
    """

    r = re.search(
        r"(?:https:\/\/(?:w{3}|open|play)\.qobuz\.com)?(?:\/[a-z]{2}-[a-z]{2})"
        r"?\/(album|artist|track|playlist|label)(?:\/[-\w\d]+)?\/([\w\d]+)",
        url,
    )
    return r.groups()
