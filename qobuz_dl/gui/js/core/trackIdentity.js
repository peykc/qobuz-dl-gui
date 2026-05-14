(function () {
  "use strict";
  const ti = (window.QobuzGui.core.trackIdentity =
    window.QobuzGui.core.trackIdentity || {});

  function normalizeTrackNo(trackNo) {
    const raw = String(trackNo || "").trim();
    if (!raw) return "";
    const m = raw.match(/\d+/);
    if (!m) return raw;
    return String(parseInt(m[0], 10));
  }

  function normalizeTrackTitle(title) {
    let t = String(title || "").trim().toLowerCase();
    if (!t) return "";
    t = t.replace(/\s+/g, " ");
    while (/\s*\([^)]*\)\s*$/.test(t)) {
      t = t.replace(/\s*\([^)]*\)\s*$/, "").trim();
    }
    return t;
  }

  function parseTrackRef(trackNo, title) {
    const rawTitle = String(title || "").trim();
    const rawNo = String(trackNo || "").trim();
    if (rawNo) {
      return { trackNo: rawNo, title: rawTitle };
    }
    const m = rawTitle.match(/^(\d+)\.\s*(.+)$/);
    if (m) return { trackNo: m[1], title: m[2] };
    return { trackNo: "", title: rawTitle };
  }

  function trackKey(trackNo, title, lyricAlbum) {
    const num = normalizeTrackNo(trackNo);
    const t = normalizeTrackTitle(title);
    const a = normalizeTrackTitle(lyricAlbum || "");
    return a ? `${num}::${t}::${a}` : `${num}::${t}`;
  }

  /**
   * `num + normalized-title` ignoring album suffix. Used while a row might be keyed
   * with or without lyric_album (short TRACK_START vs hydrate) so transient error
   * classification matches parallel / multi-queue downloads.
   */
  function trackKeyStem(fullKey) {
    const k = String(fullKey || "").trim();
    if (!k) return "";
    const sep = "::";
    const i = k.indexOf(sep);
    if (i < 0) return k;
    const num = k.slice(0, i);
    const rest = k.slice(i + sep.length);
    const j = rest.indexOf(sep);
    const t = j < 0 ? rest : rest.slice(0, j);
    if (!num && !t.trim()) return k;
    return t ? `${num}::${t}` : `${num}`;
  }

  ti.normalizeTrackNo = normalizeTrackNo;
  ti.normalizeTrackTitle = normalizeTrackTitle;
  ti.parseTrackRef = parseTrackRef;
  ti.trackKey = trackKey;
  ti.trackKeyStem = trackKeyStem;
})();
