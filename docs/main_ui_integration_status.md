# main.ui Safe Transition Status

This document tracks the safe `main.ui` transition work currently present in this branch.

## Stable Default

The normal app startup remains:

```powershell
python qt_app.py
```

That path uses the existing Python-built UI and is intentionally not changed by the experimental shell work.

## Implemented Safe Modes

### UI Validator

```powershell
python qt_app.py --validate-ui main.ui
```

Parses `main.ui` as XML and exits before importing the heavy runtime modules.

Checks:

- Core dock object names.
- Stable tab mount object names.
- Dynamic/addon mount point object names.
- Stable runtime control object names.
- Duplicate widget/layout/action object names.

This mode does not start Flask, addons, audio, TTS, STT, image generation, or the companion engine.

### Shell Smoke

```powershell
python qt_app.py --ui-shell main.ui --shell-smoke
```

Loads the Designer shell with Qt, validates bindable widgets by object name, prints a report, and exits.

Current behavior:

- Reports core shell binding readiness.
- Reports dynamic mount point availability.
- Populates a small read-only preview from `qt_session.json` when available.
- Discovers addon manifests from `addons/*/addon.json`.
- Statically scans addon `main.py` files for declared `register_tab(area=...)` targets.
- Reports likely mount targets for addon tabs/services.
- Live-mounts the current allowlisted low-risk addons, then cleans them up before exit.
- Live-registers chat provider addons through a shell-safe provider registry stub.
- Prints a static-vs-addon tab comparison for likely duplicate/fake Designer tabs.
- Reports whether the heavy `engine.py` module was imported; shell smoke is not ready if this regresses to `yes`.

This mode does not start Flask, connect engine lifecycle actions, call provider model refresh, or start audio/image/transcription/model runtime systems.

### Visual-Only Shell Preview

```powershell
python qt_app.py --ui-shell main.ui
```

Opens `main.ui` as a visual-only Designer shell preview.

Current behavior:

- Shows the Designer shell window.
- Marks existing status labels with shell-preview status.
- Populates selected controls from saved session state in read-only form.
- Disables deferred runtime controls and adds tooltips explaining that runtime wiring is intentionally not connected yet.
- Prints a concise binding/config/addon manifest summary to the terminal.
- Adds read-only addon mount placeholder tabs in the Designer shell.
- Live-mounts the allowlisted low-risk addons.
- Binds Chat Runtime provider/model/config/generation controls from shell-registered provider addon metadata without calling provider handlers.
- Binds preset/session controls in shell-local preview mode.
- Binds engine lifecycle buttons in shell-local preview mode.
- Prints a static-vs-addon tab comparison in the terminal.
- Binds local console/chat controls that only affect the shell preview.

This mode does not start runtime systems or mutate saved state.

## Low-Risk Live Addon Mounts

The shell preview now live-mounts these addons:

- `nc.chat_session_player` -> `left_tabs` as `Chat Player`
- `nc.audio_story_mode` -> replaces the static `audio_story_mode_tab` in `right_tabs` as `Audio Story Mode`
- `nc.hotkeys` -> `left_tabs` as `Hotkeys`
- `nc.loop_authoring` -> `musetalk_tabs` as `Loop Authoring`
- `nc.musetalk_preprocess` -> `musetalk_tabs` as `Preprocess`
- `nc.visual_reply` -> replaces the static `host_settings_visuals_tab` as `Visuals`
- `nc.visual_story_settings` -> `host_settings_tabs` as `Story Visuals`
- `nc.chatterbox_tts` -> replaces the static `tts_chatterbox_tab` as `Chatterbox`
- `nc.pockettts` -> replaces the static `tts_pockettts_tab` as `PocketTTS`
- `nc.screen_supervisor` -> `sensory_feedback_tabs` as `Screen / Supervisor`
- `nc.webcam_supervisor` -> `sensory_feedback_tabs` as `Webcam / Supervisor`
- `nc.clipboard_source` -> `sensory_feedback_tabs` as `Clipboard / Source`
- `nc.clipboard_supervisor` -> `sensory_feedback_tabs` as `Clipboard / Supervisor`
- `nc.gemini_tts_preview` -> `tts_runtime_addon_tabs` as `Gemini TTS`
- `nc.heart_rate_behavior` -> `sensory_feedback_tabs` as `Heart Rate / Threshold Rules`
- `nc.mock_heart_rate` -> `sensory_feedback_tabs` as `Heart Rate / Source`
- `nc.chat_provider_lmstudio` -> shell chat provider registry as `LM Studio`
- `nc.chat_provider_openai` -> shell chat provider registry as `OpenAI`
- `nc.chat_provider_xai` -> shell chat provider registry as `xAI / Grok`
- `nc.claude_provider` -> shell chat provider registry as `Claude`

