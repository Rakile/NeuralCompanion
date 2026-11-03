# Multi Persona Roleplay Companion

Start with the current [Roleplay user guide](../../docs/addons/roleplay.md). Open **Addons → Roleplay** for the numbered story workflow and isolated **Play** feed. The reference below retains story formats, voice routing, storage and advanced behavior.

Multi Persona Roleplay Companion, or MPRC, adds a Roleplay tab to NeuralCompanion for managing multiple neutral, user-configurable personas.

## What It Does

- Keeps a registry of personas with separate prompt, style, memory-scope, voice, and visual settings.
- Adds optional roleplay session state such as scene title, location, mood, objective, summary, roster, and current speaker.
- Injects the active persona into chat through NC's addon `chat_context.collect` capability.
- Routes the active persona voice sample to supported TTS backends when roleplay mode is enabled.
- Builds persona-aware Visual Reply prompts and can request generation through the existing Visual Reply addon when available.
- Adds a Story Sounds tab with a persistent Story Sounds toggle and a local Suno-style prompt builder for music, ambience, FX, and stingers.
- Adds a Master Story tab that can turn one story prompt into linked personas, session state, and saved reusable story setups.
- Adds Story Library Export for portable zip story packages with selectable sections, green availability rows, copied avatar/voice/audio assets, and safe import remapping.
- Adds Story Health for first-run demo loading, setup checks, repair actions, voice routing inspection, separate voice/image/sound tests, story bundles, and memory editing.

## Add A Persona

Open **Addons → Roleplay → Registry**, then use **Add persona** or **Duplicate persona**.
Edit the persona in **Editor**, including the display name, role, short description, system prompt, speaking style, memory scope, behavior mode, and tags.

## Assign A Voice Sample

Open **Roleplay → Voice**, enable voice, browse to a local audio sample, and choose a backend override or leave it on `inherit`.
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

- `Single active persona`: only the active persona is framed to respond. Use it for one-on-one roleplay or testing one profile/voice.
- `Multi-character group chat`: the active cast is treated as a conversation group. Characters can speak as participants, but there is no dedicated narrator layer.
- `Narrator + characters`: adds a narrator/story voice plus character dialogue. Use it for prose scenes that still include named character responses.
- `RPG / Game Master mode`: frames the assistant as a game master who describes the world, adjudicates actions, and offers tabletop-style outcomes.
- `AlternativeReality`: narrator-led interactive story mode with persistent scene state, active characters, pacing controls, choices, and story audio tags.

The active persona controls the immediate prompt in simple modes. Multi-character modes add a compact roster and current-speaker instruction without exposing hidden planning.

AlternativeReality, or AR, is a directed interactive audiobook/adventure mode. It uses compact AR session state, a narrator-first prompt layer, active characters, pacing settings, interaction-frequency settings, and structured sections such as `[NARRATOR]`, `[CHARACTER: Name]`, `[AMBIENCE]`, and `[CHOICES]`. Existing non-AR modes keep their normal prompt behavior.

AR can use separate persona prompt profiles so characters do not carry their normal companion or tabletop/DnD wording into AlternativeReality. In the Persona Editor, enable `Use AR profile in AlternativeReality mode` and fill `AR description` plus `AR system prompt`. In the AR tab, keep `Use AR persona prompts` enabled. The bundled defaults include a cinematic, stylish, suggestive adventure profile that stays consensual, non-explicit, and player-choice centered. Use `Fill AR persona prompts` to populate missing AR fields for the default personas without changing voice samples, images, names, or regular prompts.

## Master Story

Open **Addons → Roleplay → Master** to describe a whole story in one prompt. Choose the Master Story `Mode` there; it is independent from the mode on the Roleplay Session tab. Optional `Scene title`, `Location`, `Time / mood`, and `Mood` fields are binding inputs for the generated opening scene. `Time / mood` maps to the story's time/period cue, while `Mood` controls atmosphere. `Generate Story Setup` asks the current chat provider for a JSON draft that includes a title, summary, session fields, AR state when relevant, and any personas needed by the story. Review the draft before applying it.

When you apply or load a story, MPRC links personas by existing persona ID first, then by display name. If a story contains a persona that does not exist yet, `Auto-create missing personas` creates it and links it to the story session. `Update matching existing personas` fills non-empty story prompt fields into matched personas while preserving voice samples and pictures unless the story explicitly includes those fields.

