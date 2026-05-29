from unittest.mock import patch

from qobuz_dl.core import QobuzDL


def test_qobuz_session_does_not_create_download_directory_on_init():
    with patch(
        "qobuz_dl.core.create_and_return_dir",
        side_effect=PermissionError("no access"),
    ) as create_dir:
        qobuz = QobuzDL(directory="/Volumes/Musique")

    create_dir.assert_not_called()
    assert qobuz.directory
