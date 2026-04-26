# main.ui Phase Report - 2026-04-24 - 12

This phase continued Phase 6 by reducing the remaining bridge-owned provider/model runtime workflow in `--ui-real`.

## Objective

Move the visible provider/model/preset workflow away from generic bridge mirroring and toward explicit runtime-backed behavior:

1. make provider selection behave as a real runtime workflow in `--ui-real`
2. make model selection and preset selection/buttons behave as real runtime workflows in `--ui-real`
3. mirror provider/model runtime status back into the Designer window with less reliance on passive polling

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_12.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Added explicit provider/model/preset workflow bindings in the real runtime bridge

`MainUiRealRuntimeBridge` now binds these visible Designer controls as an explicit runtime workflow slice:

- `chat_provider_combo`
- `model_combo`
- `preset_combo`
- `btn_preset_load`
- `btn_preset_save`
- `btn_preset_save_as`
- `btn_preset_delete`

Instead of relying only on the generic combo-copy bridge path, these controls now go through dedicated real-mode handlers that:

- push the frontend selection into the hidden backend runtime widget
- let the backend's own runtime signals and handlers perform the real mutation
- force immediate frontend resync after the backend workflow runs

### 2. Reduced duplicate bridge wiring for this runtime slice

The generic frontend-to-backend combo/checkbox sync path now skips the controls that have dedicated real-mode workflow handlers:

- `chat_provider_combo`
- `model_combo`
- `preset_combo`
- `model_requires_vision_checkbox`

This avoids double-triggering the same runtime path in both a generic bridge handler and a dedicated workflow handler.

### 3. Mirrored provider/model runtime status back into the real Designer surface

The bridge now mirrors additional runtime-owned state into the Designer window:

- `model_budget_label`
- preset save/save-as button styling
- model refresh button enabled/text state via the runtime button-state mirror

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py addons\hotkeys\controller.py addons\audio_story_mode\controller.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Additional verification executed in this pass:

- offscreen frontend provider switch in `MainUiRealRuntimeBridge`
- offscreen frontend preset selection change in `MainUiRealRuntimeBridge`
- offscreen inspection of mirrored `model_budget_label`

Observed result:

- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- shell smoke still reports `Addon mount placeholders: none`
- offscreen provider workflow verification changed:
  - frontend provider: `xAI / Grok` -> `OpenAI`
  - backend provider value: `xai` -> `openai`
- offscreen preset workflow verification changed:
  - frontend preset: `DryRun` -> `externalModelTest`
  - backend preset combo matched: `externalModelTest`
- the real Designer `model_budget_label` now reflects the backend runtime hint text

## What Phase 6 Solved Here

- provider selection is now a more direct runtime-backed workflow in `--ui-real`
- preset selection and preset action buttons are now a more direct runtime-backed workflow in `--ui-real`
- provider/model runtime status is mirrored more explicitly into the Designer surface

## What Still Remains

- visual reply runtime actions are still not moved into a direct Designer-owned path
- some runtime workflows still rely on the hidden backend as the owning controller rather than Designer-owned logic
- the hidden backend still owns cleanup and several not-yet-migrated workflows

## Next Phase

Next recommended target:

```text
Continue Phase 6 by reducing the remaining bridge-owned runtime workflows in --ui-real, starting with visual reply runtime actions and any other visible non-addon controls that still depend on hidden-backend ownership.
```
