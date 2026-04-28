import configparser
import hashlib
import logging
import glob
import os
import sys

from qobuz_dl.bundle import Bundle
from qobuz_dl.color import GREEN, RED, YELLOW
from qobuz_dl.commands import qobuz_dl_args
from qobuz_dl.core import QobuzDL
from qobuz_dl.downloader import (
    DEFAULT_FOLDER,
    DEFAULT_MULTIPLE_DISC_TRACK,
    DEFAULT_TRACK,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)

if os.name == "nt":
    OS_CONFIG = os.environ.get("APPDATA")
else:
    OS_CONFIG = os.path.join(os.environ["HOME"], ".config")

CONFIG_PATH = os.path.join(OS_CONFIG, "qobuz-dl")
CONFIG_FILE = os.path.join(CONFIG_PATH, "config.ini")
QOBUZ_DB = os.path.join(CONFIG_PATH, "qobuz_dl.db")


def _reset_config(config_file):
    logging.info(f"{YELLOW}Creating config file: {config_file}")
    config = configparser.ConfigParser()
    config["DEFAULT"]["email"] = input("Enter your email:\n- ")
    password = input("Enter your password\n- ")
    config["DEFAULT"]["password"] = hashlib.md5(password.encode("utf-8")).hexdigest()
    config["DEFAULT"]["default_folder"] = (
        input("Folder for downloads (leave empty for default 'Qobuz Downloads')\n- ")
        or "Qobuz Downloads"
    )
    config["DEFAULT"]["default_quality"] = (
        input(
            "Download quality (5, 6, 7, 27) "
            "[320, LOSSLESS, 24B <96KHZ, 24B >96KHZ]"
            "\n(leave empty for default '6')\n- "
        )
        or "6"
    )
    config["DEFAULT"]["default_limit"] = "20"
    config["DEFAULT"]["no_m3u"] = "false"
    config["DEFAULT"]["albums_only"] = "false"
    config["DEFAULT"]["no_fallback"] = "false"
    config["DEFAULT"]["og_cover"] = "false"
    config["DEFAULT"]["embed_art"] = "false"
    config["DEFAULT"]["lyrics_enabled"] = "false"
    config["DEFAULT"]["no_cover"] = "false"
    config["DEFAULT"]["no_database"] = "false"
    logging.info(f"{YELLOW}Getting tokens. Please wait...")
    bundle = Bundle()
    config["DEFAULT"]["app_id"] = str(bundle.get_app_id())
    config["DEFAULT"]["secrets"] = ",".join(bundle.get_secrets().values())
    config["DEFAULT"]["folder_format"] = DEFAULT_FOLDER
    config["DEFAULT"]["track_format"] = DEFAULT_TRACK
    config["DEFAULT"]["smart_discography"] = "false"
    config["DEFAULT"]["fix_md5s"] = "false"
    config["DEFAULT"]["multiple_disc_prefix"] = "Disc"
    config["DEFAULT"]["multiple_disc_one_dir"] = "false"
    config["DEFAULT"]["multiple_disc_track_format"] = DEFAULT_MULTIPLE_DISC_TRACK
    config["DEFAULT"]["max_workers"] = "1"
    config["DEFAULT"]["delay_seconds"] = "0"
    config["DEFAULT"]["segmented_fallback"] = "true"
    config["DEFAULT"]["no_credits"] = "false"
    config["DEFAULT"]["native_lang"] = "false"
    for key in (
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
    ):
        config["DEFAULT"][key] = "false"
    with open(config_file, "w") as configfile:
        config.write(configfile)
    logging.info(
        f"{GREEN}Config file updated. Edit more options in {config_file}"
        "\nso you don't have to call custom flags every time you run "
        "a qobuz-dl command."
    )


def _remove_leftovers(directory):
    directory = os.path.join(directory, "**", ".*.tmp")
    for i in glob.glob(directory, recursive=True):
        try:
            os.remove(i)
        except:  # noqa
            pass


def _handle_commands(qobuz, arguments):
    try:
        if arguments.command == "dl":
            qobuz.download_list_of_urls(arguments.SOURCE)
        elif arguments.command == "lucky":
            query = " ".join(arguments.QUERY)
            qobuz.lucky_type = arguments.type
            qobuz.lucky_limit = arguments.number
            qobuz.lucky_mode(query)
        else:
            qobuz.interactive_limit = arguments.limit
            qobuz.interactive()

    except KeyboardInterrupt:
        logging.info(
            f"{RED}Interrupted by user\n{YELLOW}Already downloaded items will "
            "be skipped if you try to download the same releases again."
        )

    finally:
        _remove_leftovers(qobuz.directory)


