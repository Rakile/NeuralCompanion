# TTS Addon Latency Audit - 2026-07-17

## Scope

This note records the investigation into delays between a completed LLM reply
and the first audible TTS playback in NeuralCompanion.

- Repository: `Q:\AA NC\NeuralCompanion-dev`
- Local commit inspected: `2b03ad5`
- Online `origin/main` commit compared: `747ff82`
- Runtime used for live measurements: `Q:\AA NC\NeuralCompanion-dev_runtime`
- Fixes applied after the investigation: Spotify ducking, MPRC reply handling,
  Buddy settings persistence, and bounded latency tracing

## Conclusion

The low-latency text chunker was not the blocker. Three independent synchronous
addon operations could delay the path between a completed LLM reply and first
audio playback:

1. Spotify ducking waited on a Web API playback-state request with a 12-second
   timeout immediately before playback.
2. MPRC performed completed-reply bookkeeping, including a hidden AR provider
   request, inline while sharing its state lock with TTS routing.
3. Buddy Chat persisted its reply counters synchronously before TTS startup.

When MPRC Alternative Reality mode is active, the completed assistant reply can
trigger a hidden scene-state LLM request synchronously. This operation runs
while MPRC's shared state lock is held. TTS voice routing and generated audio
notifications use the same lock, so they can wait behind that request.

This can explain a five-to-eight-second interval where the main LLM reply is
already visible in the console but TTS has not started playing.

## Confirmed Blocking Paths

### 1. Completed-reply processing before non-streamed TTS

`engine.finalize_assistant_reply()` synchronously calls
`roleplay.assistant_reply` before returning the text to `speak_async()`.

Relevant code:

- `engine.py:5556-5567`
- `engine.py:12162-12169`
- `addons/multi_persona_roleplay/controller.py:728-752`
- `addons/multi_persona_roleplay/roleplay_engine.py:83-121`

In Alternative Reality mode, `record_assistant_text()` calls
`record_ar_reply()`, which calls `_update_ar_state_from_reply()`. That method can
make another provider request using Instructor or `_chat_completion_create()`.

Relevant code:

- `addons/multi_persona_roleplay/controller.py:1987-2011`
- `addons/multi_persona_roleplay/controller.py:2013-2091`

The hidden request has a configured timeout of at least 45 seconds. Its normal
latency can therefore directly delay TTS startup.

### 2. MPRC state-lock contention across TTS capabilities

`MultiPersonaRoleplayController.invoke_capability_threadsafe()` acquires
`_state_lock` before dispatching every capability except `real_ui.*`. This also
means unsupported capabilities wait for the lock before returning `None`.

The affected response path includes:

- `tts.voice_segments.requires_full_text`
- `tts.voice_segments`
- `tts.voice_route`
- `tts.audio_chunk_ready`
- `roleplay.assistant_reply`

A direct contention probe held `_state_lock`, invoked all five capabilities on
separate threads, and checked them after 180 ms. All five remained blocked until
the lock was released.

Idle MPRC calls were fast when the lock was uncontended. The problem is
conditional lock contention, not ordinary capability-dispatch overhead.

### 3. Synchronous generated-audio notification

After generating and writing a WAV file, the TTS generator calls
`_notify_addon_tts_audio_chunk_ready()` before the chunk enters the playback
pipeline.

Relevant code:

- `engine.py:9390-9405`
- `engine.py:1547-1555`
- `addons/multi_persona_roleplay/controller.py:748-749`

MPRC handles this notification while holding `_state_lock`. Audio capture,
file-copying, or other work in the handler can therefore delay playback even
after speech synthesis has completed.

### 4. Avatar preprocessing before playback

Generated audio also passes through `avatar_gui.process_audio_chunk()` before
it enters the ready-for-playback queue.

Relevant code:

- `engine.py:9508-9515`

This is effectively immediate with the `None` avatar. MuseTalk or another
rendering avatar can add a genuine preprocessing delay. This behavior also
exists upstream and is not specific to the recent Buddy Chat changes.

