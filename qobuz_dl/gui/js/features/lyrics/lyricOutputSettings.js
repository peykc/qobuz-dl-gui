(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g.api;
  const features = (g.features = g.features || {});
  const lyrics = (features.lyrics = features.lyrics || {});
  const mod = (lyrics.lyricOutputSettings = lyrics.lyricOutputSettings || {});

  function setChecks(lrcEnabled, metadataEnabled) {
    [
      ["dl-lyrics-enabled", lrcEnabled],
      ["lyric-output-lrc", lrcEnabled],
      ["dl-lyrics-embed-metadata", metadataEnabled],
      ["lyric-output-metadata", metadataEnabled],
    ].forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.checked = !!val;
    });
  }

  function readChecks(sourcePrefix) {
    const lrc =
      document.getElementById(
        sourcePrefix === "popover" ? "lyric-output-lrc" : "dl-lyrics-enabled",
      )?.checked || false;
    const metadata =
      document.getElementById(
        sourcePrefix === "popover"
          ? "lyric-output-metadata"
          : "dl-lyrics-embed-metadata",
      )?.checked || false;
    return { lrc, metadata };
  }

  function syncFromDownload() {
    const { lrc, metadata } = readChecks("download");
    setChecks(lrc, metadata);
  }

  function persist(lrcEnabled, metadataEnabled) {
    api.configApi
      .post({
        lyrics_enabled: String(!!lrcEnabled),
        lyrics_embed_metadata: String(!!metadataEnabled),
      })
      .catch(() => {});
  }

  function bindPopoverToggles() {
    ["lyric-output-lrc", "lyric-output-metadata"].forEach((id) => {
      const el = document.getElementById(id);
      if (!el || el.dataset.bound === "1") return;
      el.dataset.bound = "1";
      el.addEventListener("change", () => {
        const { lrc, metadata } = readChecks("popover");
        setChecks(lrc, metadata);
        persist(lrc, metadata);
      });
    });
  }

  mod.setChecks = setChecks;
  mod.readChecks = readChecks;
  mod.syncFromDownload = syncFromDownload;
  mod.persist = persist;
  mod.bindPopoverToggles = bindPopoverToggles;
})();
