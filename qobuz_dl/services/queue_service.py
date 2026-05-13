import json
import os


EMPTY_QUEUE_DOCUMENT = {
    "ok": True,
    "version": 1,
    "text_mode": False,
    "text_urls": "",
    "items": [],
}


def sanitize_gui_queue_items(items) -> list:
    if not items or not isinstance(items, list):
        return []
    out = []
    for it in items[:5000]:
        if not isinstance(it, dict):
            continue
        url = (it.get("url") or "").strip()
        if not url:
            continue
        res = it.get("resolved")
        if res is not None and not isinstance(res, dict):
            res = None
        out.append({"url": url, "resolved": res})
    return out


def load_download_queue(queue_json: str) -> dict:
    if not os.path.isfile(queue_json):
        return dict(EMPTY_QUEUE_DOCUMENT)
    try:
        with open(queue_json, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(EMPTY_QUEUE_DOCUMENT)
        return {
            "ok": True,
            "version": int(data.get("version") or 1),
            "text_mode": bool(data.get("text_mode")),
            "text_urls": str(data.get("text_urls") or ""),
            "items": sanitize_gui_queue_items(data.get("items")),
        }
    except Exception:
        raise


def build_download_queue_document(payload: dict) -> dict:
    text_urls = str(payload.get("text_urls") or "")
    if len(text_urls) > 1_500_000:
        raise ValueError("payload too large")
    items = payload.get("items")
    if items is not None and not isinstance(items, list):
        raise TypeError("items must be a list")
    return {
        "version": 1,
        "text_mode": bool(payload.get("text_mode")),
        "text_urls": text_urls,
        "items": sanitize_gui_queue_items(items),
    }


def save_download_queue(queue_json: str, document: dict) -> None:
    tmp = queue_json + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(document, f, ensure_ascii=False, indent=0)
    os.replace(tmp, queue_json)
