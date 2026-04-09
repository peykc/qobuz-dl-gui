import configparser
import logging
import os
import sys

import requests
from bs4 import BeautifulSoup as bso
from pathvalidate import sanitize_filename

from qobuz_dl import downloader, qopy
from qobuz_dl.bundle import Bundle
from qobuz_dl.color import CYAN, DF, OFF, RED, RESET, YELLOW
from qobuz_dl.db import create_db, handle_download_id
from qobuz_dl.exceptions import NonStreamable
from qobuz_dl.utils import (
    PartialFormatter,
    create_and_return_dir,
    format_duration,
    get_url_info,
    make_m3u,
    smart_discography_filter,
)

if os.name == "nt":
    _OS_CONFIG = os.environ.get("APPDATA", "")
else:
    _OS_CONFIG = os.path.join(os.environ.get("HOME", ""), ".config")
CONFIG_FILE = os.path.join(_OS_CONFIG, "qobuz-dl", "config.ini")

WEB_URL = "https://play.qobuz.com/"
ARTISTS_SELECTOR = "td.chartlist-artist > a"
TITLE_SELECTOR = "td.chartlist-name > a"
QUALITIES = {
    5: "5 - MP3",
    6: "6 - 16 bit, 44.1kHz",
    7: "7 - 24 bit, <96kHz",
    27: "27 - 24 bit, >96kHz",
}

logger = logging.getLogger(__name__)


