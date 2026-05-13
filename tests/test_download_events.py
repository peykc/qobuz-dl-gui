import unittest

from qobuz_dl.download.events import (
    LyricsResolved,
    TrackFinished,
    TrackStarted,
    UrlFinished,
)


class DownloadEventModelTests(unittest.TestCase):
    def test_track_events_keep_release_slot_and_artifact_identity_separate(self):
        started = TrackStarted(
            track_no="01",
            title="Original Slot",
            lyric_album="Album",
            track_explicit=False,
        )
        finished = TrackFinished(
            track_no=started.track_no,
            title=started.title,
            status="downloaded",
            audio_path="Album/01 - Substitute.flac",
            slot_track_id="slot-1",
            release_album_id="album-1",
        )

        self.assertEqual(finished.slot_track_id, "slot-1")
        self.assertEqual(finished.release_album_id, "album-1")
        self.assertIn("Substitute", finished.audio_path)

    def test_lyrics_and_url_events_are_explicit_about_outcome(self):
        lyrics = LyricsResolved(
            track_no="01",
            title="Track",
            lyric_type="synced",
            provider="Lrclib",
            confidence="98",
            destination="lrc",
        )
        done = UrlFinished(url="https://play.qobuz.com/album/1", ok=True)

        self.assertEqual(lyrics.destination, "lrc")
        self.assertTrue(done.ok)


if __name__ == "__main__":
    unittest.main()
