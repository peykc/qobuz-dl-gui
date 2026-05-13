import configparser
import os
import unittest

from qobuz_dl import config_paths
from qobuz_dl.config_defaults import apply_common_defaults


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


if __name__ == "__main__":
    unittest.main()
