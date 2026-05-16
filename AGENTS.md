# AGENTS.md - NeuralCompanion

## Mission
Make safe, minimal, professional changes without breaking unrelated behavior.
Default to narrow scope, backward compatibility, and low blast radius.

## Default Operating Mode
- Prefer the smallest correct change.
- Preserve current behavior unless the task explicitly requires behavior change.
- Do not perform broad refactors, renames, file moves, dependency changes, or style cleanups unless explicitly requested.
- If a request is underspecified and the work could affect architecture, UI wiring, addon contracts, presets/profiles/tutorial data, threading, audio, or model startup, ask follow-up questions before editing.
- If the request is local and low-risk, proceed with the least invasive implementation.

## Priority Order
1. Stability
2. Correctness
3. Minimal scope
4. Backward compatibility
5. Verifiability
6. Performance
7. New features

## Repo Map
Treat these areas as important and sensitive:
- `qt_app.py`: main PySide6 UI shell and wiring surface.
- `engine.py`: core orchestration and runtime flow.
- `shared_state.py`: shared state contract surface.
- `core/`: core conversation, sensory, provider, and addon framework logic.
- `core/addons/`: addon framework contracts and manager lifecycle.
- `addons/`: addon implementations loaded from `addon.json`.
- `pocket_tts_worker.py`: TTS worker/runtime-sensitive path.
- `MuseTalk/`: heavy inference, avatar runtime, and preprocess.
- `performance_profiles/`, `presets/`, `tutorials/`, `body_configs/`: user-facing data/config formats; preserve compatibility.
- `nuralcompanionbridge/` and `VaMtest/`: bridge and integration-related code.

## Known Architectural Constraints
- NeuralCompanion is a local desktop companion with a PySide6 UI and real-time streaming behavior.
- The addon framework uses manifests and dynamic loading. Preserve addon discovery, loading, initialization, shutdown, and contribution patterns.
- Presets, tutorials, and performance profiles are user-facing assets. Do not silently change their expected schema or keys.
- Real-time paths may span LLM, TTS, avatar, workers, and UI coordination. Avoid changes that widen timing risk.

## Scope Control Rules
- Only edit files directly relevant to the task.
- Do not make opportunistic "while here" changes.
- Do not silently fix unrelated bugs unless they block the requested task.
- Do not change public interfaces, config keys, addon manifest semantics, message formats, or file layout unless required by the task.
- Do not introduce new dependencies unless clearly necessary and justified.

## Sensitive-Area Rules
Use extra caution before changing:
- Qt signal-slot flow.
- Worker/thread behavior.
- Startup/shutdown sequencing.
- Audio capture, buffering, playback, or chunking.
- TTS/STT runtime behavior.
- Model loading, warm-up, or inference startup.
- Shared-state structure and naming.
- Addon discovery, manager, or manifest logic.
- Central files such as `qt_app.py`, `engine.py`, and `shared_state.py`.
- Anything under `MuseTalk/`.

For sensitive areas:
- Prefer additive or isolated changes over rewrites.
- Preserve old behavior by default.
- Explain risk if a wider change is unavoidable.
- Ask follow-up questions when expected behavior is unclear.

## Addon Rules
The addon system must remain isolated and loosely coupled.
- Follow existing patterns in `core/addons/` and nearby addons before inventing new ones.
- Do not create tight dependencies between addons.
- Do not modify unrelated addons.
- Preserve `addon.json` compatibility and load behavior.
- Prefer addon-local logic over framework changes.
- If framework changes are truly required, make them additive and backward-compatible.
- New addon behavior should fail safely when disabled or misconfigured.

## Data Compatibility Rules
Preserve compatibility for:
- `presets/*.json`
- `performance_profiles/*.json`
- `tutorials/*.json`
- `body_configs/*`
- Runtime-visible bridge/config surfaces.

Do not rename keys, move files, or change expected schemas unless the task explicitly requires migration work.

## Implementation Workflow
Before coding:
1. Identify the exact target files.
2. Identify what must remain unchanged.
3. Choose the least invasive solution.
4. If multiple plausible interpretations exist and the change is not clearly local, ask follow-up questions.

While coding:
- Match existing local patterns and naming.
- Keep changes small, readable, and reversible.
- Avoid speculative abstraction.
- Avoid rewriting working code for style reasons.
- Keep imports and dependencies stable unless necessary.

After coding:
- Re-check nearby call paths, imports, and runtime assumptions.
- Review for side effects on presets, addon contracts, worker flow, and UI wiring.
- Summarize what changed, why it changed, and what was intentionally left untouched.

## Debugging Rules
- Start from concrete symptoms, logs, stack traces, and call paths.
- Prefer root-cause fixes over cosmetic patches.
- Prefer inspection/logging over guessing.
- Do not remove existing logic unless there is evidence it is wrong, duplicated, or dead.

## When To Ask Follow-Up Questions
Ask before editing if:
- The request touches a sensitive area and expected behavior is unclear.
- More than one architecture-level approach is plausible.
- The work may affect addon compatibility.
- The work may affect presets, profiles, or tutorial compatibility.
- The request implies a broad refactor of `qt_app.py`, `engine.py`, `shared_state.py`, or `core/addons/*`.
- The request could alter latency, quality, or startup tradeoffs and the intended tradeoff is not stated.

## Output Expectations
For code changes, state:
- Files changed.
- What changed.
- Why this approach was chosen.
- What was deliberately not changed.
- Risk areas checked.
- Any follow-up validation still recommended.

## Non-Goals Unless Explicitly Requested
- Broad refactors.
- Style-only edits.
- Cleanup-only passes.
- Dependency upgrades.
- Architecture redesign.
- Moving files.
- Changing config/data formats.
