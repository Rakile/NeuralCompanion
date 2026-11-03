# Chat and Story Soundscape

Soundscape adds optional ambience and music to **Android Main Chat Remote**. It starts Off. It uses the existing NC audio-focus owner, foreground service, authenticated LAN connection, and encrypted relay connection. It does not create speech tickets, wait for background tracks to end, or change chat/Continuous Mode completion receipts.

## Using it

1. Open **Response controls → Soundscape**. Long-press that button to toggle its shortcut in the hideable chat menu.
2. Open **Library** and import audio, or use **Generate** to create a sound with the desktop's ElevenLabs configuration.
3. Choose **Use Ambience** or **Use Music**. This selects the sound and starts Soundscape in one action. Each layer has its own volume and mute control; default layer volumes are 20% and 15%.
4. Keep **Lower background during speech** on to reduce both layers while assistant or automated-user speech is actually audible. Short speech gaps retain ducking; prebuffering alone does not duck the mix.
5. **Pause** affects background audio only. **Resume** is an explicit playback request. Preview is a single foreground audition; it temporarily pauses the mix, and Stop preview returns to eligible background playback.

Soundscape remains available during ordinary chat and Main Chat Story Plan sessions. The separate Multi Persona Roleplay phone interface is not changed. iOS does not expose the new Android controls.

### Imports and library

- Phone: MP3, M4A, AAC, Ogg/Opus, up to 20 files per batch.
- Desktop: Main Chat Remote's **Import files** / **Import folder / AudioFX** controls also accept WAV and FLAC. Existing AudioFX files can be selected explicitly from their folder; their settings and originals remain untouched.
- Each input is limited to 100 MiB and 30 minutes. Folder imports are nonrecursive, reject directory links, and require smaller batches when more than 20 audio files are found.
- Identical imports reuse an existing library item rather than merging or replacing its metadata. Edit the saved title, description, category, tags, individual sound volume and loop preference in Library. Older sounds default to **Uncategorized** and 100% sound volume.
- The sound's volume multiplies its ambience/music layer volume. Preview also honors the individual sound volume. Library category filters and search use saved metadata, while audio files retain stable internal IDs.
- Removing a selected sound is refused until it is cleared from its conversation. Saved story versions keep independent audio copies.

### ElevenLabs generation

Generation uses Voice Studio's existing ElevenLabs key source. The key stays on the desktop. Ambience/effects use Sound Effects v2 (0.5–30 seconds); music uses Music v1 (30, 60, 120 or 180 seconds), with instrumental output selected by default.

Every **Generate now** or confirmed **Regenerate** is an explicit paid provider request. Preview and Save use the same generated artifact and do not submit another generation. Saving adds it to the library without selecting it. Cancellation cannot undo provider charges for an already submitted request. Ambiguous outcomes are marked unknown and never retried automatically. Unsaved drafts expire after seven days; journal receipts prevent duplicate submissions.

The phone's **Batch** tab offers eight editable sound-effect categories with twelve named prompts each. Review the entire list and confirm before any paid request. The phone submits each item with a durable idempotency ID to the existing desktop job queue; the queue processes requests one at a time. It saves completed effects to the library with the reviewed title, category and searchable tags. Batch progress and request IDs are kept in alternating private phone files so a reconnect can resume status checks without submitting the same paid request again. If the desktop restarts while a job is queued, or the provider outcome is uncertain, the item is shown as cancelled/unknown and is not automatically regenerated. Stopping a batch prevents further submissions but cannot reverse a provider charge already in flight.

**Follow story is deliberately unavailable with the current provider interface.** That interface does not guarantee that optional scene selection can be admitted only while idle and preempted before a chat request. This follows the approved fallback: keep manually selected backgrounds and give chat generation priority. No automatic paid audio generation runs.

## Playback and interruptions

The native mixer keeps at most two players per layer (current and outgoing) plus one preview. Track changes use three-second equal-power crossfades. Loop boundaries overlap using up to three seconds, shortened for short clips. A clip with a strong musical change at its endpoints may still have an audible transition; listen before selecting it.

Background sound shares NC's existing focus and service rules. Calls/focus loss pause it. An explicit Pause or earbud disconnection requires Resume; reconnecting alone must not override that intent. If Android cannot authorize a foreground service from the current background state, open NC and tap Resume. Losing the connection, changing conversation, logging out, or stopping the engine invalidates old playback work.

Continuous Mode's pause waits for current speech where its existing behavior does so. Story transport retains its existing speech behavior. Play/Resume on a saved story can resume its enabled soundscape. Opening a saved story restores its sound settings **paused**. Older story bundles default Off. A failed Open restores the previous soundscape paused along with the conversation recovery snapshot.

## Transport and diagnostics

Playback files are Ogg/Opus at 48 kHz, 64 kbps mono or 96 kbps stereo. Original WAV/PCM files are not sent to the phone for playback. The existing gateway carries 256 KiB parts with one low-priority part in flight; existing relay caps are unchanged. A private 250 MiB phone cache verifies hashes and sizes and pins active audio against eviction.

Phone diagnostics include `soundscape_playback` status transitions. Native events carry conversation/session/playback generation and revision so obsolete events can be rejected. Desktop `nc.soundscape` logs contain generation job IDs and transitions, not API keys, prompts, audio bytes or filesystem paths. Existing communication diagnostics remain the source for peer transfer/connection failures.

