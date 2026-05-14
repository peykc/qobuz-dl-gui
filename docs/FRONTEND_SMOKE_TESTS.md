# Qobuz-DL-GUI Frontend Smoke Tests

Manual checks after frontend checkpoints. Run the **normal desktop entrypoint** (`qobuz-dl-gui` / pywebview) at milestones (after leaf UI, after search/queue, after history, after download SSE work).

Use devtools console: confirm **no 404** on script URLs and no uncaught errors on load.

## 1. App launch

- App window opens.
- Either setup overlay or main `#app` appears as before.
- Status dot reflects connection state after `checkStatus` / connect.

## 2. Auth / setup

- OAuth: button starts flow, browser opens, return path still connects (if used).
- Token login: valid token connects.
- Email/password setup: still works if supported in your build.

## 3. Search

- Search disabled when query &lt; 3 chars.
- Results render; lazy load / pagination on scroll if applicable.
- Add-to-queue: item queues; queued row shows check / remove affordance.

## 4. Lucky queue

- Lucky panel toggles.
- Lucky search queues top N as configured.

## 5. Queue

- Add URL manually; paste multiple URLs.
- Drag/drop URL in card mode and in text mode (`ondrop` / `_handleDrop` / `_handleDropText`).
- Switch card mode ↔ text mode; state consistent.
- Restart app: queue restores from `/api/download-queue`.

## 6. Download start / pause

- Start download sends expected payload.
- Queue cards show pending/active as before.
- Pause shows Pausing… then returns to idle appropriately.

## 7. SSE track status

- `track_start` (or equivalent) creates/updates track status card.
- Progress UI updates during download.
- `track_result`: downloaded / failed / purchase-only states correct.
- `track_lyrics`: lyric chip updates.
- `url_done` / `url_error`: queue cards behave as before (remove success, keep errors).

## 8. History

- History hydrates from `/api/download-history`.
- All tab vs Errors tab; error count badge.
- Clear history confirmation.
- Large list: virtualization scrolls without losing active rows.

## 9. Lyrics

- Open lyric search from a history row.
- Search results; preview; local audio stream if used.
- Synced lyrics highlight / seek interaction.
- Attach updates chip and history without breaking order.

## 10. Replacement / missing placeholder

- Purchase-only row: store link and resolution UI.
- Replacement search popover; substitute download.
- `.missing.txt` placeholder path; switching resolution modes does not duplicate state.

## 11. Settings

- Settings popover opens/closes.
- Config loads into form from status/config.
- Download options autosave.
- Update check button and banner behavior.

## 12. Feedback

- Report popover opens.
- Logs preview modal loads session logs.
- Submit succeeds; history list updates; open count badge.
- Mark resolved / close flows for `fb:` ids if applicable.

## 13. UI utilities

- Global tooltip on hover targets.
- Format builder tooltips if present.
- Custom context menu on text inputs.
- Donation popover if present.

## Visual baselines (Phase 0)

Before large moves, capture screenshots or short screen recordings for:

- Search results + queued highlights
- Queue card mode and text mode
- History All / Errors tabs
- Lyric search + preview
- Replacement / missing-placeholder controls
- Feedback popover + history
- Settings + update banner

Store artifacts outside the repo or in a private folder if they contain account data.
