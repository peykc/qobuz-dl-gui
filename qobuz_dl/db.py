import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

from qobuz_dl.color import YELLOW, RED

logger = logging.getLogger(__name__)


def create_db(db_path):
    with sqlite3.connect(db_path) as conn:
        try:
            conn.execute("CREATE TABLE downloads (id TEXT UNIQUE NOT NULL);")
            logger.info(f"{YELLOW}Download-IDs database created")
        except sqlite3.OperationalError:
            pass
        return db_path


def handle_download_id(db_path, item_id, add_id=False):
    if not db_path:
        return

    with sqlite3.connect(db_path) as conn:
        # If add_if is False return a string to know if the ID is in the DB
        # Otherwise just add the ID to the DB
        if add_id:
            try:
                conn.execute(
                    "INSERT INTO downloads (id) VALUES (?)",
                    (item_id,),
                )
                conn.commit()
            except sqlite3.Error as e:
                logger.error(f"{RED}Unexpected DB error: {e}")
        else:
            return conn.execute(
                "SELECT id FROM downloads where id=?",
                (item_id,),
            ).fetchone()


# ---------------------------------------------------------------------------
# LRCLIB id ↔ local audio path (keeps music folders free of ``.lrclib_id`` files)
# ---------------------------------------------------------------------------


