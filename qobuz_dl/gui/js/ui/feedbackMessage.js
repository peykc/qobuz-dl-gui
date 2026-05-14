(function () {
  "use strict";
  const ui = (window.QobuzGui.ui = window.QobuzGui.ui || {});
  const mod = (ui.feedbackMessage = ui.feedbackMessage || {});

  let _buttonFeedbackTimer = null;

  function show(el, msg, ok) {
    el.textContent = msg;
    el.className = "feedback-msg " + (ok ? "ok" : "err");
    setTimeout(() => {
      el.className = "feedback-msg hidden";
    }, 3500);
  }

  function showButton(btn, msg, ok) {
    if (!btn) return;
    const originalText = btn.dataset.defaultText || btn.textContent;
    btn.dataset.defaultText = originalText;
    if (_buttonFeedbackTimer) {
      clearTimeout(_buttonFeedbackTimer);
      _buttonFeedbackTimer = null;
    }
    btn.textContent = msg;
    btn.disabled = true;
    btn.classList.toggle("settings-check-updates-btn--ok", !!ok);
    btn.classList.toggle("settings-check-updates-btn--err", !ok);
    _buttonFeedbackTimer = setTimeout(() => {
      btn.textContent = btn.dataset.defaultText || "Check for updates";
      btn.disabled = false;
      btn.classList.remove("settings-check-updates-btn--ok", "settings-check-updates-btn--err");
      _buttonFeedbackTimer = null;
    }, 3500);
  }

  mod.show = show;
  mod.showButton = showButton;
})();
