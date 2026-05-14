(function () {
  "use strict";
  const c = (window.QobuzGui.core.constants =
    window.QobuzGui.core.constants || {});

  /** Matches ``qobuz_dl.db.GUI_PENDING_TRACK_PREFIX``; pending DB rows have no local file. */
  c.GUI_PENDING_AUDIO_PREFIX = "__GUI_PENDING__:slot:";

  /** Virtualized download history when many rows (reduces DOM + layout cost). */
  c.TS_VIRT_THRESHOLD = 72;
  c.TS_VIRT_OVERSCAN = 6;
})();
