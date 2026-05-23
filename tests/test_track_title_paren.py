import unittest

from qobuz_dl.downloader import _track_title_base_with_feat
from qobuz_dl.track_title_paren import (
    paren_content_should_strip,
    strip_noise_parentheticals,
)


class TrackTitleParenStripTests(unittest.TestCase):
    def test_snow_hey_oh_remaster(self):
        self.assertEqual(
            strip_noise_parentheticals("Snow (Hey Oh) (2014 Remaster)"),
            "Snow (Hey Oh)",
        )

    def test_nested_album_version_explicit_removed_whole(self):
        self.assertEqual(
            strip_noise_parentheticals("Six Shots Two Guns (Album Version (Explicit))"),
            "Six Shots Two Guns",
        )

    def test_nested_title_explicit_keeps_subtitle(self):
        self.assertEqual(
            strip_noise_parentheticals(
                "Lo Chiamavano King (His Name Is King (Explicit))"
            ),
            "Lo Chiamavano King (His Name Is King)",
        )

    def test_keeps_live_and_clean(self):
        self.assertEqual(
            strip_noise_parentheticals("Stadium Arcadium (Live)"),
            "Stadium Arcadium (Live)",
        )
        self.assertEqual(
            strip_noise_parentheticals("Track (Clean)"),
            "Track (Clean)",
        )

    def test_strips_explicit_and_remaster(self):
        self.assertEqual(strip_noise_parentheticals("Song (Explicit)"), "Song")
        self.assertEqual(
            strip_noise_parentheticals("Emit Remmus (2014 Remaster)"),
            "Emit Remmus",
        )

    def test_version_labels_only_allowed_three(self):
        self.assertEqual(
            strip_noise_parentheticals("A (Album Version)"),
            "A",
        )
        self.assertEqual(
            strip_noise_parentheticals("B (Single Version)"),
            "B",
        )
        self.assertEqual(
            strip_noise_parentheticals("C (Deluxe Edition)"),
            "C",
        )
        self.assertEqual(
            strip_noise_parentheticals("D (Radio Edit)"),
            "D (Radio Edit)",
        )

    def test_technical_and_score(self):
        self.assertEqual(strip_noise_parentheticals("X (Mono)"), "X")
        self.assertEqual(strip_noise_parentheticals("X (Stereo)"), "X")
        self.assertEqual(strip_noise_parentheticals("X (Hi-Res)"), "X")
        self.assertEqual(strip_noise_parentheticals("X (Digital Master)"), "X")
        self.assertEqual(strip_noise_parentheticals("X (Score)"), "X")
        self.assertEqual(
            strip_noise_parentheticals('Theme (From "The Movie")'),
            "Theme",
        )

    def test_anniversary_metadata_edition(self):
        self.assertEqual(
            strip_noise_parentheticals("Album (10th Anniversary Edition)"),
            "Album",
        )
        self.assertEqual(
            strip_noise_parentheticals("Album (Special Edition)"),
            "Album",
        )

    def test_feat_preserved_via_downloader_helper(self):
        self.assertEqual(
            _track_title_base_with_feat(
                "Night Song (feat. Guest MC) (Deluxe Edition)"
            ),
            "Night Song (feat. Guest MC)",
        )
        self.assertEqual(
            _track_title_base_with_feat("Radio [feat. Jane]"),
            "Radio [feat. Jane]",
        )

    def test_paren_content_should_strip_explicit_not_clean(self):
        self.assertTrue(paren_content_should_strip("Explicit"))
        self.assertFalse(paren_content_should_strip("Clean"))
        self.assertFalse(paren_content_should_strip("Hey Oh"))


if __name__ == "__main__":
    unittest.main()
