# Qobuz-DL-GUI Refactor Log

## Checkpoint 1 - Config Paths And Defaults Extraction

Date: 2026-05-13
Commit: pending

### What changed

- Confirmed the branch already contains shared config path/default modules and the first backend route/service extractions.
- Added endpoint shape tests for the current Flask routes used by the GUI.
- Added a sanitized smoke-test template under `docs/`.
- Runtime behavior should be unchanged.

### Validation

- `python -m unittest discover -s tests` passed before endpoint-shape tests were added.
- `python -m unittest discover -s tests` passed after endpoint-shape tests were added.
- `python -m py_compile tests/test_gui_route_shapes.py` passed.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- Current config file format was preserved.
- Password/token storage behavior was not changed.
- Endpoint paths were not renamed.
- No UI behavior or copy was changed.
- `python -m unittest discover` did not discover the existing tests; use `python -m unittest discover -s tests`.
- Earlier accidental overwrites of tracked route/service files were restored to the branch versions before continuing.

## Checkpoint 2 - Browse Folder Utility Route Move

Date: 2026-05-13
Commit: pending

### What changed

- Moved `/api/browse_folder` from `qobuz_dl/gui_app.py` into `qobuz_dl/routes/utility_routes.py`.
- Preserved the existing endpoint path, method, response shape, and tkinter folder picker behavior.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/gui_app.py qobuz_dl/routes/utility_routes.py tests/test_gui_route_shapes.py` passed.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- No endpoint response shapes were changed.
- No UI behavior or copy was changed.
- No download semantics were changed.

## Checkpoint 3 - Search And Resolve Route Move

Date: 2026-05-13
Commit: pending

### What changed

- Added `qobuz_dl/routes/search_routes.py`.
- Moved `/api/resolve`, `/api/search`, and `/api/search_tracks_attach` out of `qobuz_dl/gui_app.py`.
- Kept replacement/download execution routes in `qobuz_dl/gui_app.py`.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/gui_app.py qobuz_dl/routes/search_routes.py` passed.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- Endpoint paths and response shapes were preserved.
- No UI behavior or copy was changed.
- No download semantics were changed.

## Checkpoint 4 - Replacement Route Move

Date: 2026-05-13
Commit: pending

### What changed

- Added `qobuz_dl/routes/replacement_routes.py`.
- Moved `/api/download_attach_track`, `/api/write_missing_track_placeholder`, and `/api/delete_track_resolution_file` out of `qobuz_dl/gui_app.py`.
- Kept the existing downloader methods and replacement workflow behavior unchanged.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/gui_app.py qobuz_dl/routes/replacement_routes.py` passed.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- Endpoint paths and response shapes were preserved.
- No UI behavior or copy was changed.
- No `qobuz_dl/downloader.py` internals were changed.

## Checkpoint 5 - Discography Check Route Move

Date: 2026-05-13
Commit: pending

### What changed

- Moved `/api/check_discography` from `qobuz_dl/gui_app.py` into `qobuz_dl/routes/search_routes.py`.
- Kept the existing artist discography count response shape unchanged.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/gui_app.py qobuz_dl/routes/search_routes.py` passed.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- Endpoint paths and response shapes were preserved.
- No UI behavior or copy was changed.
- No download semantics were changed.

## Checkpoint 6 - Download Control Route Move

Date: 2026-05-13
Commit: pending

### What changed

- Added `qobuz_dl/routes/download_routes.py`.
- Moved `/api/download`, `/api/cancel`, `/api/pause`, and `/api/lucky` out of `qobuz_dl/gui_app.py`.
- Passed download state, events, config helpers, and URL context hooks into the route module explicitly.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/gui_app.py qobuz_dl/routes/download_routes.py` passed.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- Endpoint paths and response shapes were preserved.
- No UI behavior or copy was changed.
- No `qobuz_dl/downloader.py` internals were changed.

## Checkpoint 7 - Auth Route Move

Date: 2026-05-13
Commit: pending

### What changed

- Added `qobuz_dl/routes/auth_routes.py`.
- Moved `/api/setup`, `/api/connect`, `/api/oauth/start`, and `/api/token_login` out of `qobuz_dl/gui_app.py`.
- Kept `qobuz_dl/gui_app.py` as the global Flask app and desktop startup module.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/gui_app.py qobuz_dl/routes/auth_routes.py` passed.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- Endpoint paths and response shapes were preserved.
- No UI behavior or copy was changed.
- Password/token storage behavior was not intentionally changed.

