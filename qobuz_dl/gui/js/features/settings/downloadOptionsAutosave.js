(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g.api;
  const features = (g.features = g.features || {});
  const settings = (features.settings = features.settings || {});

  function lyricOut() {
    return features.lyrics && features.lyrics.lyricOutputSettings;
  }

  function bind() {
    let _autosaveTimer = null;

    function autosavePayload() {
      const payload = {
        default_quality: document.getElementById("dl-quality").value || "27",
        folder_format: document.getElementById("dl-folder-format").value.trim(),
        track_format: document.getElementById("dl-track-format").value.trim(),
        multiple_disc_track_format: document
          .getElementById("dl-multiple-disc-track-format")
          .value.trim(),
        multiple_disc_prefix: document
          .getElementById("dl-multiple-disc-prefix")
          .value.trim(),
        max_workers: document.getElementById("dl-max-workers").value || "1",
        delay_seconds: document.getElementById("dl-delay-seconds").value || "0",
        embed_art: String(document.getElementById("dl-embed-art").checked),
        lyrics_enabled: String(
          document.getElementById("dl-lyrics-enabled").checked,
        ),
        lyrics_embed_metadata: String(
          document.getElementById("dl-lyrics-embed-metadata").checked,
        ),
        og_cover: String(document.getElementById("dl-og-cover").checked),
        no_cover: String(document.getElementById("dl-no-cover").checked),
        albums_only: String(document.getElementById("dl-albums-only").checked),
        no_m3u: String(document.getElementById("dl-no-m3u").checked),
        no_fallback: String(document.getElementById("dl-no-fallback").checked),
        no_database: String(document.getElementById("dl-no-db").checked),
        fix_md5s: String(document.getElementById("dl-fix-md5s").checked),
        no_credits: String(
          !document.getElementById("dl-digital-booklet").checked,
        ),
        native_lang: String(
          document.getElementById("dl-native-lang").checked,
        ),
        segmented_fallback: String(
          document.getElementById("dl-segmented-fallback").checked,
        ),
        multiple_disc_one_dir: String(
          !document.getElementById("dl-multiple-disc-one-dir").checked,
        ),
        smart_discography: String(
          document.getElementById("dl-smart-discography").checked,
        ),
        no_album_artist_tag: String(
          !document.getElementById("dl-tag-album-artist").checked,
        ),
        no_album_title_tag: String(
          !document.getElementById("dl-tag-album-title").checked,
        ),
        no_track_artist_tag: String(
          !document.getElementById("dl-tag-track-artist").checked,
        ),
        no_track_title_tag: String(
          !document.getElementById("dl-tag-track-title").checked,
        ),
        no_release_date_tag: String(
          !document.getElementById("dl-tag-release-date").checked,
        ),
        no_media_type_tag: String(
          !document.getElementById("dl-tag-media-type").checked,
        ),
        no_genre_tag: String(!document.getElementById("dl-tag-genre").checked),
        no_track_number_tag: String(
          !document.getElementById("dl-tag-track-number").checked,
        ),
        no_track_total_tag: String(
          !document.getElementById("dl-tag-track-total").checked,
        ),
        no_disc_number_tag: String(
          !document.getElementById("dl-tag-disc-number").checked,
        ),
        no_disc_total_tag: String(
          !document.getElementById("dl-tag-disc-total").checked,
        ),
        no_composer_tag: String(
          !document.getElementById("dl-tag-composer").checked,
        ),
        no_explicit_tag: String(
          !document.getElementById("dl-tag-explicit").checked,
        ),
        no_copyright_tag: String(
          !document.getElementById("dl-tag-copyright").checked,
        ),
        no_label_tag: String(!document.getElementById("dl-tag-label").checked),
        no_upc_tag: String(!document.getElementById("dl-tag-upc").checked),
        no_isrc_tag: String(!document.getElementById("dl-tag-isrc").checked),
        tag_title_from_track_format: String(
          document.getElementById("dl-meta-title-from-track-format").checked,
        ),
        tag_album_from_folder_format: String(
          document.getElementById("dl-meta-album-from-folder-format").checked,
        ),
      };
      const dir = document.getElementById("dl-directory").value.trim();
      if (dir) payload.default_folder = dir;
      return payload;
    }

    function autosaveNow() {
      api.configApi.post(autosavePayload()).catch(() => {});
    }

    function scheduleAutosave() {
      if (_autosaveTimer) clearTimeout(_autosaveTimer);
      _autosaveTimer = setTimeout(() => {
        _autosaveTimer = null;
        autosaveNow();
      }, 600);
    }

    [
      "dl-quality",
      "dl-embed-art",
      "dl-og-cover",
      "dl-no-cover",
      "dl-albums-only",
      "dl-segmented-fallback",
      "dl-no-db",
      "dl-native-lang",
      "dl-no-m3u",
      "dl-no-fallback",
      "dl-fix-md5s",
      "dl-lyrics-enabled",
      "dl-lyrics-embed-metadata",
      "dl-smart-discography",
      "dl-digital-booklet",
      "dl-multiple-disc-one-dir",
      "dl-tag-album-artist",
      "dl-tag-album-title",
      "dl-tag-track-artist",
      "dl-tag-track-title",
      "dl-tag-release-date",
      "dl-tag-media-type",
      "dl-tag-genre",
      "dl-tag-track-number",
      "dl-tag-track-total",
      "dl-tag-disc-number",
      "dl-tag-disc-total",
      "dl-tag-composer",
      "dl-tag-explicit",
      "dl-tag-copyright",
      "dl-tag-label",
      "dl-tag-upc",
      "dl-tag-isrc",
      "dl-meta-title-from-track-format",
      "dl-meta-album-from-folder-format",
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", autosaveNow);
    });
    ["dl-lyrics-enabled", "dl-lyrics-embed-metadata"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      const lo = lyricOut();
      el.addEventListener("change", () => {
        if (lo && lo.syncFromDownload) lo.syncFromDownload();
      });
    });

    const sdCheck = document.getElementById("dl-smart-discography");
    if (sdCheck) {
      sdCheck.addEventListener("change", () => {
        if (window._updateQueueBadge) window._updateQueueBadge();
      });
    }

    [
      "dl-directory",
      "dl-folder-format",
      "dl-track-format",
      "dl-multiple-disc-track-format",
      "dl-multiple-disc-prefix",
      "dl-max-workers",
      "dl-delay-seconds",
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", scheduleAutosave);
    });
  }

  settings.downloadOptionsAutosave = settings.downloadOptionsAutosave || {};
  settings.downloadOptionsAutosave.bind = bind;
})();
