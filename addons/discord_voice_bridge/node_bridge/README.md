# Discord Voice Bridge Node transport

For normal NC setup, use the [Discord room guide](../../../docs/addons/discord_voice.md).
**Addons → Discord Voice** manages the Node processes and localhost NC endpoints;
**Install / Update Node Deps** installs this transport's dependencies. You do not
need to start a separate Node process for a room launched by NC.

This transport logs in as a Discord bot, joins a configured voice channel,
captures incoming speech, and sends turns to the isolated NC runtime. HTTP mode
receives streamed reply audio/events and plays them into Discord. Shared rooms
also coordinate membership, routing, turn ownership and delivered-history
acknowledgments. Mock mode can test transport without NC model calls.

## Standalone developer setup

Run these commands only when deliberately managing a standalone transport. Do
not run a second copy using the same bot account as an NC-managed room.

From the repository root:

```powershell
Set-Location addons\discord_voice_bridge\node_bridge
npm install
```

Copy `.env.example` to `.env` and configure the bot and voice channel. For a
transport-only mock test:

```text
DISCORD_TOKEN=your_bot_token
DISCORD_GUILD_ID=optional_server_id
DISCORD_VOICE_CHANNEL_ID=your_voice_channel_id
DISCORD_ALLOWED_USER_ID=optional_your_user_id
DISCORD_PLAY_TEST_TONE=false
NC_BRIDGE_MODE=mock
DISCORD_MIN_TURN_SECONDS=0.6
```

Then run `npm start` from this directory. Environment values override JSON
settings. Keep real tokens in ignored local files or environment variables.
For a standalone launch using addon JSON instead, start from the repository root:

```powershell
$env:NC_DISCORD_BRIDGE_SETTINGS_JSON = (Resolve-Path addons\discord_voice_bridge\settings.local.json).Path
Set-Location addons\discord_voice_bridge\node_bridge
npm start
```

In `mock` mode, an accepted captured turn saves an input WAV under `captures/`,
filters clips shorter than the configured minimum, records a mock turn under
`turns/`, generates a reply chime under `mock_replies/`, and plays it into the
channel. This confirms transport only; it does not prove NC STT, chat or TTS.
For real model turns use the NC-managed HTTP endpoints and settings described
in the [addon technical reference](../README.md).

