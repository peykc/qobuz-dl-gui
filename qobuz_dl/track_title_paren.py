"""Selective parenthesis stripping for ``{track_title_base}`` and embedded TITLE tags.

Only removes bracket segments that match a known metadata/noise pattern (remaster,
explicit, album version, etc.). Song-title subtitles such as ``(Hey Oh)`` and
performance tags such as ``(Live)`` are kept. Nested segments are processed
innermost-first so ``(Album Version (Explicit))`` is removed entirely while
``(His Name Is King (Explicit))`` becomes ``(His Name Is King)``.
"""
from __future__ import annotations

import re

_BRACKET_PAIRS = (("[", "]"), ("(", ")"))
_WS_RE = re.compile(r"\s+")

# feat./ft./featuring — never strip
_FEAT_INNER_RE = re.compile(
    r"^(?:feat\.(\s+.+|[^\s]+)|featuring\s+|ft\.(\s+.+|[^\s]+))",
    flags=re.IGNORECASE,
)

# --- Strip-list patterns (full inner text, case-insensitive) ---
_RE_EXPLICIT = re.compile(r"^explicit$", re.IGNORECASE)
_RE_CLEAN = re.compile(r"^clean$", re.IGNORECASE)
_RE_ALBUM_VERSION = re.compile(r"^album\s+version$", re.IGNORECASE)
_RE_SINGLE_VERSION = re.compile(r"^single\s+version$", re.IGNORECASE)
_RE_DELUXE_EDITION = re.compile(r"^deluxe\s+edition$", re.IGNORECASE)
_RE_REMASTER = re.compile(
    r"^(?:(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?|remaster(?:ed)?\s+\d{4})$",
    re.IGNORECASE,
)
_RE_SCORE = re.compile(r"^score$", re.IGNORECASE)
_RE_FROM_QUOTED = re.compile(
    r'^from\s+(?:"[^"]+"|\'[^\']+\'|.+)$',
    re.IGNORECASE,
)
_RE_SOUNDTRACK_CUE = re.compile(
    r"original motion picture|motion picture soundtrack",
    re.IGNORECASE,
)
_RE_TECH_FORMAT = re.compile(
    r"^(?:hi[- ]?res|mono|stereo|digital master)$",
    re.IGNORECASE,
)
_RE_ANNIVERSARY_METADATA = re.compile(
    r"^(?:\d+(?:st|nd|rd|th)?\s+)?anniversary(?:\s+edition)?$",
    re.IGNORECASE,
)
_RE_METADATA_EDITION = re.compile(
    r"^(?:special|limited|collector'?s?|anniversary)\s+edition$",
    re.IGNORECASE,
)


def paren_is_feat_credit(inner: str) -> bool:
    inner = (inner or "").strip()
    return bool(_FEAT_INNER_RE.match(inner))


def _normalize_inner(inner: str) -> str:
    return _WS_RE.sub(" ", (inner or "").strip())


def paren_content_should_strip(inner: str) -> bool:
    """True when a single innermost bracket segment should be removed entirely."""
    t = _normalize_inner(inner)
    if not t:
        return True
    if paren_is_feat_credit(t):
        return False
    if _RE_CLEAN.match(t):
        return False
    if _RE_EXPLICIT.match(t):
        return True
    if _RE_ALBUM_VERSION.match(t) or _RE_SINGLE_VERSION.match(t) or _RE_DELUXE_EDITION.match(t):
        return True
    if _RE_REMASTER.match(t):
        return True
    if _RE_SCORE.match(t):
        return True
    if _RE_FROM_QUOTED.match(t) or _RE_SOUNDTRACK_CUE.search(t):
        return True
    if _RE_TECH_FORMAT.match(t):
        return True
    if _RE_ANNIVERSARY_METADATA.match(t) or _RE_METADATA_EDITION.match(t):
        return True
    return False


def _all_bracket_spans(
    text: str, open_ch: str, close_ch: str
) -> list[tuple[int, int, str]]:
    """Return every balanced ``open_ch…close_ch`` span (start, end_exclusive, inner)."""
    stack: list[int] = []
    spans: list[tuple[int, int, str]] = []
    for i, ch in enumerate(text):
        if ch == open_ch:
            stack.append(i)
        elif ch == close_ch and stack:
            start = stack.pop()
            spans.append((start, i + 1, text[start + 1 : i]))
    return spans


def _innermost_bracket_spans(text: str, open_ch: str, close_ch: str) -> list[tuple[int, int, str]]:
    """Return (start, end_exclusive, inner) for innermost ``open_ch…close_ch`` spans."""
    return [
        (start, end, inner)
        for start, end, inner in _all_bracket_spans(text, open_ch, close_ch)
        if open_ch not in inner and close_ch not in inner
    ]


def _collapse_bracket_whitespace(text: str) -> str:
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"\s+([\)\]])", r"\1", text)
    text = re.sub(r"([\[\(])\s+", r"\1", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    return text.strip()


def strip_noise_parentheticals(raw_title: str) -> str:
    """Remove metadata/noise bracket segments; keep feat credits and title subtitles."""
    s = (raw_title or "").strip()
    if not s:
        return ""
    for open_ch, close_ch in _BRACKET_PAIRS:
        changed = True
        while changed:
            changed = False
            spans = _innermost_bracket_spans(s, open_ch, close_ch)
            for start, end, inner in reversed(spans):
                if paren_content_should_strip(inner):
                    s = s[:start] + " " + s[end:]
                    changed = True
            s = _collapse_bracket_whitespace(s)
    return _collapse_bracket_whitespace(s)
