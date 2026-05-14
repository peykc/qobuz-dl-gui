# Qobuz-DL-GUI Frontend Contract

This document defines **public contracts** for the vanilla JS GUI refactor.  
Do not break these during extraction unless a failing test or broken route forces it.

## Script loading

- Use **ordered** `<script>` tags only. No ES modules, Vite, React, TypeScript, or bundlers for this refactor phase.

- **Script order is a real contract.** Later files may assume earlier ones have populated `window.QobuzGui` (especially `namespace.js` after `client.js`). When adding files, preserve load-before dependencies; do not reorder casually without checking each IIFE.

- Current order in [`qobuz_dl/gui/index.html`](../qobuz_dl/gui/index.html) matches this list exactly (excluding `?v=` cache query strings):

  1. `/gui/js/api/client.js` — initializes `window.QobuzGui.api`
  2. `/gui/js/api/extensions.js` — extra API helpers on `QobuzGui.api`
  3. `/gui/js/features/settings/updateBanner.js` — `QobuzGui.features.updateBanner`
  4. `/gui/js/core/namespace.js` — ensures `window.QobuzGui` scaffold
  5. `/gui/js/core/constants.js`
  6. `/gui/js/core/trackIdentity.js`
  7. `/gui/js/core/format.js`
  8. `/gui/js/core/dom.js`
  9. `/gui/js/core/icons.js`
  10. `/gui/js/features/formatBuilder/formatTooltips.js`
  11. `/gui/js/ui/globalTooltip.js`
  12. `/gui/js/ui/textFieldContextMenu.js`
  13. `/gui/js/ui/donationPopover.js`
  14. `/gui/js/ui/collapses.js`
  15. `/gui/js/ui/resetButtons.js`
  16. `/gui/js/features/lyrics/lyricOutputSettings.js` — `QobuzGui.features.lyrics.lyricOutputSettings` (several downstream scripts assume this exists)
  17. `/gui/js/features/settings/settingsForm.js` — `QobuzGui.features.settings.settingsForm` (`loadIntoForm`, `mirrorConfigOntoForms`)
  18. `/gui/js/features/settings/downloadOptionsAutosave.js` — `QobuzGui.features.settings.downloadOptionsAutosave.bind()`
  19. `/gui/js/features/queue/queueController.js` — stable `QobuzGui.features.queue` (`addUrl`, `removeUrl`, `hasUrl`, `getQueuedUrlSet`, drag/badge helpers); **`install(impl)` fills real behaviour once** (`app.js` `initDownload()`)
  20. `/gui/js/features/search/searchController.js` — `QobuzGui.features.search` (`init`, `syncQueuedHighlights`); uses `features.queue` (**safe empty/no-op until `install`**)
  21. `/gui/js/ui/feedbackMessage.js` — `QobuzGui.ui.feedbackMessage`
  22. `/gui/js/features/feedback/issueReportSubsystem.js` — registers `QobuzGui.features.feedback.issueReport.init(checkStatus)`; settings gear popover + issue-report popover/log preview (uses `feedbackMessage`; does not replace it)
  23. `/gui/app.js` — main IIFE; calls `features.queue.install({…})`, registers `features.history`, calls remaining feature `init()` where delegated

- **Optional later cleanup (non-goal until someone does it deliberately):** a more uniform mental order might be API → core → API extensions → shared UI → features → app. Today's order mixes `features`/`ui`/core somewhat for historical incremental extraction; reordering requires re-validating every cross-file assumption.

### Search vs queue lifecycle

`/gui/js/features/queue/queueController.js` runs **before** search so `QobuzGui.features.queue` is always a shaped object (`hasUrl` → false, `getQueuedUrlSet` → empty `Set`, etc.) until `app.js` calls **`features.queue.install(impl)`** at the end of `initDownload()`, binding closures over real queue state. Search `init()` still runs **after** `install`, so highlights match prior behaviour.

## Namespace rule

- Prefer `window.QobuzGui = window.QobuzGui || {}` and attach subtrees, e.g. `QobuzGui.core.trackIdentity`, `QobuzGui.ui.globalTooltip`, `QobuzGui.features.queue`.
- **Implemented (from extra scripts + `app.js`):**
  - `QobuzGui.features.updateBanner` (`js/features/settings/updateBanner.js`)
  - `QobuzGui.features.settings.settingsForm` (`js/features/settings/settingsForm.js`)
  - `QobuzGui.features.settings.downloadOptionsAutosave` (`js/features/settings/downloadOptionsAutosave.js`)
  - `QobuzGui.features.search` (`js/features/search/searchController.js`)
  - `QobuzGui.features.queue` (`js/features/queue/queueController.js`): facade + **`install(impl)` once** from `app.js`; `impl` mirrors globals `window._handleDrop*` / `_updateQueueBadge`
  - `QobuzGui.features.history` (**registered from `app.js`** after download/history wiring)
  - **`QobuzGui.ui.feedbackMessage`** (`js/ui/feedbackMessage.js`): `show`, `showButton` for `.feedback-msg` and the settings update-check button.
  - **`QobuzGui.features.feedback.issueReport`** (`js/features/feedback/issueReportSubsystem.js`): `init(checkStatus)` — settings gear popover, issue-report / sent-history UX, worker submit endpoint, logs modal (**invoked from `app.js`** `initSettings()` so `checkStatus` stays in-scope).
  - **`QobuzGui.features.lyrics.lyricOutputSettings`** (`js/features/lyrics/lyricOutputSettings.js`): download ↔ settings lyric toggles sync and `/api/config` persist.
- Do not introduce unrelated globals except the compatibility adapters listed below.

## Extraction sequencing (human process)

The issue-report subsystem (gear + Send Feedback popovers) moved to `issueReportSubsystem.js` so `checkStatus`, session logs, and `api.feedbackApi` stay reachable via `features.feedback.issueReport.init(...)`. The queue façade (`queueController.js` + **`install(impl)`**) loads before search. Prefer **deliberate** sequencing for history/SSE and other splits until intentionally scheduled.

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
