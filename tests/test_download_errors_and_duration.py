import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import qobuz_dl.gui_app as gui_app
from qobuz_dl.core import QobuzDL
from qobuz_dl.routes.download_routes import _url_error_message


class UrlErrorMessageTests(unittest.TestCase):
    def test_known_details(self):
        self.assertIn("local database", _url_error_message("already_downloaded"))
        self.assertIn("not available for streaming", _url_error_message("non_streamable"))

    def test_unknown_detail_uses_generic(self):
        msg = _url_error_message("something_else")
        self.assertIn("did not finish successfully", msg)


class AlreadyDownloadedHookTests(unittest.TestCase):
    def test_download_from_id_notes_already_downloaded(self):
        noted = {"called": False}

        def note():
            noted["called"] = True

        q = QobuzDL.__new__(QobuzDL)
        q.downloads_db = "dummy.db"
        q.cancel_event = None

        with patch("qobuz_dl.core.handle_download_id", return_value=True), patch(
            "qobuz_dl.core.note_already_downloaded_release", note
        ):
            q.download_from_id("spn1l4a9xfly6", album=True)

        self.assertTrue(noted["called"])


class SearchDurationFieldTests(unittest.TestCase):
    def test_search_by_type_includes_duration_sec_for_albums(self):
        client = MagicMock()
        client.search_albums.return_value = {
            "albums": {
                "items": [
                    {
                        "id": "alb1",
                        "title": "Demo Album",
                        "artist": {"name": "Demo Artist"},
                        "duration": 3723,
                        "tracks_count": 12,
                        "hires_streamable": True,
                        "release_date_original": "2020-01-01",
                        "image": {"large": "https://example.invalid/c.jpg"},
                    }
                ]
            }
        }
        q = QobuzDL.__new__(QobuzDL)
        q.client = client
        results = q.search_by_type("demo", "album", 5)
        self.assertTrue(results)
        self.assertEqual(results[0].get("duration_sec"), 3723)
        self.assertEqual(results[0].get("tracks"), 12)


class AlbumTracksRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        patches = [
            patch.object(gui_app, "CONFIG_PATH", root),
            patch.object(gui_app, "CONFIG_FILE", os.path.join(root, "config.ini")),
            patch.object(
                gui_app, "DOWNLOAD_QUEUE_JSON", os.path.join(root, "download_queue.json")
            ),
            patch.object(
                gui_app,
                "GUI_FEEDBACK_HISTORY_JSON",
                os.path.join(root, "feedback.json"),
            ),
            patch.object(gui_app, "QOBUZ_DB", os.path.join(root, "qobuz_dl.db")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        gui_app.app.config.update(TESTING=True)
        self.client = gui_app.app.test_client()

    def test_album_tracks_requires_connection(self):
        with patch.object(gui_app, "_qobuz_client", None):
            res = self.client.get("/api/album_tracks?id=abc")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["ok"])

    def test_album_tracks_shape(self):
        fake_client = MagicMock()
        fake_client.get_album_meta.return_value = {
            "id": "alb1",
            "title": "Demo Album",
            "artist": {"name": "Demo Artist"},
            "duration": 400,
            "hires_streamable": False,
            "image": {"large": "https://example.invalid/c.jpg"},
            "tracks": {
                "items": [
                    {
                        "id": "t1",
                        "title": "Track One",
                        "duration": 125,
                        "track_number": 1,
                        "performer": {"name": "Demo Artist"},
                        "hires_streamable": False,
                    },
                    {
                        "id": "t2",
                        "title": "Track Two",
                        "duration": 200,
                        "track_number": 2,
                        "performer": {"name": "Demo Artist"},
                        "hires_streamable": True,
                    },
                ]
            },
        }
        fake_qobuz = MagicMock()
        fake_qobuz.client = fake_client

        with patch.object(gui_app, "_qobuz_client", fake_qobuz):
            res = self.client.get("/api/album_tracks?id=alb1")

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["album_title"], "Demo Album")
        self.assertEqual(len(data["results"]), 2)
        self.assertEqual(data["results"][0]["type"], "track")
        self.assertEqual(data["results"][0]["duration_sec"], 125)
        self.assertEqual(data["results"][1]["quality"], "HI-RES")
        self.assertTrue(data["results"][0]["url"].endswith("/track/t1"))

    def test_album_tracks_sorted_by_disc_then_track(self):
        fake_client = MagicMock()
        fake_client.get_album_meta.return_value = {
            "id": "alb2",
            "title": "Multi Disc",
            "artist": {"name": "Demo Artist"},
            "duration": 900,
            "hires_streamable": False,
            "image": {"large": "https://example.invalid/c.jpg"},
            "tracks": {
                "items": [
                    {
                        "id": "t22",
                        "title": "D2T2",
                        "duration": 100,
                        "media_number": 2,
                        "track_number": 2,
                    },
                    {
                        "id": "t11",
                        "title": "D1T1",
                        "duration": 100,
                        "media_number": 1,
                        "track_number": 1,
                    },
                    {
                        "id": "t21",
                        "title": "D2T1",
                        "duration": 100,
                        "media_number": 2,
                        "track_number": 1,
                    },
                    {
                        "id": "t12",
                        "title": "D1T2",
                        "duration": 100,
                        "disc_number": 1,
                        "track_number": 2,
                    },
                ]
            },
        }
        fake_qobuz = MagicMock()
        fake_qobuz.client = fake_client

        with patch.object(gui_app, "_qobuz_client", fake_qobuz):
            res = self.client.get("/api/album_tracks?id=alb2")

        data = res.get_json()
        titles = [r["display_title"] for r in data["results"]]
        self.assertEqual(titles, ["D1T1", "D1T2", "D2T1", "D2T2"])


if __name__ == "__main__":
    unittest.main()
