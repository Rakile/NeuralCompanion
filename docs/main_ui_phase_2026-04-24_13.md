# main.ui Phase Report - 2026-04-24 - 13

This phase continued Phase 6 by moving the visible Visual Reply runtime actions out of the hidden backend ownership path and into the real Designer surface in `--ui-real`.

## Objective

Move the remaining visible non-addon Visual Reply workflow into the real `main.ui` runtime path:

1. redirect the backend Visual Reply dock/panel to the real Designer dock
2. make `Show Visual Reply` operate on the real Designer dock instead of the hidden backend dock
3. preserve the visible story/image runtime actions on that frontend panel

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_13.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Redirected the runtime Visual Reply dock into the real Designer dock

`MainUiRealRuntimeBridge` now redirects the backend Visual Reply ownership surface onto the frontend `VisualReplyDock`.

The bridge now:

- builds the live runtime panel from the addon-grade `AddonVisualReplyPanel`
- mounts that panel into the real Designer dock
- rewires backend `visual_reply_dock` / `visual_reply_panel` references to the frontend surface
- exposes `show_visual_reply_dock` on the frontend window so auto-show behavior still works from the panel state poller

### 2. Preserved the visible Designer Visual Reply controls as live runtime controls

The real frontend Visual Reply dock now keeps these visible runtime actions live:

- `btn_visual_reply`
- `visual_reply_previous_button`
- `visual_reply_load_button`
- `visual_reply_next_button`
- `visual_reply_load_current_story_button`
- `visual_reply_use_current_style_button`
- `visual_reply_caption_button`
- `visual_reply_delete_button`
- `visual_reply_clear_button`
- `visual_reply_delete_all_button`

The real panel also now owns the live status/image/storage surface instead of leaving the static Designer placeholder as the apparent owner.

### 3. Removed legacy object-name collision for the replaced Designer panel

Before swapping the runtime panel into the frontend dock, the old static Designer subtree is renamed to legacy-only object names.

That avoids duplicate object-name lookups and ensures the live runtime panel now owns:

- `visual_reply_panel`
- `visual_reply_status`
- `visual_reply_storage_label`
- the visible Visual Reply action buttons

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py core\addons\qt_host_services.py addons\audio_story_mode\controller.py addons\hotkeys\controller.py addons\visual_reply\controller.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Additional verification executed in this pass:

- offscreen frontend dock verification for the redirected Visual Reply surface
- backend `clear_visual_reply(...)` call against the redirected panel
- offscreen presence check for `visual_reply_load_current_story_button` and `visual_reply_use_current_style_button`

Observed result:

- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still reports `Addon mount placeholders: none`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- `--ui-real --runtime-smoke` now reports `Visual Reply runtime redirected: yes (AddonVisualReplyPanel)`
- offscreen verification confirmed:
  - redirected panel class: `AddonVisualReplyPanel`
  - frontend Visual Reply dock visible: `True`
  - redirected frontend status label text changed through `backend.clear_visual_reply(...)`
  - story image/style buttons are present on the live frontend panel

## What Phase 6 Solved Here

- the real Designer Visual Reply dock is now the live runtime panel in `--ui-real`
- `Show Visual Reply` now targets the Designer dock rather than the hidden backend dock
- the visible Visual Reply image/history/story actions are no longer just static Designer placeholders

## What Still Remains

- some non-addon runtime workflows in `--ui-real` still rely on hidden-backend ownership or generic bridge syncing
- sensory hidden-loop/runtime widgets still need the same level of explicit runtime ownership cleanup
- the hidden backend still owns broader cleanup and runtime orchestration

## Next Phase

Next recommended target:

```text
Continue Phase 6 by reducing the remaining hidden-backend-owned non-addon workflows in --ui-real, starting with sensory hidden-loop/runtime widgets and any remaining visible dock/button ownership gaps.
```
