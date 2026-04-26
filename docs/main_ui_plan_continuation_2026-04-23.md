# main.ui Continuation Plan - 2026-04-23

This plan continues the `main.ui` migration from the audited state currently present in this checkout.

It does not assume that `main.ui` is already the real runtime UI. That is still false.

## Current Baseline

- Stable default app startup is still `python qt_app.py`.
- `python qt_app.py --ui-shell main.ui` is still a shell-only Designer path.
- There is now an opt-in `python qt_app.py --ui-real main.ui` runtime mode.
- The normal app still uses the Python-built `CompanionQtMainWindow`.
- The shell path must keep reporting `Heavy engine imported: no`.

Current interactive-widget audit after the latest shell-binding pass:

- `380` interactive `main.ui` widgets
- `50` match both shell bindings and legacy runtime names
- `28` are shell-only bindings
- `47` are still legacy-runtime-only
- `255` are still neither, but that bucket includes labels, group boxes, placeholder surfaces, and addon-owned duplicate/static Designer controls

## Working Rules

- Keep `python qt_app.py` as the stable default until an opt-in real `main.ui` runtime exists and validates.
- Do not connect engine start/stop, push-to-talk, STT, TTS generation, avatar runtime, image generation, or runtime-heavy addon actions in the same phase as broad shell/UI binding.
- Prefer host-service boundaries over direct `CompanionQtMainWindow` field access.
- Validate after every phase:

```powershell
python -m py_compile qt_app.py core\addons\qt_host_services.py
python qt_app.py --validate-ui main.ui
python qt_app.py --ui-shell main.ui --shell-smoke
```

- Expected shell smoke must still include:

```text
Heavy engine imported: no
Addon mount placeholders: none
Result: READY for the checked shell binding surface.
```

## Phase Sequence

### Phase 1 - Expand Shell-Local Host/Core Bindings

Status: completed in this continuation pass.

Scope:

- Finish shell-local bindings for the safe Host/Core controls that were still passive or legacy-only.
- Keep all edits shell-local and session-preview only.
- Do not start runtime systems.

Completed in this pass:

- Additional shell-local Host/Core controls were bound for proactive/session behavior, response-length settings, and sensory controls.

Documentation:

- See `docs/main_ui_phase_2026-04-23_01.md`.

### Phase 2 - Add One New Host-Service Boundary

Status: completed in this continuation pass.

Scope:

- Add one new normal-app service and one shell-safe service for a real control group.
- Register the service in both addon-host maps.
- Keep the service additive; do not force callers to use it immediately.

Completed in this pass:

- Added `qt.input_settings` service in both shell and normal-app host-service maps.

Documentation:

- See `docs/main_ui_phase_2026-04-23_01.md`.

### Phase 3 - Reduce The Remaining Legacy-Only Host/Core Surface

Status: in progress.

Primary target groups:

- Persona/body/VaM controls
- Chunking and profile controls
- Dry-run controls
- Remaining response/TTS controls that are core-owned rather than addon-owned

Rules:

- Migrate one coherent group at a time.
- Keep shell-safe behavior first.
- Add or extend host services only when the group benefits from a durable runtime boundary.

Completed so far in this phase:

- chunking/profile controls now have shell-local bindings for the visible Designer sliders
- shell-safe performance-profile refresh/load now reads `performance_profiles/*.json` directly instead of importing `dry_run`
- added `qt.performance_profiles` in both shell and normal-app host-service maps
- Dry Run controls now have shell-local preview bindings for target samples, hands-free, and recommendation preview
- added `qt.dry_run` in both shell and normal-app host-service maps
- persona text, visible VSeeFace body controls, and VaM bridge fields now have shell-local bindings
- added `qt.persona_avatar` in both shell and normal-app host-service maps
- push-to-talk and the visible Audio Story action row now have shell-local preview bindings
- added `qt.input_actions` in both shell and normal-app host-service maps

Documentation:

- `docs/main_ui_phase_2026-04-23_02.md`
- `docs/main_ui_phase_2026-04-23_03.md`
- `docs/main_ui_phase_2026-04-23_04.md`
- `docs/main_ui_phase_2026-04-23_05.md`

Completion criteria:

- The count of legacy-runtime-only interactive widgets should drop materially.
- Shell smoke remains clean.

Next target after this phase sequence:

- Begin Phase 4 with `audio_story_mode`, then `musetalk_preprocess`

### Phase 4 - Split Runtime-Heavy Addon Controllers From Renderable UI State

Status: completed for the current priority targets.

Priority targets:

- `audio_story_mode`
- `musetalk_preprocess`

Rules:

- Keep runtime imports and worker/model startup out of tab build paths.
- Preserve shell safety.

Completion criteria:

- Real-looking addon tabs can render without importing heavy runtime paths.
- Shell smoke still reports `Heavy engine imported: no`.

Completed so far in this phase:

- `audio_story_mode` no longer imports `engine`, `shared_state`, or `core.chat_providers` eagerly at controller-module load time
- `audio_story_mode` controller creation is now lazy in the addon entrypoint
- `audio_story_mode` no longer creates its media player in `build_tab()`
- a render-only `audio_story_mode` controller can now build and shut down without importing `engine`
- `musetalk_preprocess` no longer imports `engine`, `cv2`, or `musetalk_bridge` eagerly at controller-module load time
- `musetalk_preprocess` controller creation is now lazy in the addon entrypoint
- `musetalk_preprocess` can now build and tear down its tab without importing `engine`, `cv2`, or the MuseTalk bridge

Documentation:

