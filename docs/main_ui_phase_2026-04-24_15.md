# main.ui Phase Report - 2026-04-24 - 15

This phase continued Phase 6 by moving the remaining visible chat/session flow controls in `--ui-real` away from passive bridge syncing and into explicit runtime-backed ownership.

## Objective

Promote the visible chat/session controls in the real Designer window from generic bridge sync to explicit runtime-backed behavior:

1. redirect backend chat/session widget ownership to the real Designer widgets
2. bind the visible chat/session controls through dedicated real-mode runtime handlers
3. remove the live generic bridge path for those controls and record what still remains after that slice

## Files Changed

- `qt_app.py`
- `docs/main_ui_phase_2026-04-24_15.md`
- `docs/main_ui_plan_continuation_2026-04-23.md`
- `docs/main_ui_integration_status.md`
- `docs/main_ui_handover_2026-04-23.md`

## Changes Made

### 1. Redirected chat/session runtime ownership to the real Designer widgets

`MainUiRealRuntimeBridge` now assigns the backend chat/session owner to the frontend `main.ui` widgets for:

- `allow_proactive_checkbox`
- `require_first_user_checkbox`
- `listen_idle_window_spin`
- `proactive_delay_spin`
- `chat_context_window_spin`
- `stored_chat_history_limit_spin`
- `chat_overflow_policy_combo`
- `chat_session_hint`
- `system_prompt_text`

That means backend runtime hint refreshes and later runtime reads now target the real Designer widgets directly instead of only a hidden-backend copy.

### 2. Added explicit real-mode handlers for the visible chat/session controls

The bridge now binds dedicated runtime handlers for:

- proactive replies enable
- first-user gate
- idle wait window
- proactive delay
- chat context window
- stored chat history limit
- overflow policy
- system prompt editing

The setting widgets now call the backend runtime handlers directly, and the bridge refreshes the frontend session hint/status after those runtime calls.

### 3. Added debounced system-prompt runtime commits

`system_prompt_text` never had a dedicated runtime callback in the legacy bridge path. This phase added a small bridge-side debounce timer so the real Designer editor now writes `system_prompt` into runtime config and saves session state without relying on generic copy-sync.

### 4. Removed live generic bridge wiring for this control group

The live generic bridge path now skips these chat/session widgets:

- `chat_overflow_policy_combo`
- `allow_proactive_checkbox`
- `require_first_user_checkbox`
- `chat_context_window_spin`
- `stored_chat_history_limit_spin`
- `listen_idle_window_spin`
- `proactive_delay_spin`

That leaves this slice on a cleaner explicit runtime path in `--ui-real`.

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
- runtime smoke now reports `Chat/session runtime redirected: yes`
- runtime smoke still reports:
  - `Provider runtime redirected: yes`
  - `Sensory runtime redirected: yes`
  - `Visual Reply runtime redirected: yes (AddonVisualReplyPanel)`

## What Phase 6 Solved Here

- the visible chat/session settings no longer rely on generic live bridge sync in `--ui-real`
- backend chat/session ownership for this slice now points at the real Designer widgets
- the real Designer session hint is now refreshed by explicit runtime handlers
- `system_prompt_text` now has an explicit real-mode runtime commit path

## What Still Remains

Visible non-addon controls still using generic bridge sync in `--ui-real` are now mostly outside the chat/session slice:

- response-length controls such as `limit_response_checkbox` and `max_response_tokens_spin`
- host/input/runtime selection controls such as audio-device, input-mode, stream-mode, engine, and TTS backend combos
- avatar/body/VaM selection fields such as `voice_combo`, `body_combo`, `emotion_combo`, `live_sync_checkbox`, and the visible VaM text/spin fields
- profile and remaining utility controls such as `chunking_profile_combo`, `performance_profile_combo`, `dry_run_target_spin`, `dry_run_auto_replies_checkbox`, and `musetalk_loop_fade_spin`
- static Designer duplicate/placeholder surfaces that still exist in `main.ui` even though live addon/runtime tabs are now mounted elsewhere

## Next Phase

Next recommended target:

```text
Finish the visible non-addon ownership audit in --ui-real, then convert the remaining generic-sync bridge-owned controls by category, starting with response-length and host/input/runtime selection controls.
```
