import os
import tempfile
import unittest
from unittest.mock import patch

import qobuz_dl.gui_app as gui_app
from qobuz_dl.config_defaults import apply_common_defaults


class GuiRouteShapeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.patches = [
            patch.object(gui_app, "CONFIG_PATH", root),
            patch.object(gui_app, "CONFIG_FILE", os.path.join(root, "config.ini")),
            patch.object(gui_app, "DOWNLOAD_QUEUE_JSON", os.path.join(root, "download_queue.json")),
            patch.object(gui_app, "GUI_FEEDBACK_HISTORY_JSON", os.path.join(root, "feedback.json")),
            patch.object(gui_app, "QOBUZ_DB", os.path.join(root, "qobuz_dl.db")),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        gui_app.app.config.update(TESTING=True)
        self.client = gui_app.app.test_client()

    def _write_config(self):
        import configparser

        cfg = configparser.ConfigParser()
        cfg["DEFAULT"] = {
            "email": "",
            "password": "",
            "app_id": "",
            "secrets": "",
        }
        apply_common_defaults(cfg["DEFAULT"], no_database="true")
        os.makedirs(gui_app.CONFIG_PATH, exist_ok=True)
        with open(gui_app.CONFIG_FILE, "w", encoding="utf-8") as f:
            cfg.write(f)

    def test_status_shape_uses_existing_endpoint(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("has_config", data)
        self.assertIn("ready", data)
        self.assertIn("config", data)
        self.assertIn("app_version", data)

    def test_config_get_post_shape_preserves_flat_keys(self):
        self._write_config()
        post = self.client.post(
            "/api/config",
            json={"default_quality": "6", "lyrics_enabled": "true"},
        )
        self.assertEqual(post.status_code, 200)
        self.assertTrue(post.get_json()["ok"])

        res = self.client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertNotIn("default_quality", data)
        self.assertEqual(data["config"]["lyrics_enabled"], "true")
        self.assertEqual(data["config"]["default_quality"], "6")

    def test_download_queue_shape_round_trips_items_and_text_mode(self):
        payload = {
            "items": [{"url": "https://play.qobuz.com/album/example"}],
            "text_mode": True,
            "text_urls": "https://play.qobuz.com/track/example",
        }
        post = self.client.post("/api/download-queue", json=payload)
        self.assertEqual(post.status_code, 200)
        self.assertTrue(post.get_json()["ok"])

        res = self.client.get("/api/download-queue")
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["items"][0]["url"], payload["items"][0]["url"])
        self.assertIn("resolved", data["items"][0])
        self.assertTrue(data["text_mode"])
        self.assertEqual(data["text_urls"], payload["text_urls"])

    def test_download_history_shape(self):
        res = self.client.get("/api/download-history")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertIsInstance(data["items"], list)

    def test_lyrics_search_shape_uses_existing_endpoint(self):
        with patch(
            "qobuz_dl.lyrics.lrclib_search_candidates_for_ui",
            return_value=[{"id": 123, "kind": "synced"}],
        ):
            res = self.client.post(
                "/api/lyrics/search",
                json={"title": "Song", "artist": "Artist", "duration_sec": 180},
            )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["results"][0]["id"], 123)

    def test_lyrics_attach_and_stream_reject_paths_outside_allowed_roots(self):
        outside = os.path.join(self.tmp.name, "..", "outside.flac")
        attach = self.client.post(
            "/api/lyrics/attach",
            json={"audio_path": outside, "lrclib_id": 1},
        )
        stream = self.client.get("/api/lyrics/stream-audio", query_string={"path": outside})
        self.assertEqual(attach.status_code, 400)
        self.assertEqual(stream.status_code, 403)


if __name__ == "__main__":
    unittest.main()