Why these addons were chosen:

- They can render without real host runtime services.
- Their shell behavior is local, inert, or limited to the shell-local addon context.
- They exercise the real addon `initialize(...)`, `register_tab(...)`, and tab factory paths across multiple mount areas.
- Chat provider addons only register metadata and callable handlers; shell mode stores those handlers but never calls them.
- Hotkeys renders with a shell-only read-only hotkey service; capture and mutation controls are disabled in the Designer shell.
- Visual Reply renders through a shell-only `qt.visual_reply` service; it does not replace the real image dock, generate images, mutate image history, or save settings.
- Visual Story Settings can render its real host-settings UI through the shell-local Visual Reply config facade; it may update in-memory preview config while the shell is open, but shell notifications do not save session state or start runtime systems.
- Clipboard Source renders with an addon-local shell-preview guard; clipboard monitoring, initial clipboard capture, runtime delivery buttons, pending-turn mutation, and hidden-loop capture are disabled in shell mode.
- Gemini TTS Preview renders with an addon-local shell-preview guard; Gemini model refresh, connection checks, TTS generation, audio file writes, backend startup, and audio playback are disabled in shell mode.
- Chatterbox renders with an addon-local shell-preview guard; Chatterbox model loading, runtime config writes, backend startup, and audio generation are disabled in shell mode.
- PocketTTS renders with an addon-local shell-preview guard; interpreter lookup, file dialogs, subprocess adapter startup, runtime config writes, and audio generation are disabled in shell mode.
- Loop Authoring renders with an addon-local shell-preview guard; Wan2GP launch, conda environment probing, file dialogs, folder writes/opens, generated-video import, and MuseTalk handoff actions are disabled in shell mode.
- MuseTalk Preprocess renders through a shell-only adapter in the addon entry point; the real controller is not imported, so shell mode avoids import-time `engine.py`, `cv2`, and `MuseTalkBridge` coupling from this addon.
- Audio Story Mode renders through a shell-only adapter in the addon entry point; the real controller is not imported, so shell mode avoids `engine.py`/`shared_state` import-time coupling, `QMediaPlayer` creation, Whisper transcription, TTS narration, Visual Reply generation, and playback timeline sync.

Important:

- The shell provides no replay, model, audio, or engine lifecycle host services yet.
- Shell-provided services are limited to metadata-only chat provider registration, read-only hotkey lookup, shell-local visual reply settings, clipboard/Gemini/TTS/Loop Authoring/MuseTalk Preprocess/Audio Story shell-preview flags, and no-op shell settings notifications.
- Buttons that require absent host services either no-op or affect only addon-local shell state.
- Addon instances are kept alive for the shell window lifetime and cleaned up when the shell exits.
- Chat Runtime fields are rendered from provider metadata in shell mode, but provider model-list, connection-check, completion, and stream handlers are not invoked.
- `Hotkeys` and `Visual Story Settings` no longer import `engine.py` during shell preview mounting. Hotkeys reads constants from `core.runtime_hotkeys`; Visual Story Settings reads/writes shell-local Visual Reply config through `qt.visual_reply`.
- Shell mode configures stdout/stderr with a Unicode fallback before live addon mounting so Windows `cp1252` consoles do not turn existing emoji startup prints into addon mount failures.
- Runtime-sensitive addons that cannot safely render their real controller in shell mode use shell-only adapters or addon-local shell guards.

