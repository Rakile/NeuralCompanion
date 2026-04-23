# main.ui Integration Handover - 2026-04-23

This handover is for continuing the NeuralCompanion `main.ui` transition while keeping the existing Python-built UI stable.

## Repositories And Folders

- Developer working folder: `E:\Tools\Python_Scripts\NeuralInterface`
- Git sync folder: `D:\tools\python_scripts\NeuralInterface_GIT`
- Designer branch reference folder: `D:\tools\python_scripts\NeuralCompanion-NC_main.ui`
- Known working Python interpreter for Qt shell checks: `E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe`

Current rule:

- Edit and validate in the developer folder first.
- Copy only validated files into the Git sync folder.
- Validate again in the Git sync folder.
- Commit and push from the Git sync folder.

## Current State

The stable app remains:

```powershell
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py
```

The Designer UI shell remains experimental:

```powershell
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui
```

The shell smoke check is:

```powershell
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
```

The shell currently:

- Loads `main.ui`.
- Validates stable object names.
- Live-mounts the allowlisted low-risk addons.
- Replaces static duplicate addon tabs where safe.
- Binds Chat Runtime from chat provider addon metadata.
- Binds Avatar Engine from avatar provider addon metadata.
- Binds TTS Backend from TTS addon service metadata.
- Binds preset preview, tutorials, chat context, console/chat local controls, lifecycle preview buttons, and Operational View preview actions.
- Keeps engine, audio, model loading, transcription, image generation, and avatar runtimes disconnected.
- Must keep reporting `Heavy engine imported: no` in shell smoke.

## Current Safety Boundary

Do not make `main.ui` the default UI yet.

Do not connect real engine start/stop as a side effect of shell preview work.

Do not let shell smoke import `engine.py`.

Do not connect the following in the same phase as broad UI binding:

- microphone capture
- Whisper/STT
- Chatterbox/PocketTTS/Gemini TTS generation
- MuseTalk worker
- VaM/VSeeFace/MuseTalk avatar runtime
- image generation
- provider model refresh/completion/stream calls
- chat context file writes
- preset writes/deletes

The current goal is to keep turning static Designer controls into host-service backed controls without starting runtime systems.

## Required Validation After Each Phase

Run these from the developer folder:

```powershell
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
```

Expected shell smoke must include:

```text
Heavy engine imported: no
Result: READY for the checked shell binding surface.
Addon mount placeholders: none
```

Before pushing, copy changed files to the Git sync folder, then run the same validation there.

## One-Button Autonomous Prompt For Codex

Use this prompt if you want Codex to work for a long unattended run:

```text
You are continuing the NeuralCompanion main.ui transition.

Read docs/main_ui_integration_status.md and docs/main_ui_handover_2026-04-23.md first.

Work in E:\Tools\Python_Scripts\NeuralInterface. Do not edit D:\tools\python_scripts\NeuralInterface_GIT until a phase validates.

Goal: move main.ui toward becoming the real UI without breaking the current Python-built UI.

Rules:
- Keep python qt_app.py as the stable default.
- Keep --ui-shell main.ui as shell-only until explicitly ready for real runtime.
- Keep shell smoke reporting Heavy engine imported: no.
- Use additive host-service facades and shell-local bindings first.
- Do not connect real engine/audio/avatar/model/image runtime in the same phase as broad UI mounting.
- Run py_compile, --validate-ui, and --ui-shell --shell-smoke after every phase.
- If a phase validates in the developer folder, copy only the changed files into D:\tools\python_scripts\NeuralInterface_GIT, validate there, commit, and push.
- If a validation fails, stop and fix that phase before continuing.
- Never use git reset --hard or destructive checkout.

Suggested next work:
1. Finish shell-local bindings for remaining static Host/Core controls.
2. Add real host-service contracts for controls that need normal-app support.
3. Move static Designer tabs that duplicate addon-owned UI behind live addon mount boundaries.
4. Only after shell boundaries are clean, create an opt-in real main.ui runtime mode.
5. Keep the normal Python-built UI working after each commit.

At the end, provide:
- commits pushed
- files changed
- validations run
- what is still shell-local
- what can be tested manually next
```

