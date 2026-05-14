(function () {
  "use strict";
  const g = window.QobuzGui;
  const api = g.api;
  const features = (g.features = g.features || {});

  function queueHas(url) {
    const q = features.queue;
    return Boolean(url && q && typeof q.hasUrl === "function" && q.hasUrl(url));
  }

  function queueAdd(url) {
    const q = features.queue;
    if (url && q && typeof q.addUrl === "function") q.addUrl(url);
  }

  function queueRemove(url) {
    const q = features.queue;
    if (url && q && typeof q.removeUrl === "function") q.removeUrl(url);
  }

  const TIP_SEARCH_QUEUED_IDLE = "In download queue";
  const TIP_SEARCH_QUEUED_REMOVE = "Remove from queue";

  const RESULT_ADD_BTN_HTML_ARROW = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <line x1="5" y1="12" x2="19" y2="12"></line>
            <polyline points="12 5 19 12 12 19"></polyline>
        </svg>
      `;
  const RESULT_ADD_BTN_HTML_CHECK = `
            <span class="result-add-btn-ico-stack">
                <span class="result-add-btn-ico result-add-btn-ico--check" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                </span>
                <span class="result-add-btn-ico result-add-btn-ico--remove" aria-hidden="true">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </span>
            </span>
          `;

  function setSearchResultAddBtnAppearance(addBtn, inQueue) {
    if (!addBtn) return;
    addBtn.classList.toggle("result-add-btn--queued", !!inQueue);
    if (inQueue) {
      addBtn.setAttribute("aria-label", "In download queue, activate to remove");
      addBtn.setAttribute("data-tip", TIP_SEARCH_QUEUED_IDLE);
      addBtn.innerHTML = RESULT_ADD_BTN_HTML_CHECK;
    } else {
      addBtn.setAttribute("aria-label", "Add to Queue");
      addBtn.setAttribute("data-tip", "Add to Queue");
      addBtn.innerHTML = RESULT_ADD_BTN_HTML_ARROW;
    }
  }

  function syncQueuedHighlights() {
    const list = document.getElementById("search-results");
    if (!list) return;
    const queued =
      features.queue && features.queue.getQueuedUrlSet
        ? features.queue.getQueuedUrlSet()
        : new Set();
    list.querySelectorAll(".result-item").forEach((row) => {
      const url = row.dataset.queueUrl || "";
      const inQueue = Boolean(url && queued.has(url));
      row.classList.toggle("result-item--queued", inQueue);
      const btn = row.querySelector(".result-add-btn");
      setSearchResultAddBtnAppearance(btn, inQueue);
    });
  }

  let _searchResults = [];
  const _QOBUZ_SEARCH_PAGE_INITIAL = 10;
  const _QOBUZ_SEARCH_PAGE_STEP = 5;
  const _QOBUZ_SEARCH_MAX = 50;
  let _searchVisibleCount = 0;
  let _searchLastQuery = "";
  let _sidebarSearchScrollRaf = null;

  function initSearch() {
    const luckySlider = document.getElementById("lucky-number");
    const luckyVal = document.getElementById("lucky-number-val");
    if (luckySlider && luckyVal) {
      luckySlider.addEventListener("input", () => {
        luckyVal.textContent = luckySlider.value;
      });
    }

    const luckyToggle = document.getElementById("lucky-toggle-btn");
    const luckyPanel = document.getElementById("lucky-panel");
    if (luckyToggle && luckyPanel) {
      const clover = luckyToggle.querySelector(".lucky-toggle-icon--clover");
      const closeIc = luckyToggle.querySelector(".lucky-toggle-icon--close");
      function syncLuckyToggleUi(expanded) {
        luckyToggle.setAttribute("aria-expanded", expanded ? "true" : "false");
        const tip = expanded ? "Hide lucky search" : "Show lucky search";
        luckyToggle.setAttribute("data-tip", tip);
        luckyToggle.setAttribute("aria-label", tip);
        luckyToggle.removeAttribute("title");
        if (clover) clover.classList.toggle("hidden", expanded);
        if (closeIc) closeIc.classList.toggle("hidden", !expanded);
      }
      luckyToggle.addEventListener("click", () => {
        const willShow = luckyPanel.classList.contains("hidden");
        luckyPanel.classList.toggle("hidden", !willShow);
        syncLuckyToggleUi(willShow);
      });
      syncLuckyToggleUi(false);
    }

    document.getElementById("search-btn").addEventListener("click", doSearch);
    const searchQuery = document.getElementById("search-query");
    const searchBtn = document.getElementById("search-btn");
    
    searchQuery.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !searchBtn.disabled) doSearch();
    });
    
    searchQuery.addEventListener("input", () => {
      const query = searchQuery.value.trim();
      searchBtn.disabled = query.length < 3;
    });

    const sidebarScroll = document.querySelector(".sidebar-results-scroll");
    if (sidebarScroll && !sidebarScroll.dataset.pagingScrollBound) {
      sidebarScroll.dataset.pagingScrollBound = "1";
      sidebarScroll.addEventListener("scroll", _onSidebarSearchScroll, {
        passive: true,
      });
    }

    const luckyBtn = document.getElementById("lucky-btn");
    if (luckyBtn) luckyBtn.addEventListener("click", doLucky);
  }

  async function doSearch() {
    const query = document.getElementById("search-query").value.trim();
    if (query.length < 3) {
      return;
    }
    const type = document.getElementById("search-type").value;

    const btn = document.getElementById("search-btn");
    btn.disabled = true;
    btn.classList.add("searching");

    document.getElementById("search-results-container").classList.add("hidden");
    document.getElementById("search-empty").classList.add("hidden");

    try {
      const res = await api.searchApi.search(query, type, _QOBUZ_SEARCH_MAX);
      const data = await res.json();

      if (!data.ok) {
        return;
      }

      _searchResults = data.results || [];
      renderResults(_searchResults, query);
    } catch (_) {
      /* ignore */
    } finally {
      btn.disabled = false;
      btn.classList.remove("searching");
    }
  }

  function _searchResultDisplayLines(r) {
    let title = (r.display_title || "").trim();
    let subtitle = (r.display_subtitle || "").trim();
    const typ = r.type || "";
    if (title && subtitle) return { title, subtitle };
    if (title && !subtitle && (typ === "artist" || typ === "playlist")) {
      return { title, subtitle: "" };
    }
    const raw = (r.text || "")
      .replace(/ \[\w+\]$/, "")
      .replace(/ - (\d+:)?\d+:\d+$/, "");
    if (typ === "artist" || typ === "playlist") {
      return { title: title || raw, subtitle: "" };
    }
    const sep = " - ";
    const ix = raw.indexOf(sep);
    if (ix === -1) return { title: title || raw, subtitle };
    return {
      title: raw.slice(ix + sep.length).trim() || title,
      subtitle: raw.slice(0, ix).trim() || subtitle,
    };
  }

  function _searchResultYearLabel(r) {
    const y = (r.release_year || "").trim();
    if (y) return y;
    const rd = r.release_date;
    if (rd && typeof rd === "string" && /^\d{4}/.test(rd)) {
      return rd.slice(0, 4);
    }
    return "";
  }

  function _buildSearchResultRow(r, i) {
    const tipHires =
      "Hi-Res lossless on Qobuz, above CD quality; up to 24-bit / 192 kHz.";
    const tipLossless =
      "CD-quality lossless on Qobuz, 16-bit / 44.1 kHz FLAC.";
    const tipMp3 = "Lossy stream (e.g. ~320 kbps), not lossless.";
    const tipExplicit = "Explicit release on Qobuz.";

    const row = document.createElement("div");
    row.className = "result-item";
    row.dataset.index = String(i);
    if (r.url) row.dataset.queueUrl = r.url;
    const item = document.createElement("div");
    item.className = "result-card";

    const img = document.createElement("img");
    img.className = "result-card-art";
    const fallback =
      r.type === "artist"
        ? "/gui/artist-placeholder.png"
        : "/gui/placeholder.png";

    img.src = r.cover || fallback;
    img.onerror = () => {
      if (!img.src.endsWith(fallback)) {
        img.src = fallback;
      }
    };

    const info = document.createElement("div");
    info.className = "result-card-info";

    const { title: lineTitle, subtitle: lineArtist } = _searchResultDisplayLines(r);

    const titleEl = document.createElement("div");
    titleEl.className = "result-card-title";
    titleEl.textContent = lineTitle;

    info.appendChild(titleEl);

    if (lineArtist) {
      const artistRow = document.createElement("div");
      artistRow.className = "result-card-artist-row";
      const artistSpan = document.createElement("span");
      artistSpan.className = "result-card-artist";
      artistSpan.textContent = lineArtist;
      artistRow.appendChild(artistSpan);
      info.appendChild(artistRow);
    }

    let badgeContent = r.badge;
    let badgeClass = "result-badge";

    if (!badgeContent) {
      if (r.quality === "HI-RES") {
        badgeClass += " badge-hires";
        badgeContent = "HI-RES";
      } else if (r.quality === "LOSSLESS") {
        badgeClass += " badge-lossless";
        badgeContent = "LOSSLESS";
      } else if (r.type !== "artist" && r.type !== "playlist") {
        badgeClass += " badge-mp3";
        badgeContent = "MP3";
      }
    }

    const metaRow = document.createElement("div");
    metaRow.className = "result-card-meta-row result-card-bottom-row";

    if (badgeContent) {
      const badge = document.createElement("span");
      badge.className = badgeClass;
      badge.removeAttribute("title");
      if (r.badge) {
        badge.className += " badge-neutral";
        badge.textContent = badgeContent;
      } else if (r.quality === "HI-RES") {
        badge.setAttribute("data-tip", tipHires);
        const icon = document.createElement("img");
        icon.src = "/gui/hi-res.jpg";
        icon.className = "quality-icon";
        icon.alt = "";
        badge.appendChild(icon);
      } else if (r.quality === "LOSSLESS") {
        badge.setAttribute("data-tip", tipLossless);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", "0 0 32 32");
        svg.setAttribute("class", "quality-icon");
        svg.innerHTML = `<path d="M16 22.7368C17.8785 22.7368 19.471 22.0837 20.7773 20.7773C22.0837 19.471 22.7368 17.8785 22.7368 16C22.7368 14.1215 22.0837 12.529 20.7773 11.2227C19.471 9.91635 17.8785 9.26318 16 9.26318C14.1215 9.26318 12.529 9.91635 11.2227 11.2227C9.91635 12.529 9.26318 14.1215 9.26318 16C9.26318 17.8785 9.91635 19.471 11.2227 20.7773C12.529 22.0837 14.1215 22.7368 16 22.7368ZM16 17.6842C15.5228 17.6842 15.1228 17.5228 14.8 17.2C14.4772 16.8772 14.3158 16.4772 14.3158 16C14.3158 15.5228 14.4772 15.1228 14.8 14.8C15.1228 14.4772 15.5228 14.3158 16 14.3158C16.4772 14.3158 16.8772 14.4772 17.2 14.8C17.5228 15.1228 17.6842 15.5228 17.6842 16C17.6842 16.4772 17.5228 16.8772 17.2 17.2C16.8772 17.5228 16.4772 17.6842 16 17.6842ZM16.0028 32C13.7899 32 11.7098 31.5801 9.76264 30.7402C7.81543 29.9003 6.12164 28.7606 4.68128 27.3208C3.24088 25.8811 2.10057 24.188 1.26034 22.2417C0.420114 20.2954 0 18.2158 0 16.0028C0 13.7899 0.419931 11.7098 1.25979 9.76264C2.09965 7.81543 3.23945 6.12165 4.67917 4.68128C6.11892 3.24088 7.81196 2.10057 9.7583 1.26034C11.7046 0.420115 13.7842 0 15.9972 0C18.2101 0 20.2902 0.419933 22.2374 1.25979C24.1846 2.09966 25.8784 3.23945 27.3187 4.67917C28.7591 6.11892 29.8994 7.81197 30.7397 9.7583C31.5799 11.7046 32 13.7842 32 15.9972C32 18.2101 31.5801 20.2902 30.7402 22.2374C29.9003 24.1846 28.7606 25.8784 27.3208 27.3187C25.8811 28.7591 24.188 29.8994 22.2417 30.7397C20.2954 31.5799 18.2158 32 16.0028 32ZM16 29.4737C19.7614 29.4737 22.9474 28.1685 25.5579 25.5579C28.1685 22.9474 29.4737 19.7614 29.4737 16C29.4737 12.2386 28.1685 9.05261 25.5579 6.44208C22.9474 3.83155 19.7614 2.52628 16 2.52628C12.2386 2.52628 9.05261 3.83155 6.44208 6.44208C3.83155 9.05261 2.52628 12.2386 2.52628 16C2.52628 19.7614 3.83155 22.9474 6.44208 25.5579C9.05261 28.1685 12.2386 29.4737 16 29.4737Z" fill="white"></path>`;
        badge.appendChild(svg);
      } else {
        badge.setAttribute("data-tip", tipMp3);
        badge.textContent = badgeContent;
      }
      metaRow.appendChild(badge);
    }

    if (r.explicit) {
      const explicitBadge = document.createElement("span");
      explicitBadge.className = "result-badge badge-explicit explicit-tag-badge";
      explicitBadge.setAttribute("data-tip", tipExplicit);
      explicitBadge.removeAttribute("title");
      const explicitSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      explicitSvg.setAttribute("viewBox", "0 0 24 24");
      explicitSvg.setAttribute("class", "quality-icon");
      explicitSvg.innerHTML = `<path fill="currentColor" d="M10.603 15.626v-2.798h3.632a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.241h-3.632V8.352h3.632a.8.8 0 0 0 .598-.24q.24-.242.24-.599a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.24h-4.47a.8.8 0 0 0-.598.24.81.81 0 0 0-.24.598v8.952q0 .357.24.598.241.24.598.241h4.47a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.81.81 0 0 0-.598-.241zM4.52 21.5c-.575-.052-.98-.284-1.383-.651-.39-.392-.55-.844-.637-1.372V4.493c.135-.607.27-.961.661-1.353.392-.391.762-.548 1.343-.64H19.47c.541.066.952.254 1.362.62.413.37.546.796.668 1.38v14.977c-.074.467-.237.976-.629 1.367-.39.392-.82.595-1.391.656z"></path>`;
      explicitBadge.appendChild(explicitSvg);
      metaRow.appendChild(explicitBadge);
    }

    const metaLine = [];
    if (r.tracks) {
      metaLine.push(`${r.tracks} track${r.tracks !== 1 ? "s" : ""}`);
    }
    const yearLbl = _searchResultYearLabel(r);
    if (yearLbl) {
      metaLine.push(yearLbl);
    }

    if (metaLine.length > 0) {
      const metaText = document.createElement("span");
      metaText.className = "result-meta-text";
      metaText.textContent = metaLine.join(" • ");
      metaRow.appendChild(metaText);
    }

    info.appendChild(metaRow);

    item.appendChild(img);
    item.appendChild(info);

    const addBtn = document.createElement("button");
    addBtn.className = "result-add-btn";
    addBtn.removeAttribute("title");
    const alreadyQueued = queueHas(r.url);
    row.classList.toggle("result-item--queued", alreadyQueued);
    setSearchResultAddBtnAppearance(addBtn, alreadyQueued);

    addBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!r.url) return;
      if (queueHas(r.url)) {
        queueRemove(r.url);
        return;
      }
      queueAdd(r.url);
    });
    addBtn.addEventListener("mouseover", () => {
      if (addBtn.classList.contains("result-add-btn--queued")) {
        addBtn.setAttribute("data-tip", TIP_SEARCH_QUEUED_REMOVE);
      }
    });
    addBtn.addEventListener("mouseleave", () => {
      if (addBtn.classList.contains("result-add-btn--queued")) {
        addBtn.setAttribute("data-tip", TIP_SEARCH_QUEUED_IDLE);
      }
    });

    item.appendChild(addBtn);

    row.appendChild(item);
    return row;
  }

  function _updateSearchResultsHeader(visible, total, query) {
    const countEl = document.getElementById("results-count");
    if (!countEl || !total) return;
    if (visible < total) {
      countEl.textContent = `Showing ${visible} of ${total} results for "${query}"`;
    } else {
      countEl.textContent = `${total} result${total !== 1 ? "s" : ""} for "${query}"`;
    }
  }

  function _appendNextSearchPage(isInitial) {
    const list = document.getElementById("search-results");
    if (!list || !_searchResults.length) return;
    const total = _searchResults.length;
    const step = isInitial ? _QOBUZ_SEARCH_PAGE_INITIAL : _QOBUZ_SEARCH_PAGE_STEP;
    const next = Math.min(_searchVisibleCount + step, total);
    for (let i = _searchVisibleCount; i < next; i++) {
      list.appendChild(_buildSearchResultRow(_searchResults[i], i));
    }
    _searchVisibleCount = next;
    _updateSearchResultsHeader(_searchVisibleCount, total, _searchLastQuery);
  }

  function _onSidebarSearchScroll() {
    if (_sidebarSearchScrollRaf != null) {
      cancelAnimationFrame(_sidebarSearchScrollRaf);
    }
    _sidebarSearchScrollRaf = requestAnimationFrame(() => {
      _sidebarSearchScrollRaf = null;
      const scrollEl = document.querySelector(".sidebar-results-scroll");
      if (!scrollEl || !_searchResults.length) return;
      if (_searchVisibleCount >= _searchResults.length) return;
      const { scrollTop, scrollHeight, clientHeight } = scrollEl;
      if (scrollHeight - scrollTop - clientHeight > 100) return;
      _appendNextSearchPage(false);
    });
  }

  function renderResults(results, query) {
    const container = document.getElementById("search-results-container");
    const empty = document.getElementById("search-empty");
    const list = document.getElementById("search-results");
    list.innerHTML = "";
    _searchLastQuery = query;
    _searchVisibleCount = 0;

    if (!results.length) {
      container.classList.add("hidden");
      empty.classList.remove("hidden");
      return;
    }

    empty.classList.add("hidden");
    container.classList.remove("hidden");
    _appendNextSearchPage(true);
  }


  async function doLucky() {
    const query = document.getElementById("search-query").value.trim();
    if (query.length < 3) {
      return;
    }
    const type = document.getElementById("search-type").value;
    const number =
      parseInt(document.getElementById("lucky-number").value, 10) || 1;

    const btn = document.getElementById("lucky-btn");
    btn.disabled = true;
    btn.textContent = "Processing…";

    try {
      // For lucky mode, we fetch results and queue the top N
      const res = await api.searchApi.search(query, type, number);
      const data = await res.json();
      if (data.ok) {
        const results = data.results || [];
        const toAdd = results.slice(0, number);
        if (toAdd.length !== 0) {
          toAdd.forEach((r) => {
            if (r.url) queueAdd(r.url);
          });
        }
      }
    } catch (_) {
      /* ignore */
    } finally {
      btn.disabled = false;
      btn.textContent = "Lucky to Queue";
    }
  }


  features.search = features.search || {};
  features.search.init = initSearch;
  features.search.syncQueuedHighlights = syncQueuedHighlights;
})();
