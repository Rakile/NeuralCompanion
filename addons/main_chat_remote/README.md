# Main Chat Remote

Main Chat Remote is a separate addon/service for phone access to the real NeuralCompanion main chat runtime. It is intentionally not part of Multi Persona Roleplay.

## Architecture

- `main.py` registers the addon and the `main_chat.remote` peer service.
- `controller.py` owns the localhost-only bridge into existing NC host services:
  - `qt.shell` for typed main chat messages
  - `qt.runtime_status` for runtime status
  - `qt.runtime_controls` for pause, skip, regenerate, and replay actions
  - `qt.engine_lifecycle` for start/stop snapshots
  - `qt.chat_replay` for the current chat feed
- `media_bridge.py` copies generated TTS audio chunks from the existing `tts.audio_chunk_ready` capability into `runtime/main_chat_remote/audio/`, including desktop- or microphone-originated main-chat replies. Current NC engine chunks are `.wav`; the cache preserves common playable audio suffixes if another backend emits them later.
- `remote_backend.py` is a separate LAN-facing backend process. Run it from the planned `nc_phone_remote` venv and point it at the addon bridge info file.
- `backend_process.py` supervises a backend process launched from the addon tab without moving backend logic into the NC UI process.

The existing engine TTS chunk notification fans out `tts.audio_chunk_ready` to all initialized addons so Main Chat Remote can capture phone playback chunks without depending on Multi Persona Roleplay addon order or ownership. The media cache is bounded and addon-local; local audio file paths are not exposed to the phone API.

The NC bridge binds only to loopback and requires the bridge token from `runtime/main_chat_remote/bridge_info.json`. The bridge-info file is written only while the local bridge is enabled, refreshed while the bridge is running, and removed when the bridge stops. The addon supervisor and LAN backend reject disabled, stale, future-dated, malformed, timestamp-less, or tokenless bridge-info files during startup. The LAN backend exposes the phone API and requires a numeric pairing code.
Preflight requests follow the same network boundary: the bridge accepts loopback clients only, and the LAN backend accepts local-network clients only.
The LAN backend only proxies to an HTTP loopback bridge origin. If a bridge URL from env or bridge-info points elsewhere, the backend falls back to `http://127.0.0.1:8776`.
The LAN backend strips phone-facing credential query keys before proxying to the loopback bridge; bridge authentication stays on the `X-NC-Bridge-Token` header. The local bridge does not accept query-string tokens.

## First Run

1. Enable the local bridge in the Main Chat Remote addon tab.
2. Create the separate backend venv when needed:

   ```powershell
   python addons\main_chat_remote\scripts\backend_venv.py --create
   ```

   The default venv path is `.venvs\nc_phone_remote`.

3. Start the LAN backend from the Main Chat Remote addon tab, or from the repo root:

   ```powershell
   python addons\main_chat_remote\scripts\backend_venv.py --start --bridge-info runtime\main_chat_remote\bridge_info.json
   ```

   If that venv does not exist yet, the system Python can run the backend for local smoke testing because it only uses the standard library.

4. Enter the LAN URL and numeric pairing code in the Expo/React Native phone app.

When the addon tab starts the backend, it generates the numeric pairing code and displays it in the tab along with the LAN URL and readiness health. When the CLI starts the backend, the backend prints the pairing code to the console or backend log.

If the addon tab or CLI helper already knows the pairing code, it passes the code to the child backend through `NC_MAIN_CHAT_REMOTE_CODE` and suppresses code echo in backend stdout logs. When the CLI helper starts without a valid `--pairing-code`, it clears stale pairing-code environment variables before launching so the backend generates and prints a fresh code. The CLI helper and direct backend entry point validate bridge-info freshness before serving. Direct backend starts that let the backend generate a code still print that generated code for pairing.

Manual pairing-code values are normalized to 4-9 digits. If no valid numeric code remains, the backend generates a fresh 6-digit code.

## HTTP API

`GET /health` is unauthenticated and returns LAN backend and bridge health. Top-level `ok` means the LAN backend is reachable and the local NC bridge responded. The `remote` object is a public status snapshot with counts and pairing-code length only; it does not include client addresses or the private bridge URL.

All `/api/*` endpoints require the pairing code through either:

- `X-NC-Phone-Code: <code>`
- `?code=<code>`

