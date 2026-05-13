import configparser
import os
import unittest
from unittest.mock import patch

from qobuz_dl import config_paths
from qobuz_dl.config_defaults import apply_common_defaults
from qobuz_dl.services.qobuz_session import as_bool, as_int, build_qobuz_from_config


class ConfigPathTests(unittest.TestCase):
    def test_windows_config_paths_use_appdata(self):
        env = {"APPDATA": r"C:\Users\me\AppData\Roaming"}

        self.assertEqual(
            config_paths.get_config_path("nt", env),
            os.path.join(env["APPDATA"], "qobuz-dl"),
        )
        self.assertEqual(
            config_paths.get_config_file("nt", env),
            os.path.join(env["APPDATA"], "qobuz-dl", "config.ini"),
        )
        self.assertEqual(
            config_paths.get_qobuz_db_path("nt", env),
            os.path.join(env["APPDATA"], "qobuz-dl", "qobuz_dl.db"),
        )

    def test_posix_config_paths_use_home_config(self):
        env = {"HOME": "/home/me"}

        self.assertEqual(
            config_paths.get_config_path("posix", env),
            os.path.join("/home/me", ".config", "qobuz-dl"),
        )
        self.assertEqual(
            config_paths.get_download_queue_path("posix", env),
            os.path.join("/home/me", ".config", "qobuz-dl", "download_queue.json"),
        )


class ConfigDefaultsTests(unittest.TestCase):
    def test_common_defaults_include_cli_and_gui_shared_options(self):
        cfg = configparser.ConfigParser()
        cfg["DEFAULT"] = {}

        apply_common_defaults(cfg["DEFAULT"], no_database="true")

        defaults = cfg["DEFAULT"]
        self.assertEqual(defaults["default_limit"], "20")
        self.assertEqual(defaults["folder_format"], "{artist}/{album}")
        self.assertEqual(defaults["track_format"], "{tracknumber} - {tracktitle}")
        self.assertEqual(
            defaults["multiple_disc_track_format"],
            "{disc_number_unpadded}{track_number} - {tracktitle}",
        )
        self.assertEqual(defaults["no_database"], "true")
        self.assertEqual(defaults["no_explicit_tag"], "false")
        self.assertEqual(defaults["tag_album_from_folder_format"], "true")


class QobuzSessionHelperTests(unittest.TestCase):
    def test_as_bool_and_as_int_match_gui_parsing_rules(self):
        self.assertTrue(as_bool("yes"))
        self.assertTrue(as_bool(1))
        self.assertFalse(as_bool("off", default=True))
        self.assertTrue(as_bool("maybe", default=True))
        self.assertEqual(as_int("7", default=27), 7)
        self.assertEqual(as_int("", default=27), 27)
        self.assertEqual(as_int("bad", default=27), 27)

    def test_build_qobuz_from_config_applies_overrides_and_db_rule(self):
        cfg = configparser.ConfigParser()
        cfg["DEFAULT"] = {
            "default_folder": "Library",
            "default_quality": "27",
            "no_database": "false",
            "no_fallback": "false",
            "lyrics_enabled": "true",
        }

        with patch("qobuz_dl.core.QobuzDL") as mock_qobuz:
            build_qobuz_from_config(
                cfg,
                overrides={"quality": "6", "directory": "Override", "no_db": "1"},
                downloads_db_path="db.sqlite",
            )

        kwargs = mock_qobuz.call_args.kwargs
        self.assertEqual(kwargs["directory"], "Override")
        self.assertEqual(kwargs["quality"], 6)
        self.assertTrue(kwargs["quality_fallback"])
        self.assertTrue(kwargs["lyrics_enabled"])
        self.assertIsNone(kwargs["downloads_db"])


if __name__ == "__main__":
    unittest.main()
