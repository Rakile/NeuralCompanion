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

This mode does not start runtime systems or mutate saved state.

## Low-Risk Live Addon Mounts

The shell preview now live-mounts these addons:

- `nc.chat_session_player` -> `left_tabs` as `Chat Player`
- `nc.screen_supervisor` -> `sensory_feedback_tabs` as `Screen / Supervisor`
- `nc.webcam_supervisor` -> `sensory_feedback_tabs` as `Webcam / Supervisor`
- `nc.clipboard_supervisor` -> `sensory_feedback_tabs` as `Clipboard / Supervisor`
- `nc.heart_rate_behavior` -> `sensory_feedback_tabs` as `Heart Rate / Threshold Rules`
- `nc.mock_heart_rate` -> `sensory_feedback_tabs` as `Heart Rate / Source`
- `nc.chat_provider_lmstudio` -> shell chat provider registry as `LM Studio`
- `nc.chat_provider_openai` -> shell chat provider registry as `OpenAI`
- `nc.chat_provider_xai` -> shell chat provider registry as `xAI / Grok`
- `nc.claude_provider` -> shell chat provider registry as `Claude`

Why these addons were chosen:

- They do not import `engine.py` during render.
- They can render without real host runtime services.
- Their shell behavior is local, inert, or limited to the shell-local addon context.
- They exercise the real addon `initialize(...)`, `register_tab(...)`, and tab factory paths across multiple mount areas.
- Chat provider addons only register metadata and callable handlers; shell mode stores those handlers but never calls them.

Important:

- The shell provides no replay, sensory, visual reply, model, audio, or engine host services yet, except a metadata-only `qt.chat_providers` registry stub.
- Buttons that require absent host services either no-op or affect only addon-local shell state.
- Addon instances are kept alive for the shell window lifetime and cleaned up when the shell exits.
- Provider model-list, connection-check, completion, and stream handlers are not invoked in shell mode.
- Addons that import `engine.py`, touch clipboard state, call network/model/audio paths during render, or expose subprocess-heavy workflows remain placeholder-only for now.

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

- `left_tabs`: static `Hotkeys` overlaps the `nc.hotkeys` addon target.
- `left_tabs`: static `Chat Player` overlaps the live-mounted `nc.chat_session_player` addon.
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

The next safe phase should be one of:

1. Decide which static duplicate candidates should be replaced by live addon mounts.
2. Add shell-only console/chat local controls that do not touch files or runtime state.
3. Add another carefully scoped addon host-service stub, but only when the addon can render without runtime/network/model calls.

Do not connect engine lifecycle, audio capture, TTS generation, transcription, or image generation in the same phase as real addon mounting.
