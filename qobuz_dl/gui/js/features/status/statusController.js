/**
 * Connection status dot + /api/status polling (S1).
 */
(function () {
  "use strict";
  const QG = (window.QobuzGui = window.QobuzGui || {});
  QG.features = QG.features || {};

  function setAppVersionLabel(version) {
    const el = document.getElementById("settings-app-version");
    if (!el) return;
    const v = String(version || "").trim();
    el.textContent = v ? `Version ${v.replace(/^v/i, "")}` : "Version unknown";
  }

  function updateStatus(ready) {
    const dot = document.getElementById("status-dot");
    const label = document.getElementById("status-label");
    if (!dot || !label) return;
    if (ready) {
      dot.className = "status-dot connected";
      label.textContent = "Connected";
    } else {
      dot.className = "status-dot disconnected";
      label.textContent = "Disconnected";
    }
  }

  async function checkStatus() {
    try {
      const api = QG.api;

      let data;
      if (api && api.statusApi && typeof api.statusApi.fetchRaw === "function") {
        const raw = await api.statusApi.fetchRaw();
        data =
          raw && typeof raw.json === "function"
            ? await raw.json()
            : raw && raw.data
              ? raw.data
              : raw;
      } else if (api && typeof api.getJson === "function") {
        const res = await api.getJson("/api/status");
        data = res.data;
      } else {
        const res = await fetch("/api/status");
        data = await res.json();
      }

      if (data && data.app_version) setAppVersionLabel(data.app_version);
      updateStatus(data.ready);
      return data;
    } catch (_) {
      updateStatus(false);
      return null;
    }
  }

  QG.features.status = {
    updateStatus,
    checkStatus,
    setAppVersionLabel,
  };
})();
