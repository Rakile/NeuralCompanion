# main.ui Phase Report - 2026-04-23 - 05

This phase continued Phase 3 of the `main.ui` migration by targeting the remaining runtime-adjacent input/control actions that were still visibly present in `main.ui`.

## Objective

Bind the visible push-to-talk and Audio Story action controls in `main.ui` without crossing into live microphone capture, Whisper/STT, media playback, or TTS narration:

1. make the visible input/action controls interactive in `--ui-shell`
2. keep microphone, transcription, and playback side effects deferred in shell preview
3. expose a durable host-service boundary for this control group

## Files Changed

- `qt_app.py`
- `core/addons/qt_host_services.py`
- `docs/main_ui_phase_2026-04-23_05.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Added shell-local input/action bindings

The shell path now binds these visible controls:

- `btn_push_to_talk`
- `audio_file_path_edit`
- `audio_story_playback_combo`
- `transcribe_seconds_slider`
- `import_audio_button`
- `transcribe_audio_button`
- `audio_story_play_button`
- `audio_story_pause_button`
- `audio_story_stop_button`
- `audio_story_seek_slider`

Behavior in this phase:

- `btn_push_to_talk` now reacts in `--ui-shell` and is enabled only when Input Mode is `Push-to-Talk`
- press/release updates shell-local preview state and console feedback only
- no microphone capture or engine-side push-to-talk hold is started in shell preview
- the Audio Story path field is now editable in shell preview so a local path can be pasted for preview purposes
- the Audio Story playback mode and transcribe-seconds controls now update shell-local preview state
- Audio Story play/pause/stop/seek now update only shell-local preview state and labels
- no media player, Whisper/STT, imported-audio playback, or TTS narration is started

### 2. Kept runtime-sensitive actions deferred while still visible

These controls are now bound in shell preview, but their real runtime side effects remain deferred:

- `btn_push_to_talk`
- `import_audio_button`
- `transcribe_audio_button`
- `audio_story_play_button`
- `audio_story_pause_button`
- `audio_story_stop_button`

Current shell-safe behavior:

- `Import Audio` now explains that the native file-import flow remains deferred and that the path field can be used for preview
- `Transcribe Audio` now logs a deferred action instead of remaining disconnected
- Audio Story playback buttons now drive only shell-local preview state and position labels

### 3. Added a new host-service boundary

Added `qt.input_actions` in both service maps:

- shell-safe service in `qt_app.py`
- normal-app service in `core/addons/qt_host_services.py`

Current service coverage:

- snapshot push-to-talk preview/runtime availability
- preview push-to-talk press/release
- snapshot Audio Story path/playback-mode/transcribe-seconds/seek state
- preview Audio Story import/transcribe/playback actions

This service is additive in this phase. Existing runtime logic still works as before.

### 4. Updated smoke/preview reporting

The shell smoke and shell preview reports no longer describe these controls as merely "found but intentionally not connected".

They now report:

- the shell-local input/action controls that are actually bound
- the subset whose real runtime side effects are still deferred

### 5. Removed an unrelated validation warning

While already editing `qt_app.py`, this pass also removed an existing `return` inside a `finally` block in `_run_engine_thread(...)`.

That warning was unrelated to the new bindings but was safe to clean up here and is now gone from the validation output.

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

That remains separate from the input/action migration completed in this phase.

## What Is Still Shell-Local

- push-to-talk button preview in `--ui-shell`
- Audio Story path/playback/seek preview in `--ui-shell`

## What Is Still Deferred In Shell

- microphone capture
- Whisper/STT transcription
- imported-audio playback
- TTS narration playback
- the native Audio Story import dialog flow

## What Is Still Legacy-Only Or Missing

- a real runtime-backed `main.ui` mode
- runtime-heavy addon controller splits for `audio_story_mode` and `musetalk_preprocess`

## Next Phase

Next recommended target:

```text
Begin Phase 4 by splitting audio_story_mode from its runtime-heavy controller path so a renderable main.ui/runtime surface can exist without importing playback/transcription/image-generation systems during tab build.
```
