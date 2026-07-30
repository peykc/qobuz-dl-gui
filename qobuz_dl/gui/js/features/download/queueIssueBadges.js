/**
 * Queue purchase-only / failed-track badges + URL error tips (D1C).
 *
 * Invoked once from `app.js` `initDownload()` via `bootstrapQueueIssueBadges(deps)`.
 */
(function () {
  "use strict";
  const g = window.QobuzGui;
  const dlroot = (g.features.download = g.features.download || {});

  const TIPS = {
    purchaseQueue:
      "Open album on Qobuz to purchase (full album required for these tracks)",
    notStreamable:
      "This release is not available for streaming on Qobuz. It may only be sold as a full album (purchase-only or region-restricted), open it on Qobuz to check.",
    alreadyDownloaded:
      'Already downloaded (local database). Enable "Ignore download database" in settings to re-download.',
    urlErrorGeneric:
      "This queue item did not finish successfully. Check the activity log for details — causes include network errors, quality restrictions, or tracks that could not be downloaded.",
    trackIssues:
      "One or more tracks on this album could not be downloaded (failed, purchase-only, or unavailable). Check download history for details.",
  };

  function _urlErrorCopy(ev) {
    const detail = String((ev && ev.detail) || "").trim();
    const message = String((ev && ev.message) || "").trim();
    if (detail === "already_downloaded") {
      return {
        label: "\u26a0 Already downloaded",
        text: message || TIPS.alreadyDownloaded,
      };
    }
    if (detail === "non_streamable") {
      return {
        label: "\u26a0 Not streamable",
        text: message || TIPS.notStreamable,
      };
    }
    if (detail === "start_failed") {
      return {
        label: "\u26a0 Couldn't start",
        text: message || "Could not start download.",
      };
    }
    return {
      label: "\u26a0 Download issue",
      text: message || TIPS.urlErrorGeneric,
    };
  }

  function _ensureUrlErrorMessage(info, text) {
    let msg = info.querySelector(".dl-error-message.dl-url-failed-message");
    if (!msg) {
      msg = document.createElement("div");
      msg.className = "dl-error-message dl-url-failed-message";
      info.appendChild(msg);
    }
    msg.textContent = text;
    return msg;
  }

  function _clearUrlErrorMessage(info) {
    if (!info) return;
    info
      .querySelectorAll(".dl-error-message.dl-url-failed-message")
      .forEach((el) => el.remove());
  }

  function bootstrapQueueIssueBadges(deps) {
    const issueKeysByUrl = new Map();
    const GUI_PENDING =
      (g.core && g.core.constants && g.core.constants.GUI_PENDING_AUDIO_PREFIX) ||
      "__GUI_PENDING__:slot:";

    function findCardByUrl(url) {
      const cards = document.querySelectorAll("#dl-queue .queue-card");
      for (const c of cards) {
        if (c.dataset.url === url) return c;
      }
      return null;
    }

    function purchaseIssueSlotKey(ev, resAlb) {
      const sid = String(ev.slot_track_id || "").trim();
      if (sid) return `sid:${sid}`;
      const trackKey = deps.trackKey;
      if (typeof trackKey !== "function") return "";
      return trackKey(ev.track_no, ev.title, resAlb);
    }

    function qUrlForPurchaseSlot(slotId) {
      const sid = String(slotId || "").trim();
      if (!sid) return "";
      const pk = `sid:${sid}`;
      for (const [url, set] of issueKeysByUrl.entries()) {
        if (set.has(pk)) return url;
      }
      return "";
    }

    function countIssuesFromHistory(releaseAlbumId) {
      const rid = String(releaseAlbumId || "").trim();
      if (!rid || typeof deps.getDbItemByKey !== "function") return 0;
      const map = deps.getDbItemByKey();
      let n = 0;
      for (const it of map.values()) {
        if (String(it.release_album_id || "").trim() !== rid) continue;
        const st = String(it.download_status || "downloaded").toLowerCase();
        const ap = String(it.audio_path || "").trim();
        if (
          (st === "failed" || st === "purchase_only") &&
          ap.startsWith(GUI_PENDING)
        ) {
          n++;
        }
      }
      return n;
    }

    function issueCountForUrl(qurl) {
      const q = String(qurl || "").trim();
      if (!q) return 0;
      const findQueueItem = deps.findQueueItemByUrl;
      const releaseIdFromQi = deps.releaseAlbumIdFromQueueItem;
      if (typeof findQueueItem === "function" && typeof releaseIdFromQi === "function") {
        const qi = findQueueItem(q);
        const rid = releaseIdFromQi(qi);
        return countIssuesFromHistory(rid);
      }
      return 0;
    }

    function syncTrackIssues(qurl) {
      const q = String(qurl || "").trim();
      if (!q) return;
      const card = findCardByUrl(q);
      if (!card) return;
      const info = card.querySelector(".queue-card-info");
      if (!info) return;
      const n = issueCountForUrl(q);
      const trackBadge = info.querySelector(
        ".dl-error-badge.dl-track-issues-badge",
      );
      const urlFailedBadge = info.querySelector(
        ".dl-error-badge.dl-url-failed-badge",
      );
      const findQueueItem = deps.findQueueItemByUrl;
      const qiHold =
        typeof findQueueItem === "function" ? findQueueItem(q) : null;
      const stayVisible = deps.albumQueueItemNeedsToStayVisible;
      const stayAlbum =
        qiHold != null &&
        typeof stayVisible === "function" &&
        stayVisible(qiHold);

      if (n === 0) {
        if (trackBadge) trackBadge.remove();
        if (!urlFailedBadge) {
          _clearUrlErrorMessage(info);
          card.classList.remove("dl-error");
        }
        const stillActive =
          card.classList.contains("dl-active") ||
          card.classList.contains("dl-pending");
        if (!stillActive && !urlFailedBadge) {
          if (stayAlbum) {
            const refresh = deps.refreshAlbumQueueCardMetas;
            if (typeof refresh === "function") refresh();
            return;
          }
          card.classList.add("dl-done");
          const remove = deps.removeFromQueue;
          if (typeof remove === "function") {
            setTimeout(() => remove(q, card), 1400);
          }
        }
        return;
      }

      if (urlFailedBadge) urlFailedBadge.remove();
      _clearUrlErrorMessage(info);

      let badge = trackBadge;
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "dl-error-badge dl-track-issues-badge";
        info.appendChild(badge);
      }
      badge.textContent = `${n} \u26a0 Purchase only`;
      badge.setAttribute("data-tip", TIPS.purchaseQueue);
      badge.setAttribute("aria-label", `${n} purchase-only track(s) on this album`);
      badge.removeAttribute("title");
      card.classList.remove("dl-active", "dl-pending", "dl-done");
      card.classList.add("dl-error");
    }

    function markTrackIssue(qurl, pk) {
      const q = String(qurl || "").trim();
      const key = String(pk || "").trim();
      if (!q || !key) return;
      let set = issueKeysByUrl.get(q);
      if (!set) {
        set = new Set();
        issueKeysByUrl.set(q, set);
      }
      set.add(key);
      syncTrackIssues(q);
    }

    function resolveTrackIssue(qurl, pk) {
      const q = String(qurl || "").trim();
      const key = String(pk || "").trim();
      if (!q) return;
      const set = issueKeysByUrl.get(q);
      if (set && key && set.delete(key) && set.size === 0) {
        issueKeysByUrl.delete(q);
      }
      syncTrackIssues(q);
    }

    function markPurchaseOnly(qurl, pk) {
      markTrackIssue(qurl, pk);
    }

    function resolvePurchaseOnly(qurl, pk) {
      resolveTrackIssue(qurl, pk);
    }

    function clearPurchaseIssues() {
      issueKeysByUrl.clear();
    }

    function syncAllTrackIssues() {
      document.querySelectorAll("#dl-queue .queue-card").forEach((card) => {
        const q = (card.dataset.url || "").trim();
        if (q) syncTrackIssues(q);
      });
    }

    function applyUrlErrorBadge(card, ev) {
      if (!card) return;
      const qurl = String(card.dataset.url || "").trim();
      if (qurl && issueCountForUrl(qurl) > 0) {
        syncTrackIssues(qurl);
        return;
      }
      card.classList.remove("dl-active", "dl-pending", "dl-done");
      card.classList.add("dl-error");
      const info = card.querySelector(".queue-card-info");
      if (!info) return;
      let badge = info.querySelector(".dl-error-badge.dl-url-failed-badge");
      if (!badge) {
        badge = document.createElement("span");
        badge.className = "dl-error-badge dl-url-failed-badge";
        info.appendChild(badge);
      }
      const copy = _urlErrorCopy(ev);
      badge.textContent = copy.label;
      badge.setAttribute("data-tip", copy.text);
      badge.setAttribute("aria-label", copy.text);
      badge.removeAttribute("title");
      _ensureUrlErrorMessage(info, copy.text);
    }

    function applyStartFailureFeedback(message) {
      const text = String(message || "").trim() || "Could not start download.";
      const cards = document.querySelectorAll("#dl-queue .queue-card");
      if (cards.length) {
        cards.forEach((card) => {
          applyUrlErrorBadge(card, {
            detail: "start_failed",
            message: text,
          });
        });
        hideQueueStartFeedback();
        return;
      }
      showQueueStartFeedback(text);
    }

    function showQueueStartFeedback(message) {
      const wrap = document.getElementById("dl-queue-start-feedback");
      const badge = document.getElementById("dl-queue-start-feedback-badge");
      const msg = document.getElementById("dl-queue-start-feedback-msg");
      if (!wrap || !badge || !msg) return;
      badge.textContent = "\u26a0 Download issue";
      msg.textContent = message;
      wrap.classList.remove("hidden");
    }

    function hideQueueStartFeedback() {
      const wrap = document.getElementById("dl-queue-start-feedback");
      if (wrap) wrap.classList.add("hidden");
    }

    window._qUrlForPurchaseSlot = qUrlForPurchaseSlot;

    return {
      tips: TIPS,
      findCardByUrl,
      purchaseIssueSlotKey,
      qUrlForPurchaseSlot,
      syncTrackIssues,
      syncAllTrackIssues,
      markTrackIssue,
      resolveTrackIssue,
      markPurchaseOnly,
      resolvePurchaseOnly,
      clearPurchaseIssues,
      applyUrlErrorBadge,
      applyStartFailureFeedback,
      hideQueueStartFeedback,
    };
  }

  dlroot.internals = dlroot.internals || {};
  dlroot.internals.bootstrapQueueIssueBadges = bootstrapQueueIssueBadges;
})();
