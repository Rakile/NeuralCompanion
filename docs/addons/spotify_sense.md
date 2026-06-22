# Spotify Sense

Spotify Sense is an optional NeuralCompanion addon that connects to Spotify through the official Spotify Web API. It can read the current track, expose safe LLM-callable music tools, control playback when explicitly enabled, duck music while NC speaks, emit simple song-change or music-mood events for other addons, and provide hidden music awareness context to normal chat.

## Setup

1. Create an app in the Spotify Developer Dashboard.
2. Add this redirect URI exactly:

   `http://127.0.0.1:8765/spotify/callback`

3. Copy the app Client ID into the Spotify Sense addon tab.
4. Click **Save Settings**, then **Login / Connect**.
5. Approve the requested scopes in the browser and return to NeuralCompanion.
6. Enable **Spotify Sense**.
7. Optional: enable **Allow LLM Spotify control** if you want autonomous/model-initiated Spotify changes beyond direct user commands.

Required scopes:

- `user-read-playback-state`
- `user-modify-playback-state`
- `user-read-currently-playing`
- `playlist-read-private`
- `playlist-read-collaborative`

Spotify playback control usually requires Spotify Premium. Spotify Sense reports Premium/device/scope errors in the UI instead of crashing.

## Safety Defaults

Spotify Sense starts disabled. LLM control is off, autonomous music is off, and confirmation is required before playback changes. Reading the current track and background music awareness require Spotify Sense to be enabled and connected.

Direct user commands such as "play ambient electronic", "pause music", and "skip this" are treated as explicit user requests. They can run when Spotify is connected, even if **Allow LLM Spotify control** is off. Autonomous/tool-triggered music changes still respect **Allow LLM Spotify control**, **Require confirmation before changing music**, and the user-change lockout.

Tokens are stored only in local addon runtime storage. Do not commit runtime files or real Spotify credentials.

When music awareness is enabled, Spotify Sense sends only compact playback metadata to chat context. It never injects the Spotify access token, refresh token, Client ID, or other credentials into prompts.

## Tools And Hooks

The addon exposes these capabilities through the NC addon capability system:

- `spotify.current_track`
- `spotify.play_search`
- `spotify.play_playlist`
- `spotify.pause`
- `spotify.resume`
- `spotify.next`
- `spotify.previous`
- `spotify.volume`
- `spotify.shuffle`
- `spotify.repeat`
- `spotify.devices`
- `spotify.transfer_device`
- `spotify.add_to_queue`
- `spotify.commentary`
- `spotify.route_intent`
- `spotify.music_context`
- `spotify.duck.start`
- `spotify.duck.end`
- `spotify.story_hook`

The intent router is conservative. It maps obvious phrases like "skip this", "pause Spotify", "stop the music", "resume Spotify", "start music", "what song is this?", and "play relaxing focus music". Unclear requests fall through to the normal LLM reply.

Normal chat command flow:

1. The user says or types a clear Spotify command.
2. The engine asks addons whether the text is a direct command.
3. Spotify Sense routes the text to the safest matching Spotify tool.
4. If control is enabled and cooldowns allow it, Spotify Sense performs the API call before the assistant reply is generated.
5. If control is disabled, Spotify is disconnected, Premium/device scopes are missing, or a cooldown blocks the action, NC speaks the reason.
6. For successful `play ...` commands, NC receives one-turn hidden context saying the Spotify command already ran and what track or playlist was selected, so the LLM can respond naturally and talk about what is on.

Common voice commands:

- "play Master of Puppets with Metallica"
- "play ambient electronic"
- "play relaxing focus music"
- "pause music"
- "resume Spotify"
- "skip this"
- "next song and comment about it"
- "previous track"
- "what song is this?"
- "turn Spotify down"
- "turn Spotify up"

Add "and comment about it" to a playback command when you want the command to run first and then have NC briefly react to the new/current music in the normal assistant reply.

## Ducking And Story Mode