class QobuzDL:
    def __init__(
        self,
        directory="Qobuz Downloads",
        quality=6,
        embed_art=False,
        lucky_limit=1,
        lucky_type="album",
        interactive_limit=20,
        ignore_singles_eps=False,
        no_m3u_for_playlists=False,
        quality_fallback=True,
        cover_og_quality=False,
        no_cover=False,
        downloads_db=None,
        folder_format="{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]",
        track_format="{tracknumber}. {tracktitle}",
        smart_discography=False,
    ):
        self.directory = create_and_return_dir(directory)
        self.quality = quality
        self.embed_art = embed_art
        self.lucky_limit = lucky_limit
        self.lucky_type = lucky_type
        self.interactive_limit = interactive_limit
        self.ignore_singles_eps = ignore_singles_eps
        self.no_m3u_for_playlists = no_m3u_for_playlists
        self.quality_fallback = quality_fallback
        self.cover_og_quality = cover_og_quality
        self.no_cover = no_cover
        self.downloads_db = create_db(downloads_db) if downloads_db else None
        self.folder_format = folder_format
        self.track_format = track_format
        self.smart_discography = smart_discography
        self.cancel_event = None  # set by gui_app to allow inter-track cancellation

    def initialize_client(self, email, pwd, app_id, secrets):
        self.client = qopy.Client(email, pwd, app_id, secrets)
        logger.info(f"{YELLOW}Set max quality: {QUALITIES[int(self.quality)]}\n")

    def initialize_client_with_token(self, user_id, user_auth_token, app_id, secrets):
        self.client = qopy.Client(None, None, app_id, secrets, skip_auth=True)
        self.client.auth_with_token(user_id, user_auth_token)
        logger.info(f"{YELLOW}Set max quality: {QUALITIES[int(self.quality)]}\n")

    def initialize_client_with_oauth(self, code, app_id, secrets, private_key):
        self.client = qopy.Client(None, None, app_id, secrets, skip_auth=True)
        usr_info = self.client.login_with_oauth_code(code, private_key)
        self.oauth_user_id = usr_info.get("user", {}).get("id")
        self.oauth_user_auth_token = usr_info.get("user_auth_token")
        logger.info(f"{YELLOW}Set max quality: {QUALITIES[int(self.quality)]}\n")

    def save_oauth_token_to_config(self, config_file):
        if not hasattr(self, "oauth_user_auth_token") or not self.oauth_user_auth_token:
            return
        config = configparser.ConfigParser()
        config.read(config_file)
        config["DEFAULT"]["user_auth_token"] = self.oauth_user_auth_token
        if hasattr(self, "oauth_user_id") and self.oauth_user_id:
            config["DEFAULT"]["user_id"] = str(self.oauth_user_id)
        config["DEFAULT"]["email"] = ""
        config["DEFAULT"]["password"] = ""
        with open(config_file, "w") as f:
            config.write(f)
        logger.info(f"{GREEN}OAuth token saved to config.")

    def get_tokens(self):
        bundle = Bundle()
        self.app_id = bundle.get_app_id()
        self.secrets = [
            secret for secret in bundle.get_secrets().values() if secret
        ]  # avoid empty fields
        self.private_key = bundle.get_private_key() or ""

    def download_from_id(self, item_id, album=True, alt_path=None):
        if handle_download_id(self.downloads_db, item_id, add_id=False):
            logger.info(
                f"{OFF}This release ID ({item_id}) was already downloaded "
                "according to the local database.\nUse the '--no-db' flag "
                "to bypass this."
            )
            return
        try:
            dloader = downloader.Download(
                self.client,
                item_id,
                alt_path or self.directory,
                int(self.quality),
                self.embed_art,
                self.ignore_singles_eps,
                self.quality_fallback,
                self.cover_og_quality,
                self.no_cover,
                self.folder_format,
                self.track_format,
                cancel_event=self.cancel_event,
            )
            dloader.download_id_by_type(not album)
            handle_download_id(self.downloads_db, item_id, add_id=True)
        except (requests.exceptions.RequestException, NonStreamable) as e:
            logger.error(f"{RED}Error getting release: {e}. Skipping...")

    def handle_url(self, url):
        possibles = {
            "playlist": {
                "func": self.client.get_plist_meta,
                "iterable_key": "tracks",
            },
            "artist": {
                "func": self.client.get_artist_meta,
                "iterable_key": "albums",
            },
            "label": {
                "func": self.client.get_label_meta,
                "iterable_key": "albums",
            },
            "album": {"album": True, "func": None, "iterable_key": None},
            "track": {"album": False, "func": None, "iterable_key": None},
        }
        try:
            url_type, item_id = get_url_info(url)
            type_dict = possibles[url_type]
        except (KeyError, IndexError):
            logger.info(
                f'{RED}Invalid url: "{url}". Use urls from https://play.qobuz.com!'
            )
            return
        if type_dict["func"]:
            content = [item for item in type_dict["func"](item_id)]
            content_name = content[0]["name"]
            logger.info(
                f"{YELLOW}Downloading all the music from {content_name} ({url_type})!"
            )
            new_path = create_and_return_dir(
                os.path.join(self.directory, sanitize_filename(content_name))
            )

            if self.smart_discography and url_type == "artist":
                # change `save_space` and `skip_extras` for customization
                items = smart_discography_filter(
                    content,
                    save_space=True,
                    skip_extras=True,
                )
            else:
                items = [item[type_dict["iterable_key"]]["items"] for item in content][
                    0
                ]

            logger.info(f"{YELLOW}{len(items)} downloads in queue")
            for item in items:
                self.download_from_id(
                    item["id"],
                    True if type_dict["iterable_key"] == "albums" else False,
                    new_path,
                )
            if url_type == "playlist" and not self.no_m3u_for_playlists:
                make_m3u(new_path)
        else:
            self.download_from_id(item_id, type_dict["album"])

    def download_list_of_urls(self, urls):
        if not urls or not isinstance(urls, list):
            logger.info(f"{OFF}Nothing to download")
            return
        for url in urls:
            if "last.fm" in url:
                self.download_lastfm_pl(url)
            elif os.path.isfile(url):
                self.download_from_txt_file(url)
            else:
                self.handle_url(url)

    def download_from_txt_file(self, txt_file):
        with open(txt_file, "r") as txt:
            try:
                urls = [
                    line.replace("\n", "")
                    for line in txt.readlines()
                    if not line.strip().startswith("#")
                ]
            except Exception as e:
                logger.error(f"{RED}Invalid text file: {e}")
                return
            logger.info(
                f"{YELLOW}qobuz-dl will download {len(urls)} urls from file: {txt_file}"
            )
            self.download_list_of_urls(urls)

    def handle_oauth_login(self, code=None):
        import socket
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import parse_qs, urlparse

        if not code:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", 0))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                port = s.getsockname()[1]

            oauth_url = (
                f"https://www.qobuz.com/signin/oauth"
                f"?ext_app_id={self.app_id}"
                f"&redirect_url=http://localhost:{port}"
            )

            class OAuthHandler(BaseHTTPRequestHandler):
                def do_GET(self):
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)
                    auth_code = params.get(
                        "code", [params.get("code_autorisation", [""])[0]]
                    )[0]
                    if auth_code:
                        OAuthHandler.auth_code = auth_code
                        self.send_response(200)
                        self.send_header("Content-type", "text/html")
                        self.end_headers()
                        self.wfile.write(
                            b"<html><body style='font-family:system-ui;text-align:center;padding:60px'><h2>Login successful</h2><p>You can close this tab and return to qobuz-dl.</p></body></html>"
                        )
                    else:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(
                            b"<html><body><h2>Login failed</h2></body></html>"
                        )

                def log_message(self, format, *args):
                    pass

            OAuthHandler.auth_code = None

            logger.info(f"{YELLOW}Opening browser for Qobuz OAuth login…")
            logger.info(f"{CYAN}OAuth URL: {oauth_url}{RESET}")

            server = HTTPServer(("127.0.0.1", port), OAuthHandler)
            thread = threading.Thread(target=server.handle_request)
            thread.start()

            import webbrowser

            webbrowser.open(oauth_url)

            thread.join(timeout=120)
            server.server_close()

            if OAuthHandler.auth_code:
                code = OAuthHandler.auth_code
            else:
                logger.error(f"{RED}No OAuth code received. Please try again.")
                return
        else:
            if "code" in code or "code_autorisation" in code:
                parsed = urlparse(code)
                params = parse_qs(parsed.query)
                code = params.get("code", [params.get("code_autorisation", [""])[0]])[0]

        if not code:
            logger.error(f"{RED}No OAuth code found.")
            return

        if not hasattr(self, "client") or self.client is None:
            logger.info(f"{YELLOW}Refreshing app_id and secrets…")
            self.get_tokens()

        self.initialize_client_with_oauth(
            code, self.app_id, self.secrets, self.private_key
        )
        logger.info(f"{GREEN}OAuth login successful!")
        self.save_oauth_token_to_config(CONFIG_FILE)

    def lucky_mode(self, query, download=True):
        if len(query) < 3:
            logger.info(f"{RED}Your search query is too short or invalid")
            return

        logger.info(
            f'{YELLOW}Searching {self.lucky_type}s for "{query}".\n'
            f"{YELLOW}qobuz-dl will attempt to download the first "
            f"{self.lucky_limit} results."
        )
        results = self.search_by_type(query, self.lucky_type, self.lucky_limit, True)

        if download:
            self.download_list_of_urls(results)

        return results

    def search_by_type(self, query, item_type, limit=10, lucky=False):
        if len(query) < 3:
            logger.info("{RED}Your search query is too short or invalid")
            return

        possibles = {
            "album": {
                "func": self.client.search_albums,
                "album": True,
                "key": "albums",
                "format": "{artist[name]} - {title}",
                "requires_extra": True,
            },
            "artist": {
                "func": self.client.search_artists,
                "album": True,
                "key": "artists",
                "format": "{name} - ({albums_count} releases)",
                "requires_extra": False,
            },
            "track": {
                "func": self.client.search_tracks,
                "album": False,
                "key": "tracks",
                "format": "{performer[name]} - {title}",
                "requires_extra": True,
            },
            "playlist": {
                "func": self.client.search_playlists,
                "album": False,
                "key": "playlists",
                "format": "{name} - ({tracks_count} releases)",
                "requires_extra": False,
            },
        }

        try:
            mode_dict = possibles[item_type]
            results = mode_dict["func"](query, limit)
            iterable = results[mode_dict["key"]]["items"]
            item_list = []
            for i in iterable:
                fmt = PartialFormatter()
                text = fmt.format(mode_dict["format"], **i)
                if mode_dict["requires_extra"]:
                    text = "{} - {} [{}]".format(
                        text,
                        format_duration(i["duration"]),
                        "HI-RES" if i["hires_streamable"] else "LOSSLESS",
                    )

                url = "{}{}/{}".format(WEB_URL, item_type, i.get("id", ""))
                item_list.append({"text": text, "url": url} if not lucky else url)
            return item_list
        except (KeyError, IndexError):
            logger.info(f"{RED}Invalid type: {item_type}")
            return

    def interactive(self, download=True):
        try:
            from pick import pick
        except (ImportError, ModuleNotFoundError):
            if os.name == "nt":
                sys.exit(
                    "Please install curses with "
                    '"pip3 install windows-curses" to continue'
                )
            raise

        qualities = [
            {"q_string": "320", "q": 5},
            {"q_string": "Lossless", "q": 6},
            {"q_string": "Hi-res =< 96kHz", "q": 7},
            {"q_string": "Hi-Res > 96 kHz", "q": 27},
        ]

        def get_title_text(option):
            return option.get("text")

        def get_quality_text(option):
            return option.get("q_string")

        try:
            item_types = ["Albums", "Tracks", "Artists", "Playlists"]
            selected_type = pick(item_types, "I'll search for:\n[press Intro]")[0][
                :-1
            ].lower()
            logger.info(f"{YELLOW}Ok, we'll search for {selected_type}s{RESET}")
            final_url_list = []
            while True:
                query = input(f"{CYAN}Enter your search: [Ctrl + c to quit]\n-{DF} ")
                logger.info(f"{YELLOW}Searching...{RESET}")
                options = self.search_by_type(
                    query, selected_type, self.interactive_limit
                )
                if not options:
                    logger.info(f"{OFF}Nothing found{RESET}")
                    continue
                title = (
                    f'*** RESULTS FOR "{query.title()}" ***\n\n'
                    "Select [space] the item(s) you want to download "
                    "(one or more)\nPress Ctrl + c to quit\n"
                    "Don't select anything to try another search"
                )
                selected_items = pick(
                    options,
                    title,
                    multiselect=True,
                    min_selection_count=0,
                    options_map_func=get_title_text,
                )
                if len(selected_items) > 0:
                    [final_url_list.append(i[0]["url"]) for i in selected_items]
                    y_n = pick(
                        ["Yes", "No"],
                        "Items were added to queue to be downloaded. Keep searching?",
                    )
                    if y_n[0][0] == "N":
                        break
                else:
                    logger.info(f"{YELLOW}Ok, try again...{RESET}")
                    continue
            if final_url_list:
                desc = (
                    "Select [intro] the quality (the quality will "
                    "be automatically\ndowngraded if the selected "
                    "is not found)"
                )
                self.quality = pick(
                    qualities,
                    desc,
                    default_index=1,
                    options_map_func=get_quality_text,
                )[0]["q"]

                if download:
                    self.download_list_of_urls(final_url_list)

                return final_url_list
        except KeyboardInterrupt:
            logger.info(f"{YELLOW}Bye")
            return

    def download_lastfm_pl(self, playlist_url):
        # Apparently, last fm API doesn't have a playlist endpoint. If you
        # find out that it has, please fix this!
        try:
            r = requests.get(playlist_url, timeout=10)
        except requests.exceptions.RequestException as e:
            logger.error(f"{RED}Playlist download failed: {e}")
            return
        soup = bso(r.content, "html.parser")
        artists = [artist.text for artist in soup.select(ARTISTS_SELECTOR)]
        titles = [title.text for title in soup.select(TITLE_SELECTOR)]

        track_list = []
        if len(artists) == len(titles) and artists:
            track_list = [
                artist + " " + title for artist, title in zip(artists, titles)
            ]

        if not track_list:
            logger.info(f"{OFF}Nothing found")
            return

        pl_title = sanitize_filename(soup.select_one("h1").text)
        pl_directory = os.path.join(self.directory, pl_title)
        logger.info(
            f"{YELLOW}Downloading playlist: {pl_title} ({len(track_list)} tracks)"
        )

        for i in track_list:
            track_id = get_url_info(self.search_by_type(i, "track", 1, lucky=True)[0])[
                1
            ]
            if track_id:
                self.download_from_id(track_id, False, pl_directory)

        if not self.no_m3u_for_playlists:
            make_m3u(pl_directory)
