"""Stable GUI download-history list order vs ``updated_at`` (lyric/metadata bumps)."""
import os
import tempfile
import unittest
from unittest.mock import patch

from qobuz_dl import db
from qobuz_dl.db import (
    GUI_PENDING_TRACK_PREFIX,
    list_gui_download_history,
    upsert_gui_download_history,
    update_gui_download_history_lyrics,
)


class GuiDownloadHistorySeqTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    @patch.object(db, "get_qobuz_db_path")
    def test_pending_rows_keep_order_sorted_by_history_seq_not_updated_at(self, mock_gp):
        mock_gp.return_value = self.db_path
        a = f"{GUI_PENDING_TRACK_PREFIX}111111"
        b = f"{GUI_PENDING_TRACK_PREFIX}222222"
        upsert_gui_download_history(a, title="First", download_status="purchase_only")
        upsert_gui_download_history(b, title="Second", download_status="failed")

        lst = list_gui_download_history()
        titles = [x["title"] for x in lst]
        self.assertEqual(titles, ["First", "Second"])

    @patch.object(db, "get_qobuz_db_path")
    def test_lyric_metadata_update_does_not_reorder_previous_row(self, mock_gp):
        mock_gp.return_value = self.db_path

        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)

        pa = os.path.join(td.name, "a.flac")
        pb = os.path.join(td.name, "b.flac")
        for p in (pa, pb):
            with open(p, "wb") as f:
                f.write(b"f")

        upsert_gui_download_history(pa, title="Track A")
        upsert_gui_download_history(pb, title="Track B")

        list_gui_download_history()  # materialize migrations

        update_gui_download_history_lyrics(
            pa,
            lyric_type="synced",
            lyric_provider="t",
            lyric_confidence="100",
        )

        lst = list_gui_download_history()
        titles = [x["title"] for x in lst]
        self.assertEqual(titles, ["Track A", "Track B"])


if __name__ == "__main__":
    unittest.main()
