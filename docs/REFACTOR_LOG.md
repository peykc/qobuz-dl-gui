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
