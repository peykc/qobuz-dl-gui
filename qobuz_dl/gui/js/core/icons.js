(function () {
  "use strict";
  const icons = (window.QobuzGui.core.icons =
    window.QobuzGui.core.icons || {});

  icons.trackDlIconSvg = `<svg class="track-dl-btn-ico" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12"/><polyline points="7 12 12 17 17 12"/><path d="M5 21h14"/></svg>`;
  icons.trackSearchIconSvg = `<svg class="track-dl-btn-ico" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>`;
  icons.trackMissingNoteIconSvg = `<svg class="track-dl-btn-ico" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.4 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7.4"/><path d="M2 6h4"/><path d="M2 10h4"/><path d="M2 14h4"/><path d="M2 18h4"/><path d="M21.378 5.626a1 1 0 1 0-3.004-3.004l-5.01 5.012a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506z"/></svg>`;
  /** Global-tooltip text for queue-row *.missing.txt control. */
  icons.missingPlaceholderBtnTip =
    'Writes a detailed placeholder txt file using your track naming pattern (*.missing.txt). Search "missing" in your library to find placeholders.';
  icons.trackFolderIconSvg = `<svg class="track-dl-btn-ico" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></svg>`;
  /** Shown after explicit/clean in lyric search when this LRCLIB id matches the saved sidecar. */
  icons.lyricSearchAttachedSvg = `<svg class="lyric-search-attached-ico lucide-folder-check" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><path d="m9 13 2 2 4-4"/></svg>`;
  icons.trackDlFailSvg = `<svg class="track-dl-btn-ico" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>`;
  /** Qobuz / lyric explicit badge | same E icon as queue cards and search. */
  icons.explicitBadgeSvg = `<svg viewBox="0 0 24 24" class="explicit-badge-icon" aria-hidden="true"><path fill="currentColor" d="M10.603 15.626v-2.798h3.632a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.241h-3.632V8.352h3.632a.8.8 0 0 0 .598-.24q.24-.242.24-.599a.81.81 0 0 0-.24-.598.8.8 0 0 0-.598-.24h-4.47a.8.8 0 0 0-.598.24.81.81 0 0 0-.24.598v8.952q0 .357.24.598.241.24.598.241h4.47a.8.8 0 0 0 .598-.241q.24-.241.24-.598a.81.81 0 0 0-.24-.598.81.81 0 0 0-.598-.241zM4.52 21.5c-.575-.052-.98-.284-1.383-.651-.39-.392-.55-.844-.637-1.372V4.493c.135-.607.27-.961.661-1.353.392-.391.762-.548 1.343-.64H19.47c.541.066.952.254 1.362.62.413.37.546.796.668 1.38v14.977c-.074.467-.237.976-.629 1.367-.39.392-.82.595-1.391.656z"></path></svg>`;
})();
