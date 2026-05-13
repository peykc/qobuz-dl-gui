import configparser
import os
import shutil
import sys

from flask import jsonify


def _resolve(value):
    return value() if callable(value) else value


def _status_config_data(config_file: str) -> dict:
    if not os.path.isfile(config_file):
        return {}
    cfg = configparser.ConfigParser()
    cfg.read(config_file)
    try:
        defaults = cfg["DEFAULT"]
        return {
            "email": defaults.get("email", ""),
            "default_folder": defaults.get("default_folder", "Qobuz Downloads"),
            "default_quality": defaults.get("default_quality", "27"),
            "no_m3u": defaults.get("no_m3u", "false"),
            "albums_only": defaults.get("albums_only", "false"),
            "no_fallback": defaults.get("no_fallback", "false"),
            "og_cover": defaults.get("og_cover", "false"),
            "embed_art": defaults.get("embed_art", "false"),
            "no_cover": defaults.get("no_cover", "false"),
            "lyrics_enabled": defaults.get("lyrics_enabled", "false"),
            "lyrics_embed_metadata": defaults.get("lyrics_embed_metadata", "false"),
            "no_database": defaults.get("no_database", "false"),
            "smart_discography": defaults.get("smart_discography", "false"),
            "fix_md5s": defaults.get("fix_md5s", "false"),
            "multiple_disc_prefix": defaults.get("multiple_disc_prefix", "Disc"),
            "multiple_disc_one_dir": defaults.get("multiple_disc_one_dir", "false"),
            "multiple_disc_track_format": defaults.get(
                "multiple_disc_track_format",
                "{disc_number_unpadded}{track_number} - {tracktitle}",
            ),
            "max_workers": defaults.get("max_workers", "1"),
            "delay_seconds": defaults.get("delay_seconds", "0"),
            "segmented_fallback": defaults.get("segmented_fallback", "true"),
            "no_credits": defaults.get("no_credits", "false"),
            "native_lang": defaults.get("native_lang", "false"),
            "folder_format": defaults.get("folder_format", "{artist}/{album}"),
            "track_format": defaults.get(
                "track_format",
                "{tracknumber} - {tracktitle}",
            ),
            "no_album_artist_tag": defaults.get("no_album_artist_tag", "false"),
            "no_album_title_tag": defaults.get("no_album_title_tag", "false"),
            "no_track_artist_tag": defaults.get("no_track_artist_tag", "false"),
            "no_track_title_tag": defaults.get("no_track_title_tag", "false"),
            "no_release_date_tag": defaults.get("no_release_date_tag", "false"),
            "no_media_type_tag": defaults.get("no_media_type_tag", "false"),
            "no_genre_tag": defaults.get("no_genre_tag", "false"),
            "no_track_number_tag": defaults.get("no_track_number_tag", "false"),
            "no_track_total_tag": defaults.get("no_track_total_tag", "false"),
            "no_disc_number_tag": defaults.get("no_disc_number_tag", "false"),
            "no_disc_total_tag": defaults.get("no_disc_total_tag", "false"),
            "no_composer_tag": defaults.get("no_composer_tag", "false"),
            "no_explicit_tag": defaults.get("no_explicit_tag", "false"),
            "no_copyright_tag": defaults.get("no_copyright_tag", "false"),
            "no_label_tag": defaults.get("no_label_tag", "false"),
            "no_upc_tag": defaults.get("no_upc_tag", "false"),
            "no_isrc_tag": defaults.get("no_isrc_tag", "false"),
            "tag_title_from_track_format": defaults.get(
                "tag_title_from_track_format",
                "true",
            ),
            "tag_album_from_folder_format": defaults.get(
                "tag_album_from_folder_format",
                "true",
            ),
        }
    except Exception:
        return {}


def register_status_routes(app, *, config_file, ready) -> None:
    @app.route("/api/status")
    def api_status():
        config_file_value = _resolve(config_file)
        from qobuz_dl.version import __version__ as app_ver

        return jsonify(
            {
                "has_config": os.path.isfile(config_file_value),
                "ready": bool(_resolve(ready)),
                "config": _status_config_data(config_file_value),
                "app_version": app_ver,
                "frozen": getattr(sys, "frozen", False),
                "capabilities": {
                    "flac_cli": bool(shutil.which("flac")),
                    "ffmpeg_cli": bool(shutil.which("ffmpeg")),
                },
            }
        )
