(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g.api;
  const features = (g.features = g.features || {});
  const settings = (features.settings = features.settings || {});

  function setValue(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
  }

  function setCheck(id, val) {
    const el = document.getElementById(id);
    if (el) el.checked = val;
  }

  /** Push server `config` + `capabilities` into cfg + dl-* form ids (mirrors legacy `loadSettingsIntoForm`). */
  function mirrorConfigOntoForms(cfg, capabilities) {
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
    setCheck("cfg-lyrics-enabled", cfg.lyrics_enabled === "true");
    setCheck("cfg-og-cover", cfg.og_cover === "true");
    setCheck("cfg-no-cover", cfg.no_cover === "true");
    setCheck("cfg-albums-only", cfg.albums_only === "true");
    setCheck("cfg-no-m3u", cfg.no_m3u === "true");
    setCheck("cfg-no-fallback", cfg.no_fallback === "true");
    setCheck("cfg-no-database", cfg.no_database === "true");
    setCheck("cfg-smart-discography", cfg.smart_discography === "true");

    setValue("dl-directory", cfg.default_folder || "Qobuz Downloads");
    setValue("dl-quality", cfg.default_quality || "");
    setValue("dl-folder-format", cfg.folder_format || "");
    setValue("dl-track-format", cfg.track_format || "");
    setCheck("dl-embed-art", cfg.embed_art === "true");
    setCheck("dl-lyrics-enabled", cfg.lyrics_enabled === "true");
    setCheck("dl-lyrics-embed-metadata", cfg.lyrics_embed_metadata === "true");

    const lo = features.lyrics && features.lyrics.lyricOutputSettings;
    if (lo && lo.setChecks) {
      lo.setChecks(
        cfg.lyrics_enabled === "true",
        cfg.lyrics_embed_metadata === "true",
      );
    }

    setCheck("dl-og-cover", cfg.og_cover === "true");
    setCheck("dl-no-cover", cfg.no_cover === "true");
    setCheck("dl-albums-only", cfg.albums_only === "true");
    setCheck("dl-no-m3u", cfg.no_m3u === "true");
    setCheck("dl-no-fallback", cfg.no_fallback === "true");
    setCheck("dl-no-db", cfg.no_database === "true");
    setCheck("dl-smart-discography", cfg.smart_discography === "true");
    setCheck("dl-fix-md5s", cfg.fix_md5s === "true");
    setCheck("dl-digital-booklet", cfg.no_credits !== "true");
    setCheck("dl-native-lang", cfg.native_lang === "true");
    setCheck("dl-segmented-fallback", cfg.segmented_fallback !== "false");
    setCheck(
      "dl-multiple-disc-one-dir",
      cfg.multiple_disc_one_dir !== "true",
    );
    setValue("dl-multiple-disc-prefix", cfg.multiple_disc_prefix || "Disc");
    setValue(
      "dl-multiple-disc-track-format",
      cfg.multiple_disc_track_format ||
        "{disc_number_unpadded}{track_number} - {tracktitle}",
    );
    setValue("dl-max-workers", cfg.max_workers || "1");
    setValue("dl-delay-seconds", cfg.delay_seconds || "0");
    setCheck("dl-tag-album-artist", cfg.no_album_artist_tag !== "true");
    setCheck("dl-tag-album-title", cfg.no_album_title_tag !== "true");
    setCheck("dl-tag-track-artist", cfg.no_track_artist_tag !== "true");
    setCheck("dl-tag-track-title", cfg.no_track_title_tag !== "true");
    setCheck("dl-tag-release-date", cfg.no_release_date_tag !== "true");
    setCheck("dl-tag-media-type", cfg.no_media_type_tag !== "true");
    setCheck("dl-tag-genre", cfg.no_genre_tag !== "true");
    setCheck("dl-tag-track-number", cfg.no_track_number_tag !== "true");
    setCheck("dl-tag-track-total", cfg.no_track_total_tag !== "true");
    setCheck("dl-tag-disc-number", cfg.no_disc_number_tag !== "true");
    setCheck("dl-tag-disc-total", cfg.no_disc_total_tag !== "true");
    setCheck("dl-tag-composer", cfg.no_composer_tag !== "true");
    setCheck("dl-tag-explicit", cfg.no_explicit_tag !== "true");
    setCheck("dl-tag-copyright", cfg.no_copyright_tag !== "true");
    setCheck("dl-tag-label", cfg.no_label_tag !== "true");
    setCheck("dl-tag-upc", cfg.no_upc_tag !== "true");
    setCheck("dl-tag-isrc", cfg.no_isrc_tag !== "true");
    setCheck(
      "dl-meta-title-from-track-format",
      cfg.tag_title_from_track_format !== "false",
    );
    setCheck(
      "dl-meta-album-from-folder-format",
      cfg.tag_album_from_folder_format !== "false",
    );

    const md5Toggle = document.getElementById("dl-fix-md5s");
    if (md5Toggle) {
      const hasFlac = !!(capabilities && capabilities.flac_cli);
      md5Toggle.disabled = !hasFlac;
      if (!hasFlac) {
        md5Toggle.checked = false;
        md5Toggle.closest(".toggle-label")?.setAttribute(
          "data-tip",
          "Fix FLAC MD5 needs the `flac` CLI tool. It is not available in this runtime.",
        );
      }
    }
  }

  async function loadIntoForm() {
    try {
      const { data } = await api.getJson("/api/status");
      const cfg = data.config || {};
      const capabilities = data.capabilities || {};
      mirrorConfigOntoForms(cfg, capabilities);
    } catch (e) {
      console.error("Failed to load settings", e);
    }
  }

  settings.settingsForm = settings.settingsForm || {};
  settings.settingsForm.loadIntoForm = loadIntoForm;
  settings.settingsForm.mirrorConfigOntoForms = mirrorConfigOntoForms;
})();
