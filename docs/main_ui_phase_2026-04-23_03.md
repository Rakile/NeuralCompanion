# main.ui Phase Report - 2026-04-23 - 03

This phase continued Phase 3 of the `main.ui` migration by targeting the Dry Run tab.

## Objective

Bind the visible Dry Run controls in `main.ui` without crossing into the real profiling/session machinery:

1. make the Dry Run tab interactive in `--ui-shell`
2. keep start/stop deferred in shell preview
3. expose a durable host-service boundary for Dry Run workflows

## Files Changed

- `qt_app.py`
- `core/addons/qt_host_services.py`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Added shell-local Dry Run bindings

The shell path now binds these Dry Run controls:

- `dry_run_target_spin`
- `dry_run_auto_replies_checkbox`
- `btn_dry_run_start`
- `btn_dry_run_stop`
- `btn_dry_run_apply`

Behavior in this phase:

- target sample count and hands-free toggle are now shell-local preview controls
- the Dry Run status label and summary area now show shell-safe preview state
- the summary uses the latest saved profile from `performance_profiles/*.json` when available
- no profiling session is started
- no engine/model/TTS/avatar runtime is started

### 2. Dry Run actions are now split between preview and deferred behavior

Shell behavior in this phase:

- `Arm Dry Run`: deferred
- `Stop Dry Run`: deferred
- `Apply Recommendation`: shell-safe preview action

`Apply Recommendation` now applies only the shell-visible subset of the latest saved recommendation:

- stream mode
- MuseTalk VRAM mode
- the visible chunking sliders already migrated in the previous phase

This remains preview-only. No runtime config is applied and no real Dry Run session state is mutated.

### 3. Added a new host-service boundary

Added `qt.dry_run` in both service maps:

- shell-safe service in `qt_app.py`
- normal-app service in `core/addons/qt_host_services.py`

Current service coverage:

- snapshot current Dry Run state
- refresh preview/runtime state
- start session
- stop session
- apply recommendation

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

- `nc.hotkeys` still failed to mount live in shell smoke because `keyboard` is unavailable
- shell smoke therefore still reported `Addon mount placeholders: left_tabs`

That remains separate from the Dry Run migration completed in this phase.

## What Is Still Shell-Local

- Dry Run target sample count in `--ui-shell`
- Dry Run hands-free toggle in `--ui-shell`
- Dry Run recommendation preview in `--ui-shell`

## What Is Still Deferred In Shell

- real Dry Run session start
- real Dry Run session stop
- any live observation capture or candidate cycling
- any runtime-side control-button disabling tied to a real Dry Run session

## What Is Still Legacy-Only Or Missing

- persona/body/VaM control groups
- push-to-talk/runtime-adjacent input actions
- a real runtime-backed `main.ui` mode

## Next Phase

Next recommended target:

```text
Move the remaining persona/body/VaM control group into shell-safe bindings, then add or extend a matching host-service boundary where direct widget access is still the only contract.
```
