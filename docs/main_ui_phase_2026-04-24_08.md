# main.ui Phase Report - 2026-04-24 - 08

This phase started Phase 5 by introducing an opt-in real `main.ui` runtime path instead of keeping `main.ui` limited to shell preview only.

## Objective

Create an initial `--ui-real main.ui` mode that:

1. opens the real Designer `main.ui` window
2. keeps the existing Python-built `CompanionQtMainWindow` as the real runtime owner
3. routes the visible Phase 5 controls through the real runtime instead of shell-local preview helpers
4. keeps the stable default startup path unchanged

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_08.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Added an opt-in `--ui-real main.ui` launcher

`qt_app.py` now recognizes:

```powershell
python qt_app.py --ui-real main.ui
```

and a non-interactive smoke variant:

```powershell
python qt_app.py --ui-real main.ui --runtime-smoke
```

The stable default remains:

```powershell
python qt_app.py
```

### 2. Added a hidden-backend runtime bridge for the first real `main.ui` slice

`qt_app.py` now includes `MainUiRealRuntimeBridge`.

That bridge:

- loads the real `main.ui` window through `QtUiTools`
- creates a hidden `CompanionQtMainWindow` as the actual runtime owner
- keeps the old runtime, addon manager, and shutdown behavior in one place
- mirrors the hidden backend console/chat/status into the Designer window

This avoids pretending that `main.ui` already owns the entire runtime directly.

### 3. Wired the first real runtime-backed controls

The Phase 5 bridge now routes these visible controls into the real runtime:

- engine lifecycle buttons
- runtime action buttons
- chat-context buttons
- model refresh trigger
- push-to-talk hold/release
- core combo/checkbox/spin/line-edit state sync for the first visible runtime slice

This is runtime-backed behavior, not shell-local preview behavior.

### 4. Kept the unsafe or still-duplicate Designer surfaces deferred

The bridge explicitly leaves some surfaces deferred in this first real mode:

- chat edit-mode apply/cancel flow
- static Audio Story duplicate controls in the Designer file
- Dry Run start/stop/apply controls in the Designer file
- provider-specific runtime editors that still live in the hidden backend window

Those controls are disabled with Phase 5 tooltips instead of pretending they are already migrated.

### 5. Hardened startup for the current validation environment

This pass also removed a few import-time blockers that prevented the new mode from starting cleanly in the current checkout environment:

- `cv2` import is now optional at top-level startup
- Flask/API startup is now optional when Flask is unavailable
- the unicode-safe stdout/stderr fallback now runs before the heavy runtime imports, so `engine` startup logging no longer crashes on cp1252-style terminals

These changes are startup resilience only. They do not claim that those optional dependencies are unnecessary for the runtime features that actually use them.

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
- shell smoke in this repo-local venv now also reports `Addon mount placeholders: none`
- `--ui-real main.ui --runtime-smoke` now starts the hidden backend runtime window, loads the real Designer window, reports the bound Phase 5 controls, and shuts down cleanly

Observed `--ui-real --runtime-smoke` summary in this pass:

- hidden backend runtime window: `yes`
- lifecycle buttons present: `btn_start_engine`, `btn_stop_engine`, `btn_reset_chat`
- runtime action buttons present: `btn_regenerate`, `btn_retry`, `btn_pause`, `btn_skip`, `btn_skip_user`
- chat-context buttons present: `chat_quick_save_button`, `chat_quick_load_button`, `btn_save_chat_session`, `btn_load_chat_session`, `btn_reset_chat_session`
- console/chat mirroring bound: `yes`

## What Phase 5 Solved Here

- there is now a real opt-in `--ui-real main.ui` mode
- the Designer window can now talk to the real runtime through the hidden legacy backend instead of only shell-local preview helpers
- console/chat/status can now mirror real runtime state into `main.ui`
- shutdown behavior still reuses the existing `CompanionQtMainWindow` cleanup path

## What Is Still Not Real `main.ui` Ownership Yet

- provider-specific chat runtime editors still live in the hidden backend
- addon-owned runtime surfaces are still not re-mounted directly into the real `main.ui` window
- the static Designer Audio Story duplicate surface is still deferred
- chat edit-mode mutation is still legacy-owned
- this pass wires engine lifecycle through the real runtime, but visible manual initialize/terminate testing in `--ui-real` is still the next check

So this phase created the opt-in real mode, but not full runtime parity.

## Next Phase

Next recommended target:

```text
Continue Phase 5 by manually verifying INIT/TERMINATE in --ui-real main.ui, then start moving provider/addon-owned runtime surfaces out of the hidden backend, beginning with chat runtime/provider fields and operational-view live tabs.
```