- `docs/main_ui_phase_2026-04-24_06.md`
- `docs/main_ui_phase_2026-04-24_07.md`

Phase 4 completion note:

- both priority runtime-heavy addons now satisfy the renderable-tab boundary

### Phase 5 - Introduce An Opt-In Real main.ui Runtime Mode

Status: started in this continuation pass.

Suggested command:

```powershell
python qt_app.py --ui-real main.ui
```

Rules:

- Keep this opt-in at first.
- Route actions through host services instead of direct shell helpers.

Completion criteria:

- Engine initialize/terminate works in the new mode.
- Console/chat update paths are live.
- Shutdown still behaves correctly.

Completed so far in this phase:

- `--ui-real main.ui` now exists as an opt-in launch path
- the new mode uses a hidden `CompanionQtMainWindow` as the actual runtime owner
- lifecycle, runtime-action, chat-context, model-refresh, and push-to-talk bindings now route into the real runtime
- console/chat/status now mirror the hidden backend into the real Designer window
- automated offscreen `INIT` / `TERMINATE` verification now passes against the real runtime-backed bridge
- `--ui-real main.ui --runtime-smoke` now validates startup/shutdown of this bridge in the repo-local `.venv`
- chat-provider runtime/editor forms now render into the real Designer layouts instead of only the hidden backend
- runtime addon tabs now adopted into the real Designer window for:
  - `left_tabs`: `Hotkeys`, `Chat Player`
  - `host_settings_tabs`: `Visuals`, `Story Visuals`
  - `right_tabs`: `Audio Story Mode`
  - `musetalk_tabs`: `Preprocess`, `Loop Authoring`
  - `tts_runtime_addon_tabs`: `Chatterbox`, `Gemini TTS`, `PocketTTS`
- the sensory runtime source surface now rebuilds directly into the real Designer `sensory_feedback_tabs` and `sensory_feedback_sources_widget`

Still not complete in this phase:

- duplicate/static Designer Audio Story controls are still deferred
- duplicate/static Designer Dry Run controls are still deferred
- chat edit-mode mutation is still legacy-owned
- provider/model workflow is still partly bridge-driven rather than Designer-owned

Documentation:

- `docs/main_ui_phase_2026-04-24_08.md`
- `docs/main_ui_phase_2026-04-24_09.md`
- `docs/main_ui_phase_2026-04-24_10.md`
- `docs/main_ui_phase_2026-04-24_11.md`

### Phase 6 - Migrate Runtime Workflows One At A Time

Status: started.

Recommended order:

1. Engine initialize/terminate/reset
2. Console and chat live updates
3. Push-to-talk / input handling
4. Model refresh and provider/model workflow
5. Preset and chat-context workflows
6. TTS backend/runtime settings
7. Avatar runtime settings and startup/shutdown
8. Visual Reply runtime actions
9. Sensory hidden-loop runtime workflows
10. Audio Story Mode runtime actions
11. MuseTalk preprocess/runtime actions

Completed so far in this phase:

- chat edit mode is now live in `--ui-real`
- Dry Run start/stop/apply controls are now live in `--ui-real`
- the adopted `Hotkeys` runtime tab now gets explicit refresh and tab-height handling in the real Designer surface
- the duplicate static Audio Story controls are no longer treated as a visible `--ui-real` target because the adopted runtime addon tab replaces that page at runtime
- provider selection is now a more direct runtime-backed workflow in `--ui-real`
- preset selection and preset action buttons are now a more direct runtime-backed workflow in `--ui-real`
- provider/model runtime status now mirrors more explicitly into the Designer surface
- the Visual Reply runtime dock/panel now lives on the real Designer surface in `--ui-real`
- the sensory hidden-loop core controls now execute through explicit runtime handlers in `--ui-real`
- the visible chat/session flow controls now execute through explicit runtime-backed handlers in `--ui-real`
- the visible response-length and host/input/runtime selection controls now execute through explicit real-mode handlers in `--ui-real`
- the visible MuseTalk/visual selection widgets now execute through explicit real-mode handlers in `--ui-real`
- the visible avatar/body/VaM controls now execute through explicit real-mode handlers in `--ui-real`
- the remaining visible profile/utility widgets now execute through explicit real-mode handlers in `--ui-real`

Documentation:

- `docs/main_ui_phase_2026-04-24_11.md`
- `docs/main_ui_phase_2026-04-24_12.md`
- `docs/main_ui_phase_2026-04-24_13.md`
- `docs/main_ui_phase_2026-04-24_14.md`
- `docs/main_ui_phase_2026-04-24_15.md`
- `docs/main_ui_phase_2026-04-24_16.md`
- `docs/main_ui_phase_2026-04-24_17.md`
- `docs/main_ui_phase_2026-04-24_18.md`
- `docs/main_ui_phase_2026-04-24_19.md`

### Phase 7 - Consider Making main.ui The Default

Status: far later.

Do not do this until:

- `--ui-real main.ui` exists
- Main workflows reach parity
- Runtime shutdown is verified
- Addon-owned surfaces are clean

## Documentation Rule For Future Passes

After every completed phase:

1. Create a new phase report in `docs/main_ui_phase_YYYY-MM-DD_##.md`
2. Record:
   - objective
   - files changed
   - validations run
   - what remains shell-local
   - what is still legacy-only
   - the next planned phase
3. Update this plan only if the sequence changes materially

## Best Next Task

The next highest-signal task is:

```text
Audit the remaining static duplicate and placeholder Designer surfaces in --ui-real, mark the non-targets explicitly, and then move to manual runtime parity testing for the workflows already migrated.
```
