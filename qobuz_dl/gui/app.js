/* ============================================================
   Qobuz-DL GUI | Frontend Logic
   ============================================================ */

(function () {
  "use strict";

  const api = window.QobuzGui && window.QobuzGui.api;
  const QG = window.QobuzGui;
  const _cgConst = QG.core.constants;
  const _GUI_PENDING_AUDIO_PREFIX = _cgConst.GUI_PENDING_AUDIO_PREFIX;
  const _TS_VIRT_THRESHOLD = _cgConst.TS_VIRT_THRESHOLD;
  const _TS_VIRT_OVERSCAN = _cgConst.TS_VIRT_OVERSCAN;
  const _ic = QG.core.icons;
  const _TRACK_DL_ICON_SVG = _ic.trackDlIconSvg;
  const _TRACK_SEARCH_ICON_SVG = _ic.trackSearchIconSvg;
  const _TRACK_MISSING_NOTE_ICON_SVG = _ic.trackMissingNoteIconSvg;
  const _MISSING_PLACEHOLDER_BTN_TIP = _ic.missingPlaceholderBtnTip;
  const _TRACK_FOLDER_ICON_SVG = _ic.trackFolderIconSvg;
  const _LYRIC_SEARCH_ATTACHED_SVG = _ic.lyricSearchAttachedSvg;
  const _TRACK_DL_FAIL_SVG = _ic.trackDlFailSvg;
  const _EXPLICIT_BADGE_SVG = _ic.explicitBadgeSvg;

  function _lyricOut() {
    return QG.features.lyrics.lyricOutputSettings;
  }

  function _syncSearchQueuedHighlights() {
    if (QG.features.search && QG.features.search.syncQueuedHighlights) {
      QG.features.search.syncQueuedHighlights();
    }
  }

  let _queueHost = null;

  let _sse = null;
  let _trackStatusMap = new Map();
  let _tsVirtActive = false;
  let _tsVirtInnerEl = null;
  let _tsVirtRowH = 50;
  let _tsVirtScrollHandlerBound = null;
  let _tsVirtScrollRaf = 0;
  let _tsVirtResizeObs = null;
  /** Visible row keys (filtered for virtualized list); mirrors `_tsOrderAll` when not virtual or when showing all. */
  let _tsOrder = [];
  /** Full row keys oldest → newest (unfiltered). */
  let _tsOrderAll = [];
  let _tsKeyToIndex = new Map();
  /** Serialized row for mounting/evicting virtual items (API shape + session results). */
  let _tsDbItemByKey = new Map();
  let _tsActiveDlKeys = new Set();
  /** audio_path → lyric_album (avoids scanning hundreds of DOM nodes). */
  let _tsAudioPathAlbum = new Map();
  /** `"all"` | `"errors"`, error view shows purchase-only, failed, pending slots, lyric errors. */
  let _tsHistoryFilterMode = "all";
  /** Skip redundant filter passes while bulk-loading history from DB. */
  let _tsSkipHistoryFilterApply = false;

  function startSSE() {
    if (_sse) return;
    _sse = new EventSource("/api/stream");

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

  function _scrollContainerAtBottom(el, slackPx) {
    return QG.core.dom.scrollContainerAtBottom(el, slackPx);
  }

  function _normalizeTrackNo(trackNo) {
    return QG.core.trackIdentity.normalizeTrackNo(trackNo);
  }

  function _normalizeTrackTitle(title) {
    return QG.core.trackIdentity.normalizeTrackTitle(title);
  }

  /** Title for the LRCLIB search field when opening from a download-history row. */
  function _lyricSearchTitleFromDisplay(displayTitle) {
    return String(displayTitle || "").trim();
  }

  function _parseTrackRef(trackNo, title) {
    return QG.core.trackIdentity.parseTrackRef(trackNo, title);
  }

  function _trackKey(trackNo, title, lyricAlbum) {
    return QG.core.trackIdentity.trackKey(trackNo, title, lyricAlbum);
  }

  /**
   * `num + normalized-title` ignoring album suffix. Used while a row might be keyed
   * with or without lyric_album (short TRACK_START vs hydrate) so transient error
   * classification matches parallel / multi-queue downloads.
   */
  function _trackKeyStem(fullKey) {
    return QG.core.trackIdentity.trackKeyStem(fullKey);
  }

  function _tsMountedCardShowsDlTerminal(card) {
    if (!card) return false;
    return Boolean(
      card.querySelector("a.download-chip.purchase-only") ||
        card.querySelector("button.download-chip.track-dl-btn--failed"),
    );
  }

  /**
   * One pass over `_tsActiveDlKeys` / mounted rows to classify history keys for Error tab churn.
   * `unsettledStems`: download active or lyric refetch (`loading`), row outcome not final for UI yet.
   * `dlTerminalErrStems`: a mounted row for that stem shows purchase-only / download-failed chip.
   * Stale hydrate `.lyrics-chip.error` alone must NOT qualify during unsettled work (fixes flicker).
   */
  function _tsComputeErrorStemContext() {
    const unsettledStems = new Set();
    const dlTerminalErrStems = new Set();
    for (const k of _tsActiveDlKeys) {
      const st = _trackKeyStem(k);
      if (st) unsettledStems.add(st);
    }
    for (const k of _trackStatusMap.keys()) {
      const card = _trackStatusMap.get(k);
      if (!card) continue;
      const st = _trackKeyStem(k);
      if (!st) continue;
      if (card.querySelector(".lyrics-chip.loading")) unsettledStems.add(st);
      const dlBtn = card.querySelector(
        "button.download-chip.track-dl-btn.track-dl-btn--active",
      );
      if (dlBtn) unsettledStems.add(st);
      if (_tsMountedCardShowsDlTerminal(card)) dlTerminalErrStems.add(st);
    }
    return { unsettledStems, dlTerminalErrStems };
  }

  function _tsRegisterAudioPathAlbum(audioPath, lyricAlbum) {
    const p = String(audioPath || "").trim();
    if (!p) return;
    _tsAudioPathAlbum.set(p, String(lyricAlbum || "").trim());
  }

  function _tsRebuildKeyIndex() {
    _tsKeyToIndex.clear();
    for (let i = 0; i < _tsOrder.length; i++) {
      _tsKeyToIndex.set(_tsOrder[i], i);
    }
  }

  /** Download / purchase placeholders only (excludes lyric sidecar failures). */
  function _tsDbDownloadOutcomeError(it) {
    if (!it) return false;
    const st = String(it.download_status || "").toLowerCase();
    if (st === "purchase_only" || st === "failed") return true;
    const ap = String(it.audio_path || "").trim();
    return ap.startsWith(_GUI_PENDING_AUDIO_PREFIX);
  }

  function _tsDbItemIsError(it) {
    if (_tsDbDownloadOutcomeError(it)) return true;
    const lt = String(it.lyric_type || "").toLowerCase();
    return lt === "error";
  }

  function _tsCardLooksLikeError(card) {
    if (!card) return false;
    if (_tsMountedCardShowsDlTerminal(card)) return true;
    if (card.querySelector(".lyrics-chip.error")) return true;
    return false;
  }

  function _tsKeyIsErrorInCurrentSession(key, stemCtx /* optional result of _tsComputeErrorStemContext */) {
    const ctx = stemCtx || _tsComputeErrorStemContext();
    const stem = key ? _trackKeyStem(key) : "";
    if (stem && ctx.unsettledStems.has(stem)) {
      return ctx.dlTerminalErrStems.has(stem);
    }
    const card = key ? _trackStatusMap.get(key) : null;
    const dlGlobally =
      typeof window !== "undefined" && Boolean(window.isDownloading);
    if (dlGlobally) {
      if (_tsDbDownloadOutcomeError(_tsDbItemByKey.get(key))) return true;
      if (_tsMountedCardShowsDlTerminal(card)) return true;
      return false;
    }
    if (_tsDbItemIsError(_tsDbItemByKey.get(key))) return true;
    return _tsCardLooksLikeError(card);
  }

  function _tsUpdateErrorHistoryCountBadge(optStemCtx) {
    const badge = document.getElementById("dl-history-errors-count");
    if (!badge) return;
    const stemCtx = optStemCtx != null ? optStemCtx : _tsComputeErrorStemContext();
    let n = 0;
    for (let i = 0; i < _tsOrderAll.length; i++) {
      if (_tsKeyIsErrorInCurrentSession(_tsOrderAll[i], stemCtx)) n++;
    }
    if (n === 0) {
      badge.classList.add("hidden");
      badge.textContent = "";
      badge.removeAttribute("aria-label");
    } else {
      badge.classList.remove("hidden");
      badge.textContent = String(n);
      badge.setAttribute(
        "aria-label",
        `${n} error entr${n === 1 ? "y" : "ies"} in download history`,
      );
    }
  }

  function _tsApplyHistoryFilter() {
    if (_tsSkipHistoryFilterApply) return;
    const stemCtx = _tsComputeErrorStemContext();
    const list = document.getElementById("dl-track-status");
    if (_tsVirtActive && _tsVirtInnerEl && list) {
      if (_tsHistoryFilterMode === "errors") {
        _tsOrder = _tsOrderAll.filter((k) =>
          _tsKeyIsErrorInCurrentSession(k, stemCtx),
        );
      } else {
        _tsOrder = _tsOrderAll.slice();
      }
      _tsRebuildKeyIndex();
      const allowed = new Set(_tsOrder);
      for (const [k, card] of [..._trackStatusMap]) {
        if (!allowed.has(k)) {
          card.remove();
          _trackStatusMap.delete(k);
        }
      }
      _tsUpdateVirtInnerHeight();
      requestAnimationFrame(() => {
        _tsVirtMeasureRowH();
        _tsVirtOnScroll();
      });
    } else {
      _tsOrder = _tsOrderAll.slice();
      _tsRebuildKeyIndex();
      if (list && _trackStatusMap.size > 0) {
        for (let i = 0; i < _tsOrderAll.length; i++) {
          const k = _tsOrderAll[i];
          const card = _trackStatusMap.get(k);
          if (!card) continue;
          const show =
            _tsHistoryFilterMode !== "errors" ||
            _tsKeyIsErrorInCurrentSession(k, stemCtx);
          card.classList.toggle("hidden", !show);
          card.setAttribute("aria-hidden", show ? "false" : "true");
        }
      }
    }
    _tsUpdateErrorHistoryCountBadge(stemCtx);
  }

  function _initDownloadHistorySegment() {
    const allBtn = document.getElementById("dl-history-tab-all");
    const errBtn = document.getElementById("dl-history-tab-errors");
    const list = document.getElementById("dl-track-status");
    if (!allBtn || !errBtn) return;
    const applyMode = (mode) => {
      _tsHistoryFilterMode = mode;
      const allOn = mode === "all";
      allBtn.classList.toggle("is-active", allOn);
      errBtn.classList.toggle("is-active", !allOn);
      allBtn.setAttribute("aria-selected", allOn ? "true" : "false");
      errBtn.setAttribute("aria-selected", allOn ? "false" : "true");
      allBtn.tabIndex = allOn ? 0 : -1;
      errBtn.tabIndex = allOn ? -1 : 0;
      _tsApplyHistoryFilter();
      if (list) list.scrollTop = 0;
    };
    allBtn.addEventListener("click", () => applyMode("all"));
    errBtn.addEventListener("click", () => applyMode("errors"));
  }

  function _tsAppendParent(list) {
    if (_tsVirtActive && _tsVirtInnerEl) return _tsVirtInnerEl;
    return list;
  }

  function _tsTeardownVirtScroller() {
    const list = document.getElementById("dl-track-status");
    if (_tsVirtResizeObs) {
      try {
        if (list) _tsVirtResizeObs.unobserve(list);
      } catch (_) {
        /* ignore */
      }
      try {
        _tsVirtResizeObs.disconnect();
      } catch (_) {
        /* ignore */
      }
      _tsVirtResizeObs = null;
    }
    if (list && _tsVirtScrollHandlerBound) {
      list.removeEventListener("scroll", _tsVirtScrollHandlerBound);
      window.removeEventListener("resize", _tsVirtScrollHandlerBound);
    }
    _tsVirtScrollHandlerBound = null;
    _tsVirtInnerEl = null;
    _tsVirtActive = false;
    if (_tsVirtScrollRaf) {
      cancelAnimationFrame(_tsVirtScrollRaf);
      _tsVirtScrollRaf = 0;
    }
  }

  function _tsEnsureVirtInner(list) {
    const inner = document.createElement("div");
    inner.id = "ts-virt-inner";
    inner.className = "track-status-virt-inner";
    list.appendChild(inner);
    _tsVirtInnerEl = inner;
  }

  function _tsUpdateVirtInnerHeight() {
    if (!_tsVirtInnerEl) return;
    _tsVirtInnerEl.style.minHeight = `${Math.max(0, _tsOrder.length) * _tsVirtRowH}px`;
  }

  function _tsPositionVirtCard(card, index) {
    if (!card || !_tsVirtActive) return;
    card.classList.add("track-status-card--virt");
    card.style.top = `${index * _tsVirtRowH}px`;
    card.style.minHeight = "";
  }

  function _tsVirtPinnedIndices(n) {
    const out = new Set();
    for (const k of _tsActiveDlKeys) {
      const i = _tsKeyToIndex.get(k);
      if (i !== undefined && i >= 0 && i < n) out.add(i);
    }
    document
      .querySelectorAll("#dl-track-status .lyric-search-anchor")
      .forEach((c) => {
        const k = c.dataset.trackKey;
        if (!k) return;
        const i = _tsKeyToIndex.get(k);
        if (i !== undefined && i >= 0 && i < n) out.add(i);
      });
    return out;
  }

  function _tsVirtMeasureRowH() {
    if (!_tsVirtInnerEl) return;
    const card = _tsVirtInnerEl.querySelector(".track-status-card");
    if (!card) return;
    const r = card.getBoundingClientRect();
    const cs = window.getComputedStyle(card);
    const mb = parseFloat(cs.marginBottom) || 0;
    if (r.height > 0) _tsVirtRowH = Math.max(48, Math.ceil(r.height + mb));
    _tsUpdateVirtInnerHeight();
  }

  function _tsVirtOnScroll() {
    if (!_tsVirtActive || !_tsVirtInnerEl) return;
    if (_tsVirtScrollRaf) return;
    _tsVirtScrollRaf = requestAnimationFrame(() => {
      _tsVirtScrollRaf = 0;
      _tsVirtRender();
    });
  }

  function _tsVirtRender() {
    if (!_tsVirtActive || !_tsVirtInnerEl) return;
    const list = document.getElementById("dl-track-status");
    if (!list) return;
    const n = _tsOrder.length;
    const H = _tsVirtRowH;
    _tsVirtInnerEl.style.minHeight = `${Math.max(0, n) * H}px`;
    if (n === 0) return;

    const st = list.scrollTop;
    const ch = list.clientHeight || 1;
    let start = Math.floor(st / H) - _TS_VIRT_OVERSCAN;
    let end = Math.ceil((st + ch) / H) + _TS_VIRT_OVERSCAN;
    start = Math.max(0, start);
    end = Math.min(n, end);

    const want = new Set();
    for (let i = start; i < end; i++) want.add(i);
    for (const ii of _tsVirtPinnedIndices(n)) want.add(ii);

    for (const [k, card] of [..._trackStatusMap]) {
      const idx = _tsKeyToIndex.get(k);
      if (idx === undefined) continue;
      if (!want.has(idx)) {
        card.remove();
        _trackStatusMap.delete(k);
      }
    }

    const sorted = [...want].sort((a, b) => a - b);
    for (let j = 0; j < sorted.length; j++) {
      const i = sorted[j];
      const k = _tsOrder[i];
      if (!k || _trackStatusMap.has(k)) continue;
      const it = _tsDbItemByKey.get(k);
      if (!it) continue;
      _tsMountDbItemAtIndex(it, i);
    }

    for (const [k, card] of _trackStatusMap) {
      const idx = _tsKeyToIndex.get(k);
      if (idx !== undefined) _tsPositionVirtCard(card, idx);
    }
  }

  function _tsApplyHistoryDbItemToCard(card, it) {
    const alb = (it.lyric_album || "").trim();
    if (it.lyric_artist) {
      card.dataset.lyricArtist = String(it.lyric_artist);
    }
    if (alb) card.dataset.lyricAlbum = alb;
    if (it.duration_sec) {
      card.dataset.durationSec = String(parseInt(it.duration_sec, 10) || 0);
    }
    if (it.audio_path) {
      const rawAp = String(it.audio_path || "").trim();
      if (rawAp && !rawAp.startsWith(_GUI_PENDING_AUDIO_PREFIX)) {
        card.dataset.audioPath = rawAp;
        _tsRegisterAudioPathAlbum(rawAp, alb);
        if (rawAp.toLowerCase().endsWith(".missing.txt")) {
          card.dataset.resolvedBy = "placeholder";
        } else if ((it.attach_search_eligible === true || it.attach_search_eligible === 1) && 
                   String(it.download_status || "").toLowerCase() === "downloaded") {
          card.dataset.resolvedBy = "search";
        }
      }
    }
    if (it.track_explicit === true || it.track_explicit === false) {
      card.dataset.trackExplicit = it.track_explicit ? "1" : "0";
      _setTrackContentRatingBadge(card, it.track_explicit);
    }
    if ((it.slot_track_id || "").trim()) {
      card.dataset.slotTrackId = String(it.slot_track_id).trim();
    }
    if ((it.release_album_id || "").trim()) {
      card.dataset.releaseAlbumId = String(it.release_album_id).trim();
    }
    if (it.attach_search_eligible === true || it.attach_search_eligible === 1) {
      card.dataset.attachSearchEligible = "1";
    } else {
      delete card.dataset.attachSearchEligible;
    }
    const st = String(it.download_status || "downloaded").toLowerCase();
    const detail = String(it.download_detail || "").trim();
    const isFailed = st === "failed";
    const isPurchase = st === "purchase_only";
    if (isPurchase && detail) {
      _setTrackDownloadChip(
        it.track_no,
        it.title,
        "Album Purchase Only",
        "failed",
        {
          href: detail,
          titleAttr:
            "Open album on Qobuz to purchase (full album required for these tracks)",
          slotTrackId: String(it.slot_track_id || "").trim(),
          releaseAlbumId: String(it.release_album_id || "").trim(),
        },
        alb,
      );
    } else {
      _setTrackDownloadChip(
        it.track_no,
        it.title,
        isFailed ? "failed" : "downloaded",
        isFailed ? "failed" : "done",
        undefined,
        alb,
      );
    }
    if (it.lyric_type && String(it.lyric_type).toLowerCase() !== "loading") {
      _setTrackLyricsChip(
        it.track_no,
        it.title,
        it.lyric_type,
        it.lyric_confidence || null,
        alb,
        it.lyric_provider || "",
        it.lyric_destination || "",
      );
    }
  }

  function _tsMountDbItemAtIndex(it, index) {
    if (!_tsVirtInnerEl) return;
    const alb = (it.lyric_album || "").trim();
    const { card, key } = _buildTrackStatusCardEl(
      it.track_no || "",
      it.title || "",
      alb,
      it.cover_url || "",
    );
    _trackStatusMap.set(key, card);
    _tsVirtInnerEl.appendChild(card);
    _tsApplyHistoryDbItemToCard(card, it);
    _tsPositionVirtCard(card, index);
  }

  function _tsApplyHistoryDbItemToNewCard(it) {
    const alb = (it.lyric_album || "").trim();
    const card = _ensureTrackStatusCard(
      it.track_no || "",
      it.title || "",
      true,
      it.cover_url || "",
      alb,
    );
    if (!card) return;
    _tsApplyHistoryDbItemToCard(card, it);
  }

  function _tsStoreDbItemFromTrackResult(ev, resAlb, card) {
    const tk = (card && card.dataset.trackKey) || "";
    if (!tk) return;
    const tEl = card.querySelector(".track-status-title");
    const st = String(ev.status || "").toLowerCase();
    const isFailed = st === "failed";
    const isPurchase = st === "purchase_only";
    const detail = String(ev.detail || "").trim();
    const img = card.querySelector(".track-status-art-img");
    const it = {
      track_no: String(ev.track_no || ""),
      title: (tEl && tEl.textContent) || String(ev.title || ""),
      lyric_album: resAlb || "",
      cover_url: (img && img.getAttribute("src")) || "",
      lyric_artist: (card.dataset.lyricArtist || "").trim(),
      duration_sec: parseInt(card.dataset.durationSec || "0", 10) || 0,
      audio_path: (card.dataset.audioPath || "").trim(),
      track_explicit:
        card.dataset.trackExplicit === "1"
          ? true
          : card.dataset.trackExplicit === "0"
            ? false
            : null,
      download_status: isPurchase ? "purchase_only" : isFailed ? "failed" : "downloaded",
      download_detail: detail,
      slot_track_id: String(ev.slot_track_id || "").trim(),
      release_album_id: String(ev.release_album_id || "").trim(),
      lyric_type: "",
      lyric_provider: "",
      lyric_confidence: "",
      lyric_destination: "",
      attach_search_eligible: card.dataset.attachSearchEligible === "1",
    };
    const chip = card.querySelector(".lyrics-chip");
    if (chip) {
      const parts = (chip.className || "").split(/\s+/);
      const lt = parts.find((c) =>
        ["synced", "plain", "none", "error", "instrumental"].includes(c),
      );
      if (lt) it.lyric_type = lt;
      it.lyric_destination = _normalizeLyricDestination(
        chip.dataset.lyricDestination || "",
      );
    }
    _tsDbItemByKey.set(tk, it);
    const apStore = (card.dataset.audioPath || "").trim();
    if (apStore && !apStore.startsWith(_GUI_PENDING_AUDIO_PREFIX)) {
      _tsRegisterAudioPathAlbum(apStore, (it.lyric_album || "").trim());
    }
  }

  function _lyricAlbumForTrackEv(ev) {
    const apEv = String(ev.audio_path || "").trim();
    if (apEv && _tsAudioPathAlbum.has(apEv)) {
      return _tsAudioPathAlbum.get(apEv) || "";
    }
    let a =
      ev.lyric_album != null && String(ev.lyric_album).trim() !== ""
        ? String(ev.lyric_album).trim()
        : "";
    if (a) return a;
    const wantN = _normalizeTrackNo(ev.track_no);
    const wantT = _normalizeTrackTitle(ev.title || "");
    const cards = document.querySelectorAll("#dl-track-status .track-status-card");
    for (let i = 0; i < cards.length; i++) {
      const c = cards[i];
      if (_normalizeTrackNo(c.dataset.trackNo) !== wantN) continue;
      const tEl = c.querySelector(".track-status-title");
      const ct = _normalizeTrackTitle((tEl && tEl.textContent) || "");
      if (ct !== wantT) continue;
      const da = (c.dataset.lyricAlbum || "").trim();
      if (da) return da;
    }
    return "";
  }

  function _setTrackCardCover(card, coverUrl) {
    const url = String(coverUrl || "").trim();
    if (!url || !card) return;
    let art = card.querySelector(".track-status-art");
    if (!art) return;
    let img = art.querySelector(".track-status-art-img");
    if (!img) {
      img = document.createElement("img");
      img.className = "track-status-art-img";
      img.alt = "";
      art.appendChild(img);
    }
    art.classList.remove("track-status-art--empty");
    img.referrerPolicy = "no-referrer";
    img.decoding = "async";
    img.loading = "lazy";
    img.onerror = () => {
      img.remove();
      art.classList.add("track-status-art--empty");
    };
    img.src = url;
  }

  function _buildTrackStatusCardEl(trackNo, title, lyricAlbum, coverUrl) {
    const parsed = _parseTrackRef(trackNo, title);
    const alb =
      lyricAlbum != null && String(lyricAlbum).trim() !== ""
        ? String(lyricAlbum).trim()
        : "";
    const key = _trackKey(parsed.trackNo, parsed.title, alb);
    const card = document.createElement("div");
    card.className = "track-status-card";
    card.dataset.trackKey = key;
    card.dataset.trackNo = _normalizeTrackNo(parsed.trackNo);
    card.dataset.trackTitle = _normalizeTrackTitle(parsed.title);
    if (alb) card.dataset.lyricAlbum = alb;
    card.innerHTML = `
      <div class="track-status-art track-status-art--empty"></div>
      <div class="track-status-main">
        <span class="track-status-title"></span>
        <div class="track-status-meta-row">
          <span class="track-status-sub"></span>
          <span class="track-content-rating" aria-hidden="true"></span>
        </div>
      </div>
      <div class="track-status-tags"></div>
    `;
    card.querySelector(".track-status-title").textContent =
      parsed.title || "Track";
    card.querySelector(".track-status-sub").textContent = `#${parsed.trackNo || "?"}`;
    if (coverUrl) _setTrackCardCover(card, coverUrl);
    return { card, key, parsed, alb };
  }

  function _ensureTrackStatusCard(
    trackNo,
    title,
    createNew = false,
    coverUrl,
    lyricAlbum,
  ) {
    const list = document.getElementById("dl-track-status");
    if (!list) return null;
    const parsed = _parseTrackRef(trackNo, title);
    const alb =
      lyricAlbum != null && String(lyricAlbum).trim() !== ""
        ? String(lyricAlbum).trim()
        : "";
    const key = _trackKey(parsed.trackNo, parsed.title, alb);
    if (key && _trackStatusMap.has(key)) {
      const existing = _trackStatusMap.get(key);
      if (coverUrl) _setTrackCardCover(existing, coverUrl);
      if (alb) existing.dataset.lyricAlbum = alb;
      return existing;
    }
    if (!createNew && !key) return null;

    const { card } = _buildTrackStatusCardEl(trackNo, title, lyricAlbum, coverUrl);
    const stickToBottom = _scrollContainerAtBottom(list);
    const parent = _tsAppendParent(list);
    parent.appendChild(card);
    if (key) {
      const isNewRow = !_trackStatusMap.has(key);
      if (isNewRow && !_tsOrderAll.includes(key)) {
        _tsOrderAll.push(key);
      }
      _trackStatusMap.set(key, card);
      if (!_tsSkipHistoryFilterApply && isNewRow) {
        _tsApplyHistoryFilter();
      }
      if (_tsVirtActive && _tsVirtInnerEl) {
        const idx = _tsKeyToIndex.get(key);
        if (idx !== undefined) _tsPositionVirtCard(card, idx);
        _tsUpdateVirtInnerHeight();
        requestAnimationFrame(() => {
          _tsVirtMeasureRowH();
          _tsVirtOnScroll();
        });
      }
    }
    if (stickToBottom) list.scrollTop = list.scrollHeight;
    return card;
  }

  function _setTrackContentRatingBadge(card, trackExplicitKnown) {
    if (!card) return;
    const el = card.querySelector(".track-content-rating");
    if (!el) return;
    if (trackExplicitKnown === true) {
      el.innerHTML = `<span class="track-explicit-badge explicit-tag-badge" data-tip="Marked explicit on Qobuz">${_EXPLICIT_BADGE_SVG}</span>`;
      el.className = "track-content-rating track-content-rating--explicit";
    } else if (trackExplicitKnown === false) {
      el.innerHTML = "";
      el.className = "track-content-rating";
    } else {
      el.innerHTML = "";
      el.className = "track-content-rating";
    }
  }

  let _attachTrackAnchorCard = null;

  function _formatAttachDur(sec) {
    return QG.core.format.formatAttachDur(sec);
  }

  function _attachNormTokens(s) {
    return String(s || "")
      .toLowerCase()
      .replace(/[^a-z0-9\s]+/gi, " ")
      .split(/\s+/)
      .filter(Boolean);
  }

  function _attachDurationDeltaLabel(anchorSec, candSec) {
    const ref = parseInt(String(anchorSec || 0), 10);
    const dur = parseInt(String(candSec || 0), 10);
    if (
      !Number.isFinite(ref) ||
      !Number.isFinite(dur) ||
      ref <= 0 ||
      dur <= 0
    ) {
      return "";
    }
    const delta = dur - ref;
    if (delta === 0) return "";
    return _formatLyricDeltaSec(delta);
  }

  /** Match ``normalize_sampling_rate_hz`` in Python (Hz/kHz/MHz-ish API quirks). */
  function _normalizeSamplingRateHz(raw) {
    return QG.core.format.normalizeSamplingRateHz(raw);
  }

  function _attachQualitySpecsTooltip(t) {
    const bd = parseInt(String(t.maximum_bit_depth || ""), 10);
    let srHz = _normalizeSamplingRateHz(t.maximum_sampling_rate);
    if (!Number.isFinite(bd) || bd <= 0) {
      return "";
    }
    if (srHz == null || !Number.isFinite(srHz) || srHz <= 0) {
      return "";
    }
    const khz = srHz / 1000;
    const kStr = Number.isInteger(khz)
      ? String(khz)
      : khz.toFixed(4).replace(/\.?0+$/, "");
    return `${bd}-bit / ${kStr} kHz`;
  }

  function _createAttachQualityBadge(t) {
    const tier = String(t.quality_tier || "LOSSLESS").toUpperCase();
    const specs = _attachQualitySpecsTooltip(t);
    const tipHires =
      "Hi-Res lossless on Qobuz, above CD quality; up to 24-bit / 192 kHz.";
    const tipLossless =
      "CD-quality lossless on Qobuz, 16-bit / 44.1 kHz FLAC.";
    const tipMp3 = "Lossy stream (e.g. ~320 kbps), not lossless.";
    const tipSuffix = specs ? `\n${specs} (catalog max)` : "";

    const badge = document.createElement("span");
    badge.className = "result-badge attach-track-quality-badge";
    badge.removeAttribute("title");

    if (tier === "HI-RES") {
      badge.classList.add("badge-hires");
      badge.setAttribute("data-tip", tipHires + tipSuffix);
      const icon = document.createElement("img");
      icon.src = "/gui/hi-res.jpg";
      icon.className = "quality-icon";
      icon.alt = "";
      badge.appendChild(icon);
      return badge;
    }
    if (tier === "MP3") {
      badge.classList.add("badge-mp3");
      badge.textContent = "MP3";
      badge.setAttribute("data-tip", tipMp3 + tipSuffix);
      return badge;
    }
    badge.classList.add("badge-lossless");
    badge.setAttribute("data-tip", tipLossless + tipSuffix);
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 32 32");
    svg.setAttribute("class", "quality-icon");
    svg.innerHTML =
      `<path d="M16 22.7368C17.8785 22.7368 19.471 22.0837 20.7773 20.7773C22.0837 19.471 22.7368 17.8785 22.7368 16C22.7368 14.1215 22.0837 12.529 20.7773 11.2227C19.471 9.91635 17.8785 9.26318 16 9.26318C14.1215 9.26318 12.529 9.91635 11.2227 11.2227C9.91635 12.529 9.26318 14.1215 9.26318 16C9.26318 17.8785 9.91635 19.471 11.2227 20.7773C12.529 22.0837 14.1215 22.7368 16 22.7368ZM16 17.6842C15.5228 17.6842 15.1228 17.5228 14.8 17.2C14.4772 16.8772 14.3158 16.4772 14.3158 16C14.3158 15.5228 14.4772 15.1228 14.8 14.8C15.1228 14.4772 15.5228 14.3158 16 14.3158C16.4772 14.3158 16.8772 14.4772 17.2 14.8C17.5228 15.1228 17.6842 15.5228 17.6842 16C17.6842 16.4772 17.5228 16.8772 17.2 17.2C16.8772 17.5228 16.4772 17.6842 16 17.6842ZM16.0028 32C13.7899 32 11.7098 31.5801 9.76264 30.7402C7.81543 29.9003 6.12164 28.7606 4.68128 27.3208C3.24088 25.8811 2.10057 24.188 1.26034 22.2417C0.420114 20.2954 0 18.2158 0 16.0028C0 13.7899 0.419931 11.7098 1.25979 9.76264C2.09965 7.81543 3.23945 6.12165 4.67917 4.68128C6.11892 3.24088 7.81196 2.10057 9.7583 1.26034C11.7046 0.420115 13.7842 0 15.9972 0C18.2101 0 20.2902 0.419933 22.2374 1.25979C24.1846 2.09966 25.8784 3.23945 27.3187 4.67917C28.7591 6.11892 29.8994 7.81197 30.7397 9.7583C31.5799 11.7046 32 13.7842 32 15.9972C32 18.2101 31.5801 20.2902 30.7402 22.2374C29.9003 24.1846 28.7606 25.8784 27.3208 27.3187C25.8811 28.7591 24.188 29.8994 22.2417 30.7397C20.2954 31.5799 18.2158 32 16.0028 32ZM16 29.4737C19.7614 29.4737 22.9474 28.1685 25.5579 25.5579C28.1685 22.9474 29.4737 19.7614 29.4737 16C29.4737 12.2386 28.1685 9.05261 25.5579 6.44208C22.9474 3.83155 19.7614 2.52628 16 2.52628C12.2386 2.52628 9.05261 3.83155 6.44208 6.44208C3.83155 9.05261 2.52628 12.2386 2.52628 16C2.52628 19.7614 3.83155 22.9474 6.44208 25.5579C9.05261 28.1685 12.2386 29.4737 16 29.4737Z" fill="white"></path>`;
    badge.appendChild(svg);
    return badge;
  }

  function _attachTrackMatchPct(anchorTitle, anchorArtist, candTitle, candArtist) {
    const a = new Set([
      ..._attachNormTokens(anchorTitle),
      ..._attachNormTokens(anchorArtist),
    ]);
    const b = new Set([
      ..._attachNormTokens(candTitle),
      ..._attachNormTokens(candArtist),
    ]);
    if (!a.size || !b.size) return 0;
    let inter = 0;
    for (const x of b) {
      if (a.has(x)) inter += 1;
    }
    return Math.round((100 * (2 * inter)) / (a.size + b.size));
  }

  function _createAttachTrackSearchRow(t, matchPct, anchorDurSec, onAttach) {
    const div = document.createElement("div");
    div.className = "lyric-search-row";
    div.setAttribute("role", "option");

    const line1 = document.createElement("div");
    line1.className =
      "lyric-search-row-line lyric-search-row-line--title";

    const tSpan = document.createElement("span");
    tSpan.className = "lyric-search-track";
    tSpan.textContent = String(t.title || "");

    line1.appendChild(tSpan);

    if (Number.isFinite(matchPct) && matchPct > 0) {
      const mp = document.createElement("span");
      mp.className = "attach-track-match-pct";
      mp.textContent = `${matchPct}%`;
      mp.setAttribute(
        "aria-label",
        `Approximate title and artist overlap: ${matchPct} percent`,
      );
      line1.appendChild(mp);
    }

    if (t.explicit) {
      const ex = document.createElement("span");
      ex.className =
        "lyric-search-rating lyric-search-rating--explicit explicit-tag-badge";
      ex.innerHTML = _EXPLICIT_BADGE_SVG;
      line1.appendChild(ex);
    } else {
      const cl = document.createElement("span");
      cl.className = "lyric-search-rating lyric-search-rating--clean";
      cl.textContent = "clean";
      line1.appendChild(cl);
    }

    const deltaStr = _attachDurationDeltaLabel(anchorDurSec, t.duration_sec);
    if (deltaStr) {
      const d = document.createElement("span");
      d.className = "lyric-search-delta";
      d.textContent = deltaStr;
      d.setAttribute(
        "aria-label",
        "Candidate duration vs album slot track: " + deltaStr + " (mm:ss)",
      );
      line1.appendChild(d);
    }

    const line2 = document.createElement("div");
    line2.className =
      "lyric-search-row-line lyric-search-row-line--album";
    const albumEl = document.createElement("span");
    albumEl.className = "lyric-search-album";
    albumEl.textContent =
      String(t.album_title || "").trim() || "\u2014";
    line2.appendChild(albumEl);
    const qBadge = _createAttachQualityBadge(t);
    if (qBadge) {
      line2.appendChild(document.createTextNode(" · "));
      line2.appendChild(qBadge);
    }
    const durStr = t.duration_sec ? _formatAttachDur(t.duration_sec) : "";
    if (durStr) {
      line2.appendChild(document.createTextNode(" · "));
      const du = document.createElement("span");
      du.className = "attach-track-inline-dur";
      du.textContent = durStr;
      line2.appendChild(du);
    }

    const line3 = document.createElement("div");
    line3.className =
      "lyric-search-row-line lyric-search-row-line--footer";

    const artistSpan = document.createElement("span");
    artistSpan.className = "lyric-search-artist";
    artistSpan.textContent =
      String(t.artist || "").trim() || "\u2014";

    const actions = document.createElement("div");
    actions.className = "lyric-search-row-actions";

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn-primary btn-sm";
    saveBtn.textContent = "Attach";
    saveBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (saveBtn.disabled) return;
      void onAttach(saveBtn);
    });

    line3.appendChild(artistSpan);
    line3.appendChild(actions);
    actions.appendChild(saveBtn);

    div.appendChild(line1);
    div.appendChild(line2);
    div.appendChild(line3);
    return div;
  }

  function _closeAttachTrackPopover() {
    _attachTrackAnchorCard = null;
    _clearLyricSearchAnchorHighlight();
    const pop = document.getElementById("attach-track-popover");
    if (!pop) return;
    pop.classList.add("hidden");
    pop.setAttribute("aria-hidden", "true");
  }

  function _openAttachTrackPopover(card) {
    const sid = ((card && card.dataset && card.dataset.slotTrackId) || "").trim();
    if (!sid || !card) return;
    _closeLyricSearchModal();
    _attachTrackAnchorCard = card;
    _setLyricSearchAnchorCard(card);
    const pop = document.getElementById("attach-track-popover");
    const ti = document.getElementById("attach-track-title");
    const ar = document.getElementById("attach-track-artist");
    const statusEl = document.getElementById("attach-track-status");
    const resultsEl = document.getElementById("attach-track-results");
    if (!pop || !ti || !ar || !resultsEl) return;
    if (statusEl) {
      statusEl.textContent = "";
      statusEl.classList.add("hidden");
    }
    resultsEl.replaceChildren();
    const tEl = card.querySelector(".track-status-title");
    const displayTitle = ((tEl && tEl.textContent) || "").trim();
    ti.value = _lyricSearchTitleFromDisplay(displayTitle);
    ar.value = (card.dataset.lyricArtist || "").trim();
    pop.classList.remove("hidden");
    pop.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => _positionAttachTrackPopover());
    void _runAttachTrackSearch(false);
  }

  async function _runAttachTrackSearch(forceShowErrors) {
    const card = _attachTrackAnchorCard;
    const ti = document.getElementById("attach-track-title");
    const ar = document.getElementById("attach-track-artist");
    const statusEl = document.getElementById("attach-track-status");
    const resultsEl = document.getElementById("attach-track-results");
    if (!card || !ti || !ar || !resultsEl) return;
    const titleQ = ti.value.trim();
    const artistQ = ar.value.trim();
    const query = [titleQ, artistQ].filter(Boolean).join(" ").trim();
    if (query.length < 2) {
      if (forceShowErrors && statusEl) {
        statusEl.textContent = "Enter at least 2 characters (title and/or artist).";
        statusEl.classList.remove("hidden");
      }
      return;
    }
    let anchor_explicit = null;
    const te = card.dataset.trackExplicit;
    if (te === "1") anchor_explicit = true;
    else if (te === "0") anchor_explicit = false;
    const body = { query };
    if (anchor_explicit !== null) body.anchor_explicit = anchor_explicit;
    if (statusEl) {
      statusEl.textContent = "Searching…";
      statusEl.classList.remove("hidden");
    }
    _showLyricSearchResultsLoading(resultsEl, "Searching Qobuz");
    try {
      const res = await api.replacementApi.searchAttachTracks(body);
      const data = await res.json();
      if (!data.ok) {
        resultsEl.replaceChildren();
        if (statusEl) {
          statusEl.textContent = data.error || "Search failed.";
          statusEl.classList.remove("hidden");
        }
        return;
      }
      const tracks = data.tracks || [];
      const sidSlot = ((card.dataset.slotTrackId) || "").trim();
      const tElA = card.querySelector(".track-status-title");
      const displayAnchor = ((tElA && tElA.textContent) || "").trim();
      const anchorTitle = _lyricSearchTitleFromDisplay(displayAnchor);
      const anchorArtist = (card.dataset.lyricArtist || "").trim();
      const anchorDur =
        parseInt(String(card.dataset.durationSec || "0"), 10) || 0;
      const scored = [];
      for (let i = 0; i < tracks.length; i++) {
        const t = tracks[i];
        if (sidSlot && String(t.id || "") === sidSlot) continue;
        const mp = _attachTrackMatchPct(
          anchorTitle,
          anchorArtist,
          String(t.title || ""),
          String(t.artist || ""),
        );
        scored.push({ t, mp });
      }
      scored.sort((a, b) => b.mp - a.mp);

      resultsEl.replaceChildren();
      if (statusEl) {
        if (!scored.length) {
          statusEl.textContent =
            anchor_explicit === null
              ? "No matches."
              : "No matches with the same explicit/clean flag.";
          statusEl.classList.remove("hidden");
        } else {
          statusEl.textContent = `${scored.length} result(s)`;
          statusEl.classList.remove("hidden");
        }
      }
      if (!scored.length) {
        const empty = document.createElement("div");
        empty.className = "lyric-search-empty";
        empty.textContent =
          anchor_explicit === null
            ? "No matches."
            : "No matches with the same explicit/clean flag.";
        resultsEl.appendChild(empty);
      } else {
        for (let j = 0; j < scored.length; j++) {
          const { t, mp } = scored[j];
          resultsEl.appendChild(
            _createAttachTrackSearchRow(t, mp, anchorDur, async (btn) => {
              btn.disabled = true;
              await _submitAttachSubstitute(String(t.id || ""));
              btn.disabled = false;
            }),
          );
        }
      }
    } catch (_) {
      resultsEl.replaceChildren();
      if (statusEl) {
        statusEl.textContent = "Network error.";
        statusEl.classList.remove("hidden");
      }
    } finally {
      const ap = document.getElementById("attach-track-popover");
      if (ap && !ap.classList.contains("hidden") && _attachTrackAnchorCard) {
        requestAnimationFrame(() => _positionAttachTrackPopover());
      }
    }
  }

  function _hasValidLyrics(card) {
    if (!card) return false;
    const chip = card.querySelector(".lyrics-chip");
    if (!chip) return false;
    const parts = (chip.className || "").split(/\s+/);
    return parts.includes("synced") || parts.includes("plain");
  }

  async function _writeAttachMissingPlaceholder(card, triggerBtnOpt) {
    const c = card && card.dataset ? card : _attachTrackAnchorCard;
    const sid = ((c && c.dataset && c.dataset.slotTrackId) || "").trim();

    const pop = document.getElementById("attach-track-popover");
    const statusEl =
      pop &&
      !pop.classList.contains("hidden") &&
      _attachTrackAnchorCard === c
        ? document.getElementById("attach-track-status")
        : null;

    const triggerBtn = triggerBtnOpt || null;
    const clearBusy = () => {
      if (triggerBtn instanceof HTMLElement) {
        triggerBtn.disabled = false;
        triggerBtn.removeAttribute("aria-busy");
      }
    };

    if (!c) {
      clearBusy();
      return;
    }
    if (!sid) {
      if (statusEl) {
        statusEl.textContent =
          "No queued track linked, use a purchase/failed queue row.";
        statusEl.classList.remove("hidden");
      }
      clearBusy();
      return;
    }

    const albumId = ((c.dataset.releaseAlbumId) || "").trim();
    const payload = { slot_track_id: sid };
    if (albumId) payload.album_id = albumId;
    let qs = ((c.dataset.queueSourceUrl) || "").trim();
    if (!qs && typeof window._qUrlForPurchaseSlot === "function") {
      qs = window._qUrlForPurchaseSlot(sid) || "";
    }
    if (qs) payload.queue_source_url = qs;
    if (_hasValidLyrics(c)) payload.skip_lyrics = true;

    if (triggerBtn instanceof HTMLElement) {
      triggerBtn.disabled = true;
      triggerBtn.setAttribute("aria-busy", "true");
    }

    try {
      const res = await api.replacementApi.writeMissingPlaceholder(payload);
      const data = await res.json().catch(() => ({}));

      if (data.ok) {
        // Store the saved path so we can delete it if the user switches to search.
        const sp = String(data.saved_path || "").trim();
        if (sp) c.dataset.missingPlaceholderPath = sp;
        c.dataset.resolvedBy = "placeholder";
        _syncResolutionButtonStates(c);
        if (statusEl) {
          const bn = String(data.basename || "").trim();
          statusEl.textContent = bn ? `Saved: ${bn}` : "Placeholder saved.";
          statusEl.classList.remove("hidden");
        }
      } else {
        const msg = String(data.error || "Could not save placeholder.");
        if (statusEl) {
          statusEl.textContent = msg;
          statusEl.classList.remove("hidden");
        } else {
          console.warn(msg);
        }
      }
    } catch (_) {
      if (statusEl) {
        statusEl.textContent = "Network error.";
        statusEl.classList.remove("hidden");
      }
    } finally {
      clearBusy();
    }
  }

  /**
   * Sync the green "resolved" fill on the search/placeholder button pair for a card.
   * card.dataset.resolvedBy === "search"      → search btn gets track-resolution-active
   * card.dataset.resolvedBy === "placeholder" → placeholder btn gets track-resolution-active
   * Anything else (undefined / "none")        → both buttons unfilled.
   */
  function _syncResolutionButtonStates(card) {
    if (!card) return;
    const tags = card.querySelector(".track-status-tags");
    if (!tags) return;
    const sb = tags.querySelector(".track-substitute-search-btn");
    const pb = tags.querySelector(".track-missing-placeholder-btn");
    const resolvedBy = (card.dataset.resolvedBy || "").trim();
    if (sb) {
      sb.classList.toggle("track-resolution-active", resolvedBy === "search");
      if (resolvedBy === "search") {
        sb.setAttribute("data-tip", "Downloaded replacement, click to search again");
      } else {
        sb.setAttribute("data-tip", "Search to replace track with similar");
      }
    }
    if (pb) {
      pb.classList.toggle("track-resolution-active", resolvedBy === "placeholder");
      if (resolvedBy === "placeholder") {
        pb.setAttribute("data-tip", "Placeholder .missing.txt written, click to switch to search replacement");
      } else {
        pb.setAttribute("data-tip", _MISSING_PLACEHOLDER_BTN_TIP);
      }
    }
  }

  async function _submitAttachSubstitute(subId) {
    const card = _attachTrackAnchorCard;
    const sid = ((card && card.dataset.slotTrackId) || "").trim();
    const albumId = ((card && card.dataset.releaseAlbumId) || "").trim();
    if (!sid || !subId) return;
    try {
      const payload = {
        slot_track_id: sid,
        substitute_track_id: subId,
      };
      if (albumId) payload.album_id = albumId;
      let qs = (card.dataset.queueSourceUrl || "").trim();
      if (
        !qs &&
        typeof window._qUrlForPurchaseSlot === "function"
      ) {
        qs = window._qUrlForPurchaseSlot(sid) || "";
      }
      if (qs) payload.queue_source_url = qs;
      const res = await api.replacementApi.downloadAttachTrack(payload);
      const data = await res.json();
      if (!data.ok) {
        console.warn(data.error || "Attach failed");
        return;
      }
      _closeAttachTrackPopover();
    } catch (_) {
      /* ignore */
    }
  }

  function _initAttachTrackSearchPopover() {
    const closeBtn = document.getElementById("attach-track-close");
    const submitBtn = document.getElementById("attach-track-submit");
    const pop = document.getElementById("attach-track-popover");
    const ti = document.getElementById("attach-track-title");
    const ar = document.getElementById("attach-track-artist");
    let attachTrackMousedownTarget = null;
    document.addEventListener(
      "mousedown",
      (e) => {
        if (!pop || pop.classList.contains("hidden")) {
          attachTrackMousedownTarget = null;
          return;
        }
        attachTrackMousedownTarget = e.target;
      },
      true,
    );
    document.addEventListener("click", (e) => {
      if (!pop || pop.classList.contains("hidden")) return;
      const target = attachTrackMousedownTarget || e.target;
      if (pop.contains(target)) return;
      if (e.target.closest && e.target.closest("#dl-track-status")) return;
      _closeAttachTrackPopover();
    });
    if (closeBtn) {
      closeBtn.addEventListener("click", () => _closeAttachTrackPopover());
    }
    if (submitBtn && ti && ar) {
      submitBtn.addEventListener("click", () => void _runAttachTrackSearch(true));
      const onEnter = (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          void _runAttachTrackSearch(true);
        }
      };
      ti.addEventListener("keydown", onEnter);
      ar.addEventListener("keydown", onEnter);
    }
    if (pop) {
      pop.addEventListener("click", (ev) => {
        if (ev.target === pop) _closeAttachTrackPopover();
      });
      window.addEventListener("resize", () => {
        if (pop.classList.contains("hidden") || !_attachTrackAnchorCard) {
          return;
        }
        _positionAttachTrackPopover();
      });
      let _attachPopWinScrollRaf = null;
      window.addEventListener(
        "scroll",
        () => {
          if (
            pop.classList.contains("hidden") ||
            !_attachTrackAnchorCard
          ) {
            return;
          }
          if (_attachPopWinScrollRaf != null) {
            cancelAnimationFrame(_attachPopWinScrollRaf);
          }
          _attachPopWinScrollRaf = requestAnimationFrame(() => {
            _attachPopWinScrollRaf = null;
            _positionAttachTrackPopover();
          });
        },
        true,
      );
    }
  }

  function _finalizeSubstituteSearchBtn(tags, card) {
    if (!tags || !card) return;
    const sid = (card.dataset.slotTrackId || "").trim();
    const rid = (card.dataset.releaseAlbumId || "").trim();
    if (!sid || !rid) return;
    tags.querySelectorAll(".track-missing-placeholder-btn").forEach((n) => n.remove());

    // ── Placeholder button ────────────────────────────────────────────────
    const mp = document.createElement("button");
    mp.type = "button";
    mp.className = "track-dl-btn track-missing-placeholder-btn";
    mp.setAttribute("data-tip", _MISSING_PLACEHOLDER_BTN_TIP);
    mp.setAttribute(
      "aria-label",
      "Save missing-track placeholder (.missing.txt) beside downloads",
    );
    mp.innerHTML = _TRACK_MISSING_NOTE_ICON_SVG;
    mp.addEventListener("click", (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      if (mp.disabled) return;
      if (card.dataset.resolvedBy === "placeholder") return;
      
      const prevAudio = (card.dataset.audioPath || "").trim();
      if (card.dataset.resolvedBy === "search" && prevAudio && !prevAudio.toLowerCase().endsWith(".missing.txt")) {
        api.replacementApi.deleteResolutionFile({ file_path: prevAudio }).catch(() => {});
        delete card.dataset.audioPath;
        delete card.dataset.resolvedBy;
      }

      // If previously resolved by search, just write the placeholder, no
      // audio file to delete (the substitute is a real downloaded track the
      // user may want to keep; only the resolution *label* switches).
      void _writeAttachMissingPlaceholder(card, mp);
    });
    tags.appendChild(mp);

    // ── Search / substitute button ────────────────────────────────────────
    const sb = document.createElement("button");
    sb.type = "button";
    sb.className = "track-dl-btn track-substitute-search-btn";
    sb.setAttribute("data-tip", "Search to replace track with similar");
    sb.setAttribute("aria-label", "Find track replacement");
    sb.innerHTML = _TRACK_SEARCH_ICON_SVG;
    sb.addEventListener("click", (evt) => {
      evt.preventDefault();
      evt.stopPropagation();
      // If previously resolved by placeholder, delete the .missing.txt first
      // so the library doesn't end up with both a real file and a placeholder.
      const prevPath = (card.dataset.missingPlaceholderPath || "").trim();
      if (card.dataset.resolvedBy === "placeholder" && prevPath) {
        api.replacementApi.deleteResolutionFile({ file_path: prevPath }).catch(() => { /* fire-and-forget; open search regardless */ });
        delete card.dataset.missingPlaceholderPath;
        delete card.dataset.resolvedBy;
        _syncResolutionButtonStates(card);
      }
      _openAttachTrackPopover(card);
    });
    tags.appendChild(sb);

    // Restore any previously saved resolution state (survives re-renders).
    _syncResolutionButtonStates(card);
  }

  function _setTrackDownloadChip(
    trackNo,
    title,
    statusText,
    cls,
    linkOpts,
    lyricAlbum,
  ) {
    const card = _ensureTrackStatusCard(trackNo, title, false, undefined, lyricAlbum);
    if (!card) return;
    const tags = card.querySelector(".track-status-tags");
    if (!tags) return;
    tags.querySelectorAll(".track-substitute-search-btn").forEach((n) => n.remove());
    tags.querySelectorAll(".track-missing-placeholder-btn").forEach((n) => n.remove());
    const old = card.querySelector(".download-chip");
    if (old) old.remove();

    const href = linkOpts && String(linkOpts.href || "").trim();
    const sid = linkOpts && String(linkOpts.slotTrackId || "").trim();
    if (href) {
      if (sid && card) {
        card.dataset.slotTrackId = sid;
      }
      const rid =
        linkOpts && String(linkOpts.releaseAlbumId || "").trim();
      if (rid && card) {
        card.dataset.releaseAlbumId = rid;
      }
      const el = document.createElement("a");
      el.className = "track-dl-btn download-chip purchase-only";
      el.href = href;
      el.target = "_blank";
      el.rel = "noopener noreferrer";
      if (linkOpts.titleAttr) {
        const tip = String(linkOpts.titleAttr).trim();
        el.setAttribute("data-tip", tip);
        el.setAttribute("aria-label", tip);
        el.removeAttribute("title");
      } else {
        el.setAttribute("aria-label", "Open in Qobuz store");
      }
      el.textContent = statusText || "Purchase";
      tags.appendChild(el);
      _finalizeSubstituteSearchBtn(tags, card);
      return;
    }

    const el = document.createElement("button");
    el.type = "button";
    el.className = "track-dl-btn download-chip";
    el.disabled = true;
    el.innerHTML = `<span class="track-dl-btn-fill"></span>${_TRACK_DL_ICON_SVG}`;

    const revealPath = (card.dataset.audioPath || "").trim();
    const canReveal = cls === "done" && revealPath !== "";

    if (cls === "done") {
      el.classList.add("track-dl-btn--done");
      if (canReveal) {
        el.classList.add("track-dl-btn--reveal");
        el.disabled = false;
        el.setAttribute("aria-label", "Show downloaded file in folder");
        el.setAttribute("data-tip", "Show in folder");
        el.innerHTML =
          '<span class="track-dl-btn-fill"></span>' +
          '<span class="track-dl-btn-ico-stack">' +
          `<span class="track-dl-btn-ico-layer track-dl-btn-ico--dl">${_TRACK_DL_ICON_SVG}</span>` +
          `<span class="track-dl-btn-ico-layer track-dl-btn-ico--folder">${_TRACK_FOLDER_ICON_SVG}</span>` +
          "</span>";
      } else {
        el.setAttribute("aria-label", "Downloaded");
      }
    } else if (cls === "failed") {
      el.classList.add("track-dl-btn--failed");
      el.setAttribute("aria-label", statusText === "failed" ? "Download failed" : String(statusText || "Failed"));
      el.innerHTML = _TRACK_DL_FAIL_SVG;
    } else {
      el.classList.add("track-dl-btn--active");
      el.setAttribute("aria-label", "Downloading");
    }
    tags.appendChild(el);
    if (cls === "failed") {
      _finalizeSubstituteSearchBtn(tags, card);
    } else if (cls === "done" && card.dataset.attachSearchEligible === "1") {
      _finalizeSubstituteSearchBtn(tags, card);
    }
  }

  function _trackStatusCardForProgress(trackNo, title, lyricAlbum) {
    const parsed = _parseTrackRef(trackNo, title);
    const pa = lyricAlbum != null && String(lyricAlbum).trim() !== "" ? String(lyricAlbum).trim() : "";
    let key = _trackKey(parsed.trackNo, parsed.title, pa);
    let card = key ? _trackStatusMap.get(key) : null;
    if (!card && pa) {
      key = _trackKey(parsed.trackNo, parsed.title, "");
      card = key ? _trackStatusMap.get(key) : null;
    }
    if (!card) {
      const wantN = _normalizeTrackNo(parsed.trackNo);
      const wantT = _normalizeTrackTitle(parsed.title);
      for (const c of _trackStatusMap.values()) {
        const tn = _normalizeTrackNo(c.dataset.trackNo || "");
        const tEl = c.querySelector(".track-status-title");
        const tt = _normalizeTrackTitle((tEl && tEl.textContent) || "");
        if (tn === wantN && tt === wantT) {
          card = c;
          break;
        }
      }
    }
    return card;
  }

  function _updateTrackDownloadProgress(
    trackNo,
    title,
    received,
    total,
    lyricAlbum,
  ) {
    const card = _trackStatusCardForProgress(trackNo, title, lyricAlbum);
    if (!card) return;
    const btn = card.querySelector("button.download-chip.track-dl-btn");
    if (!btn || !btn.classList.contains("track-dl-btn--active")) return;
    const t = Number(total);
    const r = Number(received);
    if (!Number.isFinite(t) || t <= 0 || !Number.isFinite(r)) return;
    const pct = Math.max(0, Math.min(100, Math.round((r / t) * 100)));
    const fill = btn.querySelector(".track-dl-btn-fill");
    if (fill) {
      const f = pct / 100;
      fill.style.transform = `scaleY(${f})`;
    }
    btn.setAttribute("aria-label", `Downloading, ${pct}%`);
  }

  /** Interpolate chip colors from red (0%) to accent teal (100%) | pairs with synced tag. */
  function _confidenceChipStyles(pct) {
    const p = Math.max(0, Math.min(100, pct)) / 100;
    const r0 = 255;
    const g0 = 77;
    const b0 = 77;
    const r1 = 110;
    const g1 = 231;
    const b1 = 247;
    const r = Math.round(r0 + (r1 - r0) * p);
    const g = Math.round(g0 + (g1 - g0) * p);
    const b = Math.round(b0 + (b1 - b0) * p);
    return {
      color: `rgb(${r},${g},${b})`,
      borderColor: `rgba(${r},${g},${b},0.45)`,
      background: `rgba(${r},${g},${b},0.12)`,
    };
  }

  function _positionConfidenceTooltip(wrap, tip) {
    if (!wrap || !tip || !tip.classList.contains("confidence-chip-tooltip--open")) return;
    if (tip.parentNode !== document.body) document.body.appendChild(tip);
    tip.classList.add("confidence-chip-tooltip--fixed");
    requestAnimationFrame(() => {
      const r = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      const th = tip.offsetHeight;
      const pad = 8;
      let left = r.right - tw;
      left = Math.max(pad, Math.min(left, window.innerWidth - tw - pad));
      let top = r.top - th - pad;
      if (top < pad) top = Math.min(r.bottom + pad, window.innerHeight - th - pad);
      tip.style.left = `${Math.round(left)}px`;
      tip.style.top = `${Math.round(Math.max(pad, top))}px`;
    });
  }

  function _hideConfidenceTooltip(wrap, tip) {
    if (!tip) return;
    tip.classList.remove("confidence-chip-tooltip--open");
    tip.classList.remove("confidence-chip-tooltip--fixed");
    tip.style.left = "";
    tip.style.top = "";
    if (tip.parentNode === document.body && wrap) wrap.appendChild(tip);
  }

  function _bindConfidenceTooltipUi(wrap, tip) {
    const listEl = document.getElementById("dl-track-status");

    function targetInside(container, target) {
      if (!container || !target || !(target instanceof Node)) return false;
      return container === target || container.contains(target);
    }

    function hideUnlessMovingToTip(e) {
      const next = e.relatedTarget;
      if (targetInside(tip, next) || targetInside(wrap, next)) return;
      _hideConfidenceTooltip(wrap, tip);
    }

    function showTip() {
      tip.classList.add("confidence-chip-tooltip--open");
      _positionConfidenceTooltip(wrap, tip);
    }

    function onScrollOrResize() {
      if (tip.classList.contains("confidence-chip-tooltip--open")) {
        _positionConfidenceTooltip(wrap, tip);
      }
    }

    const onMouseEnterWrap = () => showTip();
    const onMouseEnterTip = () => showTip();
    const onMouseLeaveWrap = (e) => hideUnlessMovingToTip(e);
    const onMouseLeaveTip = (e) => hideUnlessMovingToTip(e);
    const onFocusInWrap = () => showTip();
    const onFocusOutWrap = (e) => hideUnlessMovingToTip(e);

    wrap.addEventListener("mouseenter", onMouseEnterWrap);
    wrap.addEventListener("mouseleave", onMouseLeaveWrap);
    tip.addEventListener("mouseenter", onMouseEnterTip);
    tip.addEventListener("mouseleave", onMouseLeaveTip);
    wrap.addEventListener("focusin", onFocusInWrap);
    wrap.addEventListener("focusout", onFocusOutWrap);
    window.addEventListener("resize", onScrollOrResize);
    if (listEl) listEl.addEventListener("scroll", onScrollOrResize, { passive: true });
    window.addEventListener("scroll", onScrollOrResize, true);

    wrap._confidenceTooltipTeardown = () => {
      _hideConfidenceTooltip(wrap, tip);
      wrap.removeEventListener("mouseenter", onMouseEnterWrap);
      wrap.removeEventListener("mouseleave", onMouseLeaveWrap);
      tip.removeEventListener("mouseenter", onMouseEnterTip);
      tip.removeEventListener("mouseleave", onMouseLeaveTip);
      wrap.removeEventListener("focusin", onFocusInWrap);
      wrap.removeEventListener("focusout", onFocusOutWrap);
      window.removeEventListener("resize", onScrollOrResize);
      if (listEl) listEl.removeEventListener("scroll", onScrollOrResize);
      window.removeEventListener("scroll", onScrollOrResize, true);
      delete wrap._confidenceTooltipTeardown;
    };
  }

  function _setLyricConfidenceChip(tags, pct) {
    let wrap = tags.querySelector(".confidence-chip-wrap");
    const chipHtml = `
      <span class="track-status-chip confidence-chip"></span>
      <div class="confidence-chip-tooltip" role="tooltip">
        <div class="confidence-chip-tooltip-title">Lyric match confidence</div>
        <div class="confidence-chip-tooltip-desc">How well the LRCLIB result matches this track’s artist, title, length, and album. Higher means we’re more sure it’s the right song.</div>
      </div>
    `;
    if (wrap) {
      if (typeof wrap._confidenceTooltipTeardown === "function") {
        wrap._confidenceTooltipTeardown();
      }
      wrap.remove();
    }
    wrap = document.createElement("span");
    wrap.className = "confidence-chip-wrap";
    wrap.setAttribute("tabindex", "0");
    wrap.innerHTML = chipHtml;
    const chip = wrap.querySelector(".confidence-chip");
    const tip = wrap.querySelector(".confidence-chip-tooltip");
    const styles = _confidenceChipStyles(pct);
    chip.textContent = `${pct}%`;
    chip.style.color = styles.color;
    chip.style.borderColor = styles.borderColor;
    chip.style.background = styles.background;
    wrap.setAttribute(
      "aria-label",
      `Lyric match confidence ${pct} percent. Hover for details.`,
    );
    const lyricsChip = tags.querySelector(".track-status-chip.lyrics-chip");
    const download = tags.querySelector(".download-chip");
    if (lyricsChip) tags.insertBefore(wrap, lyricsChip);
    else if (download) tags.insertBefore(wrap, download);
    else tags.appendChild(wrap);

    _bindConfidenceTooltipUi(wrap, tip);
  }

  function _removeLyricConfidenceChip(tags) {
    const wrap = tags.querySelector(".confidence-chip-wrap");
    if (!wrap) return;
    if (typeof wrap._confidenceTooltipTeardown === "function") {
      wrap._confidenceTooltipTeardown();
    }
    wrap.remove();
  }

  function _normalizeLyricDestination(destination) {
    const d = String(destination || "").trim().toLowerCase();
    if (d === "both" || d === "lrc" || d === ".lrc" || d === "embed" || d === "metadata") {
      return d === ".lrc" ? "lrc" : d === "metadata" ? "embed" : d;
    }
    return "";
  }

  function _lyricDestinationFromOutputs(outputs) {
    const lrc = !!(outputs && outputs.lrc);
    const metadata = !!(outputs && outputs.metadata);
    if (lrc && metadata) return "both";
    if (lrc) return "lrc";
    if (metadata) return "embed";
    return "";
  }

  function _lyricDestinationLabel(destination) {
    const d = _normalizeLyricDestination(destination);
    if (d === "both") return "both";
    if (d === "lrc") return ".lrc";
    if (d === "embed") return "embed";
    return "";
  }

  function _setTrackLyricsChip(
    trackNo,
    title,
    lyricType,
    confidence,
    lyricAlbum,
    lyricProvider,
    lyricDestination,
  ) {
    const card = _ensureTrackStatusCard(
      trackNo,
      title,
      false,
      undefined,
      lyricAlbum,
    );
    if (!card) return;
    const tags = card.querySelector(".track-status-tags");
    let chip = card.querySelector(".track-status-chip.lyrics-chip");
    if (!chip) {
      chip = document.createElement("span");
      chip.className = "track-status-chip lyrics-chip";
      tags.appendChild(chip);
    }
    const lt = String(lyricType || "none").toLowerCase();
    chip.className = `track-status-chip lyrics-chip ${lt}`;
    const confRaw =
      confidence != null && String(confidence).trim() !== ""
        ? String(confidence).trim()
        : "";
    const confNum = confRaw !== "" ? parseInt(confRaw, 10) : NaN;
    const hasConf =
      !Number.isNaN(confNum) && confRaw !== "" && lt !== "loading";
    const dest = _normalizeLyricDestination(lyricDestination);
    const destLabel =
      lt === "loading" || lt === "none" || lt === "error"
        ? ""
        : _lyricDestinationLabel(dest);

    chip.textContent =
      lt === "none"
        ? "none"
        : lt === "error"
          ? "error"
          : lt === "loading"
            ? "loading"
            : lt;
    if (dest) {
      chip.dataset.lyricDestination = dest;
    } else {
      delete chip.dataset.lyricDestination;
    }
    chip.removeAttribute("title");
    const outputDesc =
      dest === "both"
        ? ".lrc + Embedded"
        : dest === "lrc"
          ? ".lrc"
          : dest === "embed"
            ? "Embedded"
            : "";
    if (outputDesc && lt !== "loading" && lt !== "none" && lt !== "error") {
      chip.setAttribute("aria-label", `${lt} lyrics, ${outputDesc}`);
      chip.setAttribute("data-tip", outputDesc);
    } else {
      chip.removeAttribute("aria-label");
      chip.removeAttribute("data-tip");
    }

    if (lt === "loading" || !hasConf) {
      _removeLyricConfidenceChip(tags);
    } else {
      _setLyricConfidenceChip(tags, confNum);
    }

    const apHist = (card.dataset.audioPath || "").trim();
    if (apHist && lt !== "loading") {
      void api.historyApi
        .postLyrics({
          audio_path: apHist,
          lyric_type: lt,
          lyric_provider: lyricProvider != null ? String(lyricProvider) : "",
          lyric_confidence: confRaw,
          lyric_destination: dest,
        })
        .catch(() => {});
    }
  }

  /** LRCLIB duration delta vs reference (±2s hidden; same threshold as LRCLIB matching). */
  function _formatLyricDeltaSec(sec) {
    return QG.core.format.formatLyricDeltaSec(sec);
  }

  function _lyricKindLabel(kind) {
    const k = String(kind || "").toLowerCase();
    if (k === "synced") return "Synced";
    if (k === "plain") return "Plain";
    if (k === "instrumental") return "Instrumental";
    return "\u2014";
  }

  let _lyricSearchModalCtx = null;
  let _lyricAttachAbort = null;
  let _lyricSearchReqAbort = null;
  let _lyricOpenSession = 0;
  const _LYRIC_SEARCH_PAGE_INITIAL = 10;
  const _LYRIC_SEARCH_PAGE_STEP = 5;
  let _lyricSearchScrollRaf = null;
  let _lyricSearchSeq = 0;
  let _lyricPreviewRaf = 0;
  let _lyricPreviewLastActiveIdx = -1;
  let _lyricPreviewSeekMouse = false;
  const _LYRIC_SEARCH_ANCHOR_CLASS = "lyric-search-anchor";

  function _abortLyricSearchFetches() {
    if (_lyricAttachAbort) {
      try {
        _lyricAttachAbort.abort();
      } catch (_) {
        /* ignore */
      }
      _lyricAttachAbort = null;
    }
    if (_lyricSearchReqAbort) {
      try {
        _lyricSearchReqAbort.abort();
      } catch (_) {
        /* ignore */
      }
      _lyricSearchReqAbort = null;
    }
  }

  function _clearLyricSearchAnchorHighlight() {
    document
      .querySelectorAll(".track-status-card." + _LYRIC_SEARCH_ANCHOR_CLASS)
      .forEach((el) => {
        el.classList.remove(_LYRIC_SEARCH_ANCHOR_CLASS);
      });
  }

  function _setLyricSearchAnchorCard(card) {
    _clearLyricSearchAnchorHighlight();
    if (card) card.classList.add(_LYRIC_SEARCH_ANCHOR_CLASS);
  }

  function _formatLyricPreviewTime(sec) {
    if (!Number.isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function _teardownLyricPreviewPlayback() {
    if (_lyricPreviewRaf) {
      cancelAnimationFrame(_lyricPreviewRaf);
      _lyricPreviewRaf = 0;
    }
    _lyricPreviewSeekMouse = false;
    _lyricPreviewLastActiveIdx = -1;
    const audio = document.getElementById("lyric-search-preview-audio");
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    const playBtn = document.getElementById("lyric-search-preview-play");
    if (playBtn) {
      const playIco = playBtn.querySelector(".lyric-search-preview-play-icon");
      const pauseIco = playBtn.querySelector(".lyric-search-preview-pause-icon");
      if (playIco) playIco.classList.remove("hidden");
      if (pauseIco) pauseIco.classList.add("hidden");
      playBtn.setAttribute("aria-label", "Play");
    }
    const seek = document.getElementById("lyric-search-preview-seek");
    const cur = document.getElementById("lyric-search-preview-cur");
    const dur = document.getElementById("lyric-search-preview-dur");
    if (seek) seek.value = "0";
    if (cur) cur.textContent = "0:00";
    if (dur) dur.textContent = "0:00";
  }

  function _lyricPreviewSetPlayingUi(playing) {
    const playBtn = document.getElementById("lyric-search-preview-play");
    if (!playBtn) return;
    const playIco = playBtn.querySelector(".lyric-search-preview-play-icon");
    const pauseIco = playBtn.querySelector(".lyric-search-preview-pause-icon");
    if (playIco) playIco.classList.toggle("hidden", playing);
    if (pauseIco) pauseIco.classList.toggle("hidden", !playing);
    playBtn.setAttribute("aria-label", playing ? "Pause" : "Play");
  }

  function _lyricPreviewSyncSeekAndTimeFromAudio() {
    if (_lyricPreviewSeekMouse) return;
    const audio = document.getElementById("lyric-search-preview-audio");
    const seek = document.getElementById("lyric-search-preview-seek");
    const cur = document.getElementById("lyric-search-preview-cur");
    if (!audio || !seek || !cur) return;
    const d = audio.duration;
    if (Number.isFinite(d) && d > 0) {
      seek.value = String(Math.round((audio.currentTime / d) * 1000));
    }
    cur.textContent = _formatLyricPreviewTime(audio.currentTime);
  }

  /** Apply range value to audio (used while dragging and on release). */
  function _applyLyricPreviewSeekSliderValue(scrollWhileSeeking = false) {
    const audio = document.getElementById("lyric-search-preview-audio");
    const seek = document.getElementById("lyric-search-preview-seek");
    if (!audio || !seek || seek.disabled) return;
    const d = audio.duration;
    if (!Number.isFinite(d) || d <= 0) return;
    const t = (Number(seek.value) / 1000) * d;
    audio.currentTime = t;
    const cur = document.getElementById("lyric-search-preview-cur");
    if (cur) cur.textContent = _formatLyricPreviewTime(t);
    _lyricPreviewUpdateActiveLine(t * 1000, { forceScroll: scrollWhileSeeking });
  }

  function _lyricPreviewSeekToTime(seconds) {
    const audio = document.getElementById("lyric-search-preview-audio");
    const seek = document.getElementById("lyric-search-preview-seek");
    if (!audio || !seek || seek.disabled || !audio.src) return;
    const d = audio.duration;
    if (!Number.isFinite(d) || d <= 0) return;
    const t = Math.min(Math.max(0, seconds), d);
    audio.currentTime = t;
    seek.value = String(Math.round((t / d) * 1000));
    const cur = document.getElementById("lyric-search-preview-cur");
    if (cur) cur.textContent = _formatLyricPreviewTime(t);
    _lyricPreviewUpdateActiveLine(t * 1000);
  }

  function _lyricPreviewUpdateActiveLine(progressMs, opts = {}) {
    const body = document.getElementById("lyric-search-preview-body");
    if (!body || !body.classList.contains("lyric-search-preview-body--synced")) {
      return;
    }
    const rows = body.querySelectorAll(".lyric-preview-line");
    if (!rows.length) return;
    let active = -1;
    for (let i = 0; i < rows.length; i++) {
      const start = Number(rows[i].dataset.startMs || 0);
      const end = Number(rows[i].dataset.endMs || Number.POSITIVE_INFINITY);
      if (progressMs >= start && progressMs < end) active = i;
    }
    if (active < 0) {
      for (let i = rows.length - 1; i >= 0; i--) {
        const start = Number(rows[i].dataset.startMs || 0);
        if (progressMs >= start) {
          active = i;
          break;
        }
      }
    }
    for (let i = 0; i < rows.length; i++) {
      rows[i].classList.toggle("is-active", i === active);
    }
    if (active >= 0 && active !== _lyricPreviewLastActiveIdx) {
      const previousActive = _lyricPreviewLastActiveIdx;
      _lyricPreviewLastActiveIdx = active;
      if (!_lyricPreviewSeekMouse || opts.forceScroll) {
        const targetIdx =
          previousActive >= 0 && active < previousActive
            ? Math.max(active - 2, 0)
            : Math.min(active + 2, rows.length - 1);
        const scrollTarget = rows[targetIdx];
        scrollTarget.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    } else if (active < 0) {
      _lyricPreviewLastActiveIdx = -1;
    }
  }

  function _lyricPreviewFrame() {
    const audio = document.getElementById("lyric-search-preview-audio");
    if (!audio || audio.paused || audio.ended) {
      _lyricPreviewRaf = 0;
      return;
    }
    _lyricPreviewSyncSeekAndTimeFromAudio();
    _lyricPreviewUpdateActiveLine(audio.currentTime * 1000);
    _lyricPreviewRaf = requestAnimationFrame(_lyricPreviewFrame);
  }

  function _parseLrcLinesForPreview(synced) {
    const out = [];
    const lines = String(synced || "").split(/\r?\n/);
    const re = /^\[(\d{1,3}):(\d{2}(?:\.\d{1,3})?)\]\s*(.*)$/;
    for (const line of lines) {
      const t = line.trim();
      if (!t) continue;
      const m = t.match(re);
      if (!m) continue;
      const mm = parseInt(m[1], 10);
      const ss = parseFloat(m[2]);
      if (Number.isNaN(mm) || Number.isNaN(ss)) continue;
      const start_ms = Math.round((mm * 60 + ss) * 1000);
      const lyricText = (m[3] || "").trim();
      const tag = t.match(/^\[[^\]]+\]/);
      out.push({
        start_ms,
        text: lyricText,
        timeTag: tag ? tag[0] : "",
      });
    }
    out.sort((a, b) => a.start_ms - b.start_ms);
    for (let i = 0; i < out.length; i++) {
      out[i].end_ms =
        i + 1 < out.length ? out[i + 1].start_ms : Number.POSITIVE_INFINITY;
    }
    return out;
  }

  function _renderLyricPreviewSyncedBody(body, parsed) {
    body.classList.add("lyric-search-preview-body--synced");
    body.replaceChildren();
    for (let i = 0; i < parsed.length; i++) {
      const row = document.createElement("div");
      row.className = "lyric-preview-line";
      row.dataset.startMs = String(parsed[i].start_ms);
      row.dataset.endMs = String(parsed[i].end_ms);
      const ts = document.createElement("span");
      ts.className = "lyric-preview-ts";
      ts.textContent = parsed[i].timeTag || "";
      const tx = document.createElement("span");
      tx.className = "lyric-preview-text";
      tx.textContent = parsed[i].text || " ";
      row.appendChild(ts);
      row.appendChild(tx);
      body.appendChild(row);
    }
  }

  function _renderLyricPreviewPlainBody(body, text) {
    body.classList.remove("lyric-search-preview-body--synced");
    body.textContent = text || "";
  }

  function _lyricPreviewAudioUrl(audioPath) {
    if (!audioPath) return "";
    return `/api/lyrics/stream-audio?path=${encodeURIComponent(audioPath)}`;
  }

  function _initLyricPreviewPlayer() {
    const playBtn = document.getElementById("lyric-search-preview-play");
    const seek = document.getElementById("lyric-search-preview-seek");
    const audio = document.getElementById("lyric-search-preview-audio");
    const previewRoot = document.getElementById("lyric-search-preview");
    if (!playBtn || !seek || !audio) return;
    if (playBtn.dataset.bound === "1") return;
    playBtn.dataset.bound = "1";
    playBtn.addEventListener("click", () => {
      if (playBtn.disabled || !audio.src) return;
      if (audio.paused) {
        void audio.play();
      } else {
        audio.pause();
      }
    });
    seek.addEventListener("pointerdown", (e) => {
      _lyricPreviewSeekMouse = true;
      try {
        seek.setPointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
    });
    function _finishLyricPreviewSeekDrag() {
      const wasDragging = _lyricPreviewSeekMouse;
      _lyricPreviewSeekMouse = false;
      if (!wasDragging) return;
      _lyricPreviewLastActiveIdx = -1;
      if (audio && Number.isFinite(audio.duration) && audio.duration > 0) {
        _lyricPreviewUpdateActiveLine(audio.currentTime * 1000);
      }
    }
    seek.addEventListener("pointerup", (e) => {
      try {
        seek.releasePointerCapture(e.pointerId);
      } catch (_) {
        /* ignore */
      }
      _finishLyricPreviewSeekDrag();
    });
    seek.addEventListener("pointercancel", () => {
      _finishLyricPreviewSeekDrag();
    });
    seek.addEventListener("lostpointercapture", () => {
      _finishLyricPreviewSeekDrag();
    });
    seek.addEventListener("change", () => {
      _applyLyricPreviewSeekSliderValue();
    });
    seek.addEventListener("input", () => {
      _applyLyricPreviewSeekSliderValue(true);
    });
    if (previewRoot && previewRoot.dataset.lineSeekBound !== "1") {
      previewRoot.dataset.lineSeekBound = "1";
      previewRoot.addEventListener("click", (e) => {
        const line = e.target.closest(".lyric-preview-line");
        if (!line || !previewRoot.contains(line)) return;
        const body = document.getElementById("lyric-search-preview-body");
        if (!body || !body.classList.contains("lyric-search-preview-body--synced")) {
          return;
        }
        const startMs = Number(line.dataset.startMs);
        if (!Number.isFinite(startMs)) return;
        _lyricPreviewSeekToTime(startMs / 1000);
      });
    }
    audio.addEventListener("play", () => {
      _lyricPreviewSetPlayingUi(true);
      if (!_lyricPreviewRaf) {
        _lyricPreviewRaf = requestAnimationFrame(_lyricPreviewFrame);
      }
    });
    audio.addEventListener("pause", () => {
      _lyricPreviewSetPlayingUi(false);
      if (_lyricPreviewRaf) {
        cancelAnimationFrame(_lyricPreviewRaf);
        _lyricPreviewRaf = 0;
      }
    });
    audio.addEventListener("ended", () => {
      _lyricPreviewSetPlayingUi(false);
    });
    audio.addEventListener("loadedmetadata", () => {
      const durEl = document.getElementById("lyric-search-preview-dur");
      const d = audio.duration;
      if (durEl && Number.isFinite(d)) {
        durEl.textContent = _formatLyricPreviewTime(d);
      }
    });
  }

  function _closeLyricPreviewOverlay() {
    _teardownLyricPreviewPlayback();
    const panel = document.getElementById("lyric-search-preview-panel");
    if (panel) {
      panel.classList.add("hidden");
      panel.setAttribute("aria-hidden", "true");
    }
    if (_lyricSearchModalCtx) {
      _lyricSearchModalCtx.previewingLrclibId = null;
    }
    document.querySelectorAll("#lyric-search-results .btn-ghost").forEach(btn => {
      btn.classList.remove("is-previewing");
      btn.textContent = "Preview";
      btn.style.width = "";
    });
  }

  function _closeLyricSearchModal() {
    const pop = document.getElementById("lyric-search-popover");
    if (pop) {
      pop.classList.add("hidden");
      pop.setAttribute("aria-hidden", "true");
    }
    _closeLyricPreviewOverlay();
    _abortLyricSearchFetches();
    _clearLyricSearchAnchorHighlight();
    _clearLyricSearchFieldErrors();
    _lyricSearchModalCtx = null;
  }

  /**
   * Place fixed popovers above the download history block, horizontally centered,
   * so the history list stays visible below (shared by lyric search + attach-track).
   */
  function _positionPopoverAboveDownloadHistory(pop) {
    if (!pop || pop.classList.contains("hidden")) return;
    const hist = document.getElementById("dl-track-status-container");
    const margin = 10;
    const gap = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const pw = pop.offsetWidth;
    const ph = pop.offsetHeight;
    let left;
    let top;
    if (hist) {
      const hr = hist.getBoundingClientRect();
      left = hr.left + (hr.width - pw) / 2;
      top = hr.top - ph - gap;
    } else {
      left = (vw - pw) / 2;
      top = margin;
    }
    left = Math.min(Math.max(margin, left), vw - pw - margin);
    if (top < margin) top = margin;
    if (top + ph > vh - margin) {
      top = Math.max(margin, vh - ph - margin);
    }
    pop.style.bottom = "auto";
    pop.style.left = `${Math.round(left)}px`;
    pop.style.top = `${Math.round(top)}px`;
  }

  function _positionLyricSearchPopover() {
    _positionPopoverAboveDownloadHistory(
      document.getElementById("lyric-search-popover"),
    );
  }

  function _positionAttachTrackPopover() {
    _positionPopoverAboveDownloadHistory(
      document.getElementById("attach-track-popover"),
    );
  }

  function _lyricSearchKindClass(kind) {
    const k = String(kind || "").toLowerCase();
    if (k === "plain") return "lyric-search-kind lyric-search-kind--plain";
    if (k === "instrumental") {
      return "lyric-search-kind lyric-search-kind--instrumental";
    }
    if (k === "synced") return "lyric-search-kind lyric-search-kind--synced";
    return "lyric-search-kind lyric-search-kind--muted";
  }

  function _clearLyricSearchFieldErrors() {
    const ti = document.getElementById("lyric-search-title");
    const ar = document.getElementById("lyric-search-artist");
    if (ti) ti.classList.remove("lyric-search-input-invalid");
    if (ar) ar.classList.remove("lyric-search-input-invalid");
  }

  function _applyLyricSearchFieldErrors(hasTitle, hasArtist) {
    const titleEl = document.getElementById("lyric-search-title");
    const artistEl = document.getElementById("lyric-search-artist");
    if (titleEl) {
      titleEl.classList.toggle("lyric-search-input-invalid", !hasTitle);
    }
    if (artistEl) {
      artistEl.classList.toggle("lyric-search-input-invalid", !hasArtist);
    }
  }

  function _showLyricSearchResultsLoading(container, ariaBusyLabel) {
    if (!container) return;
    container.replaceChildren();
    const root = document.createElement("div");
    root.className = "lyric-search-loading";
    root.setAttribute("role", "status");
    root.setAttribute("aria-busy", "true");
    root.setAttribute("aria-label", ariaBusyLabel || "Searching lyrics");
    for (let i = 0; i < 3; i++) {
      const row = document.createElement("div");
      row.className = "lyric-search-skeleton-row";
      const l1 = document.createElement("div");
      l1.className = "lyric-search-skeleton-line lyric-search-skeleton-line--a";
      const l2 = document.createElement("div");
      l2.className = "lyric-search-skeleton-line lyric-search-skeleton-line--b";
      const l3 = document.createElement("div");
      l3.className = "lyric-search-skeleton-line lyric-search-skeleton-line--c";
      const t = document.createElement("span");
      t.className = "lyric-search-skeleton-text";
      const p = document.createElement("span");
      p.className = "lyric-search-skeleton-pill";
      l3.appendChild(t);
      l3.appendChild(p);
      row.appendChild(l1);
      row.appendChild(l2);
      row.appendChild(l3);
      root.appendChild(row);
    }
    container.appendChild(root);
  }

  function _formatLyricConfidencePct(confVal) {
    const c = Number(confVal);
    if (!Number.isFinite(c)) return "";
    if (Number.isInteger(c)) return String(Math.round(c));
    const r = Math.round(c * 10) / 10;
    return String(r);
  }

  function _bindLyricSearchKindConfidenceHover(kindEl, kindLabel, confVal) {
    kindEl.dataset.kindLabel = kindLabel;
    const pct = _formatLyricConfidencePct(confVal);
    if (!pct) {
      kindEl.textContent = kindLabel;
      return;
    }
    kindEl.dataset.confidencePct = pct;
    kindEl.classList.add("lyric-search-kind--pct-swap");
    kindEl.textContent = `${pct}%`;
    kindEl.setAttribute(
      "aria-label",
      `LRCLIB match ${pct}% (${kindLabel}); hover shows lyric type.`,
    );

    function showKindLabel() {
      kindEl.textContent = kindEl.dataset.kindLabel || kindLabel;
    }
    function showPct() {
      const p = kindEl.dataset.confidencePct;
      kindEl.textContent = p ? `${p}%` : kindEl.dataset.kindLabel || kindLabel;
    }

    kindEl.addEventListener("mouseenter", showKindLabel);
    kindEl.addEventListener("mouseleave", showPct);
  }

  function _createLyricSearchResultRow(row) {
    const div = document.createElement("div");
    div.className = "lyric-search-row";
    const audioPath = _lyricSearchModalCtx && _lyricSearchModalCtx.audioPath;
    const attachedId =
      _lyricSearchModalCtx && _lyricSearchModalCtx.attachedLrclibId != null
        ? Number(_lyricSearchModalCtx.attachedLrclibId)
        : null;
    const rowId = row.id != null ? Number(row.id) : NaN;
    const isRowAttached =
      attachedId != null &&
      Number.isFinite(attachedId) &&
      Number.isFinite(rowId) &&
      rowId === attachedId;
    if (isRowAttached) {
      div.classList.add("lyric-search-row--attached");
      div.setAttribute("data-lyric-attached", "1");
    }
    div.dataset.rowId = String(row.id || "");

    const trackNameRaw = row.trackName || "";
    const albumRaw = row.albumName || "";
    const artistRaw = row.artistName || "";

    const line1 = document.createElement("div");
    line1.className =
      "lyric-search-row-line lyric-search-row-line--title";

    const t = document.createElement("span");
    t.className = "lyric-search-track";
    t.textContent = trackNameRaw;

    const kind = document.createElement("span");
    kind.className = _lyricSearchKindClass(row.kind);
    const kindLabel = _lyricKindLabel(row.kind);
    kind.textContent = kindLabel;
    _bindLyricSearchKindConfidenceHover(kind, kindLabel, row.confidence);

    line1.appendChild(t);
    line1.appendChild(kind);

    const ex = document.createElement("span");
    if (row.lyrics_explicit) {
      ex.className =
        "lyric-search-rating lyric-search-rating--explicit explicit-tag-badge";
      ex.innerHTML = _EXPLICIT_BADGE_SVG;
      line1.appendChild(ex);
    } else {
      ex.className = "lyric-search-rating lyric-search-rating--clean";
      ex.textContent = "clean";
      line1.appendChild(ex);
    }

    const deltaStr = _formatLyricDeltaSec(row.delta_sec);
    if (deltaStr) {
      const d = document.createElement("span");
      d.className = "lyric-search-delta";
      d.textContent = deltaStr;
      d.setAttribute(
        "aria-label",
        "LRCLIB duration vs this track: " + deltaStr + " (mm:ss)",
      );
      line1.appendChild(d);
    }

    const line2 = document.createElement("div");
    line2.className =
      "lyric-search-row-line lyric-search-row-line--album";
    const albumEl = document.createElement("span");
    albumEl.className = "lyric-search-album";
    albumEl.textContent = albumRaw || "\u2014";
    line2.appendChild(albumEl);

    const line3 = document.createElement("div");
    line3.className =
      "lyric-search-row-line lyric-search-row-line--footer";

    const artistSpan = document.createElement("span");
    artistSpan.className = "lyric-search-artist";
    artistSpan.textContent = artistRaw || "\u2014";

    const actions = document.createElement("div");
    actions.className = "lyric-search-row-actions";

    const prevBtn = document.createElement("button");
    prevBtn.type = "button";
    prevBtn.className = "btn-ghost btn-sm";
    prevBtn.textContent = "Preview";
    const rid = row.id;
    prevBtn.dataset.rid = String(rid);
    prevBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      void _previewLyricRow(rid);
    });

    const saveBtn = document.createElement("button");
    saveBtn.type = "button";
    saveBtn.className = "btn-primary btn-sm";
    saveBtn.textContent = "Attach";
    saveBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (saveBtn.disabled) return;
      void _attachLyricRow(rid, row.confidence, row.kind, saveBtn);
    });
    if (!audioPath) {
      saveBtn.disabled = true;
      saveBtn.title =
        "Audio path is available after the track file is saved to disk.";
    }

    actions.appendChild(prevBtn);
    if (isRowAttached) {
      const slot = document.createElement("span");
      slot.className = "lyric-search-attached-slot";
      slot.setAttribute("aria-label", "Already attached to this track");
      slot.setAttribute(
        "data-tip",
        "Lyrics already attached\nThis LRCLIB match is saved using your current lyric output settings. Plex and other players can read sidecar or embedded lyrics.",
      );
      slot.setAttribute("data-tip-icon", "/gui/plex.png");
      slot.innerHTML = _LYRIC_SEARCH_ATTACHED_SVG;
      actions.appendChild(slot);
    } else {
      actions.appendChild(saveBtn);
    }

    line3.appendChild(artistSpan);
    line3.appendChild(actions);

    div.appendChild(line1);
    div.appendChild(line2);
    div.appendChild(line3);
    return div;
  }

  function _lyricSearchResultsRenderEmpty() {
    const el = document.getElementById("lyric-search-results");
    if (!el) return;
    el.innerHTML = "";
    el.scrollTop = 0;
    const empty = document.createElement("div");
    empty.className = "lyric-search-empty";
    empty.textContent = "No matches.";
    el.appendChild(empty);
  }

  function _lyricSearchAppendResultsPage(isInitial) {
    const el = document.getElementById("lyric-search-results");
    const ctx = _lyricSearchModalCtx;
    if (!el || !ctx || !Array.isArray(ctx.lastSearchResults)) return;
    const all = ctx.lastSearchResults;
    const total = all.length;
    if (!total) return;
    const step = isInitial ? _LYRIC_SEARCH_PAGE_INITIAL : _LYRIC_SEARCH_PAGE_STEP;
    let shown = ctx.lyricSearchPagedShown || 0;
    if (isInitial) {
      el.innerHTML = "";
      shown = 0;
    }
    const next = Math.min(shown + step, total);
    for (let i = shown; i < next; i++) {
      el.appendChild(_createLyricSearchResultRow(all[i]));
    }
    ctx.lyricSearchPagedShown = next;
  }

  /** After results render: scroll to the row matching attached LRCLIB id, or top if none / not in list. */
  function _lyricSearchScrollToAttachedOrTop(el, list) {
    const ctx = _lyricSearchModalCtx;
    if (!el || !ctx || !Array.isArray(list) || !list.length) return;
    const attachedId =
      ctx.attachedLrclibId != null ? Number(ctx.attachedLrclibId) : NaN;
    let attachedIdx = -1;
    if (Number.isFinite(attachedId)) {
      attachedIdx = list.findIndex((r) => Number(r.id) === attachedId);
    }
    if (attachedIdx < 0) {
      el.scrollTop = 0;
      return;
    }
    const total = list.length;
    let guard = 0;
    while (
      (ctx.lyricSearchPagedShown || 0) <= attachedIdx &&
      (ctx.lyricSearchPagedShown || 0) < total &&
      guard < 200
    ) {
      _lyricSearchAppendResultsPage(false);
      guard++;
    }
    requestAnimationFrame(() => {
      const row = el.querySelector(".lyric-search-row--attached");
      if (row) {
        row.scrollIntoView({ block: "center", behavior: "auto" });
      } else {
        el.scrollTop = 0;
      }
    });
  }

  function _lyricSearchRebuildVisibleRows() {
    const ctx = _lyricSearchModalCtx;
    const el = document.getElementById("lyric-search-results");
    if (!ctx || !el || !Array.isArray(ctx.lastSearchResults)) return;
    const all = ctx.lastSearchResults;
    if (!all.length) {
      _lyricSearchResultsRenderEmpty();
      return;
    }
    const n = Math.min(ctx.lyricSearchPagedShown || 0, all.length);
    el.innerHTML = "";
    for (let i = 0; i < n; i++) {
      el.appendChild(_createLyricSearchResultRow(all[i]));
    }
    requestAnimationFrame(() => {
      const row = el.querySelector(".lyric-search-row--attached");
      if (row) {
        row.scrollIntoView({ block: "center", behavior: "auto" });
      }
    });
  }

  function _onLyricSearchResultsScroll() {
    if (_lyricSearchScrollRaf != null) {
      cancelAnimationFrame(_lyricSearchScrollRaf);
    }
    _lyricSearchScrollRaf = requestAnimationFrame(() => {
      _lyricSearchScrollRaf = null;
      const el = document.getElementById("lyric-search-results");
      const ctx = _lyricSearchModalCtx;
      if (!el || !ctx || !Array.isArray(ctx.lastSearchResults) || !ctx.lastSearchResults.length) {
        return;
      }
      const shown = ctx.lyricSearchPagedShown || 0;
      const total = ctx.lastSearchResults.length;
      if (shown >= total) return;
      const { scrollTop, scrollHeight, clientHeight } = el;
      if (scrollHeight - scrollTop - clientHeight > 100) return;
      _lyricSearchAppendResultsPage(false);
    });
  }

  function _renderLyricSearchResults(rows) {
    const el = document.getElementById("lyric-search-results");
    if (!el || !_lyricSearchModalCtx) return;
    const list = Array.isArray(rows) ? rows : [];
    _lyricSearchModalCtx.lastSearchResults = list;
    _lyricSearchModalCtx.lyricSearchPagedShown = 0;
    if (!list.length) {
      _lyricSearchResultsRenderEmpty();
      el.scrollTop = 0;
      return;
    }
    _lyricSearchAppendResultsPage(true);
    _lyricSearchScrollToAttachedOrTop(el, list);
  }

  async function _runLyricSearchFromForm() {
    const statusEl = document.getElementById("lyric-search-status");
    const resultsEl = document.getElementById("lyric-search-results");
    const titleEl = document.getElementById("lyric-search-title");
    const artistEl = document.getElementById("lyric-search-artist");
    const albumEl = document.getElementById("lyric-search-album");
    const title = titleEl ? titleEl.value.trim() : "";
    const artist = artistEl ? artistEl.value.trim() : "";
    const album = albumEl ? albumEl.value.trim() : "";
    const refDur =
      _lyricSearchModalCtx && Number.isFinite(_lyricSearchModalCtx.durationSec)
        ? _lyricSearchModalCtx.durationSec
        : 0;

    if (!title || !artist) {
      _applyLyricSearchFieldErrors(!!title, !!artist);
      if (statusEl) {
        statusEl.textContent = "Title and artist are required.";
        statusEl.classList.remove("hidden");
      }
      return;
    }
    _clearLyricSearchFieldErrors();

    if (_lyricSearchReqAbort) {
      try {
        _lyricSearchReqAbort.abort();
      } catch (_) {
        /* ignore */
      }
      _lyricSearchReqAbort = null;
    }
    const searchSeq = ++_lyricSearchSeq;
    if (_lyricSearchModalCtx) {
      _lyricSearchModalCtx.searchSeq = searchSeq;
    }
    _lyricSearchReqAbort = new AbortController();
    const searchSignal = _lyricSearchReqAbort.signal;

    if (statusEl) {
      statusEl.textContent = "Searching\u2026";
      statusEl.classList.remove("hidden");
    }
    _showLyricSearchResultsLoading(resultsEl);
    _closeLyricPreviewOverlay();

    try {
      const res = await api.lyricsApi.search(
        {
          title,
          artist,
          album,
          duration_sec: refDur,
          track_explicit:
            _lyricSearchModalCtx &&
            _lyricSearchModalCtx.trackExplicit !== null &&
            _lyricSearchModalCtx.trackExplicit !== undefined
              ? _lyricSearchModalCtx.trackExplicit
              : null,
          filter_mismatched: true,
        },
        searchSignal,
      );
      const data = await res.json();
      if (
        !_lyricSearchModalCtx ||
        _lyricSearchModalCtx.searchSeq !== searchSeq
      ) {
        return;
      }
      if (!data.ok) {
        if (statusEl) statusEl.textContent = data.error || "Search failed.";
        if (resultsEl) resultsEl.innerHTML = "";
        return;
      }
      const n = (data.results || []).length;
      if (statusEl) statusEl.textContent = `${n} result(s)`;
      const list = Array.isArray(data.results) ? data.results : [];
      if (_lyricSearchModalCtx) {
        _lyricSearchModalCtx.lastSearchResults = list.slice();
      }
      _renderLyricSearchResults(list);
    } catch (err) {
      if (err && err.name === "AbortError") {
        const ctx = _lyricSearchModalCtx;
        if (ctx && ctx.searchSeq === searchSeq && resultsEl) {
          resultsEl.innerHTML = "";
        }
        return;
      }
      if (
        !_lyricSearchModalCtx ||
        _lyricSearchModalCtx.searchSeq !== searchSeq
      ) {
        return;
      }
      if (statusEl) statusEl.textContent = "Network error.";
      if (resultsEl) resultsEl.innerHTML = "";
    }
    if (
      !_lyricSearchModalCtx ||
      _lyricSearchModalCtx.searchSeq !== searchSeq
    ) {
      return;
    }
    const popAfter = document.getElementById("lyric-search-popover");
    if (popAfter && !popAfter.classList.contains("hidden")) {
      requestAnimationFrame(() => _positionLyricSearchPopover());
    }
  }

  async function _previewLyricRow(id) {
    if (_lyricSearchModalCtx && _lyricSearchModalCtx.previewingLrclibId === id) {
      return;
    }
    if (_lyricSearchModalCtx) {
      _lyricSearchModalCtx.previewingLrclibId = id;
    }
    _teardownLyricPreviewPlayback();
    _lyricPreviewLastActiveIdx = -1;
    const panel = document.getElementById("lyric-search-preview-panel");
    const prev = document.getElementById("lyric-search-preview");
    const body = document.getElementById("lyric-search-preview-body");
    const flag = document.getElementById("lyric-search-preview-flag");
    const audio = document.getElementById("lyric-search-preview-audio");
    const playBtn = document.getElementById("lyric-search-preview-play");
    const seek = document.getElementById("lyric-search-preview-seek");
    const ctx = _lyricSearchModalCtx;
    const audioPath = ctx && ctx.audioPath ? String(ctx.audioPath).trim() : "";
    const idNum = id != null ? Number(id) : NaN;
    const attachedId =
      ctx && ctx.attachedLrclibId != null ? Number(ctx.attachedLrclibId) : NaN;
    const shouldUseLocal =
      audioPath &&
      Number.isFinite(idNum) &&
      Number.isFinite(attachedId) &&
      idNum === attachedId;
    if (!prev || !body) return;
    _renderLyricPreviewPlainBody(body, "Loading\u2026");
    if (playBtn) playBtn.disabled = true;
    if (seek) seek.disabled = true;
    if (flag) {
      flag.classList.add("hidden");
      flag.textContent = "";
    }
    if (panel) {
      panel.classList.remove("hidden");
      panel.setAttribute("aria-hidden", "false");
      requestAnimationFrame(() => _positionLyricSearchPopover());
    }

    // Highlight the button being previewed and show loading state
    let currentPreviewBtn = null;
    document.querySelectorAll("#lyric-search-results .btn-ghost").forEach(btn => {
      if (btn.dataset.rid === String(id)) {
        currentPreviewBtn = btn;
        btn.classList.add("is-previewing");
        // Lock width to prevent layout shift
        const w = btn.offsetWidth;
        if (w > 0) btn.style.width = w + "px";
        btn.innerHTML = '<span class="spinner"></span>';
      } else {
        btn.classList.remove("is-previewing");
        btn.textContent = "Preview";
        btn.style.width = "";
      }
    });

    try {
      let res;
      if (shouldUseLocal) {
        res = await api.lyricsApi.local(audioPath);
        if (!res.ok) {
          res = await api.lyricsApi.fetchById(id);
        }
      } else {
        res = await api.lyricsApi.fetchById(id);
      }
      const data = await res.json();
      if (!data.ok) {
        _renderLyricPreviewPlainBody(body, data.error || "Fetch failed.");
        return;
      }
      const rec = data.record || {};
      const synced = (rec.syncedLyrics || "").trim();
      const plain = (rec.plainLyrics || "").trim();
      if (synced) {
        const parsed = _parseLrcLinesForPreview(synced);
        if (parsed.length) {
          _renderLyricPreviewSyncedBody(body, parsed);
        } else {
          _renderLyricPreviewPlainBody(body, synced || plain || "(empty)");
        }
      } else {
        _renderLyricPreviewPlainBody(body, plain || "(empty)");
      }
      if (audioPath && audio) {
        audio.src = _lyricPreviewAudioUrl(audioPath);
        if (playBtn) playBtn.disabled = false;
        if (seek) seek.disabled = false;
      } else {
        if (audio) {
          audio.removeAttribute("src");
          audio.load();
        }
        if (playBtn) playBtn.disabled = true;
        if (seek) seek.disabled = true;
      }
      if (flag) {
        flag.classList.remove("hidden");
        if (data.lyrics_explicit) {
          flag.className = "lyric-search-preview-flag lyric-search-preview-flag--explicit";
          flag.innerHTML = `${_EXPLICIT_BADGE_SVG}<span class="lyric-search-preview-flag-text">Explicit: Lyric text contains explicit language.</span>`;
        } else {
          flag.className = "lyric-search-preview-flag lyric-search-preview-flag--clean";
          flag.innerHTML = `<span class="lyric-search-preview-flag-text lyric-search-preview-flag-text--clean">Clean: No explicit language detected in these lyrics.</span>`;
        }
      }
    } catch (_) {
      _renderLyricPreviewPlainBody(body, "Network error.");
    } finally {
      if (currentPreviewBtn && currentPreviewBtn.dataset.rid === String(id)) {
        currentPreviewBtn.textContent = "Preview";
        currentPreviewBtn.style.width = "";
      }
      requestAnimationFrame(() => _positionLyricSearchPopover());
    }
  }

  async function _attachLyricRow(id, confidence, kind, triggerBtn) {
    const ctx = _lyricSearchModalCtx;
    if (!ctx || !ctx.audioPath) return;
    const idNum = id != null ? Number(id) : NaN;
    if (!Number.isFinite(idNum)) return;
    const lyricTypeRaw = kind != null && String(kind).trim() !== ""
      ? String(kind).trim().toLowerCase()
      : "synced";
    let confForChip = "";
    if (confidence != null && String(confidence).trim() !== "") {
      const n = Math.round(Number(confidence));
      if (Number.isFinite(n)) {
        confForChip = String(Math.max(0, Math.min(100, n)));
      }
    }
    const prevBtnText = triggerBtn ? triggerBtn.textContent : "";
    if (triggerBtn) {
      triggerBtn.disabled = true;
      triggerBtn.textContent = "Attaching\u2026";
    }
    const statusEl = document.getElementById("lyric-search-status");
    const lyricOutputs = _lyricOut().readChecks("popover");
    try {
      const res = await api.lyricsApi.attach({
        audio_path: ctx.audioPath,
        lrclib_id: idNum,
        write_sidecar: lyricOutputs.lrc,
        write_metadata: lyricOutputs.metadata,
      });
      const data = await res.json();
      if (!data.ok) {
        if (statusEl) {
          statusEl.textContent = data.error || "Attach failed.";
          statusEl.classList.remove("hidden");
        }
        if (triggerBtn) {
          triggerBtn.disabled = false;
          triggerBtn.textContent = prevBtnText;
        }
        return;
      }
      ctx.attachedLrclibId = idNum;
      const anchor = ctx.anchorCard;
      if (anchor) {
        const tEl = anchor.querySelector(".track-status-title");
        const tTitle = ((tEl && tEl.textContent) || "").trim();
        const tNo = (anchor.dataset.trackNo || "").trim();
        if (tNo && tTitle) {
          _setTrackLyricsChip(
            tNo,
            tTitle,
            lyricTypeRaw,
            confForChip !== "" ? confForChip : null,
            (anchor.dataset.lyricAlbum || "").trim(),
            "Lrclib",
            _lyricDestinationFromOutputs(lyricOutputs),
          );
        }
      }
      if (ctx.lastSearchResults && ctx.lastSearchResults.length) {
        _lyricSearchRebuildVisibleRows();
      }
      if (statusEl) {
        statusEl.textContent = "Lyrics attached to file.";
        statusEl.classList.remove("hidden");
      }
      requestAnimationFrame(() => _positionLyricSearchPopover());
    } catch (_) {
      if (statusEl) {
        statusEl.textContent = "Network error.";
        statusEl.classList.remove("hidden");
      }
      if (triggerBtn) {
        triggerBtn.disabled = false;
        triggerBtn.textContent = prevBtnText;
      }
    }
  }

  async function _openLyricSearchModal(card) {
    const pop = document.getElementById("lyric-search-popover");
    if (!pop || !card) return;
    _closeAttachTrackPopover();
    _abortLyricSearchFetches();
    _closeLyricPreviewOverlay();
    const openSession = ++_lyricOpenSession;
    const titleEl = card.querySelector(".track-status-title");
    const displayTitle = ((titleEl && titleEl.textContent) || "").trim();
    const title = _lyricSearchTitleFromDisplay(displayTitle);
    _lyricOut().syncFromDownload();
    const artist = (card.dataset.lyricArtist || "").trim();
    const album = (card.dataset.lyricAlbum || "").trim();
    let durationSec = parseInt(String(card.dataset.durationSec || "0"), 10);
    if (Number.isNaN(durationSec)) durationSec = 0;
    const audioPath = (card.dataset.audioPath || "").trim();
    const openingPath = audioPath;

    const ti = document.getElementById("lyric-search-title");
    const ar = document.getElementById("lyric-search-artist");
    const al = document.getElementById("lyric-search-album");
    if (ti) ti.value = title;
    if (ar) ar.value = artist;
    if (al) al.value = album;
    _clearLyricSearchFieldErrors();

    const teRaw = card.dataset.trackExplicit;
    let trackExplicit = null;
    if (teRaw === "1") trackExplicit = true;
    else if (teRaw === "0") trackExplicit = false;
    _lyricSearchModalCtx = {
      audioPath,
      durationSec,
      trackExplicit,
      attachedLrclibId: null,
      previewingLrclibId: null,
      lastSearchResults: null,
      lyricSearchPagedShown: 0,
      anchorCard: card,
      openSession,
      searchSeq: 0,
    };
    _setLyricSearchAnchorCard(card);

    pop.classList.remove("hidden");
    pop.setAttribute("aria-hidden", "false");
    requestAnimationFrame(() => _positionLyricSearchPopover());

    const statusEl = document.getElementById("lyric-search-status");
    if (statusEl) statusEl.classList.add("hidden");
    const resultsEl = document.getElementById("lyric-search-results");
    _showLyricSearchResultsLoading(resultsEl);
    const pflag = document.getElementById("lyric-search-preview-flag");
    if (pflag) {
      pflag.classList.add("hidden");
      pflag.textContent = "";
    }

    _lyricAttachAbort = new AbortController();
    const attachSignal = _lyricAttachAbort.signal;

    let attachedLrclibId = null;
    if (audioPath) {
      try {
        const res = await api.lyricsApi.attachedId(audioPath, attachSignal);
        const data = await res.json();
        if (data.ok && data.attached_lrclib_id != null) {
          attachedLrclibId = data.attached_lrclib_id;
        }
      } catch (err) {
        if (err && err.name === "AbortError") return;
        /* ignore other attach-id errors */
      }
    }
    _lyricAttachAbort = null;
    if (
      !_lyricSearchModalCtx ||
      _lyricSearchModalCtx.openSession !== openSession ||
      _lyricSearchModalCtx.audioPath !== openingPath
    ) {
      return;
    }
    _lyricSearchModalCtx.attachedLrclibId = attachedLrclibId;
    await _runLyricSearchFromForm();
  }

  function _initLyricSearchModal() {
    _initLyricPreviewPlayer();
    _lyricOut().bindPopoverToggles();
    const pop = document.getElementById("lyric-search-popover");
    if (!pop) return;
    let lyricSearchMousedownTarget = null;
    document.addEventListener(
      "mousedown",
      (e) => {
        if (!pop || pop.classList.contains("hidden")) {
          lyricSearchMousedownTarget = null;
          return;
        }
        lyricSearchMousedownTarget = e.target;
      },
      true,
    );
    const closeBtn = document.getElementById("lyric-search-close");
    const previewCloseBtn = document.getElementById("lyric-search-preview-close");
    const submitBtn = document.getElementById("lyric-search-submit");
    if (closeBtn) closeBtn.addEventListener("click", () => _closeLyricSearchModal());
    if (previewCloseBtn) {
      previewCloseBtn.addEventListener("click", () => _closeLyricPreviewOverlay());
    }
    document.addEventListener("click", (e) => {
      if (!pop || pop.classList.contains("hidden")) return;
      const target = lyricSearchMousedownTarget || e.target;
      if (pop.contains(target)) return;
      if (e.target.closest && e.target.closest("#dl-track-status")) return;
      _closeLyricSearchModal();
    });
    window.addEventListener("resize", () => {
      if (!pop || pop.classList.contains("hidden") || !_lyricSearchModalCtx) {
        return;
      }
      _positionLyricSearchPopover();
    });
    let _lyricPopWinScrollRaf = null;
    window.addEventListener(
      "scroll",
      () => {
        if (!pop || pop.classList.contains("hidden") || !_lyricSearchModalCtx) {
          return;
        }
        if (_lyricPopWinScrollRaf != null) {
          cancelAnimationFrame(_lyricPopWinScrollRaf);
        }
        _lyricPopWinScrollRaf = requestAnimationFrame(() => {
          _lyricPopWinScrollRaf = null;
          _positionLyricSearchPopover();
        });
      },
      true,
    );
    if (submitBtn) submitBtn.addEventListener("click", () => _runLyricSearchFromForm());
    const lyricResultsScroll = document.getElementById("lyric-search-results");
    if (lyricResultsScroll && !lyricResultsScroll.dataset.pagingScrollBound) {
      lyricResultsScroll.dataset.pagingScrollBound = "1";
      lyricResultsScroll.addEventListener(
        "scroll",
        _onLyricSearchResultsScroll,
        { passive: true },
      );
    }
    const lyricTitleIn = document.getElementById("lyric-search-title");
    const lyricArtistIn = document.getElementById("lyric-search-artist");
    if (lyricTitleIn) {
      lyricTitleIn.addEventListener("input", () => {
        lyricTitleIn.classList.remove("lyric-search-input-invalid");
      });
    }
    if (lyricArtistIn) {
      lyricArtistIn.addEventListener("input", () => {
        lyricArtistIn.classList.remove("lyric-search-input-invalid");
      });
    }

    const list = document.getElementById("dl-track-status");
    if (!list) return;
    list.addEventListener("click", (e) => {
      const revealBtn = e.target.closest("button.track-dl-btn--reveal");
      if (revealBtn) {
        e.preventDefault();
        e.stopPropagation();
        const rcard = revealBtn.closest(".track-status-card");
        const rp = rcard && (rcard.dataset.audioPath || "").trim();
        if (!rp) return;
        void (async () => {
          try {
            const res = await api.utilityApi.revealInFolder(rp);
            await res.json();
          } catch (_) {
            /* ignore */
          }
        })();
        return;
      }
      if (e.target.closest(".confidence-chip-tooltip")) return;
      const wrap = e.target.closest(".confidence-chip-wrap");
      const lyricsChip = e.target.closest(".track-status-chip.lyrics-chip");
      if (!wrap && !lyricsChip) return;
      if (lyricsChip && lyricsChip.classList.contains("loading")) return;
      const rowCard = (wrap || lyricsChip).closest(".track-status-card");
      if (!rowCard) return;
      e.preventDefault();
      e.stopPropagation();
      _openLyricSearchModal(rowCard);
    });
  }

  function _persistDownloadHistoryAfterResult(ev, resAlb) {
    const ap = String(ev.audio_path || "").trim();
    if (!ap || String(ev.status || "").toLowerCase() !== "downloaded") return;
    const card = _ensureTrackStatusCard(
      ev.track_no,
      ev.title,
      false,
      undefined,
      resAlb,
    );
    if (!card) return;
    const tEl = card.querySelector(".track-status-title");
    let coverUrl = "";
    const img = card.querySelector(".track-status-art-img");
    if (img && img.getAttribute("src")) {
      coverUrl = img.getAttribute("src") || "";
    }
    const payload = {
      audio_path: ap,
      track_no: card.dataset.trackNo || String(ev.track_no || ""),
      title: (tEl && tEl.textContent) || String(ev.title || ""),
      cover_url: coverUrl,
      lyric_artist: card.dataset.lyricArtist || "",
      lyric_album: (card.dataset.lyricAlbum || resAlb || "").trim(),
      duration_sec: parseInt(card.dataset.durationSec || "0", 10) || 0,
      track_explicit:
        card.dataset.trackExplicit === "1"
          ? true
          : card.dataset.trackExplicit === "0"
            ? false
            : null,
      download_status: "downloaded",
      download_detail: String(ev.detail || ""),
      lyric_type: "",
      lyric_provider: "",
      lyric_confidence: "",
    };
    const sidEv = String(ev.slot_track_id || "").trim();
    const ridEv = String(ev.release_album_id || "").trim();
    if (sidEv) {
      payload.slot_track_id = sidEv;
      payload.pending_slot_cleanup_id = sidEv;
    }
    if (ridEv) payload.release_album_id = ridEv;
    payload.attach_search_eligible = card.dataset.attachSearchEligible === "1";
    const chip = card.querySelector(".lyrics-chip");
    if (chip) {
      const parts = (chip.className || "").split(/\s+/);
      const lt = parts.find((c) =>
        ["synced", "plain", "none", "error", "instrumental"].includes(c),
      );
      if (lt) payload.lyric_type = lt;
      payload.lyric_destination = _normalizeLyricDestination(
        chip.dataset.lyricDestination || "",
      );
    }
    _tsRegisterAudioPathAlbum(ap, (payload.lyric_album || "").trim());
    void api.historyApi.upsert(payload).catch(() => {});
  }

  function _persistPendingSlotDownloadHistory(ev, preCard, resAlb) {
    const sid = String(ev.slot_track_id || "").trim();
    const rid = String(ev.release_album_id || "").trim();
    const st = String(ev.status || "").toLowerCase();
    if (
      !preCard ||
      !sid ||
      !rid ||
      (st !== "purchase_only" && st !== "failed")
    ) {
      return;
    }
    const tEl = preCard.querySelector(".track-status-title");
    const img = preCard.querySelector(".track-status-art-img");
    let coverUrl = "";
    if (img && img.getAttribute("src")) {
      coverUrl = img.getAttribute("src") || "";
    }
    const payload = {
      audio_path: _GUI_PENDING_AUDIO_PREFIX + sid,
      track_no: preCard.dataset.trackNo || String(ev.track_no || ""),
      title: (tEl && tEl.textContent) || String(ev.title || ""),
      cover_url: coverUrl,
      lyric_artist: preCard.dataset.lyricArtist || "",
      lyric_album: (preCard.dataset.lyricAlbum || resAlb || "").trim(),
      duration_sec: parseInt(preCard.dataset.durationSec || "0", 10) || 0,
      track_explicit:
        preCard.dataset.trackExplicit === "1"
          ? true
          : preCard.dataset.trackExplicit === "0"
            ? false
            : null,
      download_status: st,
      download_detail: String(ev.detail || ""),
      lyric_type: "",
      lyric_provider: "",
      lyric_confidence: "",
      lyric_destination: "",
      slot_track_id: sid,
      release_album_id: rid,
      attach_search_eligible: true,
    };
    const chip = preCard.querySelector(".lyrics-chip");
    if (chip) {
      const parts = (chip.className || "").split(/\s+/);
      const lt = parts.find((c) =>
        ["synced", "plain", "none", "error", "instrumental"].includes(c),
      );
      if (lt) payload.lyric_type = lt;
      payload.lyric_destination = _normalizeLyricDestination(
        chip.dataset.lyricDestination || "",
      );
    }
    void api.historyApi.upsert(payload).catch(() => {});
  }

  async function _hydrateDownloadHistoryFromDb() {
    const list = document.getElementById("dl-track-status");
    if (!list) return;
    try {
      const res = await api.historyApi.list();
      const data = await res.json();
      if (!data.ok || !Array.isArray(data.items)) return;
      const items = data.items;
      const stick = _scrollContainerAtBottom(list);

      _tsSkipHistoryFilterApply = true;
      try {
        _tsTeardownVirtScroller();
        _trackStatusMap.clear();
        _tsOrderAll = [];
        _tsOrder = [];
        _tsKeyToIndex.clear();
        _tsDbItemByKey.clear();
        _tsAudioPathAlbum.clear();
        _tsActiveDlKeys.clear();
        list.innerHTML = "";

        for (let i = 0; i < items.length; i++) {
          const it = items[i];
          const alb = (it.lyric_album || "").trim();
          const parsed = _parseTrackRef(it.track_no || "", it.title || "");
          const key = _trackKey(parsed.trackNo, parsed.title, alb);
          _tsOrderAll.push(key);
          _tsDbItemByKey.set(key, it);
          const ap = (it.audio_path || "").trim();
          if (ap && !ap.startsWith(_GUI_PENDING_AUDIO_PREFIX)) {
            _tsRegisterAudioPathAlbum(ap, alb);
          }
        }

        if (items.length >= _TS_VIRT_THRESHOLD) {
          _tsVirtActive = true;
          _tsEnsureVirtInner(list);
          _tsVirtScrollHandlerBound = () => _tsVirtOnScroll();
          list.addEventListener("scroll", _tsVirtScrollHandlerBound, {
            passive: true,
          });
          window.addEventListener("resize", _tsVirtScrollHandlerBound, {
            passive: true,
          });
          if (window.ResizeObserver) {
            _tsVirtResizeObs = new ResizeObserver(() => _tsVirtOnScroll());
            _tsVirtResizeObs.observe(list);
          }
        } else {
          _tsVirtActive = false;
        }
      } finally {
        _tsSkipHistoryFilterApply = false;
      }

      _tsApplyHistoryFilter();

      if (items.length >= _TS_VIRT_THRESHOLD) {
        _tsUpdateVirtInnerHeight();
        requestAnimationFrame(() => {
          _tsVirtRender();
          _tsVirtMeasureRowH();
          _tsVirtRender();
          if (stick) list.scrollTop = list.scrollHeight;
        });
      } else {
        _tsSkipHistoryFilterApply = true;
        try {
          for (let i = 0; i < items.length; i++) {
            _tsApplyHistoryDbItemToNewCard(items[i]);
          }
        } finally {
          _tsSkipHistoryFilterApply = false;
        }
        _tsApplyHistoryFilter();
        if (stick) list.scrollTop = list.scrollHeight;
      }
    } catch (_) {
      _tsSkipHistoryFilterApply = false;
    }
  }

  async function _resetTrackStatusCards() {
    _closeLyricSearchModal();
    try {
      await api.historyApi.clear();
    } catch (_) {
      /* ignore */
    }
    const list = document.getElementById("dl-track-status");
    if (!list) return;
    _tsTeardownVirtScroller();
    _tsOrderAll = [];
    _tsOrder = [];
    _tsKeyToIndex.clear();
    _tsDbItemByKey.clear();
    _tsAudioPathAlbum.clear();
    _tsActiveDlKeys.clear();
    list.innerHTML = "";
    _trackStatusMap.clear();
    _queueHost.refreshAlbumQueueCardMetas();
    _tsUpdateErrorHistoryCountBadge();
  }

  function _positionClearHistoryConfirm() {
    const btn = document.getElementById("dl-clear-track-status");
    const pop = document.getElementById("dl-clear-history-confirm");
    if (!btn || !pop || pop.classList.contains("hidden")) return;
    const pad = 8;
    const r = btn.getBoundingClientRect();
    const vw = window.innerWidth;
    const mw = Math.min(280, vw - pad * 2);
    pop.style.top = `${Math.round(r.bottom + 6)}px`;
    let left = r.right - mw;
    left = Math.max(pad, Math.min(left, vw - pad - mw));
    pop.style.left = `${Math.round(left)}px`;
    pop.style.right = "auto";
  }

  function _clearHistoryBackdrop(e) {
    const pop = document.getElementById("dl-clear-history-confirm");
    const btn = document.getElementById("dl-clear-track-status");
    if (!pop || pop.classList.contains("hidden")) return;
    if ((btn && btn.contains(e.target)) || pop.contains(e.target)) return;
    _closeClearHistoryConfirm();
  }

  function _clearHistoryEsc(e) {
    if (e.key === "Escape") _closeClearHistoryConfirm();
  }

  function _closeClearHistoryConfirm() {
    const pop = document.getElementById("dl-clear-history-confirm");
    const btn = document.getElementById("dl-clear-track-status");
    if (!pop || pop.classList.contains("hidden")) return;
    pop.classList.add("hidden");
    document.removeEventListener("mousedown", _clearHistoryBackdrop);
    window.removeEventListener("resize", _positionClearHistoryConfirm);
    document.removeEventListener("keydown", _clearHistoryEsc);
    if (btn) {
      btn.setAttribute("aria-expanded", "false");
      btn.focus();
    }
  }

  function _openClearHistoryConfirm() {
    const pop = document.getElementById("dl-clear-history-confirm");
    const btn = document.getElementById("dl-clear-track-status");
    if (!pop || !btn) return;
    pop.classList.remove("hidden");
    btn.setAttribute("aria-expanded", "true");
    _positionClearHistoryConfirm();
    requestAnimationFrame(() => {
      document.getElementById("dl-clear-history-cancel")?.focus();
    });
    setTimeout(() => {
      document.addEventListener("mousedown", _clearHistoryBackdrop);
      window.addEventListener("resize", _positionClearHistoryConfirm);
      document.addEventListener("keydown", _clearHistoryEsc);
    }, 0);
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
      const { data } = api
        ? await api.getJson("/api/status")
        : await (async () => {
            const res = await api.statusApi.fetchRaw();
            return { data: await res.json() };
          })();
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
          const res = await api.utilityApi.browseFolder();
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
        const res = await api.setupApi.oauthStart();
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
            await QG.features.settings.settingsForm.loadIntoForm();
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
        const res = await api.setupApi.tokenLogin({
            user_id,
            user_auth_token,
            default_folder: folder,
            default_quality: quality,
          });
        const data = await res.json();
        if (data.ok) {
          showApp();
          updateStatus(true);
          await QG.features.settings.settingsForm.loadIntoForm();
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
        const res = await api.setupApi.setup({
            email,
            password,
            default_folder: folder,
            default_quality: quality,
          });
        const data = await res.json();
        if (data.ok) {
          showApp();
          updateStatus(true);
          await QG.features.settings.settingsForm.loadIntoForm();
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

  // ── Cover art mutual exclusivity ──────────────────────────
  // "Skip Cover Art" is incompatible with "Write Art to Tracks" and
      // "Full-Res Cover" | wire them up for whichever prefix is passed ('dl'/'cfg').
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
    _queueHost = QG.features.queue.internals.bootstrap({
      getTrackStatusMap: () => _tsDbItemByKey,
      guiPendingAudioPrefix: _GUI_PENDING_AUDIO_PREFIX,
      syncSearchQueuedHighlights: _syncSearchQueuedHighlights,
    });
    _queueHost.initUrlQueue();
    initCoverArtMutex("dl");

    QG.features.settings.downloadOptionsAutosave.bind();

    window._updateQueueBadge = function () {
      const badge = document.getElementById("dl-btn-badge");
      if (!badge) return;
      let total = 0;
      let hasUnknown = false;
      let hasArtist = false;
      
      if (_queueHost.textMode) {
        const val = document.getElementById("dl-urls").value || "";
        const lines = val.split(/[\n\r]+/).filter((l) => l.trim());
        total = lines.length;
        hasArtist = lines.some(l => l.includes("artist"));
      } else {
        _queueHost.urlQueue.forEach((qi) => {
          if (!qi.resolved) {
            if (qi.url && qi.url.includes("artist")) hasArtist = true;
            total += 1;
            return;
          }
          const r = qi.resolved;
          if (r.type === "artist") {
            hasArtist = true;
            if (r.raw_tracks === undefined && r.albums) hasUnknown = true;
          }
          total += _queueHost.remainingTracksContributionFromQueueItem(qi);
        });
      }
      
      if (total === 0 && !hasUnknown) {
        badge.classList.add("hidden");
        badge.textContent = "";
        badge.removeAttribute("aria-label");
      } else {
        badge.classList.remove("hidden");
        badge.textContent = hasUnknown ? `${total}+` : String(total);
        badge.setAttribute(
          "aria-label",
          `${badge.textContent} tracks to download (${hasUnknown ? "estimate" : "queue"})`,
        );
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
    let _dlTrackFinished = new Set();
    /** Queue URL → track keys still counted as purchase-only on the album badge. */
    let _purchaseOnlyKeysByUrl = new Map();

    window._qUrlForPurchaseSlot = (slotId) => {
      const sid = String(slotId || "").trim();
      if (!sid) return "";
      const pk = `sid:${sid}`;
      for (const [url, set] of _purchaseOnlyKeysByUrl.entries()) {
        if (set.has(pk)) return url;
      }
      return "";
    };

    const DL_TIP_PURCHASE_QUEUE =
      "Open album on Qobuz to purchase (full album required for these tracks)";
    const DL_TIP_NOT_STREAMABLE =
      "This release is not available for streaming on Qobuz. It may only be sold as a full album (purchase-only or region-restricted), open it on Qobuz to check.";
    const DL_TIP_QUEUE_URL_ERROR_GENERIC =
      "This queue item did not finish successfully. Check the activity log for details — causes include network errors, quality restrictions, or tracks that could not be downloaded.";

    function _findCardByUrl(url) {
      const cards = document.querySelectorAll("#dl-queue .queue-card");
      for (const c of cards) if (c.dataset.url === url) return c;
      return null;
    }

    function _syncQueueCardPurchaseIssues(qurl) {
      const q = String(qurl || "").trim();
      if (!q) return;
      const card = _findCardByUrl(q);
      if (!card) return;
      const info = card.querySelector(".queue-card-info");
      if (!info) return;
      const set = _purchaseOnlyKeysByUrl.get(q);
      const purchaseBadge = info.querySelector(".dl-error-badge.dl-purchase-badge");
      const failedBadge = info.querySelector(".dl-error-badge.dl-url-failed-badge");
      const qiHold = _queueHost.urlQueue.find((x) => x.url === q);
      const stayAlbum =
        qiHold != null && _queueHost.albumQueueItemNeedsToStayVisible(qiHold);

      if (!set || set.size === 0) {
        _purchaseOnlyKeysByUrl.delete(q);
        if (purchaseBadge) purchaseBadge.remove();
        if (!failedBadge && !stayAlbum) {
          card.classList.remove("dl-error");
        }
        const stillActive =
          card.classList.contains("dl-active") ||
          card.classList.contains("dl-pending");
        if (!stillActive && !failedBadge) {
          if (stayAlbum) {
            card.classList.add("dl-error");
            _queueHost.refreshAlbumQueueCardMetas();
            return;
          }
          card.classList.add("dl-done");
          setTimeout(() => _queueHost.removeFromQueue(q, card), 1400);
        }
        return;
      }

      let badge = purchaseBadge;
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "dl-error-badge dl-purchase-badge";
        badge.setAttribute("data-tip", DL_TIP_PURCHASE_QUEUE);
        badge.setAttribute("aria-label", DL_TIP_PURCHASE_QUEUE);
        badge.removeAttribute("title");
        info.appendChild(badge);
      }
      badge.textContent = `${set.size} ⚠ Purchase only`;
      badge.setAttribute("data-tip", DL_TIP_PURCHASE_QUEUE);
      badge.setAttribute("aria-label", DL_TIP_PURCHASE_QUEUE);
      badge.removeAttribute("title");
    }

    function _purchaseIssueSlotKey(ev, resAlb) {
      const sid = String(ev.slot_track_id || "").trim();
      if (sid) return `sid:${sid}`;
      return _trackKey(ev.track_no, ev.title, resAlb);
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
        label.textContent = `${_dlTrackDone} / ${cap} tracks`;
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
          <span class="dl-btn-body">
            <svg id="dl-btn-icon" width="15" height="15" viewBox="0 0 24 24" fill="currentColor"
                 aria-hidden="true">
              <rect x="4" y="4" width="6" height="16" rx="1.5"/>
              <rect x="14" y="4" width="6" height="16" rx="1.5"/>
            </svg>
            <span id="dl-btn-text">Pause</span>
          </span>`;
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
          <span class="dl-btn-body">
            <svg id="dl-btn-icon" width="15" height="15" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
              <polyline points="7 10 12 15 17 10"/>
              <line x1="12" y1="15" x2="12" y2="3"/>
            </svg>
            <span id="dl-btn-text">Start Download</span>
          </span>
          <span id="dl-btn-badge" class="dl-btn-badge hidden" aria-live="polite"></span>`;
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
        let trackNo = "";
        let title = "";
        let coverUrl = "";
        if (ev.track_no != null && String(ev.track_no).trim() !== "") {
          trackNo = String(ev.track_no).trim();
          title = String(ev.title || "").trim();
          coverUrl = String(ev.cover_url || "").trim();
        } else {
          const parsed = _parseTrackRef("", ev.title || "");
          trackNo = parsed.trackNo;
          title = parsed.title;
        }
        const evAlb =
          ev.lyric_album != null && String(ev.lyric_album).trim() !== ""
            ? String(ev.lyric_album).trim()
            : "";
        const _tcard = _ensureTrackStatusCard(
          trackNo,
          title,
          true,
          coverUrl,
          evAlb,
        );
        if (_tcard) {
          if (ev.lyric_artist != null && String(ev.lyric_artist).trim() !== "") {
            _tcard.dataset.lyricArtist = String(ev.lyric_artist).trim();
          }
          if (evAlb) _tcard.dataset.lyricAlbum = evAlb;
          if (ev.duration_sec != null && String(ev.duration_sec).trim() !== "") {
            const ds = parseInt(String(ev.duration_sec), 10);
            if (!Number.isNaN(ds)) _tcard.dataset.durationSec = String(ds);
          }
          if (typeof ev.track_explicit === "boolean") {
            _tcard.dataset.trackExplicit = ev.track_explicit ? "1" : "0";
            _setTrackContentRatingBadge(_tcard, ev.track_explicit);
          }
          if (_tcard.dataset.trackKey) _tsActiveDlKeys.add(_tcard.dataset.trackKey);
        }
        _setTrackDownloadChip(
          trackNo,
          title,
          "downloading",
          "",
          undefined,
          evAlb,
        );
        _updateProgress();
        _tsApplyHistoryFilter();
      } else if (ev.type === "track_download_progress") {
        const pa =
          ev.lyric_album != null && String(ev.lyric_album).trim() !== ""
            ? String(ev.lyric_album).trim()
            : "";
        _updateTrackDownloadProgress(
          ev.track_no,
          ev.title,
          ev.received,
          ev.total,
          pa,
        );
      } else if (ev.type === "track_result") {
        const resAlb = _lyricAlbumForTrackEv(ev);
        const qurl = String(ev.source_url || "").trim();
        const slotProgKey = _trackKey(ev.track_no, ev.title, resAlb);
        if (!_dlTrackFinished.has(slotProgKey)) {
          _dlTrackFinished.add(slotProgKey);
          _dlTrackDone++;
          if (!_dlTotalLocked && _dlTrackDone > _dlTrackTotal) {
            _dlTrackTotal = _dlTrackDone + 1;
          }
        }
        const st = String(ev.status || "").toLowerCase();
        const isFailed = st === "failed";
        const isPurchase = st === "purchase_only";
        const detail = String(ev.detail || "").trim();
        const ap = String(ev.audio_path || "").trim();
        const sidTrim = String(ev.slot_track_id || "").trim();
        const ridTrim = String(ev.release_album_id || "").trim();
        const preCard = _ensureTrackStatusCard(
          ev.track_no,
          ev.title,
          false,
          undefined,
          resAlb,
        );
        if (preCard && qurl) {
          preCard.dataset.queueSourceUrl = qurl;
        }
        if (preCard && sidTrim) {
          preCard.dataset.slotTrackId = sidTrim;
        }
        if (preCard && ridTrim) {
          preCard.dataset.releaseAlbumId = ridTrim;
        }
        if (preCard && sidTrim && ridTrim && (isPurchase || isFailed)) {
          preCard.dataset.attachSearchEligible = "1";
        }
        if (preCard && ap) {
          preCard.dataset.audioPath = ap;
          _tsRegisterAudioPathAlbum(ap, resAlb);
        }
        if (isPurchase && detail) {
          _setTrackDownloadChip(
            ev.track_no,
            ev.title,
            "Album Purchase Only",
            "failed",
            {
              href: detail,
              titleAttr: DL_TIP_PURCHASE_QUEUE,
              slotTrackId: sidTrim,
              releaseAlbumId: ridTrim,
            },
            resAlb,
          );
        } else {
          _setTrackDownloadChip(
            ev.track_no,
            ev.title,
            isFailed ? "failed" : "downloaded",
            isFailed ? "failed" : "done",
            undefined,
            resAlb,
          );
        }
        if (st === "downloaded" && preCard) {
          if (ev.substitute_attach === true) {
            preCard.dataset.attachSearchEligible = "1";
            // Mark resolved-by-search and delete any prior .missing.txt.
            const prevPlaceholderPath = (preCard.dataset.missingPlaceholderPath || "").trim();
            if (prevPlaceholderPath) {
              api.replacementApi.deleteResolutionFile({ file_path: prevPlaceholderPath }).catch(() => {});
              delete preCard.dataset.missingPlaceholderPath;
            }
            preCard.dataset.resolvedBy = "search";
            _syncResolutionButtonStates(preCard);
          } else if (ap.toLowerCase().endsWith(".missing.txt")) {
            preCard.dataset.attachSearchEligible = "1";
            preCard.dataset.resolvedBy = "placeholder";
            _syncResolutionButtonStates(preCard);
          } else {
            delete preCard.dataset.attachSearchEligible;
          }
        }
        if (st === "downloaded" && ap) {
          _persistDownloadHistoryAfterResult(ev, resAlb);
        } else if (
          preCard &&
          sidTrim &&
          ridTrim &&
          ((isPurchase && detail) || isFailed)
        ) {
          _persistPendingSlotDownloadHistory(ev, preCard, resAlb);
        }
        if (preCard) {
          _tsStoreDbItemFromTrackResult(ev, resAlb, preCard);
          if (preCard.dataset.trackKey) {
            _tsActiveDlKeys.delete(preCard.dataset.trackKey);
          }
          _tsVirtOnScroll();
        }
        const pk = _purchaseIssueSlotKey(ev, resAlb);
        if (isPurchase && qurl) {
          let pset = _purchaseOnlyKeysByUrl.get(qurl);
          if (!pset) {
            pset = new Set();
            _purchaseOnlyKeysByUrl.set(qurl, pset);
          }
          pset.add(pk);
          const qcard = _findCardByUrl(qurl);
          if (qcard) {
            qcard.classList.remove("dl-active", "dl-pending", "dl-done");
            qcard.classList.add("dl-error");
            _syncQueueCardPurchaseIssues(qurl);
          }
        } else if (st === "downloaded" && qurl) {
          const pset = _purchaseOnlyKeysByUrl.get(qurl);
          if (pset && pset.delete(pk) && pset.size === 0) {
            _purchaseOnlyKeysByUrl.delete(qurl);
          }
          _syncQueueCardPurchaseIssues(qurl);
        }
        _updateProgress();
        _tsApplyHistoryFilter();
        _queueHost.refreshAlbumQueueCardMetas();
      } else if (ev.type === "track_lyrics") {
        let albLy = "";
        const apEv = String(ev.audio_path || "").trim();
        if (apEv && _tsAudioPathAlbum.has(apEv)) {
          albLy = _tsAudioPathAlbum.get(apEv) || "";
        }
        if (!albLy && apEv) {
          const cards = document.querySelectorAll(
            "#dl-track-status .track-status-card",
          );
          for (let i = 0; i < cards.length; i++) {
            if ((cards[i].dataset.audioPath || "").trim() === apEv) {
              albLy = (cards[i].dataset.lyricAlbum || "").trim();
              break;
            }
          }
        }
        if (!albLy) albLy = _lyricAlbumForTrackEv(ev);
        _setTrackLyricsChip(
          ev.track_no,
          ev.title,
          ev.lyric_type || "none",
          ev.confidence,
          albLy,
          ev.provider,
          ev.lyric_destination || "",
        );
        const lk = _trackKey(
          _normalizeTrackNo(ev.track_no),
          _normalizeTrackTitle(ev.title || ""),
          albLy,
        );
        const rowSnap = lk ? _tsDbItemByKey.get(lk) : null;
        if (rowSnap) {
          rowSnap.lyric_type = String(ev.lyric_type || "none").toLowerCase();
          rowSnap.lyric_provider =
            ev.provider != null ? String(ev.provider) : "";
          rowSnap.lyric_confidence =
            ev.confidence != null && String(ev.confidence).trim() !== ""
              ? String(ev.confidence).trim()
              : "";
          rowSnap.lyric_destination = _normalizeLyricDestination(
            ev.lyric_destination || "",
          );
          _tsApplyHistoryFilter();
        }
      } else if (ev.type === "url_done") {
        _dlDone++;
        // Sync track total upward if real count exceeded estimate
        if (_dlTrackDone > _dlTrackTotal) _dlTrackTotal = _dlTrackDone;
        _updateProgress();
        const card = _findCardByUrl(ev.url);
        if (card) {
          card.classList.remove("dl-active", "dl-pending");
          const qi = _queueHost.urlQueue.find((x) => x.url === ev.url);
          const stayAlbum =
            qi != null && _queueHost.albumQueueItemNeedsToStayVisible(qi);
          if (
            card.querySelector(".dl-purchase-badge") ||
            stayAlbum
          ) {
            card.classList.add("dl-error");
          } else {
            card.classList.add("dl-done");
            setTimeout(() => _queueHost.removeFromQueue(ev.url, card), 1400);
          }
        }
      } else if (ev.type === "url_error") {
        _dlDone++;
        _updateProgress();
        const card = _findCardByUrl(ev.url);
        if (card) {
          card.classList.remove("dl-active", "dl-pending");
          card.classList.add("dl-error");
          const info = card.querySelector(".queue-card-info");
          if (info) {
            let badge = info.querySelector(".dl-error-badge.dl-url-failed-badge");
            if (!badge) {
              badge = document.createElement("span");
              badge.className = "dl-error-badge dl-url-failed-badge";
              info.appendChild(badge);
            }
            const detail = String(ev.detail || "").trim();
            const isNonStream = detail === "non_streamable";
            const tip = isNonStream
              ? DL_TIP_NOT_STREAMABLE
              : DL_TIP_QUEUE_URL_ERROR_GENERIC;
            badge.textContent = isNonStream
              ? "⚠ Not streamable"
              : "⚠ Download issue";
            badge.setAttribute("data-tip", tip);
            badge.setAttribute("aria-label", tip);
            badge.removeAttribute("title");
          }
        }
      } else if (ev.type === "dl_complete") {
        // Snap progress to 100% and show final count
        _dlTrackTotal = Math.max(_dlTrackTotal, _dlTrackDone);
        const fill = document.getElementById("dl-progress-fill");
        const holdProg = Boolean(ev.cancelled || ev.paused);
        if (fill) {
          fill.style.width = holdProg ? fill.style.width : "100%";
        }
        const label = document.getElementById("dl-progress-label");
        if (label) {
          label.textContent = `${_dlTrackDone} track${_dlTrackDone !== 1 ? "s" : ""}`;
          label.title = "";
        }
        // Reset cards still marked as active once the graceful stop settles
        if (ev.cancelled || ev.paused) {
          document
            .querySelectorAll(
              "#dl-queue .queue-card.dl-active, #dl-queue .queue-card.dl-pending",
            )
            .forEach((c) => c.classList.remove("dl-active", "dl-pending"));
        }
        // Clear the pausing-state inline styles before restoring button
        const dlBtn = document.getElementById("dl-btn");
        dlBtn.style.opacity = "";
        dlBtn.style.cursor = "";
        dlBtn.style.pointerEvents = "";
        _setDownloadingState(false);
        _queueHost.refreshAlbumQueueCardMetas();
      }
    };

    document.getElementById("dl-btn").addEventListener("click", async () => {
      const dlBtn = document.getElementById("dl-btn");

      // Pause if already running (graceful stop; same as /api/pause)
      if (dlBtn.dataset.state === "downloading") {
        dlBtn.dataset.state = "pausing";
        const te = document.getElementById("dl-btn-text");
        if (te) te.textContent = "Pausing…";
        dlBtn.disabled = false;
        dlBtn.style.opacity = "0.6";
        dlBtn.style.cursor = "default";
        dlBtn.style.pointerEvents = "none";
        try {
          await api.downloadApi.pause();
        } catch (_) {
          dlBtn.dataset.state = "downloading";
          dlBtn.style.opacity = "";
          dlBtn.style.cursor = "";
          dlBtn.style.pointerEvents = "";
          _setDownloadingState(true);
        }
        return;
      }
      if (dlBtn.dataset.state === "pausing") return;

      // Collect URLs
      let urls;
      if (_queueHost.textMode) {
        urls = document.getElementById("dl-urls").value.trim();
      } else {
        urls = _queueHost.urlQueue.map((q) => q.url).join("\n");
      }
      if (!urls) {
        return;
      }

      const payload = {
        urls,
        quality: document.getElementById("dl-quality").value || null,
        directory: document.getElementById("dl-directory").value.trim() || null,
        embed_art: document.getElementById("dl-embed-art").checked,
        lyrics_enabled: document.getElementById("dl-lyrics-enabled").checked,
        lyrics_embed_metadata: document.getElementById("dl-lyrics-embed-metadata")
          .checked,
        og_cover: document.getElementById("dl-og-cover").checked,
        no_cover: document.getElementById("dl-no-cover").checked,
        albums_only: document.getElementById("dl-albums-only").checked,
        no_m3u: document.getElementById("dl-no-m3u").checked,
        no_fallback: document.getElementById("dl-no-fallback").checked,
        no_db: document.getElementById("dl-no-db").checked,
        smart_discography: document.getElementById("dl-smart-discography")
          .checked,
        fix_md5s: document.getElementById("dl-fix-md5s").checked,
        no_credits: !document.getElementById("dl-digital-booklet").checked,
        native_lang: document.getElementById("dl-native-lang").checked,
        segmented_fallback: document.getElementById("dl-segmented-fallback")
          .checked,
        multiple_disc_prefix:
          document.getElementById("dl-multiple-disc-prefix").value.trim() ||
          null,
        multiple_disc_one_dir: !document.getElementById("dl-multiple-disc-one-dir")
          .checked,
        multiple_disc_track_format:
          document
            .getElementById("dl-multiple-disc-track-format")
            .value.trim() || null,
        max_workers:
          parseInt(document.getElementById("dl-max-workers").value, 10) || 1,
        delay_seconds:
          parseInt(document.getElementById("dl-delay-seconds").value, 10) || 0,
        folder_format:
          document.getElementById("dl-folder-format").value.trim() || null,
        track_format:
          document.getElementById("dl-track-format").value.trim() || null,
        no_album_artist_tag:
          document.getElementById("dl-tag-album-artist").checked === false,
        no_album_title_tag:
          document.getElementById("dl-tag-album-title").checked === false,
        no_track_artist_tag:
          document.getElementById("dl-tag-track-artist").checked === false,
        no_track_title_tag:
          document.getElementById("dl-tag-track-title").checked === false,
        no_release_date_tag:
          document.getElementById("dl-tag-release-date").checked === false,
        no_media_type_tag:
          document.getElementById("dl-tag-media-type").checked === false,
        no_genre_tag: document.getElementById("dl-tag-genre").checked === false,
        no_track_number_tag:
          document.getElementById("dl-tag-track-number").checked === false,
        no_track_total_tag:
          document.getElementById("dl-tag-track-total").checked === false,
        no_disc_number_tag:
          document.getElementById("dl-tag-disc-number").checked === false,
        no_disc_total_tag:
          document.getElementById("dl-tag-disc-total").checked === false,
        no_composer_tag:
          document.getElementById("dl-tag-composer").checked === false,
        no_explicit_tag:
          document.getElementById("dl-tag-explicit").checked === false,
        no_copyright_tag:
          document.getElementById("dl-tag-copyright").checked === false,
        no_label_tag: document.getElementById("dl-tag-label").checked === false,
        no_upc_tag: document.getElementById("dl-tag-upc").checked === false,
        no_isrc_tag: document.getElementById("dl-tag-isrc").checked === false,
        tag_title_from_track_format: document.getElementById(
          "dl-meta-title-from-track-format",
        ).checked,
        tag_album_from_folder_format: document.getElementById(
          "dl-meta-album-from-folder-format",
        ).checked,
      };

      try {
        const res = await api.downloadApi.start(payload);
        const data = await res.json();
        if (data.ok) {
          // Mark all visible queue cards as pending (keep them in the list)
          _dlTotal = data.queued;
          _dlDone = 0;
          _dlTrackTotal = _queueHost.textMode ? data.queued : _queueHost.calcProgressDenominatorFromQueue();
          _dlTrackDone = 0;
          _dlTotalLocked = false;
          _dlTrackFinished = new Set();
          _purchaseOnlyKeysByUrl = new Map();
          document.querySelectorAll("#dl-queue .queue-card").forEach((c) => {
            c.classList.add("dl-pending");
          });
          _setDownloadingState(true);
        }
      } catch (_) {
        /* ignore */
      }
    });

    const clearTrackStatusBtn = document.getElementById("dl-clear-track-status");
    const clearHistoryConfirm = document.getElementById("dl-clear-history-confirm");
    const clearHistoryCancel = document.getElementById("dl-clear-history-cancel");
    const clearHistoryDo = document.getElementById("dl-clear-history-confirm-do");
    if (clearTrackStatusBtn && clearHistoryConfirm) {
      clearTrackStatusBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (!clearHistoryConfirm.classList.contains("hidden")) {
          _closeClearHistoryConfirm();
          return;
        }
        _openClearHistoryConfirm();
      });
    }
    clearHistoryCancel?.addEventListener("click", () => {
      _closeClearHistoryConfirm();
    });
    clearHistoryDo?.addEventListener("click", async () => {
      _closeClearHistoryConfirm();
      await _resetTrackStatusCards();
    });
    _initLyricSearchModal();
    _initAttachTrackSearchPopover();
    _initDownloadHistorySegment();
    void (async () => {
      await _queueHost.restoreFromServer();
      await _hydrateDownloadHistoryFromDb();
      _queueHost.refreshAlbumQueueCardMetas();
    })();

    window.QobuzGui.features = window.QobuzGui.features || {};
    window.QobuzGui.features.history = {
      countDownloadedForRelease(releaseAlbumId) {
        return _queueHost.countHistoryDownloadedForRelease(releaseAlbumId);
      },
      applyFilter() {
        return _tsApplyHistoryFilter();
      },
    };
    window.QobuzGui.features.queue.install({
      addUrl(url) {
        return _queueHost.addUrlToQueue(url);
      },
      removeUrl(url) {
        return _queueHost.removeFromQueueByUrl(url);
      },
      hasUrl(url) {
        return _queueHost.urlQueue.some((q) => q.url === url);
      },
      getQueuedUrlSet() {
        return _queueHost.queuedUrlSetForSearchHighlight();
      },
      handleDrop: window._handleDrop,
      handleDropText: window._handleDropText,
      updateBadge: window._updateQueueBadge,
    });
  }

  // ── Settings tab ──────────────────────────────────────────

  function initSettings() {
    const feedback = document.getElementById("settings-popover-feedback");
    QG.features.feedback.issueReport.init(checkStatus);

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
        const res = await api.setupApi.oauthStart();
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
            await QG.features.settings.settingsForm.loadIntoForm();
            QG.ui.feedbackMessage.show(feedback, "Reconnected successfully.", true);
          }
        }, 2000);
      } catch (e) {
        QG.ui.feedbackMessage.show(feedback, e.message, false);
        reauthText.textContent = "Re-login with Qobuz";
        reauthSpinner.classList.add("hidden");
        reauthBtn.disabled = false;
      }
    });

    const checkUpdBtn = document.getElementById("settings-check-updates-btn");
    const updFeedback = document.getElementById("settings-update-feedback");
    if (checkUpdBtn && updFeedback) {
      checkUpdBtn.addEventListener("click", async () => {
        const originalText = checkUpdBtn.dataset.defaultText || checkUpdBtn.textContent;
        checkUpdBtn.dataset.defaultText = originalText;
        checkUpdBtn.disabled = true;
        updFeedback.className = "feedback-msg hidden";
        checkUpdBtn.classList.remove("settings-check-updates-btn--ok", "settings-check-updates-btn--err");
        checkUpdBtn.textContent = "Checking...";
        try {
          const data = await window.QobuzGui.features.updateBanner.refreshUpdateCheck(
            true,
          );
          if (!data) throw new Error("Network error");
          if (data.skipped && data.reason === "repo_not_configured") {
            QG.ui.feedbackMessage.showButton(
              checkUpdBtn,
              "Update source not configured (see qobuz_dl/version.py).",
              false,
            );
          } else if (!data.ok) {
            QG.ui.feedbackMessage.showButton(checkUpdBtn, data.error || "Check failed", false);
          } else if (data.update_available) {
            let updateMsg = "Update available: v" + data.latest_version;
            if (data.download_url && !data.can_auto_install) {
              updateMsg += data.frozen
                ? " (manual install on this platform)"
                : " (run the packaged desktop build to auto-install)";
            }
            QG.ui.feedbackMessage.showButton(checkUpdBtn, updateMsg, true);
          } else {
            QG.ui.feedbackMessage.showButton(checkUpdBtn, "You're on the latest version.", true);
          }
        } catch (e) {
          QG.ui.feedbackMessage.showButton(checkUpdBtn, e.message || "Check failed", false);
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
          const res = await api.setupApi.purge();
          const data = await res.json();
          if (!data.ok) throw new Error(data.error || "Purge failed");
          QG.ui.feedbackMessage.show(feedback, "Database purged.", true);
        } catch (e) {
          QG.ui.feedbackMessage.show(feedback, e.message, false);
        }
      });
  }

  // ── Init ─────────────────────────────────────────────────
  async function init() {
    window.QobuzGui.ui.collapses.init();
    window.QobuzGui.ui.resetButtons.init();
    initAuthTabs();
    initSetup();
    initBrowseButtons();
    initDownload();
    QG.features.search.init();
    initSettings();
    window.QobuzGui.features.updateBanner.init();
    setTimeout(() => {
      void window.QobuzGui.features.updateBanner.refreshUpdateCheck(true);
    }, 800);

    const status = await checkStatus();
    if (status && (status.ready || status.has_config)) {
      showApp();
      if (!status.ready && status.has_config) {
        // Config exists but client not init yet | auto-connect
        const dot = document.getElementById("status-dot");
        const label = document.getElementById("status-label");
        dot.className = "status-dot connecting";
        label.textContent = "Connecting…";
        try {
          const res = await api.setupApi.connect();
          const data = await res.json();
          updateStatus(data.ok);
        } catch (e) {
          updateStatus(false);
        }
      }
      await QG.features.settings.settingsForm.loadIntoForm();
    } else {
      showSetup();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("DOMContentLoaded", () => {
    window.QobuzGui.features.formatBuilder.formatTooltips.init();
    window.QobuzGui.ui.donationPopover.init();
    window.QobuzGui.ui.globalTooltip.init();
    window.QobuzGui.ui.textFieldContextMenu.init();
  });
})();
