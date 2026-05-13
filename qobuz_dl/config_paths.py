import os
from typing import Optional


APP_DIR_NAME = "qobuz-dl"
CONFIG_FILENAME = "config.ini"
DB_FILENAME = "qobuz_dl.db"
DOWNLOAD_QUEUE_FILENAME = "download_queue.json"
GUI_FEEDBACK_HISTORY_FILENAME = "gui_feedback_history.json"


def get_os_config_dir(platform_name: Optional[str] = None, env=None) -> str:
    """Return the OS config root used by the CLI, GUI, and DB helpers."""
    platform_name = os.name if platform_name is None else platform_name
    env = os.environ if env is None else env
    if platform_name == "nt":
        return env.get("APPDATA")
    return os.path.join(env["HOME"], ".config")


def get_config_path(platform_name: Optional[str] = None, env=None) -> str:
    return os.path.join(get_os_config_dir(platform_name, env), APP_DIR_NAME)


def get_config_file(platform_name: Optional[str] = None, env=None) -> str:
    return os.path.join(get_config_path(platform_name, env), CONFIG_FILENAME)


def get_qobuz_db_path(platform_name: Optional[str] = None, env=None) -> str:
    return os.path.join(get_config_path(platform_name, env), DB_FILENAME)


def get_download_queue_path(platform_name: Optional[str] = None, env=None) -> str:
    return os.path.join(get_config_path(platform_name, env), DOWNLOAD_QUEUE_FILENAME)


def get_gui_feedback_history_path(
    platform_name: Optional[str] = None,
    env=None,
) -> str:
    return os.path.join(get_config_path(platform_name, env), GUI_FEEDBACK_HISTORY_FILENAME)


CONFIG_PATH = get_config_path()
CONFIG_FILE = get_config_file()
QOBUZ_DB = get_qobuz_db_path()
DOWNLOAD_QUEUE_JSON = get_download_queue_path()
GUI_FEEDBACK_HISTORY_JSON = get_gui_feedback_history_path()
