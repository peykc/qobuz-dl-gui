import re
import os
import logging

from mutagen.flac import FLAC, Picture
import mutagen.id3 as id3
from mutagen.id3 import ID3NoHeaderError
from qobuz_dl.utils import flac_fix_md5s, get_album_artist

logger = logging.getLogger(__name__)


# unicode symbols
COPYRIGHT, PHON_COPYRIGHT = "\u2117", "\u00a9"
# if a metadata block exceeds this, mutagen will raise error
# and the file won't be tagged
FLAC_MAX_BLOCKSIZE = 16777215

ID3_LEGEND = {
    "album": id3.TALB,
    "albumartist": id3.TPE2,
    "artist": id3.TPE1,
    "comment": id3.COMM,
    "composer": id3.TCOM,
    "copyright": id3.TCOP,
    "date": id3.TDAT,
    "genre": id3.TCON,
    "isrc": id3.TSRC,
    "mediatype": id3.TMED,
    "itunesadvisory": id3.TXXX,
    "barcode": id3.TXXX,
    "label": id3.TPUB,
    "performer": id3.TOPE,
    "title": id3.TIT2,
    "year": id3.TYER,
}

_DEFAULT_TAG_OPTIONS = {
    "no_album_artist_tag": False,
    "no_album_title_tag": False,
    "no_track_artist_tag": False,
    "no_track_title_tag": False,
    "no_release_date_tag": False,
    "no_media_type_tag": False,
    "no_genre_tag": False,
    "no_track_number_tag": False,
    "no_track_total_tag": False,
    "no_disc_number_tag": False,
    "no_disc_total_tag": False,
    "no_composer_tag": False,
    "no_explicit_tag": False,
    "no_copyright_tag": False,
    "no_label_tag": False,
    "no_upc_tag": False,
    "no_isrc_tag": False,
    "fix_md5s": False,
}


def _resolve_tag_options(tag_options):
    if not tag_options:
        return dict(_DEFAULT_TAG_OPTIONS)
    merged = dict(_DEFAULT_TAG_OPTIONS)
    for key in _DEFAULT_TAG_OPTIONS:
        if isinstance(tag_options, dict) and key in tag_options:
            merged[key] = bool(tag_options[key])
        elif hasattr(tag_options, key):
            merged[key] = bool(getattr(tag_options, key))
    return merged


def _get_title(track_dict):
    title = track_dict["title"]
    version = track_dict.get("version")
    if version:
        title = f"{title} ({version})"
    # for classical works
    if track_dict.get("work"):
        title = f"{track_dict['work']}: {title}"

    return title


def _format_copyright(s: str) -> str:
    if s:
        s = s.replace("(P)", PHON_COPYRIGHT)
        s = s.replace("(C)", COPYRIGHT)
    return s


def _format_genres(genres: list) -> str:
    """Fixes the weirdly formatted genre lists returned by the API.
    >>> g = ['Pop/Rock', 'Pop/Rock→Rock', 'Pop/Rock→Rock→Alternatif et Indé']
    >>> _format_genres(g)
    'Pop, Rock, Alternatif et Indé'
    """
    genres = re.findall(r"([^\u2192\/]+)", "/".join(genres))
    no_repeats = []
    [no_repeats.append(g) for g in genres if g not in no_repeats]
    return ", ".join(no_repeats)


def _embed_flac_img(root_dir, audio: FLAC):
    emb_image = os.path.join(root_dir, "cover.jpg")
    multi_emb_image = os.path.join(
        os.path.abspath(os.path.join(root_dir, os.pardir)), "cover.jpg"
    )
    if os.path.isfile(emb_image):
        cover_image = emb_image
    else:
        cover_image = multi_emb_image

    try:
        # rest of the metadata still gets embedded
        # when the image size is too big
        if os.path.getsize(cover_image) > FLAC_MAX_BLOCKSIZE:
            raise Exception(
                "downloaded cover size too large to embed. "
                "turn off `og_cover` to avoid error"
            )

        image = Picture()
        image.type = 3
        image.mime = "image/jpeg"
        image.desc = "cover"
        with open(cover_image, "rb") as img:
            image.data = img.read()
        audio.add_picture(image)
    except Exception as e:
        logger.error(f"Error embedding image: {e}", exc_info=True)


def _embed_id3_img(root_dir, audio: id3.ID3):
    emb_image = os.path.join(root_dir, "cover.jpg")
    multi_emb_image = os.path.join(
        os.path.abspath(os.path.join(root_dir, os.pardir)), "cover.jpg"
    )
    if os.path.isfile(emb_image):
        cover_image = emb_image
    else:
        cover_image = multi_emb_image

    with open(cover_image, "rb") as cover:
        audio.add(id3.APIC(3, "image/jpeg", 3, "", cover.read()))


