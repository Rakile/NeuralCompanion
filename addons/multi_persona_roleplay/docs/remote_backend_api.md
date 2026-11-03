# MPRC Remote Backend API

Addon-local HTTP backend for the Multi Persona Roleplay Android remote.

Default URL: `http://<pc-lan-ip>:8765`

The backend is disabled by default. Enable it in the MPRC Play toolbar with `LAN Remote`.

## Security

- LAN/private clients only.
- No cloud service.
- No LLM, TTS, image, or story logic runs on the phone.
- `/api/*` endpoints require the six-digit local pairing code from the Play toolbar.
- Send the code using one of:
  - `X-MPRC-Code: <code>`
  - `?code=<code>`

`GET /health` is unauthenticated and returns basic status for connection testing.

## Endpoints

### `GET /health`

Returns backend health and remote status.

### `GET /api/state`

Returns:

- `session`: current MPRC session/AR state
- `personas`: cast/persona summaries
- `latest_reply`: latest story reply text
- `segments`: parsed narrator/character/audio segments
- `choices`: current playable choices
- `audio_cues`: available AudioFX metadata
- `visual`: latest visual prompt metadata when available
- `remote`: backend URL, pairing code, and client status

### `GET /api/personas`

Returns persona/cast summaries.

### `GET /api/session`

Returns current session and AR state.

### `POST /api/session`

Updates selected session fields. Accepted keys include:

- `enabled`
- `mode`
- `scene_title`
- `location`
- `time_of_day`
- `mood`
- `objective`
- `scene_summary`
- `ar_state.current_scene`
- `ar_state.location`
- `ar_state.time_of_day`
- `ar_state.mood`
- `ar_state.story_goal`
- `ar_state.player_intent`
- `ar_state.active_characters`
- `ar_state.pending_choices`

Returns the updated `/api/state` snapshot.

### `POST /api/send`

Body:

```json
{
  "text": "Open the tavern door and step outside",
  "intent": "Auto",
  "speaker_id": ""
}
```

Queues the existing MPRC Play turn pipeline on the PC. Returns the immediate state snapshot. Poll `/api/state` for the completed reply.

### `POST /api/choice`

Body:

```json
{
  "choice": "1"
}
```

`choice` may be a 1-based choice id/index or direct text.

### `POST /api/play`

Starts/resumes the MPRC Play runtime. If the story has not started, it queues the existing opening turn.

### `POST /api/pause`

Stops current MPRC Play speech/playback and disables the active play session.

### `POST /api/visual`

Requests Visual Reply through the existing PC backend for the current story moment.

### `GET /api/audio-settings`

Returns the existing MPRC AudioFX/story audio settings snapshot.

## WebSocket

`/ws` is intentionally not implemented yet. The first version uses REST polling to avoid adding Python WebSocket dependencies. The Android app polls `/api/state`.
