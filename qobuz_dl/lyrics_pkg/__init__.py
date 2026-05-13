"""Synced/plain lyrics via LRCLIB public API only (https://lrclib.net/api/).

Server behaviour matches the open-source LRCLIB project (see ``lrclib-main/`` in this
repo for reference). We do not bundle third-party scraper providers.
"""
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

import requests

_TIMESTAMP_RE = re.compile(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]")
_LRC_TS_CAPTURE = re.compile(
    r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\]",
)
_FEATURE_RE = re.compile(r"\((?:feat|ft)\.? [^)]+\)", flags=re.IGNORECASE)
_BRACKET_SEGMENT_RE = re.compile(r"[\(\[]([^)\]]+)[\)\]]")
_VERSION_TOKEN_RE = re.compile(
    r"\b("
    r"alternate|alt|version|take|demo|live|remaster(?:ed)?|remix|mix|edit|"
    r"outtake|acoustic|session|studio|mono|stereo|anniversary|deluxe|"
    r"instrumental|radio|single|club|extended"
    r")\b",
    flags=re.IGNORECASE,
)
_GENERIC_VERSION_TOKENS = frozenset(
    {"version", "take", "mix", "edit", "remaster", "remastered"}
)
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

LRCLIB_UA = {"User-Agent": "Qobuz-DL-GUI/1.2 (https://github.com/peykc/qobuz-dl-gui)"}

logger = logging.getLogger(__name__)


def _lrc_tmark(label: str, detail: str = "") -> None:
    suffix = f" | {detail}" if detail else ""
    logger.info("[LRC_TIMING] %s%s", label, suffix)


def _lrc_telapsed(t0: float, label: str, detail: str = "") -> None:
    ms = int((time.monotonic() - t0) * 1000)
    suffix = f" | {detail}" if detail else ""
    logger.info("[LRC_TIMING] +%dms %s%s", ms, label, suffix)

# Heuristic word/phrase list for “explicit lyric text” (UI + optional ITUNESADVISORY).
# Uses word-like boundaries; not exhaustive and may miss obfuscated spellings.
_EXPLICIT_LYRIC_TERMS = frozenset(
    {
        "motherfucker",
        "motherfuckers",
        "motherfuckin",
        "motherfucking",
        "muthafucka",
        "muthafuckin",
        "bullshit",
        "shithead",
        "shitty",
        "clusterfuck",
        "dumbass",
        "badass",
        "jackass",
        "hardass",
        "asshole",
        "assholes",
        "bitch",
        "bitches",
        "bitchy",
        "dickhead",
        "dickheads",
        "dyke",
        "dykes",
        "fucking",
        "fucker",
        "fuckers",
        "fucked",
        "fuckin",
        "fucks",
        "fuck",
        "fag",
        "fags",
        "faggot",
        "faggots",
        "shit",
        "kike",
        "cock",
        "cocks",
        "chink",
        "dick",
        "dicks",
        "pussy",
        "cunt",
        "cunts",
        "twat",
        "nigga",
        "niggas",
        "nigger",
        "niggers",
        "prick",
        "pricks",
        "ass",
    }
)

_EXPLICIT_LYRIC_PATTERN = re.compile(
    r"(?<![a-z0-9])("
    + "|".join(re.escape(t) for t in sorted(_EXPLICIT_LYRIC_TERMS, key=len, reverse=True))
    + r")(?![a-z0-9])",
    flags=re.IGNORECASE,
)