## Chat Runtime Shell Binding

The Designer shell now binds the `Chat Runtime` card to shell-registered chat provider addon metadata:

- `chat_provider_combo` is populated from provider addons registered through the shell-safe `qt.chat_providers` service.
- `chat_provider_fields_layout` renders provider config fields such as API key, base URL, and API version.
- `chat_provider_generation_fields_layout` renders provider-specific generation fields such as temperature, top-p, top-k, repetition penalty, and max tokens.
- `model_combo` shows the saved model plus a deferred-refresh note.
- The Chat Runtime group title summarizes the selected provider and saved model.

This is still shell-local:

- Edits are not saved to `qt_session.json`.
- Edits are not pushed into `RUNTIME_CONFIG`.
- Provider handlers are stored by the shell registry but never called.
- Live model refresh remains deferred.
- Real engine start/stop remains disconnected.

## Preset/Session Shell Binding

The Designer shell now binds the main preset/session controls in a read-only-safe way:

- `preset_combo` is populated from `presets/*.json`.
- `btn_preset_load` reads the selected preset and previews its Chat Runtime values in the shell.
- The previewed values include selected chat provider, model name, provider settings, and provider generation fields.
- `btn_preset_save`, `btn_preset_save_as`, and `btn_preset_delete` remain disabled.
- `btn_save_chat_session`, `btn_load_chat_session`, and `btn_reset_chat_session` remain disabled.
- `session_hint_label` reports that preset load is shell-local and does not mutate runtime state.

This keeps preset loading useful for validating Designer bindings while preserving the safety boundary:

- No preset file is written or deleted.
- `qt_session.json` is not changed.
- `RUNTIME_CONFIG` is not changed.
- Chat history/context files are not read or written.
- Engine lifecycle and model refresh remain disconnected.

## Lifecycle Shell Binding

The Designer shell now gives the main lifecycle buttons shell-local behavior:

- `btn_start_engine` switches the shell preview into a simulated running state and logs a shell-only Initialize message.
- `btn_stop_engine` switches the shell preview back to a simulated stopped state and logs a shell-only Terminate message.
- `btn_reset_chat` clears only the Designer shell chat widget and logs a shell-only reset message.

This is intentionally not the real engine lifecycle yet:

- `run_companion(...)` is not called.
- `stop_flag` is not changed.
- `shutdown_avatar_engine()` is not called.
- No TTS/STT/audio/avatar/image/model runtime is started or stopped.
- No session file, preset file, chat context, or `RUNTIME_CONFIG` value is mutated.

## TTS Runtime Designer Layout

The Designer shell now keeps TTS backend selection and backend-specific settings together:

- `tts_backend_combo` lives inside the `TTS Runtime` section instead of the upper Host/System Shaping form.
- `tts_runtime_addon_tabs` is visible as the runtime settings tab view instead of being squeezed into a form row.
- Static Designer tabs provide replacement targets for `Chatterbox` and `PocketTTS`; shell mode replaces them with live addon tabs.
- The PocketTTS bundled interpreter/advanced override controls moved from the Persona tab into the `PocketTTS` runtime tab.
- The live-mounted `Chatterbox`, `Gemini TTS`, and `PocketTTS` addons all mount into the same `tts_runtime_addon_tabs` surface.
- Object names used by shell validation and future binding were preserved.

This is layout-only. It does not start TTS, load models, play audio, call Gemini, or make `main.ui` the default UI.

## Addon Mount Placeholder Preview

The shell preview now displays where enabled addon manifests would mount without importing addon code.

Placeholder targets:

- `top_level` -> `left_tabs`
- `host_settings` -> `host_settings_tabs`
- `musetalk` -> `musetalk_tabs`
- `tts_runtime` -> `tts_runtime_addon_tabs`
- `vision_source` -> `sensory_feedback_tabs`
- `operational_view` -> `right_tabs`
- chat provider addons -> `chat_provider_combo`; allowlisted providers are live-registered against the shell-safe registry

