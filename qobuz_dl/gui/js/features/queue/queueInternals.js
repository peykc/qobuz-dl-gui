(function () {
  "use strict";
  const g = window.QobuzGui;
  const qroot = (g.features.queue = g.features.queue || {});

  /**
   * URL queue state, cards, persist/restore, drag handlers.
   * Invoked once per page from app `initDownload()` with deps.
   */
  function bootstrap(deps) {
    const getTsMap = () => deps.getTrackStatusMap();
    const GUI_PENDING = deps.guiPendingAudioPrefix;
    function syncSearchHi() {
      deps.syncSearchQueuedHighlights();
    }
    const QG = g;
    const api = g.api;

  // ── URL Queue System ─────────────────────────────────────
  const _urlQueue = []; // [{url, resolved: {title, artist, cover, type, ...}}]
  let _textMode = false;

  function _qobuzUrlTypeAndId(url) {
    const s = String(url || "").trim();
    const m = s.match(
      /(?:https?:\/\/(?:www|open|play)\.qobuz\.com)?(?:\/[a-z]{2}-[a-z]{2})?\/(album|artist|track|playlist|label)(?:\/[-\w\d]+)?\/([\w\d]+)/i,
    );
    if (!m) return { type: "", id: "" };
    return {
      type: String(m[1] || "").toLowerCase(),
      id: String(m[2] || "").trim(),
    };
  }

  function _countHistoryDownloadedForRelease(releaseAlbumId) {
    const rid = String(releaseAlbumId || "").trim();
    if (!rid) return 0;
    let n = 0;
    for (const it of getTsMap().values()) {
      if (String(it.release_album_id || "").trim() !== rid) continue;
      const st = String(it.download_status || "downloaded").toLowerCase();
      if (st !== "downloaded") continue;
      const ap = String(it.audio_path || "").trim();
      if (!ap || ap.startsWith(GUI_PENDING)) continue;
      n++;
    }
    return n;
  }

  function _albumRemainingAndTotalFromQueueItem(qi) {
    if (!qi || !qi.resolved) return null;
    const r = qi.resolved;
    if (r.type !== "album" || r.tracks == null) return null;
    let total = Number(r.tracks);
    if (!Number.isFinite(total) || total <= 0) return null;
    total = Math.max(0, Math.floor(total));
    const id =
      String(r.release_album_id || "").trim() ||
      _qobuzUrlTypeAndId(qi.url).id ||
      "";
    if (!id) return null;
    const done = _countHistoryDownloadedForRelease(id);
    const remaining = Math.max(0, total - done);
    return { total, done, remaining };
  }

  function _releaseAlbumIdFromQueueItem(qi) {
    if (!qi?.resolved || qi.resolved.type !== "album") return "";
    const r = qi.resolved;
    const fromMeta = String(r.release_album_id || "").trim();
    if (fromMeta) return fromMeta;
    return String(_qobuzUrlTypeAndId(qi.url).id || "").trim();
  }

  /** True while album still has unfinished work: remaining tracks vs history, failed/purchase rows, or pending substitute slots. */
  function _albumQueueItemNeedsToStayVisible(qi) {
    if (!qi?.resolved || qi.resolved.type !== "album") return false;
    const rid = _releaseAlbumIdFromQueueItem(qi);
    if (!rid) return false;
    const alb = _albumRemainingAndTotalFromQueueItem(qi);
    if (alb != null && alb.remaining > 0) return true;
    for (const it of getTsMap().values()) {
      if (String(it.release_album_id || "").trim() !== rid) continue;
      const st = String(it.download_status || "downloaded").toLowerCase();
      const ap = String(it.audio_path || "").trim();
      if (st === "failed" || st === "purchase_only") return true;
      if (ap.startsWith(GUI_PENDING)) return true;
    }
    return false;
  }

  function _remainingTracksContributionFromQueueItem(qi) {
    if (!qi.resolved) return 1;
    const r = qi.resolved;
    if (r.type === "track") return 1;
    const alb = _albumRemainingAndTotalFromQueueItem(qi);
    if (alb) return alb.remaining;
    if (r.type === "artist") {
      const sdCheck = document.getElementById("dl-smart-discography");
      if (r.raw_tracks !== undefined) {
        if (sdCheck?.checked) {
          const n = Number(r.sd_filtered_tracks);
          return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
        }
        const n = Number(r.raw_tracks);
        return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0;
      }
      if (r.albums) return (Number(r.albums) || 0) * 10;
      return 1;
    }
    if (r.tracks) {
      const n = Number(r.tracks);
      return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 1;
    }
    return 1;
  }

  /** Expected track workload for URL queue card mode (subtracts GUI download history per album). */
  function _calcTrackTotalFromQueue() {
    let total = 0;
    _urlQueue.forEach((qi) => {
      total += _remainingTracksContributionFromQueueItem(qi);
    });
    return Math.max(total, 1);
  }

  /**
   * Planned track_result callbacks for progress (full album/track passes), not remaining-after-history.
   * Downloader walks every album track even when skipping | remaining-only totals caused done > denominator.
   */
  function _progressBarDenominatorFromQueueItem(qi) {
    if (!qi?.resolved) return 1;
    const r = qi.resolved;
    if (r.type === "track") return 1;
    if (r.type === "album") {
      const alb = _albumRemainingAndTotalFromQueueItem(qi);
      if (alb != null && alb.total > 0) return alb.total;
      const n = Number(r.tracks);
      return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
    }
    if (r.type === "playlist") {
      const n = Number(r.tracks);
      return Number.isFinite(n) && n > 0 ? Math.floor(n) : 1;
    }
    return _remainingTracksContributionFromQueueItem(qi);
  }

  function _calcProgressDenominatorFromQueue() {
    let total = 0;
    _urlQueue.forEach((qi) => {
      total += _progressBarDenominatorFromQueueItem(qi);
    });
    return Math.max(total, 1);
  }

  let _guiQueueRestoring = false;
  let _guiQueuePersistTimer = null;

  function _buildGuiQueuePersistPayload() {
    const ta = document.getElementById("dl-urls");
    if (_textMode) {
      return {
        version: 1,
        text_mode: true,
        text_urls: ta ? String(ta.value || "") : "",
        items: [],
      };
    }
    return {
      version: 1,
      text_mode: false,
      text_urls: "",
      items: _urlQueue.map((qi) => ({
        url: qi.url,
        resolved: qi.resolved,
      })),
    };
  }

  function _schedulePersistGuiQueueState() {
    if (_guiQueueRestoring) return;
    if (_guiQueuePersistTimer) clearTimeout(_guiQueuePersistTimer);
    _guiQueuePersistTimer = window.setTimeout(() => {
      _guiQueuePersistTimer = null;
      void api.queueApi.persist(_buildGuiQueuePersistPayload()).catch(() => {});
    }, 400);
  }

  async function _restoreGuiQueueFromServer() {
    try {
      const res = await api.queueApi.get();
      const data = await res.json();
      if (!data.ok) return;
      const items = Array.isArray(data.items) ? data.items : [];
      _guiQueueRestoring = true;
      if (data.text_mode) {
        _setMode(false);
        _urlQueue.length = 0;
        const ta = document.getElementById("dl-urls");
        if (ta) ta.value = data.text_urls || "";
        document
          .getElementById("dl-queue")
          ?.querySelectorAll(".queue-card")
          .forEach((c) => c.remove());
        const empty = document.getElementById("dl-queue-empty");
        if (empty) empty.style.display = ta && ta.value.trim() ? "none" : "";
        if (window._updateQueueBadge) window._updateQueueBadge();
        syncSearchHi();
      } else {
        _setMode(true);
        _urlQueue.length = 0;
        for (let i = 0; i < items.length; i++) {
          const row = items[i];
          const u = String(row.url || "").trim();
          if (!u) continue;
          _urlQueue.push({
            url: u,
            resolved:
              row.resolved != null && typeof row.resolved === "object"
                ? row.resolved
                : null,
          });
        }
        _rebuildCards();
      }
    } catch (_) {
      /* ignore */
    } finally {
      _guiQueueRestoring = false;
    }
  }

  function _refreshAlbumQueueCardMetas() {
    _urlQueue.forEach((qi) => {
      if (!qi.resolved || qi.resolved.type !== "album") return;
      const cards = document.querySelectorAll("#dl-queue .queue-card");
      let card = null;
      for (let i = 0; i < cards.length; i++) {
        if (cards[i].dataset.url === qi.url) {
          card = cards[i];
          break;
        }
      }
      if (card) _updateQueueCard(card, qi.resolved);
    });
  }

  function _queuedUrlSetForSearchHighlight() {
    if (_textMode) {
      const lines = (document.getElementById("dl-urls")?.value || "")
        .split(/[\n\r]+/)
        .map((l) => l.trim())
        .filter(Boolean);
      return new Set(lines);
    }
    return new Set(_urlQueue.map((q) => q.url));
  }

  function _scrollDlQueueToBottom() {
    const el = document.getElementById("dl-queue");
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }

  function _syncHiddenTextarea() {
    document.getElementById("dl-urls").value = _urlQueue
      .map((q) => q.url)
      .join("\n");
    const empty = document.getElementById("dl-queue-empty");
    if (empty) empty.style.display = _urlQueue.length ? "none" : "";
    if (window._updateQueueBadge) window._updateQueueBadge();
    syncSearchHi();
    _schedulePersistGuiQueueState();
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
    _scrollDlQueueToBottom();

    // Resolve metadata in background
    api.downloadApi.resolve({ url })
      .then((r) => r.json())
      .then((data) => {
        if (data.ok && data.result) {
          const qi = _urlQueue.find((q) => q.url === url);
          if (qi) qi.resolved = data.result;
          data.result.resolving_discography = (data.result.type === "artist");
          _updateQueueCard(card, data.result);
          
          if (data.result.type === "artist") {
             api.downloadApi.checkDiscography({ url })
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
             })
             .finally(() => {
                _schedulePersistGuiQueueState();
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
      })
      .finally(() => {
        _schedulePersistGuiQueueState();
      });
  }

  function _removeFromQueue(url, card) {
    const i = _urlQueue.findIndex((q) => q.url === url);
    if (i !== -1) _urlQueue.splice(i, 1);
    card.remove();
    _syncHiddenTextarea();
  }

  function _removeFromQueueByUrl(url) {
    const wrap = document.getElementById("dl-queue");
    let card = null;
    if (wrap) {
      for (const c of wrap.querySelectorAll(".queue-card")) {
        if (c.dataset.url === url) {
          card = c;
          break;
        }
      }
    }
    if (card) {
      _removeFromQueue(url, card);
    } else {
      const i = _urlQueue.findIndex((q) => q.url === url);
      if (i !== -1) _urlQueue.splice(i, 1);
      _syncHiddenTextarea();
    }
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
      <span class="queue-card-title">${QG.core.dom.esc(url)}</span>
      <span class="queue-card-artist-row">
        <span class="queue-card-artist">Loading…</span>
      </span>
      <span class="queue-card-bottom-row queue-card-bottom-row--loading" aria-hidden="true"></span>
    `;
    card.appendChild(info);

    const btn = document.createElement("button");
    btn.className = "queue-card-remove";
    btn.innerHTML = "×";
    btn.setAttribute("data-tip", "Remove");
    btn.setAttribute("aria-label", "Remove");
    btn.removeAttribute("title");
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      _removeFromQueue(url, card);
    });
    card.appendChild(btn);

    return card;
  }

  /** Green (low) → app teal #6ee7f7 (high) from bit depth × sample rate. */
  function _queueQualityGradientAtT(t) {
    t = Math.max(0, Math.min(1, t));
    const r0 = 74;
    const g0 = 222;
    const b0 = 128;
    const r1 = 110;
    const g1 = 231;
    const b1 = 247;
    return {
      r: Math.round(r0 + (r1 - r0) * t),
      g: Math.round(g0 + (g1 - g0) * t),
      b: Math.round(b0 + (b1 - b0) * t),
    };
  }

  function _queueCardQualityRgb(r) {
    const qStr = String(r.quality || "").toLowerCase();
    if (/\bmp3\b|lossy|\b320\b|\baac\b/.test(qStr)) {
      return _queueQualityGradientAtT(0);
    }
    let bd = Number(r.bit_depth);
    let sr = Number(r.sample_rate);
    if (r.sample_rate != null && r.sample_rate !== "") {
      const hzNorm = QG.core.format.normalizeSamplingRateHz(r.sample_rate);
      if (hzNorm != null && Number.isFinite(hzNorm)) {
        sr = hzNorm / 1000;
      }
    }
    if ((!Number.isFinite(bd) || !Number.isFinite(sr)) && r.quality) {
      const m = String(r.quality).match(/(\d+)\s*bit\s*\/\s*([\d.]+)\s*kHz/i);
      if (m) {
        bd = parseInt(m[1], 10);
        sr = parseFloat(m[2]);
      }
    }
    if (!Number.isFinite(bd) || !Number.isFinite(sr)) {
      return _queueQualityGradientAtT(0.22);
    }
    const minScore = 16 * 44.1;
    const maxScore = 24 * 192;
    const score = bd * sr;
    const clamped = Math.max(minScore, Math.min(maxScore, score));
    const t = (clamped - minScore) / (maxScore - minScore);
    return _queueQualityGradientAtT(t);
  }

  function _queueCardQualityStyleAttr(r) {
    const { r: rv, g: gv, b: bv } = _queueCardQualityRgb(r);
    return ` style="color:rgb(${rv},${gv},${bv});border-color:rgba(${rv},${gv},${bv},0.55);background-color:rgba(${rv},${gv},${bv},0.17)"`;
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
    if (!info) return;
    /** Preserved across innerHTML rebuild — `_refreshAlbumQueueCardMetas` runs often and must not drop error UX. */
    const preservedErrorBadges = Array.from(
      info.querySelectorAll(".dl-error-badge"),
    );

    // === Type badge ===
    const typeBadge = r.type
      ? `<span class="queue-card-badge badge-${r.type}">${r.type}</span>`
      : "";

    // === Explicit icon ===
    const explicitIcon = r.explicit
      ? `<span class="queue-card-explicit explicit-tag-badge" data-tip="Explicit"><svg viewBox="0 0 24 24" class="queue-explicit-icon"><path fill="currentColor" d="M10.603 15.626v-2.798h3.632a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.241h-3.632V8.352h3.632a.8.8 0 0 0 .598-.24q.24-.242.24-.599a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.24h-4.47a.8.8 0 0 0-.598.24.81.81 0 0 0-.24.598v8.952q0 .357.24.598.241.24.598.241h4.47a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.81.81 0 0 0-.598-.241zM4.52 21.5c-.575-.052-.98-.284-1.383-.651-.39-.392-.55-.844-.637-1.372V4.493c.135-.607.27-.961.661-1.353.392-.391.762-.548 1.343-.64H19.47c.541.066.952.254 1.362.62.413.37.546.796.668 1.38v14.977c-.074.467-.237.976-.629 1.367-.39.392-.82.595-1.391.656z"></path></svg></span>`
      : "";

    // === Format chip (color grades green → teal by effective bitrate) ===
    let qualityHtml = "";
    if (r.bit_depth && r.sample_rate) {
      const q = `${r.bit_depth}bit / ${r.sample_rate}kHz`;
      qualityHtml = `<span class="queue-card-quality"${_queueCardQualityStyleAttr(
        r,
      )} data-tip="Source format from Qobuz: bit depth and sample rate">${QG.core.dom.esc(q)}</span>`;
    } else if (r.quality) {
      qualityHtml = `<span class="queue-card-quality"${_queueCardQualityStyleAttr(
        r,
      )} data-tip="Format from Qobuz">${QG.core.dom.esc(r.quality)}</span>`;
    }

    // === Meta parts (tracks, year, etc.) ===
    const metaParts = [];
    const qurlTrim = String(card.dataset.url || "").trim();
    const qiCard = qurlTrim
      ? _urlQueue.find((x) => x.url === qurlTrim)
      : null;

    if (r.tracks && r.type !== "artist") {
      const alb = qiCard ? _albumRemainingAndTotalFromQueueItem(qiCard) : null;
      if (alb && alb.done > 0 && alb.remaining < alb.total) {
        metaParts.push(
          `${alb.remaining} remaining \u00b7 ${alb.total} on album`,
        );
      } else {
        metaParts.push(`${r.tracks} track${r.tracks !== 1 ? "s" : ""}`);
      }
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
      <span class="queue-card-title">${QG.core.dom.esc(r.title || card.dataset.url)}</span>
      <span class="queue-card-artist-row">
        ${typeBadge}<span class="queue-card-artist">${QG.core.dom.esc(r.artist || "")}</span>
      </span>
      <span class="queue-card-bottom-row">${qualityHtml}${explicitIcon}${metaRow}</span>
    `;
    preservedErrorBadges.forEach((badge) => info.appendChild(badge));
    if (window._updateQueueBadge) window._updateQueueBadge();
    const qEl = document.getElementById("dl-queue");
    if (qEl) {
      const cards = qEl.querySelectorAll(".queue-card");
      if (cards.length && cards[cards.length - 1] === card) {
        _scrollDlQueueToBottom();
      }
    }
  }

  // Rebuild cards from queue data (used when switching back from text mode)
  function _rebuildCards() {
    const queue = document.getElementById("dl-queue");
    queue.querySelectorAll(".queue-card").forEach((c) => c.remove());
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
    _syncHiddenTextarea();
    _scrollDlQueueToBottom();
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
        api.downloadApi.resolve({ url: u })
          .then((r) => r.json())
          .then((data) => {
            const qi = _urlQueue.find((q) => q.url === u);
            if (qi && data.ok && data.result) qi.resolved = data.result;
          })
          .catch(() => {})
          .finally(() => {
            _schedulePersistGuiQueueState();
          });
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
    if (window._updateQueueBadge) window._updateQueueBadge();
    syncSearchHi();
    _schedulePersistGuiQueueState();
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
        if (window._updateQueueBadge) window._updateQueueBadge();
        syncSearchHi();
        _schedulePersistGuiQueueState();
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
            if (window._updateQueueBadge) window._updateQueueBadge();
            syncSearchHi();
            _schedulePersistGuiQueueState();
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
        _schedulePersistGuiQueueState();
      }
    });

    btnText.addEventListener("click", () => {
      if (!_textMode) {
        _setMode(false);
        document.getElementById("dl-urls").value = _urlQueue
          .map((q) => q.url)
          .join("\n");
        _schedulePersistGuiQueueState();
      }
    });

    // Keep badge + search highlights in sync when user edits URLs in text mode
    document.getElementById("dl-urls").addEventListener("input", () => {
      if (window._updateQueueBadge) window._updateQueueBadge();
      if (_textMode) syncSearchHi();
      _schedulePersistGuiQueueState();
    });
  }

    return {
      urlQueue: _urlQueue,
      get textMode() {
        return _textMode;
      },
      initUrlQueue,
      refreshAlbumQueueCardMetas: _refreshAlbumQueueCardMetas,
      queuedUrlSetForSearchHighlight: _queuedUrlSetForSearchHighlight,
      calcTrackTotalFromQueue: _calcTrackTotalFromQueue,
      calcProgressDenominatorFromQueue: _calcProgressDenominatorFromQueue,
      progressBarDenominatorFromQueueItem: _progressBarDenominatorFromQueueItem,
      remainingTracksContributionFromQueueItem: _remainingTracksContributionFromQueueItem,
      albumQueueItemNeedsToStayVisible: _albumQueueItemNeedsToStayVisible,
      addUrlToQueue: _addUrlToQueue,
      removeFromQueueByUrl: _removeFromQueueByUrl,
      removeFromQueue: _removeFromQueue,
      restoreFromServer: _restoreGuiQueueFromServer,
      countHistoryDownloadedForRelease: _countHistoryDownloadedForRelease,
    };
  }

  qroot.internals = qroot.internals || {};
  qroot.internals.bootstrap = bootstrap;
})();
