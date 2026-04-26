# main.ui Phase Report - 2026-04-24 - 14

This phase continued Phase 6 by moving the remaining sensory hidden-loop/runtime widgets in `--ui-real` away from passive bridge syncing and into explicit frontend-owned runtime behavior.

## Objective

Promote the visible sensory core controls in the real Designer window from generic bridge sync to explicit runtime-backed ownership:

1. make the frontend sensory hint and hidden-loop controls update through the real runtime handlers
2. keep sensory source tabs building on the real Designer surface when frontend source controls change
3. close the remaining visible sensory ownership gap after the earlier sensory tab/source redirect

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_14.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Redirected sensory core widget ownership to the real Designer widgets

`MainUiRealRuntimeBridge` now assigns the backend sensory runtime owner to the real Designer widgets for:

- `sensory_feedback_interval_spin`
- `sensory_pingpong_checkbox`
- `sensory_allow_hidden_proactive_checkbox`
- `sensory_allow_hidden_visual_checkbox`
- `sensory_pingpong_history_spin`
- `sensory_pingpong_prompt_text`
- `sensory_feedback_hint`

That means the backend sensory runtime logic now refreshes the frontend hint and prompt state directly instead of only mutating hidden-backend widgets.

### 2. Added explicit real-mode sensory control bindings

The bridge now binds dedicated real-mode handlers for the visible sensory core controls instead of relying only on generic copy-sync:

- interval spin
- hidden PING/PONG enable toggle
- hidden proactive speech toggle
- hidden visual generation toggle
- hidden PONG history depth
- hidden PING/PONG prompt editor

Each handler now runs the backend sensory runtime method and then immediately refreshes the frontend hint/state.

### 3. Preserved frontend sensory source-tab runtime behavior

The earlier sensory source redirect already built source tabs in the real Designer surface. This phase verified that frontend source selection still creates runtime source tabs there, while the new explicit sensory core bindings keep the core hint and hidden-loop text consistent on the same frontend surface.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py addons\visual_reply\controller.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Note:

- `py_compile` and the two Qt smoke checks needed to run outside the sandbox in this environment because local sandboxed runs hit Windows permission or Qt loader failures that did not reproduce outside the sandbox.

Additional verification executed in this pass:

- offscreen frontend hidden PING/PONG toggle in `MainUiRealRuntimeBridge`
- offscreen frontend source selection in `sensory_feedback_sources_widget`
- inspection of the frontend `sensory_feedback_hint` text before and after the toggle

Observed result:

- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still reports `Addon mount placeholders: none`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- runtime smoke still reports `Sensory runtime redirected: yes`
- offscreen frontend verification confirmed:
  - frontend hint text changes from `Hidden PING/PONG is off ...` to `Hidden PING/PONG is enabled ...`
  - frontend source checkbox selection created a runtime sensory tab from `Core` to `Core, Screen`

## What Phase 6 Solved Here

- the visible sensory core controls in `--ui-real` now execute through explicit runtime handlers
- the frontend sensory hint is now updated by the real runtime path instead of only hidden-backend state
- frontend sensory source selection still builds runtime source tabs on the Designer surface

## What Still Remains

- some visible non-addon runtime controls still depend on generic bridge syncing rather than explicit real-mode ownership
- the hidden backend still owns broader runtime orchestration and cleanup

## Next Phase

Next recommended target:

```text
Continue Phase 6 by converting the remaining visible chat/session flow controls in --ui-real from generic bridge sync to explicit runtime-backed ownership, then do a final audit for any remaining visible non-addon ownership gaps.
```
