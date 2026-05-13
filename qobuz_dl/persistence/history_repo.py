from qobuz_dl import db


def list_rows():
    return db.list_gui_download_history()


def upsert_row(audio_path, **fields):
    return db.upsert_gui_download_history(audio_path, **fields)


def update_lyrics(audio_path, **fields):
    return db.update_gui_download_history_lyrics(audio_path, **fields)


def clear_rows():
    return db.clear_gui_download_history()


def prune_orphans():
    return db.prune_gui_download_history_orphans()
