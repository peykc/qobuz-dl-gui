# Qobuz-DL-GUI Frontend Contract

This document defines **public contracts** for the vanilla JS GUI refactor.  
Do not break these during extraction unless a failing test or broken route forces it.

## Script loading

- Use **ordered** `<script>` tags only. No ES modules, Vite, React, TypeScript, or bundlers for this refactor phase.
- Current order in [`qobuz_dl/gui/index.html`](../qobuz_dl/gui/index.html):
  1. `/gui/js/api/client.js` — initializes `window.QobuzGui.api`
  2. `/gui/app.js` — main IIFE (compatibility shell until bootstrap shrink)
- New modules must load **before** `app.js` if `app.js` depends on them at parse time, or be initialized from `app.js` after load if they only attach to `window.QobuzGui`.

## Namespace rule

- Prefer `window.QobuzGui = window.QobuzGui || {}` and attach subtrees, e.g. `QobuzGui.core.trackIdentity`, `QobuzGui.ui.globalTooltip`, `QobuzGui.features.queue`.
- **Implemented:** `QobuzGui.features.updateBanner` (see `js/features/settings/updateBanner.js`), `QobuzGui.features.queue` and `QobuzGui.features.history` (registered from `app.js` after download UI init; queue mirrors the compatibility globals).
- Do not introduce unrelated globals except the compatibility adapters listed below.

## Compatibility globals (must keep working)

Until all callers are migrated, these must remain functional:

| Global | Role |
|--------|------|
| `window._handleDlStatus(ev)` | SSE status event handler |
| `window._qUrlForPurchaseSlot(slotId)` | Purchase-only URL lookup for a slot |
| `window._updateQueueBadge()` | Queue badge refresh |
| `window._handleDrop(e)` | Drag/drop (card mode) |
| `window._handleDropText(e)` | Drag/drop (text mode) |
| `window.isDownloading` | Download-in-progress flag |

`app.js` registers `EventSource` and calls `window._handleDlStatus` when present.

## DOM id contract (do not rename)

These ids are relied on by `app.js` and/or HTML. **Do not rename** during refactor:

- `#dl-track-status`, `#dl-track-status-container`
- `#dl-history-tab-all`, `#dl-history-tab-errors`, `#dl-history-errors-count`
- `#dl-queue`, `#dl-queue-empty`, `#dl-urls`, `#dl-url-input`, `#dl-url-add`
- `#dl-btn`, `#dl-btn-badge`, `#dl-progress-fill`, `#dl-progress-label`
- `#lyric-search-popover`, `#lyric-search-results`, `#lyric-search-preview-audio`
- `#attach-track-popover`
- `#search-results`, `#search-results-container`, `#search-query`, `#search-type`, `#search-btn`
- `#settings-popover`, `#settings-gear-btn`, `#issue-report-popover`
- `#global-tooltip`, `#text-field-context-menu`
- `#setup-overlay`, `#app`, `#update-banner` and related update banner ids
- Setup/auth: `#oauth-btn`, `#token-btn`, `#setup-btn`, panels, errors, etc. (see `index.html`)

## CSS and copy

- Do not rename CSS classes for styling hooks used by JS unless unavoidable and tested.
- Do not change visible user-facing copy as part of refactor-only work.

## API contract

- **Do not** change Flask endpoint paths or JSON response shapes consumed by the GUI.
- API wrappers in `QobuzGui.api.*` must call the same paths as current `fetch()` usage.

## Dependency direction

- `api` — no DOM, no app business state
- `core` — pure helpers / constants; minimal DOM
- `ui` — generic DOM utilities; no Qobuz-specific queue/history rules
- `features` — may use `api`, `core`, `ui`
- `main` (future) — wires feature `init()` calls

Lower layers must not call upward into unfinished feature modules.

## Empty modules

- **Do not** add placeholder files with no moved code. Add a file only when code moves into it or an adapter imports it.
