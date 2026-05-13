import json
import logging
import queue
import re
import threading
from collections import deque


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


class GuiEventHub:
    """Fan out GUI log lines and structured status events to SSE consumers."""

    def __init__(self, session_log_limit: int = 600):
        self._queues = []
        self._lock = threading.Lock()
        self._session_log_lines = deque(maxlen=session_log_limit)

    def append_session_log(self, line: str) -> None:
        clean = (line or "").strip()
        if not clean:
            return
        with self._lock:
            self._session_log_lines.append(clean)

    def session_log_text(self) -> str:
        with self._lock:
            return "\n".join(self._session_log_lines)

    def emit_event(self, event_data: dict) -> None:
        with self._lock:
            for q in self._queues:
                try:
                    q.put_nowait(event_data)
                except queue.Full:
                    pass

    def emit_log_line(self, line: str) -> None:
        with self._lock:
            for q in self._queues:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass

    def drain_queues(self) -> None:
        with self._lock:
            for q in self._queues:
                while not q.empty():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break

    def stream(self):
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._queues.append(q)
        try:
            yield "data: \n\n"
            while True:
                try:
                    msg = q.get(timeout=20)
                    if isinstance(msg, dict):
                        yield f"event: status\ndata: {json.dumps(msg)}\n\n"
                    else:
                        clean = ANSI_RE.sub("", msg)
                        yield f"data: {clean}\n\n"
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            with self._lock:
                try:
                    self._queues.remove(q)
                except ValueError:
                    pass


class GuiQueueHandler(logging.Handler):
    """Convert downloader log markers into GUI events and readable log lines."""

    def __init__(self, hub: GuiEventHub, on_error=None):
        super().__init__()
        self.hub = hub
        self.on_error = on_error or (lambda: None)

    def emit(self, record):
        msg = self.format(record)
        if record.levelno >= logging.ERROR:
            self.on_error()

        clean = ANSI_RE.sub("", msg).strip()
        self.hub.append_session_log(clean)

        if clean.startswith("[TRACK_START] "):
            self._emit_track_start(clean[len("[TRACK_START] ") :])
            return
        if clean.startswith("[TRACK_RESULT] "):
            self._emit_track_result(clean[len("[TRACK_RESULT] ") :])
            return
        if clean.startswith("[TRACK_LYRICS] "):
            self._emit_track_lyrics(clean[len("[TRACK_LYRICS] ") :])
            return

        self.hub.emit_log_line(msg)

    def _emit_track_start(self, payload: str) -> None:
        if "|" in payload:
            parts = payload.split("|")
            track_no = parts[0].strip()
            title = parts[1].strip() if len(parts) > 1 else ""
            cover_url = parts[2].strip() if len(parts) > 2 else ""
            ev_data = {
                "type": "track_start",
                "track_no": track_no,
                "title": title,
                "cover_url": cover_url,
            }
            if len(parts) >= 6:
                ev_data["lyric_artist"] = parts[3].strip()
                ev_data["lyric_album"] = parts[4].strip()
                try:
                    ev_data["duration_sec"] = int(parts[5].strip() or 0)
                except ValueError:
                    ev_data["duration_sec"] = 0
                if len(parts) >= 7:
                    ev_data["track_explicit"] = parts[6].strip() in (
                        "1",
                        "true",
                        "True",
                    )
            self.hub.emit_event(ev_data)
            self.hub.emit_log_line(f"  \u2193 {track_no}. {title}".strip())
            return

        self.hub.emit_event({"type": "track_start", "title": payload})
        self.hub.emit_log_line(f"  \u2193 {payload}")

    def _emit_track_result(self, payload: str) -> None:
        parts = payload.split("|")
        if len(parts) < 4:
            return
        track_no, title, status, detail = (
            parts[0],
            parts[1],
            parts[2],
            parts[3],
        )
        queue_url = parts[4].strip() if len(parts) >= 5 else ""
        if queue_url == "-":
            queue_url = ""
        audio_path = parts[5].strip() if len(parts) >= 6 else ""
        lyric_album = parts[6].strip() if len(parts) >= 7 else ""
        slot_track_id = parts[7].strip() if len(parts) >= 8 else ""
        release_album_id = parts[8].strip() if len(parts) >= 9 else ""
        substitute_attach = len(parts) > 9 and parts[9].strip() == "1"

        ev = {
            "type": "track_result",
            "track_no": track_no,
            "title": title,
            "status": status,
            "detail": detail,
        }
        if queue_url:
            ev["source_url"] = queue_url
        if audio_path:
            ev["audio_path"] = audio_path
        if lyric_album:
            ev["lyric_album"] = lyric_album
        if slot_track_id:
            ev["slot_track_id"] = slot_track_id
        if release_album_id:
            ev["release_album_id"] = release_album_id
        if substitute_attach:
            ev["substitute_attach"] = True
        self.hub.emit_event(ev)

    def _emit_track_lyrics(self, payload: str) -> None:
        parts = payload.split("|")
        if len(parts) < 4:
            return
        track_no, title, lyric_type, provider = (
            parts[0],
            parts[1],
            parts[2],
            parts[3],
        )
        confidence = parts[4] if len(parts) >= 5 else ""
        audio_path_lyrics = parts[5].strip() if len(parts) >= 6 else ""
        lyric_destination = parts[6].strip() if len(parts) >= 7 else ""
        ev_ly = {
            "type": "track_lyrics",
            "track_no": track_no,
            "title": title,
            "lyric_type": lyric_type,
            "provider": provider,
            "confidence": confidence,
        }
        if audio_path_lyrics:
            ev_ly["audio_path"] = audio_path_lyrics
        if lyric_destination:
            ev_ly["lyric_destination"] = lyric_destination
        self.hub.emit_event(ev_ly)
