(function () {
  "use strict";
  const ui = (window.QobuzGui.ui = window.QobuzGui.ui || {});
  ui.globalTooltip = ui.globalTooltip || {};

  ui.globalTooltip.init = function initGlobalTooltip() {
  const tooltip = document.getElementById("global-tooltip");
  if (!tooltip) return;

  let activeTarget = null;

  function _viewportClientBox() {
    const vv = window.visualViewport;
    if (vv) {
      return {
        left: vv.offsetLeft,
        top: vv.offsetTop,
        width: vv.width,
        height: vv.height,
      };
    }
    return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
  }

  /** Nudge tooltip so its paint box stays inside the client viewport (WebView quirks, scrollbars). */
  function _clampTooltipToViewport(marginPx) {
    const m = marginPx;
    void tooltip.offsetWidth;
    let r = tooltip.getBoundingClientRect();
    let baseLeft = parseFloat(tooltip.style.left);
    let baseTop = parseFloat(tooltip.style.top);
    if (!Number.isFinite(baseLeft)) baseLeft = r.left;
    if (!Number.isFinite(baseTop)) baseTop = r.top;
    for (let pass = 0; pass < 3; pass++) {
      const vp = _viewportClientBox();
      const minL = vp.left + m;
      const maxR = vp.left + vp.width - m;
      const minT = vp.top + m;
      const maxB = vp.top + vp.height - m;
      let dx = 0;
      let dy = 0;
      if (r.left < minL) dx = minL - r.left;
      else if (r.right > maxR) dx = maxR - r.right;
      if (r.top < minT) dy = minT - r.top;
      else if (r.bottom > maxB) dy = maxB - r.bottom;
      if (!dx && !dy) break;
      baseLeft += dx;
      baseTop += dy;
      tooltip.style.left = baseLeft + "px";
      tooltip.style.top = baseTop + "px";
      void tooltip.offsetWidth;
      r = tooltip.getBoundingClientRect();
    }
  }

  const formatHelpTooltipId = {
    "folder-format-help": "folder-format-tooltip",
    "track-format-help": "track-format-tooltip",
    "multi-disc-format-help": "multi-disc-format-tooltip",
  };

  function shouldSuppressDataTip(targetEl) {
    if (!targetEl || !targetEl.id) return false;
    if (targetEl.id === "settings-gear-btn") {
      const pop = document.getElementById("settings-popover");
      return !!(pop && !pop.classList.contains("hidden"));
    }
    if (targetEl.id === "report-issue-btn") {
      const pop = document.getElementById("issue-report-popover");
      return !!(pop && !pop.classList.contains("hidden"));
    }
    if (targetEl.id === "monero-btn") {
      const pop = document.getElementById("donation-popover");
      return !!(pop && !pop.classList.contains("hidden"));
    }
    const tipId = formatHelpTooltipId[targetEl.id];
    if (tipId) {
      const tip = document.getElementById(tipId);
      return !!(tip && tip.style.display === "block");
    }
    return false;
  }

  document.addEventListener("mouseover", (e) => {
    let el = e.target;
    if (!el) return;
    if (el.nodeType === Node.TEXT_NODE) el = el.parentElement;
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return;

    let targetEl = el.closest("[data-tip]");
    let tipText = targetEl ? targetEl.getAttribute("data-tip") : null;

    if (!targetEl) {
      // Auto-detect truncation (native ``title`` is not set on lyric rows | avoids bogus browser tooltips)
      const style = window.getComputedStyle(el);
      if (
        style.textOverflow === "ellipsis" &&
        el.scrollWidth - el.offsetWidth > 2
      ) {
        targetEl = el;
        tipText = el.textContent.trim();
      }
    }

    if (targetEl && tipText && shouldSuppressDataTip(targetEl)) {
      return;
    }

    if (targetEl && tipText) {
      activeTarget = targetEl;
      const iconSrc = targetEl.getAttribute("data-tip-icon");
      const safeIcon =
        iconSrc &&
        typeof iconSrc === "string" &&
        iconSrc.trim().startsWith("/gui/") &&
        !iconSrc.includes("..");
      tooltip.classList.toggle("global-tooltip--with-icon", !!safeIcon);
      if (safeIcon) {
        tooltip.replaceChildren();
        const lines = tipText.split(/\r?\n/);
        const titleLine = (lines[0] || "").trim();
        const bodyRest = lines.slice(1).join("\n").trim();
        if (bodyRest) {
          const stack = document.createElement("div");
          stack.className = "global-tooltip-tag-stack";
          const titleEl = document.createElement("div");
          titleEl.className = "global-tooltip-tag-title";
          titleEl.textContent = titleLine;
          stack.appendChild(titleEl);
          const row = document.createElement("div");
          row.className = "global-tooltip-provider-row";
          const img = document.createElement("img");
          img.className = "global-tooltip-icon";
          img.src = iconSrc.trim();
          img.alt = "";
          img.decoding = "async";
          const textEl = document.createElement("div");
          textEl.className = "global-tooltip-provider-text";
          textEl.textContent = bodyRest;
          row.appendChild(img);
          row.appendChild(textEl);
          stack.appendChild(row);
          tooltip.appendChild(stack);
        } else {
          const row = document.createElement("div");
          row.className = "global-tooltip-icon-row";
          const img = document.createElement("img");
          img.className = "global-tooltip-icon";
          img.src = iconSrc.trim();
          img.alt = "";
          img.decoding = "async";
          const textEl = document.createElement("div");
          textEl.className = "global-tooltip-icon-text";
          textEl.textContent = titleLine || tipText;
          row.appendChild(img);
          row.appendChild(textEl);
          tooltip.appendChild(row);
        }
      } else {
        tooltip.textContent = tipText;
      }
      tooltip.classList.add("visible");

      void tooltip.offsetWidth;

      const rect = targetEl.getBoundingClientRect();
      const margin = 10;
      const tipW = tooltip.offsetWidth;
      const tipH = tooltip.offsetHeight;
      const vpBox = _viewportClientBox();
      const vpBot = vpBox.top + vpBox.height;
      const place = (
        targetEl.getAttribute("data-tip-placement") || ""
      ).toLowerCase();
      let top;
      if (place === "bottom") {
        top = rect.bottom + margin;
        if (top + tipH > vpBot - margin) {
          top = rect.top - tipH - margin;
        }
      } else if (place === "top") {
        top = rect.top - tipH - margin;
        if (top < vpBox.top + margin) top = rect.bottom + margin;
      } else {
        top = rect.top - tipH - margin;
        if (top < vpBox.top + margin) top = rect.bottom + margin;
      }
      top = Math.max(
        vpBox.top + margin,
        Math.min(
          top,
          vpBot - tipH - margin,
        ),
      );

      let left = rect.left + rect.width / 2 - tipW / 2;
      const leftMax = vpBox.left + vpBox.width - tipW - margin;
      left = Math.max(vpBox.left + margin, Math.min(left, leftMax));

      tooltip.style.top = top + "px";
      tooltip.style.left = left + "px";
      _clampTooltipToViewport(margin);
    }
  });

  document.addEventListener("mouseout", (e) => {
    if (activeTarget && !activeTarget.contains(e.relatedTarget)) {
      tooltip.classList.remove("visible");
      activeTarget = null;
    }
  });

  document.addEventListener("scroll", () => {
    if (activeTarget) {
      tooltip.classList.remove("visible");
      activeTarget = null;
    }
  }, true);

  // Capture so this runs before handlers that call stopPropagation() (e.g. monero, format help).
  document.addEventListener(
    "click",
    () => {
      if (activeTarget) {
        tooltip.classList.remove("visible");
        activeTarget = null;
      }
    },
    true,
  );
  };
})();
