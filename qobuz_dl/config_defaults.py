from qobuz_dl.downloader import (
    DEFAULT_FOLDER,
    DEFAULT_MULTIPLE_DISC_TRACK,
    DEFAULT_TRACK,
)


TAG_DISABLE_OPTIONS = (
    "no_album_artist_tag",
    "no_album_title_tag",
    "no_track_artist_tag",
    "no_track_title_tag",
    "no_release_date_tag",
    "no_media_type_tag",
    "no_genre_tag",
    "no_track_number_tag",
    "no_track_total_tag",
    "no_disc_number_tag",
    "no_disc_total_tag",
    "no_composer_tag",
    "no_explicit_tag",
    "no_copyright_tag",
    "no_label_tag",
    "no_upc_tag",
    "no_isrc_tag",
)


def apply_common_defaults(defaults, *, no_database: str) -> None:
    """Populate config defaults shared by CLI setup and GUI setup."""
    defaults["default_limit"] = "20"
    defaults["no_m3u"] = "false"
    defaults["albums_only"] = "false"
    defaults["no_fallback"] = "false"
    defaults["og_cover"] = "false"
    defaults["embed_art"] = "false"
    defaults["lyrics_enabled"] = "false"
    defaults["lyrics_embed_metadata"] = "false"
    defaults["no_cover"] = "false"
    defaults["no_database"] = no_database
    defaults["folder_format"] = DEFAULT_FOLDER
    defaults["track_format"] = DEFAULT_TRACK
    defaults["smart_discography"] = "false"
    defaults["fix_md5s"] = "false"
    defaults["multiple_disc_prefix"] = "Disc"
    defaults["multiple_disc_one_dir"] = "false"
    defaults["multiple_disc_track_format"] = DEFAULT_MULTIPLE_DISC_TRACK
    defaults["max_workers"] = "1"
    defaults["delay_seconds"] = "0"
    defaults["segmented_fallback"] = "true"
    defaults["no_credits"] = "false"
    defaults["native_lang"] = "false"
    for key in TAG_DISABLE_OPTIONS:
        defaults[key] = "false"
    defaults["tag_title_from_track_format"] = "true"
    defaults["tag_album_from_folder_format"] = "true"
