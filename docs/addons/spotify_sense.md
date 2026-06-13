# Spotify Sense

Spotify Sense is an optional NeuralCompanion addon that connects to Spotify through the official Spotify Web API. It can read the current track, expose safe LLM-callable music tools, control playback when explicitly enabled, duck music while NC speaks, emit simple song-change or music-mood events for other addons, and provide hidden music awareness context to normal chat.

## Setup

1. Create an app in the Spotify Developer Dashboard.
2. Add this redirect URI exactly:

   `http://127.0.0.1:8765/spotify/callback`

3. Copy the app Client ID into the Spotify Sense addon tab.
4. Click **Save Settings**, then **Login / Connect**.
5. Approve the requested scopes in the browser and return to NeuralCompanion.

Required scopes:

- `user-read-playback-state`
- `user-modify-playback-state`
- `user-read-currently-playing`
- `playlist-read-private`
- `playlist-read-collaborative`

Spotify playback control usually requires Spotify Premium. Spotify Sense reports Premium/device/scope errors in the UI instead of crashing.

## Safety Defaults

Spotify Sense starts disabled. LLM control is off, autonomous music is off, and confirmation is required before playback changes. Reading the current track is safe once the addon is enabled and connected, but playback commands are blocked until the user enables LLM control and confirms the action.

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

The intent router is conservative. It maps obvious phrases like "skip this", "pause Spotify", "what song is this?", and "play relaxing focus music". Unclear requests return a preview route and should ask for confirmation.

## Ducking And Story Mode

If **Duck music while NC speaks** is enabled, `spotify.duck.start` stores the current Spotify volume and lowers it to the configured duck volume. `spotify.duck.end` restores the remembered volume when restore is enabled. The hooks are safe if Spotify is disconnected; they return structured errors.

Story hooks are optional and respect **Story mode background music**, **Allow autonomous music**, and confirmation settings. Spotify Sense does not depend on the Multi Persona Roleplay addon and does not force music if there is no connected account or active device.

## Music Awareness In Chat

When **Enable music awareness in chat** is enabled, Spotify Sense keeps a small cached snapshot of the current Spotify playback and contributes it through NC's addon chat-context system. This lets the LLM know what is playing during normal replies without the user asking "what song is this?"

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

## Troubleshooting

- **No active device**: Start Spotify on a phone, browser, or desktop app and press **Refresh Devices**.
- **Premium required**: Spotify Web API playback control is limited for non-Premium accounts.
- **Invalid redirect URI**: The URI in the Spotify Developer Dashboard must match the addon redirect URI exactly.
- **Missing scopes**: Disconnect and reconnect after updating scopes.
- **Token expired**: The addon refreshes tokens automatically. If refresh fails, disconnect and reconnect.
- **Spotify desktop app not open**: Open Spotify or transfer playback to another listed device.
