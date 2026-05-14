"""One-off: build queueInternals.js from app.js slice."""
from pathlib import Path
import re

root = Path(__file__).resolve().parent.parent
app_lines = (root / "qobuz_dl" / "gui" / "app.js").read_text(encoding="utf-8").splitlines(
    keepends=True
)
# Lines 3559-4305 inclusive (1-based)
chunk = "".join(app_lines[3558:4305])
chunk = chunk.replace("_tsDbItemByKey", "getTsMap()")
chunk = chunk.replace("_GUI_PENDING_AUDIO_PREFIX", "GUI_PENDING")
chunk = re.sub(r"_syncSearchQueuedHighlights\(\)", "syncSearchHi()", chunk)
chunk = chunk.replace("_normalizeSamplingRateHz", "QG.core.format.normalizeSamplingRateHz")
chunk = re.sub(
    r"\n  function _esc\(s\) \{\n    return QG\.core\.dom\.esc\(s\);\n  \}\n",
    "\n",
    chunk,
)
chunk = chunk.replace("_esc(", "QG.core.dom.esc(")
hdr = """(function () {
  "use strict";
  const g = window.QobuzGui;
  const qroot = (g.features.queue = g.features.queue || {});

  /**
   * URL queue state, cards, persist/restore, drag handlers.
   * Invoked once per page from app `initDownload()` with deps.
   */
  function bootstrap(deps) {
    const getTsMap = () => deps.getTrackStatusMap();
    const GUI_PENDING = deps.guiPendingAudioPrefix;
    function syncSearchHi() {
      deps.syncSearchQueuedHighlights();
    }
    const QG = g;
    const api = g.api;

"""

tail = """
    return {
      urlQueue: _urlQueue,
      get textMode() {
        return _textMode;
      },
      initUrlQueue,
      refreshAlbumQueueCardMetas: _refreshAlbumQueueCardMetas,
      queuedUrlSetForSearchHighlight: _queuedUrlSetForSearchHighlight,
      calcTrackTotalFromQueue: _calcTrackTotalFromQueue,
      calcProgressDenominatorFromQueue: _calcProgressDenominatorFromQueue,
      progressBarDenominatorFromQueueItem: _progressBarDenominatorFromQueueItem,
      remainingTracksContributionFromQueueItem: _remainingTracksContributionFromQueueItem,
      albumQueueItemNeedsToStayVisible: _albumQueueItemNeedsToStayVisible,
      addUrlToQueue: _addUrlToQueue,
      removeFromQueueByUrl: _removeFromQueueByUrl,
      removeFromQueue: _removeFromQueue,
      restoreFromServer: _restoreGuiQueueFromServer,
      countHistoryDownloadedForRelease: _countHistoryDownloadedForRelease,
    };
  }

  qroot.internals = qroot.internals || {};
  qroot.internals.bootstrap = bootstrap;
})();
"""

out = root / "qobuz_dl" / "gui" / "js" / "features" / "queue" / "queueInternals.js"
full = hdr + chunk + tail
out.write_text(full, encoding="utf-8", newline="\n")
print("wrote", out.relative_to(root), "bytes", len(full.encode("utf-8")))
