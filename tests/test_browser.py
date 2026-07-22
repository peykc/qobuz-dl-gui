import unittest
from unittest.mock import patch

from qobuz_dl.app import browser as browser_mod


class EnvForExternalProcessTests(unittest.TestCase):
    def test_non_linux_leaves_env_unchanged(self):
        base = {"LD_LIBRARY_PATH": "/bundle/lib", "PATH": "/usr/bin"}
        with patch.object(browser_mod.sys, "platform", "win32"), patch.object(
            browser_mod.sys, "frozen", True, create=True
        ):
            env = browser_mod.env_for_external_process(base)
        self.assertEqual(env["LD_LIBRARY_PATH"], "/bundle/lib")

    def test_non_frozen_linux_leaves_env_unchanged(self):
        base = {"LD_LIBRARY_PATH": "/bundle/lib", "PATH": "/usr/bin"}
        with patch.object(browser_mod.sys, "platform", "linux"), patch.object(
            browser_mod.sys, "frozen", False, create=True
        ):
            env = browser_mod.env_for_external_process(base)
        self.assertEqual(env["LD_LIBRARY_PATH"], "/bundle/lib")

    def test_frozen_linux_restores_orig_library_path(self):
        base = {
            "LD_LIBRARY_PATH": "/tmp/_MEIabc:/orig/lib",
            "LD_LIBRARY_PATH_ORIG": "/orig/lib",
            "LD_PRELOAD": "/tmp/_MEIabc/lib.so",
            "LD_PRELOAD_ORIG": "",
            "PATH": "/usr/bin",
        }
        with patch.object(browser_mod.sys, "platform", "linux"), patch.object(
            browser_mod.sys, "frozen", True, create=True
        ):
            env = browser_mod.env_for_external_process(base)
        self.assertEqual(env["LD_LIBRARY_PATH"], "/orig/lib")
        self.assertNotIn("LD_LIBRARY_PATH_ORIG", env)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("LD_PRELOAD_ORIG", env)

    def test_frozen_linux_drops_library_path_without_orig(self):
        base = {
            "LD_LIBRARY_PATH": "/tmp/_MEIabc",
            "LD_PRELOAD": "/tmp/_MEIabc/lib.so",
            "PATH": "/usr/bin",
        }
        with patch.object(browser_mod.sys, "platform", "linux"), patch.object(
            browser_mod.sys, "frozen", True, create=True
        ):
            env = browser_mod.env_for_external_process(base)
        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertEqual(env["PATH"], "/usr/bin")


class OpenUrlTests(unittest.TestCase):
    def test_empty_url_returns_false(self):
        self.assertFalse(browser_mod.open_url(""))
        self.assertFalse(browser_mod.open_url("   "))

    def test_linux_uses_xdg_open_with_cleaned_env(self):
        clean = {"PATH": "/usr/bin", "HOME": "/home/u"}
        with patch.object(browser_mod.sys, "platform", "linux"), patch.object(
            browser_mod.sys, "frozen", True, create=True
        ), patch.object(
            browser_mod, "env_for_external_process", return_value=clean
        ), patch.object(
            browser_mod.shutil, "which", side_effect=lambda c: "/usr/bin/" + c
        ), patch.object(browser_mod.subprocess, "Popen") as popen, patch.object(
            browser_mod.webbrowser, "open"
        ) as wb_open:
            ok = browser_mod.open_url("https://example.com/oauth")

        self.assertTrue(ok)
        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["xdg-open", "https://example.com/oauth"])
        self.assertEqual(kwargs["env"], clean)
        self.assertTrue(kwargs["start_new_session"])
        wb_open.assert_not_called()

    def test_linux_falls_back_to_gio_then_webbrowser(self):
        clean = {"PATH": "/usr/bin"}

        def which(cmd):
            return "/usr/bin/gio" if cmd == "gio" else None

        with patch.object(browser_mod.sys, "platform", "linux"), patch.object(
            browser_mod.sys, "frozen", False, create=True
        ), patch.object(
            browser_mod, "env_for_external_process", return_value=clean
        ), patch.object(browser_mod.shutil, "which", side_effect=which), patch.object(
            browser_mod.subprocess, "Popen"
        ) as popen, patch.object(browser_mod.webbrowser, "open") as wb_open:
            ok = browser_mod.open_url("https://example.com/login")

        self.assertTrue(ok)
        popen.assert_called_once()
        self.assertEqual(
            popen.call_args[0][0],
            ["gio", "open", "https://example.com/login"],
        )
        wb_open.assert_not_called()

    def test_non_linux_uses_webbrowser(self):
        with patch.object(browser_mod.sys, "platform", "win32"), patch.object(
            browser_mod.webbrowser, "open", return_value=True
        ) as wb_open, patch.object(browser_mod.subprocess, "Popen") as popen:
            ok = browser_mod.open_url("https://example.com")

        self.assertTrue(ok)
        wb_open.assert_called_once_with("https://example.com")
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
