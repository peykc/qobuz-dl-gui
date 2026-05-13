from qobuz_dl.domain.models import HistoryRow
from qobuz_dl.persistence import history_repo


def list_history():
    return history_repo.list_rows()


def clear_history():
    return history_repo.clear_rows()


def upsert_history_row(audio_path, **fields):
    return history_repo.upsert_row(audio_path, **fields)


def update_history_lyrics(audio_path, **fields):
    return history_repo.update_lyrics(audio_path, **fields)


def history_row_from_mapping(row):
    return HistoryRow(
        audio_path=row.get("audio_path", ""),
        track_no=row.get("track_no", ""),
        title=row.get("title", ""),
        lyric_album=row.get("lyric_album", ""),
        download_status=row.get("download_status", "downloaded"),
        slot_track_id=row.get("slot_track_id", ""),
        release_album_id=row.get("release_album_id", ""),
    )
