# main.ui Phase Report - 2026-04-24 - 19

This phase continued Phase 6 by moving the remaining visible profile and utility widgets in `--ui-real` away from passive generic bridge sync and into explicit runtime-backed ownership.

## Objective

Convert the final visible non-addon control group called out after Phase 18:

1. chunking/profile selection widgets
2. Dry Run utility fields
3. MuseTalk loop fade and visual-reply model editing

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_19.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Remaining profile/utility widgets now use explicit real-mode handlers

The real Designer controls:

- `chunking_profile_combo`
- `performance_profile_combo`
- `dry_run_target_spin`
- `dry_run_auto_replies_checkbox`
- `musetalk_loop_fade_spin`
- `visual_reply_model_edit`

now bind through dedicated `MainUiRealRuntimeBridge` handlers instead of the passive generic combo/checkbox/spin/line-edit listeners.

### 2. Existing backend runtime behavior now runs through the explicit bridge path

For the widgets that already had concrete backend behavior:

- `musetalk_loop_fade_spin` still drives `on_musetalk_loop_fade_changed`
- `visual_reply_model_edit` still drives `on_visual_reply_model_changed`
- Dry Run utility widgets still persist through the backend session-save path

The bridge now intentionally syncs the real Designer widget into the hidden backend owner first, then lets the backend runtime callback or save path execute through the same route the legacy UI already uses.

### 3. Profile selection now has an explicit frontend refresh path

`chunking_profile_combo` and `performance_profile_combo` were previously still relying on the broad passive combo listener.

This phase gives them their own real-mode handlers and refresh cycle so profile selection state is owned explicitly by the bridge instead of piggybacking on generic sync.

### 4. Added explicit frontend refresh and enabled-state mirroring for this group

After these profile/utility handlers run, the bridge now performs the same staged frontend refresh used by the other runtime slices so the real Designer surface stays aligned with backend widget state.

Enabled-state mirroring in the real Designer window now also covers:

- `chunking_profile_combo`
- `performance_profile_combo`
- `dry_run_target_spin`
- `dry_run_auto_replies_checkbox`
- `musetalk_loop_fade_spin`
- `visual_reply_model_edit`

### 5. Removed live generic bridge wiring for this control group

The passive generic frontend-to-backend bridge binding now skips:

- `chunking_profile_combo`
- `performance_profile_combo`
- `dry_run_target_spin`
- `dry_run_auto_replies_checkbox`
- `musetalk_loop_fade_spin`
- `visual_reply_model_edit`

That means the visible non-addon profile/utility control group no longer depends on the broad generic listener path in `--ui-real`.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

Observed result:

- `py_compile` passed
- `--validate-ui main.ui` still reports `Result: READY for the checked Phase 1 binding prerequisites.`
- shell smoke still reports `Heavy engine imported: no`
- shell smoke still reports `Addon mount placeholders: none`
- shell smoke still ends `Result: READY for the checked shell binding surface.`
- runtime smoke still reports:
  - `Provider runtime redirected: yes`
  - `Chat/session runtime redirected: yes`
  - `Sensory runtime redirected: yes`
  - `Visual Reply runtime redirected: yes (AddonVisualReplyPanel)`

## What Phase 6 Solved Here

- the remaining visible profile/utility widgets no longer depend on passive generic bridge sync in `--ui-real`
- MuseTalk loop fade and visual-reply model editing now follow the same explicit bridge pattern as the other migrated runtime control groups
- Dry Run utility field changes now go through a dedicated real-mode path instead of the broad generic widget listeners
- the visible non-addon generic-sync cleanup pass is now complete for the control groups called out in Phase 18

## What Still Remains

The remaining `--ui-real` cleanup is now mostly static duplicate or placeholder Designer surfaces that still exist in `main.ui` even though the live runtime/addon surface is mounted elsewhere.

That includes things like:

- the static duplicate Audio Story and Visual Reply Designer surfaces already replaced by adopted runtime tabs or panels
- placeholder-only Designer surfaces kept for addon/runtime mount points
- any later bridge cleanup needed to make those static remnants explicitly non-targets rather than just ignored

## Next Phase

Next recommended target:

```text
Audit the remaining static duplicate and placeholder Designer surfaces in --ui-real, mark the non-targets explicitly, and then move to manual runtime parity testing for the workflows already migrated.
```
