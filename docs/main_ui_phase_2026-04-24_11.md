# main.ui Phase Report - 2026-04-24 - 11

This phase started Phase 6 by reducing the remaining deferred visible workflows in `--ui-real`, beginning with chat edit mode, the visible Dry Run controls, and the adopted top-level Hotkeys runtime tab.

## Objective

Start moving deferred visible workflows out of the bridge's placeholder state:

1. make chat edit mode real in `--ui-real`
2. make the visible Dry Run controls real in `--ui-real`
3. fix the adopted `Hotkeys` runtime tab so it refreshes correctly on the real Designer surface
4. reassess the duplicate static Audio Story surface after the runtime addon tab adoption work

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_11.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Chat edit mode is now live in `--ui-real`

The runtime bridge now binds:

- `chat_edit_mode_button`
- `chat_apply_edit_button`
- `chat_cancel_edit_button`

to the hidden backend's real chat edit-mode methods.

The bridge now:

- enters backend chat edit mode from the Designer window
- copies the frontend edited text back into the backend before apply
- stops poll-based chat mirroring from overwriting the frontend while edit mode is active
- mirrors read-only state and button visibility from backend edit mode back into the Designer window

Effect:

- chat edit mode is no longer a deferred tooltip-only surface in `--ui-real`

### 2. Dry Run controls are now live in `--ui-real`

The runtime bridge now binds:

- `btn_dry_run_start`
- `btn_dry_run_stop`
- `btn_dry_run_apply`

to the backend's real Dry Run methods.

The bridge also now mirrors:

- `dry_run_status_label`
- `dry_run_summary`
- Dry Run button enabled state

from the backend into the Designer window.

Effect:

- the visible Dry Run controls are no longer deferred in `--ui-real`
- runtime button state and summary text now stay in sync with the backend

### 3. Hotkeys runtime tab refresh is now explicit on the real left tab strip

The runtime bridge now handles real `left_tabs` changes itself before delegating to the backend.

That handler now:

- forwards the tab-focus event into the backend
- syncs left-tab height on the real Designer widget
- explicitly refreshes the `nc.hotkeys` controller when the `Hotkeys` tab becomes active

This addresses the observed failure mode where the top-level runtime tab existed structurally but did not reliably present as populated on the real surface.

Offscreen verification in this pass confirmed that the adopted real `Hotkeys` tab contains `18` entries.

### 4. Reassessed the duplicate static Audio Story surface

The original Phase 6 target named the duplicate static Audio Story controls as a remaining visible deferred surface.

After this pass, that statement is no longer accurate for `--ui-real`:

- the real `Audio Story Mode` addon tab is adopted into the Designer `right_tabs`
- the old static Audio Story tab page is replaced at runtime by the adopted addon widget
- the duplicate static Audio Story controls therefore do not remain as live visible controls in the real Designer runtime path

So this pass did not add a second competing Audio Story runtime binding path. Instead it confirmed that the real adopted addon tab is the correct runtime surface and removed that duplicate-control slice from the immediate Phase 6 target list.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py addons\hotkeys\controller.py addons\audio_story_mode\controller.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Additional verification executed in this pass:

- offscreen `Hotkeys` tab inspection in `MainUiRealRuntimeBridge`
- offscreen chat edit-mode toggle verification in `MainUiRealRuntimeBridge`
- offscreen Dry Run start/stop verification in `MainUiRealRuntimeBridge`

Observed result:

- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- shell smoke still reports `Addon mount placeholders: none`
- offscreen hotkeys verification found `18` populated list entries on the adopted real `Hotkeys` tab
- offscreen chat edit verification showed:
  - before: frontend chat read-only `True`
  - during edit mode: frontend chat read-only `False`
  - after cancel: frontend chat read-only `True`
- offscreen Dry Run verification showed:
  - before: start enabled / stop disabled
  - after start: start disabled / stop enabled
  - after stop: start enabled / stop disabled

## What Phase 6 Solved Here

- chat edit mode is no longer deferred in `--ui-real`
- Dry Run controls are no longer deferred in `--ui-real`
- the adopted `Hotkeys` tab now has explicit real-surface refresh behavior and verified content
- the static duplicate Audio Story controls are no longer treated as a still-visible Phase 6 target in real mode

## What Still Remains

- provider/model workflow is still partly bridge-driven rather than Designer-owned
- the hidden backend still owns cleanup and several not-yet-migrated workflows
- visual reply runtime actions are still not moved into a direct Designer-owned path
- some deeper runtime workflows remain addon-owned through adopted tabs rather than Designer-owned surfaces

## Next Phase

Next recommended target:

```text
Continue Phase 6 by reducing the remaining bridge-owned runtime workflows in --ui-real, starting with provider/model mutation flow and any still-deferred visible controls outside the adopted addon tabs.
```