def get_qobuz_config_dir() -> str:
    """Same directory as ``config.ini`` / ``qobuz_dl.db`` (mirrors gui_app / cli)."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or ""
    else:
        base = os.path.join(os.environ.get("HOME", ""), ".config")
    return os.path.join(base, "qobuz-dl")


def get_qobuz_db_path() -> str:
    return os.path.join(get_qobuz_config_dir(), "qobuz_dl.db")


def _ensure_lrclib_by_audio_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS lrclib_by_audio ("
        "audio_path TEXT PRIMARY KEY,"
        "lrclib_id INTEGER NOT NULL)"
    )


def _normalize_audio_path_key(audio_path: str) -> Optional[str]:
    try:
        return str(Path(audio_path).expanduser().resolve())
    except OSError:
        return None


def normalized_audio_path(audio_path: str) -> Optional[str]:
    """Absolute resolved path used as the DB key for ``lrclib_by_audio``."""
    return _normalize_audio_path_key(audio_path)


def delete_lrclib_id_for_audio_path(audio_path: str) -> None:
    """Remove stored LRCLIB link for this file (e.g. file removed from disk)."""
    p = _normalize_audio_path_key(audio_path)
    if not p:
        return
    dbp = get_qobuz_db_path()
    if not os.path.isfile(dbp):
        return
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_lrclib_by_audio_table(conn)
            conn.execute("DELETE FROM lrclib_by_audio WHERE audio_path=?", (p,))
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}LRCLIB id delete: {e}")


def prune_lrclib_by_audio_orphans() -> int:
    """Delete ``lrclib_by_audio`` rows whose audio file no longer exists. Returns row count removed."""
    dbp = get_qobuz_db_path()
    if not os.path.isfile(dbp):
        return 0
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_lrclib_by_audio_table(conn)
            rows = conn.execute("SELECT audio_path FROM lrclib_by_audio").fetchall()
            removed = 0
            for (apath,) in rows:
                if not apath or os.path.isfile(apath):
                    continue
                conn.execute(
                    "DELETE FROM lrclib_by_audio WHERE audio_path=?",
                    (apath,),
                )
                removed += 1
            if removed:
                conn.commit()
            return removed
    except sqlite3.Error as e:
        logger.error(f"{RED}LRCLIB orphan prune: {e}")
    return 0


def set_lrclib_id_for_audio_path(audio_path: str, lrclib_id: int) -> None:
    """Persist which LRCLIB row is linked to a local file (GUI attach / auto-download)."""
    p = _normalize_audio_path_key(audio_path)
    if not p or not os.path.isfile(p):
        return
    try:
        rid = int(lrclib_id)
    except (TypeError, ValueError):
        return
    dbp = get_qobuz_db_path()
    os.makedirs(os.path.dirname(dbp), exist_ok=True)
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_lrclib_by_audio_table(conn)
            conn.execute(
                "INSERT INTO lrclib_by_audio (audio_path, lrclib_id) VALUES (?, ?) "
                "ON CONFLICT(audio_path) DO UPDATE SET lrclib_id=excluded.lrclib_id",
                (p, rid),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}LRCLIB id store: {e}")


def get_lrclib_id_for_audio_path(audio_path: str) -> Optional[int]:
    p = _normalize_audio_path_key(audio_path)
    if not p:
        return None
    dbp = get_qobuz_db_path()
    if not os.path.isfile(dbp):
        return None
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_lrclib_by_audio_table(conn)
            if not os.path.isfile(p):
                conn.execute("DELETE FROM lrclib_by_audio WHERE audio_path=?", (p,))
                conn.commit()
                return None
            row = conn.execute(
                "SELECT lrclib_id FROM lrclib_by_audio WHERE audio_path=?",
                (p,),
            ).fetchone()
            if row:
                return int(row[0])
    except sqlite3.Error as e:
        logger.error(f"{RED}LRCLIB id read: {e}")
    return None


# ---------------------------------------------------------------------------
# GUI download history (per local audio file; survives app restarts)
# ---------------------------------------------------------------------------

GUI_PENDING_TRACK_PREFIX = "__GUI_PENDING__:slot:"


def is_gui_pending_track_key(audio_path: Optional[str]) -> bool:
    """Synthetic DB keys for purchase-only / failed slots with no local file yet."""
    return isinstance(audio_path, str) and audio_path.startswith(GUI_PENDING_TRACK_PREFIX)


def is_gui_missing_placeholder_audio_path(audio_path: str) -> bool:
    """``.missing.txt`` note written instead of FLAC/MP3 (same naming pattern)."""

    raw = str(audio_path or "").strip()
    if not raw or is_gui_pending_track_key(raw):
        return False
    try:
        p = Path(audio_path).expanduser().resolve()
    except OSError:
        return False
    name = str(p.name or "").lower()
    return bool(name.endswith(".missing.txt"))


def _ensure_gui_download_history_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS gui_download_history ("
        "audio_path TEXT PRIMARY KEY,"
        "track_no TEXT,"
        "title TEXT NOT NULL,"
        "cover_url TEXT,"
        "lyric_artist TEXT,"
        "lyric_album TEXT,"
        "duration_sec INTEGER,"
        "track_explicit INTEGER,"
        "download_status TEXT,"
        "download_detail TEXT,"
        "lyric_type TEXT,"
        "lyric_provider TEXT,"
        "lyric_confidence TEXT,"
        "lyric_destination TEXT,"
        "updated_at REAL NOT NULL)"
    )
    cur = conn.execute("PRAGMA table_info(gui_download_history)")
    cols = {row[1] for row in cur.fetchall()}
    if "slot_track_id" not in cols:
        conn.execute(
            "ALTER TABLE gui_download_history ADD COLUMN slot_track_id TEXT"
        )
        cols.add("slot_track_id")
    if "release_album_id" not in cols:
        conn.execute(
            "ALTER TABLE gui_download_history ADD COLUMN release_album_id TEXT"
        )
        cols.add("release_album_id")
    if "attach_search_eligible" not in cols:
        conn.execute(
            "ALTER TABLE gui_download_history ADD COLUMN attach_search_eligible INTEGER DEFAULT 0"
        )
        cols.add("attach_search_eligible")
    if "history_seq" not in cols:
        conn.execute(
            "ALTER TABLE gui_download_history ADD COLUMN history_seq INTEGER"
        )
        _backfill_gui_download_history_history_seq(conn)
    if "lyric_destination" not in cols:
        conn.execute(
            "ALTER TABLE gui_download_history ADD COLUMN lyric_destination TEXT"
        )
        cols.add("lyric_destination")


def _backfill_gui_download_history_history_seq(conn: sqlite3.Connection) -> None:
    """Assign ``history_seq`` for rows missing it (migration: order ~ legacy ``updated_at``).

    Afterwards only new inserts get new sequence numbers; lyric updates change ``updated_at`` only.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM gui_download_history WHERE history_seq IS NULL",
    ).fetchone()
    if not row or int(row[0] or 0) == 0:
        return
    base = conn.execute(
        "SELECT COALESCE(MAX(history_seq), 0) FROM gui_download_history",
    ).fetchone()
    base_i = int(base[0] or 0) if base else 0
    rows = conn.execute(
        "SELECT audio_path FROM gui_download_history WHERE history_seq IS NULL "
        "ORDER BY updated_at ASC, audio_path COLLATE NOCASE ASC",
    ).fetchall()
    seq = base_i + 1
    for (ap,) in rows:
        conn.execute(
            "UPDATE gui_download_history SET history_seq=? WHERE audio_path=? AND history_seq IS NULL",
            (seq, ap),
        )
        seq += 1


