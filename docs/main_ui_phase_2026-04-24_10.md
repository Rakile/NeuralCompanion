# main.ui Phase Report - 2026-04-24 - 10

This phase continued Phase 5 by finishing the remaining top-level addon migration, redirecting the sensory runtime surface into the real Designer window, and verifying real runtime `INIT` / `TERMINATE` through an offscreen runtime-backed bridge run.

## Objective

Complete the next Phase 5 runtime-ownership slice:

1. verify real runtime start/stop against `--ui-real main.ui`
2. move the remaining top-level addon tabs out of the hidden backend
3. move the sensory runtime surface out of the hidden backend instead of leaving the Designer `Sources` placeholder in place

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_10.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Fixed top-level addon adoption in `--ui-real`

The runtime bridge now sources top-level addon tabs from the hidden backend's real `self.tabs` widget and adopts them into the Designer `left_tabs`.

Adopted in this pass:

- `left_tabs`: `Hotkeys`, `Chat Player`

The bridge also now repoints `backend.tabs` and the left-tab change callback to the real Designer tab widget, so follow-up runtime behavior no longer depends on the hidden backend tab strip for this slice.

### 2. Redirected the sensory runtime surface into the real Designer widgets

The runtime bridge now redirects these backend-owned sensory containers to the real `main.ui` widgets:

- `sensory_feedback_tabs`
- `sensory_feedback_sources_widget`
- `sensory_feedback_sources_layout`

After redirecting them, the bridge rebuilds the sensory runtime UI directly in the Designer window by calling the backend's normal `refresh_sensory_feedback_source_options()` path.

Effect:

- the static Designer `Sources` placeholder is no longer the runtime owner
- runtime source checkboxes now live in the real Designer surface
- runtime source tabs are now built in the real Designer `sensory_feedback_tabs`
- source-specific vision-source addon tabs follow the normal backend runtime build path, but now render in `main.ui`

### 3. Added clearer `--ui-real --runtime-smoke` reporting

The runtime smoke output now reports:

- whether the sensory runtime surface redirect succeeded
- the current sensory runtime tab titles visible in the real Designer tab group

### 4. Verified real runtime `INIT` / `TERMINATE` offscreen

An offscreen `MainUiRealRuntimeBridge('main.ui')` run was used to exercise the real runtime lifecycle path:

- start engine through `bridge._start_engine_from_ui_real()`
- wait for the backend thread to become alive
- stop engine through `bridge._engine_lifecycle_service.stop_engine()`
- wait for the backend thread to stop

Observed result in this pass:

- `engine_started = True`
- `engine_stopped = True`

The same verification pass also toggled one sensory source checkbox and confirmed that the frontend sensory tabs changed from:

- before: `Core`
- enabled: `Core`, `Screen`
- disabled again: `Core`

That proves the runtime sensory source tabs are now being built on the real Designer tab widget rather than staying hidden in the legacy backend window.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Additional verification executed in this pass:

- offscreen runtime-backed `INIT` / `TERMINATE` verification through `MainUiRealRuntimeBridge`
- offscreen sensory source toggle verification against the frontend `sensory_feedback_tabs`

Observed result:

- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- shell smoke still reports `Addon mount placeholders: none`
- `--ui-real main.ui --runtime-smoke` now reports:
  - provider runtime redirected: `yes`
  - sensory runtime redirected: `yes`
  - adopted runtime tabs:
    - `left_tabs`: `Hotkeys`, `Chat Player`
    - `host_settings_tabs`: `Visuals`, `Story Visuals`
    - `right_tabs`: `Audio Story Mode`
    - `musetalk_tabs`: `Preprocess`, `Loop Authoring`
    - `tts_runtime_addon_tabs`: `Chatterbox`, `Gemini TTS`, `PocketTTS`
  - sensory runtime tabs: `Core`

## What Phase 5 Solved Here

- automated `INIT` / `TERMINATE` verification now exists for the real runtime-backed Designer bridge
- the remaining top-level addon tabs are no longer hidden-backend-only
- the sensory runtime source surface is no longer hidden-backend-only
- sensory provider tabs now build directly in the real Designer tab widget

## What Is Still Not Fully Moved Yet

- chat edit-mode mutation is still legacy-owned
- duplicate/static Designer Audio Story controls are still deferred even though the real addon tab is visible
- duplicate/static Designer Dry Run controls are still deferred
- provider/model workflow is still partly bridge-driven rather than Designer-owned
- the hidden backend still exists as the runtime owner for cleanup and for non-migrated workflows

## Next Phase

Next recommended target:

```text
Begin Phase 6 by reducing the remaining deferred visible workflows in --ui-real, starting with chat edit-mode and the duplicate static Audio Story / Dry Run Designer surfaces.
```
