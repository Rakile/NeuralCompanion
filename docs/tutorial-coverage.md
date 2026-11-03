# Contextual tutorial coverage

Implemented in NeuralCompanion-dev and NeuralCompanion-dev-dirt on 2026-11-03. Publication is handled separately from implementation; see the branch history for the commit.

## Result

- Runtime Session pilot: overview plus Session setup, Resources, LLM, STT, TTS, Visual reply and Avatar.
- All 55 bundled addon manifests have authored contextual guides, including hosted providers, sensory contributors, disabled options and service-only integrations.
- Catalog: 367 definitions (353 visible entries and 14 preserved overview aliases): 64 overviews, 257 focused section guides, 37 explicitly labelled existing workflows, 8 unchanged Remote reader guides and the unchanged First Chat.
- First Chat SHA256: `e415f566e499921136e9201098d72efb97617ed109928fd6f96c5ba947e3645c`.
- Authorship and live verification are separate. **No addon is marked fully runtime verified.** Conditional controls, installed backends, external services and real device behavior still require walkthroughs in the installed app.

Scenic Pack Creator is included with an overview and an Editor chapter. This is authored coverage; its tutorial walkthrough is not marked runtime verified.

## Access and behavior

Right-click a workspace, addon icon, provider or supported internal tab to open its scoped tutorial menu. The clicked destination determines the menu; opening it does not activate the tab. A visible Tutorial action is available above each workspace and on Addon Manager rows, including service-only addons. Existing hide, reorder and docking actions remain.

Large menus show a short list and Browse all guides for this area. The browser exposes an explicit Show all desktop guides action. Search returns to the complete audience catalog, preserving the existing search semantics. Desktop, Remote and workflow guidance remain distinct.

Scoped tutorials retain their current audio request when the user browses another tab. Yellow destination markers remain on the owning workspace, addon/provider and section tabs. Show current step uses a separate view token and returns without replaying narration. The current utterance continues; automatic progression waits while its page is elsewhere. No tab change cancels the tutorial.

Authored guides use a course → actual page chapter → exact target step structure. Informational steps advance only after a successful playback receipt (or successful Windows fallback process exit), with the exact target visible in its owning window. Missing targets, cancelled/failed narration and interactive steps hold for recovery or Continue. The final step stays open until Finish. Chapters can be selected directly, including retained old overview IDs. Optional follow-ups remain explicit.

LiquidAI uses Overview → Setup → Voice → Generation. Advanced and voice-tag rules are optional follow-ups. Its 16 main-course steps point to actual LiquidAI control IDs; Advanced targets the two override fields. Duplicate overview entries are merged, with the old IDs preserved as hidden aliases.

Tutorial launchers, menu text and destination outlines are yellow. The Tutorials browser and floating Tutorial Guide use normal theme text colors for their headings, step text, notices and controls. Ordinary controls keep their theme. Tutorials workspace offers independent persisted switches for Tutorial buttons and right-click tutorial entries. These switches hide launchers only; the active guide, playback controls and yellow return markers remain available.

First Chat bypasses course composition and the new scope rules. Its file is byte-identical, and its first-run entry point, manual step flow and existing two-argument narration path remain unchanged. The shared narration controller adds an optional completion callback used only by scoped guides. Existing guide IDs remain loadable; broad guides retain their content and receive workflow metadata and explicit route allowlists.

Tutorial navigation uses existing view-provider and workspace APIs. It never calls provider activation, grants MCP access, changes addon enablement, starts a service or loads a model. Explicit exercises and the existing narration preference remain user-controlled. Navigation and scroll preferences continue through the existing mechanisms.

## Files and boundaries

| Area | Changes |
|---|---|
| core/tutorial_scope.py | Typed pure scope normalization, validation, contextual filtering and per-step presentation tracking, independent of playback. |
| core/tutorial_course.py | Pure, explicit course composition and stable chapter shortcuts; validates every source chapter before flattening. |
| core/tutorial_narration.py | Optional completion receipt callback; fallback exit monitoring runs in a worker. Legacy calls retain their existing behavior. |
| core/ui_session_schema.py | Two tutorial launcher visibility preferences in the existing UI persistence contract. |
| core/tutorial_catalog.py | Authored bundle loading, preserved direct legacy loading, ownership metadata and workflow labels. |
| ui/qml_bridge/application_bridge.py | Presentation routing, scoped lifecycle, contextual menus and transient browser filtering. |
| ui/qml/components | Shared tutorial menu, route reader, workspace help action, target anchors and scope-aware overlay; existing navigation actions retained. |
| ui/qml/workspaces | Small contextual-help hooks for actual section/provider tabs and preview anchors. |
| addons/voice_studio/qml/VoiceStudio.qml | UI identity and tutorial contexts for its three existing tabs. No addon controller changes. |
| tutorials/scoped | Authored addon/main-page bundles and the explicit 55-owner inventory. |
| tutorials/runtime_*.json | Eight Runtime Session pilot definitions. |
| Existing desktop tutorial JSON | Workflow metadata/category only; existing IDs, steps and prose retained. |
| External tutorial validation suite | Scope, catalog, actual bridge-method and offscreen QML checks; the seven test files are excluded from the RC tree. |
| tools/check_tutorial_coverage.py | Read-only authored-coverage audit; does not import addon runtimes. |

