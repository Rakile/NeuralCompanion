# Main Chat Remote Goal Prompt

Use this as the implementation goal for building phone access to NeuralCompanion's real main chat runtime.

```text
You are a senior professional Python/PySide6 and React Native developer working on NeuralCompanion.

Branch policy:
- All new commits and pushes for this work must use a new branch named best-architecture.
- The original human-readable branch label is "Best Architecture", but Git branch names cannot contain spaces, so use the valid slug best-architecture.
- Do not commit or push unrelated local changes.

Goal:
Build Main Chat Remote as a separate NeuralCompanion addon/service, not inside the Multi Persona Roleplay addon.

Architecture:
- Add a small in-process NC addon that safely accesses the real main chat runtime.
- Run a separate remote backend process from its own virtual environment, for example:
  Q:\new dev_latest\NeuralCompanion-dev\.venvs\nc_phone_remote
- Keep the phone app as Expo/React Native.
- Start LAN-first with numeric pairing code.
- Do not use raw port forwarding for internet access.
- Add later internet support only through a proper relay, tunnel, and authentication layer.

Implementation constraints:
- Protect existing LLM, TTS, STT, Visual Reply, persona, addon, MuseTalk, Companion Orb, and runtime behavior.
- Inspect existing files before editing and reuse current NC runtime and addon mechanisms.
- Keep changes small, additive, localized, and reversible.
- Prefer addon-local code. Touch shared core/runtime files only when a safe service surface is required.
- Use typed Python, defensive error handling, Qt-safe signal/slot patterns, worker threads for blocking work, and no UI-thread blocking.
- Do not create a parallel chat, TTS, STT, Visual Reply, or avatar runtime.
- Do not place this functionality under addons/multi_persona_roleplay.

First-version transport:
- Use LAN WebSocket state/control messages.
- Serve generated TTS chunks over HTTP for phone playback.
- Expose avatar/Visual Reply media through safe HTTP endpoints or frame streams.
- Use numeric pairing and reconnect-safe session state.
- Prefer simple, robust streaming first:
  - acceptable first version: frame polling or WebSocket frame URLs
  - better later: MJPEG or HLS-style frame stream
  - best later: WebRTC, only if the app moves beyond plain Expo Go or the native constraints are resolved

Expected work estimate:
- Basic main chat on phone with text send, chat feed, and runtime status: 2-4 days.
- Phone playback of generated TTS chunks: 2-4 more days.
- Voice reply from phone microphone into NC STT/chat: 3-6 days.
- Visual Reply display and request controls: 2-4 days.
- MuseTalk avatar stream/video mode: 1-2 weeks, depending on quality target.
- Polish, reconnect handling, pairing, settings, and testing: 4-7 days.
- Total realistic estimate: 2.5 to 4 weeks for a solid version.
- A rough prototype may be possible in about 1 week, but likely with rough streaming, pause/resume, reconnect, and MuseTalk timing behavior.

Likely existing desktop files to inspect before touching:
- engine.py: safe state snapshots, TTS state, chat actions, maybe MuseTalk/audio events.
- core/addons/qt_host_services.py: clean service surface for main chat remote commands.
- core/audio_playback.py: playback and level events only if needed; avoid changing core playback behavior.
- core/musetalk_preview_runtime.py: likely reused, maybe lightly extended.
- addons/musetalk_avatar/state.py: likely reused for live frame feed, maybe extended with safe HTTP frame access.
- ui/runtime/backend_console_chat.py: inspect if exact main chat behavior must be mirrored.
- ui/runtime/backend_engine_lifecycle.py: inspect for remote server install/start controls.
- ui/runtime/backend_runtime_controls.py: inspect for pause/skip/regenerate state exposure.

Expected additive files:
- addons/main_chat_remote/
- addons/main_chat_remote/addon.json
- addons/main_chat_remote/controller.py
- addons/main_chat_remote/remote_backend.py
- addons/main_chat_remote/media_bridge.py
- addon-local settings/UI files if needed
- docs and smoke tests
- Expo app split into maintainable files instead of one large App.tsx

Risk focus:
- MuseTalk streamed as smooth phone video is the highest-risk area.
- Reuse existing preview frame state where possible.
- Avoid damaging the desktop MuseTalk preview/runtime path.
- Start with stable LAN WebSocket state plus HTTP audio chunks and frame streaming.
- Defer WebRTC until a deliberate native/dev-client plan exists.

Validation expectations:
- Add smoke/manual validation steps where practical.
- Verify the addon loads and unloads safely.
- Verify disabled state leaves main chat, TTS, STT, Visual Reply, MuseTalk, persona, addon loading, and Companion Orb behavior unchanged.
- Verify pairing, reconnect behavior, text send, chat feed updates, runtime status, TTS chunk playback, and media endpoints on LAN.
- Document remaining known limitations, especially around MuseTalk timing and phone video quality.

Definition of done:
- A separate Main Chat Remote addon/service exists outside Multi Persona Roleplay.
- The phone app can pair over LAN, show status/chat feed, send text to the real main chat runtime, and play generated TTS chunks.
- STT microphone input, Visual Reply controls/display, and MuseTalk/video mode are implemented or explicitly staged with documented limitations.
- Existing NC runtime behavior remains intact when the addon is disabled.
- Tests or smoke/manual validation notes are present.
- All commits and pushes are on best-architecture.
```
