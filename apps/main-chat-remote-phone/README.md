# NC Main Chat Remote Phone

Expo/React Native phone app for `addons/main_chat_remote`.

## Setup

```powershell
cd apps\main-chat-remote-phone
npm install
npm run start
```

Use the LAN URL and numeric pairing code shown in the Main Chat Remote addon tab after starting the LAN backend. From the repo root, the same backend can be created and started with:

```powershell
python addons\main_chat_remote\scripts\backend_venv.py --create
python addons\main_chat_remote\scripts\backend_venv.py --start --bridge-info runtime\main_chat_remote\bridge_info.json
```

The helper uses `.venvs\nc_phone_remote` by default. The URL field accepts the full LAN URL, a copied full endpoint such as `http://192.168.1.10:8777/health`, or a bare host/IP address. Bare hosts default to port `8777`. Path-only values are rejected because the app cannot infer the host. Pairing codes must be 4-9 digits.

This app targets Expo SDK 54 so it can run in Expo Go client 54.0.8. The code is split into API, hooks, components, styles, and utilities so the first `App.tsx` stays small.

## Demo Mode

Use the `Demo` button in the connection panel to run an offline phone-app tour without starting the LAN backend. Demo mode keeps pairing/auth untouched and feeds local sample state into the same Chat, Story, Visual Reply, TTS Audio, and MuseTalk panels used by the live app.

Demo mode includes:

- A pre-made main chat conversation.
- A Multi Persona Story scene with narrator and character segments, choices, memory counts, story audio chunks, and Chromecast status.
- A Visual Reply storyboard scene.
- A local animated MuseTalk-style avatar preview.
- Buddy Chat status with per-persona provider demo data.

Exit demo mode before connecting to a real Main Chat Remote backend.

## Current Scope

- LAN pairing with numeric code.
- LAN URL and pairing code persisted with Expo SecureStore.
- WebSocket state stream and command path for text, runtime control, engine lifecycle, and Visual Reply actions, with immediate HTTP polling/fetch fallback for socket failures, disconnects, or stale state streams.
- Reconnect attempts keep the visible transport in polling mode while the fallback is still active.
- Last known chat/runtime/media state stays visible during active fallback transports, while commands stay disabled until the connection is healthy.
- Refresh remains available during active fallback transports so recovery can be probed manually.
- Fast backend health/readiness check before state polling.
- Pairing authorization and rate-limit failures stop reconnect/polling retries until the user reconnects with updated settings.
- Bounded JSON request timeouts so bad LAN targets fail visibly instead of hanging.
- Accepted actions stay accepted if the follow-up refresh fails; the refresh error is shown as connection state instead of as a command failure.
- Header-only pairing for JSON API fetches; query-code URLs are kept for WebSocket and media loads.
- Chat stays in the primary flexible area while TTS, Visual Reply, MuseTalk, and composer controls sit in a bounded keyboard-aware scroll area.
- Main chat feed and text send.
- Runtime controls and engine start/stop.
- Sequential TTS chunk playback with autoplay, stop, reset, and manual play controls. Chunks received while autoplay is off or played manually stay out of later autoplay backlog.
- Phone microphone clip upload to NC STT when the selected desktop STT backend exposes file transcription, with a one-minute clip cap before upload.
- Visual Reply generate, snapshot, show, hide, and clear controls.
- MuseTalk frame stream display with newest-frame fallback when stream loading fails or stalls.
- Feature-aware controls for desktop STT, Visual Reply, and MuseTalk availability.
- Buddy Chat status display, including enabled state, active persona count, shared provider mode, and per-persona provider override count. Provider URLs, API keys, and local voice paths are not exposed to the phone.
- Offline Demo mode for reviewing the phone UI without a running backend.

WebRTC-grade MuseTalk video and internet relay/auth support remain backend and transport work, not phone-only UI work.

## Validation

Run `npm run validate:temp` from this directory to typecheck and inspect Expo config from a temporary copy without leaving `node_modules` or lockfiles in the repo. Use `docs/addons/main_chat_remote_manual_validation.md` from the repo root for the real NC runtime and physical phone LAN checklist.
