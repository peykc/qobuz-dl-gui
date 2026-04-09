/* ============================================================
   Qobuz-DL GUI — Frontend Logic
   ============================================================ */

(function () {
  "use strict";

  // ── SSE (shared log stream) ────────────────────────────────
  let _sse = null;

  function startSSE() {
    if (_sse) return;
    _sse = new EventSource("/api/stream");

    // Plain log lines
    _sse.onmessage = (e) => {
      if (!e.data || e.data.trim() === "") return;
      appendLog("log-output", e.data);
      appendLog("log-output-search", e.data);
    };

    // Structured per-URL status events
    _sse.addEventListener("status", (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (window._handleDlStatus) window._handleDlStatus(ev);
      } catch (_) {}
    });

    _sse.onerror = () => {
      _sse.close();
      _sse = null;
      setTimeout(startSSE, 3000);
    };
  }

  function appendLog(targetId, text) {
    const el = document.getElementById(targetId);
    if (!el) return;
    const line = document.createElement("span");
    line.className = classifyLogLine(text);
    line.textContent = text;
    el.appendChild(line);
    el.appendChild(document.createTextNode("\n"));
    el.scrollTop = el.scrollHeight;
  }

  function classifyLogLine(text) {
    const t = text.toLowerCase();
    if (t.includes("error") || t.includes("failed") || t.includes("invalid"))
      return "log-line log-error";
    if (t.includes("complete") || t.includes("success") || t.includes("logged"))
      return "log-line log-ok";
    if (t.includes("skip") || t.includes("already") || t.includes("demo"))
      return "log-line log-warn";
    if (
      t.includes("download") ||
      t.includes("search") ||
      t.includes("quality") ||
      t.includes("connect")
    )
      return "log-line log-info";
    return "log-line";
  }

  // ── Tab routing ───────────────────────────────────────────
  function initTabs() {
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tab = btn.dataset.tab;
        document
          .querySelectorAll(".nav-item")
          .forEach((b) => b.classList.remove("active"));
        document
          .querySelectorAll(".tab-panel")
          .forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        document.getElementById("tab-" + tab).classList.add("active");
      });
    });
  }

  // ── Status polling ────────────────────────────────────────
  function updateStatus(ready) {
    const dot = document.getElementById("status-dot");
    const label = document.getElementById("status-label");
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
      const res = await fetch("/api/status");
      const data = await res.json();
      updateStatus(data.ready);
      return data;
    } catch (e) {
      updateStatus(false);
      return null;
    }
  }

  // ── Setup overlay ─────────────────────────────────────────
  function showSetup() {
    document.getElementById("setup-overlay").classList.remove("hidden");
    document.getElementById("app").classList.add("hidden");
  }

  function showApp() {
    document.getElementById("setup-overlay").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
    startSSE();
  }

  // ── Browse folder ─────────────────────────────────────────
  function initBrowseButtons() {
    document.querySelectorAll(".btn-browse").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          const res = await fetch("/api/browse_folder", { method: "POST" });
          const data = await res.json();
          if (data.ok && data.path) {
            const targetId = btn.dataset.target;
            const input = document.getElementById(targetId);
            if (input) input.value = data.path;
          }
        } catch (e) {
          console.error("Browse error:", e);
        }
      });
    });
  }

  // ── Auth method tabs ──────────────────────────────────────
  function initAuthTabs() {
    document.querySelectorAll(".auth-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document
          .querySelectorAll(".auth-tab")
          .forEach((t) => t.classList.remove("active"));
        document
          .querySelectorAll(".auth-panel")
          .forEach((p) => p.classList.add("hidden"));
        tab.classList.add("active");
        document
          .getElementById("auth-panel-" + tab.dataset.auth)
          .classList.remove("hidden");
      });
    });
  }

  function initSetup() {
    // ── OAuth button ────────────────────────────────────────
    const oauthBtn = document.getElementById("oauth-btn");
    const oauthBtnText = document.getElementById("oauth-btn-text");
    const oauthSpinner = document.getElementById("oauth-spinner");
    const oauthErr = document.getElementById("setup-error-oauth");
    let _oauthPolling = null;

    oauthBtn.addEventListener("click", async () => {
      oauthErr.classList.add("hidden");
      oauthBtn.disabled = true;
      oauthBtnText.textContent = "Opening browser…";
      oauthSpinner.classList.remove("hidden");

      try {
        const res = await fetch("/api/oauth/start", { method: "POST" });
        const data = await res.json();
        if (!data.ok) {
          oauthErr.textContent = data.error || "OAuth start failed.";
          oauthErr.classList.remove("hidden");
          return;
        }
        oauthBtnText.textContent = "Waiting for browser login…";
        // Poll status until connected
        _oauthPolling = setInterval(async () => {
          const s = await checkStatus();
          if (s && s.ready) {
            clearInterval(_oauthPolling);
            oauthBtn.disabled = false;
            oauthBtnText.textContent = "Login with Qobuz";
            oauthSpinner.classList.add("hidden");
            showApp();
            await loadSettingsIntoForm();
          }
        }, 1500);
      } catch (e) {
        oauthErr.textContent = "Network error: " + e.message;
        oauthErr.classList.remove("hidden");
        oauthBtn.disabled = false;
        oauthBtnText.textContent = "Login with Qobuz";
        oauthSpinner.classList.add("hidden");
      }
    });

    // ── Token button ────────────────────────────────────────
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
        const res = await fetch("/api/token_login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            user_id,
            user_auth_token,
            default_folder: folder,
            default_quality: quality,
          }),
        });
        const data = await res.json();
        if (data.ok) {
          showApp();
          updateStatus(true);
          await loadSettingsIntoForm();
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

    // ── Email/Password button (legacy) ───────────────────────
    const btn = document.getElementById("setup-btn");
    const btnText = document.getElementById("setup-btn-text");
    const spinner = document.getElementById("setup-spinner");
    const errEl = document.getElementById("setup-error");

    btn.addEventListener("click", async () => {
      const email = document.getElementById("setup-email").value.trim();
      const password = document.getElementById("setup-password").value;
      const folder =
        document.getElementById("setup-folder").value.trim() ||
        "Qobuz Downloads";
      const quality = document.getElementById("setup-quality").value;

      errEl.classList.add("hidden");
      if (!email || !password) {
        errEl.textContent = "Please enter your email and password.";
        errEl.classList.remove("hidden");
        return;
      }

      btn.disabled = true;
      btnText.textContent = "Connecting…";
      spinner.classList.remove("hidden");

      try {
        const res = await fetch("/api/setup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email,
            password,
            default_folder: folder,
            default_quality: quality,
          }),
        });
        const data = await res.json();
        if (data.ok) {
          showApp();
          updateStatus(true);
          await loadSettingsIntoForm();
        } else {
          errEl.textContent = data.error || "Setup failed.";
          errEl.classList.remove("hidden");
        }
      } catch (e) {
        errEl.textContent = "Network error: " + e.message;
        errEl.classList.remove("hidden");
      } finally {
        btn.disabled = false;
        btnText.textContent = "Save & Connect";
        spinner.classList.add("hidden");
      }
    });
  }

  // ── URL Queue System ─────────────────────────────────────
  const _urlQueue = []; // [{url, resolved: {title, artist, cover, type, ...}}]
  let _textMode = false;

  function _syncHiddenTextarea() {
    document.getElementById("dl-urls").value = _urlQueue
      .map((q) => q.url)
      .join("\n");
    const empty = document.getElementById("dl-queue-empty");
    if (empty) empty.style.display = _urlQueue.length ? "none" : "";
    if (window._updateQueueBadge) window._updateQueueBadge();
  }

  function _addUrlToQueue(rawUrl) {
    const url = rawUrl.trim();
    if (!url) return;
    if (_urlQueue.some((q) => q.url === url)) return; // dupe

    _urlQueue.push({ url, resolved: null });
    _syncHiddenTextarea();

    // Add a loading card immediately
    const card = _createQueueCard(url);
    document.getElementById("dl-queue").appendChild(card);

    // Resolve metadata in background
    fetch("/api/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok && data.result) {
          const qi = _urlQueue.find((q) => q.url === url);
          if (qi) qi.resolved = data.result;
          _updateQueueCard(card, data.result);
        } else {
          _updateQueueCard(card, {
            type: "link",
            title: url,
            artist: "",
            cover: "",
          });
        }
      })
      .catch(() => {
        _updateQueueCard(card, {
          type: "link",
          title: url,
          artist: "",
          cover: "",
        });
      });
  }

  function _removeFromQueue(url, card) {
    const i = _urlQueue.findIndex((q) => q.url === url);
    if (i !== -1) _urlQueue.splice(i, 1);
    card.remove();
    _syncHiddenTextarea();
  }

  function _createQueueCard(url) {
    const card = document.createElement("a");
    card.className = "queue-card loading";
    card.href = url;
    card.target = "_blank";
    card.rel = "noopener";
    card.dataset.url = url;
    // Prevent navigation when clicking the remove button
    card.addEventListener("click", (e) => {
      if (e.target.closest(".queue-card-remove")) e.preventDefault();
    });

    const art = document.createElement("div");
    art.className = "queue-card-art";
    card.appendChild(art);

    const info = document.createElement("div");
    info.className = "queue-card-info";
    info.innerHTML = `
      <span class="queue-card-title">${_esc(url)}</span>
      <span class="queue-card-artist">Loading…</span>
    `;
    card.appendChild(info);

    const btn = document.createElement("button");
    btn.className = "queue-card-remove";
    btn.innerHTML = "×";
    btn.title = "Remove";
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      _removeFromQueue(url, card);
    });
    card.appendChild(btn);

    return card;
  }

  function _updateQueueCard(card, r) {
    card.classList.remove("loading");
    // Art
    const artEl = card.querySelector(".queue-card-art");
    if (r.cover) {
      const img = document.createElement("img");
      img.className = "queue-card-art";
      img.src = r.cover;
      img.alt = "";
      artEl.replaceWith(img);
    }
    // Info
    const info = card.querySelector(".queue-card-info");
    const badge = r.type
      ? `<span class="queue-card-badge badge-${r.type}">${r.type}</span>`
      : "";
    const metaParts = [];
    if (r.year) metaParts.push(r.year);
    if (r.quality) metaParts.push(r.quality);
    if (r.tracks) metaParts.push(r.tracks + " tracks");
    if (r.albums) metaParts.push(r.albums + " albums");

    info.innerHTML = `
      <span class="queue-card-title">${_esc(r.title || card.dataset.url)}</span>
      <span class="queue-card-artist">${_esc(r.artist || "")}</span>
      <span class="queue-card-meta">${badge} ${metaParts.join(" · ")}</span>
    `;
    if (window._updateQueueBadge) window._updateQueueBadge();
  }

  function _esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  // Rebuild cards from queue data (used when switching back from text mode)
  function _rebuildCards() {
    const queue = document.getElementById("dl-queue");
    queue.innerHTML = "";
    _urlQueue.forEach((qi) => {
      const card = _createQueueCard(qi.url);
      queue.appendChild(card);
      if (qi.resolved) {
        _updateQueueCard(card, qi.resolved);
      } else {
        _updateQueueCard(card, {
          type: "link",
          title: qi.url,
          artist: "",
          cover: "",
        });
      }
    });
  }

  // Sync textarea edits back into the queue (when switching from text → card mode)
  function _syncTextareaToQueue() {
    const lines = document
      .getElementById("dl-urls")
      .value.split(/[\n\r]+/)
      .map((l) => l.trim())
      .filter(Boolean);
    // Find removed URLs
    for (let i = _urlQueue.length - 1; i >= 0; i--) {
      if (!lines.includes(_urlQueue[i].url)) _urlQueue.splice(i, 1);
    }
    // Find added URLs
    lines.forEach((u) => {
      if (!_urlQueue.some((q) => q.url === u)) {
        _urlQueue.push({ url: u, resolved: null });
        // Resolve in background
        fetch("/api/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url: u }),
        })
          .then((r) => r.json())
          .then((data) => {
            const qi = _urlQueue.find((q) => q.url === u);
            if (qi && data.ok && data.result) qi.resolved = data.result;
          })
          .catch(() => {});
      }
    });
    _syncHiddenTextarea();
  }

  // Global drop handler for card-mode queue
  window._handleDrop = function (e) {
    const text =
      e.dataTransfer.getData("text/plain") ||
      e.dataTransfer.getData("text/uri-list") ||
      "";
    text.split(/[\n\r]+/).forEach((line) => {
      const u = line.trim();
      if (u && (u.startsWith("http") || u.startsWith("/"))) _addUrlToQueue(u);
    });
  };

  // Drop handler for text-mode textarea
  window._handleDropText = function (e) {
    const text =
      e.dataTransfer.getData("text/plain") ||
      e.dataTransfer.getData("text/uri-list") ||
      "";
    const ta = document.getElementById("dl-urls");
    const cur = ta.value.trim();
    const lines = text
      .split(/[\n\r]+/)
      .map((l) => l.trim())
      .filter(Boolean);
    ta.value = (cur ? cur + "\n" : "") + lines.join("\n");
  };

  function _setMode(cardMode) {
    const urlCard = document.getElementById("url-card");
    const btnCard = document.getElementById("btn-mode-card");
    const btnText = document.getElementById("btn-mode-text");
    if (cardMode) {
      _textMode = false;
      urlCard.classList.remove("text-mode");
      btnCard.classList.add("active");
      btnText.classList.remove("active");
    } else {
      _textMode = true;
      urlCard.classList.add("text-mode");
      btnCard.classList.remove("active");
      btnText.classList.add("active");
    }
  }

  function initUrlQueue() {
    const input = document.getElementById("dl-url-input");
    const addBtn = document.getElementById("dl-url-add");
    const btnCard = document.getElementById("btn-mode-card");
    const btnText = document.getElementById("btn-mode-text");

    function addFromInput() {
      const val = input.value.trim();
      if (!val) return;
      if (_textMode) {
        const ta = document.getElementById("dl-urls");
        const cur = ta.value.trim();
        const lines = val
          .split(/[\n\r]+/)
          .map((l) => l.trim())
          .filter(Boolean);
        ta.value = (cur ? cur + "\n" : "") + lines.join("\n");
      } else {
        val.split(/[\n\r]+/).forEach((u) => {
          if (u.trim()) _addUrlToQueue(u.trim());
        });
      }
      input.value = "";
      input.focus();
    }

    addBtn.addEventListener("click", addFromInput);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addFromInput();
      }
    });

    input.addEventListener("paste", (e) => {
      setTimeout(() => {
        const val = input.value.trim();
        if (val.includes("\n") || val.includes("\r")) {
          if (_textMode) {
            const ta = document.getElementById("dl-urls");
            const cur = ta.value.trim();
            const lines = val
              .split(/[\n\r]+/)
              .map((l) => l.trim())
              .filter(Boolean);
            ta.value = (cur ? cur + "\n" : "") + lines.join("\n");
          } else {
            val.split(/[\n\r]+/).forEach((u) => {
              if (u.trim()) _addUrlToQueue(u.trim());
            });
          }
          input.value = "";
        }
      }, 0);
    });

    btnCard.addEventListener("click", () => {
      if (_textMode) {
        _syncTextareaToQueue();
        _setMode(true);
        _rebuildCards();
      }
    });

    btnText.addEventListener("click", () => {
      if (!_textMode) {
        _setMode(false);
        document.getElementById("dl-urls").value = _urlQueue
          .map((q) => q.url)
          .join("\n");
      }
    });

    // Keep badge in sync when user edits URLs in text mode
    document.getElementById("dl-urls").addEventListener("input", () => {
      if (window._updateQueueBadge) window._updateQueueBadge();
    });
  }

  // ── Collapse toggles ──────────────────────────────────────
  function initCollapses() {
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
  }

  // ── Reset buttons ─────────────────────────────────────────
  function initResetButtons() {
    document.querySelectorAll(".btn-reset").forEach((btn) => {
      btn.addEventListener("click", () => {
        const targetId = btn.dataset.reset;
        const def = btn.dataset.default;
        const input = document.getElementById(targetId);
        if (input) input.value = def;
      });
    });
  }

  // ── Cover art mutual exclusivity ──────────────────────────
  // "Skip Cover Art" is incompatible with "Write Art to Tracks" and
  // "Full-Res Cover" — wire them up for whichever prefix is passed ('dl'/'cfg').
  function initCoverArtMutex(prefix) {
    const embedArt = document.getElementById(`${prefix}-embed-art`);
    const ogCover = document.getElementById(`${prefix}-og-cover`);
    const noCover = document.getElementById(`${prefix}-no-cover`);
    if (!embedArt || !ogCover || !noCover) return;

    // Enabling "Skip Cover Art" turns the other two off
    noCover.addEventListener("change", () => {
      if (noCover.checked) {
        embedArt.checked = false;
        ogCover.checked = false;
      }
    });

    // Enabling either art option turns off "Skip Cover Art"
    embedArt.addEventListener("change", () => {
      if (embedArt.checked) noCover.checked = false;
    });
    ogCover.addEventListener("change", () => {
      if (ogCover.checked) noCover.checked = false;
    });
  }

  // ── Download tab ──────────────────────────────────────────
  function initDownload() {
    initUrlQueue();
    initCoverArtMutex("dl");

    // ── Autosave download options to config on every change ──
    let _autosaveTimer = null;

    function _autosave() {
      const payload = {
        default_quality: document.getElementById("dl-quality").value || "27",
        folder_format: document.getElementById("dl-folder-format").value.trim(),
        track_format: document.getElementById("dl-track-format").value.trim(),
        embed_art: String(document.getElementById("dl-embed-art").checked),
        og_cover: String(document.getElementById("dl-og-cover").checked),
        no_cover: String(document.getElementById("dl-no-cover").checked),
        albums_only: String(document.getElementById("dl-albums-only").checked),
        no_m3u: String(document.getElementById("dl-no-m3u").checked),
        no_fallback: String(document.getElementById("dl-no-fallback").checked),
        no_database: String(document.getElementById("dl-no-db").checked),
        smart_discography: String(
          document.getElementById("dl-smart-discography").checked,
        ),
      };
      const dir = document.getElementById("dl-directory").value.trim();
      if (dir) payload.default_folder = dir;
      fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch(() => {});
    }

    function _scheduleAutosave() {
      if (_autosaveTimer) clearTimeout(_autosaveTimer);
      _autosaveTimer = setTimeout(_autosave, 600);
    }

    // Immediate save for selects and checkboxes
    [
      "dl-quality",
      "dl-embed-art",
      "dl-og-cover",
      "dl-no-cover",
      "dl-albums-only",
      "dl-no-m3u",
      "dl-no-fallback",
      "dl-no-db",
      "dl-smart-discography",
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", _autosave);
    });

    // Debounced save for text inputs
    ["dl-directory", "dl-folder-format", "dl-track-format"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", _scheduleAutosave);
    });

    window._updateQueueBadge = function () {
      const badge = document.getElementById("dl-btn-badge");
      if (!badge) return;
      let total = 0;
      let hasUnknown = false;
      if (_textMode) {
        const val = document.getElementById("dl-urls").value || "";
        total = val.split(/[\n\r]+/).filter((l) => l.trim()).length;
      } else {
        _urlQueue.forEach((qi) => {
          if (!qi.resolved) {
            total += 1;
            return;
          }
          const r = qi.resolved;
          if (r.type === "track") {
            total += 1;
            return;
          }
          if (r.type === "artist") {
            hasUnknown = true;
            return;
          }
          if (r.tracks) {
            total += r.tracks;
            return;
          }
          total += 1;
        });
      }
      if (total === 0 && !hasUnknown) {
        badge.classList.add("hidden");
        badge.textContent = "";
      } else {
        badge.classList.remove("hidden");
        badge.textContent = hasUnknown ? `${total}+` : String(total);
      }
    };

    // URL-level counters (for card state management)
    let _dlTotal = 0;
    let _dlDone = 0;

    // Track-level counters (drive the progress bar)
    let _dlTrackTotal = 0;
    let _dlTrackDone = 0;

    function _findCardByUrl(url) {
      const cards = document.querySelectorAll("#dl-queue .queue-card");
      for (const c of cards) if (c.dataset.url === url) return c;
      return null;
    }

    // Sum up expected track count from resolved queue metadata
    function _calcTrackTotal() {
      let total = 0;
      _urlQueue.forEach((qi) => {
        if (!qi.resolved) {
          total += 1;
          return;
        }
        const r = qi.resolved;
        if (r.type === "track") {
          total += 1;
          return;
        }
        if (r.tracks) {
          total += r.tracks;
          return;
        }
        total += 1; // artist / label / unknown — will grow dynamically
      });
      return Math.max(total, 1);
    }

    function _updateProgress() {
      const fill = document.getElementById("dl-progress-fill");
      const label = document.getElementById("dl-progress-label");
      const cap = Math.max(_dlTrackTotal, _dlTrackDone); // never go backward

      if (fill) {
        const pct = cap > 0 ? Math.round((_dlTrackDone / cap) * 100) : 0;
        fill.style.width = pct + "%";
      }
      if (label) {
        label.textContent = `${_dlTrackDone} / ${_dlTrackTotal} tracks`;
        label.title = "";
      }
    }

    function _setDownloadingState(isDownloading) {
      const dlBtn = document.getElementById("dl-btn");
      const progressWrap = document.getElementById("dl-progress-wrap");
      window.isDownloading = isDownloading;

      if (isDownloading) {
        dlBtn.dataset.state = "downloading";
        dlBtn.innerHTML = `
          <svg id="dl-btn-icon" width="15" height="15" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
          <span id="dl-btn-text">Cancel</span>`;
        // Hide badge during active download
        const _badge = document.getElementById("dl-btn-badge");
        if (_badge) _badge.classList.add("hidden");
        dlBtn.disabled = false;
        progressWrap.classList.remove("hidden");
        _updateProgress();
        // Hide remove buttons while downloading
        document
          .querySelectorAll("#dl-queue .queue-card-remove")
          .forEach((b) => (b.style.display = "none"));
      } else {
        dlBtn.dataset.state = "idle";
        dlBtn.innerHTML = `
          <svg id="dl-btn-icon" width="15" height="15" viewBox="0 0 24 24" fill="none"
               stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
          <span id="dl-btn-text">Start Download</span>
          <span id="dl-btn-badge" class="dl-btn-badge hidden"></span>`;
        window._updateQueueBadge();
        dlBtn.disabled = false;
        // Re-enable remove buttons on leftover (error) cards
        document
          .querySelectorAll("#dl-queue .queue-card-remove")
          .forEach((b) => (b.style.display = ""));
        setTimeout(() => progressWrap.classList.add("hidden"), 2000);
      }
    }

    // Called by SSE 'status' events
    window._handleDlStatus = function (ev) {
      if (ev.type === "url_start") {
        const card = _findCardByUrl(ev.url);
        if (card) {
          card.classList.remove("dl-pending");
          card.classList.add("dl-active");
        }
      } else if (ev.type === "track_start") {
        // Advance track-level progress bar
        _dlTrackDone++;
        // If we somehow exceed the estimated total (e.g. artist URL with many
        // albums), grow the total so the bar never stalls at 100% prematurely.
        if (_dlTrackDone > _dlTrackTotal) _dlTrackTotal = _dlTrackDone + 1;
        _updateProgress();
      } else if (ev.type === "url_done") {
        _dlDone++;
        // Sync track total upward if real count exceeded estimate
        if (_dlTrackDone > _dlTrackTotal) _dlTrackTotal = _dlTrackDone;
        _updateProgress();
        const card = _findCardByUrl(ev.url);
        if (card) {
          card.classList.remove("dl-active", "dl-pending");
          card.classList.add("dl-done");
          setTimeout(() => _removeFromQueue(ev.url, card), 1400);
        }
      } else if (ev.type === "url_error") {
        _dlDone++;
        _updateProgress();
        const card = _findCardByUrl(ev.url);
        if (card) {
          card.classList.remove("dl-active", "dl-pending");
          card.classList.add("dl-error");
          // Inject error badge into the card's info block
          const info = card.querySelector(".queue-card-info");
          if (info && !info.querySelector(".dl-error-badge")) {
            const badge = document.createElement("span");
            badge.className = "dl-error-badge";
            badge.textContent = "⚠ Failed";
            info.appendChild(badge);
          }
        }
      } else if (ev.type === "dl_complete") {
        // Snap progress to 100% and show final count
        _dlTrackTotal = Math.max(_dlTrackTotal, _dlTrackDone);
        const fill = document.getElementById("dl-progress-fill");
        if (fill) fill.style.width = ev.cancelled ? fill.style.width : "100%";
        const label = document.getElementById("dl-progress-label");
        if (label) {
          label.textContent = `${_dlTrackDone} track${_dlTrackDone !== 1 ? "s" : ""}`;
          label.title = "";
        }
        // Reset any cards still mid-flight (cancelled before they finished)
        if (ev.cancelled) {
          document
            .querySelectorAll(
              "#dl-queue .queue-card.dl-active, #dl-queue .queue-card.dl-pending",
            )
            .forEach((c) => c.classList.remove("dl-active", "dl-pending"));
          appendLog("log-output", "[warn] Download cancelled by user.");
        }
        // Clear the cancelling-state inline styles before restoring button
        const dlBtn = document.getElementById("dl-btn");
        dlBtn.style.opacity = "";
        dlBtn.style.cursor = "";
        dlBtn.style.pointerEvents = "";
        _setDownloadingState(false);
      }
    };

    document.getElementById("dl-btn").addEventListener("click", async () => {
      const dlBtn = document.getElementById("dl-btn");

      // Cancel if already running
      if (dlBtn.dataset.state === "downloading") {
        dlBtn.dataset.state = "cancelling";
        const span = dlBtn.querySelector("span");
        if (span) span.textContent = "Cancelling…";
        // Keep button enabled but re-style it so it looks responsive, not frozen
        dlBtn.disabled = false;
        dlBtn.style.opacity = "0.6";
        dlBtn.style.cursor = "default";
        dlBtn.style.pointerEvents = "none";
        await fetch("/api/cancel", { method: "POST" }).catch(() => {});
        return;
      }
      // Ignore clicks while waiting for cancel to propagate
      if (dlBtn.dataset.state === "cancelling") return;

      // Collect URLs
      let urls;
      if (_textMode) {
        urls = document.getElementById("dl-urls").value.trim();
      } else {
        urls = _urlQueue.map((q) => q.url).join("\n");
      }
      if (!urls) {
        appendLog("log-output", "[error] No URLs in queue. Add some first.");
        return;
      }

      const payload = {
        urls,
        quality: document.getElementById("dl-quality").value || null,
        directory: document.getElementById("dl-directory").value.trim() || null,
        embed_art: document.getElementById("dl-embed-art").checked,
        og_cover: document.getElementById("dl-og-cover").checked,
        no_cover: document.getElementById("dl-no-cover").checked,
        albums_only: document.getElementById("dl-albums-only").checked,
        no_m3u: document.getElementById("dl-no-m3u").checked,
        no_fallback: document.getElementById("dl-no-fallback").checked,
        no_db: document.getElementById("dl-no-db").checked,
        smart_discography: document.getElementById("dl-smart-discography")
          .checked,
        folder_format:
          document.getElementById("dl-folder-format").value.trim() || null,
        track_format:
          document.getElementById("dl-track-format").value.trim() || null,
      };

      try {
        const res = await fetch("/api/download", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!data.ok) {
          appendLog("log-output", "[error] " + data.error);
        } else {
          appendLog(
            "log-output",
            `[info] Queued ${data.queued} URL(s) for download…`,
          );
          // Mark all visible queue cards as pending (keep them in the list)
          _dlTotal = data.queued;
          _dlDone = 0;
          _dlTrackTotal = _textMode ? data.queued : _calcTrackTotal();
          _dlTrackDone = 0;
          document.querySelectorAll("#dl-queue .queue-card").forEach((c) => {
            c.classList.add("dl-pending");
          });
          _setDownloadingState(true);
        }
      } catch (e) {
        appendLog("log-output", "[error] Network error: " + e.message);
      }
    });

    document.getElementById("dl-clear-log").addEventListener("click", () => {
      document.getElementById("log-output").innerHTML = "";
    });
  }

  // ── Search tab ────────────────────────────────────────────
  let _searchResults = [];

  function initSearch() {
    const limitSlider = document.getElementById("search-limit");
    const limitVal = document.getElementById("search-limit-val");
    limitSlider.addEventListener("input", () => {
      limitVal.textContent = limitSlider.value;
    });

    document.getElementById("search-btn").addEventListener("click", doSearch);
    document.getElementById("search-query").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch();
    });

    document.getElementById("lucky-btn").addEventListener("click", doLucky);
    document
      .getElementById("download-selected-btn")
      .addEventListener("click", downloadSelected);
    document
      .getElementById("search-clear-log")
      .addEventListener("click", () => {
        document.getElementById("log-output-search").innerHTML = "";
      });
  }

  async function doSearch() {
    const query = document.getElementById("search-query").value.trim();
    if (query.length < 3) {
      appendLog(
        "log-output-search",
        "[error] Query must be at least 3 characters.",
      );
      return;
    }
    const type = document.getElementById("search-type").value;
    const limit = document.getElementById("search-limit").value;

    const btn = document.getElementById("search-btn");
    btn.disabled = true;
    btn.textContent = "Searching…";

    document.getElementById("search-results-container").classList.add("hidden");
    document.getElementById("search-empty").classList.add("hidden");

    try {
      const res = await fetch(
        `/api/search?q=${encodeURIComponent(query)}&type=${type}&limit=${limit}`,
      );
      const data = await res.json();

      if (!data.ok) {
        appendLog("log-output-search", "[error] " + data.error);
        return;
      }

      _searchResults = data.results || [];
      renderResults(_searchResults, query);
    } catch (e) {
      appendLog("log-output-search", "[error] " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Search";
    }
  }

  function renderResults(results, query) {
    const container = document.getElementById("search-results-container");
    const empty = document.getElementById("search-empty");
    const list = document.getElementById("search-results");
    const countEl = document.getElementById("results-count");

    list.innerHTML = "";
    if (!results.length) {
      container.classList.add("hidden");
      empty.classList.remove("hidden");
      return;
    }

    empty.classList.add("hidden");
    container.classList.remove("hidden");
    countEl.textContent = `${results.length} result${results.length !== 1 ? "s" : ""} for "${query}"`;

    results.forEach((r, i) => {
      const item = document.createElement("div");
      item.className = "result-item";
      item.dataset.index = i;

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = `result-cb-${i}`;

      const text = document.createElement("label");
      text.className = "result-text";
      text.htmlFor = `result-cb-${i}`;
      text.textContent = r.text;

      item.appendChild(cb);
      item.appendChild(text);

      // Quality badge from text
      if (r.text) {
        const badge = document.createElement("span");
        badge.className = "result-badge";
        if (r.text.includes("HI-RES")) {
          badge.className += " badge-hires";
          badge.textContent = "HI-RES";
        } else if (r.text.includes("LOSSLESS")) {
          badge.className += " badge-lossless";
          badge.textContent = "LOSSLESS";
        } else {
          badge.className += " badge-mp3";
          badge.textContent = "MP3";
        }
        item.appendChild(badge);
      }

      item.addEventListener("click", (e) => {
        if (e.target === cb) return; // handled by checkbox itself
        cb.checked = !cb.checked;
        item.classList.toggle("selected", cb.checked);
      });
      cb.addEventListener("change", () => {
        item.classList.toggle("selected", cb.checked);
      });

      list.appendChild(item);
    });
  }

  function downloadSelected() {
    const urls = [];
    document
      .querySelectorAll(
        "#search-results .result-item input[type='checkbox']:checked",
      )
      .forEach((cb) => {
        const idx = parseInt(cb.closest(".result-item").dataset.index, 10);
        if (_searchResults[idx]?.url) urls.push(_searchResults[idx].url);
      });

    if (!urls.length) {
      appendLog("log-output-search", "[warn] No items selected.");
      return;
    }

    fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls: urls.join("\n") }),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok) {
          appendLog(
            "log-output-search",
            `[info] Queued ${data.queued} item(s) for download…`,
          );
        } else {
          appendLog("log-output-search", "[error] " + data.error);
        }
      })
      .catch((e) => appendLog("log-output-search", "[error] " + e.message));
  }

  async function doLucky() {
    const query = document.getElementById("search-query").value.trim();
    if (query.length < 3) {
      appendLog(
        "log-output-search",
        "[error] Query must be at least 3 characters.",
      );
      return;
    }
    const type = document.getElementById("search-type").value;
    const number =
      parseInt(document.getElementById("lucky-number").value, 10) || 1;

    const btn = document.getElementById("lucky-btn");
    btn.disabled = true;

    try {
      const res = await fetch("/api/lucky", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, type, number }),
      });
      const data = await res.json();
      if (!data.ok) {
        appendLog("log-output-search", "[error] " + data.error);
      } else {
        appendLog(
          "log-output-search",
          `[info] Lucky download started for "${query}" (${type}, top ${number})…`,
        );
      }
    } catch (e) {
      appendLog("log-output-search", "[error] " + e.message);
    } finally {
      btn.disabled = false;
    }
  }

  // ── Settings tab ──────────────────────────────────────────
  async function loadSettingsIntoForm() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();
      const cfg = data.config || {};

      setValue("cfg-email", cfg.email || "");
      setValue("cfg-folder", cfg.default_folder || "Qobuz Downloads");
      setValue("cfg-quality", cfg.default_quality || "6");
      setValue(
        "cfg-folder-format",
        cfg.folder_format ||
          "{artist} - {album} ({year}) [{bit_depth}B-{sampling_rate}kHz]",
      );
      setValue(
        "cfg-track-format",
        cfg.track_format || "{tracknumber}. {tracktitle}",
      );
      setCheck("cfg-embed-art", cfg.embed_art === "true");
      setCheck("cfg-og-cover", cfg.og_cover === "true");
      setCheck("cfg-no-cover", cfg.no_cover === "true");
      setCheck("cfg-albums-only", cfg.albums_only === "true");
      setCheck("cfg-no-m3u", cfg.no_m3u === "true");
      setCheck("cfg-no-fallback", cfg.no_fallback === "true");
      setCheck("cfg-no-database", cfg.no_database === "true");
      setCheck("cfg-smart-discography", cfg.smart_discography === "true");

      // Also mirror these directly to the Download Options tab so they match the saved defaults
      setValue("dl-directory", cfg.default_folder || "Qobuz Downloads");
      setValue("dl-quality", cfg.default_quality || ""); // Use default
      setValue("dl-folder-format", cfg.folder_format || "");
      setValue("dl-track-format", cfg.track_format || "");
      setCheck("dl-embed-art", cfg.embed_art === "true");
      setCheck("dl-og-cover", cfg.og_cover === "true");
      setCheck("dl-no-cover", cfg.no_cover === "true");
      setCheck("dl-albums-only", cfg.albums_only === "true");
      setCheck("dl-no-m3u", cfg.no_m3u === "true");
      setCheck("dl-no-fallback", cfg.no_fallback === "true");
      setCheck("dl-no-db", cfg.no_database === "true");
      setCheck("dl-smart-discography", cfg.smart_discography === "true");
    } catch (e) {
      console.error("Failed to load settings", e);
    }
  }

  function setValue(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  }
  function setCheck(id, val) {
    const el = document.getElementById(id);
    if (el) el.checked = val;
  }

  function initSettings() {
    // ── Gear button / popover open-close ─────────────────────
    const gearBtn = document.getElementById("settings-gear-btn");
    const popover = document.getElementById("settings-popover");
    const backdrop = document.getElementById("settings-backdrop");
    const closeBtn = document.getElementById("settings-popover-close");
    const feedback = document.getElementById("settings-popover-feedback");

    function openPopover() {
      popover.classList.remove("hidden");
      backdrop.classList.remove("hidden");
      gearBtn.classList.add("active");
    }
    function closePopover() {
      popover.classList.add("hidden");
      backdrop.classList.add("hidden");
      gearBtn.classList.remove("active");
      feedback.className = "feedback-msg hidden";
    }

    gearBtn.addEventListener("click", () => {
      popover.classList.contains("hidden") ? openPopover() : closePopover();
    });
    backdrop.addEventListener("click", closePopover);
    closeBtn.addEventListener("click", closePopover);

    // ── Re-auth (OAuth) ───────────────────────────────────────
    const reauthBtn = document.getElementById("settings-reauth-btn");
    const reauthText = document.getElementById("settings-reauth-text");
    const reauthSpinner = document.getElementById("settings-reauth-spinner");
    let _reauthPolling = null;

    reauthBtn.addEventListener("click", async () => {
      reauthBtn.disabled = true;
      reauthText.textContent = "Opening browser…";
      reauthSpinner.classList.remove("hidden");

      try {
        const res = await fetch("/api/oauth/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        const data = await res.json();
        if (!data.ok) throw new Error(data.error || "OAuth start failed");

        reauthText.textContent = "Waiting for login…";
        if (_reauthPolling) clearInterval(_reauthPolling);
        _reauthPolling = setInterval(async () => {
          const s = await checkStatus();
          if (s && s.ready) {
            clearInterval(_reauthPolling);
            _reauthPolling = null;
            reauthText.textContent = "Re-login with Qobuz";
            reauthSpinner.classList.add("hidden");
            reauthBtn.disabled = false;
            updateStatus(true);
            await loadSettingsIntoForm();
            showFeedback(feedback, "Reconnected successfully.", true);
          }
        }, 2000);
      } catch (e) {
        showFeedback(feedback, e.message, false);
        reauthText.textContent = "Re-login with Qobuz";
        reauthSpinner.classList.add("hidden");
        reauthBtn.disabled = false;
      }
    });

    // ── Purge database ────────────────────────────────────────
    document
      .getElementById("settings-purge-btn")
      .addEventListener("click", async () => {
        if (
          !confirm(
            "Purge the download database? Future downloads won't be skipped.",
          )
        )
          return;
        try {
          const res = await fetch("/api/purge", { method: "POST" });
          const data = await res.json();
          if (!data.ok) throw new Error(data.error || "Purge failed");
          showFeedback(feedback, "Database purged.", true);
        } catch (e) {
          showFeedback(feedback, e.message, false);
        }
      });
  }

  function showFeedback(el, msg, ok) {
    el.textContent = msg;
    el.className = "feedback-msg " + (ok ? "ok" : "err");
    setTimeout(() => {
      el.className = "feedback-msg hidden";
    }, 3500);
  }

  // ── Init ─────────────────────────────────────────────────
  async function init() {
    initTabs();
    initCollapses();
    initResetButtons();
    initAuthTabs();
    initSetup();
    initBrowseButtons();
    initDownload();
    initSearch();
    initSettings();

    const status = await checkStatus();
    if (status && (status.ready || status.has_config)) {
      showApp();
      if (!status.ready && status.has_config) {
        // Config exists but client not init yet — auto-connect
        const dot = document.getElementById("status-dot");
        const label = document.getElementById("status-label");
        dot.className = "status-dot connecting";
        label.textContent = "Connecting…";
        try {
          const res = await fetch("/api/connect", { method: "POST" });
          const data = await res.json();
          updateStatus(data.ok);
        } catch (e) {
          updateStatus(false);
        }
      }
      await loadSettingsIntoForm();
    } else {
      showSetup();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
