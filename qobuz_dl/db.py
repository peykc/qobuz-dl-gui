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
        "updated_at REAL NOT NULL)"
    )


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
) -> None:
    """Insert or replace one history row (full row for this file)."""
    import time

    p = _normalize_audio_path_key(audio_path)
    if not p or not os.path.isfile(p):
        return
    dbp = get_qobuz_db_path()
    os.makedirs(os.path.dirname(dbp), exist_ok=True)
    now = time.time()
    try:
        with sqlite3.connect(dbp) as conn:
            _ensure_gui_download_history_table(conn)
            conn.execute(
                "INSERT INTO gui_download_history ("
                "audio_path, track_no, title, cover_url, lyric_artist, lyric_album, "
                "duration_sec, track_explicit, download_status, download_detail, "
                "lyric_type, lyric_provider, lyric_confidence, updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(audio_path) DO UPDATE SET "
                "track_no=excluded.track_no, title=excluded.title, cover_url=excluded.cover_url, "
                "lyric_artist=excluded.lyric_artist, lyric_album=excluded.lyric_album, "
                "duration_sec=excluded.duration_sec, track_explicit=excluded.track_explicit, "
                "download_status=excluded.download_status, download_detail=excluded.download_detail, "
                "lyric_type=excluded.lyric_type, lyric_provider=excluded.lyric_provider, "
                "lyric_confidence=excluded.lyric_confidence, updated_at=excluded.updated_at",
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
                    now,
                ),
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
                "lyric_confidence=?, updated_at=? WHERE audio_path=?",
                (
                    lyric_type,
                    lyric_provider,
                    lyric_confidence,
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
                "lyric_type, lyric_provider, lyric_confidence, updated_at "
                "FROM gui_download_history ORDER BY updated_at ASC"
            ).fetchall()
            removed = 0
            for r in rows:
                ap = r[0]
                if not ap or not os.path.isfile(ap):
                    conn.execute(
                        "DELETE FROM gui_download_history WHERE audio_path=?",
                        (ap,),
                    )
                    removed += 1
                    continue
                tex = r[7]
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
                        "updated_at": r[13],
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
