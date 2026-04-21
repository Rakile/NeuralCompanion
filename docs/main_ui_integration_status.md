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

This mode does not import addon modules, instantiate addon controllers, register services, start Flask, or connect engine lifecycle actions.

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

This mode does not start runtime systems or mutate saved state.

## Current Safety Boundaries

Intentionally not connected yet:

- Engine start.
- Engine stop.
- Reset chat memory.
- Addon initialization.
- Addon widget mounting.
- TTS/STT/audio runtime.
- Image generation.
- Transcription.
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

## Current Addon Discovery

The shell smoke report reads addon manifests and statically reports likely mount targets.

Examples:

- `top_level` -> `left_tabs`
- `host_settings` -> `host_settings_tabs`
- `musetalk` -> `musetalk_tabs`
- `tts_runtime` -> `tts_runtime_addon_tabs`
- `vision_source` -> `sensory_feedback_tabs`
- `operational_view` -> `OperationalViewDock`
- chat provider addons -> `chat_provider_combo`

No addon Python module is imported during this discovery.

## Recommended Next Step

The next safe phase should be one of:

1. Add a shell-local visual report panel or label for addon discovery results.
2. Add read-only mount placeholders showing which addons would mount where.
3. Add one carefully scoped real addon mount path, but only for a low-risk display-only addon.

Do not connect engine lifecycle, audio capture, TTS generation, transcription, or image generation in the same phase as addon mounting.
