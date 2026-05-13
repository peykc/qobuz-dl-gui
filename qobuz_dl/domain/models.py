from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class QobuzTrack:
    id: str
    title: str = ""
    artist: str = ""
    album: str = ""
    explicit: Optional[bool] = None


@dataclass(frozen=True)
class ReleaseSlot:
    track_id: str
    album_id: str = ""
    track_no: str = ""
    title: str = ""


@dataclass(frozen=True)
class TrackResolution:
    status: str
    detail: str = ""
    source_url: str = ""
    audio_path: str = ""


@dataclass(frozen=True)
class LocalAudioFile:
    audio_path: str
    title: str = ""
    album: str = ""
    duration_sec: int = 0


@dataclass(frozen=True)
class HistoryRow:
    audio_path: str
    track_no: str = ""
    title: str = ""
    lyric_album: str = ""
    download_status: str = "downloaded"
    slot_track_id: str = ""
    release_album_id: str = ""


@dataclass(frozen=True)
class LyricCandidate:
    id: int
    track_name: str = ""
    artist_name: str = ""
    album_name: str = ""
    kind: str = ""
    confidence: Optional[float] = None
