# Discord Voice Bridge

Addon for connecting Neural Companion to a Discord voice channel.

The addon runs Discord voice turns through an isolated Discord-only chat loop. It
can use the selected NC STT, chat, and TTS providers without appending to the
normal Chat tab history.

The Discord transport lives in `node_bridge/`. For local non-Discord testing,
Bridge mode can also launch the TinyMVP Python bridge against a local fake
voice-room server. The addon tab exposes local settings, runtime controls,
status, recent logs, a structured multi-bot editor, and advanced multi-bot JSON
overrides for unusual cases.

When `bridge_mode` is `http`, the addon also starts a localhost endpoint. The Discord bridge posts captured WAV files to this endpoint, and the addon handles an isolated Discord-only turn:

1. transcribe with the selected NC STT backend
2. generate a reply with the selected NC chat provider/model
3. synthesize with the selected NC TTS backend
4. return the reply WAV path to the Node bridge

This does not append to normal NC chat history and does not trigger normal NC local audio playback.

When `bridge_mode` is `tiny_mvp`, the addon still starts the same localhost NC
runtime endpoints, but launches `tiny_voice_bridge.py` instead of the Discord
Node bridge. The TinyMVP server must already be running, for example:

```powershell
cd D:\tools\python_scripts\TinyMVP
python main.py
```

Then choose `TinyMVP local room` in the Discord Voice tab, set the TinyMVP room
URL if needed, save settings, and press `Start Bridge`. Each configured bot is
started as a local TinyMVP bridge process pointed at its own NC `/turn`
endpoint.

## Intended Shape

```text
Discord voice channel
  -> Node bridge
  -> NC addon bridge endpoint, isolated Discord chat loop
  -> selected STT provider
  -> selected chat provider
  -> selected TTS provider
  -> Node bridge
  -> Discord voice channel
```

TinyMVP local room:

```text
TinyMVP fake voice room
  -> tiny_voice_bridge.py
  -> NC addon bridge endpoint, isolated Discord chat loop
  -> selected STT/chat/TTS providers as applicable
  -> tiny_voice_bridge.py
  -> TinyMVP fake voice room playback/event state
```

## Implemented Scope

- Python addon entry point loads safely and exposes a Discord Voice settings tab.
- Node bridge can run one or multiple Discord bot processes.
- Defaults live in `settings.example.json`; local overrides are saved in ignored `settings.local.json`.
- `settings_schema.json` describes the settings metadata used by the addon UI.
- No secrets are stored in the repository.
- The bridge keeps Discord chat history isolated from normal NC chat history.

## Discord Setup

1. Create a Discord application in the Discord Developer Portal.
2. Add a Bot user to the application.
3. Enable the bot permissions needed for the target server:
   - View Channels
   - Connect
   - Speak
4. Invite the bot to your server with the generated OAuth2 URL.
5. Enable Discord Developer Mode in the Discord client.
6. Copy the server/guild ID and target voice channel ID into the Discord Voice tab.
7. Store the bot token in an environment variable, or enter a local test token in
   the Discord tab or structured bot editor for private local testing.
8. Install the bundled Node bridge dependencies once:

   ```powershell
   cd addons\discord_voice_bridge\node_bridge
   npm install
   ```

Prefer environment variables for tokens. Local token fields are ignored by git
through `settings.local.json` and are write-only in the UI.

## Settings

For local testing, either use the Discord Voice tab or copy:

```text
settings.example.json -> settings.local.json
```

Then fill in non-secret values such as server ID, voice channel ID, allowed user
ID, silence cutoff, and minimum turn length.

To start the bridge automatically when NC loads the addon, enable
`Start bridge when NC launches` or set:

```json
"start_on_nc_launch": true
```

The Discord token should remain outside the settings JSON. Store it in the environment variable named by:

```json
"discord": {
  "token_env_var": "DISCORD_TOKEN"
}
```

The Node bridge uses the exact configured `token_env_var`. In multi-bot setups,
each bot's token environment variable must be present; a missing per-bot token
does not fall back to the generic `DISCORD_TOKEN`.

The bundled Node bridge can consume the addon settings file with:

```powershell
$env:NC_DISCORD_BRIDGE_SETTINGS_JSON="D:\tools\python_scripts\NeuralCompanion-dev\addons\discord_voice_bridge\settings.local.json"
npm start
```

When started by NC, bridge stdout/stderr is written to:

```text
addons/discord_voice_bridge/runtime_logs/discord_voice_bridge.log
```

## UI Runtime Controls

The Discord Voice tab can:

- save local settings
- start, stop, or restart the bridge
- show per-instance Node/runtime endpoint status
- show recent bridge logs
- open the runtime log folder
- validate launch settings before starting the bridge
- install or update the bundled Node bridge dependencies with `npm install`
- copy a redacted diagnostics bundle for support/debugging
- arm a one-shot quiet test tone and restart the bridge to verify Discord playback
- edit capture, playback, response-filter, persona, runtime, cleanup, and
  bot-instance settings
- add/remove bot instances without hand-editing JSON
- keep direct local tokens hidden; token fields are write-only and local

Start/stop/restart operations run in a background thread so the GUI should not
freeze during normal bridge control operations.

The test-tone action enables `play_test_tone_on_join` only for the restart it
launches, then turns the setting back off in `settings.local.json`. This avoids
surprising users with a tone on every later launch.

