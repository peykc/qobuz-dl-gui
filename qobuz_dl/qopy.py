# Wrapper for Qo-DL Reborn. This is a sligthly modified version
# of qopy, originally written by Sorrow446. All credits to the
# original author.

import base64
import hashlib
import logging
import time

import requests
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from qobuz_dl.exceptions import (
    AuthenticationError,
    IneligibleError,
    InvalidAppIdError,
    InvalidAppSecretError,
    InvalidQuality,
)
from qobuz_dl.color import GREEN, YELLOW

RESET = "Reset your credentials with 'qobuz-dl -r'"

logger = logging.getLogger(__name__)


class Client:
    def __init__(self, email, pwd, app_id, secrets, skip_auth=False):
        logger.info(f"{YELLOW}Logging...")
        self.secrets = secrets
        self.id = str(app_id)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:83.0) Gecko/20100101 Firefox/83.0",
                "X-App-Id": self.id,
                "Content-Type": "application/json;charset=UTF-8"

            }
        )
        self.base = "https://www.qobuz.com/api.json/0.2/"
        self.sec = None
        self.session_id = None
        self.session_infos = None
        self.session_key = None
        if not skip_auth:
            self.auth(email, pwd)
            self.cfg_setup()

    def api_call(self, epoint, **kwargs):
        if epoint == "user/login":
            params = {
                "email": kwargs["email"],
                "password": kwargs["pwd"],
                "app_id": self.id,
            }
        elif epoint == "track/get":
            params = {"track_id": kwargs["id"], "app_id": self.id}
        elif epoint == "album/get":
            params = {"album_id": kwargs["id"]}
        elif epoint == "playlist/get":
            params = {
                "extra": "tracks",
                "playlist_id": kwargs["id"],
                "limit": 500,
                "offset": kwargs["offset"],
            }
        elif epoint == "artist/get":
            params = {
                "app_id": self.id,
                "artist_id": kwargs["id"],
                "limit": 500,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "artist/getReleasesList":
            params = {
                "artist_id": kwargs["id"],
                "release_type": kwargs.get("release_type", "album"),
                # Default catalog order is popularity (relevance), not release date.
                "sort": kwargs.get("sort", "popularity"),
                "order": kwargs.get("order", "desc"),
                "limit": kwargs.get("limit", 50),
                "offset": kwargs.get("offset", 0),
                "track_size": 1,
            }
        elif epoint == "label/get":
            params = {
                "label_id": kwargs["id"],
                "limit": 500,
                "offset": kwargs["offset"],
                "extra": "albums",
            }
        elif epoint == "favorite/getUserFavorites":
            unix = time.time()
            # r_sig = "userLibrarygetAlbumsList" + str(unix) + kwargs["sec"]
            r_sig = "favoritegetUserFavorites" + str(unix) + kwargs["sec"]
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "app_id": self.id,
                "user_auth_token": self.uat,
                "type": "albums",
                "request_ts": unix,
                "request_sig": r_sig_hashed,
            }
        elif epoint == "track/getFileUrl":
            unix = time.time()
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            if int(fmt_id) not in (5, 6, 7, 27):
                raise InvalidQuality("Invalid quality id: choose between 5, 6, 7 or 27")
            r_sig = "trackgetFileUrlformat_id{}intentstreamtrack_id{}{}{}".format(
                fmt_id, track_id, unix, kwargs.get("sec", self.sec)
            )
            r_sig_hashed = hashlib.md5(r_sig.encode("utf-8")).hexdigest()
            params = {
                "request_ts": unix,
                "request_sig": r_sig_hashed,
                "track_id": track_id,
                "format_id": fmt_id,
                "intent": "stream",
            }
        elif epoint == "session/start":
            params = {"profile": "qbz-1"}
            unix = int(time.time())
            params["request_ts"] = unix
            params["request_sig"] = self._modern_sig(
                epoint, params, kwargs.get("sec", self.sec)
            )
        elif epoint == "file/url":
            track_id = kwargs["id"]
            fmt_id = kwargs["fmt_id"]
            if int(fmt_id) not in (6, 7, 27):
                raise InvalidQuality(
                    "Invalid quality id: choose between 6, 7 or 27"
                )
            params = {
                "track_id": track_id,
                "format_id": fmt_id,
                "intent": "import",
            }
            unix = int(time.time())
            params["request_ts"] = unix
            params["request_sig"] = self._modern_sig(
                epoint, params, kwargs.get("sec", self.sec)
            )
        else:
            params = kwargs
        if epoint == "session/start":
            r = self.session.post(
                self.base + epoint,
                data=params,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        else:
            r = self.session.get(self.base + epoint, params=params)
        if epoint == "user/login":
            if r.status_code == 401:
                raise AuthenticationError("Invalid credentials.\n" + RESET)
            elif r.status_code == 400:
                raise InvalidAppIdError("Invalid app id.\n" + RESET)
            else:
                logger.info(f"{GREEN}Logged: OK")
        elif (
            epoint in ["track/getFileUrl", "favorite/getUserFavorites", "file/url"]
            and r.status_code == 400
        ):
            raise InvalidAppSecretError(f"Invalid app secret: {r.json()}.\n" + RESET)

        r.raise_for_status()
        return r.json()

    def auth(self, email, pwd):
        usr_info = self.api_call("user/login", email=email, pwd=pwd)
        if not usr_info["user"]["credential"]["parameters"]:
            raise IneligibleError("This Qobuz account is not eligible to download tracks.")
        self.uat = usr_info["user_auth_token"]
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        self.label = usr_info["user"]["credential"]["parameters"]["short_label"]
        logger.info(f"{GREEN}Membership: {self.label}")

    def auth_with_token(self, user_id, user_auth_token):
        params = {
            "user_id": str(user_id),
            "user_auth_token": user_auth_token,
            "app_id": self.id,
        }
        r = self.session.get(self.base + "user/login", params=params)
        if r.status_code == 401:
            raise AuthenticationError("Invalid credentials.\n" + RESET)
        elif r.status_code == 400:
            raise InvalidAppIdError("Invalid app id.\n" + RESET)
        r.raise_for_status()
        usr_info = r.json()
        if not usr_info["user"]["credential"]["parameters"]:
            raise IneligibleError("This Qobuz account is not eligible to download tracks.")
        self.uat = user_auth_token
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        self.label = usr_info["user"]["credential"]["parameters"]["short_label"]
        logger.info(f"{GREEN}Membership: {self.label}")
        self.cfg_setup()

    def login_with_oauth_code(self, code, private_key):
        callback_url = self.base + "oauth/callback"
        params = {
            "code": code,
            "private_key": private_key,
            "app_id": self.id,
        }
        r = self.session.get(callback_url, params=params)
        r.raise_for_status()
        json_resp = r.json()
        token = json_resp.get("token")
        if not token:
            raise AuthenticationError("No token in OAuth callback response")
        self.uat = token
        self.session.headers.update({"X-User-Auth-Token": self.uat})
        login_url = self.base + "user/login"
        r = self.session.post(
            login_url,
            headers={"Content-Type": "text/plain;charset=UTF-8"},
            data="extra=partner"
        )
        if r.status_code == 401:
            raise AuthenticationError("OAuth token rejected")
        r.raise_for_status()
        usr_info = r.json()
        if not usr_info["user"]["credential"]["parameters"]:
            raise IneligibleError("This Qobuz account is not eligible to download tracks.")
        self.label = usr_info["user"]["credential"]["parameters"]["short_label"]
        logger.info(f"{GREEN}Membership: {self.label}")
        self.cfg_setup()
        return usr_info

    @staticmethod
    def _modern_sig(epoint, params, sec):
        object_, method = epoint.split("/")
        r_sig = [object_, method]
        for key in sorted(params):
            value = params[key]
            if key not in ("request_ts", "request_sig") and isinstance(
                value, (str, int, float)
            ):
                r_sig.extend((key, str(value)))
        r_sig.extend((str(params["request_ts"]), sec))
        return hashlib.md5("".join(r_sig).encode("utf-8")).hexdigest()

    @staticmethod
    def _b64url_decode(value):
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def _derive_session_key(self):
        salt, info = self.session_infos.split(".")
        return HKDF(
            algorithm=hashes.SHA256(),
            length=16,
            salt=self._b64url_decode(salt),
            info=self._b64url_decode(info),
        ).derive(bytes.fromhex(self.sec))

    def _unwrap_track_key(self, key_token):
        _, wrapped, iv = key_token.split(".")
        decryptor = Cipher(
            algorithms.AES(self.session_key),
            modes.CBC(self._b64url_decode(iv)),
        ).decryptor()
        padded = decryptor.update(self._b64url_decode(wrapped)) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()

    def multi_meta(self, epoint, key, id, type):
        total = 1
        offset = 0
        while total > 0:
            if type in ["tracks", "albums"]:
                j = self.api_call(epoint, id=id, offset=offset, type=type)[type]
            else:
                j = self.api_call(epoint, id=id, offset=offset, type=type)
            if offset == 0:
                yield j
                total = j[key] - 500
            else:
                yield j
                total -= 500
            offset += 500

    def get_album_meta(self, id):
        return self.api_call("album/get", id=id)

    def get_track_meta(self, id):
        return self.api_call("track/get", id=id)

    def get_track_url(self, id, fmt_id, force_segments=False):
        if int(fmt_id) == 5:
            return self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)

        if not force_segments:
            try:
                track = self.api_call("track/getFileUrl", id=id, fmt_id=fmt_id)
                if "url" in track:
                    return track
            except Exception:
                pass

        if self.session_id is None:
            session = self.api_call("session/start")
            self.session_id = session["session_id"]
            self.session_infos = session["infos"]
            self.session_key = self._derive_session_key()
            self.session.headers.update({"X-Session-Id": self.session_id})

        track = self.api_call("file/url", id=id, fmt_id=fmt_id)
        if "bits_depth" in track and "bit_depth" not in track:
            track["bit_depth"] = track["bits_depth"]
        if track.get("sampling_rate", 0) > 1000:
            track["sampling_rate"] = track["sampling_rate"] / 1000
        if "key" in track:
            track["raw_key"] = self._unwrap_track_key(track["key"])
        return track

    def get_artist_meta(self, id):
        return self.multi_meta("artist/get", "albums_count", id, None)

    def get_artist_releases(
        self,
        artist_id,
        limit=50,
        offset=0,
        release_type="album",
        sort="popularity",
        order="desc",
    ):
        return self.api_call(
            "artist/getReleasesList",
            id=artist_id,
            limit=limit,
            offset=offset,
            release_type=release_type,
            sort=sort,
            order=order,
        )

    def get_plist_meta(self, id):
        return self.multi_meta("playlist/get", "tracks_count", id, None)

    def get_label_meta(self, id):
        return self.multi_meta("label/get", "albums_count", id, None)

    def search_albums(self, query, limit, offset=0):
        return self.api_call(
            "album/search", query=query, limit=limit, offset=offset
        )

    def search_artists(self, query, limit, offset=0):
        return self.api_call(
            "artist/search", query=query, limit=limit, offset=offset
        )

    def search_playlists(self, query, limit, offset=0):
        return self.api_call(
            "playlist/search", query=query, limit=limit, offset=offset
        )

    def search_tracks(self, query, limit, offset=0):
        return self.api_call(
            "track/search", query=query, limit=limit, offset=offset
        )

    def get_favorite_albums(self, offset, limit):
        return self.api_call(
            "favorite/getUserFavorites", type="albums", offset=offset, limit=limit
        )

    def get_favorite_tracks(self, offset, limit):
        return self.api_call(
            "favorite/getUserFavorites", type="tracks", offset=offset, limit=limit
        )

    def get_favorite_artists(self, offset, limit):
        return self.api_call(
            "favorite/getUserFavorites", type="artists", offset=offset, limit=limit
        )

    def get_user_playlists(self, limit):
        return self.api_call("playlist/getUserPlaylists", limit=limit)

    def test_secret(self, sec):
        try:
            self.api_call("track/getFileUrl", id=5966783, fmt_id=5, sec=sec)
            return True
        except InvalidAppSecretError:
            return False

    def set_language_headers(self, native_lang: bool = False):
        """Prefer English metadata unless native_lang requests account locale."""
        if native_lang:
            self.session.headers.pop("Accept-Language", None)
        else:
            self.session.headers["Accept-Language"] = "en-US,en;q=0.9"

    def cfg_setup(self):
        for secret in self.secrets:
            # Falsy secrets
            if not secret:
                continue

            if self.test_secret(secret):
                self.sec = secret
                break

        if self.sec is None:
            raise InvalidAppSecretError("Can't find any valid app secret.\n" + RESET)
