from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrackStarted:
    track_no: str
    title: str
    cover_url: str = ""
    lyric_artist: str = ""
    lyric_album: str = ""
    duration_sec: int = 0
    track_explicit: Optional[bool] = None


@dataclass(frozen=True)
class TrackFinished:
    track_no: str
    title: str
    status: str
    detail: str = ""
    source_url: str = ""
    audio_path: str = ""
    lyric_album: str = ""
    slot_track_id: str = ""
    release_album_id: str = ""


@dataclass(frozen=True)
class LyricsResolved:
    track_no: str
    title: str
    lyric_type: str
    provider: str = ""
    confidence: str = ""
    audio_path: str = ""
    destination: str = ""


@dataclass(frozen=True)
class UrlFinished:
    url: str
    ok: bool
    detail: str = ""