def _lyrics_body_for_content_scan(lyrics_text: str) -> str:
    """Strip LRC timestamps / line tags so we scan words only."""
    t = (lyrics_text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = _TIMESTAMP_RE.sub(" ", t)
    t = _LINE_META_RE.sub("", t)
    t = re.sub(r"\[[^\]]+\]", " ", t)
    return _WHITESPACE_RE.sub(" ", t).strip()


def lyrics_text_indicates_explicit(lyrics_text: str) -> bool:
    """True when lyric text matches the built-in explicit vocabulary (heuristic)."""
    body = _lyrics_body_for_content_scan(lyrics_text)
    if not body:
        return False
    return bool(_EXPLICIT_LYRIC_PATTERN.search(body))


def qobuz_track_is_explicit(track: dict) -> bool:
    """True when Qobuz metadata flags the track (or its album) as explicit / parental."""
    t = track or {}
    if bool(
        t.get("parental_warning")
        or t.get("parental_advisory")
        or t.get("explicit")
    ):
        return True
    alb = t.get("album")
    if isinstance(alb, dict) and bool(
        alb.get("parental_warning")
        or alb.get("parental_advisory")
        or alb.get("explicit")
    ):
        return True
    return False


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


def _version_qualifier_tokens(title: str) -> set:
    """Meaningful version/remaster/live/demo tokens from title parentheses/brackets.

    Feat/ft credits are intentionally ignored; they describe personnel, not a
    different audio performance.
    """
    out = set()
    for seg in _BRACKET_SEGMENT_RE.findall(title or ""):
        if _FEATURE_RE.search(f"({seg})"):
            continue
        norm = _normalize_for_match(seg)
        if not _VERSION_TOKEN_RE.search(norm):
            continue
        out.update(
            tok
            for tok in re.findall(r"[a-z0-9]+", norm.lower())
            if len(tok) > 2 and tok not in {"the", "and", "for", "with"}
        )
    return out


def _title_version_compatible(want_title: str, got_title: str) -> bool:
    want = _version_qualifier_tokens(want_title)
    got = _version_qualifier_tokens(got_title)
    if not want and not got:
        return True
    if want and got:
        meaningful = (want & got) - _GENERIC_VERSION_TOKENS
        return bool(meaningful)
    return False


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


def _album_similarity(want_album: str, got_album: str) -> float:
    """Album similarity for UI confidence scoring.

    - No requested album: neutral (1.0)
    - Missing LRCLIB album: mildly penalized (0.75)
    - Exact normalized match: 1.0
    - Otherwise: fuzzy score from ratio + token overlap
    """
    want = _normalize_for_match(_normalize_piece(want_album or ""))
    got = _normalize_for_match(_normalize_piece(got_album or ""))
    if not want:
        return 1.0
    if not got:
        return 0.75
    if want == got:
        return 1.0
    seq = SequenceMatcher(None, want, got).ratio()
    tok = _token_overlap(want, got)
    return max(0.0, min(1.0, 0.7 * seq + 0.3 * tok))


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


def _lyrics_kind_rank(lyrics_type: Optional[str]) -> int:
    """Preference tier for picking among LRCLIB results (lower ranks win).

    Order: synced > plain > instrumental > none.
    """
    lt = str(lyrics_type or "").lower()
    if lt == "synced":
        return 0
    if lt == "plain":
        return 1
    if lt == "instrumental":
        return 2
    if lt in ("none", ""):
        return 3
    return 4


def _pack_result(
    lyrics: str,
    provider: str,
    query: str,
    lyrics_type: str,
    *,
    explicit_matched: bool,
    fallback_used: bool,
    confidence: float,
    lrclib_id: Optional[int] = None,
) -> Dict[str, object]:
    out: Dict[str, object] = {
        "lyrics": _normalize_lrc_text(lyrics),
        "provider": provider,
        "query": query,
        "lyrics_type": lyrics_type,
        "explicit_matched": explicit_matched,
        "fallback_used": fallback_used,
        "confidence": round(confidence, 1),
    }
    if lrclib_id is not None:
        try:
            out["lrclib_id"] = int(lrclib_id)
        except (TypeError, ValueError):
            pass
    return out


def _safe_int_id(rec: Dict) -> Optional[int]:
    rid = rec.get("id")
    if rid is None:
        return None
    try:
        return int(rid)
    except (TypeError, ValueError):
        return None


def _lrclib_row_album_matches_qobuz(want_album: str, rec: Dict) -> bool:
    """Require LRCLIB ``albumName`` to match Qobuz when both sides name an album.

    Rows with no album on LRCLIB stay eligible (API often omits it). Wrong album
    (e.g. artist repeated as album on a synced mirror) is rejected so plain text
    on the correct release can win.
    """
    if not (want_album or "").strip():
        return True
    ga = (rec.get("albumName") or "").strip()
    if not ga:
        return True
    a0 = _normalize_for_match(want_album)
    a1 = _normalize_for_match(_normalize_piece(ga))
    return bool(a0 and a1 and a0 == a1)


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
    t_http = time.monotonic()
    try:
        r = requests.get(
            "https://lrclib.net/api/get",
            params=params,
            headers=LRCLIB_UA,
            timeout=(3.0, timeout_sec),
        )
        if r.status_code != 200:
            _lrc_telapsed(t_http, "HTTP GET /api/get", f"status={r.status_code}")
            return None
        data = r.json() or {}
    except Exception:
        _lrc_telapsed(t_http, "HTTP GET /api/get", "exc")
        return None
    _lrc_telapsed(t_http, "HTTP GET /api/get", "status=200")
    # LRCLIB sometimes marks instrumental=true while still returning lyric text,
    # or returns a duration-matched wrong row | never trust instrumental alone.
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
            if not _lrclib_row_album_matches_qobuz(album, data):
                return None
            got_title = (data.get("trackName") or title) or ""
            got_artist = (data.get("artistName") or artist) or ""
            if not _title_version_compatible(title, got_title):
                return None
            api_dur = int(data.get("duration") or 0)
            sim = _title_artist_similarity(title, artist, got_title, got_artist)
            album_part = _album_similarity(album, data.get("albumName") or "")
            sim = (0.65 * sim) + (0.35 * album_part)
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
                            lrclib_id=_safe_int_id(data),
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
    if not _lrclib_row_album_matches_qobuz(album, data):
        return None
    if not _title_version_compatible(title, data.get("trackName", title)):
        return None
    sim = _title_artist_similarity(
        title, artist, data.get("trackName", title), data.get("artistName", artist)
    )
    album_part = _album_similarity(album, data.get("albumName") or "")
    sim = (0.65 * sim) + (0.35 * album_part)

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
    want_e = qobuz_track_is_explicit(track)
    got_e = lyrics_text_indicates_explicit(lyrics_text)
    if not want_e and got_e:
        return None
    if want_e and not got_e:
        return None
    return (
        _pack_result(
            lyrics_text,
            "Lrclib",
            f"{artist} - {title}",
            _lyrics_type(lyrics_text),
            explicit_matched=got_e,
            fallback_used=False,
            confidence=conf,
            lrclib_id=_safe_int_id(data),
        ),
        conf,
    )


def _lrclib_search_single(
    params: Dict[str, str], timeout_sec: float
) -> List[dict]:
    """One LRCLIB ``/api/search`` call; returns JSON rows or []."""
    keys = ",".join(sorted(params.keys()))
    t0 = time.monotonic()
    try:
        r = requests.get(
            "https://lrclib.net/api/search",
            params=params,
            headers=LRCLIB_UA,
            timeout=(3.0, timeout_sec),
        )
        if r.status_code != 200:
            _lrc_telapsed(t0, "HTTP GET /api/search", f"keys={keys} status={r.status_code} rows=0")
            return []
        items = r.json()
        if not isinstance(items, list):
            _lrc_telapsed(t0, "HTTP GET /api/search", f"keys={keys} bad_json rows=0")
            return []
        out = [rec for rec in items if isinstance(rec, dict)]
        _lrc_telapsed(t0, "HTTP GET /api/search", f"keys={keys} status=200 rows={len(out)}")
        return out
    except Exception:
        _lrc_telapsed(t0, "HTTP GET /api/search", f"keys={keys} exc rows=0")
        return []


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
    _lrc_tmark(
        "_lrclib_search_raw START",
        f"n_attempts={len(attempts)} artist={artist[:48]!r} title={title[:48]!r}",
    )
    t_merge = time.monotonic()
    if len(attempts) == 1:
        batch_lists = [_lrclib_search_single(attempts[0], timeout_sec)]
    else:
        with ThreadPoolExecutor(max_workers=len(attempts)) as ex:
            futs = [
                ex.submit(_lrclib_search_single, p, timeout_sec) for p in attempts
            ]
            batch_lists = []
            extra = min(4.0, timeout_sec)
            for fut in futs:
                try:
                    batch_lists.append(fut.result(timeout=timeout_sec + extra))
                except Exception:
                    batch_lists.append([])
    seen_ids = set()
    merged: List[dict] = []
    for items in batch_lists:
        for rec in items:
            rid = rec.get("id")
            key = rid if rid is not None else (rec.get("trackName"), rec.get("artistName"))
            if key in seen_ids:
                continue
            seen_ids.add(key)
            merged.append(rec)
    _lrc_telapsed(t_merge, "_lrclib_search_raw DONE", f"merged_rows={len(merged)}")
    return merged


def _lrclib_search_order_exact_album_first(
    items: List[dict], want_album: str
) -> List[dict]:
    """Stable reorder: same release first, then the rest in original merge order.

    Do not globally re-sort by similarity | that reordered good LRCLIB rows, pushed
    ``synced`` past the processing cap, and the loose album substring case matched
    wrong editions.  Only a strict normalized album equality split is used.
    """
    rows = [r for r in (items or []) if isinstance(r, dict)]
    if not want_album or not rows:
        return rows
    # ``album`` from the caller is already ``_normalize_piece`` for the Qobuz album title.
    a0 = _normalize_for_match(want_album)
    if not a0:
        return rows
    head: List[dict] = []
    tail: List[dict] = []
    for r in rows:
        ga = (r.get("albumName") or "").strip()
        a1 = _normalize_for_match(_normalize_piece(ga)) if ga else ""
        (head if a1 and a0 == a1 else tail).append(r)
    return head + tail


def _reconcile_pack_result_confidence_with_search_rows(
    track: Dict,
    result: Dict[str, object],
    search_rows: List[dict],
) -> Dict[str, object]:
    """Replace ``confidence`` with the same score the GUI uses for manual search.

    ``GET /api/get`` metadata (especially ``albumName``) can differ from
    ``/api/search`` rows for the **same** LRCLIB id, so the downloader used to
    log ~100% while the modal list showed ~84% for the attached row.
    """
    if not isinstance(result, dict) or not search_rows:
        return result
    rid = result.get("lrclib_id")
    if rid is None:
        return result
    try:
        ik = int(rid)
    except (TypeError, ValueError):
        return result
    ref = int(track.get("duration") or 0)
    title = _normalize_piece(track.get("title", ""))
    artist = _normalize_piece(
        track.get("performer", {}).get("name")
        or track.get("album", {}).get("artist", {}).get("name")
        or ""
    )
    album = _normalize_piece(track.get("album", {}).get("title", ""))
    for rec in search_rows:
        if not isinstance(rec, dict):
            continue
        try:
            if int(rec.get("id")) != ik:
                continue
        except (TypeError, ValueError):
            continue
        row = _compact_lrclib_search_row(rec, ref, title, artist, album)
        if not row:
            return result
        c = row.get("confidence")
        if c is None:
            return result
        try:
            cf = round(float(c), 1)
        except (TypeError, ValueError):
            return result
        out = dict(result)
        out["confidence"] = cf
        return out
    return result


# Defensive cap (LRCLIB search is typically dozens of rows, not thousands).
_LRCLIB_SEARCH_BEST_MAX_SCAN = 500


def _lrclib_merge_search_row_with_get(
    rec: Dict,
    *,
    timeout_sec: float,
    _cache: Dict[int, Optional[Dict]],
) -> Dict:
    """Apply ``GET /api/get/{{id}}`` lyrics over search JSON.

    ``/api/search`` can return metadata rows with **no** ``syncedLyrics``/``plainLyrics``
    in the JSON even when ``GET /api/get/{{id}}`` has the full timed LRC (see lrclib#87).
    Manual attach uses ``/get/:id``; auto-download must hydrate the same way.
    """
    if not isinstance(rec, dict) or rec.get("id") is None:
        return rec
    try:
        ik = int(rec.get("id"))
    except (TypeError, ValueError):
        return rec
    if ik not in _cache:
        _cache[ik] = lrclib_get_by_id(ik, timeout_sec=timeout_sec)
    full = _cache[ik]
    if not full or not isinstance(full, dict):
        return rec
    out = dict(rec)
    fs = (full.get("syncedLyrics") or "").strip()
    fp = (full.get("plainLyrics") or "").strip()
    if fs:
        out["syncedLyrics"] = full.get("syncedLyrics")
    if fp:
        out["plainLyrics"] = full.get("plainLyrics")
    if "instrumental" in full:
        out["instrumental"] = bool(full.get("instrumental"))
    if full.get("duration") is not None:
        try:
            out["duration"] = int(float(full["duration"]))
        except (TypeError, ValueError):
            pass
    return out


def _lrclib_search_best(
    track: Dict,
    timeout_sec: float,
    items: Optional[List[dict]] = None,
    *,
    max_get_hydrations: int = 8,
) -> Optional[Dict[str, object]]:
    t_sb = time.monotonic()
    artist = _normalize_piece(
        track.get("performer", {}).get("name")
        or track.get("album", {}).get("artist", {}).get("name")
        or ""
    )
    title = _normalize_piece(track.get("title", ""))
    album = _normalize_piece(track.get("album", {}).get("title", ""))
    duration = int(track.get("duration") or 0)
    if not artist or not title:
        _lrc_telapsed(t_sb, "_lrclib_search_best", "skip_empty_meta")
        return None
    if items is None:
        items = _lrclib_search_raw(artist, title, album, timeout_sec)
    if not items:
        _lrc_telapsed(t_sb, "_lrclib_search_best", "no_search_items")
        return None
    items = _lrclib_search_order_exact_album_first(items, album)

    soundtrack = _is_likely_soundtrack_cue(track)
    want_e = qobuz_track_is_explicit(track)
    get_cache: Dict[int, Optional[Dict]] = {}
    hydrated_ids = set()

    def _prefetch_get_cache(merge: Optional[str]) -> None:
        if not merge or int(max_get_hydrations or 0) <= 0:
            return
        ids: List[int] = []
        seen = set()
        for rec in items[:_LRCLIB_SEARCH_BEST_MAX_SCAN]:
            if not isinstance(rec, dict) or rec.get("id") is None:
                continue
            if merge == "empty" and (rec.get("syncedLyrics") or rec.get("plainLyrics") or "").strip():
                continue
            try:
                ik = int(rec.get("id"))
            except (TypeError, ValueError):
                continue
            if ik in seen or ik in get_cache:
                continue
            seen.add(ik)
            ids.append(ik)
            if len(ids) >= max(0, int(max_get_hydrations or 0)):
                break
        if not ids:
            return
        with ThreadPoolExecutor(max_workers=min(len(ids), 8)) as ex:
            futs = {
                ex.submit(lrclib_get_by_id, ik, timeout_sec=timeout_sec): ik
                for ik in ids
            }
            done, _pending = wait(list(futs.keys()), timeout=timeout_sec + 3.0)
            for fut in done:
                ik = futs[fut]
                try:
                    get_cache[ik] = fut.result()
                except Exception:
                    get_cache[ik] = None

    def _run_pass(merge: Optional[str]) -> List[Tuple[Dict[str, object], float, bool, bool]]:
        _prefetch_get_cache(merge)
        scored: List[Tuple[Dict[str, object], float, bool, bool]] = []
        for rec in items[:_LRCLIB_SEARCH_BEST_MAX_SCAN]:
            if not isinstance(rec, dict):
                continue
            r = rec
            if merge and r.get("id") is not None:
                if merge == "all" or (
                    merge == "empty"
                    and not (r.get("syncedLyrics") or r.get("plainLyrics") or "").strip()
                ):
                    try:
                        ik = int(r.get("id"))
                    except (TypeError, ValueError):
                        ik = None
                    if (
                        ik is not None
                        and ik not in get_cache
                        and len(hydrated_ids) >= max(0, int(max_get_hydrations or 0))
                    ):
                        continue
                    r = _lrclib_merge_search_row_with_get(
                        r, timeout_sec=timeout_sec, _cache=get_cache
                    )
                    if ik is not None:
                        hydrated_ids.add(ik)
            got_title = r.get("trackName") or r.get("name") or ""
            got_artist = r.get("artistName") or ""
            if not _title_version_compatible(title, got_title):
                continue
            sim = _title_artist_similarity(title, artist, got_title, got_artist)
            album_part = _album_similarity(album, r.get("albumName") or "")
            sim = (0.65 * sim) + (0.35 * album_part)
            dur = _duration_score(duration, int(r.get("duration") or 0))
            if sim < 0.45:
                continue

            lyrics_text = (r.get("syncedLyrics") or r.get("plainLyrics") or "").strip()
            inst = bool(r.get("instrumental"))
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
                            fallback_used=False,
                            confidence=conf,
                            lrclib_id=_safe_int_id(r),
                        )
                        scored.append(
                            (
                                cand,
                                conf,
                                False,
                                _lrclib_row_album_matches_qobuz(album, r),
                            )
                        )
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
            got_e = lyrics_text_indicates_explicit(lyrics_text)
            cand = _pack_result(
                lyrics_text,
                "Lrclib",
                f"{got_artist} - {got_title}",
                lt,
                explicit_matched=got_e,
                fallback_used=False,
                confidence=conf,
                lrclib_id=_safe_int_id(r),
            )
            scored.append(
                (cand, conf, got_e, _lrclib_row_album_matches_qobuz(album, r))
            )
        return scored

    for merge in (None, "empty", "all"):
        scored = _run_pass(merge)
        if not scored:
            continue
        if not want_e:
            scored = [x for x in scored if not x[2]]
        if not scored:
            continue
        album_ok_rows = [t for t in scored if t[3]]
        if album_ok_rows:
            scored = album_ok_rows
        else:
            scored = [
                t
                for t in scored
                if not (
                    str(t[0].get("lyrics_type") or "") == "synced" and not t[3]
                )
            ]
        if not scored:
            continue
        if want_e:
            scored.sort(
                key=lambda t: (
                    _lyrics_kind_rank(str(t[0].get("lyrics_type") or "")),
                    -float(t[1]),
                    -int(t[2]),
                )
            )
        else:
            scored.sort(
                key=lambda t: (
                    _lyrics_kind_rank(str(t[0].get("lyrics_type") or "")),
                    -float(t[1]),
                )
            )
        _lrc_telapsed(
            t_sb, "_lrclib_search_best", f"HIT merge={merge} kind={scored[0][0].get('lyrics_type')!s}"
        )
        return scored[0][0]
    _lrc_telapsed(t_sb, "_lrclib_search_best", "MISS")
    return None


