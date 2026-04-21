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
- Adds tooltips to deferred runtime controls.
- Prints a concise binding/config/addon manifest summary to the terminal.
- Adds read-only addon mount placeholder tabs in the Designer shell.
- Live-mounts the allowlisted low-risk addons.
- Shows chat provider addon metadata without calling provider handlers.
- Prints a static-vs-addon tab comparison in the terminal.
- Binds local console/chat controls that only affect the shell preview.

This mode does not start runtime systems or mutate saved state.

## Low-Risk Live Addon Mounts

The shell preview now live-mounts these addons:

- `nc.chat_session_player` -> `left_tabs` as `Chat Player`
- `nc.hotkeys` -> `left_tabs` as `Hotkeys`
- `nc.loop_authoring` -> `musetalk_tabs` as `Loop Authoring`
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
- Visual Story Settings can render its real host-settings UI; it may update in-memory preview/runtime config while the shell is open, but shell notifications do not save session state or start runtime systems.
- Clipboard Source renders with an addon-local shell-preview guard; clipboard monitoring, initial clipboard capture, runtime delivery buttons, pending-turn mutation, and hidden-loop capture are disabled in shell mode.
- Gemini TTS Preview renders with an addon-local shell-preview guard; Gemini model refresh, connection checks, TTS generation, audio file writes, backend startup, and audio playback are disabled in shell mode.
- Chatterbox renders with an addon-local shell-preview guard; Chatterbox model loading, runtime config writes, backend startup, and audio generation are disabled in shell mode.
- PocketTTS renders with an addon-local shell-preview guard; interpreter lookup, file dialogs, subprocess adapter startup, runtime config writes, and audio generation are disabled in shell mode.
- Loop Authoring renders with an addon-local shell-preview guard; Wan2GP launch, conda environment probing, file dialogs, folder writes/opens, generated-video import, and MuseTalk handoff actions are disabled in shell mode.

Important:

- The shell provides no replay, model, audio, or engine lifecycle host services yet.
- Shell-provided services are limited to metadata-only chat provider registration, read-only hotkey lookup, shell-local visual reply settings, clipboard/Gemini/TTS/Loop Authoring shell-preview flags, and no-op shell settings notifications.
- Buttons that require absent host services either no-op or affect only addon-local shell state.
- Addon instances are kept alive for the shell window lifetime and cleaned up when the shell exits.
- Provider model-list, connection-check, completion, and stream handlers are not invoked in shell mode.
- `Hotkeys` and `Visual Story Settings` currently import `engine.py` to read existing hotkey/config constants. Smoke tests confirm this does not start the companion runtime, but it can emit existing engine-import warnings.
- Shell mode configures stdout/stderr with a Unicode fallback before live addon mounting so Windows `cp1252` consoles do not turn existing emoji startup prints into addon mount failures.
- Addons that call network/model/audio paths during render or expose subprocess-heavy workflows remain placeholder-only for now.

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
- `musetalk_tabs`: `Loop Authoring` is live-mounted through `nc.loop_authoring`; `MuseTalk Preprocess` remains placeholder-only.
- `tts_runtime_addon_tabs`: static `Chatterbox` and `PocketTTS` are replaced by the live-mounted `nc.chatterbox_tts` and `nc.pockettts` addons in shell mode.
- `right_tabs`: static `Audio Story Mode` overlaps the `nc.audio_story_mode` addon target.

These should be handled gradually. Do not remove static tabs until the corresponding addon is safely live-mounted in the shell or intentionally kept as a static Designer-owned panel.

## Current Safety Boundaries

Intentionally not connected yet:

- Engine start.
- Engine stop.
- Reset chat memory.
- Broad real addon initialization.
- Broad real addon widget mounting.
- TTS/STT/audio runtime.
- Image generation.
- Transcription.
- Provider model refresh/checks/completions/streaming.
- Model loading.
- Session save/load actions.
- Chat quick save/load actions.

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

Behavior:

- Console and chat clear only the preview widgets.
- Autoscroll toggles update shell status labels only.
- Chat font size changes only the preview `chat_edit` widget.
- Chat edit/apply/cancel is shell-local and does not save or update runtime state.
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
- Preset list/current preset.
- Chat Provider.
- LLM Model.
- Visual Reply mode/provider/size/model.
- TTS sampling controls.

These are display-only in shell mode.

## Recommended Next Step

Recommended next phase:

1. Keep the static `Audio Story Mode` tab Designer-owned for now.
2. Leave `MuseTalk Preprocess` placeholder-only until it has a dedicated shell-safe path that avoids import-time `engine.py`, `cv2`, and `MuseTalkBridge` coupling.
3. Keep `Audio Story Mode` as a dedicated later phase because it touches audio playback, transcription, timing, image generation, and addon state.
4. Re-run `python qt_app.py --ui-shell main.ui --shell-smoke` after each phase and confirm `left_tabs`, `host_settings_tabs`, `musetalk_tabs`, `sensory_feedback_tabs`, and `tts_runtime_addon_tabs` stay clean with no duplicate candidates except intentionally deferred runtime-sensitive tabs.

Why this should come next:

- `left_tabs` is now clean after live-mounting `Chat Player` and `Hotkeys`.
- `host_settings_tabs` is now clean after live-mounting `Visual Reply` and `Visual Story Settings`.
- `sensory_feedback_tabs` is now clean after live-mounting `Clipboard Source` with shell-only clipboard capture disabled.
- `Audio Story Mode` is the next visible duplicate, but it touches audio playback, transcription, timing, and image generation, so it needs a dedicated risk-controlled phase.
- Console/chat local controls are now in place without starting runtime systems.
- `tts_runtime_addon_tabs` is now clean after live-mounting Chatterbox, Gemini TTS, and PocketTTS with shell-only backend/model/subprocess work disabled.
- `musetalk_tabs` now live-mounts Loop Authoring with Wan2GP/subprocess/file actions disabled in shell mode.
- The remaining placeholder-only addons are runtime-sensitive surfaces, so the next phase should inspect one target at a time before allowlisting it.
- This keeps `python qt_app.py` as the stable default and keeps the Designer shell path experimental.

Audio Story Mode notes:

- The current addon controller imports `engine.py` and `shared_state` at module import time.
- `build_tab()` creates a `QMediaPlayer` through `_ensure_player()`.
- The tab controls connect directly to Whisper transcription, source/TTS playback, visual generation, timeline sync, and Visual Reply publication.
- Do not live-mount this addon through the generic shell allowlist until it has either a shell-only adapter or a controller split that can render UI without creating playback/model/image-generation runtime objects.

Alternative later phases:

1. Replace the static `Audio Story Mode` tab only after defining a shell-safe audio story host service boundary.
2. Add another carefully scoped addon host-service stub, but only when the addon can render without runtime/network/model calls.

Do not connect engine lifecycle, audio capture, TTS generation, transcription, or image generation in the same phase as real addon mounting.
