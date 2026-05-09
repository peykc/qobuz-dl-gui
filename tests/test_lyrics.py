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

    def test_fetch_lrclib_prefers_search_synced_over_higher_confidence_get_plain(self):
        """Tier beats score: /api/search synced must win over /api/get plain even when plain scores higher."""
        track = {
            "title": "Same",
            "performer": {"name": "Artist"},
            "album": {"title": "Album"},
            "duration": 200,
        }
        got = lyrics._pack_result(
            "word " * 40,
            "Lrclib",
            "Artist - Same",
            "plain",
            explicit_matched=False,
            fallback_used=False,
            confidence=100.0,
            lrclib_id=1,
        )
        search_pick = lyrics._pack_result(
            "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
            "Lrclib",
            "Artist - Same",
            "synced",
            explicit_matched=False,
            fallback_used=True,
            confidence=90.0,
            lrclib_id=2,
        )
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=[]), patch(
            "qobuz_dl.lyrics._lrclib_get", return_value=(got, 100.0)
        ), patch("qobuz_dl.lyrics._lrclib_search_best", return_value=search_pick):
            out = lyrics._fetch_lrclib(track, timeout_sec=2.0)
        self.assertIsNotNone(out)
        self.assertEqual(out.get("lyrics_type"), "synced")
        self.assertIn("[00:01.00]", out.get("lyrics", ""))

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

    def test_instrumental_placeholder_lrc(self):
        s = lyrics.instrumental_placeholder_lrc()
        self.assertTrue(lyrics._is_synced_lrc(s))
        self.assertEqual(lyrics._lyrics_type(s), "instrumental")

    def test_lrclib_compact_row_duration_delta_ui_threshold(self):
        rec = {
            "id": 42,
            "trackName": "T",
            "artistName": "A",
            "albumName": "Al",
            "duration": 180,
            "syncedLyrics": "[00:01.00]x",
        }
        near = lyrics._compact_lrclib_search_row(rec, 181, "T", "A", "Al")
        self.assertIsNotNone(near)
        self.assertIsNone(near["delta_sec"])
        self.assertIn("lyrics_explicit", near)
        self.assertIn("confidence", near)
        self.assertIsInstance(near["confidence"], (int, float))
        far = lyrics._compact_lrclib_search_row(rec, 100, "T", "A", "Al")
        self.assertIsNotNone(far)
        self.assertEqual(far["delta_sec"], 80)
        self.assertIn("confidence", far)

    def test_lrclib_compact_row_confidence_penalizes_album_mismatch(self):
        rec_match = {
            "id": 1,
            "trackName": "Best Mode (feat. PnB Rock & YoungBoy Never Broke Again)",
            "artistName": "A Boogie Wit da Hoodie",
            "albumName": "The Bigger Artist",
            "duration": 209,
            "syncedLyrics": "[00:01.00]line\n[00:05.00]line\n",
        }
        rec_mismatch = dict(rec_match)
        rec_mismatch["id"] = 2
        rec_mismatch["albumName"] = "A Boogie Wit da Hoodie"
        want_title = "Best Mode (feat. PnB Rock & YoungBoy Never Broke Again)"
        want_artist = "A Boogie Wit da Hoodie"
        want_album = "The Bigger Artist"
        a = lyrics._compact_lrclib_search_row(
            rec_match, 209, want_title, want_artist, want_album
        )
        b = lyrics._compact_lrclib_search_row(
            rec_mismatch, 209, want_title, want_artist, want_album
        )
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertGreater(a["confidence"], b["confidence"])
        self.assertLess(b["confidence"], 95.0)

    def test_pack_result_confidence_reconciles_with_search_row_metadata(self):
        """GET may agree on album while /api/search lists another album string for the same id."""
        track = {
            "title": "H.Y.B.",
            "performer": {"name": "J. Cole"},
            "album": {"title": "Might Delete Later"},
            "duration": 200,
        }
        rec = {
            "id": 999,
            "trackName": "H.Y.B. (feat. Bas)",
            "artistName": "J. Cole",
            "albumName": "Bas & J. Cole",
            "duration": 200,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n",
        }
        packed = {
            "lyrics": rec["syncedLyrics"],
            "confidence": 100.0,
            "lrclib_id": 999,
            "lyrics_type": "synced",
        }
        compact = lyrics._compact_lrclib_search_row(
            rec, 200, "H.Y.B.", "J. Cole", "Might Delete Later"
        )
        self.assertIsNotNone(compact)
        out = lyrics._reconcile_pack_result_confidence_with_search_rows(
            track, packed, [rec]
        )
        self.assertEqual(out["confidence"], compact["confidence"])
        self.assertLess(float(out["confidence"]), 95.0)

    def test_lyrics_explicit_wordlist_heuristic(self):
        self.assertFalse(lyrics.lyrics_text_indicates_explicit("hello world"))
        self.assertFalse(lyrics.lyrics_text_indicates_explicit("class dismissed"))
        self.assertTrue(lyrics.lyrics_text_indicates_explicit("what the fuck"))
        self.assertTrue(lyrics.lyrics_text_indicates_explicit("[00:01.00] oh shit\n"))

    def test_qobuz_track_is_explicit(self):
        self.assertTrue(
            lyrics.qobuz_track_is_explicit(
                {"title": "X", "explicit": True, "album": {"title": "A"}}
            )
        )
        self.assertTrue(
            lyrics.qobuz_track_is_explicit(
                {"title": "X", "album": {"title": "A", "parental_warning": True}}
            )
        )
        self.assertFalse(
            lyrics.qobuz_track_is_explicit(
                {"title": "X", "album": {"title": "A"}}
            )
        )

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

    def test_lrclib_get_rejects_when_response_album_metadata_wrong(self):
        """``/api/get`` can still return a row whose ``albumName`` does not match the query."""
        track = {
            "title": "Fever",
            "performer": {"name": "J. Cole"},
            "album": {"title": "Might Delete Later"},
            "duration": 200,
        }
        fake = {
            "trackName": "Fever",
            "artistName": "J. Cole",
            "albumName": "J. Cole",
            "duration": 200,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
        }

        class Resp:
            status_code = 200

            def json(self):
                return fake

        with patch("qobuz_dl.lyrics.requests.get", return_value=Resp()):
            got = lyrics._lrclib_get(track, timeout_sec=2.0)
        self.assertIsNone(got)

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

    def test_fetch_with_search_fallback_returns_strict_hit_immediately(self):
        track = {
            "title": "Song Name",
            "performer": {"name": "Artist A"},
            "album": {"title": "Album Name"},
        }
        strict = {
            "lyrics": "[00:01.00]line\n[00:05.00]line\n",
            "provider": "Lrclib",
            "lyrics_type": "synced",
            "confidence": 95.0,
        }
        with patch(
            "qobuz_dl.lyrics._fetch_lrclib_result_and_rows",
            return_value=(strict, []),
        ), patch("qobuz_dl.lyrics._lrclib_search_raw") as m_search:
            out = lyrics.fetch_synced_lyrics_with_search_fallback(
                track, prefer_explicit=False, timeout_sec=2.0
            )
        self.assertIs(out, strict)
        m_search.assert_not_called()

    def test_fetch_with_search_fallback_uses_top_candidate_id_when_strict_misses(self):
        track = {
            "title": "Song Name",
            "performer": {"name": "Artist A"},
            "album": {"title": "Album Name"},
            "duration": 200,
            "explicit": True,
        }
        rows = [
            {
                "id": 10,
                "trackName": "Song Name",
                "artistName": "Artist A",
                "albumName": "Album Name",
                "duration": 200,
            },
            {
                "id": 11,
                "trackName": "Song Name",
                "artistName": "Artist A",
                "albumName": "Album Name",
                "duration": 201,
            },
        ]
        detail = {
            "syncedLyrics": "[00:01.00]line one\n[00:04.00]line two\n",
            "plainLyrics": "",
        }
        with patch(
            "qobuz_dl.lyrics._fetch_lrclib_result_and_rows",
            return_value=(None, []),
        ), patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=rows), patch(
            "qobuz_dl.lyrics.lrclib_get_by_id", return_value=detail
        ) as m_get:
            out = lyrics.fetch_synced_lyrics_with_search_fallback(
                track, prefer_explicit=True, timeout_sec=2.0, max_fallback_candidates=3
            )
        self.assertIsNotNone(out)
        self.assertEqual((out or {}).get("provider"), "Lrclib search fallback")
        self.assertTrue(bool((out or {}).get("search_fallback_used")))
        self.assertEqual((out or {}).get("lrclib_id"), 10)
        self.assertEqual(m_get.call_count, 1)

    def test_fetch_with_search_fallback_skips_explicit_rows_for_clean_track(self):
        track = {
            "title": "Song Name",
            "performer": {"name": "Artist A"},
            "album": {"title": "Album Name"},
            "duration": 200,
            "explicit": False,
        }
        rows = [
            {
                "id": 10,
                "trackName": "Song Name",
                "artistName": "Artist A",
                "albumName": "Album Name",
                "duration": 200,
            }
        ]
        detail = {
            "syncedLyrics": "[00:01.00]what the fuck\n[00:04.00]line two\n",
            "plainLyrics": "",
        }
        with patch(
            "qobuz_dl.lyrics._fetch_lrclib_result_and_rows",
            return_value=(None, []),
        ), patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=rows), patch(
            "qobuz_dl.lyrics.lrclib_get_by_id", return_value=detail
        ):
            out = lyrics.fetch_synced_lyrics_with_search_fallback(
                track, prefer_explicit=False, timeout_sec=2.0, max_fallback_candidates=3
            )
        self.assertIsNone(out)

    def test_fetch_with_search_fallback_reuses_strict_search_rows(self):
        track = {
            "title": "Song Name",
            "performer": {"name": "Artist A"},
            "album": {"title": "Album Name"},
            "duration": 200,
            "explicit": True,
        }
        strict_rows = [
            {
                "id": 10,
                "trackName": "Song Name",
                "artistName": "Artist A",
                "albumName": "Album Name",
                "duration": 200,
                "syncedLyrics": "[00:01.00]line one\n[00:04.00]line two\n",
                "plainLyrics": "",
            }
        ]
        with patch(
            "qobuz_dl.lyrics._fetch_lrclib_result_and_rows",
            return_value=(None, strict_rows),
        ), patch("qobuz_dl.lyrics._lrclib_search_raw") as m_search, patch(
            "qobuz_dl.lyrics.lrclib_get_by_id"
        ) as m_get:
            out = lyrics.fetch_synced_lyrics_with_search_fallback(
                track, prefer_explicit=True, timeout_sec=2.0, max_fallback_candidates=3
            )
        self.assertIsNotNone(out)
        self.assertEqual((out or {}).get("lrclib_id"), 10)
        self.assertTrue(bool((out or {}).get("search_fallback_used")))
        m_search.assert_not_called()
        m_get.assert_not_called()

    def test_lrclib_search_best_prefers_relevance_not_merge_order(self):
        """The correct UTOPIA row must be considered even if API merge order places it after index 20."""

        def _noise(i: int) -> dict:
            return {
                "id": i,
                "trackName": f"Other Song {i}",
                "artistName": "Unrelated",
                "albumName": "Somewhere",
                "duration": 100,
                "syncedLyrics": "[00:01.00]aa\n[00:02.00]bb\n",
            }

        want = {
            "id": 9001,
            "trackName": "MELTDOWN",
            "artistName": "Travis Scott",
            "albumName": "UTOPIA",
            "duration": 246,
            "syncedLyrics": "[00:01.00]line one here\n[00:05.00]line two here\n",
        }
        merged = [_noise(i) for i in range(28)] + [want]
        track = {
            "title": "MELTDOWN",
            "performer": {"name": "Travis Scott"},
            "album": {"title": "UTOPIA"},
            "duration": 246,
        }
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=merged):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNotNone(out)
        self.assertIn("line one here", (out or {}).get("lyrics", ""))
        self.assertIn("Lrclib", (out or {}).get("provider", ""))
        self.assertEqual((out or {}).get("lyrics_type"), "synced")

    def test_lrclib_search_prefers_synced_over_higher_confidence_plain(self):
        """Plain-only row must not win when a lower-scoring synced LRC exists."""
        plain_high = {
            "id": 1,
            "trackName": "Same",
            "artistName": "Artist",
            "albumName": "Album",
            "duration": 200,
            "plainLyrics": "word " * 40,
            "syncedLyrics": "",
        }
        synced_ok = {
            "id": 2,
            "trackName": "Same",
            "artistName": "Artist",
            "albumName": "Album",
            "duration": 200,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
            "plainLyrics": "",
        }
        track = {
            "title": "Same",
            "performer": {"name": "Artist"},
            "album": {"title": "Album"},
            "duration": 200,
        }
        merged = [plain_high, synced_ok]
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=merged):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNotNone(out)
        self.assertEqual((out or {}).get("lyrics_type"), "synced")
        self.assertIn("[00:01.00]", (out or {}).get("lyrics", ""))

    def test_lrclib_search_plain_wins_when_synced_has_wrong_album(self):
        """Synced LRC with bogus album metadata must not beat plain on the real release."""
        plain_release = {
            "id": 101,
            "trackName": "Fever",
            "artistName": "J. Cole",
            "albumName": "Might Delete Later",
            "duration": 200,
            "plainLyrics": "word " * 40,
            "syncedLyrics": "",
        }
        synced_mirror_bad_album = {
            "id": 202,
            "trackName": "Fever",
            "artistName": "J. Cole",
            "albumName": "J. Cole",
            "duration": 200,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
            "plainLyrics": "",
        }
        track = {
            "title": "Fever",
            "performer": {"name": "J. Cole"},
            "album": {"title": "Might Delete Later"},
            "duration": 200,
        }
        merged = [synced_mirror_bad_album, plain_release]
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=merged):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNotNone(out)
        self.assertEqual((out or {}).get("lyrics_type"), "plain")
        self.assertNotIn("[00:01.00]", (out or {}).get("lyrics", ""))
        self.assertEqual((out or {}).get("lrclib_id"), 101)

    def test_lrclib_search_rejects_unversioned_row_for_versioned_qobuz_title(self):
        """Auto attach should prefer no lyrics over a same-duration row for a different version."""
        track = {
            "title": "The Damage You've Done (Alternate Version, 1987)",
            "performer": {"name": "Tom Petty & The Heartbreakers"},
            "album": {"title": "An American Treasure (Deluxe)"},
            "duration": 247,
        }
        wrong_version = {
            "id": 303,
            "trackName": "The Damage You've Done",
            "artistName": "Tom Petty & The Heartbreakers",
            "albumName": "An American Treasure (2)",
            "duration": 247,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
            "plainLyrics": "",
        }
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=[wrong_version]):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNone(out)

    def test_lrclib_search_allows_matching_version_qualifier(self):
        track = {
            "title": "The Damage You've Done (Alternate Version, 1987)",
            "performer": {"name": "Tom Petty & The Heartbreakers"},
            "album": {"title": "An American Treasure (Deluxe)"},
            "duration": 247,
        }
        right_version = {
            "id": 304,
            "trackName": "The Damage You've Done (Alternate Version)",
            "artistName": "Tom Petty & The Heartbreakers",
            "albumName": "An American Treasure (Deluxe)",
            "duration": 247,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
            "plainLyrics": "",
        }
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=[right_version]):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNotNone(out)
        self.assertEqual((out or {}).get("lrclib_id"), 304)

    def test_lrclib_search_rejects_generic_version_overlap_only(self):
        track = {
            "title": "The Damage You've Done (Alternate Version, 1987)",
            "performer": {"name": "Tom Petty & The Heartbreakers"},
            "album": {"title": "An American Treasure (Deluxe)"},
            "duration": 247,
        }
        wrong_version = {
            "id": 306,
            "trackName": "The Damage You've Done (Live Version)",
            "artistName": "Tom Petty & The Heartbreakers",
            "albumName": "An American Treasure (Deluxe)",
            "duration": 247,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
            "plainLyrics": "",
        }
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=[wrong_version]):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNone(out)

    def test_lrclib_search_still_ignores_feat_parenthetical(self):
        track = {
            "title": "Best Mode (feat. Guest)",
            "performer": {"name": "Artist"},
            "album": {"title": "Album"},
            "duration": 200,
        }
        row = {
            "id": 305,
            "trackName": "Best Mode",
            "artistName": "Artist",
            "albumName": "Album",
            "duration": 200,
            "syncedLyrics": "[00:01.00]one\n[00:05.00]two\n[00:09.00]three\n",
            "plainLyrics": "",
        }
        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=[row]):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNotNone(out)
        self.assertEqual((out or {}).get("lrclib_id"), 305)

    def test_lrclib_search_hydrates_via_get_when_search_omits_lyrics(self):
        """Search JSON can lack bodies; GET /api/get/{{id}} must still supply LRC text."""
        track = {
            "title": "MELTDOWN",
            "performer": {"name": "Travis Scott"},
            "album": {"title": "UTOPIA"},
            "duration": 246,
        }
        search_row = {
            "id": 4242,
            "trackName": "MELTDOWN",
            "artistName": "Travis Scott",
            "albumName": "UTOPIA",
            "duration": 246,
            "syncedLyrics": "",
            "plainLyrics": "",
        }
        detail = {
            "syncedLyrics": (
                "[00:01.00]line one here\n[00:05.00]line two here\n[00:09.00]line three here\n"
            ),
            "plainLyrics": "",
            "duration": 246,
        }

        with patch("qobuz_dl.lyrics._lrclib_search_raw", return_value=[search_row]), patch(
            "qobuz_dl.lyrics.lrclib_get_by_id", return_value=detail
        ):
            out = lyrics._lrclib_search_best(track, timeout_sec=2.0)
        self.assertIsNotNone(out)
        self.assertEqual((out or {}).get("lyrics_type"), "synced")
        self.assertIn("line one here", (out or {}).get("lyrics", ""))

if __name__ == "__main__":
    unittest.main()
