# Neural Companion Discord Voice Bridge

Standalone Node transport for the Discord Voice Bridge addon.

It currently proves Discord voice transport before NC runtime wiring:

- logs in as the bot
- joins one configured voice channel
- optionally plays a short test tone
- captures user speech turns as WAV files in `captures/`
- in mock mode, writes a fake NC turn record in `turns/`
- in mock mode, plays a generated reply chime back into Discord

## Setup

Copy `.env.example` to `.env` and fill in:

```text
DISCORD_TOKEN=your_bot_token
DISCORD_GUILD_ID=optional_server_id
DISCORD_VOICE_CHANNEL_ID=your_voice_channel_id
DISCORD_ALLOWED_USER_ID=optional_your_user_id
DISCORD_PLAY_TEST_TONE=false
NC_BRIDGE_MODE=mock
DISCORD_MIN_TURN_SECONDS=0.6
```

Alternatively, point the bridge at the addon mock settings file:

```powershell
$env:NC_DISCORD_BRIDGE_SETTINGS_JSON="D:\tools\python_scripts\NeuralCompanion-dev\addons\discord_voice_bridge\settings.local.json"
npm start
```

Values from `.env` override values from the JSON settings file.

Install dependencies:

```powershell
npm install
```

Run:

```powershell
npm start
```

When `NC_BRIDGE_MODE=mock`, every captured speech turn will:

1. save the input WAV in `captures/`
2. ignore it if it is shorter than `DISCORD_MIN_TURN_SECONDS`
3. write a mock NC turn JSON file in `turns/`
4. write a generated mock reply WAV in `mock_replies/`
5. play the mock reply audio back into the Discord voice channel