def _initial_checks():
    if not os.path.isdir(CONFIG_PATH) or not os.path.isfile(CONFIG_FILE):
        os.makedirs(CONFIG_PATH, exist_ok=True)
        _reset_config(CONFIG_FILE)

    if len(sys.argv) < 2:
        sys.exit(qobuz_dl_args().print_help())


def main():
    _initial_checks()

    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)

    try:
        email = config["DEFAULT"]["email"]
        password = config["DEFAULT"]["password"]
        default_folder = config["DEFAULT"]["default_folder"]
        default_limit = config["DEFAULT"]["default_limit"]
        default_quality = config["DEFAULT"]["default_quality"]
        no_m3u = config.getboolean("DEFAULT", "no_m3u")
        albums_only = config.getboolean("DEFAULT", "albums_only")
        no_fallback = config.getboolean("DEFAULT", "no_fallback")
        og_cover = config.getboolean("DEFAULT", "og_cover")
        embed_art = config.getboolean("DEFAULT", "embed_art")
        no_cover = config.getboolean("DEFAULT", "no_cover")
        lyrics_enabled = config.getboolean("DEFAULT", "lyrics_enabled", fallback=False)
        no_database = config.getboolean("DEFAULT", "no_database")
        app_id = config["DEFAULT"]["app_id"]
        smart_discography = config.getboolean("DEFAULT", "smart_discography")
        folder_format = config["DEFAULT"]["folder_format"]
        track_format = config["DEFAULT"]["track_format"]
        fix_md5s = config.getboolean("DEFAULT", "fix_md5s", fallback=False)
        multiple_disc_prefix = config.get(
            "DEFAULT", "multiple_disc_prefix", fallback="Disc"
        )
        multiple_disc_one_dir = config.getboolean(
            "DEFAULT", "multiple_disc_one_dir", fallback=False
        )
        multiple_disc_track_format = config.get(
            "DEFAULT",
            "multiple_disc_track_format",
            fallback=DEFAULT_MULTIPLE_DISC_TRACK,
        )
        max_workers = config.getint("DEFAULT", "max_workers", fallback=1)
        delay_seconds = config.getint("DEFAULT", "delay_seconds", fallback=0)
        segmented_fallback = config.getboolean(
            "DEFAULT", "segmented_fallback", fallback=True
        )
        no_credits = config.getboolean("DEFAULT", "no_credits", fallback=False)
        native_lang = config.getboolean("DEFAULT", "native_lang", fallback=False)
        no_album_artist_tag = config.getboolean(
            "DEFAULT", "no_album_artist_tag", fallback=False
        )
        no_album_title_tag = config.getboolean(
            "DEFAULT", "no_album_title_tag", fallback=False
        )
        no_track_artist_tag = config.getboolean(
            "DEFAULT", "no_track_artist_tag", fallback=False
        )
        no_track_title_tag = config.getboolean(
            "DEFAULT", "no_track_title_tag", fallback=False
        )
        no_release_date_tag = config.getboolean(
            "DEFAULT", "no_release_date_tag", fallback=False
        )
        no_media_type_tag = config.getboolean(
            "DEFAULT", "no_media_type_tag", fallback=False
        )
        no_genre_tag = config.getboolean("DEFAULT", "no_genre_tag", fallback=False)
        no_track_number_tag = config.getboolean(
            "DEFAULT", "no_track_number_tag", fallback=False
        )
        no_track_total_tag = config.getboolean(
            "DEFAULT", "no_track_total_tag", fallback=False
        )
        no_disc_number_tag = config.getboolean(
            "DEFAULT", "no_disc_number_tag", fallback=False
        )
        no_disc_total_tag = config.getboolean(
            "DEFAULT", "no_disc_total_tag", fallback=False
        )
        no_composer_tag = config.getboolean(
            "DEFAULT", "no_composer_tag", fallback=False
        )
        no_explicit_tag = config.getboolean(
            "DEFAULT", "no_explicit_tag", fallback=False
        )
        no_copyright_tag = config.getboolean(
            "DEFAULT", "no_copyright_tag", fallback=False
        )
        no_label_tag = config.getboolean("DEFAULT", "no_label_tag", fallback=False)
        no_upc_tag = config.getboolean("DEFAULT", "no_upc_tag", fallback=False)
        no_isrc_tag = config.getboolean("DEFAULT", "no_isrc_tag", fallback=False)

        secrets = [
            secret for secret in config["DEFAULT"]["secrets"].split(",") if secret
        ]
        arguments = qobuz_dl_args(
            default_quality, default_limit, default_folder
        ).parse_args()
    except (KeyError, UnicodeDecodeError, configparser.Error) as error:
        arguments = qobuz_dl_args().parse_args()
        if not arguments.reset:
            sys.exit(
                f"{RED}Your config file is corrupted: {error}! "
                "Run 'qobuz-dl -r' to fix this."
            )

    if arguments.reset:
        sys.exit(_reset_config(CONFIG_FILE))

    if arguments.show_config:
        print(f"Configuation: {CONFIG_FILE}\nDatabase: {QOBUZ_DB}\n---")
        with open(CONFIG_FILE, "r") as f:
            print(f.read())
        sys.exit()

    if arguments.purge:
        try:
            os.remove(QOBUZ_DB)
        except FileNotFoundError:
            pass
        sys.exit(f"{GREEN}The database was deleted.")

    qobuz = QobuzDL(
        arguments.directory,
        arguments.quality,
        arguments.embed_art or embed_art,
        ignore_singles_eps=arguments.albums_only or albums_only,
        no_m3u_for_playlists=arguments.no_m3u or no_m3u,
        quality_fallback=not arguments.no_fallback or not no_fallback,
        cover_og_quality=arguments.og_cover or og_cover,
        no_cover=arguments.no_cover or no_cover,
        lyrics_enabled=arguments.lyrics or lyrics_enabled,
        downloads_db=None if no_database or arguments.no_db else QOBUZ_DB,
        folder_format=arguments.folder_format or folder_format,
        track_format=arguments.track_format or track_format,
        smart_discography=arguments.smart_discography or smart_discography,
        fix_md5s=arguments.fix_md5s or fix_md5s,
        multiple_disc_prefix=arguments.multiple_disc_prefix or multiple_disc_prefix,
        multiple_disc_one_dir=arguments.multiple_disc_one_dir or multiple_disc_one_dir,
        multiple_disc_track_format=arguments.multiple_disc_track_format
        or multiple_disc_track_format,
        max_workers=arguments.max_workers or max_workers,
        delay_seconds=arguments.delay or delay_seconds,
        segmented_fallback=not arguments.no_segmented_fallback and segmented_fallback,
        no_credits=arguments.no_credits or no_credits,
        native_lang=arguments.native_lang or native_lang,
        no_album_artist_tag=arguments.no_album_artist_tag or no_album_artist_tag,
        no_album_title_tag=arguments.no_album_title_tag or no_album_title_tag,
        no_track_artist_tag=arguments.no_track_artist_tag or no_track_artist_tag,
        no_track_title_tag=arguments.no_track_title_tag or no_track_title_tag,
        no_release_date_tag=arguments.no_release_date_tag or no_release_date_tag,
        no_media_type_tag=arguments.no_media_type_tag or no_media_type_tag,
        no_genre_tag=arguments.no_genre_tag or no_genre_tag,
        no_track_number_tag=arguments.no_track_number_tag or no_track_number_tag,
        no_track_total_tag=arguments.no_track_total_tag or no_track_total_tag,
        no_disc_number_tag=arguments.no_disc_number_tag or no_disc_number_tag,
        no_disc_total_tag=arguments.no_disc_total_tag or no_disc_total_tag,
        no_composer_tag=arguments.no_composer_tag or no_composer_tag,
        no_explicit_tag=arguments.no_explicit_tag or no_explicit_tag,
        no_copyright_tag=arguments.no_copyright_tag or no_copyright_tag,
        no_label_tag=arguments.no_label_tag or no_label_tag,
        no_upc_tag=arguments.no_upc_tag or no_upc_tag,
        no_isrc_tag=arguments.no_isrc_tag or no_isrc_tag,
    )
    qobuz.initialize_client(email, password, app_id, secrets)

    _handle_commands(qobuz, arguments)


if __name__ == "__main__":
    sys.exit(main())
