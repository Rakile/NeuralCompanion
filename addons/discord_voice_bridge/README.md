# Discord Voice Bridge

For normal setup, follow the [Discord Voice and rooms guide](../../docs/addons/discord_voice.md).
For a desktop-only discussion with no Discord accounts, use [Local Room](../../docs/addons/local_room.md).
Open **Addons → Discord Voice**; the shared room interface is in **Local room**.

## Current user workflow

1. In **Discord → Bot accounts**, use **Add account** for each bot token. Saving
   checks the token; **Check all accounts** refreshes all saved checks. Supply the
   shared **Server ID** and **Voice channel ID** and invite each bot to the server.
2. In **Local room**, choose **Room transport → Discord** while stopped. Add saved
   Personas, assign a different **Prepared bot** to each, and choose a moderator.
3. Use **Start room** or **Continue conversation**. NC manages its Node bridge
   processes and isolated NC endpoints. Join the channel in Discord to speak.
4. Use **Open conversation** for the room feed. **Send as** chooses a human or
   **NC operator** for typed room context; it does not post Discord text messages.

Install Node.js/npm if needed. Use **Install / Update Node Deps** when setup
validation reports missing bundled transport dependencies. Stop bridges before
installing or updating dependencies. Normal use does not require separate
`npm start`, Python bridge consoles, or a manually started TinyMVP server.

Bot checks validate credentials, not invitations or voice permissions. Persona
names are applied as server nicknames when permitted; global account names are
not changed. The user guide covers live membership, no-catch-up Persona memory,
incoming-voice acceptance, protected speech, moderator handoffs and transcript
versus full-reply preview behavior.

## Runtime architecture

The addon registers the settings workspace and manages an isolated room runtime:

```text
Discord voice channel
  -> bundled Node transport
  -> localhost NC addon endpoint
  -> selected STT, chat and TTS providers
  -> Node transport -> Discord voice channel
```

The HTTP turn loop does not append to Main Chat history or play its reply through
normal local Main Chat playback. Shared Local/Discord rooms also coordinate
speaker ownership, heard-only Persona context, graceful holds and continuation.
The selected providers must be ready; enabling the addon alone does not load a
working STT/chat/TTS stack. Main Chat and rooms share runtime resources and are
mutually exclusive.

`node_bridge/` contains the real Discord transport. `tiny_mvp/` contains the
bundled fake voice-room service and Python bridge for local testing. In legacy
`bridge_mode: tiny_mvp` operation NC checks the configured fake-room endpoint and
starts the bundled server when needed, then launches its bridge processes. An
already reachable external server remains externally owned. The normal **Local**
room uses the managed local runtime and needs no Discord token.

Defaults are in `settings.example.json`, schema metadata in
`settings_schema.json`, and ignored local overrides in `settings.local.json`.
No real credentials belong in source control. The following sections document
advanced/standalone integration; use the linked user guides for normal setup.

## Local Room conversation behavior

Use **Open conversation** to follow the room in the main **Conversation** tab.
Its **Main chat / Local room / Discord room** selector changes the displayed conversation only;
room messages and input stay separate from the main chat. Room controls remain
available from that full-size conversation view. Reading position and drafts are
kept when switching views.

Normal chat and Local room cannot run together, including Text only mode and
normal chat replay. If normal chat is initialized, starting or continuing a room
asks before stopping it. Once it has stopped, the usual **Save / Don't Save /
Cancel** prompt handles unsaved main-chat changes before clearing its loaded
context and starting the room. A saved main chat can be loaded again later.
Cancelling the save prompt keeps its context and does not start the room; the
engine remains stopped after the earlier explicit switch confirmation.

In the dedicated Local Room view, open **Room controls → Conversation behavior**.
Choose automatic AI selection, names/questions, or manual speaker selection. The
same rule applies to normal turns and moderator handovers. Manual mode waits for
Speak next or Let me speak and disables automatic moderator recovery.

Moderator help defaults to both human and AI speech, with **0 seconds** of added
delay. A longer delay leaves time to jump in. With preparation enabled, generation
and audio preparation overlap that delay; playback waits until the current turn
finishes, the delay expires, and the floor is free. Human speech, replacement Next,
immediate Stop speech & hold and behavior changes cancel unheard preparations.
Pause room lets the current speaker finish, then keeps the next speaker and any
prepared reply waiting until Resume; a long pause does not expire that reply.
Stop room also lets the current speaker finish, saves the next speaker, listener
mutes and speaker lock, then shuts down the room. Continue conversation restores
that handoff and each participant's saved heard history, including after an NC
restart. Speech is prepared again after a stopped room is continued. Pending
moderator guidance is retained too. Already audible speech finishes when changing behavior. Advanced options expose repeat speakers,
preparation, recovery triggers, cooldown and speaker-selection instructions.

**Save behavior** persists only `local_room.behavior`; it does not edit Persona
profiles or shared Discord routing settings. The room summary shows the saved
rules and speaker lock even when Room controls is closed. Draft edits stay local
until saved.

## Developer reference: settings and standalone launch

Normal users configure accounts and rooms in NC. For an externally managed
standalone bridge or developer fixture, copy:

```text
settings.example.json -> settings.local.json
```

Then fill in non-secret values such as server ID, voice channel ID, allowed user
ID, silence cutoff, and minimum turn length.

For legacy standalone bridge use, automatic startup on addon load is controlled
by **Start bridge when NC launches**, corresponding to:

```json
"start_on_nc_launch": true
```

For an environment-managed credential, store the token in the variable named by:

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
$env:NC_DISCORD_BRIDGE_SETTINGS_JSON = (Resolve-Path addons\discord_voice_bridge\settings.local.json).Path
Set-Location addons\discord_voice_bridge\node_bridge
npm start
```

When started by NC, bridge stdout/stderr is written to:

```text
addons/discord_voice_bridge/runtime_logs/discord_voice_bridge.log
```

## Developer reference: standalone multi-bot settings

One addon can launch multiple Discord bot instances from `settings.local.json`.
Each bot gets its own Discord token/channel settings, localhost runtime port,
Node process, isolated Discord chat history, optional persona prompt, and
optional voice clone WAV.

If `bots` is empty or missing, the top-level single-bot settings are used.
If `bots` contains entries, each enabled entry is merged over the top-level
settings. Bot entries can override only the fields that differ.

For normal shared rooms, use **Bot accounts** and assign them to Persona cards
in **Local room → Discord**. The legacy structured Bots controls are hidden in
the current UI. Advanced standalone settings can still be supplied through the
local JSON file; keep per-bot credentials, IDs and runtime ports distinct.

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
global voice fallback; linked room Personas resolve their own saved voice settings.

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
  before starting NC, or enter a local test token in **Bot accounts**.
- If validation says Node.js is missing, install Node.js and restart NC so
  `node.exe` is available on PATH.
- If validation says Node bridge dependencies are missing or incomplete, run
  `Install / Update Node Deps` from the **Status** section,
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

## Developer checks

These offline developer checks run from the repository root:

```powershell
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
