(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g.api;
  const QG = g;
  const features = (g.features = g.features || {});
  const feedbackFeature = (features.feedback = features.feedback || {});

  function init(checkStatus) {
    // ── Gear button / popover open-close ─────────────────────
    const gearBtn = document.getElementById("settings-gear-btn");
    const popover = document.getElementById("settings-popover");
    const backdrop = document.getElementById("settings-backdrop");
    const closeBtn = document.getElementById("settings-popover-close");
    const feedback = document.getElementById("settings-popover-feedback");
    const reportBtn = document.getElementById("report-issue-btn");
    const reportPopover = document.getElementById("issue-report-popover");
    const reportCloseBtn = document.getElementById("issue-report-close");
    const reportHistoryBtn = document.getElementById("issue-report-history-btn");
    const reportHistoryIconHistory = reportHistoryBtn
      ? reportHistoryBtn.querySelector(".issue-report-history-btn-icon--history")
      : null;
    const reportHistoryIconBack = reportHistoryBtn
      ? reportHistoryBtn.querySelector(".issue-report-history-btn-icon--back")
      : null;
    const reportHistoryPanel = document.getElementById("issue-report-history-panel");
    const reportHistoryList = document.getElementById("issue-report-history-list");
    const reportHistoryEmpty = document.getElementById("issue-report-history-empty");
    const reportMain = document.getElementById("issue-report-main");
    const reportHeading = document.getElementById("issue-report-heading");
    const reportOpenCountBadge = document.getElementById("issue-report-open-count");
    const reportLogPreviewBtn = document.getElementById("issue-report-log-preview-btn");
    const logsModal = document.getElementById("issue-report-logs-modal");
    const logsModalBackdrop = logsModal
      ? logsModal.querySelector("[data-logs-modal-dismiss]")
      : null;
    const logsModalCloseBtn = document.getElementById("issue-report-logs-modal-close");
    const logsModalDoneBtn = document.getElementById("issue-report-logs-modal-done");
    const logsModalBody = document.getElementById("issue-report-logs-modal-body");
    const logsModalLoading = document.getElementById("issue-report-logs-modal-loading");
    const logsModalTitleEl = document.getElementById("issue-report-logs-modal-title");
    const logsModalFooterLogs = document.getElementById("issue-report-logs-modal-footer-logs");
    const logsModalFooterFeedback = document.getElementById(
      "issue-report-logs-modal-footer-feedback",
    );
    const feedbackDetailStatusEl = document.getElementById("issue-report-feedback-detail-status");
    const logsIncludeCheckbox = document.getElementById("issue-report-logs-include");
    const reportMessage = document.getElementById("issue-report-message");
    const reportFeedback = document.getElementById("issue-report-feedback");
    const reportOpenBtn = document.getElementById("issue-report-open");
    const FEEDBACK_ENDPOINT = "https://feedback.pkcollection.net";
    const FEEDBACK_HISTORY_LS = "qobuz_dl_feedback_history_v1";
    const FEEDBACK_CLIENT_TOKEN_LS = "qobuz_dl_feedback_client_token";
    function resetIssueReportPopoverHeight() {
      if (!reportPopover) return;
      reportPopover.style.removeProperty("height");
    }

    let issueReportResizeStartY = 0;
    let issueReportResizeStartH = 0;

    function onIssueReportPopoverResizeMove(ev) {
      if (!reportPopover) return;
      const delta = ev.clientY - issueReportResizeStartY;
      const minH = 296;
      const maxH = Math.max(minH, window.innerHeight - 90);
      let h = issueReportResizeStartH + delta;
      h = Math.max(minH, Math.min(maxH, h));
      reportPopover.style.height = `${Math.round(h)}px`;
    }

    function onIssueReportPopoverResizeUp(ev) {
      const bar = ev.currentTarget;
      try {
        bar.releasePointerCapture(ev.pointerId);
      } catch (_) {}
      bar.removeEventListener("pointermove", onIssueReportPopoverResizeMove);
      bar.removeEventListener("pointerup", onIssueReportPopoverResizeUp);
      bar.removeEventListener("pointercancel", onIssueReportPopoverResizeUp);
      document.body.style.removeProperty("user-select");
    }

    function onIssueReportPopoverResizeDown(ev) {
      if (ev.button !== 0 || !reportPopover) return;
      const bar = ev.currentTarget;
      ev.preventDefault();
      ev.stopPropagation();
      issueReportResizeStartY = ev.clientY;
      issueReportResizeStartH = reportPopover.getBoundingClientRect().height;
      document.body.style.userSelect = "none";
      try {
        bar.setPointerCapture(ev.pointerId);
      } catch (_) {}
      bar.addEventListener("pointermove", onIssueReportPopoverResizeMove);
      bar.addEventListener("pointerup", onIssueReportPopoverResizeUp);
      bar.addEventListener("pointercancel", onIssueReportPopoverResizeUp);
    }
    let issueReportSending = false;
    let issueReportClosingId = null;
    let issueReportSendResetTimer = null;
    let feedbackDetailModalItem = null;

    function resetIssueReportSendButtonVisual() {
      if (issueReportSendResetTimer) {
        clearTimeout(issueReportSendResetTimer);
        issueReportSendResetTimer = null;
      }
      if (reportOpenBtn) {
        reportOpenBtn.classList.remove(
          "issue-report-send--success",
          "issue-report-send--loading",
        );
        reportOpenBtn.removeAttribute("aria-label");
        reportOpenBtn.removeAttribute("aria-busy");
        const spin = reportOpenBtn.querySelector(".issue-report-send-spinner");
        if (spin) spin.classList.add("hidden");
      }
    }

    function setIssueReportSendLoading(loading) {
      if (!reportOpenBtn) return;
      const spin = reportOpenBtn.querySelector(".issue-report-send-spinner");
      if (loading) {
        reportOpenBtn.classList.add("issue-report-send--loading");
        reportOpenBtn.setAttribute("aria-busy", "true");
        if (spin) spin.classList.remove("hidden");
      } else {
        reportOpenBtn.classList.remove("issue-report-send--loading");
        reportOpenBtn.removeAttribute("aria-busy");
        if (spin) spin.classList.add("hidden");
      }
    }

    function flashIssueReportSendSuccess() {
      if (!reportOpenBtn) return;
      resetIssueReportSendButtonVisual();
      reportOpenBtn.classList.add("issue-report-send--success");
      reportOpenBtn.setAttribute("aria-label", "Feedback sent");
      issueReportSendResetTimer = setTimeout(() => {
        issueReportSendResetTimer = null;
        if (reportOpenBtn) {
          reportOpenBtn.classList.remove("issue-report-send--success");
          reportOpenBtn.removeAttribute("aria-label");
        }
        syncIssueReportSendBtn();
      }, 2800);
    }

    function countOpenFeedbackItems() {
      return loadFeedbackHistory().filter((x) => !x.closed).length;
    }

    function syncIssueReportOpenCountBadge() {
      if (!reportHistoryBtn) return;
      const n = countOpenFeedbackItems();
      const historyMode =
        reportHistoryPanel && !reportHistoryPanel.classList.contains("hidden");
      if (reportOpenCountBadge) {
        if (n <= 0) {
          reportOpenCountBadge.classList.add("hidden");
          reportOpenCountBadge.textContent = "";
        } else {
          reportOpenCountBadge.classList.remove("hidden");
          reportOpenCountBadge.textContent = n > 99 ? "99+" : String(n);
        }
      }
      const base = historyMode ? "Back to compose" : "Sent feedback history";
      if (n > 0) {
        reportHistoryBtn.setAttribute("aria-label", `${base} (${n} open)`);
      } else {
        reportHistoryBtn.setAttribute("aria-label", base);
      }
    }

    function syncIssueReportHeader(historyMode) {
      if (reportHeading) {
        reportHeading.textContent = "Send Feedback";
      }
      if (reportHistoryIconHistory && reportHistoryIconBack) {
        reportHistoryIconHistory.classList.toggle("hidden", historyMode);
        reportHistoryIconBack.classList.toggle("hidden", !historyMode);
      }
      if (reportHistoryBtn) {
        reportHistoryBtn.dataset.tip = historyMode ? "Back" : "History";
      }
      syncIssueReportOpenCountBadge();
    }

    function getFeedbackClientToken() {
      let t = localStorage.getItem(FEEDBACK_CLIENT_TOKEN_LS);
      if (!t || t.length < 8) {
        try {
          t = crypto.randomUUID();
        } catch (_) {
          t = `${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
        }
        localStorage.setItem(FEEDBACK_CLIENT_TOKEN_LS, t);
      }
      return t;
    }

    /** Token stored when feedback was sent (survives different GUI ports / localStorage origins). */
    function getClientTokenForClose(feedbackId) {
      try {
        const items = loadFeedbackHistory();
        const it = items.find((x) => x && x.id === feedbackId);
        const t = it && typeof it.clientToken === "string" ? it.clientToken.trim() : "";
        if (t.length >= 8) return t;
      } catch (_) {}
      return getFeedbackClientToken();
    }

    function loadFeedbackHistory() {
      try {
        const raw = localStorage.getItem(FEEDBACK_HISTORY_LS);
        const arr = raw ? JSON.parse(raw) : [];
        return Array.isArray(arr) ? arr : [];
      } catch (_) {
        return [];
      }
    }

    async function persistFeedbackHistoryToServer(items) {
      try {
        await api.feedbackApi.persistHistory(items);
      } catch (_) {}
    }

    function saveFeedbackHistory(items) {
      const slice = items.slice(0, 100);
      try {
        localStorage.setItem(FEEDBACK_HISTORY_LS, JSON.stringify(slice));
      } catch (_) {}
      void persistFeedbackHistoryToServer(slice);
    }

    async function hydrateFeedbackHistoryFromDisk() {
      try {
        const res = await api.feedbackApi.getHistory();
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok || !Array.isArray(data.items)) return;
        const disk = data.items;
        const ls = loadFeedbackHistory();
        if (disk.length === 0 && ls.length > 0) {
          await persistFeedbackHistoryToServer(ls);
          return;
        }
        if (disk.length > 0) {
          const ids = new Set(disk.map((x) => x && x.id).filter(Boolean));
          const extras = ls.filter((x) => x && x.id && !ids.has(x.id));
          const merged = extras.length ? [...extras, ...disk].slice(0, 100) : disk;
          try {
            localStorage.setItem(FEEDBACK_HISTORY_LS, JSON.stringify(merged));
          } catch (_) {}
          if (extras.length) await persistFeedbackHistoryToServer(merged);
        }
      } catch (_) {}
    }

    function pushFeedbackHistory(entry) {
      const rest = loadFeedbackHistory().filter((x) => x.id !== entry.id);
      rest.unshift(entry);
      saveFeedbackHistory(rest);
    }

    function patchFeedbackHistory(id, patch) {
      const items = loadFeedbackHistory();
      const i = items.findIndex((x) => x.id === id);
      if (i === -1) return;
      items[i] = { ...items[i], ...patch };
      saveFeedbackHistory(items);
    }

    function issueReportAttachLogs() {
      return logsIncludeCheckbox ? logsIncludeCheckbox.checked : true;
    }

    function githubIssueOpenDotIconHtml(cls) {
      const c = cls ? ` ${cls}` : "";
      return (
        `<svg class="issue-report-history-resolve-icon${c}" width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">` +
        '<circle cx="8" cy="8" r="6.25" stroke="currentColor" stroke-width="1.25"/>' +
        '<circle cx="8" cy="8" r="2" fill="currentColor"/>' +
        "</svg>"
      );
    }

    function feedbackHistoryResolvedIconHtml(cls) {
      const c = cls ? ` ${cls}` : "";
      return (
        `<svg class="issue-report-history-resolve-icon${c}" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
        '<path d="M20 6 9 17l-5-5"/>' +
        "</svg>"
      );
    }

    function formatFeedbackHistoryTagDate(ts) {
      const n = Number(ts) || 0;
      if (!n) return "";
      const d = new Date(n * 1000);
      const now = new Date();
      const opts = { month: "short", day: "numeric" };
      if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
      return d.toLocaleDateString(undefined, opts);
    }

    function abbrevFeedbackPlatform(p) {
      const s = String(p || "").toLowerCase();
      if (s === "windows" || s.includes("win")) return "Win";
      if (s === "macos" || s.includes("mac")) return "Mac";
      if (s === "linux" || s.includes("linux")) return "Linux";
      const t = String(p || "").trim();
      return t.length > 10 ? `${t.slice(0, 9)}…` : t;
    }

    function setFeedbackDetailStatusPill(item) {
      if (!feedbackDetailStatusEl || !item) return;
      feedbackDetailStatusEl.classList.remove(
        "feedback-detail-status-pill--busy",
        "feedback-detail-status-pill--actionable",
      );
      feedbackDetailStatusEl.removeAttribute("aria-busy");
      const closed = !!item.closed;
      const canMark =
        item && !closed && String(item.id || "").startsWith("fb:");
      feedbackDetailStatusEl.className =
        "feedback-detail-status-pill" +
        (closed ? " feedback-detail-status-pill--closed" : " feedback-detail-status-pill--open");
      if (canMark) {
        feedbackDetailStatusEl.classList.add("feedback-detail-status-pill--actionable");
        feedbackDetailStatusEl.setAttribute("role", "button");
        feedbackDetailStatusEl.setAttribute("tabindex", "0");
        feedbackDetailStatusEl.setAttribute(
          "aria-label",
          "Mark feedback as resolved or closed",
        );
      } else {
        feedbackDetailStatusEl.setAttribute("role", "status");
        feedbackDetailStatusEl.removeAttribute("tabindex");
        feedbackDetailStatusEl.removeAttribute("aria-label");
      }
      if (closed) {
        feedbackDetailStatusEl.innerHTML = `${feedbackHistoryResolvedIconHtml("feedback-detail-status-icon")}<span>Closed</span>`;
        feedbackDetailStatusEl.setAttribute("data-tip", "Resolved");
      } else {
        feedbackDetailStatusEl.innerHTML = `${githubIssueOpenDotIconHtml("feedback-detail-status-icon")}<span>Open</span>`;
        feedbackDetailStatusEl.setAttribute(
          "data-tip",
          "Mark feedback as resolved/closed",
        );
      }
    }

    function openFeedbackDetailModal(item) {
      if (!item || !logsModal || !logsModalBody || !logsModalLoading) return;
      if (logsModalFooterLogs) logsModalFooterLogs.classList.add("hidden");
      if (logsModalFooterFeedback) logsModalFooterFeedback.classList.remove("hidden");
      if (logsModalTitleEl) logsModalTitleEl.textContent = "Feedback";
      logsModalBody.setAttribute("aria-label", "Feedback message");
      feedbackDetailModalItem = { ...item };
      setFeedbackDetailStatusPill(feedbackDetailModalItem);
      logsModalLoading.classList.add("hidden");
      logsModalBody.textContent = String(item.messagePreview || "(no message)");
      logsModal.classList.remove("hidden");
      logsModal.setAttribute("aria-hidden", "false");
    }

    function syncIssueReportSendBtn() {
      if (!reportOpenBtn || !reportMessage) return;
      reportOpenBtn.disabled =
        issueReportSending || reportMessage.value.trim().length === 0;
    }

    function syncHistoryMsgClamp(msgEl, fullTextRaw) {
      const measureSuffix = "... →";
      msgEl.textContent = "";
      const trimmed = String(fullTextRaw || "").trim();
      if (!trimmed) {
        msgEl.textContent = "(no message)";
        return false;
      }
      msgEl.textContent = trimmed;
      if (msgEl.scrollHeight <= msgEl.clientHeight + 1) {
        return false;
      }
      let lo = 0;
      let hi = trimmed.length;
      while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        const chunk = trimmed.slice(0, mid).trimEnd() + measureSuffix;
        msgEl.textContent = chunk;
        if (msgEl.scrollHeight > msgEl.clientHeight + 1) hi = mid - 1;
        else lo = mid;
      }
      if (lo < 1) lo = 1;
      const prefix = trimmed.slice(0, lo).trimEnd();
      msgEl.textContent = "";
      msgEl.appendChild(document.createTextNode(`${prefix}...`));
      const sufEl = document.createElement("span");
      sufEl.className = "issue-report-history-msg-suffix";
      sufEl.textContent = " →";
      msgEl.appendChild(sufEl);
      return true;
    }

    function renderFeedbackHistoryList() {
      if (!reportHistoryList || !reportHistoryEmpty) return;
      const items = loadFeedbackHistory();
      reportHistoryEmpty.classList.toggle("hidden", items.length > 0);
      reportHistoryList.innerHTML = "";
      items.forEach((it) => {
        const row = document.createElement("div");
        row.className =
          "issue-report-history-row" +
          (it.closed ? " issue-report-history-row--closed" : "");
        row.setAttribute("role", "listitem");
        const fullText = String(it.messagePreview || "");

        const msgBlock = document.createElement("div");
        msgBlock.className = "issue-report-history-msg-block";

        const msg = document.createElement("p");
        msg.className = "issue-report-history-msg";

        msgBlock.appendChild(msg);

        function openThisDetail(ev) {
          if (!msgBlock.classList.contains("issue-report-history-msg-block--expandable")) {
            return;
          }
          ev.preventDefault();
          ev.stopPropagation();
          openFeedbackDetailModal(it);
        }
        msgBlock.addEventListener("click", openThisDetail);
        msgBlock.addEventListener("keydown", (ev) => {
          if (!msgBlock.classList.contains("issue-report-history-msg-block--expandable")) {
            return;
          }
          if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            openFeedbackDetailModal(it);
          }
        });

        function runMsgClamp() {
          const truncated = syncHistoryMsgClamp(msg, fullText);
          if (truncated) {
            msgBlock.classList.add("issue-report-history-msg-block--expandable");
            msgBlock.setAttribute("role", "button");
            msgBlock.setAttribute("tabindex", "0");
            msgBlock.setAttribute(
              "aria-label",
              "View full feedback message",
            );
          } else {
            msgBlock.classList.remove("issue-report-history-msg-block--expandable");
            msgBlock.removeAttribute("role");
            msgBlock.removeAttribute("tabindex");
            msgBlock.removeAttribute("aria-label");
          }
        }

        const meta = document.createElement("div");
        meta.className = "issue-report-history-meta";
        const dateStr = formatFeedbackHistoryTagDate(it.timestamp);
        if (dateStr) {
          const sp = document.createElement("span");
          sp.className = "issue-report-history-tag issue-report-history-tag--date";
          sp.textContent = dateStr;
          meta.appendChild(sp);
        }
        if (it.version) {
          const sp = document.createElement("span");
          sp.className = "issue-report-history-tag issue-report-history-tag--ver";
          const v = String(it.version).replace(/^v/i, "");
          sp.textContent = `v${v}`;
          meta.appendChild(sp);
        }
        const plat = abbrevFeedbackPlatform(it.platform);
        if (plat) {
          const sp = document.createElement("span");
          sp.className = "issue-report-history-tag issue-report-history-tag--plat";
          sp.textContent = plat;
          meta.appendChild(sp);
        }
        if (it.hasLog) {
          const sp = document.createElement("span");
          sp.className = "issue-report-history-tag issue-report-history-tag--logs";
          sp.textContent = "Logs";
          meta.appendChild(sp);
        }

        const body = document.createElement("div");
        body.className = "issue-report-history-body";
        body.appendChild(msgBlock);
        body.appendChild(meta);
        const resolveBtn = document.createElement("button");
        resolveBtn.type = "button";
        resolveBtn.className = "issue-report-history-resolve";
        const idStr = String(it.id || "");
        resolveBtn.classList.toggle(
          "issue-report-history-resolve--locked",
          !it.closed && !idStr.startsWith("fb:"),
        );
        resolveBtn.setAttribute(
          "aria-label",
          it.closed ? "Resolved" : "Mark as resolved",
        );
        resolveBtn.setAttribute("aria-pressed", it.closed ? "true" : "false");
        if (it.closed) {
          resolveBtn.setAttribute("data-tip", "Resolved");
        } else if (!idStr.startsWith("fb:")) {
          resolveBtn.setAttribute(
            "data-tip",
            "Cannot mark resolved for this entry",
          );
        } else {
          resolveBtn.setAttribute(
            "data-tip",
            "Mark feedback as resolved/closed",
          );
        }
        resolveBtn.innerHTML = it.closed
          ? feedbackHistoryResolvedIconHtml()
          : githubIssueOpenDotIconHtml();
        resolveBtn.disabled =
          !!it.closed ||
          issueReportClosingId === it.id ||
          !idStr.startsWith("fb:");
        resolveBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          if (it.closed || issueReportClosingId) return;
          void markFeedbackClosedOnServer(it.id, resolveBtn);
        });
        row.appendChild(body);
        row.appendChild(resolveBtn);
        reportHistoryList.appendChild(row);
        requestAnimationFrame(() => runMsgClamp());
      });
    }

    async function markFeedbackClosedOnServer(id, btnEl) {
      issueReportClosingId = id;
      if (btnEl) btnEl.disabled = true;
      const usePillBusy =
        feedbackDetailStatusEl &&
        feedbackDetailModalItem &&
        feedbackDetailModalItem.id === id &&
        !feedbackDetailModalItem.closed;
      if (usePillBusy) {
        feedbackDetailStatusEl.setAttribute("aria-busy", "true");
        feedbackDetailStatusEl.classList.add("feedback-detail-status-pill--busy");
      }
      try {
        const res = await fetch(`${FEEDBACK_ENDPOINT}/api/feedback/close`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id,
            clientToken: getClientTokenForClose(id),
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) throw new Error(data.error || "failed");
        patchFeedbackHistory(id, { closed: true });
        renderFeedbackHistoryList();
        syncIssueReportOpenCountBadge();
        if (feedbackDetailModalItem && feedbackDetailModalItem.id === id) {
          feedbackDetailModalItem = { ...feedbackDetailModalItem, closed: true };
          setFeedbackDetailStatusPill(feedbackDetailModalItem);
        }
      } catch (err) {
        if (reportFeedback) {
          const why =
            err && err.message === "forbidden"
              ? "Could not close this report (session token mismatch). Dev and packaged builds use different browser storage ports; older history entries may lack a saved token. Close or delete from the feedback inbox using your admin bearer token, or remove the stale row from Sent history."
              : "Could not mark resolved (network error).";
          QG.ui.feedbackMessage.show(reportFeedback, why, false);
        }
        if (btnEl) btnEl.disabled = false;
        if (usePillBusy) setFeedbackDetailStatusPill(feedbackDetailModalItem);
      } finally {
        issueReportClosingId = null;
      }
    }

    if (feedbackDetailStatusEl) {
      feedbackDetailStatusEl.addEventListener("click", (ev) => {
        if (
          !feedbackDetailStatusEl.classList.contains(
            "feedback-detail-status-pill--actionable",
          )
        )
          return;
        ev.preventDefault();
        ev.stopPropagation();
        if (
          !feedbackDetailModalItem ||
          feedbackDetailModalItem.closed ||
          issueReportClosingId
        )
          return;
        const id = feedbackDetailModalItem.id;
        if (!String(id || "").startsWith("fb:")) return;
        void markFeedbackClosedOnServer(id, null);
      });
      feedbackDetailStatusEl.addEventListener("keydown", (ev) => {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        if (
          !feedbackDetailStatusEl.classList.contains(
            "feedback-detail-status-pill--actionable",
          )
        )
          return;
        ev.preventDefault();
        if (
          !feedbackDetailModalItem ||
          feedbackDetailModalItem.closed ||
          issueReportClosingId
        )
          return;
        const id = feedbackDetailModalItem.id;
        if (!String(id || "").startsWith("fb:")) return;
        void markFeedbackClosedOnServer(id, null);
      });
    }

    function closeIssueReportLogsModal() {
      if (!logsModal) return;
      feedbackDetailModalItem = null;
      logsModal.classList.add("hidden");
      logsModal.setAttribute("aria-hidden", "true");
    }

    async function openIssueReportLogsModal() {
      if (!logsModal || !logsModalBody || !logsModalLoading) return;
      feedbackDetailModalItem = null;
      if (logsModalFooterLogs) logsModalFooterLogs.classList.remove("hidden");
      if (logsModalFooterFeedback) logsModalFooterFeedback.classList.add("hidden");
      if (logsModalTitleEl) logsModalTitleEl.textContent = "Session log";
      logsModalBody.setAttribute("aria-label", "Log contents");
      logsModal.classList.remove("hidden");
      logsModal.setAttribute("aria-hidden", "false");
      logsModalLoading.classList.remove("hidden");
      logsModalBody.textContent = "";
      try {
        const res = await api.sessionLogsApi.get();
        const text = res.ok ? await res.text() : "";
        logsModalBody.textContent =
          (text && text.trim()) || "(No log lines captured in this session yet.)";
      } catch (_) {
        logsModalBody.textContent = "(Could not load session logs.)";
      } finally {
        logsModalLoading.classList.add("hidden");
      }
    }

    function showIssueReportMainPane() {
      resetIssueReportSendButtonVisual();
      if (reportMain) reportMain.classList.remove("hidden");
      if (reportHistoryPanel) reportHistoryPanel.classList.add("hidden");
      syncIssueReportHeader(false);
      if (reportFeedback) reportFeedback.className = "feedback-msg hidden";
    }

    function showIssueReportHistoryPane() {
      resetIssueReportSendButtonVisual();
      if (reportMain) reportMain.classList.add("hidden");
      if (reportHistoryPanel) reportHistoryPanel.classList.remove("hidden");
      syncIssueReportHeader(true);
      renderFeedbackHistoryList();
    }

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

    function closeReportPopover() {
      if (!reportPopover || !reportBtn) return;
      resetIssueReportSendButtonVisual();
      closeIssueReportLogsModal();
      reportPopover.classList.add("hidden");
      reportPopover.setAttribute("aria-hidden", "true");
      reportBtn.classList.remove("active");
      if (reportFeedback) reportFeedback.className = "feedback-msg hidden";
    }

    function openReportPopover() {
      if (!reportPopover || !reportBtn) return;
      closePopover();
      resetIssueReportSendButtonVisual();
      resetIssueReportPopoverHeight();
      reportPopover.classList.remove("hidden");
      reportPopover.setAttribute("aria-hidden", "false");
      reportBtn.classList.add("active");
      if (reportFeedback) reportFeedback.className = "feedback-msg hidden";
      showIssueReportMainPane();
      if (reportMessage) reportMessage.focus();
      syncIssueReportSendBtn();
    }

    async function submitFeedbackFromApp() {
      if (!reportMessage || !reportFeedback || !reportOpenBtn) return;
      const message = reportMessage.value.trim();
      if (!message || issueReportSending) return;
      issueReportSending = true;
      setIssueReportSendLoading(true);
      syncIssueReportSendBtn();
      try {
        const st = await checkStatus();
        const version = st && st.app_version ? String(st.app_version) : "unknown";
        const navP = String(navigator.platform || "").toLowerCase();
        let platform = "unknown";
        if (navP.includes("win")) platform = "windows";
        else if (navP.includes("mac")) platform = "macos";
        else if (navP.includes("linux")) platform = "linux";
        let logText = "";
        if (issueReportAttachLogs()) {
          try {
            const lr = await api.sessionLogsApi.get();
            if (lr.ok) {
              logText = await lr.text();
              const maxL = 100000;
              if (logText.length > maxL) {
                logText =
                  logText.slice(logText.length - maxL) +
                  "\n… (truncated)\n";
              }
            }
          } catch (_) {}
        }
        const payload = {
          message,
          version,
          platform,
          timestamp: Math.floor(Date.now() / 1000),
          clientToken: getFeedbackClientToken(),
        };
        if (logText) payload.logText = logText;
        const res = await fetch(FEEDBACK_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) {
          setIssueReportSendLoading(false);
          QG.ui.feedbackMessage.show(reportFeedback, "Failed to send", false);
          return;
        }
        const data = await res.json().catch(() => ({}));
        const id = data && data.id ? String(data.id) : "";
        reportMessage.value = "";
        if (reportFeedback) reportFeedback.className = "feedback-msg hidden";
        flashIssueReportSendSuccess();
        if (id) {
          pushFeedbackHistory({
            id,
            messagePreview: message,
            version,
            platform,
            timestamp: payload.timestamp,
            closed: false,
            hasLog: Boolean(logText),
            clientToken: payload.clientToken,
          });
          syncIssueReportOpenCountBadge();
          if (
            reportHistoryPanel &&
            !reportHistoryPanel.classList.contains("hidden")
          ) {
            renderFeedbackHistoryList();
          }
        }
      } catch (_) {
        setIssueReportSendLoading(false);
        QG.ui.feedbackMessage.show(reportFeedback, "Failed to send", false);
      } finally {
        issueReportSending = false;
        syncIssueReportSendBtn();
      }
    }

    if (reportHistoryBtn) {
      reportHistoryBtn.addEventListener("click", () => {
        const historyVisible =
          reportHistoryPanel && !reportHistoryPanel.classList.contains("hidden");
        if (historyVisible) showIssueReportMainPane();
        else showIssueReportHistoryPane();
      });
    }
    syncIssueReportOpenCountBadge();
    document.querySelectorAll(".issue-report-popover-resize").forEach((bar) => {
      bar.addEventListener("pointerdown", onIssueReportPopoverResizeDown);
    });
    if (reportLogPreviewBtn) {
      reportLogPreviewBtn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        void openIssueReportLogsModal();
      });
    }
    if (logsModalBackdrop) {
      logsModalBackdrop.addEventListener("click", () => closeIssueReportLogsModal());
    }
    if (logsModalCloseBtn) {
      logsModalCloseBtn.addEventListener("click", () => closeIssueReportLogsModal());
    }
    if (logsModalDoneBtn) {
      logsModalDoneBtn.addEventListener("click", () => closeIssueReportLogsModal());
    }

    void (async () => {
      await hydrateFeedbackHistoryFromDisk();
      syncIssueReportOpenCountBadge();
      if (
        reportHistoryPanel &&
        !reportHistoryPanel.classList.contains("hidden")
      ) {
        renderFeedbackHistoryList();
      }
    })();

    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!logsModal || logsModal.classList.contains("hidden")) return;
      closeIssueReportLogsModal();
      e.stopPropagation();
    });

    if (reportOpenBtn) {
      reportOpenBtn.addEventListener("click", () => {
        void submitFeedbackFromApp();
      });
    }
    if (reportMessage) {
      reportMessage.addEventListener("input", syncIssueReportSendBtn);
      syncIssueReportSendBtn();
    }

    gearBtn.addEventListener("click", () => {
      if (popover.classList.contains("hidden")) {
        closeReportPopover();
        openPopover();
      } else {
        closePopover();
      }
    });
    backdrop.addEventListener("click", closePopover);
    closeBtn.addEventListener("click", closePopover);
    if (reportBtn) {
      reportBtn.addEventListener("click", () => {
        if (!reportPopover || reportPopover.classList.contains("hidden")) {
          openReportPopover();
        } else {
          closeReportPopover();
        }
      });
    }
    if (reportCloseBtn) reportCloseBtn.addEventListener("click", closeReportPopover);
    document.addEventListener("mousedown", (e) => {
      if (!reportPopover || reportPopover.classList.contains("hidden")) return;
      const t = e.target;
      if (reportPopover.contains(t)) return;
      if (reportBtn && reportBtn.contains(t)) return;
      if (logsModal && !logsModal.classList.contains("hidden") && logsModal.contains(t)) return;
      closeReportPopover();
    });


  }

  feedbackFeature.issueReport = feedbackFeature.issueReport || {};
  feedbackFeature.issueReport.init = init;
})();
