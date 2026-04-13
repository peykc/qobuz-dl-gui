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
          data.result.resolving_discography = (data.result.type === "artist");
          _updateQueueCard(card, data.result);
          
          if (data.result.type === "artist") {
             fetch("/api/check_discography", {
               method: "POST",
               headers: { "Content-Type": "application/json" },
               body: JSON.stringify({ url })
             })
             .then(r => r.json())
             .then(cd => {
                if (cd.ok && cd.result) {
                  const res = cd.result;
                  data.result.resolving_discography = false;
                  
                  data.result.diff_sd = res.diff_sd;
                  data.result.diff_ao = res.diff_ao;
                  data.result.diff_both = res.diff_both;
                  
                  data.result.raw_tracks = res.raw_tracks;
                  data.result.sd_filtered_tracks = res.sd_filtered_tracks;
                  data.result.ao_filtered_tracks = res.ao_filtered_tracks;
                  data.result.both_filtered_tracks = res.both_filtered_tracks;
                  _updateQueueCard(card, data.result);
                }
             })
             .catch(() => {
                data.result.resolving_discography = false;
                _updateQueueCard(card, data.result);
             });
          }
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

    // === Type badge ===
    const typeBadge = r.type
      ? `<span class="queue-card-badge badge-${r.type}">${r.type}</span>`
      : "";

    // === Explicit icon ===
    const explicitIcon = r.explicit
      ? `<span class="queue-card-explicit" title="Explicit"><svg viewBox="0 0 24 24" class="queue-explicit-icon"><path fill="currentColor" d="M10.603 15.626v-2.798h3.632a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.241h-3.632V8.352h3.632a.8.8 0 0 0 .598-.24q.24-.242.24-.599a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.24h-4.47a.8.8 0 0 0-.598.24.81.81 0 0 0-.24.598v8.952q0 .357.24.598.241.24.598.241h4.47a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.81.81 0 0 0-.598-.241zM4.52 21.5c-.575-.052-.98-.284-1.383-.651-.39-.392-.55-.844-.637-1.372V4.493c.135-.607.27-.961.661-1.353.392-.391.762-.548 1.343-.64H19.47c.541.066.952.254 1.362.62.413.37.546.796.668 1.38v14.977c-.074.467-.237.976-.629 1.367-.39.392-.82.595-1.391.656z"></path></svg></span>`
      : "";

    // === Meta parts ===
    const metaParts = [];

    if (r.bit_depth && r.sample_rate) {
      metaParts.push(`${r.bit_depth}bit / ${r.sample_rate}kHz`);
    } else if (r.quality) {
      metaParts.push(r.quality);
    }

    if (r.tracks && r.type !== "artist") {
      metaParts.push(`${r.tracks} track${r.tracks !== 1 ? "s" : ""}`);
    }

    if (r.albums) {
      if (r.type === "artist") {
        let albumHtml = `Albums: <span class="artist-albums-count">${r.albums}</span>`;
        if (r.resolving_discography) {
          albumHtml += ` <span class="artist-albums-filter scrambling"></span>`;
        } else if (r.diff_sd !== undefined && r.diff_sd > 0) {
          albumHtml += ` <span class="artist-albums-filter dynamic-filter" data-sd="${r.diff_sd}" data-tip="Estimates active duplicate and edition filters skipping releases based on Discography toggles."></span>`;
        }
        metaParts.push(albumHtml);
      } else {
        metaParts.push(r.albums + " albums");
      }
    }

    if (r.release_date) {
      metaParts.push(r.release_date.slice(0, 4));
    } else if (r.year) {
      metaParts.push(r.year);
    }

    const metaRow = metaParts.length
      ? `<span class="queue-card-meta">${metaParts.join(" · ")}</span>`
      : "";

    info.innerHTML = `
      <span class="queue-card-title">${_esc(r.title || card.dataset.url)}</span>
      <span class="queue-card-artist">${_esc(r.artist || "")}</span>
      <span class="queue-card-bottom-row">${typeBadge}${explicitIcon}${metaRow}</span>
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

    const sdCheck = document.getElementById("dl-smart-discography");
    if (sdCheck) {
      sdCheck.addEventListener("change", () => {
        if (window._updateQueueBadge) window._updateQueueBadge();
      });
    }

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
      let hasArtist = false;
      
      if (_textMode) {
        const val = document.getElementById("dl-urls").value || "";
        const lines = val.split(/[\n\r]+/).filter((l) => l.trim());
        total = lines.length;
        hasArtist = lines.some(l => l.includes("artist"));
      } else {
        _urlQueue.forEach((qi) => {
          if (!qi.resolved) {
            if (qi.url && qi.url.includes("artist")) hasArtist = true;
            total += 1;
            return;
          }
          const r = qi.resolved;
          if (r.type === "track") {
            total += 1;
            return;
          }
          if (r.type === "artist") {
            const sdCheck = document.getElementById("dl-smart-discography");
            const aoCheck = document.getElementById("dl-albums-only");
            
            if (r.raw_tracks !== undefined) {
                if (sdCheck?.checked) {
                    total += r.sd_filtered_tracks;
                } else {
                    total += r.raw_tracks;
                }
            } else {
                if (r.albums) total += (r.albums * 10); // temporary rough estimate until check async resolves
                hasUnknown = true;
            }
            hasArtist = true;
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
      
      const artistGroup = document.getElementById("dl-artist-section");
      if (artistGroup) {
        if (!hasArtist) {
          artistGroup.classList.add("hidden");
        } else {
          artistGroup.classList.remove("hidden");
        }
      }
    };

    // URL-level counters (for card state management)
    let _dlTotal = 0;
    let _dlDone = 0;

    // Track-level counters (drive the progress bar)
    let _dlTrackTotal = 0;
    let _dlTrackDone = 0;
    let _dlTotalLocked = false;

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
      if (ev.type === "total_tracks") {
        _dlTrackTotal = ev.count;
        _dlTotalLocked = true;
        _updateProgress();
      } else if (ev.type === "url_start") {
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
        if (!_dlTotalLocked && _dlTrackDone > _dlTrackTotal) {
           _dlTrackTotal = _dlTrackDone + 1;
        }
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
          _dlTotalLocked = false;
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
    const luckySlider = document.getElementById("lucky-number");
    const luckyVal = document.getElementById("lucky-number-val");
    if (luckySlider && luckyVal) {
      luckySlider.addEventListener("input", () => {
        luckyVal.textContent = luckySlider.value;
      });
    }

    document.getElementById("search-btn").addEventListener("click", doSearch);
    const searchQuery = document.getElementById("search-query");
    const searchBtn = document.getElementById("search-btn");
    
    searchQuery.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !searchBtn.disabled) doSearch();
    });
    
    searchQuery.addEventListener("input", () => {
      const query = searchQuery.value.trim();
      searchBtn.disabled = query.length < 3;
    });

    document.getElementById("lucky-btn").addEventListener("click", doLucky);
  }

  async function doSearch() {
    const query = document.getElementById("search-query").value.trim();
    if (query.length < 3) {
      appendLog(
        "log-output",
        "[error] Query must be at least 3 characters.",
      );
      return;
    }
    const type = document.getElementById("search-type").value;
    const limit = document.getElementById("search-limit").value;

    const btn = document.getElementById("search-btn");
    btn.disabled = true;
    btn.classList.add("searching");

    document.getElementById("search-results-container").classList.add("hidden");
    document.getElementById("search-empty").classList.add("hidden");

    try {
      const res = await fetch(
        `/api/search?q=${encodeURIComponent(query)}&type=${type}&limit=${limit}`,
      );
      const data = await res.json();

      if (!data.ok) {
        appendLog("log-output", "[error] " + data.error);
        return;
      }

      _searchResults = data.results || [];
      renderResults(_searchResults, query);
    } catch (e) {
      appendLog("log-output", "[error] " + e.message);
    } finally {
      btn.disabled = false;
      btn.classList.remove("searching");
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
      item.className = "result-item result-card";
      item.dataset.index = i;

      // Image - use type-specific placeholders
      const img = document.createElement("img");
      img.className = "result-card-art";
      const fallback = r.type === "artist" 
        ? "/gui/artist-placeholder.png" 
        : "/gui/placeholder.png";
      
      img.src = r.cover || fallback;
      img.onerror = () => {
        // Prevent infinite loop if fallback also fails
        if (!img.src.endsWith(fallback)) {
          img.src = fallback;
        }
      };

      const info = document.createElement("div");
      info.className = "result-card-info";

      const text = document.createElement("div");
      text.className = "result-card-text";
      text.textContent = r.text;

      info.appendChild(text);

      // Quality / Stat badge
      let badgeContent = r.badge;
      let badgeClass = "result-badge";

      // The backend text may still have [HI-RES] if it's an old cache, but core.py is now cleaning it.
      // We clean it here too just in case. Duration can be MM:SS or HH:MM:SS.
      let cleanText = (r.text || "")
        .replace(/ \[\w+\]$/, "")              // Remove trailing [QUALITY]
        .replace(/ - (\d+:)?\d+:\d+$/, "");    // Remove trailing - duration (MM:SS or HH:MM:SS)

      if (!badgeContent) {
        if (r.quality === "HI-RES") {
          badgeClass += " badge-hires";
          badgeContent = "HI-RES";
        } else if (r.quality === "LOSSLESS") {
          badgeClass += " badge-lossless";
          badgeContent = "LOSSLESS";
        } else if (r.type !== "artist" && r.type !== "playlist") {
          badgeClass += " badge-mp3";
          badgeContent = "MP3";
        }
      }

      // Metadata line (second line)
      const metaRow = document.createElement("div");
      metaRow.className = "result-card-meta-row";

      if (r.explicit) {
        const explicitBadge = document.createElement("span");
        explicitBadge.className = "result-badge badge-explicit";
        const explicitSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        explicitSvg.setAttribute("viewBox", "0 0 24 24");
        explicitSvg.setAttribute("class", "quality-icon");
        explicitSvg.innerHTML = `<path fill="currentColor" d="M10.603 15.626v-2.798h3.632a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.241h-3.632V8.352h3.632a.8.8 0 0 0 .598-.24q.24-.242.24-.599a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.24h-4.47a.8.8 0 0 0-.598.24.81.81 0 0 0-.24.598v8.952q0 .357.24.598.241.24.598.241h4.47a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.81.81 0 0 0-.598-.241zM4.52 21.5c-.575-.052-.98-.284-1.383-.651-.39-.392-.55-.844-.637-1.372V4.493c.135-.607.27-.961.661-1.353.392-.391.762-.548 1.343-.64H19.47c.541.066.952.254 1.362.62.413.37.546.796.668 1.38v14.977c-.074.467-.237.976-.629 1.367-.39.392-.82.595-1.391.656z"></path>`;
        explicitBadge.appendChild(explicitSvg);
        metaRow.appendChild(explicitBadge);
      }

      if (badgeContent) {
        const badge = document.createElement("span");
        badge.className = badgeClass;
        if (r.badge) {
          badge.className += " badge-neutral";
          badge.textContent = badgeContent;
        } else if (r.quality === "HI-RES") {
          const icon = document.createElement("img");
          icon.src = "/gui/hi-res.jpg";
          icon.className = "quality-icon";
          badge.appendChild(icon);
        } else if (r.quality === "LOSSLESS") {
          const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
          svg.setAttribute("viewBox", "0 0 32 32");
          svg.setAttribute("class", "quality-icon");
          svg.innerHTML = `<path d="M16 22.7368C17.8785 22.7368 19.471 22.0837 20.7773 20.7773C22.0837 19.471 22.7368 17.8785 22.7368 16C22.7368 14.1215 22.0837 12.529 20.7773 11.2227C19.471 9.91635 17.8785 9.26318 16 9.26318C14.1215 9.26318 12.529 9.91635 11.2227 11.2227C9.91635 12.529 9.26318 14.1215 9.26318 16C9.26318 17.8785 9.91635 19.471 11.2227 20.7773C12.529 22.0837 14.1215 22.7368 16 22.7368ZM16 17.6842C15.5228 17.6842 15.1228 17.5228 14.8 17.2C14.4772 16.8772 14.3158 16.4772 14.3158 16C14.3158 15.5228 14.4772 15.1228 14.8 14.8C15.1228 14.4772 15.5228 14.3158 16 14.3158C16.4772 14.3158 16.8772 14.4772 17.2 14.8C17.5228 15.1228 17.6842 15.5228 17.6842 16C17.6842 16.4772 17.5228 16.8772 17.2 17.2C16.8772 17.5228 16.4772 17.6842 16 17.6842ZM16.0028 32C13.7899 32 11.7098 31.5801 9.76264 30.7402C7.81543 29.9003 6.12164 28.7606 4.68128 27.3208C3.24088 25.8811 2.10057 24.188 1.26034 22.2417C0.420114 20.2954 0 18.2158 0 16.0028C0 13.7899 0.419931 11.7098 1.25979 9.76264C2.09965 7.81543 3.23945 6.12165 4.67917 4.68128C6.11892 3.24088 7.81196 2.10057 9.7583 1.26034C11.7046 0.420115 13.7842 0 15.9972 0C18.2101 0 20.2902 0.419933 22.2374 1.25979C24.1846 2.09966 25.8784 3.23945 27.3187 4.67917C28.7591 6.11892 29.8994 7.81197 30.7397 9.7583C31.5799 11.7046 32 13.7842 32 15.9972C32 18.2101 31.5801 20.2902 30.7402 22.2374C29.9003 24.1846 28.7606 25.8784 27.3208 27.3187C25.8811 28.7591 24.188 29.8994 22.2417 30.7397C20.2954 31.5799 18.2158 32 16.0028 32ZM16 29.4737C19.7614 29.4737 22.9474 28.1685 25.5579 25.5579C28.1685 22.9474 29.4737 19.7614 29.4737 16C29.4737 12.2386 28.1685 9.05261 25.5579 6.44208C22.9474 3.83155 19.7614 2.52628 16 2.52628C12.2386 2.52628 9.05261 3.83155 6.44208 6.44208C3.83155 9.05261 2.52628 12.2386 2.52628 16C2.52628 19.7614 3.83155 22.9474 6.44208 25.5579C9.05261 28.1685 12.2386 29.4737 16 29.4737Z" fill="white"></path>`;
          badge.appendChild(svg);
        } else {
          badge.textContent = badgeContent;
        }
        metaRow.appendChild(badge);
      }

      // Tracks + Release Date metadata
      let metaLine = [];
      if (r.tracks) {
        metaLine.push(`${r.tracks} track${r.tracks !== 1 ? 's' : ''}`);
      }
      if (r.release_date) {
        const d = new Date(r.release_date + "T00:00:00");
        const formatted = d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
        metaLine.push(formatted);
      }

      if (metaLine.length > 0) {
        const metaText = document.createElement("span");
        metaText.className = "result-meta-text";
        metaText.textContent = metaLine.join(" • ");
        metaRow.appendChild(metaText);
      }

      // Update text with clean version
      text.textContent = cleanText;

      info.appendChild(metaRow);

      item.appendChild(img);
      item.appendChild(info);

      // Add "Add to Queue" button (Hover icon)
      const addBtn = document.createElement("button");
      addBtn.className = "result-add-btn";
      addBtn.title = "Add to Queue";
      addBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
            <polyline points="12 5 19 12 12 19"></polyline>
        </svg>
      `;

      addBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (r.url) {
          _addUrlToQueue(r.url);
          // Visual feedback
          addBtn.classList.add("added");
          addBtn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          `;
          setTimeout(() => {
            addBtn.classList.remove("added");
            addBtn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="5" y1="12" x2="19" y2="12"></line>
                    <polyline points="12 5 19 12 12 19"></polyline>
                </svg>
            `;
          }, 1500);
        }
      });

      item.appendChild(addBtn);

      list.appendChild(item);
    });
  }


  async function doLucky() {
    const query = document.getElementById("search-query").value.trim();
    if (query.length < 3) {
      appendLog(
        "log-output",
        "[error] Query must be at least 3 characters.",
      );
      return;
    }
    const type = document.getElementById("search-type").value;
    const number =
      parseInt(document.getElementById("lucky-number").value, 10) || 1;

    const btn = document.getElementById("lucky-btn");
    btn.disabled = true;
    btn.textContent = "Processing…";

    try {
      // For lucky mode, we fetch results and queue the top N
      const res = await fetch(
        `/api/search?q=${encodeURIComponent(query)}&type=${type}&limit=${number}`,
      );
      const data = await res.json();
      if (!data.ok) {
        appendLog("log-output", "[error] " + data.error);
      } else {
        const results = data.results || [];
        const toAdd = results.slice(0, number);
        if (toAdd.length === 0) {
          appendLog("log-output", "[warn] No lucky results found.");
        } else {
          toAdd.forEach((r) => {
            if (r.url) _addUrlToQueue(r.url);
          });
          appendLog(
            "log-output",
            `[info] Queued top ${toAdd.length} result(s) for "${query}".`,
          );
        }
      }
    } catch (e) {
      appendLog("log-output", "[error] " + e.message);
    } finally {
      btn.disabled = false;
      btn.textContent = "Lucky to Queue";
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
        cfg.folder_format || "{artist}/{album}",
      );
      setValue(
        "cfg-track-format",
        cfg.track_format || "{tracknumber} - {tracktitle}",
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
        const res = await fetch("/api/update/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ download_url: _updateInfo.download_url }),
        });
        const data = await res.json();
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
    const res = await fetch("/api/update/check" + q);
    return await res.json();
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
    try {
      const dismissed = sessionStorage.getItem("qobuz-dl-update-dismiss");
      if (dismissed && dismissed === String(data.latest_version)) {
        banner.classList.add("hidden");
        return;
      }
    } catch (e) {
      /* ignore */
    }
    let msg =
      "Version " +
      data.latest_version +
      " is available (you have " +
      data.current_version +
      ").";
    if (!data.download_url) {
      msg += " Download the new build from the release page.";
    }
    textEl.textContent = msg;
    if (data.release_page) {
      linkEl.href = data.release_page;
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

    const checkUpdBtn = document.getElementById("settings-check-updates-btn");
    const updFeedback = document.getElementById("settings-update-feedback");
    if (checkUpdBtn && updFeedback) {
      checkUpdBtn.addEventListener("click", async () => {
        checkUpdBtn.disabled = true;
        updFeedback.className = "feedback-msg hidden";
        try {
          const data = await refreshUpdateCheck(true);
          if (!data) throw new Error("Network error");
          if (data.skipped && data.reason === "repo_not_configured") {
            showFeedback(
              updFeedback,
              "Update source not configured (see qobuz_dl/version.py).",
              false,
            );
          } else if (!data.ok) {
            showFeedback(updFeedback, data.error || "Check failed", false);
          } else if (data.update_available) {
            showFeedback(
              updFeedback,
              "Update available: v" + data.latest_version,
              true,
            );
          } else {
            showFeedback(updFeedback, "You're on the latest version.", true);
          }
        } catch (e) {
          showFeedback(updFeedback, e.message || "Check failed", false);
        } finally {
          checkUpdBtn.disabled = false;
        }
      });
    }

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
    initCollapses();
    initResetButtons();
    initAuthTabs();
    initSetup();
    initBrowseButtons();
    initDownload();
    initSearch();
    initSettings();
    initUpdateBanner();

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
      refreshUpdateCheck(false);
    } else {
      showSetup();
    }
  }

  // ── Format field help panels (click ⓘ to open; click out to close) ──
  function initFormatTooltips() {
    let openTip = null;

    function positionFormatTooltip(tip, anchorEl) {
      const zone = anchorEl.closest(".form-group");
      if (!zone) return;
      const zoneRect = zone.getBoundingClientRect();
      tip.style.position = "fixed";
      tip.style.display = "block";
      tip.style.top = "auto";
      tip.style.bottom = window.innerHeight - zoneRect.top + 8 + "px";
      const rightFromEdge = window.innerWidth - zoneRect.right;
      tip.style.right = Math.max(8, rightFromEdge) + "px";
      tip.style.left = "auto";
      const rect = tip.getBoundingClientRect();
      if (rect.left < 8) {
        tip.style.right = "auto";
        tip.style.left = "8px";
      }
    }

    function resetFormatPreview(tip) {
      const preview = tip.querySelector(".fmt-preview-output");
      if (!preview) return;
      const ph = preview.dataset.placeholder || "Hover a template below";
      preview.textContent = ph;
      preview.classList.add("fmt-preview-placeholder");
    }

    function closeAllFormatTips() {
      if (!openTip) return;
      openTip.style.display = "none";
      resetFormatPreview(openTip);
      const prevId =
        openTip.id === "folder-format-tooltip"
          ? "folder-format-help"
          : "track-format-help";
      const prevTrigger = document.getElementById(prevId);
      if (prevTrigger) {
        prevTrigger.classList.remove("active");
        prevTrigger.setAttribute("aria-expanded", "false");
      }
      openTip = null;
    }

    function bindTemplatePreviews(tip) {
      const preview = tip.querySelector(".fmt-preview-output");
      const container = tip.querySelector(".fmt-templates");
      if (!preview || !container) return;
      const placeholder =
        preview.dataset.placeholder || "Hover a template below";

      container.querySelectorAll(".fmt-template-chip").forEach((chip) => {
        chip.addEventListener("mouseenter", () => {
          const text = chip.getAttribute("data-preview");
          if (!text) return;
          preview.textContent = text;
          preview.classList.remove("fmt-preview-placeholder");
        });
      });
      container.addEventListener("mouseleave", () => {
        preview.textContent = placeholder;
        preview.classList.add("fmt-preview-placeholder");
      });
    }

    const pairs = [
      ["folder-format-help", "folder-format-tooltip"],
      ["track-format-help", "track-format-tooltip"],
    ];

    pairs.forEach(([triggerId, tooltipId]) => {
      const trigger = document.getElementById(triggerId);
      const tip = document.getElementById(tooltipId);
      if (!trigger || !tip) return;

      bindTemplatePreviews(tip);

      function toggleFromTrigger(e) {
        if (e) {
          e.preventDefault();
          e.stopPropagation();
        }
        const wasOpen = openTip === tip && tip.style.display === "block";
        closeAllFormatTips();
        if (!wasOpen) {
          positionFormatTooltip(tip, trigger);
          openTip = tip;
          trigger.classList.add("active");
          trigger.setAttribute("aria-expanded", "true");
        }
      }

      trigger.addEventListener("click", toggleFromTrigger);
      trigger.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleFromTrigger(e);
        }
      });
    });

    document.addEventListener("click", (e) => {
      if (!openTip) return;
      if (openTip.contains(e.target)) return;
      const triggers = pairs
        .map(([id]) => document.getElementById(id))
        .filter(Boolean);
      if (triggers.some((t) => t.contains(e.target))) return;
      closeAllFormatTips();
    });

    window.addEventListener("resize", () => {
      if (!openTip) return;
      const tid =
        openTip.id === "folder-format-tooltip"
          ? "folder-format-help"
          : "track-format-help";
      const tr = document.getElementById(tid);
      if (tr) positionFormatTooltip(openTip, tr);
    });
  }

  function initDonationPopover() {
    const btn = document.getElementById("monero-btn");
    const pop = document.getElementById("donation-popover");
    const copyBtn = document.getElementById("copy-address-btn");
    const addrEl = document.getElementById("monero-address");
    const copyText = document.getElementById("copy-text");

    if (!btn || !pop) return;

    function togglePopover(e) {
      if (e) e.stopPropagation();
      const isHidden = pop.classList.contains("hidden");

      if (isHidden) {
        // Show and position
        pop.classList.remove("hidden");
        const btnRect = btn.getBoundingClientRect();
        
        // Position above the button
        pop.style.bottom = (window.innerHeight - btnRect.top + 10) + "px";
        
        // Align with the button's center, but stay within window
        let left = btnRect.left + (btnRect.width / 2) - (pop.offsetWidth / 2);
        pop.style.left = Math.max(10, Math.min(left, window.innerWidth - pop.offsetWidth - 10)) + "px";
        
        btn.classList.add("active");
      } else {
        hidePopover();
      }
    }

    function hidePopover() {
      pop.classList.add("hidden");
      btn.classList.remove("active");
    }

    btn.addEventListener("click", togglePopover);

    // Close on click outside
    document.addEventListener("click", (e) => {
      if (!pop.classList.contains("hidden") && !pop.contains(e.target) && !btn.contains(e.target)) {
        hidePopover();
      }
    });

    if (copyBtn && addrEl) {
      copyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const addr = addrEl.textContent.trim();
        navigator.clipboard.writeText(addr).then(() => {
          const original = copyText.textContent;
          copyText.textContent = "Copied!";
          copyBtn.style.background = "var(--success)";
          copyBtn.style.color = "white";
          setTimeout(() => {
            copyText.textContent = original;
            copyBtn.style.background = "";
            copyBtn.style.color = "";
          }, 2000);
        });
      });
    }
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("DOMContentLoaded", initFormatTooltips);
  document.addEventListener("DOMContentLoaded", initDonationPopover);
})();