## Local Versus Online Engine Differences

The local engine adds a synchronous stream-policy fanout before starting the
streamed LLM and TTS workers:

- `engine.py:1421-1428`
- `engine.py:12142-12158`

This call asks all initialized addons for
`tts.voice_segments.requires_full_text`. MPRC does not implement that
capability, but its current dispatcher still acquires `_state_lock` before
returning `None`. A busy MPRC lock can therefore delay stream startup.

The following hooks are also present in online `origin/main` and are not purely
local additions:

- `roleplay.assistant_reply`
- `tts.audio_chunk_ready`
- playback voice-volume routing

The local code exposes an existing synchronous-addon design risk more often;
it did not create every blocking hook.

## Buddy Chat Findings

Buddy Chat currently returns `requires_full_text: False` from
`_requires_full_text_voice_segments()`. It therefore no longer intentionally
buffers the complete streamed response before starting TTS.

Relevant code:

- `addons/buddy_chat/controller.py:533-549`
- `engine.py:10462-10479`

Completed Buddy responses can use a smaller first TTS segment of approximately
20-30 characters. This is intended to reduce, not increase, time to first
speech.

Buddy's completed-reply notification does synchronously save its updated reply
counter. That is normally a small disk operation and is a secondary risk, not
the strongest explanation for a repeatable five-to-eight-second delay.

## Live TTS Measurements

With Chatterbox, `None` avatar mode, and prepared Buddy voice paths, observed
model times were:

- cached first chunk: approximately 1.0-1.9 seconds
- uncached voice chunk: approximately 2.8 seconds
- later larger chunks: approximately 3.4-4.6 seconds

Later chunks can generate while an earlier chunk plays. These measurements show
that raw first-chunk synthesis alone does not account for a consistent
five-to-eight-second post-LLM pause.

## Companion Orb Finding

A stale Companion Orb sensory target can synchronously refresh a desktop
snapshot and run OCR while the main chat request is being built. OCR fallbacks
can wait for four- and six-second timeouts.

This delay occurs before the main LLM request, so it does not match the symptom
where the LLM reply has already completed and TTS is still waiting.

## Applied Fix

- Spotify playback-state lookup and volume ducking are queued on a background
  worker. Audio playback no longer waits for Spotify networking.
- MPRC rejects unsupported capabilities before taking `_state_lock` and queues
  main-chat reply bookkeeping on a serialized background worker.
- MPRC snapshots persistent state under its lock and performs disk writes after
  releasing it.
- MPRC voice-routing diagnostics use a bounded ordered background writer rather
  than appending JSON on the TTS routing thread.
- MPRC phone-remote WAV capture uses an ordered background copy queue, so local
  playback does not wait for filesystem or antivirus latency.
- MPRC persona-state changes triggered at segment start are persisted by a
  coalescing background writer rather than the playback worker.
- Buddy Chat rejects unsupported capabilities before taking its lock and
  coalesces hot-path settings writes on a background writer.
- Buddy's `requires_full_text` policy remains false.

## Runtime Diagnostics

`runtime/logs/tts_addon_latency.jsonl` now records:

- assistant finalization duration;
- TTS pipeline start, generation duration, first WAV readiness, and playback
  start;
- addon ID, capability, duration, handled state, thread, and error class for
  every TTS-critical addon call;
- any non-critical addon call that takes at least 100 ms.

The trace contains timing metadata only, is capped at 2 MB with one rotated
copy, and is included explicitly in NC debug bundles. It does not store prompts,
responses, pairing data, API keys, tokens, or addon payloads.

## Comparing Another Installation

A working installation can provide a useful control sample. Run the same short
normal-chat reply once with Buddy Chat, MPRC, and Spotify Sense enabled, then
attach its debug bundle. Compare Git commit, Python/package versions, addon
settings flags, and `tts_addon_latency_tail.jsonl`. Do not exchange provider
configuration files or credentials.