## Checkpoint 8 - Frontend API Client Adapter

Date: 2026-05-13
Commit: pending

### What changed

- Added `qobuz_dl/gui/js/api/client.js` as the first ordered vanilla JavaScript module.
- Loaded the API client before `qobuz_dl/gui/app.js` without introducing build tooling.
- Routed two `/api/status` reads through the shared API adapter while preserving fallback behavior.

### Validation

- `python -m unittest discover -s tests` passed.
- Cursor diagnostics reported no linter errors for the changed frontend files.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- No UI behavior or copy was changed.
- No frontend build tooling was introduced.
- The large `app.js` IIFE remains in place while adapter modules are introduced incrementally.

## Checkpoint 9 - History Service Boundary

Date: 2026-05-13
Commit: pending

### What changed

- Added conservative dataclasses in `qobuz_dl/domain/models.py`.
- Added `qobuz_dl/persistence/history_repo.py` as a thin repository wrapper over existing DB functions.
- Added `qobuz_dl/services/history_service.py` and routed history endpoints through it.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/domain/models.py qobuz_dl/persistence/history_repo.py qobuz_dl/services/history_service.py qobuz_dl/routes/history_routes.py` passed.
- Cursor diagnostics reported no linter errors for changed history/domain files.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- SQL behavior remains in `qobuz_dl/db.py` for this checkpoint.
- No endpoint response shapes were changed.
- No UI behavior or copy was changed.

## Checkpoint 10 - Lyrics Package Compatibility Split

Date: 2026-05-13
Commit: pending

### What changed

- Converted `qobuz_dl/lyrics.py` into the package `qobuz_dl/lyrics/__init__.py`.
- Added thin compatibility submodules for `lrclib_client`, `matcher`, `classifier`, `attach`, and `preview`.
- Preserved existing `from qobuz_dl import lyrics` and `qobuz_dl.lyrics.<function>` imports.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/lyrics/__init__.py qobuz_dl/lyrics/lrclib_client.py qobuz_dl/lyrics/matcher.py qobuz_dl/lyrics/classifier.py qobuz_dl/lyrics/attach.py qobuz_dl/lyrics/preview.py` passed.
- Cursor diagnostics reported no linter errors for `qobuz_dl/lyrics`.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- This checkpoint is primarily mechanical package movement plus compatibility adapters.
- No lyric matching or attachment behavior was intentionally changed.
- No endpoint response shapes or UI behavior were changed.

## Checkpoint 11 - Placeholder Helper Extraction

Date: 2026-05-13
Commit: pending

### What changed

- Added `qobuz_dl/download/placeholders.py`.
- Moved missing-placeholder formatting and Qobuz storefront URL helpers out of `qobuz_dl/downloader.py`.
- Imported the helpers back under the existing private names so downloader call sites remain unchanged.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/downloader.py qobuz_dl/download/placeholders.py` passed.
- Cursor diagnostics reported no linter errors for changed downloader/download files.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- No download semantics were changed.
- Placeholder file content and URL formatting should be unchanged.
- No endpoint response shapes or UI behavior were changed.

## Checkpoint 12 - Typed Download Event Models

Date: 2026-05-13
Commit: pending

### What changed

- Added `qobuz_dl/download/events.py` with typed event dataclasses for track start, track finish, lyrics resolution, and URL finish.
- Added tests documenting that release slot identity, local artifact identity, and URL outcome remain separate.
- Kept existing string marker parsing and frontend SSE behavior unchanged.

### Validation

- `python -m unittest discover -s tests` passed.
- `python -m py_compile qobuz_dl/download/events.py tests/test_download_events.py` passed.
- Cursor diagnostics reported no linter errors for changed event model files.
- `python -m flake8 <changed files>` could not run because `flake8` is not installed in the current Python environment.

### Notes

- No download semantics were changed.
- Existing `[TRACK_START]`, `[TRACK_RESULT]`, and `[TRACK_LYRICS]` markers remain in place.
- No endpoint response shapes or UI behavior were changed.
