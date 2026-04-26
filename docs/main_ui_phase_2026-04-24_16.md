# main.ui Phase Report - 2026-04-24 - 16

This phase continued Phase 6 by moving the visible response-length and host/input/runtime selection controls in `--ui-real` away from passive bridge syncing and into explicit runtime-backed behavior.

## Objective

Convert the next visible non-addon control groups called out in the continuation docs:

1. response-length controls first
2. host/input/runtime selection controls next
3. leave the remaining generic-sync ownership gaps listed concretely for the next pass

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_16.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Response-length controls now use explicit real-mode handlers

The real Designer controls:

- `limit_response_checkbox`
- `max_response_tokens_spin`

now bind through dedicated `MainUiRealRuntimeBridge` handlers instead of the passive generic frontend-to-backend sync wiring.

Those bridge handlers intentionally drive the hidden backend widgets so the existing runtime callbacks still run, and the frontend enable/disable state for `max_response_tokens_spin` is refreshed from the runtime-backed widget state.

### 2. Host/input/runtime selection controls now use explicit real-mode handlers

The real Designer controls:

- `audio_input_device_combo`
- `audio_output_device_combo`
- `engine_combo`
- `input_mode_combo`
- `input_role_combo`
- `stream_mode_combo`
- `tts_backend_combo`

now bind through dedicated real-mode bridge handlers instead of the passive generic combo-sync path.

For the controls that already had legacy runtime callbacks (`engine`, `input mode`, `input role`, `stream mode`, `tts backend`), the bridge now drives the hidden backend widget intentionally so the runtime-side handler executes through the same path the legacy UI used.

### 3. Audio-device selection is now persisted explicitly in `--ui-real`

`audio_input_device_combo` and `audio_output_device_combo` did not have legacy runtime widgets or callbacks in `CompanionQtMainWindow`.

This phase gave them an explicit real-mode commit path by:

- populating the visible Designer combos directly from the audio-device snapshot/session state
- writing the chosen input/output device into runtime config
- saving the selection into `qt_session.json`

The backend session save/restore path now includes these fields so the real Designer surface is not just showing transient UI-only state.

### 4. Removed live generic bridge wiring for these groups

The passive generic frontend-to-backend bridge binding now skips:

- `limit_response_checkbox`
- `max_response_tokens_spin`
- `audio_input_device_combo`
- `audio_output_device_combo`
- `engine_combo`
- `input_mode_combo`
- `input_role_combo`
- `stream_mode_combo`
- `tts_backend_combo`

That means these controls no longer depend on the broad generic copy-sync listener to reach runtime behavior in `--ui-real`.

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

- the visible response-length controls no longer depend on passive generic sync in `--ui-real`
- the visible host/input/runtime selection controls no longer depend on passive generic sync in `--ui-real`
- audio input/output selection now has an explicit real-mode persistence path instead of being effectively decorative state
- the frontend enable state for runtime-backed response/selection widgets now mirrors the backend runtime widget state more intentionally

## What Still Remains

Visible non-addon controls still using generic bridge sync in `--ui-real` are now:

- MuseTalk and visual-selection combos such as `musetalk_vram_combo`, `musetalk_avatar_pack_combo`, `visual_reply_mode_combo`, `visual_reply_provider_combo`, `visual_reply_size_combo`, `sensory_feedback_source_combo`, and `chat_font_size_combo`
- avatar/body/VaM controls such as `voice_combo`, `body_combo`, `emotion_combo`, `live_sync_checkbox`, `vam_root_edit`, `vam_bridge_root_edit`, `vam_target_atom_uid_edit`, `vam_target_storable_id_edit`, `vam_vmc_host_edit`, `vam_vmc_port_spin`, `vam_vmc_enabled_checkbox`, `vam_bridge_enabled_checkbox`, `vam_play_audio_in_vam_checkbox`, and `vam_timeline_auto_resume_checkbox`
- profile and utility controls such as `chunking_profile_combo`, `performance_profile_combo`, `dry_run_target_spin`, `dry_run_auto_replies_checkbox`, `musetalk_loop_fade_spin`, and `visual_reply_model_edit`
- static Designer duplicate/placeholder surfaces that still exist in `main.ui` even though live addon/runtime tabs are mounted elsewhere

## Next Phase

Next recommended target:

```text
Finish the visible non-addon ownership audit in --ui-real, then convert the remaining generic-sync controls by category, starting with MuseTalk/visual selection widgets and the avatar/body/VaM control group.
```
