/**
 * Download Start/Pause button click flow (D1E).
 *
 * Invoked once from `app.js` `initDownload()` via `bootstrapStartPause(deps)`.
 */
(function () {
  "use strict";
  const g = window.QobuzGui;
  const dlroot = (g.features.download = g.features.download || {});

  function buildStartPayload(urls) {
    return {
      urls,
      quality: document.getElementById("dl-quality")?.value || null,
      directory:
        document.getElementById("dl-directory")?.value.trim() || null,
      embed_art: document.getElementById("dl-embed-art")?.checked,
      lyrics_enabled: document.getElementById("dl-lyrics-enabled")?.checked,
      lyrics_embed_metadata: document.getElementById("dl-lyrics-embed-metadata")
        ?.checked,
      og_cover: document.getElementById("dl-og-cover")?.checked,
      no_cover: document.getElementById("dl-no-cover")?.checked,
      albums_only: document.getElementById("dl-albums-only")?.checked,
      no_m3u: document.getElementById("dl-no-m3u")?.checked,
      convert_to_alac: document.getElementById("dl-convert-alac")?.checked,
      no_fallback: document.getElementById("dl-no-fallback")?.checked,
      no_db: document.getElementById("dl-no-db")?.checked,
      smart_discography: document.getElementById("dl-smart-discography")
        ?.checked,
      fix_md5s: document.getElementById("dl-fix-md5s")?.checked,
      no_credits: !document.getElementById("dl-digital-booklet")?.checked,
      native_lang: document.getElementById("dl-native-lang")?.checked,
      segmented_fallback: document.getElementById("dl-segmented-fallback")
        ?.checked,
      multiple_disc_prefix:
        document.getElementById("dl-multiple-disc-prefix")?.value.trim() ||
        null,
      multiple_disc_one_dir: !document.getElementById("dl-multiple-disc-one-dir")
        ?.checked,
      multiple_disc_track_format:
        document
          .getElementById("dl-multiple-disc-track-format")
          ?.value.trim() || null,
      max_workers:
        parseInt(document.getElementById("dl-max-workers")?.value, 10) || 1,
      delay_seconds:
        parseInt(document.getElementById("dl-delay-seconds")?.value, 10) || 0,
      folder_format:
        document.getElementById("dl-folder-format")?.value.trim() || null,
      track_format:
        document.getElementById("dl-track-format")?.value.trim() || null,
      no_album_artist_tag:
        document.getElementById("dl-tag-album-artist")?.checked === false,
      no_album_title_tag:
        document.getElementById("dl-tag-album-title")?.checked === false,
      no_track_artist_tag:
        document.getElementById("dl-tag-track-artist")?.checked === false,
      no_track_title_tag:
        document.getElementById("dl-tag-track-title")?.checked === false,
      no_release_date_tag:
        document.getElementById("dl-tag-release-date")?.checked === false,
      no_media_type_tag:
        document.getElementById("dl-tag-media-type")?.checked === false,
      no_genre_tag:
        document.getElementById("dl-tag-genre")?.checked === false,
      no_track_number_tag:
        document.getElementById("dl-tag-track-number")?.checked === false,
      no_track_total_tag:
        document.getElementById("dl-tag-track-total")?.checked === false,
      no_disc_number_tag:
        document.getElementById("dl-tag-disc-number")?.checked === false,
      no_disc_total_tag:
        document.getElementById("dl-tag-disc-total")?.checked === false,
      no_composer_tag:
        document.getElementById("dl-tag-composer")?.checked === false,
      no_explicit_tag:
        document.getElementById("dl-tag-explicit")?.checked === false,
      no_copyright_tag:
        document.getElementById("dl-tag-copyright")?.checked === false,
      no_label_tag:
        document.getElementById("dl-tag-label")?.checked === false,
      no_upc_tag: document.getElementById("dl-tag-upc")?.checked === false,
      no_isrc_tag: document.getElementById("dl-tag-isrc")?.checked === false,
      tag_title_from_track_format: document.getElementById(
        "dl-meta-title-from-track-format",
      )?.checked,
      tag_album_from_folder_format: document.getElementById(
        "dl-meta-album-from-folder-format",
      )?.checked,
    };
  }

  function bootstrapStartPause(deps) {
    let clickBound = false;

    function progress() {
      return typeof deps.getProgress === "function" ? deps.getProgress() : null;
    }

    function queueIssues() {
      return typeof deps.getQueueIssues === "function"
        ? deps.getQueueIssues()
        : null;
    }

    function collectUrls() {
      if (typeof deps.isTextMode === "function" && deps.isTextMode()) {
        return (document.getElementById("dl-urls")?.value || "").trim();
      }
      if (typeof deps.getQueueUrlsText === "function") {
        return deps.getQueueUrlsText();
      }
      return "";
    }

    function markQueueCardsPending() {
      document.querySelectorAll("#dl-queue .queue-card").forEach((c) => {
        c.classList.add("dl-pending");
      });
    }

    function reportStartFailure(message) {
      const issues = queueIssues();
      if (issues && typeof issues.applyStartFailureFeedback === "function") {
        issues.applyStartFailureFeedback(message);
        return;
      }
    }

    async function runStart() {
      const urls = collectUrls();
      if (!urls) {
        reportStartFailure("Add a URL to the queue first.");
        return;
      }

      const startDownload = deps.startDownload;
      if (typeof startDownload !== "function") return;

      try {
        const res = await startDownload(buildStartPayload(urls));
        const data = await res.json().catch(() => null);
        if (!data || !data.ok) {
          reportStartFailure(
            (data && data.error) || "Could not start download.",
          );
          return;
        }

        const prog = progress();
        const trackTotal =
          typeof deps.calcProgressDenominatorFromQueue === "function" &&
          !(typeof deps.isTextMode === "function" && deps.isTextMode())
            ? deps.calcProgressDenominatorFromQueue()
            : data.queued;
        prog?.resetForStart({
          urlQueued: data.queued,
          trackTotal,
        });
        queueIssues()?.clearPurchaseIssues();
        queueIssues()?.hideQueueStartFeedback?.();
        markQueueCardsPending();
        prog?.setDownloadingState(true);
      } catch (e) {
        reportStartFailure(
          (e && e.message) || "Network error while starting download.",
        );
      }
    }

    async function runPauseUi() {
      const dlBtn = document.getElementById("dl-btn");
      if (!dlBtn) return;

      dlBtn.dataset.state = "pausing";
      const te = document.getElementById("dl-btn-text");
      if (te) te.textContent = "Pausing…";
      dlBtn.disabled = false;
      dlBtn.style.opacity = "0.6";
      dlBtn.style.cursor = "default";
      dlBtn.style.pointerEvents = "none";

      const pauseDownload = deps.pauseDownload;
      try {
        if (typeof pauseDownload === "function") {
          await pauseDownload();
        }
      } catch (_) {
        dlBtn.dataset.state = "downloading";
        dlBtn.style.opacity = "";
        dlBtn.style.cursor = "";
        dlBtn.style.pointerEvents = "";
        progress()?.setDownloadingState(true);
      }
    }

    async function handleClick() {
      const dlBtn = document.getElementById("dl-btn");
      if (!dlBtn) return;

      if (dlBtn.dataset.state === "downloading") {
        await runPauseUi();
        return;
      }
      if (dlBtn.dataset.state === "pausing") return;

      await runStart();
    }

    function startFromCurrentQueue() {
      const dlBtn = document.getElementById("dl-btn");
      if (!dlBtn) return Promise.resolve();
      if (
        dlBtn.dataset.state === "downloading" ||
        dlBtn.dataset.state === "pausing"
      ) {
        return Promise.resolve();
      }
      return runStart();
    }

    function init() {
      if (clickBound) return;
      const dlBtn = document.getElementById("dl-btn");
      if (!dlBtn) return;
      dlBtn.addEventListener("click", handleClick);
      clickBound = true;
    }

    init();

    return {
      init,
      handleClick,
      startFromCurrentQueue,
      runStart,
      runPauseUi,
    };
  }

  dlroot.internals = dlroot.internals || {};
  dlroot.internals.bootstrapStartPause = bootstrapStartPause;
})();
