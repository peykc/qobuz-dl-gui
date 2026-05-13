import json
import os


def load_feedback_history(path: str) -> list:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            items = raw if isinstance(raw, list) else raw.get("items", [])
            if not isinstance(items, list):
                items = []
        else:
            items = []
    except Exception:
        items = []
    return items[:100]


def save_feedback_history(path: str, config_path: str, items: list) -> None:
    os.makedirs(config_path, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items[:100], f, ensure_ascii=False, indent=2)
