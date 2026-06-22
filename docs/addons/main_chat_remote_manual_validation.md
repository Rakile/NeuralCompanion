# Main Chat Remote Manual Validation

Use this checklist after the local smoke tests pass and before treating Main Chat Remote as complete. It is meant for the real NeuralCompanion desktop runtime plus a physical phone on the same LAN.

## Scope

- Validate the separate `addons/main_chat_remote` addon/service, not Multi Persona Roleplay.
- Validate the LAN backend process and Expo phone app together.
- Do not use internet port forwarding. Internet support remains deferred until a relay/tunnel/auth layer exists.
- Keep unrelated desktop runtime behavior unchanged.

## Preflight

1. Confirm the branch:

   ```powershell
   git branch --show-current
   ```

   Expected: `best-architecture`.

2. Run local smoke checks from the repo root:

   ```powershell
   python -B -m py_compile addons\main_chat_remote\main.py addons\main_chat_remote\controller.py addons\main_chat_remote\media_bridge.py addons\main_chat_remote\remote_backend.py addons\main_chat_remote\backend_process.py addons\main_chat_remote\scripts\backend_venv.py addons\main_chat_remote\smoke_main_chat_remote.py
   python -B addons\main_chat_remote\smoke_main_chat_remote.py
   ```

3. Typecheck the phone app without leaving install artifacts in the repo:

   ```powershell
   cd apps\main-chat-remote-phone
   npm run validate:temp
   ```

4. In desktop NC, verify Main Chat Remote appears as its own addon tab and that disabling/unloading it leaves main chat, LLM, TTS, STT, Visual Reply, MuseTalk, persona, addon loading, and Companion Orb behavior unchanged.

## Desktop Backend

1. In the Main Chat Remote addon tab, enable the local bridge.
2. Create the backend venv only for real backend validation:

   ```powershell
   python addons\main_chat_remote\scripts\backend_venv.py --create
   ```

   Expected venv: `.venvs\nc_phone_remote`.

3. Confirm the LAN backend refuses to start from a disabled or stale `runtime\main_chat_remote\bridge_info.json`.
4. Start the LAN backend from the addon tab.
5. Confirm the tab shows:
   - local bridge running
   - LAN backend running
   - numeric pairing code
   - LAN URL using the desktop LAN IP
   - health `ready`

6. From the desktop browser or PowerShell, verify:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:8777/health
   ```

   Expected: LAN backend responds and bridge health is ready.

## Phone Pairing

1. Start the Expo app on a physical phone connected to the same LAN.
2. Enter the LAN URL and numeric pairing code from the addon tab.
3. Connect.
4. Confirm:
   - status becomes connected
   - transport becomes WebSocket when available
   - polling fallback appears if WebSocket is blocked or stale
   - wrong pairing code returns a visible unauthorized error
   - repeated wrong pairing codes eventually return a visible rate-limit error without continuous reconnect/poll retry churn, then the correct code connects again
   - changing the URL or pairing code disconnects stale sessions

## Main Chat

1. Confirm the phone shows runtime status, provider/model/TTS/mic status, and recent chat feed.
2. Send a text message from the phone.
3. Confirm the same message reaches the real desktop main chat runtime.
4. Confirm the phone chat feed updates after the response.
5. Use pause/skip/regenerate/replay controls where available and confirm the desktop runtime reacts through existing runtime controls.
6. Start/stop the engine from the phone only if the desktop lifecycle service is expected to be available.

## TTS Playback

1. Trigger an assistant response that generates TTS chunks.
2. Confirm phone TTS panel receives chunks.
3. Confirm autoplay plays new chunks in order.
4. Toggle autoplay off, trigger another response, and confirm old unseen chunks are not unexpectedly replayed when autoplay is turned back on.
5. Use manual Play, Stop, and Reset.
6. Confirm playback recovers if a chunk has no duration metadata or if playback completion is missed.

## Phone STT

1. Confirm the desktop selected STT backend exposes file transcription.
2. Record a short clip from the phone.
3. Stop recording and confirm the transcript is sent into real main chat.
4. Confirm the temporary phone recording is removed from the phone app path after upload.
5. Confirm oversized clips are rejected locally before upload and the desktop upload cache remains bounded.

## Visual Reply

1. Confirm the phone shows Visual Reply availability and current image when present.
2. Run Snapshot, Show, Hide, and Clear from the phone.
3. Generate a Visual Reply request from a phone prompt.
4. Confirm failed generate attempts keep the prompt text for retry.
5. Confirm the desktop Visual Reply service receives the request through its existing service surface.

## MuseTalk

1. Enable the existing desktop MuseTalk preview/runtime path.
2. Confirm the phone receives MuseTalk state and a current frame.
3. Confirm `/api/musetalk/stream` displays on phone when the Expo image loader accepts the stream.
4. Confirm the phone falls back to newest-frame polling/feed access if the stream fails or stalls.
5. Note frame rate, latency, and any A/V timing drift. WebRTC-grade smooth video is not expected in the first version.

## Reconnect And Cleanup

1. While connected, stop and restart the LAN backend.
2. Confirm the phone shows polling/error state, then recovers after reconnect.
3. While connected, disable and re-enable the local bridge.
4. Confirm health changes are visible in the addon tab and phone.
5. Stop the LAN backend from the addon tab.
6. Confirm `runtime\main_chat_remote\bridge_info.json` is removed after the local bridge is disabled.
7. If the backend venv was created only for validation, decide whether to keep `.venvs\nc_phone_remote` or remove it intentionally.

## Evidence To Capture

- Branch name and smoke command outputs.
- Expo typecheck/config command outputs.
- Addon tab screenshot or notes showing LAN URL, pairing code, and health ready.
- Phone screenshots or notes for connected status, chat feed, TTS, STT, Visual Reply, and MuseTalk.
- Any remaining MuseTalk timing or reconnect issues with exact dates and reproduction steps.
