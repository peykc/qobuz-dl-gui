"""Patch app.js: remove inlined queue block, wire queueInternals bootstrap."""
from pathlib import Path
import re

root = Path(__file__).resolve().parent.parent
p = root / "qobuz_dl" / "gui" / "app.js"
text = p.read_text(encoding="utf-8")

if "let _queueHost = null" not in text:
    text = text.replace(
        "  let _sse = null;",
        "  let _queueHost = null;\n\n  let _sse = null;",
        1,
    )

lines = text.splitlines(True)
start = end = None
for i, line in enumerate(lines):
    if "// ── URL Queue System ──" in line:
        start = i
        continue
    if start is not None and "// ── Cover art mutual exclusivity" in line:
        end = i
        break
if start is None or end is None:
    raise RuntimeError(f"queue block markers not found start={start} end={end}")

del lines[start:end]
text = "".join(lines)

text = text.replace(
    "function initDownload() {\n    initUrlQueue();",
    "function initDownload() {\n"
    "    _queueHost = QG.features.queue.internals.bootstrap({\n"
    "      getTrackStatusMap: () => _tsDbItemByKey,\n"
    "      guiPendingAudioPrefix: _GUI_PENDING_AUDIO_PREFIX,\n"
    "      syncSearchQueuedHighlights: _syncSearchQueuedHighlights,\n"
    "    });\n"
    "    _queueHost.initUrlQueue();",
    1,
)

pairs = [
    ("_calcProgressDenominatorFromQueue()", "_queueHost.calcProgressDenominatorFromQueue()"),
    ("_remainingTracksContributionFromQueueItem(", "_queueHost.remainingTracksContributionFromQueueItem("),
    ("_albumQueueItemNeedsToStayVisible(", "_queueHost.albumQueueItemNeedsToStayVisible("),
    ("_refreshAlbumQueueCardMetas()", "_queueHost.refreshAlbumQueueCardMetas()"),
    ("_queuedUrlSetForSearchHighlight()", "_queueHost.queuedUrlSetForSearchHighlight()"),
    ("await _restoreGuiQueueFromServer()", "await _queueHost.restoreFromServer()"),
    ("_removeFromQueue(", "_queueHost.removeFromQueue("),
    ("return _urlQueue.some((q) => q.url === url)", "return _queueHost.urlQueue.some((q) => q.url === url)"),
    ("return _addUrlToQueue(url)", "return _queueHost.addUrlToQueue(url)"),
    ("return _removeFromQueueByUrl(url)", "return _queueHost.removeFromQueueByUrl(url)"),
    (
        "return _countHistoryDownloadedForRelease(releaseAlbumId);",
        "return _queueHost.countHistoryDownloadedForRelease(releaseAlbumId);",
    ),
]
for old, new in pairs:
    if old not in text:
        raise RuntimeError(f"patch token missing: {old!r}")
    text = text.replace(old, new)

text = re.sub(r"\b_urlQueue\b", "_queueHost.urlQueue", text)
text = re.sub(r"\b_textMode\b", "_queueHost.textMode", text)
text = text.replace("_queueHost._queueHost.", "_queueHost.")

p.write_text(text, encoding="utf-8")
print("patched app.js")
