import os
import tempfile
import unittest
from pathlib import Path

from qobuz_dl.app.path_security import audio_path_allowed_for_lyrics_attach


class PathSecurityTests(unittest.TestCase):
    def test_audio_path_must_exist_under_allowed_root_with_supported_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed_root = Path(tmp) / "library"
            allowed_root.mkdir()
            good = allowed_root / "track.flac"
            good.write_bytes(b"audio")
            bad_suffix = allowed_root / "track.exe"
            bad_suffix.write_bytes(b"binary")
            outside = Path(tmp) / "outside.mp3"
            outside.write_bytes(b"audio")

            self.assertTrue(
                audio_path_allowed_for_lyrics_attach(str(good), [allowed_root])
            )
            self.assertFalse(
                audio_path_allowed_for_lyrics_attach(str(bad_suffix), [allowed_root])
            )
            self.assertFalse(
                audio_path_allowed_for_lyrics_attach(str(outside), [allowed_root])
            )

    def test_missing_placeholder_is_allowed_under_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed_root = Path(tmp) / "library"
            allowed_root.mkdir()
            placeholder = allowed_root / "01 - Missing.missing.txt"
            placeholder.write_text("missing", encoding="utf-8")

            self.assertTrue(
                audio_path_allowed_for_lyrics_attach(
                    os.fspath(placeholder),
                    [allowed_root],
                )
            )


if __name__ == "__main__":
    unittest.main()