def upsert_gui_download_history(
    audio_path: str,
    *,
    track_no: str = "",
    title: str = "",
    cover_url: str = "",
    lyric_artist: str = "",
    lyric_album: str = "",
    duration_sec: int = 0,
    track_explicit: Optional[int] = None,
    download_status: str = "",
    download_detail: str = "",
    lyric_type: str = "",
    lyric_provider: str = "",
    lyric_confidence: str = "",
    lyric_destination: str = "",
    slot_track_id: str = "",
    release_album_id: str = "",
    pending_slot_cleanup_id: str = "",
    attach_search_eligible: Optional[int] = None,
) -> None:
    """Insert or replace one history row (full row for this file).

    ``GUI_PENDING_TRACK_PREFIX`` rows persist purchase-only / failed slots until a real
    file is saved (caller passes ``pending_slot_cleanup_id`` to remove the pending row).
    """
    import time

    raw_in = (audio_path or "").strip()
    if is_gui_pending_track_key(raw_in):
        p = raw_in
        sid_tail = raw_in[len(GUI_PENDING_TRACK_PREFIX) :].strip()
        if not sid_tail.isdigit():
            return
    else:
        p = _normalize_audio_path_key(audio_path)
        if not p:
            return
        is_miss_ph = is_gui_missing_placeholder_audio_path(p)
        if not is_miss_ph and not os.path.isfile(p):
            return
    dbp = get_qobuz_db_path()
    os.makedirs(os.path.dirname(dbp), exist_ok=True)
    now = time.time()
    sid_col = (slot_track_id or "").strip()
    rid_col = (release_album_id or "").strip()
    if not sid_col and is_gui_pending_track_key(p):
        sid_col = p[len(GUI_PENDING_TRACK_PREFIX) :].strip()
    cleanup = (pending_slot_cleanup_id or "").strip()
    if attach_search_eligible is None:
        attach_eligible_int = 1 if is_gui_pending_track_key(p) else 0
    else:
        attach_eligible_int = 1 if int(attach_search_eligible) else 0
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_gui_download_history_table(conn)
            row = conn.execute(
                "SELECT COALESCE(MAX(history_seq), 0) + 1 FROM gui_download_history",
            ).fetchone()
            next_hist = int(row[0]) if row and row[0] is not None else 1
            conn.execute(
                "INSERT INTO gui_download_history ("
                "audio_path, track_no, title, cover_url, lyric_artist, lyric_album, "
                "duration_sec, track_explicit, download_status, download_detail, "
                "lyric_type, lyric_provider, lyric_confidence, lyric_destination, updated_at, "
                "slot_track_id, release_album_id, attach_search_eligible, history_seq"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(audio_path) DO UPDATE SET "
                "track_no=excluded.track_no, title=excluded.title, cover_url=excluded.cover_url, "
                "lyric_artist=excluded.lyric_artist, lyric_album=excluded.lyric_album, "
                "duration_sec=excluded.duration_sec, track_explicit=excluded.track_explicit, "
                "download_status=excluded.download_status, download_detail=excluded.download_detail, "
                "lyric_type=excluded.lyric_type, lyric_provider=excluded.lyric_provider, "
                "lyric_confidence=excluded.lyric_confidence, "
                "lyric_destination=excluded.lyric_destination, updated_at=excluded.updated_at, "
                "slot_track_id=excluded.slot_track_id, "
                "release_album_id=excluded.release_album_id, "
                "attach_search_eligible=excluded.attach_search_eligible",
                (
                    p,
                    track_no,
                    title,
                    cover_url,
                    lyric_artist,
                    lyric_album,
                    int(duration_sec or 0),
                    track_explicit,
                    download_status,
                    download_detail,
                    lyric_type,
                    lyric_provider,
                    lyric_confidence,
                    lyric_destination,
                    now,
                    sid_col or None,
                    rid_col or None,
                    attach_eligible_int,
                    next_hist,
                ),
            )
            if cleanup:
                pend = f"{GUI_PENDING_TRACK_PREFIX}{cleanup}"
                conn.execute(
                    "DELETE FROM gui_download_history WHERE audio_path=?",
                    (pend,),
                )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}download history upsert: {e}")


def update_gui_download_history_lyrics(
    audio_path: str,
    *,
    lyric_type: str,
    lyric_provider: str = "",
    lyric_confidence: str = "",
    lyric_destination: str = "",
) -> None:
    import time

    p = _normalize_audio_path_key(audio_path)
    if not p or not os.path.isfile(p):
        return
    dbp = get_qobuz_db_path()
    if not os.path.isfile(dbp):
        return
    now = time.time()
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_gui_download_history_table(conn)
            conn.execute(
                "UPDATE gui_download_history SET lyric_type=?, lyric_provider=?, "
                "lyric_confidence=?, lyric_destination=?, updated_at=? WHERE audio_path=?",
                (
                    lyric_type,
                    lyric_provider,
                    lyric_confidence,
                    lyric_destination,
                    now,
                    p,
                ),
            )
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}download history lyrics update: {e}")


