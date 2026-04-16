import unittest
from unittest.mock import patch

from qobuz_dl import lyrics


class LyricsTests(unittest.TestCase):
    def test_build_queries_contains_preferred_and_fallback(self):
        track = {
            "title": "Song Name (feat. Artist B)",
            "performer": {"name": "Artist A"},
            "album": {"title": "Album Name"},
        }
        preferred, fallback = lyrics._build_queries(track, prefer_explicit=False)
        self.assertTrue(preferred)
        self.assertTrue(fallback)
        self.assertEqual("Artist A - Song Name", preferred[0])
        self.assertIn("Artist A - Song Name", fallback[0])

    def test_fetch_returns_lrclib_hit(self):
        track = {
            "title": "Song Name",
            "performer": {"name": "Artist A"},
            "album": {"title": "Album Name"},
        }
        lrclib_hit = {
            "lyrics": "[00:10.00]line one\n[00:20.00]line two\n",
            "provider": "Lrclib",
            "query": "Artist A - Song Name",
            "lyrics_type": "synced",
            "explicit_matched": False,
            "fallback_used": False,
            "confidence": 88.0,
        }
        with patch("qobuz_dl.lyrics._fetch_lrclib", return_value=lrclib_hit):
            result = lyrics.fetch_synced_lyrics(track, prefer_explicit=False)
        self.assertIs(result, lrclib_hit)
        self.assertIn("[00:10.00]", result["lyrics"])

    def test_lyrics_type_never_instrumental_from_no_lyrics_phrase(self):
        """Plain provider text can contain \"no lyrics\" in real vocal lines; must not classify as instrumental."""
        text = "I've got bad news for you\nAnd we got no lyrics to waste on you\nNext line here"
        self.assertEqual(lyrics._lyrics_type(text), "plain")

    def test_lrc_last_end_seconds(self):
        lrc = "[00:01.00]a\n[01:30.50]b\n[02:05]c"
        self.assertAlmostEqual(lyrics._lrc_last_end_seconds(lrc), 125.0, places=3)

    def test_synced_lrc_exceeds_track_duration(self):
        lrc = (
            "[00:01.00]word\n"
            "[01:00.00]word\n"
            "[04:35.00]this line is long enough for latin check"
        )
        self.assertTrue(lyrics._synced_lrc_exceeds_track_duration(lrc, 90))
        self.assertFalse(lyrics._synced_lrc_exceeds_track_duration(lrc, 400))

    def test_instrumentalish_timestamps_only(self):
        lrc = "[00:00.00]\n[00:01.00]\n[00:02.00]\n"
        self.assertTrue(lyrics._is_instrumentalish_lyrics(lrc))
        self.assertEqual(lyrics._lyrics_type(lrc), "instrumental")

    def test_garbage_path_like_lyrics_rejected(self):
        self.assertTrue(
            lyrics._lyrics_looks_like_garbage(
                r'@c:\Users\peyto\Desktop\music\John Williams\album\01 - Main Title.lrc'
            )
        )
        self.assertFalse(
            lyrics._lyrics_looks_like_garbage(
                "[00:01.00]First line\n[00:05.20]Second line\n"
            )
        )

    def test_vocalish_word_count_strips_timestamps(self):
        words = " ".join([f"word{n}" for n in range(25)])
        text = f"[00:01.00]{words}\n[00:05.00]{words}"
        self.assertGreaterEqual(lyrics._vocalish_word_count(text), 18)

    def test_lrclib_get_demotes_instrumental_when_substantial_lyrics(self):
        track = {
            "title": "H.Y.B.",
            "performer": {"name": "J. Cole"},
            "album": {"title": "Might Delete Later"},
            "duration": 200,
        }
        body = " ".join(["word"] * 25)
        fake = {
            "instrumental": True,
            "syncedLyrics": "[00:01.00]" + body + "\n[00:05.00]" + body,
            "trackName": "H.Y.B.",
            "artistName": "J. Cole",
            "duration": 200,
        }

        class Resp:
            status_code = 200

            def json(self):
                return fake

        with patch("qobuz_dl.lyrics.requests.get", return_value=Resp()):
            got = lyrics._lrclib_get(track, timeout_sec=2.0)
        self.assertIsNotNone(got)
        result, conf = got
        self.assertNotEqual(result.get("lyrics_type"), "instrumental")
        self.assertGreater(conf, 50.0)

    def test_lrclib_get_rejects_instrumental_on_metadata_mismatch(self):
        track = {
            "title": "H.Y.B.",
            "performer": {"name": "J. Cole"},
            "album": {"title": "Might Delete Later"},
            "duration": 200,
        }
        fake = {
            "instrumental": True,
            "trackName": "Other Song",
            "artistName": "Other Artist",
            "duration": 200,
        }

        class Resp:
            status_code = 200

            def json(self):
                return fake

        with patch("qobuz_dl.lyrics.requests.get", return_value=Resp()):
            got = lyrics._lrclib_get(track, timeout_sec=2.0)
        self.assertIsNone(got)

    def test_lrclib_get_accepts_instrumental_match_without_lyrics(self):
        """LRCLIB instrumental=true with no text: accept when title/artist/duration align."""
        track = {
            "title": "H.Y.B.",
            "performer": {"name": "J. Cole"},
            "album": {"title": "Might Delete Later"},
            "duration": 235,
        }
        fake = {
            "instrumental": True,
            "trackName": "H.Y.B.",
            "artistName": "J. Cole",
            "duration": 235,
        }

        class Resp:
            status_code = 200

            def json(self):
                return fake

        with patch("qobuz_dl.lyrics.requests.get", return_value=Resp()):
            got = lyrics._lrclib_get(track, timeout_sec=2.0)
        self.assertIsNotNone(got)
        result, conf = got
        self.assertEqual(result.get("lyrics_type"), "instrumental")
        self.assertGreaterEqual(conf, 50.0)
        self.assertEqual((result.get("lyrics") or "").strip(), "")

    def test_fetch_returns_none_when_lrclib_misses(self):
        track = {
            "title": "Song Name",
            "performer": {"name": "Artist A"},
            "album": {"title": "Album Name"},
        }
        with patch("qobuz_dl.lyrics._fetch_lrclib", return_value=None):
            got = lyrics.fetch_synced_lyrics(
                track, prefer_explicit=False
            )
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
