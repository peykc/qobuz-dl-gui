import re

from qobuz_dl.utils import sampling_rate_khz_for_chip


def missing_placeholder_line(label: str, value: str, width: int = 22) -> str:
    """One aligned Label : value row for *.missing.txt placeholder files."""
    lb = label.strip()
    val = "" if value is None else str(value).replace("\n", " ").replace("\r", "")
    return f"{lb.ljust(width)}: {val}"


def missing_placeholder_quality_line(
    qlid: int,
    qlabel_fallback: str,
    bd,
    sr_raw,
) -> str:
    """Short preset label + catalog bit-depth / sample rate where available."""
    try:
        bd_i = int(bd)
    except (TypeError, ValueError):
        bd_i = None
    if bd_i is not None and bd_i <= 0:
        bd_i = None
    kid = sampling_rate_khz_for_chip(sr_raw)
    kid_s = ""
    if kid is not None:
        if isinstance(kid, float) and not kid.is_integer():
            kid_s = f"{kid:.4g}"
        else:
            kid_s = str(int(round(float(kid))))
    presets = {
        5: "MP3 (~320 kbps)",
        6: "CD-quality FLAC",
        7: "24-bit FLAC",
        27: "Best available FLAC / Hi-Res",
    }
    head = presets.get(int(qlid), qlabel_fallback)
    specs = ""
    if bd_i and kid_s:
        specs = f" ({bd_i}-bit / {kid_s} kHz)"
    elif bd_i:
        specs = f" ({bd_i}-bit)"
    elif kid_s:
        specs = f" ({kid_s} kHz)"
    return head + specs


def qobuz_store_slug_from_cms_or_default(native_lang: bool, cms_url: str) -> str:
    """www.qobuz.com storefront locale (``us-en``, ``fr-fr``)."""
    cms = str(cms_url or "").strip()
    if native_lang and cms:
        m = re.search(
            r"https?://(?:www\.)?qobuz\.com/([a-z]{2}-[a-z]{2})(?:/|$)",
            cms,
            re.I,
        )
        if m:
            return m.group(1).lower()
    return "us-en"


def qobuz_www_album_product_url(store_slug: str, album_id) -> str:
    aid = str(album_id or "").strip()
    if not aid:
        return ""
    slug = (store_slug or "us-en").strip().lower() or "us-en"
    return f"https://www.qobuz.com/{slug}/album/-/{aid}"


def qobuz_www_track_product_url(store_slug: str, track_id) -> str:
    tid = str(track_id or "").strip()
    if not tid:
        return ""
    slug = (store_slug or "us-en").strip().lower() or "us-en"
    return f"https://www.qobuz.com/{slug}/track/-/{tid}"


def qobuz_purchase_store_url(
    track_meta: dict,
    album_meta: dict = None,
    *,
    native_lang: bool = False,
) -> str:
    """www.qobuz storefront URL for purchase / not-streamable."""
    cand_alb = album_meta if isinstance(album_meta, dict) else None
    if not cand_alb and isinstance((track_meta or {}).get("album"), dict):
        cand_alb = track_meta["album"]
    alb_cms_url = ""
    if isinstance(cand_alb, dict):
        alb_cms_url = str(cand_alb.get("url") or "").strip()
    slug = qobuz_store_slug_from_cms_or_default(native_lang, alb_cms_url)
    if isinstance(cand_alb, dict) and cand_alb.get("id"):
        return qobuz_www_album_product_url(slug, cand_alb["id"])
    if track_meta and isinstance(track_meta, dict):
        tid = track_meta.get("id")
        if tid:
            return qobuz_www_track_product_url(slug, tid)
    return ""
