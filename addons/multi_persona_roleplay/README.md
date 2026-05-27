# Multi Persona Roleplay Companion

Multi Persona Roleplay Companion, or MPRC, adds a Roleplay tab to NeuralCompanion for managing multiple neutral, user-configurable personas.

## What It Does

- Keeps a registry of personas with separate prompt, style, memory-scope, voice, and visual settings.
- Adds optional roleplay session state such as scene title, location, mood, objective, summary, roster, and current speaker.
- Injects the active persona into chat through NC's addon `chat_context.collect` capability.
- Routes the active persona voice sample to supported TTS backends when roleplay mode is enabled.
- Builds persona-aware Visual Reply prompts and can request generation through the existing Visual Reply addon when available.
- Adds an Audio tab with a persistent Story Sounds toggle and a local Suno-style prompt builder for music, ambience, FX, and stingers.
- Adds a Master Story tab that can turn one story prompt into linked personas, session state, and saved reusable story setups.
- Adds a Status cockpit for first-run demo, validation, repair actions, voice routing inspection, Visual Reply/AudioFX tests, story bundles, and memory editing.

## Add A Persona

Open `System Shaping > Roleplay > Persona Registry`, then use `Add persona` or `Duplicate persona`.
Edit the persona in `Persona Editor`, including the display name, role, short description, system prompt, speaking style, memory scope, behavior mode, and tags.

## Assign A Voice Sample

Open `Voice Per Persona`, enable voice, browse to a local audio sample, and choose a backend override or leave it on `inherit`.
MPRC stores only the path to the sample. It does not copy voice files into git-tracked source.
By default, `Follow active persona` keeps the Voice tab locked to the current active character. The `Currently editing` line shows the exact persona whose voice fields will be saved. Disable `Follow active persona` only when you intentionally want to edit another persona's voice while a different character is active.

Voice samples are supported only when the active NC TTS backend supports reference audio:

- Chatterbox
- Chatterbox Multilingual
- PocketTTS
- PocketTTS Multilingual

Gemini TTS Preview does not currently support voice samples, so MPRC warns and falls back safely.

## Roleplay Modes

The session panel supports:

- Single active persona
- Multi-character group chat
- Narrator + characters
- RPG / Game Master mode
- AlternativeReality

The active persona controls the immediate prompt. Multi-character modes add a compact roster and current-speaker instruction without exposing hidden planning.

AlternativeReality, or AR, is a directed interactive audiobook/adventure mode. It uses compact AR session state, a narrator-first prompt layer, active characters, pacing settings, interaction-frequency settings, and structured sections such as `[NARRATOR]`, `[CHARACTER: Name]`, `[AMBIENCE]`, and `[CHOICES]`. Existing non-AR modes keep their normal prompt behavior.

AR can use separate persona prompt profiles so characters do not carry their normal companion or tabletop/DnD wording into AlternativeReality. In the Persona Editor, enable `Use AR profile in AlternativeReality mode` and fill `AR description` plus `AR system prompt`. In the AR tab, keep `Use AR persona prompts` enabled. The bundled defaults include a cinematic, stylish, suggestive adventure profile that stays consensual, non-explicit, and player-choice centered. Use `Fill AR persona prompts` to populate missing AR fields for the default personas without changing voice samples, images, names, or regular prompts.

## Master Story

Open `Roleplay > Master` to describe a whole story in one prompt. `Generate Story Setup` asks the current chat provider for a JSON draft that includes a title, summary, session fields, AR state, and any personas needed by the story. Review the draft before applying it.

When you apply or load a story, MPRC links personas by existing persona ID first, then by display name. If a story contains a persona that does not exist yet, `Auto-create missing personas` creates it and links it to the story session. `Update matching existing personas` fills non-empty story prompt fields into matched personas while preserving voice samples and pictures unless the story explicitly includes those fields.

Personas linked to the current Master Story are marked in the persona selectors as `[Story]`, `[Active Story]`, or `[New Story]` so you can see which characters belong to the loaded setup. The Master tab can also request avatar pictures for newly created personas through the existing Visual Reply service. Use `Avatar visual direction` to steer the image style; generated story drafts include persona visual profiles such as character appearance, clothing/props, environment style, and negative prompt guidance. `Create avatar style sheets for new personas` is optional and default off; enable it only for Visual Reply providers/workflows that can use an avatar image as a reference for character reference-sheet generation.

`Save Story` stores the reviewed draft in addon storage. `Load Story` loads and applies it, so saved stories can quickly switch scene state, active speaker, AR settings, and linked persona roster. The Story Library sits above the builder and shows a framed 180x180 story image beside the saved-story selector. If a saved story has no image path, MPRC creates a local fallback cover image in story storage.

MPRC stores active long memory and session state per loaded Master Story. When a story is loaded again, the addon restores that story's memory so AR state, recent events, long-memory context, and story-linked audio prompt data continue with the loaded story instead of leaking from another story.

## Story Production Cockpit

The Status tab is the recommended first stop before a serious AR session. `Start Demo / Validate / Continue` loads the built-in demo, validates the setup, tests AudioFX and Visual Reply, and queues a Continue message. The template selector can load three polished starters: fantasy mystery, sci-fi horror, and cozy tavern adventure.

