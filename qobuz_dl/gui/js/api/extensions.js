(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g && g.api;
  if (!api) return;

  function jsonPost(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body != null ? body : {}),
    });
  }

  api.statusApi = {
    get() {
      return api.getJson("/api/status");
    },
    fetchRaw() {
      return fetch("/api/status");
    },
  };

  api.configApi = {
    post(payload) {
      return jsonPost("/api/config", payload);
    },
  };

  api.searchApi = {
    search(query, type, limit) {
      return fetch(
        `/api/search?q=${encodeURIComponent(query)}&type=${encodeURIComponent(type)}&limit=${limit}`,
      );
    },
    artistReleases(artistId, limit, sort) {
      const lim = limit != null ? limit : 50;
      // Default relevance unless the UI explicitly selected newest.
      const sortMode =
        String(sort || "relevance").toLowerCase() === "newest"
          ? "newest"
          : "relevance";
      return fetch(
        `/api/artist_releases?id=${encodeURIComponent(artistId)}&limit=${lim}&sort=${encodeURIComponent(sortMode)}`,
      );
    },
    albumTracks(albumId) {
      return fetch(
        `/api/album_tracks?id=${encodeURIComponent(albumId || "")}`,
      );
    },
  };

  api.queueApi = {
    persist(payload) {
      return jsonPost("/api/download-queue", payload);
    },
    get() {
      return fetch("/api/download-queue");
    },
  };

  api.downloadApi = {
    resolve(payload) {
      return jsonPost("/api/resolve", payload);
    },
    checkDiscography(payload) {
      return jsonPost("/api/check_discography", payload);
    },
    pause() {
      return fetch("/api/pause", { method: "POST" });
    },
    start(payload) {
      return jsonPost("/api/download", payload);
    },
  };

  api.historyApi = {
    postLyrics(body) {
      return jsonPost("/api/download-history/lyrics", body);
    },
    upsert(body) {
      return jsonPost("/api/download-history/upsert", body);
    },
    list() {
      return fetch("/api/download-history");
    },
    clear() {
      return fetch("/api/download-history/clear", { method: "POST" });
    },
  };

  api.lyricsApi = {
    search(body, signal) {
      const opts = {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      };
      if (signal) opts.signal = signal;
      return fetch("/api/lyrics/search", opts);
    },
    attach(body) {
      return jsonPost("/api/lyrics/attach", body);
    },
    local(audioPath) {
      return fetch(
        `/api/lyrics/local?audio_path=${encodeURIComponent(audioPath)}`,
      );
    },
    fetchById(id) {
      return fetch(`/api/lyrics/fetch?id=${encodeURIComponent(id)}`);
    },
    attachedId(audioPath, signal) {
      return fetch(
        `/api/lyrics/attached-id?audio_path=${encodeURIComponent(audioPath)}`,
        { signal },
      );
    },
  };

  api.themeApi = {
    get() {
      return fetch("/api/gui/theme");
    },
    save(theme) {
      return jsonPost("/api/gui/theme", { theme });
    },
  };

  function lyricDownloadOptionsFromUi() {
    const o = {};
    const lrc = document.getElementById("dl-lyrics-enabled");
    const emb = document.getElementById("dl-lyrics-embed-metadata");
    if (lrc) o.lyrics_enabled = !!lrc.checked;
    if (emb) o.lyrics_embed_metadata = !!emb.checked;
    return o;
  }

  api.replacementApi = {
    lyricDownloadOptionsFromUi,
    searchAttachTracks(body) {
      return jsonPost("/api/search_tracks_attach", body);
    },
    writeMissingPlaceholder(body) {
      return jsonPost("/api/write_missing_track_placeholder", body);
    },
    downloadAttachTrack(body) {
      return jsonPost("/api/download_attach_track", body);
    },
    deleteResolutionFile(body) {
      return jsonPost("/api/delete_track_resolution_file", body);
    },
  };

  api.updateApi = {
    install(payload) {
      return jsonPost("/api/update/install", payload);
    },
    check(querySuffix) {
      return fetch("/api/update/check" + querySuffix);
    },
  };

  api.feedbackApi = {
    persistHistory(items) {
      return jsonPost("/api/feedback-history", {
        items: items.slice(0, 100),
      });
    },
    getHistory() {
      return fetch("/api/feedback-history");
    },
  };

  api.utilityApi = {
    revealInFolder(audioPath) {
      return jsonPost("/api/reveal-in-folder", { audio_path: audioPath });
    },
    browseFolder() {
      return fetch("/api/browse_folder", { method: "POST" });
    },
  };

  api.setupApi = {
    oauthStart(body) {
      return jsonPost("/api/oauth/start", body != null ? body : {});
    },
    oauthStatus(attemptId) {
      return fetch(
        `/api/oauth/status?attempt_id=${encodeURIComponent(attemptId || "")}`,
      );
    },
    oauthCancel(attemptId) {
      return jsonPost("/api/oauth/cancel", { attempt_id: attemptId || "" });
    },
    tokenLogin(body) {
      return jsonPost("/api/token_login", body);
    },
    setup(body) {
      return jsonPost("/api/setup", body);
    },
    connect() {
      return fetch("/api/connect", { method: "POST" });
    },
    purge() {
      return fetch("/api/purge", { method: "POST" });
    },
  };

  api.sessionLogsApi = {
    get() {
      return fetch("/api/session-logs");
    },
  };
})();