# Use KeyError catching instead of dict.get to avoid empty tags
def tag_flac(
    filename,
    root_dir,
    final_name,
    d: dict,
    album,
    istrack=True,
    em_image=False,
    tag_options=None,
):
    """
    Tag a FLAC file

    :param str filename: FLAC file path
    :param str root_dir: Root dir used to get the cover art
    :param str final_name: Final name of the FLAC file (complete path)
    :param dict d: Track dictionary from Qobuz_client
    :param dict album: Album dictionary from Qobuz_client
    :param bool istrack
    :param bool em_image: Embed cover art into file
    """
    audio = FLAC(filename)

    options = _resolve_tag_options(tag_options)
    qobuz_item = d
    qobuz_album = d.get("album", {}) if istrack else album
    release_date = qobuz_album.get("release_date_original", "")

    if not options["no_track_title_tag"]:
        audio["TITLE"] = _get_title(qobuz_item)
    if not options["no_track_number_tag"]:
        audio["TRACKNUMBER"] = str(qobuz_item.get("track_number", 1))
    if not options["no_track_total_tag"]:
        audio["TRACKTOTAL"] = str(qobuz_album.get("tracks_count", 1))
    if not options["no_disc_number_tag"]:
        audio["DISCNUMBER"] = str(qobuz_item.get("media_number", 1))
    if not options["no_disc_total_tag"]:
        audio["DISCTOTAL"] = str(qobuz_album.get("media_count", 1))
    if not options["no_composer_tag"]:
        composer = qobuz_item.get("composer", {}).get("name")
        if composer:
            audio["COMPOSER"] = composer
    if not options["no_track_artist_tag"]:
        artist_ = qobuz_item.get("performer", {}).get("name")
        audio["ARTIST"] = artist_ or qobuz_album.get("artist", {}).get("name", "")
    if not options["no_genre_tag"]:
        genres = qobuz_album.get("genres_list") or []
        if genres:
            audio["GENRE"] = _format_genres(genres)
    if not options["no_album_artist_tag"]:
        album_artist = get_album_artist(qobuz_album)
        if album_artist:
            audio["ALBUMARTIST"] = album_artist
    if not options["no_album_title_tag"]:
        audio["ALBUM"] = qobuz_album.get("title", "")
    if not options["no_release_date_tag"] and release_date:
        audio["DATE"] = release_date
    if not options["no_copyright_tag"]:
        copyright_v = _format_copyright(qobuz_album.get("copyright") or "n/a")
        if copyright_v:
            audio["COPYRIGHT"] = copyright_v
    if not options["no_label_tag"]:
        label = qobuz_album.get("label", {}).get("name", "")
        if label:
            audio["LABEL"] = label
    if not options["no_media_type_tag"]:
        media_type = (qobuz_album.get("product_type") or "").upper()
        if media_type:
            audio["MEDIATYPE"] = media_type
    if not options["no_upc_tag"]:
        upc = qobuz_album.get("upc", "")
        if upc:
            audio["BARCODE"] = upc
    if not options["no_isrc_tag"]:
        isrc = qobuz_item.get("isrc", "")
        if isrc:
            audio["ISRC"] = isrc
    if not options["no_explicit_tag"]:
        explicit = bool(
            qobuz_item.get("parental_warning")
            or qobuz_item.get("parental_advisory")
            or qobuz_item.get("explicit")
            or qobuz_album.get("parental_warning")
            or qobuz_album.get("parental_advisory")
            or qobuz_album.get("explicit")
        )
        audio["ITUNESADVISORY"] = "1" if explicit else "0"

    if em_image:
        _embed_flac_img(root_dir, audio)

    audio.save()
    os.rename(filename, final_name)
    if options["fix_md5s"]:
        flac_fix_md5s(final_name)


