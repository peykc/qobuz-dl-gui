(function () {
  "use strict";
  const dom = (window.QobuzGui.core.dom = window.QobuzGui.core.dom || {});

  /** True if the scrollable element is at (or within a few px of) the bottom. */
  function scrollContainerAtBottom(el, slackPx) {
    const slack = slackPx == null ? 8 : slackPx;
    if (!el) return true;
    const max = el.scrollHeight - el.clientHeight;
    if (max <= 0) return true;
    return el.scrollTop >= max - slack;
  }

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  dom.scrollContainerAtBottom = scrollContainerAtBottom;
  dom.esc = esc;
})();