Generated native contracts, models, virtual environments, configuration secrets, remotes, phone app sources, backend contracts and the unrelated pre-existing chat/speech edits were not edited.

## Full walkthrough reachability check

Every existing desktop workflow now declares contextual_guides, pointing to the contextual courses from which it can be reached. All 37 existing full walkthroughs are connected. The coverage audit fails if a walkthrough lacks a parent, if a parent no longer includes it, if a focused chapter becomes disconnected from its course, or if an automatic continuation crosses the parent's area. New workflow definitions must declare contextual_guides and be referenced by those parents in course_chapters or optional_chapters.

Twelve main courses use the short introduction followed by the existing full walkthrough: Conversation, Persona, Audio Story, Multi Persona Roleplay, AI Presence, Conversation Replay, Hotkeys, Discord Voice Bridge, Corsair Visual Instrument, User Identity, Voice Studio and Buddy Chat. Their focused topic guides remain available as chapter shortcuts and optional follow-ups.

The other 25 workflows are optional, explicitly labelled Workflow entries because they cover setup or related areas. They are available from the matching contextual menu/browser and the guide's follow-up selector. Layout guidance is linked from the main workspace courses. Existing workflows retain their original steps and manual exercise progression.

The former separate core Persona overview is a preserved hidden alias of the full Persona course. First Chat and Remote guides are excluded from this linking policy. No addon or tab without a relevant longer guide is redirected to an unrelated walkthrough.

Touched code: core/tutorial_coverage.py, core/tutorial_scope.py, core/tutorial_catalog.py, tools/check_tutorial_coverage.py, and the follow-up selector in NCTutorialOverlay.qml. Tutorial JSON changes declare the relationships and main continuations; the existing walkthrough content is reused. The detailed-coverage regressions are retained in the external tutorial validation suite.

## Continuous-player validation

- DeepSeek agents supplied focused narration/course proposals and reviewed playback and overlay changes. Suggestions were checked against the actual code; return navigation deliberately retains audio identity and completion status.
- 50 focused tests pass in each tree. Checks cover actual bridge methods, successful/stale/interrupted receipts, fallback exit, interactive holds, scope validation, course shortcuts, launcher persistence, real QML compilation, floating-window ownership and no duplicate narration on state updates or Show current step.
- The provider-navigation regression tests exercise all six standard TTS panels using their actual declared section names, delayed provider mounting, manual tab changes, the actual addon-manager row and repeated Avatar workspace mounting. The supplied log's 212 marker-layout warnings and contextKey binding loop are reproduced and fixed. The separate avatar-rules description warning was not reproduced in the actual Avatar workspace harness; installed-app confirmation remains required. Nahimic, texture filtering and clipboard messages are outside the tutorial subsystem.
- Conversation's contextual course now includes its existing 13-step chat walkthrough after the two orientation steps. User exercises wait for Continue. Catalog step counts and outlines show the composed course instead of only the overview. First Chat remains separate.
- The coverage audit validates all composed chapters and retained aliases, all 54 manifests and the First Chat hash.
- Installed backend/audio walkthroughs remain manual: source validation and offscreen tests do not certify actual speakers, providers, or every conditional addon control. No addon is marked fully runtime verified.

## Addon inventory

The counts below include each addon's overview, focused topics and relevant hosted Orb/Spotify awareness guides. These are authored counts, not runtime certifications. Provider cards and wizard stages are documented in their actual host; no artificial tabs were added.