`Apply Draft` opens an Apply Master Story workflow before anything is written. The left Draft Characters list shows each generated character; when you generate a draft avatar, that row immediately switches from initials to the generated thumbnail. The Draft Avatar / Visual Prompt field is editable, and its right-click `Refine Avatar Visual Prompt` action uses the current chat provider to clean up the image prompt before you send it to Visual Reply. With `Auto-assign distinct voices to new personas` enabled, Apply Story selects different local `.wav` references for newly created personas that have no explicit voice. The Draft Voice section still lets you choose or replace a sample, edit the emotional preview text, and press `Preview Voice` before applying. Explicit draft and existing persona voices are preserved. Apply now saves the applied story definition and its clean memory baseline automatically, leaves the session paused, and reports separately how many story characters and narrator personas were linked. Press `Start Play` to arm the isolated MPRC feed and begin the opening turn.

Personas linked to the current Master Story are marked in the persona selectors as `[Story]`, `[Active Story]`, or `[New Story]` so you can see which characters belong to the loaded setup. The Master tab can also request avatar pictures for newly created personas through the existing Visual Reply service. Use `Avatar visual direction` to steer the image style; generated story drafts include persona visual profiles such as character appearance, clothing/props, environment style, and negative prompt guidance. `Create avatar style sheets for new personas` is optional and default off; enable it only for Visual Reply providers/workflows that can use an avatar image as a reference for character reference-sheet generation.

`Save Story` remains available for explicitly saving later draft edits. Current-story snapshots include only the linked story cast, and Apply Story drops AR active-character IDs that are not part of the applied cast, preventing personas from an older story from leaking into a new one. It never promotes the first ordinary character to narrator merely because a narrator was missing; it uses a real narrator profile when one exists and otherwise leaves narrator selection automatic. `Load Story` also ignores unrelated disabled personas in legacy snapshots that accidentally captured the full persona registry. It restores only that story's saved memory, leaves the session paused, and waits for `Start Play`. The Story Library sits above the builder and shows a framed 180x180 story image beside the saved-story selector. If a saved story has no image path, MPRC creates a local fallback cover image in story storage.

`Story Library Export` sits directly below Story Library. It creates a portable `.mprcstory.zip` package with selectable sections for session state, story metadata, linked personas, visual settings, avatar image files, voice settings, voice files, story memory, recent events, AudioFX settings, AudioFX files, visual styles, Master Story draft data, and templates/prompts. Green rows mean data exists for that section. When avatar, voice, or AudioFX files are selected, MPRC copies those files into the package instead of requiring the original absolute paths on restore.

Imported story packages are validated through `manifest.json`, saved through the existing recovery-backup path, and restored into the addon's runtime asset folder. Avatar image, voice sample, and AudioFX paths are remapped to extracted local files under `runtime/addons/nc.multi_persona_roleplay/assets/story_packages/imported/<story_id>/`. Re-importing the same story package reuses that story asset folder instead of creating a new timestamped folder. Existing personas and stories are protected by creating unique imported IDs when a package would collide with saved data.

MPRC stores active long memory and session state per loaded Master Story. When a story is loaded again, the addon restores that story's memory so AR state, recent events, long-memory context, and story-linked audio prompt data continue with the loaded story instead of leaking from another story. While MPRC Play is active, global Main Chat, Spotify Sense, Companion Orb, and other ordinary assistant replies are not recorded into the isolated story; only direct MPRC Play turns advance its memory.

## Story Health

Open **Addons → Roleplay → Story Health** before a long session. **Load Demo if
Needed & Check** loads the demo only when no story is active, then checks setup.
It does not start narration or run the separate service tests. The template
selector and **Load Template** offer fantasy mystery, sci-fi horror, and cozy
tavern starters.

Use **Test narrator voice**, **Test selected character voice**, **Test Visual
Reply**, and **Test Story Sound** separately when you want to check those
services. Start narration from **Play → Start Play** after reviewing the results.
For the complete workflow, follow the [Roleplay user guide](../../docs/addons/roleplay.md).

**Check Story Setup** reports missing narrator setup, missing voice files, unsupported voice backends, broken image paths, missing memory snapshots, invalid persona links, malformed persona overrides, and missing AudioFX resources. The repair buttons handle common fixes directly: choose narrator, browse voice file, disable missing AudioFX, fix image path, create memory snapshot, relink personas, and reset invalid overrides.