`Validate Story Setup` reports missing narrator setup, missing voice files, unsupported voice backends, broken image paths, missing memory snapshots, invalid persona links, malformed persona overrides, and missing AudioFX resources. The repair buttons handle common fixes directly: choose narrator, browse voice file, disable missing AudioFX, fix image path, create memory snapshot, relink personas, and reset invalid overrides.

The Voice Routing Inspector shows exactly how `[NARRATOR]` and `[CHARACTER: Name]` sections map to personas and voice files. The next-turn inspector can preview the next AR request or explain the narrator, active character, voice, memory, Visual Reply, and AudioFX routing before the next Continue.

`Export Story Bundle` creates a portable JSON bundle containing story metadata, linked cast, narrator lock, memory snapshot, prompts, AudioFX links/descriptions, visual settings, voice routing info, and `schema_version`. `Import Story Bundle` restores a bundle after saving a recovery backup.

## Visual Reply

Each persona has its own visual profile. The Preview button shows the effective image prompt. Generate Visual Reply sends that prompt to the existing Visual Reply service when the first-party Visual Reply addon is enabled and configured.

MPRC does not duplicate Visual Reply history or image storage. Generated images still flow through the existing Visual Reply state and dock.

## Audio

The Audio tab includes a Story Sounds checkbox. It defaults on and is stored in `settings.json` as `story_sounds_enabled`. In AR mode, story audio tags are treated as non-spoken audio controls: matching AudioFX descriptions, file names, or cue IDs are played in the background and removed before TTS reads the story text. Supported tags are `[AMBIENCE: description]`, `[MUSIC: description]`, `[FX: description]`, `[STINGER: description]`, and generic `[AUDIO: description]`. Examples: `[AMBIENCE: pub ambient]`, `[MUSIC: adventure music]`, `[FX: magic shimmer]`, `[STINGER: danger stinger]`. Manual preview and test controls are intentionally unaffected.

The Create Prompt for Audio section converts a short sound description into a polished cinematic prompt for Suno-style generation. It supports Auto, Music, Ambience, FX, and Stinger prompt types, plus quick ambience, horror, calmer, and action variations. Saved prompts are shown in the Saved Audio Prompts list, can be loaded back into the editor, and can be deleted. They are kept in addon settings under `saved_audio_prompts`.

The AudioFX Library connects sound descriptions and prompts to local audio files. Use Create New AudioFX from the current description, then Add Sound File to attach a WAV, MP3, FLAC, OGG, or M4A. Ready AudioFX items are shown in green and are automatically mirrored into the addon `available_audio_files` database so AR prompts know which local story sounds can be used. The file on disk is never deleted when an AudioFX item is removed from the addon.

Use `Import Audio Pack Resources` to bulk-load a prepared sound pack folder. The folder should contain `mprc_audio_pack.json` or `audio_pack.json` with entries that point to local audio files. Importing merges by file path and stable pack cue ID, so running it again updates the AudioFX Library instead of adding duplicate sounds.

## Storage

Runtime data is stored through addon storage:

```text
runtime/addons/nc.multi_persona_roleplay/
  personas.json
  settings.json
  visual_styles.json
  roleplay_templates.json
  sessions/current_session.json
  stories/index.json
  stories/*.json
  memory/long_memory.json
```

Voice sample paths are stored as paths only.

## Long Memory

MPRC uses an addon-local JSON long-memory layer for both normal roleplay and AlternativeReality mode. New assistant turns are recorded into `memory/long_memory.json` with compact event summaries, chapter summaries, character memory, location memory, active characters, scene, location, and mode. Prompts retrieve only a small relevant slice of this memory plus recent events, so long stories can keep continuity without stuffing the full transcript into every request.

The Status tab includes a Memory Browser / Editor. It supports pinned facts, recent memory review, deleting one wrong memory event, resetting character memory only, and resetting story memory only while preserving pinned facts.

This JSON backend is the stable local memory shape. A PostgreSQL or vector backend can be added later as an optional storage adapter without changing persona or session files.

## Backend Limits

- Per-message backend switching is not performed. NC loads one active TTS backend, and MPRC routes voice samples only when the persona backend is `inherit` or matches the active backend.
- Some backends ignore language hints. PocketTTS accepts per-request language hints; other backends may require changing their normal runtime setting.
- Visual Reply generation requires the existing Visual Reply provider to be configured with the needed API key, base URL, or workflow.

## Troubleshooting

- If the Roleplay tab is missing, confirm the addon is enabled in the Addons UI and restart NC.
- If a voice does not apply, check that roleplay mode is enabled, the persona voice toggle is on, the file path exists, and the active TTS backend supports voice samples.
- If image generation does not start, use Preview Image Prompt first, then check the Visual Reply provider settings.
- If a persona feels too repetitive, lower the repetition threshold in `settings.json` or edit the persona prompt to ask for more varied responses.
- If AR mode feels too chatty, set pacing to `Slow / Audiobook` and interaction frequency to `Continue until important choice`.

## Safety And Limits

Default personas are neutral and non-romantic. MPRC does not reveal chain-of-thought. Scene and character state are compact visible summaries only.

## Disable

Disable `Multi Persona Roleplay` in the Addons UI and restart NC. Normal chat, TTS, Visual Reply, avatars, and other addons continue to use their usual paths.
