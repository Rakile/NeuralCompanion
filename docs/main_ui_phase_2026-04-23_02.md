# main.ui Phase Report - 2026-04-23 - 02

This phase continued Phase 3 of the `main.ui` migration by targeting the remaining chunking/profile surface.

## Objective

Do the next safe migration step without importing `dry_run` in the shell path:

1. Bind the visible chunking controls in `main.ui` as shell-local preview controls.
2. Make performance-profile refresh/load available in the shell path through direct JSON reads.
3. Add a durable host-service boundary for chunking/profile workflows that a future real `main.ui` runtime can call.

## Files Changed

- `qt_app.py`
- `core/addons/qt_host_services.py`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Added shell-local chunking bindings

The shell path now binds the visible chunking sliders in `main.ui` as preview-only controls:

- `chunk_target_chars_slider`
- `chunk_max_chars_slider`
- `musetalk_chunk_target_chars_slider`
- `musetalk_chunk_max_chars_slider`
- `musetalk_quickstart_1_target_chars_slider`
- `stream_chunk_target_chars_slider`
- `stream_chunk_max_chars_slider`
- `stream_first_chunk_min_chars_slider`

Behavior in this phase:

- shell-local slider ranges now match the legacy Python-built UI
- labels update with the current numeric value
- console/status lines update in shell preview
- no runtime config is written
- no engine/model/TTS/avatar work is started

Important current gap:

- `main.ui` still does not expose the legacy quickstart-1-max, quickstart-2, or flush-timer sliders, so those legacy chunking fields remain outside the visible Designer surface

### 2. Added shell-local performance-profile refresh/load

The shell path now binds these profile controls:

- `chunking_profile_combo`
- `performance_profile_combo`
- `btn_chunking_profile_refresh`
- `btn_profile_refresh`
- `btn_chunking_profile_load`
- `btn_profile_load`
- `btn_reset_chunking_defaults`

Shell profile refresh/load is backed by direct JSON reads from `performance_profiles/*.json`.

Why this matters:

- the shell path exits before `dry_run` is imported
- using file-backed JSON reads keeps the shell path safe and self-contained
- `Load Profile` now applies the shell-visible subset only

Shell-visible subset currently applied from a profile:

- `stream_mode`
- `musetalk_vram_mode`
- visible chunking slider values listed above

Still deferred in shell preview:

- `btn_chunking_profile_save`
- `btn_profile_save_latest`
- `btn_chunking_profile_delete`
- `btn_profile_delete`

Those buttons are intentionally bound as shell-local deferred actions that only explain the limitation in the console. They do not mutate files.

### 3. Added a new host-service boundary

Added `qt.performance_profiles` in both service maps:

- shell-safe service in `qt_app.py`
- normal-app service in `core/addons/qt_host_services.py`

Current service coverage:

- snapshot current profile/chunking state
- refresh profile lists
- load a selected profile
- reset chunking defaults
- expose save/delete entry points without forcing callers onto legacy widget access

This service is additive in this phase. Existing runtime logic still works as before.

## Validation Run

Executed:

```powershell
python -m py_compile qt_app.py core\addons\qt_host_services.py
python qt_app.py --validate-ui main.ui
python qt_app.py --ui-shell main.ui --shell-smoke
```

Observed result:

- `Heavy engine imported: no`
- `Result: READY for the checked shell binding surface.`

Observed environment note in this pass:

- `nc.hotkeys` failed to mount live in shell smoke because `keyboard` is unavailable
- because of that, shell smoke currently reports `Addon mount placeholders: left_tabs`

That addon-mount issue is separate from the chunking/profile migration done in this phase.

## What Is Still Shell-Local

- chunking slider changes
- performance-profile refresh/load in `--ui-shell`
- chunking reset in `--ui-shell`
- all profile save/delete actions in `--ui-shell`

## What Is Still Legacy-Only Or Missing

- dry-run start/stop/apply workflow
- persona/body/VaM runtime control groups
- push-to-talk and other runtime-adjacent input actions
- a real runtime-backed `main.ui` mode

## Next Phase

Next recommended target:

```text
Bind the dry-run controls as shell-safe preview/deferred actions and keep the runtime session machinery out of the shell path.
```