The voice-routing view in **Story Health** shows how `[NARRATOR]` and `[CHARACTER: Name]` sections map to personas and voice files. The next-turn inspector can preview the next AR request or explain the narrator, active character, voice, memory, Visual Reply, and AudioFX routing before the next Continue.

`Export Story Bundle` creates a compact JSON bundle containing story metadata, linked cast, narrator lock, memory snapshot, prompts, AudioFX links/descriptions, visual settings, voice routing info, and `schema_version`. `Import Story Bundle` restores a bundle after saving a recovery backup. For a complete movable package with copied voice/audio assets, use `Story Library Export` in the Master tab.

## Visual Reply

Each persona has its own visual profile. The Preview button shows the effective image prompt. Generate Visual Reply sends that prompt to the existing Visual Reply service when the first-party Visual Reply addon is enabled and configured.

MPRC changes prompt style by provider. Grok/xAI uses a richer natural-language prompt with story moment, visible action, persona identity, appearance, scene, mood, lighting, visual style, and continuity. Runware uses a shorter direct prompt with concrete visual phrases so the provider is not overloaded by long story instructions. ComfyUI keeps the existing compact positive-prompt behavior.

If a persona provider is set to `inherit`, MPRC resolves the active Visual Reply provider snapshot when available and builds the prompt for that provider. The **Troubleshooting** tab shows the effective provider, persona override, active provider snapshot, and final prompt style.

MPRC does not duplicate Visual Reply history or image storage. Generated images still flow through the existing Visual Reply state and dock.

## Audio

The **Story Sounds** tab includes a Story Sounds checkbox. It defaults on and is stored in `settings.json` as `story_sounds_enabled`. In AR mode, story audio tags are treated as non-spoken audio controls: matching AudioFX descriptions, file names, or cue IDs are played in the background and removed before TTS reads the story text. Supported tags are `[AMBIENCE: description]`, `[MUSIC: description]`, `[FX: description]`, `[STINGER: description]`, and generic `[AUDIO: description]`. Examples: `[AMBIENCE: pub ambient]`, `[MUSIC: adventure music]`, `[FX: magic shimmer]`, `[STINGER: danger stinger]`. Manual preview and test controls are intentionally unaffected.

The Create Prompt for Audio section converts a short sound description into a polished cinematic prompt for Suno-style generation. It supports Auto, Music, Ambience, FX, and Stinger prompt types, plus quick ambience, horror, calmer, and action variations. Saved prompts are shown in the Saved Audio Prompts list, can be loaded back into the editor, and can be deleted. They are kept in addon settings under `saved_audio_prompts`.

The AudioFX Library connects sound descriptions and prompts to local audio files. Use **Create Story Sound** from the current description, then **Add Sound File** to attach a WAV, MP3, FLAC, OGG, or M4A. Ready AudioFX items are shown in green and are automatically mirrored into the addon `available_audio_files` database so AR prompts know which local story sounds can be used. The file on disk is never deleted when an AudioFX item is removed from the addon.

Use **Import Sound Pack** to bulk-load a prepared sound pack folder. The folder should contain `mprc_audio_pack.json` or `audio_pack.json` with entries that point to local audio files. Importing merges by file path and stable pack cue ID, so running it again updates the AudioFX Library instead of adding duplicate sounds.

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
  assets/story_packages/imported/
  memory/long_memory.json
