from qobuz_dl.config_paths import QOBUZ_DB


def as_bool(value, default=False):
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    sval = str(value).strip().lower()
    if sval in {"1", "true", "yes", "on"}:
        return True
    if sval in {"0", "false", "no", "off", ""}:
        return False
    return bool(default)


def as_int(value, default=0):
    if value is None or value == "":
        return int(default)
    try:
        return int(value)
    except Exception:
        return int(default)


def build_qobuz_from_config(cfg, overrides=None, downloads_db_path=QOBUZ_DB):
    """Instantiate QobuzDL from config plus optional request overrides."""
    from qobuz_dl.core import QobuzDL

    o = overrides or {}
    directory = o.get("directory") or cfg.get(
        "DEFAULT", "default_folder", fallback="Qobuz Downloads"
    )
    quality = as_int(
        o.get("quality"),
        as_int(cfg.get("DEFAULT", "default_quality", fallback="27"), 27),
    )
    embed_art = as_bool(
        o.get("embed_art"), cfg.getboolean("DEFAULT", "embed_art", fallback=False)
    )
    albums_only = as_bool(
        o.get("albums_only"), cfg.getboolean("DEFAULT", "albums_only", fallback=False)
    )
    no_m3u = as_bool(
        o.get("no_m3u"), cfg.getboolean("DEFAULT", "no_m3u", fallback=False)
    )
    no_fallback = as_bool(
        o.get("no_fallback"),
        cfg.getboolean("DEFAULT", "no_fallback", fallback=False),
    )
    og_cover = as_bool(
        o.get("og_cover"), cfg.getboolean("DEFAULT", "og_cover", fallback=False)
    )
    no_cover = as_bool(
        o.get("no_cover"), cfg.getboolean("DEFAULT", "no_cover", fallback=False)
    )
    lyrics_enabled = as_bool(
        o.get("lyrics_enabled"),
        cfg.getboolean("DEFAULT", "lyrics_enabled", fallback=False),
    )
    lyrics_embed_metadata = as_bool(
        o.get("lyrics_embed_metadata"),
        cfg.getboolean("DEFAULT", "lyrics_embed_metadata", fallback=False),
    )
    no_database = as_bool(
        o.get("no_db"), cfg.getboolean("DEFAULT", "no_database", fallback=True)
    )
    smart_discography = as_bool(
        o.get("smart_discography"),
        cfg.getboolean("DEFAULT", "smart_discography", fallback=False),
    )
    folder_format = o.get("folder_format") or cfg.get(
        "DEFAULT",
        "folder_format",
        fallback="{artist}/{album}",
    )
    track_format = o.get("track_format") or cfg.get(
        "DEFAULT", "track_format", fallback="{tracknumber} - {tracktitle}"
    )
    fix_md5s = as_bool(
        o.get("fix_md5s"), cfg.getboolean("DEFAULT", "fix_md5s", fallback=False)
    )
    multiple_disc_prefix = o.get("multiple_disc_prefix") or cfg.get(
        "DEFAULT", "multiple_disc_prefix", fallback="Disc"
    )
    multiple_disc_one_dir = as_bool(
        o.get("multiple_disc_one_dir"),
        cfg.getboolean("DEFAULT", "multiple_disc_one_dir", fallback=False),
    )
    multiple_disc_track_format = o.get("multiple_disc_track_format") or cfg.get(
        "DEFAULT",
        "multiple_disc_track_format",
        fallback="{disc_number_unpadded}{track_number} - {tracktitle}",
    )
    max_workers = max(
        1,
        as_int(
            o.get("max_workers"),
            as_int(cfg.get("DEFAULT", "max_workers", fallback="1"), 1),
        ),
    )
    delay_seconds = max(
        0,
        as_int(
            o.get("delay_seconds"),
            as_int(cfg.get("DEFAULT", "delay_seconds", fallback="0"), 0),
        ),
    )
    segmented_fallback = as_bool(
        o.get("segmented_fallback"),
        cfg.getboolean("DEFAULT", "segmented_fallback", fallback=True),
    )
    no_credits = as_bool(
        o.get("no_credits"),
        cfg.getboolean("DEFAULT", "no_credits", fallback=False),
    )
    native_lang = as_bool(
        o.get("native_lang"),
        cfg.getboolean("DEFAULT", "native_lang", fallback=False),
    )
    tag_title_from_track_format = as_bool(
        o.get("tag_title_from_track_format"),
        cfg.getboolean("DEFAULT", "tag_title_from_track_format", fallback=True),
    )
    tag_album_from_folder_format = as_bool(
        o.get("tag_album_from_folder_format"),
        cfg.getboolean("DEFAULT", "tag_album_from_folder_format", fallback=True),
    )

    return QobuzDL(
        directory=directory,
        quality=quality,
        embed_art=embed_art,
        ignore_singles_eps=albums_only,
        no_m3u_for_playlists=no_m3u,
        quality_fallback=not no_fallback,
        cover_og_quality=og_cover,
        no_cover=no_cover,
        lyrics_enabled=lyrics_enabled,
        lyrics_embed_metadata=lyrics_embed_metadata,
        downloads_db=None if no_database else downloads_db_path,
        folder_format=folder_format,
        track_format=track_format,
        smart_discography=smart_discography,
        fix_md5s=fix_md5s,
        multiple_disc_prefix=multiple_disc_prefix,
        multiple_disc_one_dir=multiple_disc_one_dir,
        multiple_disc_track_format=multiple_disc_track_format,
        max_workers=max_workers,
        delay_seconds=delay_seconds,
        segmented_fallback=segmented_fallback,
        no_credits=no_credits,
        native_lang=native_lang,
        no_album_artist_tag=as_bool(
            o.get("no_album_artist_tag"),
            cfg.getboolean("DEFAULT", "no_album_artist_tag", fallback=False),
        ),
        no_album_title_tag=as_bool(
            o.get("no_album_title_tag"),
            cfg.getboolean("DEFAULT", "no_album_title_tag", fallback=False),
        ),
        no_track_artist_tag=as_bool(
            o.get("no_track_artist_tag"),
            cfg.getboolean("DEFAULT", "no_track_artist_tag", fallback=False),
        ),
        no_track_title_tag=as_bool(
            o.get("no_track_title_tag"),
            cfg.getboolean("DEFAULT", "no_track_title_tag", fallback=False),
        ),
        no_release_date_tag=as_bool(
            o.get("no_release_date_tag"),
            cfg.getboolean("DEFAULT", "no_release_date_tag", fallback=False),
        ),
        no_media_type_tag=as_bool(
            o.get("no_media_type_tag"),
            cfg.getboolean("DEFAULT", "no_media_type_tag", fallback=False),
        ),
        no_genre_tag=as_bool(
            o.get("no_genre_tag"),
            cfg.getboolean("DEFAULT", "no_genre_tag", fallback=False),
        ),
        no_track_number_tag=as_bool(
            o.get("no_track_number_tag"),
            cfg.getboolean("DEFAULT", "no_track_number_tag", fallback=False),
        ),
        no_track_total_tag=as_bool(
            o.get("no_track_total_tag"),
            cfg.getboolean("DEFAULT", "no_track_total_tag", fallback=False),
        ),
        no_disc_number_tag=as_bool(
            o.get("no_disc_number_tag"),
            cfg.getboolean("DEFAULT", "no_disc_number_tag", fallback=False),
        ),
        no_disc_total_tag=as_bool(
            o.get("no_disc_total_tag"),
            cfg.getboolean("DEFAULT", "no_disc_total_tag", fallback=False),
        ),
        no_composer_tag=as_bool(
            o.get("no_composer_tag"),
            cfg.getboolean("DEFAULT", "no_composer_tag", fallback=False),
        ),
        no_explicit_tag=as_bool(
            o.get("no_explicit_tag"),
            cfg.getboolean("DEFAULT", "no_explicit_tag", fallback=False),
        ),
        no_copyright_tag=as_bool(
            o.get("no_copyright_tag"),
            cfg.getboolean("DEFAULT", "no_copyright_tag", fallback=False),
        ),
        no_label_tag=as_bool(
            o.get("no_label_tag"),
            cfg.getboolean("DEFAULT", "no_label_tag", fallback=False),
        ),
        no_upc_tag=as_bool(
            o.get("no_upc_tag"),
            cfg.getboolean("DEFAULT", "no_upc_tag", fallback=False),
        ),
        no_isrc_tag=as_bool(
            o.get("no_isrc_tag"),
            cfg.getboolean("DEFAULT", "no_isrc_tag", fallback=False),
        ),
        tag_title_from_track_format=tag_title_from_track_format,
        tag_album_from_folder_format=tag_album_from_folder_format,
    )
