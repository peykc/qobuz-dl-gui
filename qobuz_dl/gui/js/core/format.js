(function () {
  "use strict";
  const fmt = (window.QobuzGui.core.format = window.QobuzGui.core.format || {});

  function formatAttachDur(sec) {
    const s = Number(sec) || 0;
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${m}:${String(r).padStart(2, "0")}`;
  }

  /** Match ``normalize_sampling_rate_hz`` in Python (Hz/kHz/MHz-ish API quirks). */
  function normalizeSamplingRateHz(raw) {
    const f =
      typeof raw === "number" ? raw : parseFloat(String(raw != null ? raw : ""));
    if (!Number.isFinite(f) || f <= 0) return null;
    if (f < 1) return f * 1_000_000;
    if (f < 1000) return f * 1000;
    return f;
  }

  /** LRCLIB duration delta vs reference (±2s hidden; same threshold as LRCLIB matching). */
  function formatLyricDeltaSec(sec) {
    if (sec == null || !Number.isFinite(Number(sec))) return "";
    const n = Math.round(Number(sec));
    const sign = n > 0 ? "+" : "\u2212";
    const a = Math.abs(n);
    const m = Math.floor(a / 60);
    const s = a % 60;
    return `${sign}${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }

  fmt.formatAttachDur = formatAttachDur;
  fmt.normalizeSamplingRateHz = normalizeSamplingRateHz;
  fmt.formatLyricDeltaSec = formatLyricDeltaSec;
})();
