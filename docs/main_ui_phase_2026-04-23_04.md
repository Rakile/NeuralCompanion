# main.ui Phase Report - 2026-04-23 - 04

This phase continued Phase 3 of the `main.ui` migration by targeting the persona/body/VaM control group.

## Objective

Bind the visible persona, VSeeFace body, and VaM bridge controls in `main.ui` without crossing into the real runtime or process-launch behavior:

1. make the visible persona/body/VaM controls interactive in `--ui-shell`
2. keep file mutation, debugger, hide-interface, and VaM launch actions deferred in shell preview
3. expose a durable host-service boundary for this control group

## Files Changed

- `qt_app.py`
- `core/addons/qt_host_services.py`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Added shell-local persona bindings

The shell path now binds these persona controls:

- `voice_combo`
- `emotional_text`
- `system_prompt_text`
- `btn_apply_text_config`

Behavior in this phase:

- voice options are populated from `voices/*.wav`
- persona text fields now remain editable in shell preview
- `Apply Changes` now acts as a shell-local preview action only
- no runtime config is written
- no TTS/avatar/runtime systems are restarted

### 2. Added shell-local VSeeFace body bindings

The shell path now binds the visible body controls:

- `body_combo`
- `btn_body_load`
- `emotion_combo`
- `live_sync_checkbox`
- visible body/dynamics sliders in `main.ui`:
  - `idle_fwd_left_slider`
  - `idle_fwd_right_slider`
  - `idle_arm_down_slider`
  - `eye_activity_slider`
  - `breath_speed_slider`
  - `shoulder_lift_slider`

Shell-safe behavior:

- body preset lists are now loaded from `body_configs/*.json`
- loading a body preset applies only the shell-visible pose subset
- changing emotion updates the visible shell sliders from the loaded preset
- changing sliders updates label text and shell console feedback only
- no avatar runtime pose state is changed

Still deferred in shell preview:

- `btn_body_save`
- `btn_body_save_as`
- `btn_body_delete`
- `btn_hand_doctor`
- `btn_vseeface_hide_interface`

### 3. Added shell-local VaM bridge bindings

The shell path now binds the visible VaM controls:

- `vam_root_edit`
- `vam_bridge_root_edit`
- `vam_target_atom_uid_edit`
- `vam_target_storable_id_edit`
- `vam_vmc_host_edit`
- `vam_vmc_port_spin`
- `vam_vmc_enabled_checkbox`
- `vam_bridge_enabled_checkbox`
- `vam_play_audio_in_vam_checkbox`
- `vam_timeline_auto_resume_checkbox`

Shell-safe behavior:

- VaM root is normalized locally in shell preview
- bridge path is derived locally from VaM root
- the detected setup labels now show shell-local preview state
- no sockets, file bridge, or VaM runtime connector is started

Still deferred in shell preview:

- `btn_start_vam_desktop`
- `btn_start_vam_vr`
- `btn_vam_hide_interface`

### 4. Added a new host-service boundary

Added `qt.persona_avatar` in both service maps:

- shell-safe service in `qt_app.py`
- normal-app service in `core/addons/qt_host_services.py`

Current service coverage:

- snapshot persona/body/VaM state
- refresh body preset list
- load a body preset
- apply persona changes
- save/delete body presets
- launch VaM
- request external avatar view

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

That remains separate from the persona/body/VaM migration completed in this phase.

## What Is Still Shell-Local

- persona text editing in `--ui-shell`
- body preset load and visible pose preview in `--ui-shell`
- VaM bridge field editing in `--ui-shell`

## What Is Still Deferred In Shell

- body preset save/delete
- hand doctor
- VSeeFace hide-interface
- VaM launch
- VaM hide-interface

## What Is Still Legacy-Only Or Missing

- push-to-talk and runtime-adjacent input actions
- a real runtime-backed `main.ui` mode

## Next Phase

Next recommended target:

```text
Start consolidating the remaining runtime-adjacent input/control actions, beginning with push-to-talk and any still-legacy action buttons that are visible in main.ui but intentionally deferred today.
```
