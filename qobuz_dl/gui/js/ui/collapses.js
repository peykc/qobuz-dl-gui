(function () {
  "use strict";
  const ui = (window.QobuzGui.ui = window.QobuzGui.ui || {});
  ui.collapses = ui.collapses || {};

  ui.collapses.init = function initCollapses() {
    document.querySelectorAll(".collapse-toggle").forEach((btn) => {
      btn.addEventListener("click", () => {
        const body = document.getElementById(
          btn.id.replace("-toggle", "-body"),
        );
        const expanded = btn.getAttribute("aria-expanded") === "true";
        btn.setAttribute("aria-expanded", String(!expanded));
        body.classList.toggle("hidden", expanded);
      });
    });
  };
})();