The validator checks the effective bot settings that would launch: unique bot
IDs, token source, guild/server ID, voice channel ID, unique localhost runtime
ports, whether the runtime host has been changed away from localhost, and
whether the bundled Node bridge dependencies have been installed. Start/restart
refuses to launch when validation finds errors.

Copy Diagnostics places a redacted bundle on the clipboard containing current
status, validation results, and recent logs. It is intended for debugging setup
issues without sharing token-like secrets.

## Multiple Bot Instances

One addon can launch multiple Discord bot instances from `settings.local.json`.
Each bot gets its own Discord token/channel settings, localhost runtime port,
Node process, isolated Discord chat history, optional persona prompt, and
optional voice clone WAV.

If `bots` is empty or missing, the top-level single-bot settings are used.
If `bots` contains entries, each enabled entry is merged over the top-level
settings. Bot entries can override only the fields that differ.

Use the structured Bots editor for normal setup. The local token field is
write-only: leave it blank to keep any existing ignored local token, or enter a
new test token to save it into `settings.local.json`. Prefer token environment
variables for normal use. The advanced JSON editor remains available for fields
that do not yet have dedicated controls.

Example:

```json
{
  "enabled": true,
  "start_on_nc_launch": true,
  "bridge_mode": "http",
  "discord": {
    "guild_id": "121212121212121212",
    "voice_channel_id": "343434343434343434",
    "answer_mode": "anyone"
  },
  "bots": [
    {
      "id": "echo",
      "call_names": "Echo",
      "discord": {
        "token_env_var": "DISCORD_TOKEN_ECHO"
      },
      "nc_runtime": {
        "port": 8768
      },
      "persona": {
        "system_prompt": "You are Echo, a warm and curious Discord voice companion.",
        "replace_nc_system_prompt": true,
        "voice_clone_wav": "echo.wav"
      }
    },
    {
      "id": "nova",
      "call_names": "Nova",
      "discord": {
        "token_env_var": "DISCORD_TOKEN_NOVA"
      },
      "nc_runtime": {
        "port": 8769
      },
      "persona": {
        "system_prompt": "You are Nova, a playful debate partner who keeps replies brief.",
        "replace_nc_system_prompt": true,
        "voice_clone_wav": "nova.wav"
      }
    }
  ]
}
```

For private local testing, a bot entry may use `discord.token`, but real use should
prefer environment variables. Status output redacts token-like fields.

Relative `persona.voice_clone_wav` values are loaded from NC's root `voices`
folder, matching the normal Persona tab. Leave it blank or omit it to use the
voice selected in NC's global Persona tab.

## Privacy And Security

- Discord voice audio and transcripts are untrusted input.
- Do not paste token values into logs, screenshots, GitHub issues, or Discord.
- Keep `nc_runtime.host` on `127.0.0.1`, `localhost`, or `::1` unless you are
  deliberately exposing the bridge on a trusted network.
- Non-localhost runtime hosts are blocked by default; enable the advanced
  non-localhost override only for a trusted private network.
- The bridge does not execute transcript text and does not shell out with user
  speech.
- Captured WAVs and generated reply WAVs are local debug artifacts and are
  cleaned by the configured cleanup timer.
- Disable `capture.save_captures` if you do not want captured user audio kept
  for debugging.

## Troubleshooting

- If validation fails with a missing token, set the named environment variable
  before starting NC, or enter a local test token in the bot editor.
- If validation says Node.js is missing, install Node.js and restart NC so
  `node.exe` is available on PATH.
- If validation says Node bridge dependencies are missing or incomplete, run
  `Install / Update Node Deps` from the Discord Voice status/diagnostics tab,
  or run `npm install` in `addons/discord_voice_bridge/node_bridge`. Stop the
  bridge before installing or updating Node dependencies.
- If the bot does not join, verify the server/guild ID, voice channel ID, and
  bot permissions.
- If the bot joins but is silent, use `Play Test Tone On Restart` to verify
  Discord playback, then check selected NC TTS readiness.
- If STT creates tiny junk turns, raise `Minimum turn length`, keep
  low-information filtering enabled, or add exact junk phrases to the filter.
- If two bots answer at once, enable reply floor coordination and ensure each bot
  has a unique runtime port.
- If Discord replies should use the simple NC RAG database, enable `Use selected
  RAG context` in the Runtime tab and make sure the RAG Context addon is enabled
  and indexed.
- Use `Copy Diagnostics` before sharing logs; raw log files may include local
  file paths.

## Local Smoke Test

Run this from the NC repo root before runtime testing:

```powershell
python addons\discord_voice_bridge\smoke_discord_voice_bridge.py
node --check addons\discord_voice_bridge\node_bridge\src\index.js
```

The smoke test checks settings validation, token preservation, and redaction. It
does not connect to Discord or call NC model providers.

## Runtime Test Checklist

Before release or wider use, runtime-test:

1. single bot join, capture, STT, chat, TTS, and playback
2. interruption and reply-immunity behavior
3. short junk clips and `__NC_NO_REPLY__` silence
4. multiple bots with reply-floor coordination
5. per-bot voice clone WAVs from the root `voices/` folder
6. simple RAG context injection when RAG Context is enabled and indexed
