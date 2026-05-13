import logging
import unittest

from qobuz_dl.app.events import GuiEventHub, GuiQueueHandler


class GuiEventHubTests(unittest.TestCase):
    def test_track_result_marker_emits_structured_event(self):
        hub = GuiEventHub()
        handler = GuiQueueHandler(hub)
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="[TRACK_RESULT] 01|Song|downloaded|ok|url|C:/a.flac|Album|11|22|1",
            args=(),
            exc_info=None,
        )

        stream = hub.stream()
        self.assertEqual(next(stream), "data: \n\n")
        handler.emit(record)
        got = next(stream)
        self.assertIn("event: status", got)
        self.assertIn('"type": "track_result"', got)
        self.assertIn('"slot_track_id": "11"', got)
        self.assertIn('"substitute_attach": true', got)
        stream.close()

    def test_error_record_calls_error_callback_and_session_log_is_clean(self):
        hub = GuiEventHub()
        calls = []
        handler = GuiQueueHandler(hub, on_error=lambda: calls.append(True))
        handler.setFormatter(logging.Formatter("%(message)s"))

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="\x1b[31mboom\x1b[0m",
            args=(),
            exc_info=None,
        )
        handler.emit(record)

        self.assertEqual(calls, [True])
        self.assertEqual(hub.session_log_text(), "boom")


if __name__ == "__main__":
    unittest.main()
