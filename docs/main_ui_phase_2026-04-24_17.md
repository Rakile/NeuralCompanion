# main.ui Phase Report - 2026-04-24 - 17

This phase continued Phase 6 by moving the remaining visible MuseTalk and visual selection widgets in `--ui-real` away from passive generic combo sync and into explicit runtime-backed behavior.

## Objective

Convert the next visible non-addon control group called out after Phase 16:

1. MuseTalk selection widgets
2. visual selection widgets
3. supporting frontend state mirroring for those runtime-backed controls

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_17.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. MuseTalk and visual selection widgets now use explicit real-mode handlers

The real Designer controls:

- `musetalk_vram_combo`
- `musetalk_avatar_pack_combo`
- `visual_reply_mode_combo`
- `visual_reply_provider_combo`
- `visual_reply_size_combo`
- `sensory_feedback_source_combo`
- `chat_font_size_combo`

now bind through dedicated `MainUiRealRuntimeBridge` handlers instead of the passive generic combo-sync listener.

For each of these controls, the bridge now intentionally drives the hidden backend widget so the legacy runtime callback still executes through the same path the backend UI uses.

### 2. Added explicit runtime refresh for this widget group

After each real-mode handler runs, the bridge now performs a short staged frontend refresh so the real Designer surface picks up:

- MuseTalk avatar-pack and VRAM side effects
- Visual Reply hint/model/provider/size side effects
- sensory-source summary/hint updates and runtime source-tab rebuilds
- chat font-size changes reflected in the visible chat surface

### 3. Removed live generic bridge wiring for this combo group

The passive generic frontend-to-backend combo binding now skips:

- `musetalk_vram_combo`
- `musetalk_avatar_pack_combo`
- `visual_reply_mode_combo`
- `visual_reply_provider_combo`
- `visual_reply_size_combo`
- `sensory_feedback_source_combo`
- `chat_font_size_combo`

That means these widgets no longer depend on the broad generic combo listener in `--ui-real`.

### 4. Added enabled-state mirroring for the runtime-backed selection widgets

The real Designer frontend now mirrors backend enabled state for this group more intentionally, especially for runtime-sensitive controls such as:

- `musetalk_vram_combo`
- `musetalk_avatar_pack_combo`
- `sensory_feedback_source_combo`

This keeps the real Designer surface aligned with backend runtime state when the hidden runtime window disables or re-enables these widgets.

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

- the visible MuseTalk/visual selection widgets no longer depend on passive generic combo sync in `--ui-real`
- the visible sensory-source selector is now on the same explicit runtime path as the rest of the sensory control group
- the visible chat font-size selector is now on an explicit real-mode handler path instead of the generic combo listener
- frontend enabled-state mirroring for this widget group is now more intentional

## What Still Remains

Visible non-addon controls still using generic bridge sync in `--ui-real` are now mostly the avatar/body/VaM and remaining utility fields:

- avatar/body/VaM controls such as `voice_combo`, `body_combo`, `emotion_combo`, `live_sync_checkbox`, `vam_root_edit`, `vam_bridge_root_edit`, `vam_target_atom_uid_edit`, `vam_target_storable_id_edit`, `vam_vmc_host_edit`, `vam_vmc_port_spin`, `vam_vmc_enabled_checkbox`, `vam_bridge_enabled_checkbox`, `vam_play_audio_in_vam_checkbox`, and `vam_timeline_auto_resume_checkbox`
- profile and utility controls such as `chunking_profile_combo`, `performance_profile_combo`, `dry_run_target_spin`, `dry_run_auto_replies_checkbox`, `musetalk_loop_fade_spin`, and `visual_reply_model_edit`
- static Designer duplicate/placeholder surfaces that still exist in `main.ui` even though live addon/runtime tabs are mounted elsewhere

## Next Phase

Next recommended target:

```text
Convert the remaining avatar/body/VaM control group in --ui-real from generic sync to explicit runtime-backed ownership, then do the remaining profile/utility cleanup pass.
```
