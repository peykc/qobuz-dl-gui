/**
 * Native <select> enhanced with a context-menu-styled dropdown (setup overlay, etc.).
 */
(function () {
  "use strict";
  const QG = (window.QobuzGui = window.QobuzGui || {});
  const ui = (QG.ui = QG.ui || {});
  ui.menuSelect = ui.menuSelect || {};

  function syncTriggerLabel(select, labelEl) {
    const opt = select.options[select.selectedIndex];
    labelEl.textContent = opt ? opt.textContent : "";
  }

  function syncMenuSelection(menu, value) {
    menu.querySelectorAll(".text-field-context-menu-item").forEach((item) => {
      item.classList.toggle(
        "is-selected",
        item.dataset.value === value,
      );
    });
  }

  function closeMenu(wrap) {
    const menu = wrap.querySelector(".menu-select-menu");
    const trigger = wrap.querySelector(".menu-select-trigger");
    if (!menu || !trigger) return;
    menu.classList.add("hidden");
    trigger.setAttribute("aria-expanded", "false");
    wrap.classList.remove("menu-select--open");
  }

  function openMenu(wrap) {
    document.querySelectorAll(".menu-select--open").forEach((other) => {
      if (other !== wrap) closeMenu(other);
    });
    const menu = wrap.querySelector(".menu-select-menu");
    const trigger = wrap.querySelector(".menu-select-trigger");
    if (!menu || !trigger) return;
    menu.classList.remove("hidden");
    trigger.setAttribute("aria-expanded", "true");
    wrap.classList.add("menu-select--open");
  }

  function enhanceSelect(select) {
    if (select.dataset.menuSelectInit === "1") return;
    select.dataset.menuSelectInit = "1";

    const wrap = document.createElement("div");
    wrap.className = "menu-select";
    if (select.classList.contains("search-type-select")) {
      wrap.classList.add("menu-select--search");
    }
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("menu-select-native");

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "menu-select-trigger";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    if (select.id) {
      trigger.setAttribute("aria-labelledby", select.id + "-label");
    }

    const labelSpan = document.createElement("span");
    labelSpan.className = "menu-select-trigger-label";
    syncTriggerLabel(select, labelSpan);
    trigger.appendChild(labelSpan);

    const chevron = document.createElement("span");
    chevron.className = "menu-select-chevron";
    chevron.setAttribute("aria-hidden", "true");
    chevron.innerHTML =
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
    trigger.appendChild(chevron);

    const menu = document.createElement("div");
    menu.className = "menu-select-menu text-field-context-menu hidden";
    menu.setAttribute("role", "listbox");
    if (select.id) {
      menu.id = select.id + "-menu";
      trigger.setAttribute("aria-controls", menu.id);
    }

    Array.from(select.options).forEach((opt) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "text-field-context-menu-item";
      item.setAttribute("role", "option");
      item.dataset.value = opt.value;
      item.textContent = opt.textContent;
      if (opt.selected) item.classList.add("is-selected");
      item.addEventListener("click", (e) => {
        e.preventDefault();
        select.value = opt.value;
        syncTriggerLabel(select, labelSpan);
        syncMenuSelection(menu, opt.value);
        select.dispatchEvent(new Event("change", { bubbles: true }));
        closeMenu(wrap);
      });
      menu.appendChild(item);
    });

    trigger.addEventListener("click", (e) => {
      e.preventDefault();
      if (wrap.classList.contains("menu-select--open")) {
        closeMenu(wrap);
      } else {
        openMenu(wrap);
      }
    });

    wrap.appendChild(trigger);
    wrap.appendChild(menu);

    select.addEventListener("change", () => {
      syncTriggerLabel(select, labelSpan);
      syncMenuSelection(menu, select.value);
    });
  }

  function syncFromSelect(select) {
    if (!select || select.dataset.menuSelectInit !== "1") return;
    const wrap = select.closest(".menu-select");
    if (!wrap) return;
    const labelSpan = wrap.querySelector(".menu-select-trigger-label");
    const menu = wrap.querySelector(".menu-select-menu");
    if (labelSpan) syncTriggerLabel(select, labelSpan);
    if (menu) syncMenuSelection(menu, select.value);
  }

  function init(root) {
    const scope = root || document;
    scope.querySelectorAll("select.menu-select-target").forEach(enhanceSelect);
  }

  document.addEventListener("click", (e) => {
    if (e.target.closest(".menu-select")) return;
    document.querySelectorAll(".menu-select--open").forEach(closeMenu);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.querySelectorAll(".menu-select--open").forEach(closeMenu);
    }
  });

  ui.menuSelect.init = init;
  ui.menuSelect.syncFromSelect = syncFromSelect;
})();
