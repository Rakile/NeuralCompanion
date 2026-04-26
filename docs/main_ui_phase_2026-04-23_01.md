# main.ui Phase Report - 2026-04-23 - 01

This phase started from the audited state where `main.ui` had a healthier shell path, but a large remaining integration surface.

## Objective

Do two safe things without crossing the runtime boundary:

1. Expand shell-local Host/Core bindings for controls that were still passive or legacy-only.
2. Add one new host-service boundary that the future real `main.ui` runtime can use instead of direct widget access.

## Files Changed

- `qt_app.py`
- `core/addons/qt_host_services.py`

## Changes Made

### 1. Expanded shell-local Host/Core bindings

The shell path now binds more Host/Core controls as preview-only controls instead of leaving them as passive session-populated widgets.

Newly bound shell-local controls in this phase:

- `allow_proactive_checkbox`
- `require_first_user_checkbox`
- `listen_idle_window_spin`
- `proactive_delay_spin`
- `limit_response_checkbox`
- `max_response_tokens_spin`
- `sensory_feedback_source_combo`
- `sensory_feedback_interval_spin`
- `sensory_pingpong_checkbox`
- `sensory_allow_hidden_proactive_checkbox`
- `sensory_allow_hidden_visual_checkbox`
- `sensory_pingpong_history_spin`

These remain shell-local:

- no runtime systems are started
- no chat/session files are written
- no sensory capture loop is started
- no provider/model/image runtime action is triggered

### 2. Added a new host-service boundary

Added `qt.input_settings` in both service maps:

- shell-safe service in `qt_app.py`
- normal-app service in `core/addons/qt_host_services.py`

Purpose:

- provide a durable boundary for input/session behavior controls
- reduce future dependence on direct `CompanionQtMainWindow` field access
- create a reusable contract for a future `--ui-real main.ui` mode

Current service coverage:

- audio input/output labels/options
- input mode
- input role
- stream mode
- proactive reply settings
- idle/proactive delay settings
- chat context window
- stored history limit
- chat overflow policy
- response length toggle
- max response tokens

The service is additive in this phase. It is registered and validated, but existing addon/controller code is not forced onto it yet.

## Validation Run

Executed:

```powershell
python -m py_compile qt_app.py core\addons\qt_host_services.py
python qt_app.py --validate-ui main.ui
python qt_app.py --ui-shell main.ui --shell-smoke
```

Observed result:

- `Heavy engine imported: no`
- `Addon mount placeholders: none`
- `Result: READY for the checked shell binding surface.`

## Current Snapshot After This Phase

Interactive-widget audit after this phase:

- `380` interactive `main.ui` widgets
- `50` match both shell bindings and legacy runtime names
- `28` are shell-only bindings
- `47` are still legacy-runtime-only
- `255` are still neither, but that includes labels, group boxes, placeholder surfaces, and addon-owned duplicate/static Designer controls

Remaining legacy-only groups still worth targeting:

- Persona/body/VaM controls
- Chunking/profile controls
- Dry-run controls
- Some TTS/session-adjacent controls
- Push-to-talk/runtime-adjacent controls

## What Is Still Shell-Local

- engine lifecycle in `--ui-shell`
- runtime control actions in `--ui-shell`
- model refresh in `--ui-shell`
- chat context file operations in `--ui-shell`
- sensory capture/runtime behavior in `--ui-shell`
- image generation and runtime Visual Reply actions in `--ui-shell`

## What Still Does Not Exist

- no `--ui-real main.ui` mode
- no full runtime-backed `main.ui` window
- no default switch away from the Python-built UI

## Next Phase

Next recommended phase:

```text
Migrate one remaining legacy-only Host/Core group into shell-safe `main.ui` bindings and only then add or extend a matching host-service boundary if that group needs a durable runtime contract.
```

Recommended first target group:

- chunking/profile or persona/body/VaM controls

Reason:

- they are still legacy-only
- they are structurally separate from the heaviest runtime systems
- they can be migrated without immediately forcing a `--ui-real` runtime mode
