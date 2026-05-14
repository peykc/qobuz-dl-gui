(function () {
  "use strict";
  const ui = (window.QobuzGui.ui = window.QobuzGui.ui || {});
  ui.resetButtons = ui.resetButtons || {};

  ui.resetButtons.init = function initResetButtons() {
    document.querySelectorAll(".btn-reset").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetId = btn.dataset.reset;
        const def = btn.dataset.default;
        const input = document.getElementById(targetId);
        if (input) input.value = def;
      });
    });
  };
})();
