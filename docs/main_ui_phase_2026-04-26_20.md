This pass documented and fixed the remaining concrete `main.ui` connection drift that appeared after the earlier Phase 6 runtime-ownership work.

## Objective

Identify the actual remaining `main.ui` connection gaps, document them clearly, and fix the ones that were structural rather than runtime-behavior issues.

## What Was Still Broken

The audit showed that the visible non-addon generic-sync migration was already complete, but `main.ui` had drifted from what `qt_app.py` expected in three specific places:

1. `chat_provider_fields_widget` was missing from the provider runtime surface.
2. `chat_provider_generation_fields_widget` was missing from the provider generation runtime surface.
3. `sensory_feedback_sources_widget` was missing from the sensory runtime surface.

In all three cases, the child layouts still existed in `main.ui`, but the named wrapper widgets did not.

That mattered because the runtime bridge in `qt_app.py` redirects ownership against those named widgets:

- provider runtime redirect: `MainUiRealRuntimeBridge._redirect_backend_provider_runtime_surface`
- sensory runtime redirect: `MainUiRealRuntimeBridge._redirect_backend_sensory_runtime_surface`

The most visible failure was the sensory runtime slice: because `sensory_feedback_sources_widget` was missing, the redirect bailed out and runtime smoke reported:

```text
Sensory runtime redirected: no
```

## Files Changed

- `main.ui`
- `docs/main_ui_phase_2026-04-26_20.md`

## Changes Made

### 1. Restored the missing provider runtime wrapper widgets in `main.ui`

Added:

- `chat_provider_fields_widget`
- `chat_provider_generation_fields_widget`

The existing `QFormLayout` objects were preserved and moved under those wrapper widgets so the bridge and validator now see the expected structure again.

### 2. Restored the missing sensory runtime wrapper widget in `main.ui`

Added:

- `sensory_feedback_sources_widget`

The existing `sensoryFeedbackSourcesWidgetLayout` was preserved and moved under that wrapper widget.

This was the structural fix needed for the sensory runtime bridge to retake ownership of the visible Designer surface in `--ui-real`.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

## Result

Observed results after the fix:

- `--validate-ui main.ui`
  - `Dynamic Mount Points: OK`
  - `Stable Runtime Controls: OK`
  - `Result: READY for the checked Phase 1 binding prerequisites.`

- `--ui-shell main.ui --shell-smoke`
  - all previously missing mount points are now present
  - `Result: READY for the checked shell binding surface.`

- `--ui-real main.ui --runtime-smoke`
  - `Provider runtime redirected: yes`
  - `Chat/session runtime redirected: yes`
  - `Sensory runtime redirected: yes`
  - `Visual Reply runtime redirected: yes (AddonVisualReplyPanel)`

## What Still Remains

After this fix, the remaining `main.ui` cleanup is no longer missing bridge mount objects.

What remains is mostly the same later-stage cleanup target already identified before:

- static duplicate Designer surfaces kept beside live addon/runtime-owned surfaces
- placeholder or preview-only Designer controls that are intentionally not the live runtime owner
- manual runtime parity testing for the migrated workflows

So this pass closes the structural bridge drift and returns the `main.ui` binding surface to a clean validated state.
