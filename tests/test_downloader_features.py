import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from qobuz_dl.downloader import (
    Download,
    _track_dict_for_lrclib,
    _track_metadata_display_title,
    _track_title_base_with_feat,
)
from qobuz_dl.utils import flac_fix_md5s, make_m3u


class DownloaderFeatureTests(unittest.TestCase):
    def test_make_m3u_writes_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            album_dir = os.path.join(tmp, "Albüm")
            os.makedirs(album_dir, exist_ok=True)
            mp3_path = os.path.join(album_dir, "Şarkı.mp3")
            with open(mp3_path, "wb") as f:
                f.write(b"fake")

            class FakeAudio:
                info = SimpleNamespace(length=201)

                def __getitem__(self, key):
                    if key == "TITLE":
                        return ["Şarkı"]
                    if key == "ARTIST":
                        return ["Sanatçı"]
                    raise KeyError(key)

            with patch("qobuz_dl.utils.EasyMP3", return_value=FakeAudio()):
                make_m3u(tmp)

            pl_path = os.path.join(tmp, os.path.basename(tmp) + ".m3u")
            with open(pl_path, "r", encoding="utf-8") as f:
                body = f.read()
            self.assertIn("Sanatçı - Şarkı", body)

    def test_flac_fix_md5s_missing_file(self):
        got = flac_fix_md5s("C:/does/not/exist.flac")
        self.assertFalse(got)

    def test_flac_fix_md5s_success(self):
        with patch("qobuz_dl.utils.os.path.isfile", return_value=True), patch(
            "qobuz_dl.utils.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stderr=""),
        ):
            got = flac_fix_md5s("C:/music/test.flac")
        self.assertTrue(got)

    def test_filename_attr_includes_extended_variables(self):
        track = {
            "id": 123,
            "title": "Track Name",
            "version": "Deluxe",
            "track_number": 3,
            "media_number": 2,
            "maximum_bit_depth": 24,
            "maximum_sampling_rate": 96,
            "isrc": "US1234567890",
            "release_date_original": "2024-01-12",
            "performer": {"name": "Artist"},
            "album": {
                "id": 999,
                "title": "Album Name",
                "url": "https://play.qobuz.com/album/999",
                "artist": {"name": "Artist"},
                "upc": "123456789012",
                "tracks_count": 10,
                "media_count": 2,
                "product_type": "album",
                "release_date_original": "2024-01-12",
            },
        }
        attrs = Download._get_filename_attr("Artist", track, "Track Name")
        self.assertEqual(attrs["track_number"], "03")
        self.assertEqual(attrs["disc_number"], "02")
        self.assertEqual(attrs["album_url"], "https://play.qobuz.com/album/999")
        self.assertEqual(attrs["barcode"], "123456789012")

    def test_track_title_base_with_feat_keeps_feat_drops_edition(self):
        self.assertEqual(
            _track_title_base_with_feat("Emit Remmus (2014 Remaster)"),
            "Emit Remmus",
        )
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

    def test_track_metadata_display_title_no_track_numbers(self):
        meta = {"title": "Emit Remmus", "track_number": 9}
        self.assertEqual(_track_metadata_display_title(meta), "Emit Remmus")

    def test_track_metadata_display_title_classical_work_prefix(self):
        meta = {"title": "Movement I", "work": "Symphony No. 9"}
        self.assertEqual(
            _track_metadata_display_title(meta), "Symphony No. 9: Movement I"
        )

    def test_track_metadata_display_title_feat_from_version_field(self):
        meta = {"title": "Hit Song", "version": "feat. Collaborator"}
        self.assertEqual(
            _track_metadata_display_title(meta), "Hit Song (feat. Collaborator)"
        )

    def test_track_dict_for_lrclib_fills_missing_nested_album(self):
        track = {
            "title": "Song",
            "version": "Alternate Version, 1987",
            "track_number": 1,
            "performer": {"name": "Artist"},
            "duration": 200,
        }
        release = {
            "title": "Album Name",
            "explicit": True,
            "parental_warning": True,
        }
        out = _track_dict_for_lrclib(track, release)
        self.assertEqual(out["title"], "Song (Alternate Version, 1987)")
        self.assertEqual(out["album"]["title"], "Album Name")
        self.assertTrue(out["album"].get("explicit"))

    def test_track_dict_for_lrclib_preserves_full_title_with_existing_album(self):
        track = {
            "title": "The Damage You've Done",
            "version": "Alternate Version, 1987",
            "performer": {"name": "Tom Petty & The Heartbreakers"},
            "duration": 247,
            "album": {"title": "An American Treasure (Deluxe)"},
        }
        out = _track_dict_for_lrclib(track, None)
        self.assertEqual(
            out["title"], "The Damage You've Done (Alternate Version, 1987)"
        )
        self.assertEqual(out["album"]["title"], "An American Treasure (Deluxe)")

    def test_stream_abort_falls_back_to_cancel_event(self):
        import tempfile
        import threading
        from unittest.mock import MagicMock

        ce = threading.Event()
        d = Download(MagicMock(), "1", tempfile.gettempdir(), 6, cancel_event=ce)
        self.assertFalse(d._stream_abort_is_set())
        ce.set()
        self.assertTrue(d._stream_abort_is_set())

    def test_stream_abort_uses_bound_event_not_cooperative_cancel(self):
        import tempfile
        import threading
        from unittest.mock import MagicMock

        ce = threading.Event()
        ae = threading.Event()
        d = Download(
            MagicMock(),
            "1",
            tempfile.gettempdir(),
            6,
            cancel_event=ce,
            abort_stream_event=ae,
        )
        ce.set()
        self.assertFalse(d._stream_abort_is_set())
        ae.set()
        self.assertTrue(d._stream_abort_is_set())

    def test_cooperative_stop_is_set_independent_of_stream_abort(self):
        import tempfile
        import threading
        from unittest.mock import MagicMock

        ce = threading.Event()
        ae = threading.Event()
        d = Download(
            MagicMock(),
            "1",
            tempfile.gettempdir(),
            6,
            cancel_event=ce,
            abort_stream_event=ae,
        )
        ce.set()
        self.assertTrue(d._cooperative_stop_is_set())
        self.assertFalse(d._stream_abort_is_set())

    def test_album_track_defers_lyrics_sidecar_when_executor_is_provided(self):
        from unittest.mock import MagicMock

        class FakeExecutor:
            def __init__(self):
                import concurrent.futures

                self.future = concurrent.futures.Future()
                self.future.set_result(None)
                self.submitted = None

            def submit(self, fn, *args, **kwargs):
                self.submitted = (fn, args, kwargs)
                return self.future

        track = {
            "id": 123,
            "title": "Track Name",
            "track_number": 1,
            "performer": {"name": "Artist"},
            "duration": 180,
        }
        album = {
            "id": 999,
            "title": "Album Name",
            "artist": {"name": "Artist"},
        }
        fake_fetch_ex = FakeExecutor()
        fake_sidecar_ex = FakeExecutor()
        pending = []
        client = MagicMock()
        d = Download(client, "999", tempfile.gettempdir(), 6, lyrics_enabled=True)

        def fake_tag(_tmp, _root, final_file, *_args, **_kwargs):
            with open(final_file, "wb") as f:
                f.write(b"audio")

        with tempfile.TemporaryDirectory() as tmp, patch(
            "qobuz_dl.downloader.tqdm_download"
        ), patch("qobuz_dl.downloader.metadata.tag_flac", side_effect=fake_tag), patch.object(
            d, "_write_track_lyrics_sidecar"
        ) as m_write:
            d._download_and_tag(
                tmp,
                1,
                {"url": "https://example.invalid/audio.flac"},
                track,
                album,
                False,
                False,
                lyrics_executor=fake_fetch_ex,
                lyrics_sidecar_executor=fake_sidecar_ex,
                lyrics_pending=pending,
            )

        m_write.assert_not_called()
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0].done())
        self.assertIsNotNone(fake_fetch_ex.submitted)
        self.assertIsNotNone(fake_sidecar_ex.submitted)
        _fn, args, kwargs = fake_sidecar_ex.submitted
        self.assertEqual(args[0], os.path.join(tmp, "01 - Track Name.flac"))
        self.assertEqual(args[1], track)
        self.assertEqual(args[2], album)
        self.assertIs(kwargs["lyrics_fetch_future"], fake_fetch_ex.future)

    def test_drain_deferred_lyrics_waits_for_pending_jobs(self):
        import concurrent.futures
        from unittest.mock import MagicMock

        client = MagicMock()
        d = Download(client, "999", tempfile.gettempdir(), 6, lyrics_enabled=True)
        future = concurrent.futures.Future()
        future.set_result(None)
        pending = [future]
        d._drain_deferred_lyrics(pending)

        self.assertEqual(pending, [])
        self.assertTrue(future.done())


if __name__ == "__main__":
    unittest.main()
