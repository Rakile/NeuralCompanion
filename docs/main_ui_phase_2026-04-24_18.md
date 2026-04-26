# main.ui Phase Report - 2026-04-24 - 18

This phase continued Phase 6 by moving the remaining visible avatar/body/VaM control group in `--ui-real` away from passive generic sync and into explicit runtime-backed ownership.

## Objective

Convert the next visible non-addon control group called out after Phase 17:

1. avatar/body controls
2. VaM config controls
3. the runtime-facing enabled-state mirroring needed to keep the real Designer surface aligned with backend mode changes

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_18.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Avatar/body/VaM controls now use explicit real-mode handlers

The real Designer controls:

- `voice_combo`
- `body_combo`
- `emotion_combo`
- `live_sync_checkbox`
- `vam_vmc_enabled_checkbox`
- `vam_bridge_enabled_checkbox`
- `vam_play_audio_in_vam_checkbox`
- `vam_timeline_auto_resume_checkbox`
- `vam_vmc_port_spin`
- `vam_root_edit`
- `vam_target_atom_uid_edit`
- `vam_target_storable_id_edit`
- `vam_vmc_host_edit`

now bind through dedicated `MainUiRealRuntimeBridge` handlers instead of the passive generic combo/checkbox/spin/line-edit listeners.

For controls that already had legacy runtime callbacks, the bridge now intentionally drives the hidden backend widget so those callbacks still execute through the same path the legacy backend UI uses.

### 2. Body preset selection now executes as a real runtime action

`body_combo` was not just a state field in the backend UI. The actual runtime action was `load_body_config_from_combo()`.

This phase now makes the real Designer body-preset selector execute that backend action explicitly after syncing the selected body into the hidden backend combo. That removes the last passive-copy assumption from this part of the body workflow.

### 3. Added explicit frontend refresh for this control group

After avatar/body/VaM handlers run, the bridge now performs a short staged refresh so the real Designer surface picks up:

- avatar/body selection changes
- VaM derived path changes from `vam_root_edit`
- checkbox/spin/text updates written through backend callbacks
- follow-on widget-state changes caused by backend avatar mode logic

### 4. Added enabled-state mirroring for avatar/body/VaM widgets and related buttons

The real Designer frontend now mirrors backend enabled state more intentionally for:

- avatar/body/VaM field widgets
- body/VaM action buttons such as `btn_body_load`, `btn_body_save`, `btn_body_save_as`, `btn_body_delete`, `btn_hand_doctor`, `btn_start_vam_desktop`, `btn_start_vam_vr`, and `btn_vam_hide_interface`

This keeps the visible Designer surface aligned with backend mode-dependent enable/disable behavior instead of relying on stale frontend state.

### 5. Removed live generic bridge wiring for this control group

The passive generic frontend-to-backend bridge binding now skips:

- `voice_combo`
- `body_combo`
- `emotion_combo`
- `live_sync_checkbox`
- `vam_vmc_enabled_checkbox`
- `vam_bridge_enabled_checkbox`
- `vam_play_audio_in_vam_checkbox`
- `vam_timeline_auto_resume_checkbox`
- `vam_vmc_port_spin`
- `vam_root_edit`
- `vam_bridge_root_edit`
- `vam_target_atom_uid_edit`
- `vam_target_storable_id_edit`
- `vam_vmc_host_edit`

That means this visible control group no longer depends on the broad generic frontend listener path in `--ui-real`.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Observed result:

- `py_compile` passed
- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still reports `Addon mount placeholders: none`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- runtime smoke still reports:
  - `Provider runtime redirected: yes`
  - `Chat/session runtime redirected: yes`
  - `Sensory runtime redirected: yes`
  - `Visual Reply runtime redirected: yes (AddonVisualReplyPanel)`

## What Phase 6 Solved Here

- the visible avatar/body/VaM controls no longer depend on passive generic sync in `--ui-real`
- body preset selection now executes through an explicit runtime action instead of relying on passive combo copy
- the real Designer VaM path fields now follow backend-derived path refreshes more intentionally
- frontend enabled state for the avatar/body/VaM group now mirrors backend mode changes more intentionally

## What Still Remains

Visible non-addon controls still using generic bridge sync in `--ui-real` are now mainly the remaining profile/utility fields:

- `chunking_profile_combo`
- `performance_profile_combo`
- `dry_run_target_spin`
- `dry_run_auto_replies_checkbox`
- `musetalk_loop_fade_spin`
- `visual_reply_model_edit`
- static Designer duplicate/placeholder surfaces that still exist in `main.ui` even though live addon/runtime tabs are mounted elsewhere

## Next Phase

Next recommended target:

```text
Finish the remaining profile/utility cleanup pass in --ui-real by converting chunking/profile controls, Dry Run utility fields, MuseTalk loop fade, and visual-reply model editing off generic sync.
```
