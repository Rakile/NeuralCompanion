# Tutorial authoring checklist

Keep stable guide IDs and existing JSON fields. Prefer a focused outcome over a tour of unrelated features. First Run is the short main-chat path; advanced workflows remain separate guides.

For each new or repaired step:

1. Inspect the current QML and adapter. Name the exact visible button, card, tab, window or setting, not a remembered label.
2. Set the workspace, addon section and inner navigation metadata to the actual destination. Use a stable objectName on the specific existing control; add an identifier when needed without changing its behavior.
3. State one action, its observable result, and how to recover if the control or result is absent. For conditional targets supply fallback_target and a specific target_hint.
4. Keep viewing separate from activation, selection separate from loading, and finishing a guide separate from successfully testing the feature.
5. Explain prerequisites. Reading must not install models, initialize the engine, enable addons, send messages, or alter settings automatically.
6. For tutorial speech, explain that Chatterbox must be selected and loaded using the large top-right power button OFF → ON (Initialize). The same control ON → OFF stops the engine (Terminate). Windows TTS is a fallback attempt, not proof of Chatterbox playback. Other configured providers may handle ordinary chat speech.
7. Verify real QML navigation/highlighting, hidden controls, absent content/addons and floating windows where relevant. Static target existence is not complete coverage.


Do not claim exhaustive coverage from the number of guides. Record separately whether a control is documented, its destination validates, its highlight works, and its end-to-end workflow has been exercised.

First Chat starts on Runtime → LLM: single-click views settings; double-click or Make active activates. Explain LM Studio/Ollama local servers and hosted API Key fields before Refresh, Chat model, Test connection and power ON. Complete a real main-chat reply before optional voice. The Persona guide follows the visible tab order, beginning with creating, reviewing and applying the system prompt, then saving the Persona and assigning its voice.

The Startup Self-Check console demonstration is explicitly started with Show me. It animates the actual split handle using presentation state and restores it afterward; it never emits visibility requests, saves settings or starts/stops providers. Cancel it on guide navigation/close or manual input. Keep this separate from executable tutorial actions.

Layout checks: run `ui.qml_bridge.smoke_tutorial_layout_qml` for the real desktop shell and `ui.qml_bridge.smoke_tutorial_target_geometry_qml` for scrolling and clipping. Include hidden tabs, locked/rearranged panes, grouped and minimized floating windows, and detaching/redocking during a step. A tutorial temporarily reveals its hidden destination without changing saved tab visibility. Closing it restores that visibility; normal tab selection still follows the user's navigation. Highlights use live control instances, with separate first reveals for a fallback and a late-loading primary target. Do not repeatedly force the user's scroll position or tab selection.