The placeholders are shell-local and read-only. They do not create addon controllers, call addon services, or start runtime behavior.

## Static-vs-Addon Comparison

The shell smoke and preview now compare static `main.ui` tab pages against discovered addon mount targets.

This is diagnostic only. It does not delete or hide Designer tabs.

The current comparison is useful for spotting tabs that are probably static placeholders or duplicate addon-owned UI. Current notable candidates:

- `left_tabs`: static `Hotkeys` is replaced by the live-mounted `nc.hotkeys` addon in shell mode.
- `left_tabs`: static `Chat Player` is replaced by the live-mounted `nc.chat_session_player` addon in shell mode.
- `host_settings_tabs`: static `Visuals` is replaced by the live-mounted `nc.visual_reply` addon in shell mode, and `nc.visual_story_settings` mounts as `Story Visuals`.
- `musetalk_tabs`: `Loop Authoring` is live-mounted through `nc.loop_authoring`; `Preprocess` is live-mounted through the `nc.musetalk_preprocess` shell-only adapter.
- `tts_runtime_addon_tabs`: static `Chatterbox` and `PocketTTS` are replaced by the live-mounted `nc.chatterbox_tts` and `nc.pockettts` addons in shell mode.
- `right_tabs`: static `Audio Story Mode` is replaced by the `nc.audio_story_mode` shell-only adapter.

These should be handled gradually. Do not remove static tabs until the corresponding addon is safely live-mounted in the shell or intentionally kept as a static Designer-owned panel.

## Current Safety Boundaries

Intentionally not connected yet:

- Real engine start.
- Real engine stop.
- Real reset chat memory.
- Broad real addon initialization.
- Broad real addon widget mounting.
- TTS/STT/audio runtime.
- Image generation.
- Transcription.
- Provider model refresh/checks/completions/streaming.
- Model loading.
- Session save/load/delete actions.
- Chat quick save/load actions.

In shell preview, the main runtime buttons are now shell-local previews rather than real runtime controls:

- `btn_start_engine`
- `btn_stop_engine`
- `btn_reset_chat`

Runtime-heavy audio-story buttons remain visibly disabled:

- `import_audio_button`
- `transcribe_audio_button`

## Shell-Local Console/Chat Controls

The Designer shell now binds these controls locally:

- `console_clear_button`
- `console_autoscroll_button`
- `chat_clear_button`
- `chat_autoscroll_button`
- `chat_font_size_combo`
- `chat_edit_mode_button`
- `chat_apply_edit_button`
- `chat_cancel_edit_button`
- `btn_start_engine`
- `btn_stop_engine`
- `btn_reset_chat`

Behavior:

- Console and chat clear only the preview widgets.
- Autoscroll toggles update shell status labels only.
- Chat font size changes only the preview `chat_edit` widget.
- Chat edit/apply/cancel is shell-local and does not save or update runtime state.
- Lifecycle start/stop/reset is shell-local and does not start or stop runtime systems.
- `chat_quick_save_button` and `chat_quick_load_button` remain disabled because they touch file/session operations.

## Current Read-Only Preview Data

The shell preview can mirror saved values such as:

- Avatar Engine.
- Input Mode.
- Input Role.
- Stream Mode.
- TTS Backend.
- MuseTalk VRAM mode.
- MuseTalk avatar pack.
- Preset list/current preset, with shell-local preset-load preview for Chat Runtime values.
- Chat Provider and provider-specific config/generation fields, now shell-local rather than placeholder text.
- LLM Model, currently saved-model display plus deferred live refresh.
- Visual Reply mode/provider/size/model.
- TTS sampling controls.

These are display-only in shell mode.

## Recommended Next Step

Recommended next phase:

1. Keep `main.ui` shell mode as a non-runtime shell until the object-name and addon-mount boundary is accepted.
2. Continue runtime binding one narrow surface at a time. The next good candidates are runtime host-service facades for model refresh/status or shell-safe engine lifecycle preparation, with real model/audio/avatar startup still deferred until that boundary is accepted.
3. Later, consider replacing shell adapters with real controller splits only if runtime-heavy imports can be kept out of shell rendering.
4. Re-run `python qt_app.py --ui-shell main.ui --shell-smoke` after each phase and confirm addon-owned tab surfaces stay clean with no duplicate candidates or placeholder-only addon targets.

## Handover Notes

Current pushed shell milestones:

- `0d8222f` - Chat Runtime provider/model/config/generation metadata binding.
- `a08f291` - Preset Load previews selected preset Chat Runtime values without mutating runtime/session state.
- `af08b8e` - Handover boundary docs plus visibly disabled deferred runtime buttons.

Current local shell-boundary milestone:

- Shell live-addon mounting no longer imports the heavy runtime engine path for Hotkeys or Visual Story Settings.
- `python qt_app.py --ui-shell main.ui --shell-smoke` now completes without the engine-import startup cleanup/TensorFlow warning path.
- Shell smoke now prints `Heavy engine imported: no` and treats a heavy-engine import as a shell-boundary regression.
- MuseTalk avatar adapter payload construction has been moved further into the MuseTalk avatar addon and still needs a quick real MuseTalk runtime validation before being treated as a pushed safe point.

Current handover boundary:

- The Python-built app remains the stable default via `python qt_app.py`.
- `python qt_app.py --ui-shell main.ui` is the safe Designer shell preview.
- Shell mode can render addon tabs and preview Chat Runtime/preset state, but cannot start runtime systems.
- Shell-local lifecycle buttons can simulate Initialize/Terminate/Reset, but they do not call real runtime functions.
- Real engine lifecycle should be the next deliberately planned phase, not a side effect of these preview bindings.

Why this should come next:

- `left_tabs` is now clean after live-mounting `Chat Player` and `Hotkeys`.
- `host_settings_tabs` is now clean after live-mounting `Visual Reply` and `Visual Story Settings`.
- `sensory_feedback_tabs` is now clean after live-mounting `Clipboard Source` with shell-only clipboard capture disabled.
- `right_tabs` is now clean after replacing the static `Audio Story Mode` tab with the addon shell adapter.
- Console/chat local controls are now in place without starting runtime systems.
- `tts_runtime_addon_tabs` is now clean after live-mounting Chatterbox, Gemini TTS, and PocketTTS with shell-only backend/model/subprocess work disabled.
- `musetalk_tabs` now live-mounts Loop Authoring with Wan2GP/subprocess/file actions disabled in shell mode, and Preprocess through a shell-only adapter.
- All addon-owned tab surfaces currently report clean in shell smoke; remaining shell placeholders are provider-field metadata placeholders, not tab duplicates.
- This keeps `python qt_app.py` as the stable default and keeps the Designer shell path experimental.

Audio Story Mode notes:

- The current addon controller imports `engine.py` and `shared_state` at module import time.
- `build_tab()` creates a `QMediaPlayer` through `_ensure_player()`.
- The tab controls connect directly to Whisper transcription, source/TTS playback, visual generation, timeline sync, and Visual Reply publication.
- Shell mode live-mounts this addon through a shell-only adapter. Do not replace that adapter with the real controller until the controller is split so UI rendering cannot create playback/model/image-generation runtime objects.

Alternative later phases:

1. Split the real Audio Story Mode controller into shell-renderable UI state and runtime actions if the shell eventually needs a faithful live form instead of the current safe adapter.
2. Split the real MuseTalk Preprocess controller into shell-renderable UI state and runtime bridge actions if the shell eventually needs a faithful live form instead of the current safe adapter.
3. Add carefully scoped runtime host-service stubs only when the target behavior can be proven not to start network/model/audio/video work during shell rendering.

Do not connect engine lifecycle, audio capture, TTS generation, transcription, or image generation in the same phase as real addon mounting.
