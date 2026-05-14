(function () {
  "use strict";
  const fb = ((window.QobuzGui.features = window.QobuzGui.features || {}).formatBuilder =
    window.QobuzGui.features.formatBuilder || {});
  fb.formatTooltips = fb.formatTooltips || {};

  fb.formatTooltips.init = function initFormatTooltips() {
  let openTip = null;
  const tooltipToTrigger = new Map();

  function positionFormatTooltip(tip, anchorEl) {
    const zone = anchorEl.closest(".form-group");
    if (!zone) return;
    
    tip.style.position = "fixed";
    tip.style.display = "block";
    tip.style.top = "auto";
    tip.style.bottom = "auto";
    tip.style.left = "auto";
    tip.style.right = "auto";
    tip.style.transform = "";
    
    const tipRect = tip.getBoundingClientRect();
    const tipHeight = tipRect.height;
    const tipWidth = tipRect.width;
    
    const zoneRect = zone.getBoundingClientRect();
    const margin = 8;
    
    const spaceAbove = zoneRect.top;
    const spaceBelow = window.innerHeight - zoneRect.bottom;
    const spaceLeft = zoneRect.left;
    const spaceRight = window.innerWidth - zoneRect.right;
    
    if (spaceAbove >= tipHeight + margin) {
      tip.style.bottom = (window.innerHeight - zoneRect.top + margin) + "px";
      const rightFromEdge = window.innerWidth - zoneRect.right;
      tip.style.right = Math.max(margin, rightFromEdge) + "px";
    } else if (spaceRight >= tipWidth + margin) {
      tip.style.left = (zoneRect.right + margin) + "px";
      let topPos = zoneRect.top + (zoneRect.height / 2) - (tipHeight / 2);
      if (topPos < margin) {
        topPos = margin;
      } else if (topPos + tipHeight + margin > window.innerHeight) {
        topPos = window.innerHeight - tipHeight - margin;
      }
      tip.style.top = topPos + "px";
    } else if (spaceLeft >= tipWidth + margin) {
      tip.style.right = (window.innerWidth - zoneRect.left + margin) + "px";
      let topPos = zoneRect.top + (zoneRect.height / 2) - (tipHeight / 2);
      if (topPos < margin) {
        topPos = margin;
      } else if (topPos + tipHeight + margin > window.innerHeight) {
        topPos = window.innerHeight - tipHeight - margin;
      }
      tip.style.top = topPos + "px";
    } else if (spaceBelow >= tipHeight + margin) {
      tip.style.top = (zoneRect.bottom + margin) + "px";
      const rightFromEdge = window.innerWidth - zoneRect.right;
      tip.style.right = Math.max(margin, rightFromEdge) + "px";
    } else {
      tip.style.top = "50%";
      tip.style.left = "50%";
      tip.style.transform = "translate(-50%, -50%)";
    }
    
    if (tip.style.right && tip.style.right !== "auto" && (!tip.style.left || tip.style.left === "auto")) {
      const rect = tip.getBoundingClientRect();
      if (rect.left < margin) {
        tip.style.right = "auto";
        tip.style.left = margin + "px";
      }
    }
  }

  const formatExamples = {
    "{artist}": "Bastille",
    "{albumartist}": "Bastille",
    "{album}": "Bad Blood X (10th Anniversary Edition)",
    "{album_title_base}": "Bad Blood X",
    "{year}": "2013",
    "{release_date}": "2013-03-04",
    "{label}": "UMC (Universal Music Catalogue)",
    "{barcode}": "0602458674385",
    "{disc_count}": "2",
    "{track_count}": "33",
    "{bit_depth}": "24",
    "{sampling_rate}": "96.0",
    "{format}": "FLAC",
    "{tracknumber}": "08",
    "{track_number}": "08",
    "{tracktitle}": "Icarus (Dan's Bedroom Demo)",
    "{track_title_base}": "Icarus (feat. Maya)",
    "{version}": "10th Anniversary Edition",
    "{disc_number}": "02",
    "{disc_number_unpadded}": "2",
    "{isrc}": "GBUM72301353"
  };

  function generatePreview(text) {
    return text.replace(/\{[^}]+\}/g, match => formatExamples[match] || match);
  }

  function updateBuilderPreview(tip, builderInput) {
    const preview = tip.querySelector(".fmt-preview-output");
    if (!preview || !builderInput) return;
    const val = builderInput.value;
    if (!val) {
      resetFormatPreview(tip);
      return;
    }
    let generated = generatePreview(val);
    const targetId = builderInput.getAttribute("data-target");
    if (targetId && targetId.includes("track-format")) {
      generated += ".flac";
    }
    preview.textContent = generated;
    preview.classList.remove("fmt-preview-placeholder");
    preview.classList.add("fmt-preview-builder");
  }

  function resetFormatPreview(tip) {
    const preview = tip.querySelector(".fmt-preview-output");
    const builderInput = tip.querySelector(".fmt-builder-input");
    if (!preview) return;
    if (builderInput && builderInput.value) {
      updateBuilderPreview(tip, builderInput);
      return;
    }
    const ph = preview.dataset.placeholder || "Hover a template or type in builder";
    preview.textContent = ph;
    preview.classList.add("fmt-preview-placeholder");
    preview.classList.remove("fmt-preview-builder");
  }

  function closeAllFormatTips() {
    if (!openTip) return;
    openTip.style.display = "none";
    resetFormatPreview(openTip);
    const prevId = tooltipToTrigger.get(openTip.id);
    const prevTrigger = document.getElementById(prevId);
    if (prevTrigger) {
      prevTrigger.classList.remove("active");
      prevTrigger.setAttribute("aria-expanded", "false");
    }
    openTip = null;
  }

  function bindTemplatePreviews(tip) {
    const preview = tip.querySelector(".fmt-preview-output");
    const container = tip.querySelector(".fmt-templates");
    const builderInput = tip.querySelector(".fmt-builder-input");
    const builderHighlights = tip.querySelector(".fmt-builder-highlights");
    
    if (!preview) return;
    const placeholder = preview.dataset.placeholder || "Hover a template or type in builder";

    if (container) {
      container.querySelectorAll(".fmt-template-chip").forEach((chip) => {
        chip.addEventListener("mouseenter", () => {
          const text = chip.getAttribute("data-preview");
          if (!text) return;
          preview.textContent = text;
          preview.classList.remove("fmt-preview-placeholder");
          preview.classList.remove("fmt-preview-builder");
        });
        chip.addEventListener("click", () => {
          if (builderInput) {
            builderInput.value = chip.textContent;
            builderInput.dispatchEvent(new Event("input", { bubbles: true }));
            
            // Flash effect
            const originalBg = chip.style.background;
            chip.style.background = "var(--success-dim)";
            chip.style.borderColor = "var(--success)";
            setTimeout(() => {
              chip.style.background = originalBg;
              chip.style.borderColor = "";
            }, 300);
          }
        });
      });
      container.addEventListener("mouseleave", () => {
        resetFormatPreview(tip);
      });
    }

    if (builderInput && builderHighlights) {
      const applyBtn = tip.querySelector(".fmt-builder-apply");
      const targetId = builderInput.getAttribute("data-target");
      const targetInput = targetId ? document.getElementById(targetId) : null;

      const checkApplyState = () => {
        if (!applyBtn || !targetInput) return;
        if (targetInput.value !== builderInput.value) {
          applyBtn.classList.add("active");
          applyBtn.disabled = false;
        } else {
          applyBtn.classList.remove("active");
          applyBtn.disabled = true;
        }
      };

      const updateHighlights = () => {
        const text = builderInput.value;
        // Escape HTML
        const escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        // Wrap {vars} in span
        const highlighted = escaped.replace(/(\{[^}]+\})/g, '<span class="var">$1</span>');
        builderHighlights.innerHTML = highlighted;
        updateBuilderPreview(tip, builderInput);
        checkApplyState();
      };

      builderInput.addEventListener("input", () => {
        updateHighlights();
      });

      if (applyBtn && targetInput) {
        applyBtn.addEventListener("click", () => {
          if (applyBtn.disabled) return;
          targetInput.value = builderInput.value;
          targetInput.dispatchEvent(new Event("input", { bubbles: true }));
          checkApplyState();
        });
      }

      builderInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          if (applyBtn && !applyBtn.disabled) {
            applyBtn.click();
          }
        }
      });
      
      // Sync back from main input if user types there while tooltip is open
      if (targetInput) {
        targetInput.addEventListener("input", () => {
          if (openTip === tip && builderInput.value !== targetInput.value) {
            builderInput.value = targetInput.value;
            updateHighlights();
          }
        });
      }
      builderInput.addEventListener("scroll", () => {
        builderHighlights.scrollLeft = builderInput.scrollLeft;
      });
      
      // Handle clicking variables
      tip.querySelectorAll(".fmt-vars-table code").forEach(codeEl => {
        codeEl.addEventListener("click", () => {
          const varText = codeEl.textContent;
          const start = builderInput.selectionStart;
          const end = builderInput.selectionEnd;
          const val = builderInput.value;
          builderInput.value = val.substring(0, start) + varText + val.substring(end);
          builderInput.selectionStart = builderInput.selectionEnd = start + varText.length;
          builderInput.focus();
          updateHighlights();
        });
      });
    }
  }

  const pairs = [
    ["folder-format-help", "folder-format-tooltip"],
    ["track-format-help", "track-format-tooltip"],
    ["multi-disc-format-help", "multi-disc-format-tooltip"],
  ];

  /** Open tooltip id → its format text field (only this element keeps the panel open on click-outside). */
  const tooltipInputId = {
    "folder-format-tooltip": "dl-folder-format",
    "track-format-tooltip": "dl-track-format",
    "multi-disc-format-tooltip": "dl-multiple-disc-track-format",
  };

  pairs.forEach(([triggerId, tooltipId]) => {
    tooltipToTrigger.set(tooltipId, triggerId);
  });

  pairs.forEach(([triggerId, tooltipId]) => {
    const trigger = document.getElementById(triggerId);
    const tip = document.getElementById(tooltipId);
    if (!trigger || !tip) return;

    // Keep format popovers out of the download/settings stacking contexts.
    if (tip.parentNode !== document.body) document.body.appendChild(tip);
    bindTemplatePreviews(tip);

    function toggleFromTrigger(e) {
      if (e) {
        e.preventDefault();
        e.stopPropagation();
      }
      const wasOpen = openTip === tip && tip.style.display === "block";
      closeAllFormatTips();
      if (!wasOpen) {
        positionFormatTooltip(tip, trigger);
        openTip = tip;
        trigger.classList.add("active");
        trigger.setAttribute("aria-expanded", "true");
        
        // Sync builder with main input when opening
        const builderInput = tip.querySelector(".fmt-builder-input");
        if (builderInput) {
          const targetId = builderInput.getAttribute("data-target");
          if (targetId) {
            const targetInput = document.getElementById(targetId);
            if (targetInput) {
              builderInput.value = targetInput.value;
              builderInput.dispatchEvent(new Event("input", { bubbles: true }));
            }
          }
        }
      }
    }

    trigger.addEventListener("click", toggleFromTrigger);
    trigger.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggleFromTrigger(e);
      }
    });
  });

  let mousedownTarget = null;
  document.addEventListener("mousedown", (e) => {
    mousedownTarget = e.target;
  });

  document.addEventListener("click", (e) => {
    if (!openTip) return;
    const target = mousedownTarget || e.target;
    if (openTip.contains(target)) return;
    const triggers = pairs
      .map(([id]) => document.getElementById(id))
      .filter(Boolean);
    if (triggers.some((t) => t.contains(target))) return;
    const fieldId = tooltipInputId[openTip.id];
    if (fieldId && target && target.id === fieldId) return;
    closeAllFormatTips();
  });

  window.addEventListener("resize", () => {
    if (!openTip) return;
    const tid = tooltipToTrigger.get(openTip.id);
    const tr = document.getElementById(tid);
    if (tr) positionFormatTooltip(openTip, tr);
  });

  let isHoveringVars = false;

  pairs.forEach(([triggerId, tooltipId]) => {
    const tip = document.getElementById(tooltipId);
    if (!tip) return;
    const scrollArea = tip.querySelector(".fmt-vars-scroll");
    if (scrollArea) {
      scrollArea.addEventListener("mouseenter", () => isHoveringVars = true);
      scrollArea.addEventListener("mouseleave", () => isHoveringVars = false);
    }
  });

  // Scroll does not bubble; use capture so any scrollable ancestor closes the panel.
  window.addEventListener(
    "scroll",
    (e) => {
      if (isHoveringVars) return;
      if (e.target && e.target.tagName === "INPUT") return;
      if (e.target && e.target.classList) {
        if (
          e.target.classList.contains("fmt-vars-scroll") ||
          e.target.classList.contains("fmt-builder-input") ||
          e.target.classList.contains("fmt-builder-highlights") ||
          e.target.classList.contains("format-tooltip")
        ) {
          return;
        }
      }
      // Auto-scroll on the download history list must not dismiss the panel.
      if (
        e.target &&
        typeof e.target.closest === "function" &&
        (e.target.closest("#dl-track-status") ||
          e.target.closest("#lyric-search-popover") ||
          e.target.closest("#attach-track-popover"))
      ) {
        return;
      }
      closeAllFormatTips();
    },
    true,
  );
  };
})();