```

Normal avatar, voice sample, and AudioFX paths are stored as paths only. Story Library Export packages can copy selected avatar, voice, and AudioFX files into the zip and remap them into the addon's runtime asset folder during import, so restored voices and sound effects play from `runtime/addons/nc.multi_persona_roleplay/assets/...`.

## Long Memory

MPRC uses an addon-local long-memory layer for both normal roleplay and AlternativeReality mode. New assistant turns are recorded into `memory/long_memory.json` for export/import compatibility and mirrored into `memory/long_memory.sqlite3` for ranked retrieval. The memory shape includes compact event summaries, chapter summaries, character memory, location memory, active characters, scene, location, and mode. Prompts retrieve only a small relevant slice of this memory plus recent events, so long stories can keep continuity without stuffing the full transcript into every request.

The **Story Health** tab includes story-memory review and editing controls. It supports pinned facts, recent memory review, deleting one wrong memory event, resetting character memory only, and resetting story memory only while preserving pinned facts.

The SQLite mirror includes deterministic local embedding vectors and data-bank chunks for semantic-ish story recall. The data bank can index pinned facts, chapter summaries, recent long-memory events, story archives, and configured local documents from `long_memory_databank_sources` in settings. PostgreSQL can be selected later by setting `long_memory_database_backend` to `postgres` or `postgresql` and providing `long_memory_postgres_dsn`; if the driver or connection is unavailable, MPRC falls back to SQLite.

## Backend Limits

- Per-message backend switching is not performed. NC loads one active TTS backend, and MPRC routes voice samples only when the persona backend is `inherit` or matches the active backend.
- MPRC can route distinct voices per persona only when the active NC TTS backend supports reference audio. Master Story can auto-assign distinct local samples to new personas; manual and imported personas still need a valid sample before they can sound different.
- During one TTS response, voices should switch only on explicit speaker segments such as `[NARRATOR]`, `[CHARACTER: Exact Persona Display Name]`, or supported speaker/persona labels. Explicit payload `persona_id`, `speaker_id`, or `current_speaker_id` wins over text labels.
- Some backends ignore language hints. PocketTTS accepts per-request language hints; other backends may require changing their normal runtime setting.
- Visual Reply generation requires the existing Visual Reply provider to be configured with the needed API key, base URL, or workflow.

## Troubleshooting

- If the Roleplay tab is missing, confirm the addon is enabled in the Addons UI and restart NC.
- If a voice does not apply, check that roleplay mode is enabled, the persona voice toggle is on, the file path exists, and the active TTS backend supports voice samples.
- If a voice changes unexpectedly during one response, open **Story Health** or **Troubleshooting** and inspect voice routing. The route reason should explain whether the segment came from `explicit_persona`, `text_speaker_label`, `ar_narrator_default`, `ar_stream_speaker`, `current_speaker`, or `active_persona`.
- If image generation does not start, use Preview Image Prompt first, then check the Visual Reply provider settings, persona visual enablement, trigger mode, cooldown, and max auto images.
- If Runware results get worse, shorten the prompt and keep concrete visual phrases. If Grok/xAI results are too plain, add richer natural-language visual detail.
- If a persona feels too repetitive, lower the repetition threshold in `settings.json` or edit the persona prompt to ask for more varied responses.
- If AR mode feels too chatty, set pacing to `Slow / Audiobook` and interaction frequency to `Continue until important choice`.

## Safety And Limits

Default personas are neutral and non-romantic. MPRC does not reveal chain-of-thought. Scene and character state are compact visible summaries only.

## Master Story: scenarios, lore and refinement

The native MPRC workspace has six numbered navigation buttons: **Create story → Scenes & lore (optional) → Apply story → Voices & media (optional) → Check setup → Play**. They open the relevant tab and, for Master, the relevant card. Previous, Next and Skip optional only navigate. All tabs stay accessible; a highlighted step means your current location, not that setup is complete.

In **Master Story Builder**, enter a rough premise and review **Cast generation**, then choose a **Refinement provider**. The default follows the current main model. Another configured provider can use a loaded model list or a typed model ID without switching NC's main chat selection. **Refine story idea** requests a rich multi-act campaign brief (target 1,000–1,600 words), an exact cast plan for a positive requested count, and opening scene/title/location/time/mood/visual fields. Zero requests only characters explicitly required by the premise. The new-character creation limit is separate from the requested draft count.

**Refine story idea** fills the six builder text fields automatically after a successful response. **Refine & build complete draft** uses the selected provider/model for three sequential stages: refine the brief, create the Master draft and cast, then generate related scenes and lore. A spinner and stage text show progress. The full result fills both the builder and editable Master draft; it does not activate a story or create personas in the registry. Mode, SFW and cast options remain user-controlled. Check **Preview only** to review before choosing **Use refined fields** or **Use complete draft**.

**Retry failed stage** reuses completed stages held in memory, provided inputs, provider/model and Master draft have not changed. Cancellation, invalid output or conflicting edits leave the existing fields and Master draft intact. Partial results never replace the Master draft. All provider network work runs in a worker. The separate **Generate Story Setup** button continues to use the current main model.

After a complete build, open **Scenarios & Lore** to review the generated content. A clean editor automatically loads the newer Master draft; unsent edits are preserved with a notice instead. Only send back changes you make there. Then review **Master → Editable draft → Apply Draft**, check voices/media and Story Health, and start Play.

Open the **Scenarios & Lore** tab beside **Master** inside MPRC. The embedded editor uses NC's shared theme, cards, inputs and buttons; it does not open a separate window. Each field has visible guidance and a hover tooltip. Text edits use **Set field**; checkboxes and dropdowns update the editor immediately. **Send to Master Draft** validates and copies the editor into the existing Master draft. Use **Open Master**, then the existing **Save** or **Apply Draft** controls there. Sending or saving a draft does not run its actions. Switching tabs preserves the editor's unsent changes. **Reload Master Draft** asks before discarding those changes and loading a draft edited or generated elsewhere.

The category tabs wrap on narrower windows and cover the opening/instructions, scenes, lorebooks and entries, typed variables, events, authored choices, cast roles, existing story fields and builder options. Add, duplicate or delete records; referenced scenes and variables cannot be deleted until their references are repaired. Effects belong to scenes or events. Choices contain their own effect. Conditions use typed comparisons, optionally combined with All or Any. Only the three built-in actions are supported: set a scenario variable, change scene, and narrate authored text.

Select **Refine** on a field, **Refine record**, **Refine section**, or **Whole story**, describe the change and generate a preview. This uses the currently selected main chat provider/model through NC's existing provider capability. Boolean, numeric and dropdown options are eligible too. Review Original/Proposal and choose Apply preview or Discard. Stable IDs, revisions, machine paths and provider settings are protected. Cancellation, draft changes and model changes invalidate late results. A refinement never executes story actions.

Under **Builder options**, enable **master story include scenario** to request the extension during the next normal Master Story generation. Set **master story scenario context limit** to the known token capacity of your main model and choose a reply reserve (default 1024). A limit of 0 means unknown: authored lore is omitted, with a visible reason. Selection targets up to 1200 tokens, uses a conservative UTF-8 byte estimate, includes request/schema overhead, skips oversized entries whole, and never truncates a fact midway. Keywords match whole words or phrases, including Swedish text, against the latest ten completed Play messages and the current player action. Pinned and scene-scoped entries are supported. Authored lore stays separate from learned story memory and Databank documents.

Use **Preview draft lore** to inspect which facts match a player action in the initial scene, or the scene selected under Scenes. This estimate uses the draft without Play history; Play recalculates selection against the full request.

Apply a story and press **Start Play**. **Play → Additional controls → Scenario Choices & Progress** navigates to **Scenarios & Lore**, where the applied-scenario card shows the current scene, lore diagnostics and authored choice buttons. These are separate from ordinary generated text choices. Narration uses the existing MPRC voice routing and speech service; it waits briefly for current speech, then admits the authored text to the transcript and requests speech. Text remains available if TTS cannot initialize. The panel reports speech availability separately; success means visible narration, not audible completion. Diagnostic text is never spoken.

**Stop** saves progress; **Start Play** resumes the exact captured definition without repeating the opening or completed effects. After applying a revised definition, **Restart Story** starts a fresh scenario session using it. Progress includes typed variables, scene, definition and effect journal, saved atomically under addon-owned `scenario_progress`. A failed once-event offers an explicit Retry button that skips completed effects. A crash or timeout after uncertain speech admission is marked indeterminate and is never automatically retried. Restart is a fresh session, so its opening/effects can run again.

**Load lighthouse example** replaces the scenario extension in the editor draft only. It demonstrates harbour → lighthouse, the code 7314, keeper Mira, a pinned storm fact, a conditional scene choice and an arrival narration. Send, Apply and Start are still required. Story packages/bundles carry authored definitions, not execution checkpoints; imported extensions receive fresh internal IDs and start paused. Invalid/future definitions are rejected before import mutations. Existing stories without an extension retain their original Play behavior.

Automated checks use temporary storage and fake providers/speech. Before using a live story, manually check the editor at your display scaling, slow-provider cancellation, real voice admission/Stop, Save→reload→resume, and ordinary chat afterward. No phone actions, model-controlled tools, avatar automation, per-character model scheduling, core changes or additional dependencies are introduced by this feature.

## Disable

Disable `Multi Persona Roleplay` in the Addons UI and restart NC. Normal chat, TTS, Visual Reply, avatars, and other addons continue to use their usual paths.