| Addon | Presentation | Authored guides |
|---|---|---:|
| AI Presence Mode | addon | 7 |
| Audio Story Mode | addon | 8 |
| Buddy Chat | addon | 8 |
| Chatterbox Multilingual TTS | tts | 6 |
| Chatterbox TTS | tts | 5 |
| Chat MCP Tools | service | 2 |
| Conversation Replay | addon | 5 |
| Claude Chat Provider | language | 4 |
| Clipboard Source | vision | 4 |
| Clipboard Supervisor | vision | 3 |
| Companion Chess | addon | 2 |
| Companion Orb Overlay | addon | 15 |
| Corsair Visual Instrument | addon | 8 |
| DeepSeek Chat Provider | language | 4 |
| Discord Voice Bridge | addon | 11 |
| Ditto Avatar | avatar | 8 |
| Ditto Avatar Creator | cards | 5 |
| ElevenLabs TTS | tts | 5 |
| Gemini TTS Preview | tts | 5 |
| Heart Rate Behavior | vision | 3 |
| Hotkeys | addon | 4 |
| NC Identity Relay | addon | 6 |
| LiquidAI TTS | tts | 7 |
| LM Studio (REST) Chat Provider | language | 4 |
| LM Studio Chat Provider | language | 4 |
| Main Chat Remote | remote | 6 |
| MCP Core | cards | 4 |
| Mock Heart Rate | vision | 4 |
| Multi Persona Roleplay | addon | 14 |
| MuseTalk Avatar | avatar | 5 |
| MuseTalk Avatar Creator | cards | 9 |
| No Avatar | avatar | 2 |
| No STT | stt | 2 |
| Ollama Chat Provider | language | 4 |
| OpenAI Chat Provider | language | 4 |
| PocketTTS | tts | 6 |
| PocketTTS Multilingual | tts | 5 |
| Document Memory | memory | 6 |
| Scenic Avatar | avatar | 3 |
| Scenic Pack Creator | cards | 2 |
| Screen Source | vision | 4 |
| Screen Supervisor | vision | 3 |
| Spotify Sense | addon | 14 |
| Ua Companion Orb Overlay | service | 2 |
| User Identity | addon | 4 |
| Visual Reply | cards | 3 |
| Visual Story Settings | cards | 5 |
| Voice Studio | studio | 4 |
| VSeeFace Avatar | avatar | 6 |
| Webcam Source | vision | 4 |
| Webcam Supervisor | vision | 3 |
| Web Search | addon | 4 |
| Whisper English STT | stt | 2 |
| Whisper Multilingual STT | stt | 2 |
| xAI / Grok Chat Provider | language | 4 |

## Verification

Run from the repository root:

```powershell
rtk proxy python -B tools/check_tutorial_coverage.py
rtk git diff --check
```

Automated regression tests are maintained outside the release-candidate tree. The following test results describe external validation, not files shipped with NC.

The focused tests cover exact ownership, workflow allowlists, malformed metadata, all 54 manifests, inventory page resolution, unique IDs, overview links, First Chat's hash and legacy path, stale tokens, bounded presentation settling, browsing/return/end, contextual browser search, inactive-tab mouse/keyboard access, QML compilation, and highlighting in the owning floating window. Service-free fixtures execute the actual bridge method bodies and real QML. They do not instantiate the full app facade or claim backend readiness.

Final verification: **50 focused tutorial tests pass in each tree**. Both trees pass the coverage audit and diff whitespace check. The full suite ran 90 tests in the development tree, with 12 dependency import errors, no assertion failures, and one Windows symlink skip. Tutorial feature files match between trees; protected user edits and First Chat match their before-change hashes. The tutorial commit excludes the unrelated pre-existing speech/highlighting edits.

The available Python lacks the optional `keyboard` dependency. The full suite therefore reports import errors in AI Presence defaults, bundled Personas, power restart and the existing TTS-provider-tab tests. The Stockfish symlink test is skipped because Windows does not grant symlink creation. Dependencies were not installed or changed to work around those limitations.

The phone-sync skill's named smoke scripts are absent from this checkout. Phone sources and backend/API contracts were unchanged; no phone build or physical-device test was performed.

## Manual walkthrough still required

1. Launch NC in its usual installed environment. Confirm the welcome prompt and Your first chat navigation/read-aloud remain familiar.
2. Right-click Runtime Session, run its overview, and choose each pilot section guide. Check every highlight against the visible control with both a narrow and wide window.
3. Right-click an inactive section/provider. Verify that the menu belongs to it and that opening the menu does not change selection or activate a provider. Check the existing Hide and docking actions.
4. Start narration, change tabs, and confirm the utterance continues without restarting or losing the tutorial. Follow the yellow destination markers. Show current step must return without replay; Replay step is separate. Check that automatic progression waits for the exact visible target, that interactive steps wait for Continue, and that ending tutorial narration leaves normal conversation speech intact.
5. Toggle the two launcher visibility settings independently, restart NC, and verify persistence. The active guide and yellow return markers must remain available with both switches off.
6. Repeat with a floating workspace, a grouped floating window, a minimized owner and a temporarily hidden main tab. Check saved geometry and docking remain intact.
7. Walk every available addon and its actual tabs against its authored guides. Test prerequisites, conditional package controls and missing/disabled addons. Keep unavailable destinations recorded as unverified rather than counting a fallback highlight as a verified control.
8. Check the Remote audience reader separately. If exercising Main Chat Remote setup guidance, use a real phone with the existing matching app build.

## Future additions

Add authored definitions under tutorials/scoped using a stable ID, kind and explicit scope. Use actual workspace/provider/contribution keys and real objectName anchors. Section/overview steps inherit their owner and cannot add another destination; workflows must enumerate every effective route. A new addon manifest without authored ownership fails the audit.

Declare course_chapters explicitly on course roots and course_id on shortcuts. Use optional_chapters for related optional guidance; use advance_mode: continue for user exercises. Hidden redirect_to definitions preserve old IDs without duplicate menu entries. Legacy workflows and First Chat retain their existing flow.

Update the owner's page inventory when real navigation changes. Do not edit generated native contracts or mark an addon runtime verified based only on schema tests, source inspection, a provider name or reaching Finish.