If **Duck music while NC speaks** is enabled, `spotify.duck.start` stores the current Spotify volume and lowers it to the configured duck volume. `spotify.duck.end` restores the remembered volume when restore is enabled. The hooks are safe if Spotify is disconnected; they return structured errors.

Use **Duck fade down** and **Duck fade up** to smooth the volume transition instead of jumping instantly when NC starts or stops speaking.

Story hooks are optional and respect **Story mode background music**, **Allow autonomous music**, and confirmation settings. Spotify Sense does not depend on the Multi Persona Roleplay addon and does not force music if there is no connected account or active device.

## Music Awareness In Chat

When **Enable music awareness in chat** is enabled, Spotify Sense keeps a small cached snapshot of the current Spotify playback and contributes it through NC's addon chat-context system. This lets the LLM know what is playing during normal replies without the user asking "what song is this?"

The Spotify Sense addon tab also has a **Now Playing** section. When **Album art thumbnail** is enabled, it shows a small album or single cover from Spotify metadata for the current track.

The hidden context can include:

- track name
- artists
- album
- play/pause state
- progress and duration
- active Spotify device
- playlist/context URI
- metadata-based mood hint

The LLM is instructed to treat this as ambient context, not as a direct user request. It should not mention the music every turn, and it should not claim to hear or analyze raw audio. Spotify Sense uses Spotify metadata only; it does not listen to the computer's audio stream.

The **Music response mode** controls how strongly NC uses the context:

- **Off**: no hidden music context is contributed.
- **Subtle**: quiet mood awareness; mention music only when useful.
- **Companion**: the music can become a small companion signal in suitable replies.
- **DJ / Music Critic**: allows a more playful music-commentary flavor when relevant.
- **Story soundtrack**: treats the current music as atmosphere for story, roleplay, and scene pacing.

**Include paused Spotify track context** allows the last paused track to stay visible to the LLM. Leave it off if paused music should be ignored.

## Song Change Awareness

When **Song-change monitor** is enabled, the addon polls current playback every seven seconds. On a track change it emits:

- `spotify_track_changed`
- `spotify_music_mood_changed`

If **Comment on song changes** is enabled, the next chat context may include a short optional song-change acknowledgement. The **Song-change comment cooldown** prevents repeated comments from becoming noisy.

The mood is inferred from Spotify metadata text only. Spotify Sense does not analyze raw audio.

## Hidden Responses And Cooldowns

Spotify Sense can be selected as a hidden sensory source, but its source guidance is managed inside the Spotify Sense addon tab instead of a separate Vision source tab. It does not continuously send Spotify snapshots to the hidden PING/PONG loop. It only offers a hidden Spotify snapshot when:

- Spotify Sense is enabled and connected.
- Music awareness is enabled.
- A fresh track-change acknowledgement is pending.
- **Comment on song changes** is enabled.
- **Hidden response cooldown** has elapsed.

This prevents periodic hidden music responses when nothing meaningful changed.

**User change lockout** protects manual Spotify choices. When Spotify Sense notices a track change that NC did not trigger, it treats it as an external/user change and waits for the configured lockout before NC may change playback again. Set this to `0s` if you want NC to be allowed to change Spotify immediately after user/external changes.

## Troubleshooting

- **Specific song does not start**: Enable **Debug log**, try the command again, then open the debug log from the Spotify Sense tab. Song-like commands such as "play Master of Puppets with Metallica" are routed as track-preferred searches.
- **No active device**: Start Spotify on a phone, browser, or desktop app and press **Refresh Devices**.
- **Premium required**: Spotify Web API playback control is limited for non-Premium accounts.
- **Invalid redirect URI**: The URI in the Spotify Developer Dashboard must match the addon redirect URI exactly.
- **Missing scopes**: Disconnect and reconnect after updating scopes.
- **Token expired**: The addon refreshes tokens automatically. If refresh fails, disconnect and reconnect.
- **Spotify desktop app not open**: Open Spotify or transfer playback to another listed device.
