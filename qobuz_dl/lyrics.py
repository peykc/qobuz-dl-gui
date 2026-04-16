"""Synced/plain lyrics via LRCLIB public API only (https://lrclib.net/api/).

Server behaviour matches the open-source LRCLIB project (see ``lrclib-main/`` in this
repo for reference). We do not bundle third-party scraper providers.
"""
import os
import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import requests

_TIMESTAMP_RE = re.compile(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]")
_LRC_TS_CAPTURE = re.compile(
    r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]",
)
_FEATURE_RE = re.compile(r"\((?:feat|ft)\.? [^)]+\)", flags=re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_LINE_META_RE = re.compile(r"^\[[^\]]+\]\s*", flags=re.MULTILINE)
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")
# Windows paths, @file refs, or lyrics that are mostly a single path line
_PATH_LIKE_RE = re.compile(
    r"(?:"
    r"[A-Za-z]:\\"
    r"|file://"
    r"|^@\s*[A-Za-z]:"
    r"|^/\w:/"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
_SOUNDTRACK_CUE_RE = re.compile(
    r'\(from\s+["\']|/score\)\s*$|\(score\)|original motion picture|soundtrack',
    re.IGNORECASE,
)

LRCLIB_UA = {"User-Agent": "Qobuz-DL-GUI/1.1 (https://github.com/peykc/qobuz-dl-gui)"}


def _normalize_piece(value: str) -> str:
    value = (value or "").strip()
    value = _FEATURE_RE.sub("", value)
    value = _WHITESPACE_RE.sub(" ", value)
    return value.strip(" -")


def _normalize_for_match(s: str) -> str:
    s = _normalize_piece(s).lower()
    s = re.sub(r"\s*\([^)]*\)", " ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s


def _token_overlap(a: str, b: str) -> float:
    ta = set(_normalize_for_match(a).split())
    tb = set(_normalize_for_match(b).split())
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / max(len(ta), len(tb))


def _title_artist_similarity(
    want_title: str,
    want_artist: str,
    got_title: str,
    got_artist: str,
) -> float:
    t = 0.65 * SequenceMatcher(
        None, _normalize_for_match(want_title), _normalize_for_match(got_title)
    ).ratio() + 0.35 * _token_overlap(want_title, got_title)
    if want_artist and got_artist:
        a = SequenceMatcher(
            None, _normalize_for_match(want_artist), _normalize_for_match(got_artist)
        ).ratio()
        return 0.55 * t + 0.45 * a
    return t


def _duration_score(want_sec: int, got_sec: int) -> float:
    if want_sec <= 0 or got_sec <= 0:
        return 0.75
    delta = abs(want_sec - got_sec)
    if delta <= 2:
        return 1.0
    if delta <= 8:
        return 0.85
    if delta <= 20:
        return 0.55
    return 0.25


def _is_synced_lrc(lyrics: str) -> bool:
    return bool(_TIMESTAMP_RE.search(lyrics or ""))


def _looks_latin_enough(lyrics_text: str, min_ratio: float = 0.70) -> bool:
    text = _LINE_META_RE.sub("", (lyrics_text or ""))
    chars = [c for c in text if c.isalpha() or _ALNUM_RE.match(c)]
    if not chars:
        return True
    latinish = 0
    for c in chars:
        if ("A" <= c <= "Z") or ("a" <= c <= "z") or ("0" <= c <= "9"):
            latinish += 1
    return (latinish / max(1, len(chars))) >= min_ratio


def _lyrics_looks_like_garbage(text: str) -> bool:
    """Reject provider junk (paths, single-line file refs, etc.)."""
    raw = (text or "").strip()
    if not raw:
        return True
    if _PATH_LIKE_RE.search(raw):
        return True
    lines = [ln.strip() for ln in raw.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not lines:
        return True
    joined = " ".join(lines).lower()
    if len(lines) <= 3 and any(
        ext in joined for ext in (".mp3", ".flac", ".m4a", ".wav", ".ogg")
    ):
        return True
    if len(lines) == 1 and len(raw) < 260 and ("\\" in raw or "/" in raw):
        return True
    return False


def _min_synced_lines(text: str) -> int:
    return len(_TIMESTAMP_RE.findall(text or ""))


def _lrc_last_end_seconds(lyrics_text: str) -> float:
    """Latest end time in seconds from LRC timestamp tags (mm:ss or mm:ss.xx)."""
    mx = 0.0
    for m in _LRC_TS_CAPTURE.finditer(lyrics_text or ""):
        mm, ss = int(m.group(1)), int(m.group(2))
        frac = 0.0
        if m.group(3):
            frac = int(m.group(3).ljust(3, "0")[:3]) / 1000.0
        mx = max(mx, mm * 60.0 + ss + frac)
    return mx


def _synced_lrc_exceeds_track_duration(lyrics_text: str, dur_sec: int) -> bool:
    """True when synced LRC runs much longer than the track (wrong match)."""
    if dur_sec < 35 or not _is_synced_lrc(lyrics_text):
        return False
    end_sec = _lrc_last_end_seconds(lyrics_text)
    return end_sec > 0.0 and end_sec > dur_sec * 1.22 + 10.0


def _vocalish_word_count(text: str) -> int:
    """Rough count of lyric-like tokens (filters timestamps)."""
    body = _LINE_META_RE.sub("", text or "")
    return len(re.findall(r"[A-Za-z]{3,}", body))


def _is_likely_soundtrack_cue(track: Dict) -> bool:
    title = (track.get("title") or "") + " " + (track.get("album") or {}).get("title", "")
    return bool(_SOUNDTRACK_CUE_RE.search(title))


def _confidence_from_match(
    similarity: float,
    duration_part: float,
    source: str,
    synced: bool,
    soundtrack_penalty: bool,
) -> float:
    base = 100.0 * (0.55 * similarity + 0.35 * duration_part + 0.10 * (1.0 if synced else 0.85))
    if source == "Lrclib":
        base = min(100.0, base + 5.0)
    if soundtrack_penalty and similarity < 0.92:
        base *= 0.85
    return max(0.0, min(100.0, base))


def _build_queries(track: Dict, prefer_explicit: Optional[bool]) -> Tuple[List[str], List[str]]:
    title = _normalize_piece(track.get("title", ""))
    performer = _normalize_piece(
        track.get("performer", {}).get("name")
        or track.get("album", {}).get("artist", {}).get("name")
        or ""
    )
    album = _normalize_piece(track.get("album", {}).get("title", ""))

    base_candidates = [
        f"{performer} - {title}" if performer and title else "",
        f"{title} {performer}".strip(),
        f"{title} {album}".strip(),
    ]
    base = [q for q in dict.fromkeys(base_candidates) if q]
    preferred = base[:1] if base else []
    return preferred, base


def _normalize_lrc_text(lyrics: str) -> str:
    text = (lyrics or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text + "\n" if text else text


def _is_instrumentalish_lyrics(text: str) -> bool:
    """True when text has almost no lyric words (OST timing / tags / trailing only).

    Avoids the old substring heuristic on \"no lyrics\" in normal verses. Uses
    word count and optional (instrumental) / bracket tags only after stripping LRC.
    """
    t = (text or "").strip()
    if not t:
        return True
    if _vocalish_word_count(t) >= 10:
        return False
    bare = _LINE_META_RE.sub("", t)
    bare = re.sub(r"\[[^\]]+\]", "", bare)
    bare = re.sub(r"\([^)]*instrumental[^)]*\)", "", bare, flags=re.I).strip()
    bare = _WHITESPACE_RE.sub(" ", bare).strip()
    if not bare:
        return True
    return _vocalish_word_count(bare) < 3


def _lyrics_type(lyrics_text: str) -> str:
    """Classify lyrics for UI / sidecar."""
    text = (lyrics_text or "").strip()
    if not text:
        return "none"
    if _is_synced_lrc(text):
        if _is_instrumentalish_lyrics(text):
            return "instrumental"
        return "synced"
    if _is_instrumentalish_lyrics(text):
        return "instrumental"
    return "plain"


def _pack_result(
    lyrics: str,
    provider: str,
    query: str,
    lyrics_type: str,
    *,
    explicit_matched: bool,
    fallback_used: bool,
    confidence: float,
) -> Dict[str, object]:
    return {
        "lyrics": _normalize_lrc_text(lyrics),
        "provider": provider,
        "query": query,
        "lyrics_type": lyrics_type,
        "explicit_matched": explicit_matched,
        "fallback_used": fallback_used,
        "confidence": round(confidence, 1),
    }


def _lrclib_get(track: Dict, timeout_sec: float) -> Optional[Tuple[Dict, float]]:
    artist = _normalize_piece(
        track.get("performer", {}).get("name")
        or track.get("album", {}).get("artist", {}).get("name")
        or ""
    )
    title = _normalize_piece(track.get("title", ""))
    album = _normalize_piece(track.get("album", {}).get("title", ""))
    duration = int(track.get("duration") or 0)
    if not artist or not title or not album or duration <= 0:
        return None
    params = {
        "artist_name": artist,
        "track_name": title,
        "album_name": album,
        "duration": duration,
    }
    try:
        r = requests.get(
            "https://lrclib.net/api/get",
            params=params,
            headers=LRCLIB_UA,
            timeout=timeout_sec,
        )
        if r.status_code != 200:
            return None
        data = r.json() or {}
    except Exception:
        return None
    # LRCLIB sometimes marks instrumental=true while still returning lyric text,
    # or returns a duration-matched wrong row — never trust instrumental alone.
    lyrics_early = (data.get("syncedLyrics") or data.get("plainLyrics") or "").strip()
    if data.get("instrumental") and lyrics_early and not _lyrics_looks_like_garbage(
        lyrics_early
    ):
        if _vocalish_word_count(lyrics_early) >= 18:
            data = dict(data)
            data["instrumental"] = False
    # Instrumental with no lyric payload: accept only when LRCLIB's own title,
    # artist, and duration line up tightly with the Qobuz track (same idea as /get).
    if data.get("instrumental"):
        if not lyrics_early or _lyrics_looks_like_garbage(lyrics_early):
            got_title = (data.get("trackName") or title) or ""
            got_artist = (data.get("artistName") or artist) or ""
            api_dur = int(data.get("duration") or 0)
            sim = _title_artist_similarity(title, artist, got_title, got_artist)
            dur = _duration_score(duration, api_dur)
            if sim >= 0.88 and dur >= 0.85:
                conf = _confidence_from_match(
                    sim,
                    dur,
                    "Lrclib",
                    False,
                    _is_likely_soundtrack_cue(track),
                )
                if conf >= 50.0:
                    return (
                        _pack_result(
                            "",
                            "Lrclib",
                            f"{artist} - {title}",
                            "instrumental",
                            explicit_matched=False,
                            fallback_used=False,
                            confidence=conf,
                        ),
                        conf,
                    )
            return None
        data = dict(data)
        data["instrumental"] = False
    lyrics_text = data.get("syncedLyrics") or data.get("plainLyrics") or ""
    if not lyrics_text or _lyrics_looks_like_garbage(lyrics_text):
        return None
    if _is_synced_lrc(lyrics_text) and _min_synced_lines(lyrics_text) < 2:
        return None
    if _synced_lrc_exceeds_track_duration(lyrics_text, duration):
        return None
    sim = _title_artist_similarity(
        title, artist, data.get("trackName", title), data.get("artistName", artist)
    )
    dur = _duration_score(duration, int(data.get("duration") or 0))
    conf = _confidence_from_match(
        sim,
        dur,
        "Lrclib",
        _is_synced_lrc(lyrics_text),
        _is_likely_soundtrack_cue(track),
    )
    if conf < 55.0:
        return None
    return (
        _pack_result(
            lyrics_text,
            "Lrclib",
            f"{artist} - {title}",
            _lyrics_type(lyrics_text),
            explicit_matched=False,
            fallback_used=False,
            confidence=conf,
        ),
        conf,
    )


def _lrclib_search_raw(
    artist: str, title: str, album: str, timeout_sec: float
) -> List[dict]:
    if not artist or not title:
        return []
    attempts: List[Dict[str, str]] = [
        {"track_name": title, "artist_name": artist},
    ]
    if album:
        attempts.append(
            {"track_name": title, "artist_name": artist, "album_name": album}
        )
    seen_ids = set()
    merged: List[dict] = []
    for params in attempts:
        try:
            r = requests.get(
                "https://lrclib.net/api/search",
                params=params,
                headers=LRCLIB_UA,
                timeout=timeout_sec,
            )
            if r.status_code != 200:
                continue
            items = r.json()
            if not isinstance(items, list):
                continue
            for rec in items:
                if not isinstance(rec, dict):
                    continue
                rid = rec.get("id")
                key = rid if rid is not None else (rec.get("trackName"), rec.get("artistName"))
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                merged.append(rec)
        except Exception:
            continue
    return merged


def _lrclib_search_best(track: Dict, timeout_sec: float) -> Optional[Dict[str, object]]:
    artist = _normalize_piece(
        track.get("performer", {}).get("name")
        or track.get("album", {}).get("artist", {}).get("name")
        or ""
    )
    title = _normalize_piece(track.get("title", ""))
    album = _normalize_piece(track.get("album", {}).get("title", ""))
    duration = int(track.get("duration") or 0)
    if not artist or not title:
        return None
    items = _lrclib_search_raw(artist, title, album, timeout_sec)
    if not items:
        return None

    soundtrack = _is_likely_soundtrack_cue(track)
    best: Optional[Dict[str, object]] = None
    best_conf = -1.0

    for rec in items[:20]:
        if not isinstance(rec, dict):
            continue
        got_title = rec.get("trackName") or rec.get("name") or ""
        got_artist = rec.get("artistName") or ""
        sim = _title_artist_similarity(title, artist, got_title, got_artist)
        dur = _duration_score(duration, int(rec.get("duration") or 0))
        if sim < 0.45:
            continue

        lyrics_text = rec.get("syncedLyrics") or rec.get("plainLyrics") or ""
        inst = bool(rec.get("instrumental"))
        if inst and (not lyrics_text or _lyrics_looks_like_garbage(lyrics_text)):
            if sim >= 0.88 and dur >= 0.85:
                conf = _confidence_from_match(
                    sim, dur, "Lrclib", False, soundtrack
                )
                if conf >= 50.0:
                    cand = _pack_result(
                        "",
                        "Lrclib",
                        f"{got_artist} - {got_title}",
                        "instrumental",
                        explicit_matched=False,
                        fallback_used=True,
                        confidence=conf,
                    )
                    if conf > best_conf:
                        best, best_conf = cand, conf
            continue

        if not lyrics_text or _lyrics_looks_like_garbage(lyrics_text):
            continue
        if _is_synced_lrc(lyrics_text) and _min_synced_lines(lyrics_text) < 2:
            continue
        if _synced_lrc_exceeds_track_duration(lyrics_text, duration):
            continue
        if not _looks_latin_enough(lyrics_text):
            continue
        lt = _lyrics_type(lyrics_text)
        conf = _confidence_from_match(
            sim, dur, "Lrclib", lt == "synced", soundtrack
        )
        if conf < 50.0:
            continue
        cand = _pack_result(
            lyrics_text,
            "Lrclib",
            f"{got_artist} - {got_title}",
            lt,
            explicit_matched=False,
            fallback_used=True,
            confidence=conf,
        )
        if conf > best_conf:
            best, best_conf = cand, conf

    if best is not None:
        return best
    return None


def _fetch_lrclib(track: Dict, timeout_sec: float = 6.0) -> Optional[Dict[str, object]]:
    got = _lrclib_get(track, timeout_sec=min(timeout_sec, 8.0))
    if got:
        result, conf = got
        if isinstance(result, dict):
            lyrics = (result.get("lyrics") or "").strip()
            lt = str(result.get("lyrics_type") or "")
            if lt == "instrumental" or (lyrics and _looks_latin_enough(lyrics)):
                return result
    return _lrclib_search_best(track, timeout_sec=min(timeout_sec, 8.0))


def fetch_synced_lyrics(
    track: Dict,
    prefer_explicit: Optional[bool],
    timeout_sec: float = 12.0,
) -> Optional[Dict[str, object]]:
    """Resolve lyrics using LRCLIB ``/api/get`` and ``/api/search`` only."""
    _ = prefer_explicit  # reserved for query-building / future LRCLIB hints
    return _fetch_lrclib(track, timeout_sec=min(timeout_sec, 15.0))


def write_lrc_sidecar(audio_path: str, lyrics_text: str, overwrite: bool = False) -> Optional[str]:
    if not (lyrics_text or "").strip():
        return None
    base, _ = os.path.splitext(audio_path)
    out = base + ".lrc"
    if not overwrite and os.path.exists(out):
        return None
    with open(out, "w", encoding="utf-8") as f:
        f.write(lyrics_text.strip() + "\n")
    return out
