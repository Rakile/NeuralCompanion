# TinyMVP Fake Voice Channel

TinyMVP is a tiny standalone fake voice-channel service for reasoning about Discord Voice Bridge behavior without connecting to Discord.

It is intentionally simple. It does not control Neural Companion directly. Instead, NC's Discord Voice Bridge addon can launch local TinyMVP bridge processes that send commands to TinyMVP over HTTP, similar to how the Discord bridge reacts to a real room.

TinyMVP keeps transparent local state:

- participants
- connected/disconnected state
- Current speaker
- Next speaker
- queued audio count
- playback state
- route-flow timeline

There is also an optional monitor window. It displays room state and exposes a few local test controls for stopping playback and clearing current/next state.

## Run

Start the fake channel server:

```powershell
cd D:\tools\python_scripts\TinyMVP
python main.py
```

Default URL:

```text
http://127.0.0.1:8788
```

Open the passive monitor in another terminal:

```powershell
cd D:\tools\python_scripts\TinyMVP
python main.py --monitor
```

The monitor uses Tkinter from the Python standard library. No PySide6 is required.

## Local NC Voice Bridge

`tiny_voice_bridge.py` is the Discord-bridge substitute. Start one bridge process per bot you want to represent in the fake room.

Example for Echo:

```powershell
cd D:\tools\python_scripts\TinyMVP
python tiny_voice_bridge.py --bot-id echo --bot-name Echo --tiny-url http://127.0.0.1:8788 --nc-turn-url http://127.0.0.1:8768/turn
```

Example for Nova:

```powershell
python tiny_voice_bridge.py --bot-id nova --bot-name Nova --tiny-url http://127.0.0.1:8788 --nc-turn-url http://127.0.0.1:8769/turn
```

Optional local microphone capture can be enabled on bridge processes. TinyMVP elects one connected bot as the capture owner, similar to the Discord bridge. Only the owner activates microphone input; if that bot disconnects, ownership moves to the next connected bot. Press Enter in the capture-owner bridge console to record a fixed-length human utterance, send it through NC STT/router, and publish the transcript plus route decision into TinyMVP:

```powershell
python tiny_voice_bridge.py --bot-id echo --bot-name Echo --tiny-url http://127.0.0.1:8788 --nc-turn-url http://127.0.0.1:8768/turn --capture-mic --mic-user-id rakila --mic-user-name Rakila --mic-seconds 6
```

Microphone capture uses the optional `sounddevice` Python package when available. The recorded WAV is saved as 16 kHz mono 16-bit PCM under `mic_captures`. If several bot bridges are started with `--capture-mic`, only the current TinyMVP capture owner will actually prompt for recording.

How it works:

1. The bridge registers its bot in TinyMVP.
2. It watches the TinyMVP route flow.
3. When a route targets its bot id, it sends the latest fake speech text to the NC `/turn` endpoint.
4. NC returns TTS WAV chunks as NDJSON events.
5. The bridge sends those WAV paths back to TinyMVP `/play`.
6. When the reply is complete, the bridge records the bot reply as fake room speech.

This is intentionally a local substitute for Discord voice routing, not a full Discord emulator.

## API

Inspect state:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/state
```

Register or update a participant:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/participants/upsert -Method Post -ContentType 'application/json' -Body '{"id":"echo","name":"Echo","type":"bot","connected":true}'
```

Simulate speech:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/speech -Method Post -ContentType 'application/json' -Body '{"speaker_id":"rakila","text":"Hello room"}'
```

Route next speaker:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/route -Method Post -ContentType 'application/json' -Body '{"target_id":"echo","reason":"test route"}'
```

Call a participant now:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/call -Method Post -ContentType 'application/json' -Body '{"target_id":"nova","reason":"call now"}'
```

Trigger dead-air recovery:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/dead-air -Method Post -ContentType 'application/json' -Body '{"reason":"room quiet"}'
```

Send a moderator command:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/moderator -Method Post -ContentType 'application/json' -Body '{"action":"moderator_route_next","target_bot_id":"echo","reason":"human moderator"}'
```

Play a WAV as a bot:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/play -Method Post -ContentType 'application/json' -Body '{"speaker_id":"echo","wav_path":"D:\\path\\to\\reply.wav"}'
```

Stop playback:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/stop -Method Post -ContentType 'application/json' -Body '{}'
```

End-to-end local route example:

```powershell
Invoke-RestMethod http://127.0.0.1:8788/speech -Method Post -ContentType 'application/json' -Body '{"speaker_id":"rakila","text":"Echo, what do you think?"}'
Invoke-RestMethod http://127.0.0.1:8788/route -Method Post -ContentType 'application/json' -Body '{"target_id":"echo","reason":"manual local route"}'
```

## Validate

```powershell
cd D:\tools\python_scripts\TinyMVP
python -m py_compile main.py
python -m py_compile tiny_voice_bridge.py
python main.py --self-test
python tiny_voice_bridge.py --self-test
```

## What This Is For

- Visualizing which participant is Current or Next
- Testing route-flow wording and state transitions
- Receiving fake room commands from another local bridge process
- Starting local bot bridge processes instead of Discord bot processes
- Testing local WAV playback state
- Sending local microphone speech into the fake room through NC STT/router
- Exploring moderator/dead-air behavior before trying it in Discord

## What This Is Not

- Not a Discord client
- Does not replace NC's Discord addon UI yet
- No built-in STT, TTS, LLM, database, or Discord API; microphone mode delegates STT/routing to a running NC Discord bridge endpoint
- No room-control GUI
- Not a replacement for real Discord runtime QA
