import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qobuz_dl.downloader import Download, _track_dict_for_lrclib
from qobuz_dl.utils import flac_fix_md5s, make_m3u


class DownloaderFeatureTests(unittest.TestCase):
    def test_make_m3u_writes_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            album_dir = os.path.join(tmp, "Albüm")
            os.makedirs(album_dir, exist_ok=True)
            mp3_path = os.path.join(album_dir, "Şarkı.mp3")
            with open(mp3_path, "wb") as f:
                f.write(b"fake")

            class FakeAudio:
                info = SimpleNamespace(length=201)

                def __getitem__(self, key):
                    if key == "TITLE":
                        return ["Şarkı"]
                    if key == "ARTIST":
                        return ["Sanatçı"]
                    raise KeyError(key)

            with patch("qobuz_dl.utils.EasyMP3", return_value=FakeAudio()):
                make_m3u(tmp)

            pl_path = os.path.join(tmp, os.path.basename(tmp) + ".m3u")
            with open(pl_path, "r", encoding="utf-8") as f:
                body = f.read()
            self.assertIn("Sanatçı - Şarkı", body)

    def test_flac_fix_md5s_missing_file(self):
        got = flac_fix_md5s("C:/does/not/exist.flac")
        self.assertFalse(got)

    def test_flac_fix_md5s_success(self):
        with patch("qobuz_dl.utils.os.path.isfile", return_value=True), patch(
            "qobuz_dl.utils.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ):
            got = flac_fix_md5s("C:/music/test.flac")
        self.assertTrue(got)

    def test_filename_attr_includes_extended_variables(self):
        track = {
            "id": 123,
            "title": "Track Name",
            "version": "Deluxe",
            "track_number": 3,
            "media_number": 2,
            "maximum_bit_depth": 24,
            "maximum_sampling_rate": 96,
            "isrc": "US1234567890",
            "release_date_original": "2024-01-12",
            "performer": {"name": "Artist"},
            "album": {
                "id": 999,
                "title": "Album Name",
                "url": "https://play.qobuz.com/album/999",
                "artist": {"name": "Artist"},
                "upc": "123456789012",
                "tracks_count": 10,
                "media_count": 2,
                "product_type": "album",
                "release_date_original": "2024-01-12",
            },
        }
        attrs = Download._get_filename_attr("Artist", track, "Track Name")
        self.assertEqual(attrs["track_number"], "03")
        self.assertEqual(attrs["disc_number"], "02")
        self.assertEqual(attrs["album_url"], "https://play.qobuz.com/album/999")
        self.assertEqual(attrs["barcode"], "123456789012")

    def test_track_dict_for_lrclib_fills_missing_nested_album(self):
        track = {
            "title": "Song",
            "track_number": 1,
            "performer": {"name": "Artist"},
            "duration": 200,
        }
        release = {
            "title": "Album Name",
            "explicit": True,
            "parental_warning": True,
        }
        out = _track_dict_for_lrclib(track, release)
        self.assertEqual(out["album"]["title"], "Album Name")
        self.assertTrue(out["album"].get("explicit"))


if __name__ == "__main__":
    unittest.main()
