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
  const _ic = QG.core.icons;
  const _MISSING_PLACEHOLDER_BTN_TIP = _ic.missingPlaceholderBtnTip;
  const _EXPLICIT_BADGE_SVG = _ic.explicitBadgeSvg;

  function _lyricSearch() {
    return QG.features.lyrics.search;
  }

  function _syncSearchQueuedHighlights() {
    if (QG.features.search && QG.features.search.syncQueuedHighlights) {
      QG.features.search.syncQueuedHighlights();
    }
  }

  function _hist() {
    return QG.features.history;
  }

  function _cardHasResolvedRealAudio(card) {
    if (!card) return false;
    const ap = (card.dataset.audioPath || "").trim();
    if (!ap || ap.startsWith(_GUI_PENDING_AUDIO_PREFIX)) return false;
    return true;
  }

  function _dl() {
    return QG.features.download;
  }

  function _dlQueueIssues() {
    return _downloadQueueIssuesHost;
  }

  function _dlProgress() {
    return _downloadProgressHost;
  }

  function _dlStatus() {
    return _downloadStatusHost;
  }

  function _dlStartPause() {
    return _downloadStartPauseHost;
  }

  function _dispatchDownloadStatusEvent(ev) {
    const status = _downloadStatusHost;
    if (status && typeof status.handleStatus === "function") {
      status.handleStatus(ev);
      return;
    }
    if (typeof window._handleDlStatus === "function") {
      window._handleDlStatus(ev);
    }
  }

  function _startDownloadSse() {
    if (_downloadSseHost && typeof _downloadSseHost.startSSE === "function") {
      _downloadSseHost.startSSE();
    }
  }

  function _getHistoryDbMap() {
    return _historyStoreHost
      ? _historyStoreHost.getDbItemByKey()
      : _emptyHistoryMap;
  }

  let _queueHost = null;
  /** D1C queue purchase-only / URL error badge host (set in `initDownload()`). */
  let _downloadQueueIssuesHost = null;
  /** D1B progress bar + Start/Pause button host (set in `initDownload()`). */
  let _downloadProgressHost = null;
  /** D1D SSE status handler host (set in `initDownload()`). */
  let _downloadStatusHost = null;
  /** D1E Start/Pause button host (set in `initDownload()`). */
  let _downloadStartPauseHost = null;
  /** D1F SSE / EventSource host (set in `initDownload()`). */
  let _downloadSseHost = null;
  /** H5 virtualization host (set in `initDownload()`). */
  let _historyVirtHost = null;
  /** H6 hydrate/persist host (set in `initDownload()`). */
  let _historyStoreHost = null;
  /** C1 clear-history confirm host (set in `initDownload()`). */
  let _historyClearConfirmHost = null;
  const _emptyHistoryMap = new Map();
  /** R2 attach-track popover host (set in `initDownload()`). */
  let _replacementAttachHost = null;
  /** R3 resolution button sync host (set in `initDownload()`). */
  let _replacementResolutionHost = null;
  /** R3 missing-placeholder host (set in `initDownload()`). */
  let _replacementPlaceholderHost = null;

  /** H3 card rendering host (set in `initDownload()`). */
  let _historyCardHost = null;

  let _trackStatusMap = new Map();
  /** Visible row keys (filtered for virtualized list); mirrors `_tsOrderAll` when not virtual or when showing all. */
  let _tsOrder = [];
  /** Full row keys oldest → newest (unfiltered). */
  let _tsOrderAll = [];
  let _tsKeyToIndex = new Map();
  let _tsActiveDlKeys = new Set();
  /** `"all"` | `"errors"` — owned by history filter module after bootstrap. */
  let _historyFilterHost = null;
  /** Skip redundant filter passes while bulk-loading history from DB. */
  let _tsSkipHistoryFilterApply = false;

  function _scrollContainerAtBottom(el, slackPx) {
    return QG.core.dom.scrollContainerAtBottom(el, slackPx);
  }

  function _normalizeTrackNo(trackNo) {
    return QG.core.trackIdentity.normalizeTrackNo(trackNo);
  }

  function _normalizeTrackTitle(title) {
    return QG.core.trackIdentity.normalizeTrackTitle(title);
  }

  function _parseTrackRef(trackNo, title) {
    return QG.core.trackIdentity.parseTrackRef(trackNo, title);
  }

  function _trackKey(trackNo, title, lyricAlbum, audioPath) {
    return QG.core.trackIdentity.trackKey(
      trackNo,
      title,
      lyricAlbum,
      audioPath,
    );
  }

  function _tsResetListForHydrate(list) {
    if (_historyVirtHost) _historyVirtHost.teardownVirtScroller();
    _trackStatusMap.clear();
    _tsOrderAll = [];
    _tsOrder = [];
    _tsKeyToIndex.clear();
    _tsActiveDlKeys.clear();
    if (list) list.innerHTML = "";
  }

  function _tsApplyHistoryFilter() {
    if (_historyFilterHost) _historyFilterHost.applyFilter();
  }

  function _tsUpdateErrorHistoryCountBadge(optStemCtx) {
    if (_historyFilterHost) {
      _historyFilterHost.updateErrorHistoryCountBadge(optStemCtx);
    }
  }

  function _initDownloadHistorySegment() {
    if (_historyFilterHost) _historyFilterHost.initDownloadHistorySegment();
  }

  function _tsRegisterAudioPathAlbum(audioPath, lyricAlbum) {
    if (_historyStoreHost) {
      _historyStoreHost.registerAudioPathAlbum(audioPath, lyricAlbum);
    }
  }

  function _tsRebuildKeyIndex() {
    _tsKeyToIndex.clear();
    for (let i = 0; i < _tsOrder.length; i++) {
      _tsKeyToIndex.set(_tsOrder[i], i);
    }
  }

  function _tsApplyHistoryDbItemToCard(card, it) {
    if (_historyStoreHost) {
      _historyStoreHost.applyHistoryDbItemToCard(card, it);
    }
  }

  function _tsMountDbItemAtIndex(it, index) {
    if (!_historyVirtHost) return;
    const inner = _historyVirtHost.getVirtInnerEl();
    if (!inner) return;
    const alb = (it.lyric_album || "").trim();
    const { card, key } = _buildTrackStatusCardEl(
      it.track_no || "",
      it.title || "",
      alb,
      it.cover_url || "",
      it.audio_path || "",
    );
    _trackStatusMap.set(key, card);
    inner.appendChild(card);
    _tsApplyHistoryDbItemToCard(card, it);
    _historyVirtHost.positionVirtCard(card, index);
  }

  function _tsRemapCardTrackKey(card) {
    if (!card || !QG.core.trackIdentity.rebindCardTrackKey) return "";
    return QG.core.trackIdentity.rebindCardTrackKey(
      _trackStatusMap,
      card,
      _tsOrderAll,
    );
  }

  function _lyricAlbumForTrackEv(ev) {
    if (_historyStoreHost) {
      return _historyStoreHost.lyricAlbumForTrackEv(ev);
    }
    return "";
  }

  function _setTrackCardCover(card, coverUrl) {
    if (_historyCardHost) _historyCardHost.setTrackCardCover(card, coverUrl);
  }

  function _buildTrackStatusCardEl(trackNo, title, lyricAlbum, coverUrl) {
    return _historyCardHost
      ? _historyCardHost.buildTrackStatusCardEl(
          trackNo,
          title,
          lyricAlbum,
          coverUrl,
        )
      : { card: null, key: "", parsed: { trackNo: "", title: "" }, alb: "" };
  }

  function _ensureTrackStatusCard(
    trackNo,
    title,
    createNew = false,
    coverUrl,
    lyricAlbum,
    slotTrackId,
  ) {
    return _historyCardHost
      ? _historyCardHost.ensureTrackStatusCard(
          trackNo,
          title,
          createNew,
          coverUrl,
          lyricAlbum,
          slotTrackId,
        )
      : null;
  }

  function _setTrackContentRatingBadge(card, trackExplicitKnown) {
    if (_historyCardHost) {
      _historyCardHost.setTrackContentRatingBadge(card, trackExplicitKnown);
    }
  }

  function _setTrackDownloadChip(
    trackNo,
    title,
    statusText,
    cls,
    linkOpts,
    lyricAlbum,
  ) {
    if (_historyCardHost) {
      _historyCardHost.setTrackDownloadChip(
        trackNo,
        title,
        statusText,
        cls,
        linkOpts,
        lyricAlbum,
      );
    }
  }

  function _updateTrackDownloadProgress(
    trackNo,
    title,
    received,
    total,
    lyricAlbum,
  ) {
    if (_historyCardHost) {
      _historyCardHost.updateTrackDownloadProgress(
        trackNo,
        title,
        received,
        total,
        lyricAlbum,
      );
    }
  }

  function _normalizeLyricDestination(destination) {
    return _historyCardHost
      ? _historyCardHost.normalizeLyricDestination(destination)
      : "";
  }

  function _lyricDestinationFromOutputs(outputs) {
    return _historyCardHost
      ? _historyCardHost.lyricDestinationFromOutputs(outputs)
      : "";
  }

  function _setTrackLyricsChip(
    trackNo,
    title,
    lyricType,
    confidence,
    lyricAlbum,
    lyricProvider,
    lyricDestination,
    audioPath,
  ) {
    if (_historyCardHost) {
      _historyCardHost.setTrackLyricsChip(
        trackNo,
        title,
        lyricType,
        confidence,
        lyricAlbum,
        lyricProvider,
        lyricDestination,
        audioPath,
      );
    }
  }

  /** LRCLIB duration delta vs reference (±2s hidden; same threshold as LRCLIB matching). */
  function _formatLyricDeltaSec(sec) {
    return QG.core.format.formatLyricDeltaSec(sec);
  }

  async function _resetTrackStatusCards() {
    _lyricSearch().close();
    if (_historyCardHost?.dismissAllConfidenceTooltips) {
      _historyCardHost.dismissAllConfidenceTooltips();
    }
    const list = document.getElementById("dl-track-status");
    if (_historyStoreHost) {
      await _historyStoreHost.clearServerAndLocal(list);
    } else if (list) {
      _tsResetListForHydrate(list);
    }
    _queueHost.refreshAlbumQueueCardMetas();
    _tsUpdateErrorHistoryCountBadge();
    if (
      _downloadQueueIssuesHost &&
      typeof _downloadQueueIssuesHost.clearPurchaseIssues === "function"
    ) {
      _downloadQueueIssuesHost.clearPurchaseIssues();
    }
    if (
      _downloadQueueIssuesHost &&
      typeof _downloadQueueIssuesHost.syncAllTrackIssues === "function"
    ) {
      _downloadQueueIssuesHost.syncAllTrackIssues();
    }
  }

  // ── Download tab ──────────────────────────────────────────

  function initDownload() {
    _queueHost = QG.features.queue.internals.bootstrap({
      getTrackStatusMap: _getHistoryDbMap,
      guiPendingAudioPrefix: _GUI_PENDING_AUDIO_PREFIX,
      syncSearchQueuedHighlights: _syncSearchQueuedHighlights,
    });
    if (
      QG.features.download &&
      QG.features.download.internals &&
      typeof QG.features.download.internals.bootstrapQueueIssueBadges ===
        "function"
    ) {
      _downloadQueueIssuesHost =
        QG.features.download.internals.bootstrapQueueIssueBadges({
          trackKey: (trackNo, title, album) =>
            _trackKey(trackNo, title, album),
          getDbItemByKey: _getHistoryDbMap,
          findQueueItemByUrl: (q) =>
            _queueHost.urlQueue.find((x) => x.url === q) || null,
          releaseAlbumIdFromQueueItem: (qi) =>
            _queueHost.releaseAlbumIdFromQueueItem(qi),
          albumQueueItemNeedsToStayVisible: (qi) =>
            _queueHost.albumQueueItemNeedsToStayVisible(qi),
          refreshAlbumQueueCardMetas: () =>
            _queueHost.refreshAlbumQueueCardMetas(),
          removeFromQueue: (url, card) =>
            _queueHost.removeFromQueue(url, card),
        });
    }
    if (
      QG.features.download &&
      QG.features.download.internals &&
      typeof QG.features.download.internals.bootstrapProgress === "function"
    ) {
      _downloadProgressHost =
        QG.features.download.internals.bootstrapProgress({
          updateQueueBadge: () => {
            if (typeof window._updateQueueBadge === "function") {
              window._updateQueueBadge();
            }
          },
        });
    }
    if (
      QG.features.history &&
      QG.features.history.internals &&
      typeof QG.features.history.internals.bootstrapVirtualization ===
        "function"
    ) {
      _historyVirtHost =
        QG.features.history.internals.bootstrapVirtualization({
          getOrder: () => _tsOrder,
          getKeyToIndex: () => _tsKeyToIndex,
          getCardMap: () => _trackStatusMap,
          getDbItemByKey: _getHistoryDbMap,
          getActiveDlKeys: () => _tsActiveDlKeys,
          mountDbItemAtIndex: _tsMountDbItemAtIndex,
        });
    }
    if (
      QG.features.history &&
      QG.features.history.internals &&
      typeof QG.features.history.internals.bootstrapFilters === "function"
    ) {
      _historyFilterHost = QG.features.history.internals.bootstrapFilters({
        guiPendingAudioPrefix: _GUI_PENDING_AUDIO_PREFIX,
        getActiveDlKeys: () => _tsActiveDlKeys,
        getCardMap: () => _trackStatusMap,
        getDbItemByKey: _getHistoryDbMap,
        getOrderAll: () => _tsOrderAll,
        getOrder: () => _tsOrder,
        setOrder: (order) => {
          _tsOrder = order;
        },
        getSkipHistoryFilterApply: () => _tsSkipHistoryFilterApply,
        isVirtActive: () =>
          _historyVirtHost ? _historyVirtHost.isVirtActive() : false,
        getVirtInnerEl: () =>
          _historyVirtHost ? _historyVirtHost.getVirtInnerEl() : null,
        rebuildKeyIndex: _tsRebuildKeyIndex,
        updateVirtInnerHeight: () => {
          if (_historyVirtHost) _historyVirtHost.updateVirtInnerHeight();
        },
        virtMeasureRowH: () => {
          if (_historyVirtHost) _historyVirtHost.measureRowH();
        },
        virtOnScroll: () => {
          if (_historyVirtHost) _historyVirtHost.onScroll();
        },
        runVirtRenderPass: (opts) => {
          if (_historyVirtHost) _historyVirtHost.runVirtRenderPass(opts);
        },
        scrollContainerAtBottom: _scrollContainerAtBottom,
      });
    }
    if (
      QG.features.replacements &&
      QG.features.replacements.internals &&
      typeof QG.features.replacements.internals.bootstrapAttachTrackPopover ===
        "function"
    ) {
      _replacementAttachHost =
        QG.features.replacements.internals.bootstrapAttachTrackPopover({
          closeLyricSearchModal: () => _lyricSearch().close(),
          setLyricSearchAnchorCard:
            QG.features.lyrics.internals.setLyricSearchAnchorCard,
          clearLyricSearchAnchorHighlight:
            QG.features.lyrics.internals.clearLyricSearchAnchorHighlight,
          lyricSearchTitleFromDisplay:
            QG.features.lyrics.internals.lyricSearchTitleFromDisplay,
          showLyricSearchResultsLoading:
            QG.features.lyrics.internals.showLyricSearchResultsLoading,
          positionPopoverAboveDownloadHistory:
            QG.ui.popoverPositioning.positionAboveDownloadHistory,
          formatLyricDeltaSec: _formatLyricDeltaSec,
          formatAttachDur: QG.core.format.formatAttachDur,
          explicitBadgeSvg: _EXPLICIT_BADGE_SVG,
          getQueueUrlForPurchaseSlot: (sid) =>
            typeof window._qUrlForPurchaseSlot === "function"
              ? window._qUrlForPurchaseSlot(sid) || ""
              : "",
        });
    }
    if (
      QG.features.replacements &&
      QG.features.replacements.internals &&
      typeof QG.features.replacements.internals.bootstrapResolutionButtons ===
        "function"
    ) {
      _replacementResolutionHost =
        QG.features.replacements.internals.bootstrapResolutionButtons({
          missingPlaceholderBtnTip: _MISSING_PLACEHOLDER_BTN_TIP,
        });
    }
    if (
      QG.features.history &&
      QG.features.history.internals &&
      typeof QG.features.history.internals.bootstrapCardRendering === "function"
    ) {
      _historyCardHost = QG.features.history.internals.bootstrapCardRendering({
        getCardMap: () => _trackStatusMap,
        getOrderAll: () => _tsOrderAll,
        appendTsOrderKey: (key) => {
          if (!_tsOrderAll.includes(key)) _tsOrderAll.push(key);
        },
        getSkipHistoryFilterApply: () => _tsSkipHistoryFilterApply,
        applyHistoryFilter: _tsApplyHistoryFilter,
        isVirtActive: () =>
          _historyVirtHost ? _historyVirtHost.isVirtActive() : false,
        getVirtInnerEl: () =>
          _historyVirtHost ? _historyVirtHost.getVirtInnerEl() : null,
        getKeyToIndex: () => _tsKeyToIndex,
        appendParent: (list) =>
          _historyVirtHost
            ? _historyVirtHost.appendParent(list)
            : list,
        positionVirtCard: (card, index) => {
          if (_historyVirtHost) _historyVirtHost.positionVirtCard(card, index);
        },
        updateVirtInnerHeight: () => {
          if (_historyVirtHost) _historyVirtHost.updateVirtInnerHeight();
        },
        virtMeasureRowH: () => {
          if (_historyVirtHost) _historyVirtHost.measureRowH();
        },
        virtOnScroll: () => {
          if (_historyVirtHost) _historyVirtHost.onScroll();
        },
        scrollContainerAtBottom: _scrollContainerAtBottom,
        writeAttachMissingPlaceholder: (card, btn) => {
          if (_replacementPlaceholderHost) {
            void _replacementPlaceholderHost.writeMissingPlaceholder(card, btn);
          }
        },
        openAttachTrackPopover: (card) => {
          if (_replacementAttachHost) _replacementAttachHost.open(card);
        },
        syncResolutionButtonStates: (card) => {
          if (_replacementResolutionHost) {
            _replacementResolutionHost.syncResolutionButtonStates(card);
          }
        },
      });
    }
    if (
      QG.features.history &&
      QG.features.history.internals &&
      typeof QG.features.history.internals.bootstrapHydratePersist ===
        "function"
    ) {
      _historyStoreHost =
        QG.features.history.internals.bootstrapHydratePersist({
          guiPendingAudioPrefix: _GUI_PENDING_AUDIO_PREFIX,
          virtThreshold: _TS_VIRT_THRESHOLD,
          ensureTrackStatusCard: _ensureTrackStatusCard,
          setTrackCardCover: _setTrackCardCover,
          setTrackDownloadChip: _setTrackDownloadChip,
          setTrackLyricsChip: _setTrackLyricsChip,
          setTrackContentRatingBadge: _setTrackContentRatingBadge,
          normalizeLyricDestination: _normalizeLyricDestination,
          remapCardTrackKey: _tsRemapCardTrackKey,
          applyHistoryFilter: _tsApplyHistoryFilter,
          getSkipHistoryFilterApply: () => _tsSkipHistoryFilterApply,
          setSkipHistoryFilterApply: (v) => {
            _tsSkipHistoryFilterApply = v;
          },
          resetListForHydrate: _tsResetListForHydrate,
          pushOrderAllKey: (key) => {
            if (!_tsOrderAll.includes(key)) _tsOrderAll.push(key);
          },
          scrollContainerAtBottom: _scrollContainerAtBottom,
          activateVirtForList: (list) => {
            if (_historyVirtHost) _historyVirtHost.activateForList(list);
          },
          runVirtInitialRenderPass: (list, stick) => {
            if (_historyVirtHost) {
              _historyVirtHost.runInitialRenderPass(list, stick);
            }
          },
          getOrderAll: () => _tsOrderAll,
          onPlaceholderResolved: (card) => {
            if (_replacementResolutionHost) {
              _replacementResolutionHost.syncResolutionButtonStates(card);
            }
            _tsApplyHistoryFilter();
            if (_downloadQueueIssuesHost) {
              let q = (card && card.dataset.queueSourceUrl) || "";
              q = String(q).trim();
              const sid = (card && card.dataset.slotTrackId) || "";
              if (
                !q &&
                sid &&
                typeof window._qUrlForPurchaseSlot === "function"
              ) {
                q = window._qUrlForPurchaseSlot(sid) || "";
              }
              if (q) _downloadQueueIssuesHost.syncTrackIssues(q);
            }
            if (_queueHost) _queueHost.refreshAlbumQueueCardMetas();
          },
        });
    }
    if (
      QG.features.replacements &&
      QG.features.replacements.internals &&
      typeof QG.features.replacements.internals.bootstrapMissingPlaceholder ===
        "function" &&
      _replacementAttachHost &&
      _replacementResolutionHost
    ) {
      _replacementPlaceholderHost =
        QG.features.replacements.internals.bootstrapMissingPlaceholder({
          getAttachAnchorCard: () => _replacementAttachHost.getAnchorCard(),
          getAttachStatusElementForCard: (card) =>
            _replacementAttachHost.getStatusElementForCard(card),
          syncResolutionButtonStates: (card) =>
            _replacementResolutionHost.syncResolutionButtonStates(card),
          getQueueUrlForPurchaseSlot: (sid) =>
            typeof window._qUrlForPurchaseSlot === "function"
              ? window._qUrlForPurchaseSlot(sid) || ""
              : "",
          persistPlaceholderResolution: (card, savedPath) =>
            _historyStoreHost
              ? _historyStoreHost.persistPlaceholderResolution(card, savedPath)
              : Promise.resolve(),
        });
    }
    _queueHost.initUrlQueue();
    QG.features.settings.coverArtMutex.init("dl");

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

    if (
      QG.features.download &&
      QG.features.download.internals &&
      typeof QG.features.download.internals.bootstrapStatusHandler === "function"
    ) {
      _downloadStatusHost =
        QG.features.download.internals.bootstrapStatusHandler({
          getProgress: () => _downloadProgressHost,
          getQueueIssues: () => _downloadQueueIssuesHost,
          history: () => _hist(),
          parseTrackRef: _parseTrackRef,
          setTrackContentRatingBadge: _setTrackContentRatingBadge,
          cardHasResolvedRealAudio: _cardHasResolvedRealAudio,
          updateTrackDownloadProgress: _updateTrackDownloadProgress,
          lyricAlbumForTrackEv: _lyricAlbumForTrackEv,
          trackKey: _trackKey,
          normalizeTrackNo: _normalizeTrackNo,
          normalizeTrackTitle: _normalizeTrackTitle,
          registerAudioPathAlbum: _tsRegisterAudioPathAlbum,
          getCardMap: () => _trackStatusMap,
          getOrderAll: () => _tsOrderAll,
          addActiveDlKey: (key) => _tsActiveDlKeys.add(key),
          removeActiveDlKey: (key) => _tsActiveDlKeys.delete(key),
          getHistoryStore: () => _historyStoreHost,
          removeDuplicateHistoryCards: (card, opts) => {
            if (_historyCardHost) {
              _historyCardHost.removeDuplicateHistoryCards(card, opts);
            }
          },
          syncResolutionButtonStates: (card) => {
            if (_replacementResolutionHost) {
              _replacementResolutionHost.syncResolutionButtonStates(card);
            }
          },
          deleteResolutionFile: (opts) => {
            const ra = api && api.replacementApi;
            if (ra && typeof ra.deleteResolutionFile === "function") {
              return ra.deleteResolutionFile(opts);
            }
            return Promise.resolve(null);
          },
          historyVirtOnScroll: () => {
            if (_historyVirtHost) _historyVirtHost.onScroll();
          },
          findQueueItemByUrl: (url) =>
            _queueHost.urlQueue.find((x) => x.url === url) || null,
          albumQueueItemNeedsToStayVisible: (qi) =>
            _queueHost.albumQueueItemNeedsToStayVisible(qi),
          removeFromQueue: (url, card) =>
            _queueHost.removeFromQueue(url, card),
          refreshAlbumQueueCardMetas: () =>
            _queueHost.refreshAlbumQueueCardMetas(),
        });
    }
    if (
      QG.features.download &&
      QG.features.download.internals &&
      typeof QG.features.download.internals.bootstrapStartPause === "function"
    ) {
      _downloadStartPauseHost =
        QG.features.download.internals.bootstrapStartPause({
          getProgress: () => _downloadProgressHost,
          getQueueIssues: () => _downloadQueueIssuesHost,
          isTextMode: () => _queueHost.textMode,
          getQueueUrlsText: () =>
            _queueHost.urlQueue.map((q) => q.url).join("\n"),
          calcProgressDenominatorFromQueue: () =>
            _queueHost.calcProgressDenominatorFromQueue(),
          startDownload: (payload) => api.downloadApi.start(payload),
          pauseDownload: () => api.downloadApi.pause(),
        });
    }
    if (
      QG.features.download &&
      QG.features.download.internals &&
      typeof QG.features.download.internals.bootstrapSseClient === "function"
    ) {
      _downloadSseHost = QG.features.download.internals.bootstrapSseClient({
        streamUrl: "/api/stream",
        reconnectDelayMs: 3000,
        handleStatusEvent: _dispatchDownloadStatusEvent,
      });
    }

    if (
      QG.features.history &&
      QG.features.history.internals &&
      typeof QG.features.history.internals.bootstrapClearHistoryConfirm ===
        "function"
    ) {
      _historyClearConfirmHost =
        QG.features.history.internals.bootstrapClearHistoryConfirm({
          onConfirmClear: _resetTrackStatusCards,
          dismissConfidenceTooltips: () => {
            if (_historyCardHost?.dismissAllConfidenceTooltips) {
              _historyCardHost.dismissAllConfidenceTooltips();
            }
          },
        });
    }

    _lyricSearch().init({
      closeAttachPopover: () => {
        if (
          QG.features.replacements &&
          typeof QG.features.replacements.closeAttachPopover === "function"
        ) {
          QG.features.replacements.closeAttachPopover();
        }
      },
      setLyricsChip: (...args) => _hist().setLyricsChip(...args),
      lyricDestinationFromOutputs: _lyricDestinationFromOutputs,
    });
    if (_replacementAttachHost) _replacementAttachHost.init();
    _initDownloadHistorySegment();

    window.QobuzGui.features = window.QobuzGui.features || {};
    if (
      QG.features &&
      QG.features.history &&
      typeof QG.features.history.install === "function"
    ) {
      QG.features.history.install({
        countDownloadedForRelease: (rid) =>
          _historyStoreHost
            ? _historyStoreHost.countDownloadedForRelease(rid)
            : 0,
        applyFilter: _tsApplyHistoryFilter,
        ensureTrackCard: _ensureTrackStatusCard,
        setDownloadChip: _setTrackDownloadChip,
        setLyricsChip: _setTrackLyricsChip,
      });
    }

    if (
      QG.features &&
      QG.features.replacements &&
      typeof QG.features.replacements.install === "function"
    ) {
      QG.features.replacements.install({
        openAttachPopover: (card) => {
          if (_replacementAttachHost) _replacementAttachHost.open(card);
        },
        closeAttachPopover: () => {
          if (_replacementAttachHost) _replacementAttachHost.close();
        },
        writeMissingPlaceholder: (card, btn) => {
          if (_replacementPlaceholderHost) {
            void _replacementPlaceholderHost.writeMissingPlaceholder(
              card,
              btn,
            );
          }
        },
        syncResolutionButtonStates: (card) => {
          if (_replacementResolutionHost) {
            _replacementResolutionHost.syncResolutionButtonStates(card);
          }
        },
      });
    }

    const downloadInitReady = (async () => {
      await _queueHost.restoreFromServer();
      if (_historyStoreHost) {
        await _historyStoreHost.hydrateFromDb();
      }
      _queueHost.refreshAlbumQueueCardMetas();
      if (
        _downloadQueueIssuesHost &&
        typeof _downloadQueueIssuesHost.syncAllTrackIssues === "function"
      ) {
        _downloadQueueIssuesHost.syncAllTrackIssues();
      }
    })();
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
    if (
      QG.features &&
      QG.features.download &&
      typeof QG.features.download.install === "function"
    ) {
      QG.features.download.install({
        init(_deps) {
          /* click listener bound in bootstrapStartPause */
        },
        startSSE: _startDownloadSse,
        handleStatusEvent: _dispatchDownloadStatusEvent,
        startFromCurrentQueue() {
          const sp = _downloadStartPauseHost;
          if (sp && typeof sp.startFromCurrentQueue === "function") {
            return sp.startFromCurrentQueue();
          }
        },
        pause() {
          const dlApi = api && api.downloadApi;
          if (dlApi && typeof dlApi.pause === "function") {
            return dlApi.pause();
          }
          return Promise.resolve(null);
        },
        isDownloading() {
          const prog = _downloadProgressHost;
          if (prog && typeof prog.isDownloading === "function") {
            return prog.isDownloading();
          }
          return !!window.isDownloading;
        },
        qUrlForPurchaseSlot(slotId) {
          const issues = _downloadQueueIssuesHost;
          if (issues && typeof issues.qUrlForPurchaseSlot === "function") {
            return issues.qUrlForPurchaseSlot(slotId) || "";
          }
          return typeof window._qUrlForPurchaseSlot === "function"
            ? window._qUrlForPurchaseSlot(slotId) || ""
            : "";
        },
      });
    }

    return downloadInitReady;
  }

  // ── Init ─────────────────────────────────────────────────
  async function init() {
    window.QobuzGui.ui.theme.init();
    window.QobuzGui.ui.collapses.init();
    window.QobuzGui.ui.resetButtons.init();

    QG.features.setup.configure({
      startDownloadSse: _startDownloadSse,
      ensureDownloadReady: () => _downloadInitReady,
      loadSettingsForm: () => QG.features.settings.settingsForm.loadIntoForm(),
      connect: () => api.setupApi.connect(),
    });
    QG.features.setup.authTabs.init();
    QG.features.setup.browseButtons.init();
    if (QG.ui.menuSelect && typeof QG.ui.menuSelect.init === "function") {
      QG.ui.menuSelect.init();
    }
    QG.features.setup.initSetup();

    const _downloadInitReady = initDownload();
    QG.features.search.init();
    QG.features.settings.actions.init({
      checkStatus: QG.features.status.checkStatus,
      updateStatus: QG.features.status.updateStatus,
      loadSettingsForm: () => QG.features.settings.settingsForm.loadIntoForm(),
    });
    _startDownloadSse();
    window.QobuzGui.features.updateBanner.init();
    setTimeout(() => {
      void window.QobuzGui.features.updateBanner.refreshUpdateCheck(true);
    }, 800);

    await QG.features.setup.resolveInitialView();
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("DOMContentLoaded", () => {
    window.QobuzGui.features.formatBuilder.formatTooltips.init();
    window.QobuzGui.ui.donationPopover.init();
    window.QobuzGui.ui.globalTooltip.init();
    window.QobuzGui.ui.textFieldContextMenu.init();
  });
})();
