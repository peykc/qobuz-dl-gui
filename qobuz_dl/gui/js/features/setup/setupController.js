/**
 * Setup overlay, auth flows, and initial app shell routing (S1).
 */
(function () {
  "use strict";
  const QG = (window.QobuzGui = window.QobuzGui || {});
  QG.features = QG.features || {};
  const setup = (QG.features.setup = QG.features.setup || {});

  const api = QG.api;
  let _deps = {};

  function configure(deps) {
    _deps = { ..._deps, ...(deps || {}) };
  }

  function showSetup() {
    document.getElementById("setup-overlay").classList.remove("hidden");
    document.getElementById("app").classList.add("hidden");
  }

  async function showApp() {
    document.getElementById("setup-overlay").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    if (typeof _deps.startDownloadSse === "function") {
      _deps.startDownloadSse();
    }
    if (typeof _deps.ensureDownloadReady === "function") {
      try {
        await _deps.ensureDownloadReady();
      } catch (_) {}
    }
  }

  function loadSettingsForm() {
    if (typeof _deps.loadSettingsForm === "function") {
      return _deps.loadSettingsForm();
    }
    if (
      QG.features.settings &&
      QG.features.settings.settingsForm &&
      typeof QG.features.settings.settingsForm.loadIntoForm === "function"
    ) {
      return QG.features.settings.settingsForm.loadIntoForm();
    }
    return Promise.resolve();
  }

  function initSetup() {
    const oauthBtn = document.getElementById("oauth-btn");
    const oauthBtnText = document.getElementById("oauth-btn-text");
    const oauthSpinner = document.getElementById("oauth-spinner");
    const oauthErr = document.getElementById("setup-error-oauth");
    const oauthManualOpen = document.getElementById("oauth-manual-open");
    const oauthManualLink = document.getElementById("oauth-manual-link");
    const authToast = document.getElementById("auth-toast");
    let _oauthPolling = null;
    let _oauthAttemptId = "";
    let _oauthWaiting = false;

    function friendlyOauthError(message) {
      const text = String(message || "").trim();
      if (/free accounts are not eligible/i.test(text)) {
        return "Free accounts are not eligible, an active Qobuz subscription is required.";
      }
      return text || "OAuth login failed.";
    }

    function showAuthToast(message, ok) {
      if (!authToast) return;
      authToast.textContent = message;
      authToast.classList.toggle("ok", !!ok);
      authToast.classList.remove("hidden");
    }

    if (authToast) {
      authToast.addEventListener("click", () => {
        authToast.classList.add("hidden");
      });
    }

    function hideOauthManualLink() {
      if (oauthManualOpen) oauthManualOpen.classList.add("hidden");
      if (oauthManualLink) oauthManualLink.removeAttribute("href");
    }

    function showOauthManualLink(url) {
      if (!oauthManualOpen || !oauthManualLink || !url) {
        hideOauthManualLink();
        return;
      }
      oauthManualLink.href = url;
      oauthManualOpen.classList.remove("hidden");
    }

    function resetOauthButton() {
      _oauthWaiting = false;
      _oauthAttemptId = "";
      oauthBtn.disabled = false;
      oauthBtn.classList.remove("oauth-waiting");
      oauthBtnText.textContent = "Login with Qobuz";
      oauthSpinner.classList.add("hidden");
      hideOauthManualLink();
    }

    function setOauthWaiting() {
      _oauthWaiting = true;
      oauthBtn.disabled = false;
      oauthBtn.classList.add("oauth-waiting");
      oauthBtnText.textContent = "Waiting for browser login…";
      oauthSpinner.classList.remove("hidden");
    }

    async function cancelOauthAttempt() {
      const attemptId = _oauthAttemptId;
      if (_oauthPolling) {
        clearInterval(_oauthPolling);
        _oauthPolling = null;
      }
      if (
        attemptId &&
        api.setupApi &&
        typeof api.setupApi.oauthCancel === "function"
      ) {
        try {
          await api.setupApi.oauthCancel(attemptId);
        } catch (_) {}
      }
      resetOauthButton();
    }

    oauthBtn.addEventListener("mouseenter", () => {
      if (!_oauthWaiting) return;
      oauthBtnText.textContent = "✕ Cancel login";
    });

    oauthBtn.addEventListener("mouseleave", () => {
      if (!_oauthWaiting) return;
      oauthBtnText.textContent = "Waiting for browser login…";
    });

    oauthBtn.addEventListener("click", async () => {
      if (_oauthWaiting) {
        await cancelOauthAttempt();
        return;
      }
      oauthErr.classList.add("hidden");
      if (authToast) authToast.classList.add("hidden");
      oauthBtn.disabled = true;
      oauthBtn.classList.remove("oauth-waiting");
      oauthBtnText.textContent = "Opening browser…";
      oauthSpinner.classList.remove("hidden");
      if (_oauthPolling) {
        clearInterval(_oauthPolling);
        _oauthPolling = null;
      }

      try {
        const oauthFolder =
          document.getElementById("setup-folder-oauth")?.value.trim() ||
          "Qobuz Downloads";
        const oauthQuality =
          document.getElementById("setup-quality-oauth")?.value || "27";
        const res = await api.setupApi.oauthStart({
          default_folder: oauthFolder,
          default_quality: oauthQuality,
        });
        const data = await res.json();
        if (!data.ok) {
          showAuthToast(friendlyOauthError(data.error || "OAuth start failed."), false);
          resetOauthButton();
          return;
        }
        const attemptId = data.attempt_id || "";
        _oauthAttemptId = attemptId;
        const baselineGeneration = Number(data.baseline_auth_generation || 0);
        const startedAt = Date.now();
        setOauthWaiting();
        showOauthManualLink(data.url || "");
        _oauthPolling = setInterval(async () => {
          let s = null;
          if (
            attemptId &&
            api.setupApi &&
            typeof api.setupApi.oauthStatus === "function"
          ) {
            const statusRes = await api.setupApi.oauthStatus(attemptId);
            s = await statusRes.json().catch(() => null);
          }
          if (!s || !s.ok) {
            s = await QG.features.status.checkStatus();
          }
          if (s && s.state === "failed") {
            clearInterval(_oauthPolling);
            _oauthPolling = null;
            showAuthToast(friendlyOauthError(s.error), false);
            resetOauthButton();
            return;
          }
          if (s && s.state === "cancelled") {
            clearInterval(_oauthPolling);
            _oauthPolling = null;
            resetOauthButton();
            return;
          }
          if (
            s &&
            s.state === "success" &&
            Number(s.auth_generation || 0) > baselineGeneration
          ) {
            clearInterval(_oauthPolling);
            _oauthPolling = null;
            resetOauthButton();
            await showApp();
            await loadSettingsForm();
          } else if (Date.now() - startedAt > 125000) {
            clearInterval(_oauthPolling);
            _oauthPolling = null;
            showAuthToast(
              "OAuth login was not completed. Your previous login was kept.",
              false,
            );
            resetOauthButton();
          }
        }, 1500);
      } catch (e) {
        showAuthToast("Network error: " + e.message, false);
        resetOauthButton();
      }
    });

    const tokenBtn = document.getElementById("token-btn");
    const tokenBtnText = document.getElementById("token-btn-text");
    const tokenSpinner = document.getElementById("token-spinner");
    const tokenErr = document.getElementById("setup-error-token");

    tokenBtn.addEventListener("click", async () => {
      const user_id = document.getElementById("setup-user-id").value.trim();
      const user_auth_token = document
        .getElementById("setup-user-auth-token")
        .value.trim();
      const folder =
        document.getElementById("setup-folder-token").value.trim() ||
        "Qobuz Downloads";
      const quality = document.getElementById("setup-quality-token").value;

      tokenErr.classList.add("hidden");
      if (!user_id || !user_auth_token) {
        tokenErr.textContent = "Please enter both User ID and User Auth Token.";
        tokenErr.classList.remove("hidden");
        return;
      }

      tokenBtn.disabled = true;
      tokenBtnText.textContent = "Connecting…";
      tokenSpinner.classList.remove("hidden");

      try {
        const res = await api.setupApi.tokenLogin({
          user_id,
          user_auth_token,
          default_folder: folder,
          default_quality: quality,
        });
        const data = await res.json();
        if (data.ok) {
          await showApp();
          QG.features.status.updateStatus(true);
          await loadSettingsForm();
        } else {
          tokenErr.textContent = data.error || "Token login failed.";
          tokenErr.classList.remove("hidden");
        }
      } catch (e) {
        tokenErr.textContent = "Network error: " + e.message;
        tokenErr.classList.remove("hidden");
      } finally {
        tokenBtn.disabled = false;
        tokenBtnText.textContent = "Connect with Token";
        tokenSpinner.classList.add("hidden");
      }
    });

  }

  async function resolveInitialView() {
    const status = await QG.features.status.checkStatus();
    if (status && (status.ready || status.has_config)) {
      await showApp();
      if (!status.ready && status.has_config) {
        const dot = document.getElementById("status-dot");
        const label = document.getElementById("status-label");
        if (dot && label) {
          dot.className = "status-dot connecting";
          label.textContent = "Connecting…";
        }
        try {
          const connect =
            typeof _deps.connect === "function"
              ? _deps.connect
              : () => api.setupApi.connect();
          const res = await connect();
          const data = await res.json();
          QG.features.status.updateStatus(data.ok);
        } catch (_) {
          QG.features.status.updateStatus(false);
        }
      }
      await loadSettingsForm();
    } else {
      showSetup();
    }
  }

  Object.assign(setup, {
    configure,
    showSetup,
    showApp,
    initSetup,
    resolveInitialView,
  });
})();
