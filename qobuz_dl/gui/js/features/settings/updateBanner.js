(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g && g.api;
  const features = (g.features = g.features || {});
  const mod = (features.updateBanner = features.updateBanner || {});

  let _updateInfo = null;

  function initUpdateBanner() {
    const banner = document.getElementById("update-banner");
    const installBtn = document.getElementById("update-banner-install");
    const dismissBtn = document.getElementById("update-banner-dismiss");
    if (!banner || !installBtn || !dismissBtn) return;

    dismissBtn.addEventListener("click", () => {
      if (_updateInfo && _updateInfo.latest_version) {
        try {
          sessionStorage.setItem(
            "qobuz-dl-update-dismiss",
            String(_updateInfo.latest_version),
          );
        } catch (e) {
          /* ignore */
        }
      }
      banner.classList.add("hidden");
    });

    installBtn.addEventListener("click", async () => {
      if (!_updateInfo || !_updateInfo.download_url) return;
      installBtn.disabled = true;
      const prev = installBtn.textContent;
      installBtn.textContent = "Downloading…";
      try {
        const res = await api.updateApi.install({
          download_url: _updateInfo.download_url,
        });
        const raw = await res.text();
        let data = {};
        try {
          data = raw ? JSON.parse(raw) : {};
        } catch {
          throw new Error(
            res.ok
              ? "Invalid response from server, try again or install from GitHub Releases."
              : `Install failed (HTTP ${res.status}).`,
          );
        }
        if (!data.ok) throw new Error(data.error || "Install failed");
        installBtn.textContent = "Restarting…";
      } catch (e) {
        alert(e.message);
        installBtn.disabled = false;
        installBtn.textContent = prev;
      }
    });
  }

  async function fetchUpdateCheck(force) {
    const q = force ? "?force=1" : "";
    const res = await api.updateApi.check(q);
    return await res.json();
  }

  function updateReleaseNotesUrl(data) {
    const rawTag = String(
      (data && data.tag_name) || (data && data.latest_version) || "",
    ).trim();
    if (!rawTag) return "";
    const tag = /^v/i.test(rawTag) ? rawTag : "v" + rawTag;
    return `https://github.com/peykc/qobuz-dl-gui/releases/tag/${encodeURIComponent(tag)}`;
  }

  function showUpdateBannerIfNeeded(data) {
    const banner = document.getElementById("update-banner");
    const textEl = document.getElementById("update-banner-text");
    const installBtn = document.getElementById("update-banner-install");
    const linkEl = document.getElementById("update-banner-link");
    if (!banner || !textEl || !installBtn || !linkEl) return;
    _updateInfo = data;
    if (!data || !data.update_available) {
      banner.classList.add("hidden");
      return;
    }
    if (!data.test_mode) {
      try {
        const dismissed = sessionStorage.getItem("qobuz-dl-update-dismiss");
        if (dismissed && dismissed === String(data.latest_version)) {
          banner.classList.add("hidden");
          return;
        }
      } catch (e) {
        /* ignore */
      }
    }
    let msg =
      "Version " +
      data.latest_version +
      " is available (you have " +
      data.current_version +
      ").";
    if (!data.download_url) {
      msg += " Download the new build from the release page.";
    } else if (!data.can_auto_install) {
      msg += data.frozen
        ? " Automatic install is not available for this platform yet."
        : " Automatic install only works in the packaged desktop build.";
    }
    textEl.textContent = msg;
    const releaseNotesUrl = updateReleaseNotesUrl(data);
    if (releaseNotesUrl) {
      linkEl.href = releaseNotesUrl;
      linkEl.classList.remove("hidden");
    } else {
      linkEl.classList.add("hidden");
    }
    if (data.can_auto_install && data.download_url) {
      installBtn.classList.remove("hidden");
    } else {
      installBtn.classList.add("hidden");
    }
    banner.classList.remove("hidden");
  }

  async function refreshUpdateCheck(force) {
    try {
      const data = await fetchUpdateCheck(force);
      showUpdateBannerIfNeeded(data);
      return data;
    } catch (e) {
      return null;
    }
  }

  mod.init = initUpdateBanner;
  mod.refreshUpdateCheck = refreshUpdateCheck;
  mod.getUpdateInfo = function getUpdateInfo() {
    return _updateInfo;
  };
})();
