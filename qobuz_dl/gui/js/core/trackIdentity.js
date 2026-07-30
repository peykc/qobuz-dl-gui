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

  /** Stable history keys: keep edition tags so remaster vs demo rows do not collide. */
  function normalizeTrackTitleForKey(title) {
    return String(title || "").trim().toLowerCase().replace(/\s+/g, " ");
  }

  function discNumberFromAudioPath(audioPath) {
    const p = String(audioPath || "").replace(/\\/g, "/");
    const fromFolder = parseDiscFromAudioPath(p);
    if (fromFolder > 0) return fromFolder;
    const base = p.split("/").filter(Boolean).pop() || "";
    const codeMatch = base.match(/^(\d+)\s*-/);
    if (!codeMatch || codeMatch[1].length < 3) return 0;
    const enc = parseDiscTrackFromFilenameBase(base);
    return enc && enc.disc > 0 ? enc.disc : 0;
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

  function trackKey(trackNo, title, lyricAlbum, audioPath) {
    const num = normalizeTrackNo(trackNo);
    const t = normalizeTrackTitleForKey(title);
    const a = normalizeTrackTitleForKey(lyricAlbum || "");
    const disc = discNumberFromAudioPath(audioPath || "");
    const discPart = disc > 0 ? `d${disc}::` : "";
    return a ? `${discPart}${num}::${t}::${a}` : `${discPart}${num}::${t}`;
  }

  /**
   * `num + normalized-title` ignoring album suffix. Used while a row might be keyed
   * with or without lyric_album (short TRACK_START vs hydrate) so transient error
   * classification matches parallel / multi-queue downloads.
   */
  function parseDiscFromAudioPath(audioPath) {
    const p = String(audioPath || "").replace(/\\/g, "/");
    const m = p.match(/\/Disc\s*(\d+)\//i);
    if (!m) return 0;
    return parseInt(m[1], 10) || 0;
  }

  function parseDiscTrackFromFilenameBase(base) {
    const name = String(base || "").trim();
    const m = name.match(/^(\d+)\s*-/);
    if (!m) return null;
    const code = m[1];
    if (code.length < 3) {
      return { disc: 1, track: parseInt(code, 10) || 0 };
    }
    const track = parseInt(code.slice(-2), 10) || 0;
    const disc = parseInt(code.slice(0, -2), 10) || 0;
    if (disc <= 0 || track <= 0) return null;
    return { disc, track };
  }

  /** ``{ disc, track }`` for sorting; matches subtitle / filename disc logic. */
  function discTrackSortTuple(audioPath, trackNo) {
    const p = String(audioPath || "").replace(/\\/g, "/");
    const base = p.split("/").filter(Boolean).pop() || "";
    const encoded = parseDiscTrackFromFilenameBase(base);
    const discFromPath = parseDiscFromAudioPath(p);
    const trackFromNo = parseInt(normalizeTrackNo(trackNo), 10) || 0;
    const codeMatch = base.match(/^(\d+)\s*-/);
    const multiDiscFilename = !!(codeMatch && codeMatch[1].length >= 3);
    if (multiDiscFilename && encoded) {
      return { disc: encoded.disc, track: encoded.track };
    }
    if (discFromPath > 0 && trackFromNo > 0) {
      return { disc: discFromPath, track: trackFromNo };
    }
    return { disc: 0, track: trackFromNo };
  }

  /** History row subtitle: ``#3-11`` for multi-disc paths, else ``#11``. */
  function formatTrackStatusSubLabel(trackNo, audioPath) {
    const p = String(audioPath || "").replace(/\\/g, "/");
    const base = p.split("/").filter(Boolean).pop() || "";
    const encoded = parseDiscTrackFromFilenameBase(base);
    const discFromPath = parseDiscFromAudioPath(p);
    const trackFromNo = parseInt(normalizeTrackNo(trackNo), 10) || 0;
    const codeMatch = base.match(/^(\d+)\s*-/);
    const multiDiscFilename = !!(codeMatch && codeMatch[1].length >= 3);
    if (multiDiscFilename && encoded) {
      return `#${encoded.disc}-${String(encoded.track).padStart(2, "0")}`;
    }
    if (discFromPath > 0 && trackFromNo > 0) {
      return `#${discFromPath}-${String(trackFromNo).padStart(2, "0")}`;
    }
    const n = normalizeTrackNo(trackNo);
    return `#${n || "?"}`;
  }

  function applyTrackStatusSubLabel(card) {
    if (!card) return;
    const sub = card.querySelector(".track-status-sub");
    if (!sub) return;
    const base = formatTrackStatusSubLabel(
      card.dataset.trackNo || "",
      card.dataset.audioPath || "",
    );
    const durSec = parseInt(card.dataset.durationSec || "0", 10) || 0;
    const fmt =
      window.QobuzGui &&
      window.QobuzGui.core &&
      window.QobuzGui.core.format &&
      window.QobuzGui.core.format.formatAttachDur;
    if (durSec > 0 && typeof fmt === "function") {
      sub.textContent = `${base} · ${fmt(durSec)}`;
      return;
    }
    sub.textContent = base;
  }

  function syncCardTrackKey(card) {
    if (!card) return "";
    const titleEl = card.querySelector(".track-status-title");
    const key = trackKey(
      card.dataset.trackNo || "",
      (titleEl && titleEl.textContent) || "",
      card.dataset.lyricAlbum || "",
      card.dataset.audioPath || "",
    );
    if (key) card.dataset.trackKey = key;
    return key;
  }

  /** www.qobuz.com storefront URL (not play.qobuz streaming). */
  function qobuzStoreUrlFromHistoryFields(
    detail,
    releaseAlbumId,
    slotTrackId,
    storeSlug,
  ) {
    const d = String(detail || "").trim();
    if (/^https:\/\/www\.qobuz\.com\//i.test(d)) return d;
    const slug =
      String(storeSlug || "us-en")
        .trim()
        .toLowerCase() || "us-en";
    const rid = String(releaseAlbumId || "").trim();
    const sid = String(slotTrackId || "").trim();
    if (rid) return `https://www.qobuz.com/${slug}/album/-/${rid}`;
    if (sid) return `https://www.qobuz.com/${slug}/track/-/${sid}`;
    return "";
  }

  function cardForHistoryKey(cardMap, key) {
    const k = String(key || "").trim();
    if (!k || !cardMap) return null;
    if (cardMap.has(k)) return cardMap.get(k) || null;
    const stem = trackKeyStem(k);
    if (!stem) return null;
    for (const [mapKey, card] of cardMap) {
      if (trackKeyStem(mapKey) === stem) return card || null;
    }
    return null;
  }

  function qobuzAlbumIdFromUrl(url) {
    const s = String(url || "").trim();
    const m = s.match(
      /(?:https?:\/\/(?:www|open|play)\.qobuz\.com)?(?:\/[a-z]{2}-[a-z]{2})?\/album(?:\/[-\w\d]+)?\/([\w\d]+)/i,
    );
    return m ? String(m[1] || "").trim() : "";
  }

  function queueContextForRelease(releaseAlbumId) {
    const rid = String(releaseAlbumId || "").trim();
    if (!rid) return { cover: "", artist: "" };
    const cards = document.querySelectorAll("#dl-queue .queue-card");
    for (let i = 0; i < cards.length; i++) {
      const card = cards[i];
      const url = (card.dataset.url || "").trim();
      if (qobuzAlbumIdFromUrl(url) !== rid) continue;
      const img = card.querySelector("img.queue-card-art");
      const cover = (img && img.getAttribute("src")) || "";
      const artistEl = card.querySelector(".queue-card-artist");
      const artist =
        artistEl && artistEl.textContent
          ? String(artistEl.textContent).trim()
          : "";
      return { cover, artist };
    }
    return { cover: "", artist: "" };
  }

  function lyricArtistFromAudioPath(audioPath) {
    const p = String(audioPath || "").replace(/\\/g, "/").trim();
    if (!p) return "";
    const parts = p.split("/").filter(Boolean);
    const musicIdx = parts.findIndex((seg) => seg.toLowerCase() === "music");
    if (musicIdx >= 0 && musicIdx + 1 < parts.length) {
      return parts[musicIdx + 1].trim();
    }
    if (parts.length >= 3) {
      return parts[parts.length - 3].trim();
    }
    return "";
  }

  /** Artist for lyric/attach search: card → path → siblings → queue album card. */
  function resolveHistoryArtistForCard(card, pendingPrefix) {
    if (!card) return "";
    let artist = (card.dataset.lyricArtist || "").trim();
    if (artist) return artist;

    const ap = String(card.dataset.audioPath || "").trim();
    const pending = String(pendingPrefix || "__GUI_PENDING__:slot:");
    if (ap && !ap.startsWith(pending)) {
      artist = lyricArtistFromAudioPath(ap);
      if (artist) {
        card.dataset.lyricArtist = artist;
        return artist;
      }
    }

    const alb = (card.dataset.lyricAlbum || "").trim();
    if (alb) {
      const siblings = document.querySelectorAll(
        "#dl-track-status .track-status-card",
      );
      for (let i = 0; i < siblings.length; i++) {
        const c = siblings[i];
        if (c === card) continue;
        if ((c.dataset.lyricAlbum || "").trim() !== alb) continue;
        const a = (c.dataset.lyricArtist || "").trim();
        if (a) {
          card.dataset.lyricArtist = a;
          return a;
        }
      }
    }

    const rid = (card.dataset.releaseAlbumId || "").trim();
    const fromQueue = queueContextForRelease(rid);
    if (fromQueue.artist) {
      card.dataset.lyricArtist = fromQueue.artist;
      return fromQueue.artist;
    }
    return "";
  }

  function clearSubstituteLyricMeta(card) {
    if (!card || !card.dataset) return;
    delete card.dataset.substituteLyricTitle;
    delete card.dataset.substituteLyricArtist;
    delete card.dataset.substituteLyricAlbum;
    delete card.dataset.substituteLyricDurationSec;
    delete card.dataset.substituteLyricExplicit;
  }

  /** Persist Qobuz metadata for the attached replacement (not the album slot). */
  function applySubstituteLyricMetaToCard(card, meta) {
    if (!card || !card.dataset || !meta) return;
    const title = String(meta.title || "").trim();
    const artist = String(meta.artist || "").trim();
    const album = String(
      meta.album_title || meta.album || meta.lyric_album || "",
    ).trim();
    let dur = parseInt(String(meta.duration_sec ?? meta.durationSec ?? "0"), 10);
    if (Number.isNaN(dur)) dur = 0;
    if (title) card.dataset.substituteLyricTitle = title;
    else delete card.dataset.substituteLyricTitle;
    if (artist) card.dataset.substituteLyricArtist = artist;
    else delete card.dataset.substituteLyricArtist;
    if (album) card.dataset.substituteLyricAlbum = album;
    else delete card.dataset.substituteLyricAlbum;
    if (dur > 0) card.dataset.substituteLyricDurationSec = String(dur);
    else delete card.dataset.substituteLyricDurationSec;
    if (meta.explicit === true || meta.explicit === 1) {
      card.dataset.substituteLyricExplicit = "1";
    } else if (meta.explicit === false || meta.explicit === 0) {
      card.dataset.substituteLyricExplicit = "0";
    } else {
      delete card.dataset.substituteLyricExplicit;
    }
  }

  function applySubstituteLyricMetaFromDbItem(card, it) {
    if (!card || !it) return;
    applySubstituteLyricMetaToCard(card, {
      title: it.substitute_lyric_title || "",
      artist: it.substitute_lyric_artist || "",
      album_title: it.substitute_lyric_album || "",
      duration_sec: it.substitute_lyric_duration_sec,
      explicit:
        it.substitute_lyric_explicit === true
          ? true
          : it.substitute_lyric_explicit === false
            ? false
            : null,
    });
  }

  /**
   * Title/artist/album/duration for lyric search + autosearch only.
   * Replacement rows (resolvedBy=search) use the attached Qobuz track; placeholders and
   * normal downloads use the history row / slot display fields.
   */
  function substituteLyricFieldsForPersist(card) {
    if (!card || (card.dataset.resolvedBy || "").trim() !== "search") {
      return {};
    }
    const title = String(card.dataset.substituteLyricTitle || "").trim();
    if (!title) return {};
    const artist = String(card.dataset.substituteLyricArtist || "").trim();
    const album = String(card.dataset.substituteLyricAlbum || "").trim();
    let dur = parseInt(
      String(card.dataset.substituteLyricDurationSec || "0"),
      10,
    );
    if (Number.isNaN(dur)) dur = 0;
    const te = (card.dataset.substituteLyricExplicit || "").trim();
    let subEx = null;
    if (te === "1") subEx = true;
    else if (te === "0") subEx = false;
    return {
      substitute_lyric_title: title,
      substitute_lyric_artist: artist,
      substitute_lyric_album: album,
      substitute_lyric_duration_sec: dur,
      substitute_lyric_explicit: subEx,
    };
  }

  function lyricSearchContextForCard(card) {
    if (!card) {
      return {
        title: "",
        artist: "",
        album: "",
        durationSec: 0,
        trackExplicit: null,
      };
    }
    const resolvedBy = (card.dataset.resolvedBy || "").trim();
    const useSubstitute =
      resolvedBy === "search" &&
      String(card.dataset.substituteLyricTitle || "").trim();
    if (useSubstitute) {
      let durationSec = parseInt(
        String(
          card.dataset.substituteLyricDurationSec ||
            card.dataset.durationSec ||
            "0",
        ),
        10,
      );
      if (Number.isNaN(durationSec)) durationSec = 0;
      const te = (card.dataset.substituteLyricExplicit || "").trim();
      let trackExplicit = null;
      if (te === "1") trackExplicit = true;
      else if (te === "0") trackExplicit = false;
      return {
        title: String(card.dataset.substituteLyricTitle || "").trim(),
        artist: String(card.dataset.substituteLyricArtist || "").trim(),
        album:
          String(card.dataset.substituteLyricAlbum || "").trim() ||
          String(card.dataset.lyricAlbum || "").trim(),
        durationSec,
        trackExplicit,
      };
    }
    const titleEl = card.querySelector(".track-status-title");
    const displayTitle = ((titleEl && titleEl.textContent) || "").trim();
    let durationSec = parseInt(String(card.dataset.durationSec || "0"), 10);
    if (Number.isNaN(durationSec)) durationSec = 0;
    const teRaw = card.dataset.trackExplicit;
    let trackExplicit = null;
    if (teRaw === "1") trackExplicit = true;
    else if (teRaw === "0") trackExplicit = false;
    return {
      title: displayTitle,
      artist: resolveHistoryArtistForCard(card, "__GUI_PENDING__:slot:"),
      album: String(card.dataset.lyricAlbum || "").trim(),
      durationSec,
      trackExplicit,
    };
  }

  function rebindCardTrackKey(cardMap, card, orderAll) {
    if (!card || !cardMap) return syncCardTrackKey(card);
    const prev = (card.dataset.trackKey || "").trim();
    const next = syncCardTrackKey(card);
    if (!next) return "";
    for (const [mapKey, mapped] of [...cardMap]) {
      if (mapped === card && mapKey !== next) cardMap.delete(mapKey);
    }
    cardMap.set(next, card);
    if (Array.isArray(orderAll) && prev && prev !== next) {
      const idx = orderAll.indexOf(prev);
      if (idx >= 0) orderAll[idx] = next;
    }
    return next;
  }

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
  ti.normalizeTrackTitleForKey = normalizeTrackTitleForKey;
  ti.parseTrackRef = parseTrackRef;
  ti.trackKey = trackKey;
  ti.discNumberFromAudioPath = discNumberFromAudioPath;
  ti.discTrackSortTuple = discTrackSortTuple;
  ti.trackKeyStem = trackKeyStem;
  ti.formatTrackStatusSubLabel = formatTrackStatusSubLabel;
  ti.applyTrackStatusSubLabel = applyTrackStatusSubLabel;
  ti.syncCardTrackKey = syncCardTrackKey;
  ti.qobuzStoreUrlFromHistoryFields = qobuzStoreUrlFromHistoryFields;
  ti.cardForHistoryKey = cardForHistoryKey;
  ti.rebindCardTrackKey = rebindCardTrackKey;
  ti.resolveHistoryArtistForCard = resolveHistoryArtistForCard;
  ti.clearSubstituteLyricMeta = clearSubstituteLyricMeta;
  ti.applySubstituteLyricMetaToCard = applySubstituteLyricMetaToCard;
  ti.applySubstituteLyricMetaFromDbItem = applySubstituteLyricMetaFromDbItem;
  ti.lyricSearchContextForCard = lyricSearchContextForCard;
  ti.substituteLyricFieldsForPersist = substituteLyricFieldsForPersist;
  ti.queueContextForRelease = queueContextForRelease;
  ti.lyricArtistFromAudioPath = lyricArtistFromAudioPath;
})();