def list_gui_download_history() -> list:
    """Rows for audio files that still exist; drops missing files from the table."""
    dbp = get_qobuz_db_path()
    if not os.path.isfile(dbp):
        return []
    out = []
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_gui_download_history_table(conn)
            rows = conn.execute(
                "SELECT audio_path, track_no, title, cover_url, lyric_artist, lyric_album, "
                "duration_sec, track_explicit, download_status, download_detail, "
                "lyric_type, lyric_provider, lyric_confidence, lyric_destination, updated_at, "
                "slot_track_id, release_album_id, attach_search_eligible "
                "FROM gui_download_history ORDER BY "
                "(history_seq IS NULL) ASC, history_seq ASC, "
                "audio_path COLLATE NOCASE ASC"
            ).fetchall()
            removed = 0
            for r in rows:
                ap = r[0]
                if ap and is_gui_pending_track_key(ap):
                    tex = r[7]
                    sid_db = (r[15] or "").strip() if len(r) > 15 else ""
                    rid_db = (r[16] or "").strip() if len(r) > 16 else ""
                    attach_eligible = bool(int(r[17] or 0)) if len(r) > 17 else False
                    if not sid_db:
                        sid_db = ap[len(GUI_PENDING_TRACK_PREFIX) :].strip()
                    out.append(
                        {
                            "audio_path": ap,
                            "track_no": r[1] or "",
                            "title": r[2] or "",
                            "cover_url": r[3] or "",
                            "lyric_artist": r[4] or "",
                            "lyric_album": r[5] or "",
                            "duration_sec": int(r[6] or 0),
                            "track_explicit": bool(tex)
                            if tex is not None
                            else None,
                            "download_status": r[8] or "downloaded",
                            "download_detail": r[9] or "",
                            "lyric_type": r[10] or "",
                            "lyric_provider": r[11] or "",
                            "lyric_confidence": r[12] or "",
                            "lyric_destination": r[13] or "",
                            "updated_at": r[14],
                            "slot_track_id": sid_db,
                            "release_album_id": rid_db,
                            "attach_search_eligible": attach_eligible,
                        }
                    )
                    continue
                if not ap or not os.path.isfile(ap):
                    conn.execute(
                        "DELETE FROM gui_download_history WHERE audio_path=?",
                        (ap,),
                    )
                    removed += 1
                    continue
                tex = r[7]
                sid_db = (r[15] or "").strip() if len(r) > 15 else ""
                rid_db = (r[16] or "").strip() if len(r) > 16 else ""
                attach_eligible = bool(int(r[17] or 0)) if len(r) > 17 else False
                out.append(
                    {
                        "audio_path": ap,
                        "track_no": r[1] or "",
                        "title": r[2] or "",
                        "cover_url": r[3] or "",
                        "lyric_artist": r[4] or "",
                        "lyric_album": r[5] or "",
                        "duration_sec": int(r[6] or 0),
                        "track_explicit": bool(tex)
                        if tex is not None
                        else None,
                        "download_status": r[8] or "downloaded",
                        "download_detail": r[9] or "",
                        "lyric_type": r[10] or "",
                        "lyric_provider": r[11] or "",
                        "lyric_confidence": r[12] or "",
                        "lyric_destination": r[13] or "",
                        "updated_at": r[14],
                        "slot_track_id": sid_db,
                        "release_album_id": rid_db,
                        "attach_search_eligible": attach_eligible,
                    }
                )
            if removed:
                conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}download history list: {e}")
        return []
    return out


def clear_gui_download_history() -> None:
    dbp = get_qobuz_db_path()
    if not os.path.isfile(dbp):
        return
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_gui_download_history_table(conn)
            conn.execute("DELETE FROM gui_download_history")
            conn.commit()
    except sqlite3.Error as e:
        logger.error(f"{RED}download history clear: {e}")


def prune_gui_download_history_orphans() -> int:
    """Remove history rows whose file is gone (e.g. user deleted the library)."""
    dbp = get_qobuz_db_path()
    if not os.path.isfile(dbp):
        return 0
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_gui_download_history_table(conn)
            rows = conn.execute(
                "SELECT audio_path FROM gui_download_history"
            ).fetchall()
            n = 0
            for (ap,) in rows:
                if ap and is_gui_pending_track_key(ap):
                    continue
                if ap and os.path.isfile(ap):
                    continue
                conn.execute(
                    "DELETE FROM gui_download_history WHERE audio_path=?",
                    (ap,),
                )
                n += 1
            if n:
                conn.commit()
            return n
    except sqlite3.Error as e:
        logger.error(f"{RED}download history prune: {e}")
    return 0
