This pass documented and cleaned up the remaining static duplicate and preview-only Designer surfaces that are intentionally not the live runtime owner in `--ui-real`.

## Objective

Make the remaining duplicate/preview `main.ui` surfaces explicit non-targets instead of leaving them in an ambiguous “maybe wire later” state.

## What Was Left

After the mount-wrapper fix in Phase 20, the remaining work was no longer missing bridge objects.

What remained was the set of addon-owned placeholder Designer surfaces that are still intentionally stored in `main.ui` for Qt Creator and shell preview purposes, but are not the live owner in `--ui-real`.

Examples:

- `audio_story_mode_tab`
- `host_settings_visuals_tab`
- `host_settings_story_visuals_tab`
- `tts_chatterbox_tab`
- `tts_pockettts_tab`
- the legacy Visual Reply dock widget after live panel replacement

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-26_21.md`

## Changes Made

### 1. Validator/report wording now treats these surfaces as intentional non-targets

The `main.ui` validator output no longer describes these addon-owned Designer remnants as something to “keep ... until later binding”.

It now reports them as:

```text
Addon-owned preview/non-target UI intentionally present in main.ui
```

That matches the current architecture more accurately.

### 2. Added explicit `--ui-real` cleanup for preview-only root surfaces

`MainUiRealRuntimeBridge` now runs a cleanup pass after runtime redirection and tab adoption.

If a known placeholder root survives after the live runtime/addon surface has been mounted, the bridge now:

- marks it as preview-only
- renames it to a `_legacy` object name where appropriate
- disables it
- hides it
- attaches a tooltip/whatsthis note explaining that it is not the live runtime owner

This applies only when the corresponding live runtime/addon surface is actually present.

## Validation Run

Executed from the repo-local virtualenv in this checkout:

```powershell
.\.venv\Scripts\python.exe -m py_compile qt_app.py
.\.venv\Scripts\python.exe qt_app.py --validate-ui main.ui
.\.venv\Scripts\python.exe qt_app.py --ui-shell main.ui --shell-smoke
.\.venv\Scripts\python.exe qt_app.py --ui-real main.ui --runtime-smoke
```

## Result

Observed results after the cleanup:

- `py_compile` passed
- `--validate-ui main.ui` still reports:
  - `Dynamic Mount Points: OK`
  - `Stable Runtime Controls: OK`
  - `Result: READY for the checked Phase 1 binding prerequisites.`
- `--ui-shell main.ui --shell-smoke` still reports:
  - `Result: READY for the checked shell binding surface.`
- `--ui-real main.ui --runtime-smoke` still reports:
  - `Provider runtime redirected: yes`
  - `Chat/session runtime redirected: yes`
  - `Sensory runtime redirected: yes`
  - `Visual Reply runtime redirected: yes (AddonVisualReplyPanel)`

## What This Solved

- the remaining static Designer addon placeholders are now explicitly treated as preview-only non-targets
- `--ui-real` no longer leaves surviving placeholder roots ambiguous if a live runtime owner has already replaced them
- the validator language now matches the real integration state instead of implying more live bridge work is still pending for those remnants

## What Still Remains

After this pass, the remaining work is mostly manual runtime parity and visual cleanup, not unresolved bridge ownership:

- verify that the live addon/runtime owners fully match the intended UX
- remove or redesign placeholder Designer surfaces later only if you decide they are no longer useful in Qt Creator preview work