The Expo app uses `X-NC-Phone-Code` for JSON API calls and reserves `?code=` for WebSocket, image, audio, and stream URLs where React Native cannot attach custom headers.
Phone-facing JSON exposes URL paths such as `image_url_path`, `frame_url_path`, and `url_path`; desktop-local file paths, backend commands, bridge-info paths, STT upload paths, and common secret fields such as API keys, tokens, passwords, and authorization values are kept private to the addon process.
Repeated invalid pairing attempts from the same client are rate-limited for a short window. A valid code clears the client's failure window.

Endpoints:

- `GET /api/state`: runtime status, chat feed, control actions, TTS media, Visual Reply state, MuseTalk state, and feature flags.
- `POST /api/send`: body `{"text": "hello"}` queues text into the existing main chat runtime.
- `POST /api/control`: body `{"action": "pause_speech"}` triggers an existing runtime control action.
- `POST /api/engine/start`: starts the NC runtime through the existing lifecycle service.
- `POST /api/engine/stop`: stops the NC runtime through the existing lifecycle service.
- `GET /api/audio`: lists captured generated TTS chunks.
- `GET /api/audio/file/<id>`: returns a captured TTS audio chunk with the cached file's content type.
- `POST /api/stt`: body `{"audio_base64": "...", "format": "wav", "send_to_chat": true}` transcribes phone audio with the selected NC STT backend and optionally queues the transcript into main chat. Uploaded phone clips are stored under `runtime/main_chat_remote/stt_uploads/` with bounded addon-local retention.
- `GET /api/visual`: returns current Visual Reply settings, display state, and recent phone-request status.
- `POST /api/visual`: body `{"prompt": "...", "action": "generate"}` queues a Visual Reply request through the existing Visual Reply service. Supported actions are `snapshot`, `show`, `hide`, `clear`, and `generate`.
- `GET /api/visual/image`: returns the current Visual Reply image when one exists.
- `GET /api/musetalk?after_seq=<n>`: returns the current MuseTalk preview/pipeline state and recent frame feed items.
- `GET /api/musetalk/frame/<id>`: returns a current MuseTalk preview frame.
- `GET /api/musetalk/stream`: returns a multipart MJPEG-style stream of current MuseTalk preview frames. Optional query params: `fps`, `frames`, and `wait`.

JSON payloads are capped at 25 MB. Phone microphone uploads should be short clips, not long recordings. The Expo app rejects recordings larger than 18 MB before base64 encoding so the bridge stays under the JSON cap.

## WebSocket

`GET /ws?code=<code>` upgrades to a dependency-free WebSocket connection.

Periodic WebSocket state snapshots use a short bridge timeout so a stalled desktop bridge reports an error quickly instead of freezing the phone state stream. Command messages still use the normal bridge timeout.

Server messages:

- `{"type": "hello", "remote": {...}}`
- `{"type": "state", "payload": {...}}`
- `{"type": "send_result", "request_id": "...", "payload": {...}}`
- `{"type": "control_result", "request_id": "...", "payload": {...}}`
- `{"type": "engine_start_result", "request_id": "...", "payload": {...}}`
- `{"type": "engine_stop_result", "request_id": "...", "payload": {...}}`
- `{"type": "error", "error": "..."}`

The WebSocket `hello.remote` payload uses the same public status snapshot as `/health`.

Client messages:

```json
{"type": "state"}
{"type": "send_text", "request_id": "phone_1", "text": "hello"}
{"type": "control", "request_id": "phone_2", "action": "skip_speech"}
{"type": "visual", "request_id": "phone_3", "payload": {"prompt": "make an image from the current reply"}}
{"type": "engine_start", "request_id": "phone_4"}
{"type": "engine_stop", "request_id": "phone_5"}
```

## Current Limits

- Text send, chat feed, runtime status, runtime controls, LAN pairing, WebSocket state, HTTP TTS chunk access, JSON/base64 phone STT upload, Visual Reply snapshot/request controls, MuseTalk frame polling, and an MJPEG-style MuseTalk frame stream are scaffolded.
- Phone STT uses the selected NC STT backend and can be slow while the model loads.
- MuseTalk phone display prefers the frame stream and falls back to frame polling/feed access. It is still not WebRTC-grade smooth video.
- The Expo app scaffold lives in `apps/main-chat-remote-phone/` and targets Expo SDK 54 / Expo Go client 54.0.8.
- Internet access remains out of scope until a relay/tunnel/auth layer is deliberately added.

## Validation

Run the smoke checks in `smoke_main_chat_remote.py` for local coverage. Use `docs/addons/main_chat_remote_manual_validation.md` for real NC runtime plus physical phone LAN validation before calling the feature complete.
