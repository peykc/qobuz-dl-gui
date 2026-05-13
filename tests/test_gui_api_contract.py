import configparser
import os
import tempfile
import unittest
from unittest.mock import patch

from qobuz_dl import gui_app


class GuiApiContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_dir = self.tmp.name
        self.config_file = os.path.join(self.config_dir, "config.ini")
        self.queue_json = os.path.join(self.config_dir, "download_queue.json")
        self.feedback_json = os.path.join(self.config_dir, "gui_feedback_history.json")
        self.allowed_root = os.path.join(self.config_dir, "library")
        os.makedirs(self.allowed_root, exist_ok=True)

        patches = (
            patch.object(gui_app, "CONFIG_PATH", self.config_dir),
            patch.object(gui_app, "CONFIG_FILE", self.config_file),
            patch.object(gui_app, "DOWNLOAD_QUEUE_JSON", self.queue_json),
            patch.object(gui_app, "GUI_FEEDBACK_HISTORY_JSON", self.feedback_json),
            patch.object(gui_app, "_qobuz_client", None),
            patch.object(gui_app, "_session_download_root_resolved", None),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        self.client = gui_app.app.test_client()

    def _write_config(self):
        cfg = configparser.ConfigParser()
        cfg["DEFAULT"] = {
            "email": "user@example.invalid",
            "default_folder": self.allowed_root,
            "default_quality": "27",
            "lyrics_enabled": "true",
            "lyrics_embed_metadata": "false",
            "no_explicit_tag": "false",
        }
        with open(self.config_file, "w", encoding="utf-8") as f:
            cfg.write(f)

    def test_status_shape_without_config(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        self.assertFalse(data["has_config"])
        self.assertFalse(data["ready"])
        self.assertIn("config", data)
        self.assertIn("app_version", data)
        self.assertIn("frozen", data)
        self.assertIn("capabilities", data)

    def test_config_get_and_post_shape_preserves_private_token_filtering(self):
        self._write_config()

        get_res = self.client.get("/api/config")
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.get_json()
        self.assertTrue(get_data["ok"])
        self.assertIn("config", get_data)

        post_res = self.client.post(
            "/api/config",
            json={"default_quality": "6", "genius_token": "do-not-save"},
        )
        self.assertEqual(post_res.status_code, 200)
        self.assertEqual(post_res.get_json(), {"ok": True})

        cfg = configparser.ConfigParser()
        cfg.read(self.config_file)
        self.assertEqual(cfg["DEFAULT"]["default_quality"], "6")
        self.assertFalse(cfg.has_option("DEFAULT", "genius_token"))

    def test_download_queue_get_and_post_shape(self):
        get_res = self.client.get("/api/download-queue")
        self.assertEqual(get_res.status_code, 200)
        get_data = get_res.get_json()
        self.assertEqual(
            set(get_data.keys()),
            {"ok", "version", "text_mode", "text_urls", "items"},
        )
        self.assertEqual(get_data["items"], [])

        post_res = self.client.post(
            "/api/download-queue",
            json={
                "text_mode": True,
                "text_urls": "https://play.qobuz.com/album/123",
                "items": [
                    {"url": " https://play.qobuz.com/track/456 ", "resolved": []},
                    {"url": "", "resolved": {"title": "ignored"}},
                ],
            },
        )
        self.assertEqual(post_res.status_code, 200)
        self.assertEqual(post_res.get_json(), {"ok": True})

        roundtrip = self.client.get("/api/download-queue").get_json()
        self.assertTrue(roundtrip["text_mode"])
        self.assertEqual(roundtrip["text_urls"], "https://play.qobuz.com/album/123")
        self.assertEqual(
            roundtrip["items"],
            [{"url": "https://play.qobuz.com/track/456", "resolved": None}],
        )

    def test_download_history_shape(self):
        with patch("qobuz_dl.db.list_gui_download_history", return_value=[]):
            res = self.client.get("/api/download-history")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"ok": True, "items": []})

    def test_feedback_history_get_and_post_shape(self):
        get_res = self.client.get("/api/feedback-history")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.get_json(), {"ok": True, "items": []})

        post_res = self.client.post(
            "/api/feedback-history",
            json={"items": [{"id": "one", "status": "sent"}]},
        )
        self.assertEqual(post_res.status_code, 200)
        self.assertEqual(post_res.get_json(), {"ok": True})

        roundtrip = self.client.get("/api/feedback-history").get_json()
        self.assertEqual(roundtrip["items"], [{"id": "one", "status": "sent"}])

    def test_update_check_shape(self):
        with patch(
            "qobuz_dl.updater.check_for_update",
            return_value={"ok": True, "update_available": False},
        ) as mock_check:
            res = self.client.get("/api/update/check?force=1")

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"ok": True, "update_available": False})
        mock_check.assert_called_once_with(self.config_dir, force=True)

    def test_lyrics_search_shape(self):
        with patch(
            "qobuz_dl.lyrics.lrclib_search_candidates_for_ui",
            return_value=[{"id": 123, "name": "Song"}],
        ):
            res = self.client.post(
                "/api/lyrics/search",
                json={"title": "Song", "artist": "Artist", "duration_sec": 180},
            )

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["results"], [{"id": 123, "name": "Song"}])
        self.assertEqual(data["reference_duration_sec"], 180)

    def test_lyrics_attach_rejects_path_outside_allowed_root(self):
        self._write_config()
        outside = os.path.join(self.tmp.name, "outside.mp3")
        with open(outside, "wb") as f:
            f.write(b"audio")

        res = self.client.post(
            "/api/lyrics/attach",
            json={"audio_path": outside, "lrclib_id": 123, "write_sidecar": True},
        )

        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("error", data)

    def test_lyrics_stream_audio_rejects_path_outside_allowed_root(self):
        self._write_config()
        outside = os.path.join(self.tmp.name, "outside.mp3")
        with open(outside, "wb") as f:
            f.write(b"audio")

        res = self.client.get("/api/lyrics/stream-audio", query_string={"path": outside})

        self.assertEqual(res.status_code, 403)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main()
