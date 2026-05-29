/**
 * Settings-popover actions (S2B): re-auth, update check, purge DB, issue-report launch wiring.
 */
(function () {
  "use strict";
  const QG = (window.QobuzGui = window.QobuzGui || {});
  QG.features = QG.features || {};
  const settings = (QG.features.settings = QG.features.settings || {});
  const api = QG.api;

  function init(deps) {
    deps = deps || {};
    const checkStatus = deps.checkStatus || (async () => null);
    const updateStatus = deps.updateStatus || (() => {});
    const loadSettingsForm = deps.loadSettingsForm || (async () => {});

    const feedback = document.getElementById("settings-popover-feedback");
    QG.features.feedback.issueReport.init(checkStatus);

    const reauthBtn = document.getElementById("settings-reauth-btn");
    const reauthText = document.getElementById("settings-reauth-text");
    const reauthSpinner = document.getElementById("settings-reauth-spinner");
    let _reauthPolling = null;

    reauthBtn.addEventListener("click", () => {
      if (_reauthPolling) {
        clearInterval(_reauthPolling);
        _reauthPolling = null;
      }
      const popover = document.getElementById("settings-popover");
      const backdrop = document.getElementById("settings-backdrop");
      const gearBtn = document.getElementById("settings-gear-btn");
      if (popover) popover.classList.add("hidden");
      if (backdrop) backdrop.classList.add("hidden");
      if (gearBtn) gearBtn.classList.remove("active");
      if (feedback) feedback.className = "feedback-msg hidden";
      reauthText.textContent = "Re-login with Qobuz";
      reauthSpinner.classList.add("hidden");
      reauthBtn.disabled = false;
      updateStatus(false);
      if (
        QG.features.setup &&
        typeof QG.features.setup.showSetup === "function"
      ) {
        QG.features.setup.showSetup();
      }
    });

    const checkUpdBtn = document.getElementById("settings-check-updates-btn");
    const updFeedback = document.getElementById("settings-update-feedback");
    if (checkUpdBtn && updFeedback) {
      checkUpdBtn.addEventListener("click", async () => {
        const originalText =
          checkUpdBtn.dataset.defaultText || checkUpdBtn.textContent;
        checkUpdBtn.dataset.defaultText = originalText;
        checkUpdBtn.disabled = true;
        updFeedback.className = "feedback-msg hidden";
        checkUpdBtn.classList.remove(
          "settings-check-updates-btn--ok",
          "settings-check-updates-btn--err",
        );
        checkUpdBtn.textContent = "Checking...";
        try {
          const data = await QG.features.updateBanner.refreshUpdateCheck(true);
          if (!data) throw new Error("Network error");
          if (data.skipped && data.reason === "repo_not_configured") {
            QG.ui.feedbackMessage.showButton(
              checkUpdBtn,
              "Update source not configured (see qobuz_dl/version.py).",
              false,
            );
          } else if (!data.ok) {
            QG.ui.feedbackMessage.showButton(
              checkUpdBtn,
              data.error || "Check failed",
              false,
            );
          } else if (data.update_available) {
            let updateMsg = "Update available: v" + data.latest_version;
            if (data.download_url && !data.can_auto_install) {
              updateMsg += data.frozen
                ? " (manual install on this platform)"
                : " (run the packaged desktop build to auto-install)";
            }
            QG.ui.feedbackMessage.showButton(checkUpdBtn, updateMsg, true);
          } else {
            QG.ui.feedbackMessage.showButton(
              checkUpdBtn,
              "You're on the latest version.",
              true,
            );
          }
        } catch (e) {
          QG.ui.feedbackMessage.showButton(
            checkUpdBtn,
            e.message || "Check failed",
            false,
          );
        } finally {
          if (
            !checkUpdBtn.classList.contains("settings-check-updates-btn--ok") &&
            !checkUpdBtn.classList.contains("settings-check-updates-btn--err")
          ) {
            checkUpdBtn.disabled = false;
            checkUpdBtn.textContent = originalText;
          }
        }
      });
    }

    document.getElementById("settings-purge-btn").addEventListener("click", async () => {
        if (
          !confirm(
            "Purge the download database? Future downloads won't be skipped.",
          )
        ) {
          return;
        }
        try {
          const res = await api.setupApi.purge();
          const data = await res.json();
          if (!data.ok) throw new Error(data.error || "Purge failed");
          QG.ui.feedbackMessage.show(feedback, "Database purged.", true);
        } catch (e) {
        QG.ui.feedbackMessage.show(feedback, e.message, false);
      }
    });

    if (
      settings.coverArtMutex &&
      typeof settings.coverArtMutex.init === "function"
    ) {
      settings.coverArtMutex.init("cfg");
    }
  }

  settings.actions = { init };
})();