def _fetch_lrclib_result_and_rows(
    track: Dict,
    timeout_sec: float = 6.0,
    *,
    max_get_hydrations: int = 8,
) -> Tuple[Optional[Dict[str, object]], List[dict]]:
    """Resolve from LRCLIB without stacking network waits serially."""
    t_all = time.monotonic()
    base_timeout = max(1.0, float(timeout_sec or 0))
    get_t = min(base_timeout, 8.0)
    search_t = min(base_timeout, 15.0)
    deadline = max(get_t, search_t) + 4.0
    artist = _normalize_piece(
        track.get("performer", {}).get("name")
        or track.get("album", {}).get("artist", {}).get("name")
        or ""
    )
    title = _normalize_piece(track.get("title", ""))
    album = _normalize_piece(track.get("album", {}).get("title", ""))
    _lrc_tmark(
        "_fetch_lrclib START",
        f"title={title[:56]!r} get_cap={get_t}s search_cap={search_t}s parallel_deadline={deadline}s",
    )

    got: Optional[Tuple[Dict, float]] = None
    search_rows: List[dict] = []
    t_initial = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_get = ex.submit(_lrclib_get, track, get_t)
        fut_rows = ex.submit(
            lambda: _lrclib_search_order_exact_album_first(
                _lrclib_search_raw(artist, title, album, search_t),
                album,
            )
        )
        try:
            got = fut_get.result(timeout=deadline)
        except Exception:
            got = None
        try:
            search_rows = fut_rows.result(timeout=deadline) or []
        except Exception:
            search_rows = []
    _lrc_telapsed(
        t_initial,
        "_fetch_lrclib initial parallel done",
        f"get_tuple={got is not None} search_rows={len(search_rows)}",
    )

    def _pick_non_empty(res: Optional[Dict[str, object]]) -> bool:
        if not res or not isinstance(res, dict):
            return False
        lt = str(res.get("lyrics_type") or "").lower()
        if lt == "instrumental":
            return True
        return bool((res.get("lyrics") or "").strip())

    got_result: Optional[Dict[str, object]] = None
    if got:
        result, _conf = got
        if isinstance(result, dict):
            lyrics = (result.get("lyrics") or "").strip()
            lt = str(result.get("lyrics_type") or "")
            if lt == "instrumental" or (lyrics and _looks_latin_enough(lyrics)):
                got_result = _reconcile_pack_result_confidence_with_search_rows(
                    track, result, search_rows
                )

    if got_result and str(got_result.get("lyrics_type") or "").lower() == "synced":
        _lrc_telapsed(t_all, "_fetch_lrclib END", "pick get_result_fast_synced")
        return got_result, search_rows

    search_out: Optional[Dict[str, object]] = _lrclib_search_best(
        track,
        search_t,
        search_rows,
        max_get_hydrations=max_get_hydrations,
    )

    if got_result:
        search_out = (
            _reconcile_pack_result_confidence_with_search_rows(
                track, search_out, search_rows
            )
            if search_out
            else None
        )
        if search_out and _pick_non_empty(search_out):
            rg = _lyrics_kind_rank(str(got_result.get("lyrics_type") or ""))
            rs = _lyrics_kind_rank(str(search_out.get("lyrics_type") or ""))
            if rs < rg:
                _lrc_telapsed(t_all, "_fetch_lrclib END", "pick search_out (better_kind)")
                return search_out, search_rows
            if rg < rs:
                _lrc_telapsed(t_all, "_fetch_lrclib END", "pick get_result (better_kind)")
                return got_result, search_rows
            try:
                gc = float(got_result.get("confidence") or 0.0)
                sc = float(search_out.get("confidence") or 0.0)
            except (TypeError, ValueError):
                _lrc_telapsed(t_all, "_fetch_lrclib END", "pick get_result (tie_conf_exc)")
                return got_result, search_rows
            if sc > gc + 1e-9:
                _lrc_telapsed(t_all, "_fetch_lrclib END", "pick search_out (higher_conf)")
                return search_out, search_rows
        _lrc_telapsed(t_all, "_fetch_lrclib END", "pick get_result")
        return got_result, search_rows
    if search_out:
        _lrc_telapsed(t_all, "_fetch_lrclib END", "pick search_out_only")
        return _reconcile_pack_result_confidence_with_search_rows(
            track, search_out, search_rows
        ), search_rows
    _lrc_telapsed(t_all, "_fetch_lrclib END", "miss")
    return None, search_rows