## Roadmap To Full main.ui Integration

### Phase 1 - Preserve The Shell Boundary

Status: mostly complete.

Finish these if they are not already done:

- Keep all shell smoke checks passing.
- Keep `Heavy engine imported: no`.
- Keep addon placeholder report clean.
- Keep Designer static duplicate candidates clean.
- Keep normal app startup unchanged.

Completion criteria:

- `python qt_app.py` works exactly as before.
- `--ui-shell main.ui --shell-smoke` passes.
- `--ui-shell main.ui` opens a visual shell with no runtime startup.

### Phase 2 - Bind Remaining Static Host/Core Controls In Shell Mode

Purpose:

Make the Designer shell reflect real saved state and addon metadata without mutating runtime state.

Likely controls:

- `audio_input_device_combo`
- `audio_output_device_combo`
- `input_mode_combo`
- `input_role_combo`
- `stream_mode_combo`
- `musetalk_vram_combo`
- `musetalk_avatar_pack_combo`
- visual reply core fields if still static
- chat context window and overflow policy controls

Implementation style:

- Add shell-local binding helpers in `qt_app.py`.
- Use saved `qt_session.json`, addon metadata, or filesystem discovery.
- Do not call runtime handlers.
- Update shell runtime status preview when shell-local values change.

Completion criteria:

- Shell preview feels interactive but does not save.
- Shell smoke still reports `Heavy engine imported: no`.

### Phase 3 - Promote Host Services As The UI Boundary

Purpose:

Stop `main.ui` from needing direct knowledge of `CompanionQtMainWindow` internals.

Existing service names already started:

- `qt.runtime_status`
- `qt.model_refresh`
- `qt.engine_lifecycle`
- `qt.runtime_controls`
- `qt.chat_context`
- `qt.chat_replay`
- `qt.tutorials`
- `qt.dialogs`
- `qt.sensory`
- `qt.avatar_providers`

Likely additional service boundaries:

- `qt.audio_devices`
- `qt.input_settings`
- `qt.tts_backends`
- `qt.avatar_runtime_settings`
- `qt.preset_store`
- `qt.chat_view`
- `qt.console_view`
- `qt.visual_reply_dock`

Implementation style:

- Add shell-safe facades before real bindings.
- Add normal-app service implementations in `core/addons/qt_host_services.py` only when needed.
- Keep service methods small and explicit.

Completion criteria:

- Designer binding code calls service contracts instead of direct runtime fields.
- The normal Python-built UI can expose the same services.
- Shell service implementations remain no-op or preview-only.

### Phase 4 - Convert Static Tabs Into Addon-Owned Tabs

Purpose:

Remove fake/static Designer copies of tabs that are actually addon-owned.

Already live-mounted in shell:

- Chat Player
- Hotkeys
- Visual Reply
- Story Visuals
- Audio Story Mode shell adapter
- Chatterbox
- PocketTTS
- Gemini TTS
- Loop Authoring
- MuseTalk Preprocess shell adapter
- Screen/Webcam/Clipboard/Heart Rate sensory tabs

Remaining care points:

- Audio Story Mode real controller imports runtime-heavy modules.
- MuseTalk Preprocess real controller imports runtime-heavy modules.
- Some static Designer tabs may still exist as placeholders and should only be removed after the live addon surface is reliable.

Completion criteria:

- No duplicate static/addon tabs.
- Addon tabs mount through `addon.json` and `register_tab(...)`.
- Disabled addons disappear from the shell on next launch.
- Static tabs are only used for core UI, not addon-owned UI.

### Phase 5 - Split Runtime-Heavy Addons From Renderable UI State

Purpose:

Allow faithful Designer rendering of heavy addons without importing or starting runtime subsystems.

Priority candidates:

- Audio Story Mode
- MuseTalk Preprocess
- any future addon that creates media players, workers, models, network calls, or filesystem side effects in `build_tab()`

Pattern:

- Keep `main.py` as addon entry.
- Split UI state/controller construction from runtime action execution.
- Keep model/worker/audio/image imports behind action methods, not module import or tab build.
- In shell mode, render the same controls but route actions to shell-safe services.

Completion criteria:

- Shell can mount the real-looking tab.
- Shell smoke still avoids heavy imports.
- Normal app can still execute the runtime actions.

### Phase 6 - Build A Real main.ui Runtime Window Behind An Explicit Flag

Purpose:

Start turning `main.ui` from shell preview into an alternative real UI.

Suggested command:

```powershell
python qt_app.py --ui-real main.ui
```

Requirements:

- This remains opt-in.
- Normal `python qt_app.py` remains the old stable UI.
- Real runtime binding happens through host services.
- Start/stop/reset buttons call the same tested normal-app lifecycle paths.
- Console/chat widgets receive live updates.
- Runtime status labels update from `qt.runtime_status`.

Completion criteria:

- `--ui-real main.ui` can initialize and terminate the engine.
- It can run one simple text/voice chat cycle.
- It can stop without leaked GPU workers.
- Normal UI still works.

### Phase 7 - Wire Core Runtime Workflows One At A Time

Do not wire everything at once.

Recommended order:

1. Engine initialize/terminate/reset.
2. Console and chat live rendering.
3. Push-to-talk and voice activation.
4. Chat provider/model refresh.
5. Preset load/save/delete.
6. TTS backend selection and settings persistence.
7. Avatar engine selection and startup/shutdown.
8. Visual Reply dock actions.
9. Vision/sensory hidden-loop controls.
10. Audio Story Mode runtime actions.
11. MuseTalk preprocess/runtime actions.

Each item needs:

- normal UI comparison test
- `--ui-real main.ui` test
- shutdown/leak test when runtime-heavy systems are involved

### Phase 8 - Make main.ui The Default

Only consider this when:

- `--ui-real main.ui` has feature parity for the main workflows.
- Normal chat sessions work with None, VaM, MuseTalk, and VSeeFace where available.
- TTS backends work with Chatterbox, PocketTTS, and Gemini TTS.
- Chat providers work with LM Studio, OpenAI, xAI, and Claude where credentials exist.
- Preset/session dirty-state behavior matches the old UI.
- Addon enable/disable behavior remains session-only and restart-aware.
- Shutdown releases TTS/STT/avatar GPU memory as expected.
- Audio Story Mode and Visual Reply workflows survive realistic testing.

Then:

- Keep an escape hatch flag for the old Python-built UI for at least one release.
- Document migration and known gaps.
- Tag a release checkpoint.

## Testing Matrix

Minimum manual smoke after any runtime phase:

- Start app.
- Load a preset.
- Initialize with Avatar Engine `None`.
- Send one push-to-talk message.
- Terminate and confirm GPU memory returns close to baseline.
- Repeat with VaM if available.
- Repeat with MuseTalk if available.
- Open Visual Reply and confirm no blank image regression.
- Open Audio Story Mode and confirm import/transcribe/play still works if touched.

Automated checks:

```powershell
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
```

Optional real UI smoke, only once `--ui-real` exists:

```powershell
E:\Tools\Python_Scripts\ChatterBoxViz\.venv\Scripts\python.exe qt_app.py --ui-real main.ui
```

## Known Risks

- `qt_app.py` is still very large and contains both legacy UI and shell transition code.
- `engine.py` remains runtime-sensitive.
- Some addons still need shell adapters because their real controllers import runtime-heavy modules.
- Broad real runtime wiring can easily reintroduce the push-to-talk and shutdown race conditions previously fixed.
- Static `main.ui` controls can drift from addon-owned UI unless live addon mounting remains the source of truth.

## Best Next Task

The next safest task is:

```text
Bind remaining Host/Core shell controls from saved session and addon metadata, keeping them shell-local and updating the shell runtime-status line. Do not connect real runtime actions.
```

After that:

```text
Add one new normal-app host service at a time for the controls that will eventually need real `main.ui` runtime behavior.
```