def tag_mp3(
    filename,
    root_dir,
    final_name,
    d,
    album,
    istrack=True,
    em_image=False,
    tag_options=None,
):
    """
    Tag an mp3 file

    :param str filename: mp3 temporary file path
    :param str root_dir: Root dir used to get the cover art
    :param str final_name: Final name of the mp3 file (complete path)
    :param dict d: Track dictionary from Qobuz_client
    :param bool istrack
    :param bool em_image: Embed cover art into file
    """

    try:
        audio = id3.ID3(filename)
    except ID3NoHeaderError:
        audio = id3.ID3()

    options = _resolve_tag_options(tag_options)
    qobuz_item = d
    qobuz_album = d.get("album", {}) if istrack else album
    release_date = qobuz_album.get("release_date_original", "")

    tags = dict()
    if not options["no_track_title_tag"]:
        tags["title"] = _get_title(qobuz_item)
    if not options["no_album_title_tag"]:
        tags["album"] = qobuz_album.get("title", "")
    if not options["no_track_artist_tag"]:
        artist_ = qobuz_item.get("performer", {}).get("name")
        tags["artist"] = artist_ or qobuz_album.get("artist", {}).get("name", "")
    if not options["no_album_artist_tag"]:
        tags["albumartist"] = get_album_artist(qobuz_album)
    if not options["no_composer_tag"]:
        tags["composer"] = qobuz_item.get("composer", {}).get("name", "")
    if not options["no_release_date_tag"] and release_date:
        tags["date"] = release_date
        tags["year"] = release_date[:4]
    if not options["no_genre_tag"]:
        genres = qobuz_album.get("genres_list") or []
        if genres:
            tags["genre"] = _format_genres(genres)
    if not options["no_copyright_tag"]:
        tags["copyright"] = _format_copyright(qobuz_album.get("copyright", ""))
    if not options["no_label_tag"]:
        tags["label"] = qobuz_album.get("label", {}).get("name", "")
    if not options["no_isrc_tag"]:
        tags["isrc"] = qobuz_item.get("isrc", "")
    if not options["no_media_type_tag"]:
        tags["mediatype"] = (qobuz_album.get("product_type") or "").upper()
    if not options["no_upc_tag"]:
        tags["barcode"] = qobuz_album.get("upc", "")
    if not options["no_explicit_tag"]:
        explicit = bool(
            qobuz_item.get("parental_warning")
            or qobuz_item.get("parental_advisory")
            or qobuz_item.get("explicit")
            or qobuz_album.get("parental_warning")
            or qobuz_album.get("parental_advisory")
            or qobuz_album.get("explicit")
        )
        tags["itunesadvisory"] = "1" if explicit else "0"

    track_no = str(qobuz_item.get("track_number", 1))
    track_total = str(qobuz_album.get("tracks_count", 1))
    disc_no = str(qobuz_item.get("media_number", 1))
    disc_total = str(qobuz_album.get("media_count", 1))
    if not options["no_track_number_tag"] and not options["no_track_total_tag"]:
        audio["TRCK"] = id3.TRCK(encoding=3, text=f"{track_no}/{track_total}")
    elif not options["no_track_number_tag"]:
        audio["TRCK"] = id3.TRCK(encoding=3, text=track_no)
    if not options["no_disc_number_tag"] and not options["no_disc_total_tag"]:
        audio["TPOS"] = id3.TPOS(encoding=3, text=f"{disc_no}/{disc_total}")
    elif not options["no_disc_number_tag"]:
        audio["TPOS"] = id3.TPOS(encoding=3, text=disc_no)

    # write metadata in `tags` to file
    for k, v in tags.items():
        if not v:
            continue
        id3tag = ID3_LEGEND[k]
        if id3tag is id3.TXXX:
            audio.add(id3.TXXX(encoding=3, desc=k.upper(), text=str(v)))
        else:
            audio[id3tag.__name__] = id3tag(encoding=3, text=v)

    if em_image:
        _embed_id3_img(root_dir, audio)

    audio.save(filename, v2_version=3)
    os.rename(filename, final_name)


def set_itunes_explicit_from_lyrics_content(audio_path: str, lyrics_text: str) -> bool:
    """If lyric text matches the explicit-vocabulary heuristic, set ITUNESADVISORY to 1."""
    from qobuz_dl import lyrics as lyrics_mod

    if not lyrics_mod.lyrics_text_indicates_explicit(lyrics_text or ""):
        return False
    return _set_audio_itunes_explicit_one(audio_path)


def _set_audio_itunes_explicit_one(audio_path: str) -> bool:
    ext = os.path.splitext(audio_path)[1].lower()
    try:
        if ext == ".flac":
            audio = FLAC(audio_path)
            audio["ITUNESADVISORY"] = "1"
            audio.save()
            return True
        if ext == ".mp3":
            try:
                audio = id3.ID3(audio_path)
            except ID3NoHeaderError:
                logger.warning("No ID3 header; skipping explicit tag update: %s", audio_path)
                return False
            audio.delall("TXXX:ITUNESADVISORY")
            audio.add(id3.TXXX(encoding=3, desc="ITUNESADVISORY", text="1"))
            audio.save(audio_path, v2_version=3)
            return True
    except Exception as e:
        logger.warning("Could not set ITUNESADVISORY from lyrics: %s", e)
    return False
