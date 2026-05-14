(function () {
  "use strict";
  const ui = (window.QobuzGui.ui = window.QobuzGui.ui || {});
  ui.textFieldContextMenu = ui.textFieldContextMenu || {};

  ui.textFieldContextMenu.init = function initTextFieldContextMenu() {
  const menu = document.getElementById("text-field-context-menu");
  if (!menu) return;

  const tooltip = document.getElementById("global-tooltip");
  let activeField = null;

  const INPUT_TYPES_TEXT = new Set([
    "text",
    "search",
    "url",
    "email",
    "password",
    "tel",
    "number",
    "",
  ]);

  function isTextLikeField(el) {
    if (!el || el.disabled) return false;
    if (el.isContentEditable) return true;
    if (el.tagName === "TEXTAREA") return true;
    if (el.tagName !== "INPUT") return false;
    const t = String(el.type || "text").toLowerCase();
    return INPUT_TYPES_TEXT.has(t);
  }

  function resolveField(target) {
    let n = target;
    if (n && n.nodeType === Node.TEXT_NODE) n = n.parentElement;
    let cur = n;
    let guard = 0;
    while (cur && cur !== document.documentElement && guard++ < 28) {
      if (isTextLikeField(cur)) return cur;
      cur = cur.parentElement;
    }
    return null;
  }

  function pickField(e) {
    let f = resolveField(e.target);
    if (!f) {
      const hit = document.elementFromPoint(e.clientX, e.clientY);
      f = resolveField(hit);
    }
    return f;
  }

  function hideMenu() {
    menu.classList.add("hidden");
    menu.setAttribute("aria-hidden", "true");
    activeField = null;
  }

  function clampMenu(clientX, clientY) {
    const margin = 8;
    void menu.offsetWidth;
    const r = menu.getBoundingClientRect();
    const vv = window.visualViewport;
    const vl = vv ? vv.offsetLeft : 0;
    const vt = vv ? vv.offsetTop : 0;
    const vw = vv ? vv.width : window.innerWidth;
    const vh = vv ? vv.height : window.innerHeight;
    let left = clientX;
    let top = clientY;
    if (left + r.width > vl + vw - margin) left = vl + vw - r.width - margin;
    if (left < vl + margin) left = vl + margin;
    if (top + r.height > vt + vh - margin) top = vt + vh - r.height - margin;
    if (top < vt + margin) top = vt + margin;
    menu.style.left = left + "px";
    menu.style.top = top + "px";
  }

  function selectionLength(field) {
    if (field.isContentEditable) {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return 0;
      return String(sel.toString() || "").length;
    }
    if (
      field.selectionStart != null &&
      field.selectionEnd != null
    ) {
      return Math.abs(field.selectionEnd - field.selectionStart);
    }
    return 0;
  }

  function updateItemStates(field) {
    const ce = field.isContentEditable;
    const ro = ce ? false : field.readOnly;
    const hasSel = selectionLength(field) > 0;
    const canCut = !ro && hasSel;
    const canCopy = hasSel;
    const canPaste = !ro;

    menu.querySelectorAll("[data-action]").forEach((btn) => {
      const a = btn.getAttribute("data-action");
      let dis = false;
      if (a === "cut") dis = !canCut;
      else if (a === "copy") dis = !canCopy;
      else if (a === "paste") dis = !canPaste;
      btn.disabled = dis;
      btn.setAttribute("aria-disabled", dis ? "true" : "false");
    });
  }

  function insertAtCaret(el, text) {
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const val = el.value;
    const before = val.slice(0, start);
    const after = val.slice(end);
    el.value = before + text + after;
    const pos = start + text.length;
    el.setSelectionRange(pos, pos);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function execCut(field) {
    field.focus();
    document.execCommand("cut");
  }

  function execCopy(field) {
    field.focus();
    document.execCommand("copy");
  }

  function execPaste(field) {
    field.focus();
    const applyText = (t) => {
      const text = typeof t === "string" ? t : "";
      if (field.isContentEditable) {
        document.execCommand("insertText", false, text);
      } else {
        insertAtCaret(field, text);
      }
    };

    return fetch("/api/clipboard-text")
      .then((r) => r.json())
      .then((data) => {
        if (data && data.ok && typeof data.text === "string") {
          applyText(data.text);
          return;
        }
        throw new Error("backend clipboard unavailable");
      })
      .catch(() =>
        navigator.clipboard.readText().then(applyText, () => {
          document.execCommand("paste");
        }),
      );
  }

  function execSelectAll(field) {
    field.focus();
    if (field.isContentEditable) {
      document.execCommand("selectAll");
    } else if (typeof field.select === "function") {
      field.select();
    }
  }

  function showMenu(e, field) {
    if (tooltip) tooltip.classList.remove("visible");
    activeField = field;
    updateItemStates(field);
    menu.classList.remove("hidden");
    menu.setAttribute("aria-hidden", "false");
    menu.style.left = e.clientX + "px";
    menu.style.top = e.clientY + "px";
    field.focus();
    requestAnimationFrame(() => clampMenu(e.clientX, e.clientY));
  }

  document.addEventListener(
    "contextmenu",
    (e) => {
      const field = pickField(e);
      if (!field) return;
      e.preventDefault();
      e.stopPropagation();
      showMenu(e, field);
    },
    true,
  );

  menu.addEventListener(
    "mousedown",
    (e) => {
      e.stopPropagation();
    },
    true,
  );

  menu.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-action]");
    if (!btn || btn.disabled) return;
    e.preventDefault();
    e.stopPropagation();
    const field = activeField;
    if (!field) {
      hideMenu();
      return;
    }
    const action = btn.getAttribute("data-action");
    if (action === "paste") {
      void execPaste(field).finally(() => hideMenu());
      return;
    }
    if (action === "cut") execCut(field);
    else if (action === "copy") execCopy(field);
    else if (action === "selectAll") execSelectAll(field);
    hideMenu();
  });

  document.addEventListener(
    "mousedown",
    (e) => {
      if (menu.classList.contains("hidden")) return;
      if (e.button === 2) return;
      if (menu.contains(e.target)) return;
      hideMenu();
    },
    true,
  );

  document.addEventListener(
    "keydown",
    (e) => {
      if (menu.classList.contains("hidden")) return;
      if (e.key === "Escape") {
        e.preventDefault();
        hideMenu();
      }
    },
    true,
  );

  document.addEventListener(
    "scroll",
    () => {
      if (!menu.classList.contains("hidden")) hideMenu();
    },
    true,
  );

  window.addEventListener("blur", () => {
    if (!menu.classList.contains("hidden")) hideMenu();
  });
  };
})();
