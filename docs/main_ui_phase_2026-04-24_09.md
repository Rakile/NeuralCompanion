# main.ui Phase Report - 2026-04-24 - 09

This phase continued Phase 5 by moving the first provider/addon-owned runtime surfaces out of the hidden backend and into the real Designer window.

## Objective

Take the first runtime-owned UI surfaces that still lived only in the hidden `CompanionQtMainWindow` and make them visible in `--ui-real main.ui`:

1. move chat-provider runtime editors into the real Designer layouts
2. move addon-owned runtime tabs into the real Designer tab widgets
3. keep the hidden backend as the runtime owner while reducing how much UI it still keeps for itself

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_09.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Redirected chat-provider runtime editors into the real Designer surface

`MainUiRealRuntimeBridge` now redirects the backend chat-provider form writers into the real `main.ui` widgets instead of leaving them inside the hidden backend window.

That redirect now targets:

- `chat_provider_fields_widget`
- `chat_provider_fields_layout`
- `chat_provider_generation_fields_widget`
- `chat_provider_generation_fields_layout`

Effect:

- changing chat providers in `--ui-real main.ui` now renders the real provider-specific runtime fields into the Designer window
- generation-field editors also render into the Designer window
- the hidden backend still owns the runtime logic, but it no longer keeps this provider-editor surface for itself

### 2. Adopted backend addon tabs into the real Designer tabs

The bridge now moves already-mounted backend addon widgets out of the hidden backend tab widgets and into the real Designer tab widgets.

Adopted in this pass:

- `host_settings_tabs`: `Visuals`, `Story Visuals`
- `right_tabs`: `Audio Story Mode`
- `musetalk_tabs`: `Preprocess`, `Loop Authoring`
- `tts_runtime_addon_tabs`: `Chatterbox`, `Gemini TTS`, `PocketTTS`

Effect:

- these runtime addon surfaces are now visible in the real Designer window
- the hidden backend still owns the controllers/runtime, but those widgets are no longer visually trapped inside the hidden legacy window

### 3. Repointed follow-up runtime callbacks to the real tab widgets

After adopting the tabs, the bridge now repoints the backend runtime tab references and callback wiring so they continue to work against the real Designer widgets:

- right-tab change handling
- TTS runtime tab change handling
- tab-height syncing for host-settings and sensory tab groups

This keeps the moved surfaces live instead of making them one-time copies.

### 4. Mirrored provider/runtime labels into the real Designer surface

The bridge now mirrors the backend provider/runtime summary labels back into the real `main.ui` labels/group titles so the moved provider surface reads correctly inside the Designer window.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Observed result:

- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- shell smoke still reports `Addon mount placeholders: none` in the repo-local `.venv`
- `--ui-real main.ui --runtime-smoke` now reports provider-runtime redirection and the adopted runtime tab set

Observed `--ui-real --runtime-smoke` summary in this pass:

- provider runtime redirected: `yes`
- adopted runtime tabs:
  - `host_settings_tabs`: `Visuals`, `Story Visuals`
  - `right_tabs`: `Audio Story Mode`
  - `musetalk_tabs`: `Preprocess`, `Loop Authoring`
  - `tts_runtime_addon_tabs`: `Chatterbox`, `Gemini TTS`, `PocketTTS`

## What Phase 5 Solved Here

- provider-specific chat runtime editors are no longer hidden-backend-only
- several addon-owned runtime tabs are no longer hidden-backend-only
- `--ui-real main.ui` now shows more real runtime UI and fewer shell-like placeholders

## What Is Still Not Fully Moved Yet

- top-level addon tabs like `Chat Player` / `Hotkeys` were not part of this adoption slice
- sensory/additional runtime addon surfaces are not yet all adopted into the real Designer window
- the static Designer Audio Story duplicate controls are still deferred even though the real Audio Story addon tab is now visible
- chat edit-mode mutation is still legacy-owned
- manual INIT/TERMINATE verification in the real Designer window is still the next manual runtime check

So this pass materially reduced the hidden-backend-only UI surface, but it did not eliminate the hidden backend.

## Next Phase

Next recommended target:

```text
Continue Phase 5 by manually verifying INIT/TERMINATE in --ui-real main.ui, then move the remaining top-level and sensory runtime addon surfaces out of the hidden backend and reduce the bridge's remaining hidden-backend-owned controls.
```
