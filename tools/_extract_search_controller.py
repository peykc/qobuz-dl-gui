"""Extract search UI from gui/app.js into js/features/search/searchController.js"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "qobuz_dl" / "gui" / "app.js"
OUT = ROOT / "qobuz_dl" / "gui" / "js" / "features" / "search" / "searchController.js"

PREFIX = '''(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g.api;
  const features = (g.features = g.features || {});

  function qfeat() {
    return features.queue || {};
  }

  const TIP_SEARCH_QUEUED_IDLE = "In download queue";
  const TIP_SEARCH_QUEUED_REMOVE = "Remove from queue";

  const RESULT_ADD_BTN_HTML_ARROW = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
            <polyline points="12 5 19 12 12 19"></polyline>
        </svg>
      `;
  const RESULT_ADD_BTN_HTML_CHECK = `
            <span class="result-add-btn-ico-stack">
                <span class="result-add-btn-ico result-add-btn-ico--check" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                </span>
                <span class="result-add-btn-ico result-add-btn-ico--remove" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </span>
            </span>
          `;

  function setSearchResultAddBtnAppearance(addBtn, inQueue) {
    if (!addBtn) return;
    addBtn.classList.toggle("result-add-btn--queued", !!inQueue);
    if (inQueue) {
      addBtn.setAttribute("aria-label", "In download queue, activate to remove");
      addBtn.setAttribute("data-tip", TIP_SEARCH_QUEUED_IDLE);
      addBtn.innerHTML = RESULT_ADD_BTN_HTML_CHECK;
    } else {
      addBtn.setAttribute("aria-label", "Add to Queue");
      addBtn.setAttribute("data-tip", "Add to Queue");
      addBtn.innerHTML = RESULT_ADD_BTN_HTML_ARROW;
    }
  }

  function syncQueuedHighlights() {
    const list = document.getElementById("search-results");
    if (!list) return;
    const queued =
      features.queue && features.queue.getQueuedUrlSet
        ? features.queue.getQueuedUrlSet()
        : new Set();
    list.querySelectorAll(".result-item").forEach((row) => {
      const url = row.dataset.queueUrl || "";
      const inQueue = Boolean(url && queued.has(url));
      row.classList.toggle("result-item--queued", inQueue);
      const btn = row.querySelector(".result-add-btn");
      setSearchResultAddBtnAppearance(btn, inQueue);
    });
  }

'''

SUFFIX = """
  features.search = features.search || {};
  features.search.init = initSearch;
  features.search.syncQueuedHighlights = syncQueuedHighlights;
})();
"""


def main() -> None:
    lines = APP.read_text(encoding="utf-8").splitlines(True)
    # Line numbers from current app.js (1-indexed): start "// ── Search" state through end of doLucky
    start = 5276  # 0-based: "// ── Search tab"
    end = 5664  # exclusive: line before "  // ── Settings tab"
    body = "".join(lines[start:end])
    if "// ── Search tab" not in body.splitlines()[0]:
        raise SystemExit(f"unexpected first line of chunk: {body.splitlines()[0]!r}")
    body_lines = body.splitlines(True)[1:]  # drop section header comment line
    body = "".join(body_lines)

    body = body.replace(
        "_urlQueue.some((q) => q.url === r.url)",
        "(qfeat().hasUrl ? qfeat().hasUrl(r.url) : false)",
    )
    body = body.replace("_addUrlToQueue(r.url)", "qfeat().addUrl(r.url)")
    body = body.replace("_removeFromQueueByUrl(r.url)", "qfeat().removeUrl(r.url)")
    body = body.replace(
        "_setSearchResultAddBtnAppearance(addBtn",
        "setSearchResultAddBtnAppearance(addBtn",
    )
    body = body.replace("_TIP_SEARCH_QUEUED_REMOVE", "TIP_SEARCH_QUEUED_REMOVE")
    body = body.replace("_TIP_SEARCH_QUEUED_IDLE", "TIP_SEARCH_QUEUED_IDLE")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(PREFIX + body + SUFFIX, encoding="utf-8")
    print("Wrote", OUT.relative_to(ROOT), len(OUT.read_text(encoding="utf-8")), "chars")


if __name__ == "__main__":
    main()