def _fetch_lrclib(track: Dict, timeout_sec: float = 6.0) -> Optional[Dict[str, object]]:
    result, _search_rows = _fetch_lrclib_result_and_rows(track, timeout_sec=timeout_sec)
    return result


def fetch_synced_lyrics(
    track: Dict,
    prefer_explicit: Optional[bool],
    timeout_sec: float = 12.0,
) -> Optional[Dict[str, object]]:
    """Resolve lyrics using LRCLIB ``/api/get`` and ``/api/search`` only.

    Explicit vs clean lyric text is matched to Qobuz ``qobuz_track_is_explicit``:
    non-explicit tracks will not use lyric text flagged by the word list; explicit
    tracks prefer word-list–explicit lyrics when multiple LRCLIB rows tie otherwise.
    """
    _ = prefer_explicit  # legacy; policy uses ``track`` metadata
    return _fetch_lrclib(track, timeout_sec=min(timeout_sec, 15.0))


def fetch_synced_lyrics_with_search_fallback(
    track: Dict,
    prefer_explicit: Optional[bool],
    timeout_sec: float = 12.0,
    *,
    max_fallback_candidates: int = 5,
) -> Optional[Dict[str, object]]:
    """LRCLIB strict resolver with manual-search candidate fallback."""
    artist = _normalize_piece(
        track.get("performer", {}).get("name")
        or track.get("album", {}).get("artist", {}).get("name")
        or ""
    )
    title = _normalize_piece(track.get("title", ""))
    album = _normalize_piece(track.get("album", {}).get("title", ""))
    duration = int(track.get("duration") or 0)
    _lrc_tmark(
        "fallback_pipeline START",
        f"{artist[:44]!r} — {title[:52]!r}",
    )
    t_pipe = time.monotonic()

    t_phase1 = time.monotonic()
    out, strict_rows = _fetch_lrclib_result_and_rows(
        track,
        timeout_sec=timeout_sec,
        max_get_hydrations=0,
    )
    if out:
        _lrc_telapsed(t_phase1, "phase1 fetch_synced_lyrics (_fetch_lrclib)", "HIT")
        _lrc_telapsed(t_pipe, "fallback_pipeline END", "path=strict provider=Lrclib")
        return out
    _lrc_telapsed(t_phase1, "phase1 fetch_synced_lyrics (_fetch_lrclib)", "MISS")

    if int(max_fallback_candidates or 0) <= 0:
        _lrc_telapsed(t_pipe, "fallback_pipeline END", "miss_max_fallback_0")
        return None

    if not title or not artist:
        _lrc_telapsed(t_pipe, "fallback_pipeline END", "miss_empty_title_artist")
        return None

    want_explicit = qobuz_track_is_explicit(track)
    t_cand = time.monotonic()
    raw_rows = list(strict_rows or [])
    source_label = "strict_rows"
    if not raw_rows:
        raw_rows = _lrclib_search_order_exact_album_first(
            _lrclib_search_raw(
                artist,
                title,
                album,
                timeout_sec=min(max(6.0, timeout_sec), 18.0),
            ),
            album,
        )
        source_label = "retry_search"
    candidate_pairs: List[Tuple[Dict[str, object], Dict]] = []
    for rec in raw_rows:
        if not _title_version_compatible(title, rec.get("trackName") or ""):
            continue
        row = _compact_lrclib_search_row(rec, duration, title, artist, album)
        if not row:
            continue
        if want_explicit is False and row.get("lyrics_explicit"):
            continue
        candidate_pairs.append((row, rec))
    if want_explicit is True and len(candidate_pairs) > 1:
        candidate_pairs.sort(
            key=lambda pair: (
                not bool(pair[0].get("lyrics_explicit")),
                pair[0].get("id") or 0,
            )
        )
    _lrc_telapsed(
        t_cand,
        f"lrclib_search_candidates_for_auto ({source_label})",
        f"n_rows={len(candidate_pairs)} raw={len(raw_rows)}",
    )
    if not candidate_pairs:
        _lrc_telapsed(t_pipe, "fallback_pipeline END", "miss_empty_candidates")
        return None

    def _row_conf(r: Dict[str, object]) -> float:
        c = r.get("confidence")
        try:
            return float(c)
        except (TypeError, ValueError):
            return -1.0

    def _kind_rank(r: Dict[str, object]) -> int:
        k = str(r.get("kind") or "").lower()
        if k == "synced":
            return 0
        if k == "plain":
            return 1
        if k == "instrumental":
            return 2
        return 3

    ranked = sorted(
        candidate_pairs,
        key=lambda pair: (
            _kind_rank(pair[0]),
            -_row_conf(pair[0]),
            abs(int(pair[0].get("delta_sec") or 0)),
            int(pair[0].get("id") or 0),
        ),
    )
    for try_idx, (row, rec) in enumerate(ranked[: int(max_fallback_candidates)], start=1):
        body = ((rec.get("syncedLyrics") or "").strip() or (rec.get("plainLyrics") or "").strip())
        if not body or _lyrics_looks_like_garbage(body):
            continue
        got_explicit = lyrics_text_indicates_explicit(body)
        if not want_explicit and got_explicit:
            continue
        rid = row.get("id")
        try:
            ik = int(rid)
        except (TypeError, ValueError):
            ik = None
        conf = _row_conf(row)
        out = _pack_result(
            body,
            "Lrclib search fallback",
            f"{artist} - {title}",
            _lyrics_type(body),
            explicit_matched=got_explicit,
            fallback_used=False,
            confidence=conf if conf >= 0.0 else 0.0,
            lrclib_id=ik,
        )
        out["search_fallback_used"] = True
        _lrc_telapsed(
            t_pipe,
            "fallback_pipeline END",
            f"path=fallback_search_row={try_idx} id={ik} kind={out.get('lyrics_type')!s}",
        )
        return out

    candidate_rows: List[Tuple[int, Dict[str, object], int]] = []
    for try_idx, (row, _rec) in enumerate(ranked[: int(max_fallback_candidates)], start=1):
        rid = row.get("id")
        try:
            ik = int(rid)
        except (TypeError, ValueError):
            continue
        _lrc_tmark("fallback TRY_ROW", f"try={try_idx} id={ik}")
        candidate_rows.append((try_idx, row, ik))
    if not candidate_rows:
        _lrc_telapsed(t_pipe, "fallback_pipeline END", "miss_no_candidate_ids")
        return None

    get_timeout = min(max(6.0, timeout_sec), 18.0)

    def _pack_candidate(
        try_idx: int,
        row: Dict[str, object],
        ik: int,
        data: Optional[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not data:
            return None
        synced = (data.get("syncedLyrics") or "").strip()
        plain = (data.get("plainLyrics") or "").strip()
        body = synced or plain
        if not body or _lyrics_looks_like_garbage(body):
            return None
        got_explicit = lyrics_text_indicates_explicit(body)
        if not want_explicit and got_explicit:
            return None
        conf = _row_conf(row)
        out = _pack_result(
            body,
            "Lrclib search fallback",
            f"{artist} - {title}",
            _lyrics_type(body),
            explicit_matched=got_explicit,
            fallback_used=False,
            confidence=conf if conf >= 0.0 else 0.0,
            lrclib_id=ik,
        )
        out["search_fallback_used"] = True
        _lrc_telapsed(
            t_pipe,
            "fallback_pipeline END",
            f"path=fallback_try={try_idx} id={ik} kind={out.get('lyrics_type')!s}",
        )
        return out

    first_try, first_row, first_id = candidate_rows[0]
    packed = _pack_candidate(
        first_try,
        first_row,
        first_id,
        lrclib_get_by_id(first_id, timeout_sec=get_timeout),
    )
    if packed:
        return packed

    remaining = candidate_rows[1:]
    if remaining:
        data_by_id: Dict[int, Optional[Dict[str, object]]] = {}
        with ThreadPoolExecutor(max_workers=len(remaining)) as ex:
            futs = {
                ex.submit(lrclib_get_by_id, ik, timeout_sec=get_timeout): ik
                for _try_idx, _row, ik in remaining
            }
            done, _pending = wait(list(futs.keys()), timeout=get_timeout + 3.0)
            for fut in done:
                ik = futs[fut]
                try:
                    data_by_id[ik] = fut.result()
                except Exception:
                    data_by_id[ik] = None
        for try_idx, row, ik in remaining:
            packed = _pack_candidate(try_idx, row, ik, data_by_id.get(ik))
            if packed:
                return packed
    _lrc_telapsed(t_pipe, "fallback_pipeline END", "miss_after_fallback_tries")
    return None


def instrumental_placeholder_lrc() -> str:
    """Minimal synced LRC when LRCLIB marks instrumental but returns no lyric lines.

    Mirrors typical LRCLIB rows so players still get a valid ``.lrc`` sidecar.
    """
    return "[00:00.00](instrumental)"


def write_lrc_sidecar(audio_path: str, lyrics_text: str, overwrite: bool = False) -> Optional[str]:
    if not (lyrics_text or "").strip():
        return None
    ap = audio_path or ""
    if ap.lower().endswith(".missing.txt"):
        base = ap[: -len(".missing.txt")]
    else:
        base, _ = os.path.splitext(ap)
    out = base + ".lrc"
    if not overwrite and os.path.exists(out):
        return None
    with open(out, "w", encoding="utf-8") as f:
        f.write(lyrics_text.strip() + "\n")
    return out


def lrclib_id_sidecar_path(audio_path: str) -> str:
    """Legacy path only: ``track.flac`` → ``track.lrclib_id`` (new installs use SQLite)."""
    base, _ = os.path.splitext(audio_path)
    return base + ".lrclib_id"


def write_lrclib_id_sidecar(audio_path: str, record_id: int) -> None:
    """Store LRCLIB record id for this file in app ``qobuz_dl.db`` (no extra file in the music folder)."""
    from qobuz_dl import db as db_mod

    db_mod.set_lrclib_id_for_audio_path(audio_path, record_id)


def read_lrclib_id_sidecar(audio_path: str) -> Optional[int]:
    from qobuz_dl import db as db_mod

    got = db_mod.get_lrclib_id_for_audio_path(audio_path)
    if got is not None:
        return got
    p = db_mod.normalized_audio_path(audio_path)
    legacy_path = lrclib_id_sidecar_path(p) if p else lrclib_id_sidecar_path(audio_path)
    if not p or not os.path.isfile(p):
        try:
            if os.path.isfile(legacy_path):
                os.remove(legacy_path)
        except OSError:
            pass
        return None
    try:
        with open(legacy_path, encoding="utf-8") as f:
            line = (f.readline() or "").strip()
        legacy = int(line) if line else None
    except OSError:
        return None
    except ValueError:
        return None
    if legacy is not None:
        try:
            db_mod.set_lrclib_id_for_audio_path(audio_path, legacy)
            os.remove(legacy_path)
        except OSError:
            pass
    return legacy


# --- Manual LRCLIB browse / attach (GUI) ------------------------------------

# LRCLIB treats ±2s as a duration match; hide smaller deltas in the list (LRCGET-style).
LRCLIB_UI_DURATION_DELTA_SEC = 2


def _compact_lrclib_search_row(
    rec: dict,
    reference_duration_sec: int,
    want_title: str = "",
    want_artist: str = "",
    want_album: str = "",
) -> Optional[Dict[str, object]]:
    if not isinstance(rec, dict):
        return None
    rid = rec.get("id")
    if rid is None:
        return None
    dur = int(rec.get("duration") or 0)
    ref = int(reference_duration_sec or 0)
    delta_sec = None
    if ref > 0 and dur > 0 and abs(dur - ref) > LRCLIB_UI_DURATION_DELTA_SEC:
        delta_sec = int(dur - ref)
    synced = (rec.get("syncedLyrics") or "").strip()
    plain = (rec.get("plainLyrics") or "").strip()
    inst = bool(rec.get("instrumental"))
    if synced:
        kind = "synced"
    elif plain:
        kind = "plain"
    elif inst:
        kind = "instrumental"
    else:
        kind = "none"
    scan_text = f"{synced}\n{plain}".strip()
    lyrics_explicit = lyrics_text_indicates_explicit(scan_text) if scan_text else False
    got_t = (rec.get("trackName") or "") or ""
    got_ar = (rec.get("artistName") or "") or ""
    sim = _title_artist_similarity(
        _normalize_piece(want_title),
        _normalize_piece(want_artist),
        got_t,
        got_ar,
    )
    got_al = (rec.get("albumName") or "") or ""
    album_part = _album_similarity(_normalize_piece(want_album), got_al)
    # Manual browse confidence should reflect release match quality too, not only
    # title/artist+duration; this avoids misleading 100% rows on wrong albums.
    sim = (0.65 * sim) + (0.35 * album_part)
    dur_part = _duration_score(ref, dur)
    is_synced = bool(synced)
    st_track = {
        "title": got_t or _normalize_piece(want_title),
        "album": {"title": (rec.get("albumName") or "") or _normalize_piece(want_album)},
    }
    soundtrack_penalty = _is_likely_soundtrack_cue(st_track)
    confidence = round(
        _confidence_from_match(
            sim,
            dur_part,
            "Lrclib",
            is_synced,
            soundtrack_penalty and sim < 0.92,
        ),
        1,
    )
    return {
        "id": rid,
        "trackName": rec.get("trackName"),
        "artistName": rec.get("artistName"),
        "albumName": rec.get("albumName"),
        "duration": dur,
        "delta_sec": delta_sec,
        "kind": kind,
        "instrumental": inst,
        "lyrics_explicit": lyrics_explicit,
        "confidence": confidence,
    }


def lrclib_search_candidates_for_ui(
    title: str,
    artist: str,
    album: str = "",
    reference_duration_sec: int = 0,
    *,
    timeout_sec: float = 15.0,
    track_explicit: Optional[bool] = None,
    filter_mismatched: bool = True,
) -> List[Dict[str, object]]:
    """LRCLIB /api/search rows without returning lyric bodies to the client; includes
    duration delta vs reference and a heuristic ``lyrics_explicit`` flag from scan.

    When ``filter_mismatched`` and ``track_explicit`` is False, drop rows whose
    lyric text looks explicit (clean track). When ``track_explicit`` is True,
    sort so explicit-looking lyrics appear first; all rows are kept.
    """
    items = _lrclib_search_raw(
        _normalize_piece(artist),
        _normalize_piece(title),
        _normalize_piece(album),
        timeout_sec,
    )
    ref = int(reference_duration_sec or 0)
    out: List[Dict[str, object]] = []
    for rec in items:
        row = _compact_lrclib_search_row(rec, ref, title, artist, album)
        if row:
            out.append(row)
    if filter_mismatched and track_explicit is False:
        out = [r for r in out if not r.get("lyrics_explicit")]
    if track_explicit is True and len(out) > 1:
        out.sort(key=lambda r: (not bool(r.get("lyrics_explicit")), r.get("id") or 0))
    return out[:50]


def lrclib_get_by_id(record_id: int, *, timeout_sec: float = 15.0) -> Optional[Dict[str, object]]:
    """Full LRCLIB record from GET /api/get/{id}."""
    try:
        rid = int(record_id)
    except (TypeError, ValueError):
        return None
    t0 = time.monotonic()
    try:
        r = requests.get(
            f"https://lrclib.net/api/get/{rid}",
            headers=LRCLIB_UA,
            timeout=(3.0, timeout_sec),
        )
        if r.status_code != 200:
            _lrc_telapsed(t0, "HTTP GET /api/get/{id}", f"id={rid} status={r.status_code}")
            return None
        data = r.json()
    except Exception:
        _lrc_telapsed(t0, "HTTP GET /api/get/{id}", f"id={rid} exc")
        return None
    ok = isinstance(data, dict)
    _lrc_telapsed(t0, "HTTP GET /api/get/{id}", f"id={rid} status=200 dict={ok}")
    return data if ok else None


def attach_lrclib_id_to_audio(
    audio_path: str,
    record_id: int,
    *,
    overwrite: bool = True,
    timeout_sec: float = 15.0,
    update_explicit_tag: bool = False,
    write_sidecar: bool = True,
    write_metadata: bool = False,
) -> Tuple[Optional[str], bool, bool, bool]:
    """Download lyrics for LRCLIB id and attach them to ``audio_path``.

    Returns ``(lrc_path_or_none, lyrics_explicit, explicit_tag_applied, metadata_written)``.
    When ``update_explicit_tag`` is True and lyrics match the heuristic, sets
    ITUNESADVISORY on FLAC/MP3 (``explicit_tag_applied`` is True only if tagging worked).
    """
    data = lrclib_get_by_id(record_id, timeout_sec=timeout_sec)
    if not data:
        return None, False, False, False
    synced = (data.get("syncedLyrics") or "").strip()
    plain = (data.get("plainLyrics") or "").strip()
    body = synced or plain
    if not body:
        if bool(data.get("instrumental")):
            body = instrumental_placeholder_lrc()
        else:
            return None, False, False, False
    if _lyrics_looks_like_garbage(body):
        return None, False, False, False
    explicit = lyrics_text_indicates_explicit(body)
    audio_low = str(audio_path or "").lower()
    if audio_low.endswith(".missing.txt"):
        update_explicit_tag = False
        write_metadata = False
    out = write_lrc_sidecar(audio_path, body, overwrite=overwrite) if write_sidecar else None
    metadata_written = False
    if write_metadata:
        from qobuz_dl import metadata as metadata_mod

        metadata_written = metadata_mod.write_lyrics_metadata(audio_path, body)
    if not out and not metadata_written:
        return None, explicit, False, False
    try:
        write_lrclib_id_sidecar(audio_path, record_id)
    except Exception:
        pass
    tag_applied = False
    if update_explicit_tag and explicit:
        from qobuz_dl import metadata as metadata_mod

        tag_applied = metadata_mod.set_itunes_explicit_from_lyrics_content(
            audio_path, body
        )
    return out, explicit, tag_applied, metadata_written
