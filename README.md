# Neural Interface Qt

Neural Interface Qt is a local desktop avatar companion application built around:

- `LM Studio` for the local language model
- `PocketTTS` and `Chatterbox / TurboTTS` for speech
- `MuseTalk` and `VSeeFace` as avatar-engine options
- a `PySide6 / Qt` desktop UI for setup, tuning, preview, tutorials, and runtime control

The project is especially focused on streamed avatar replies, where text generation, TTS, and avatar rendering overlap in real time.

The safest way to approach the app is:

- get one simple path working first
- then tune
- then expand into authoring and optimization workflows

## Index

- [Current Layout](#current-layout)
- [What The App Does](#what-the-app-does)
- [Main Features](#main-features)
- [Requirements](#requirements)
- [Python Dependencies](#python-dependencies)
- [Installation](#installation)
- [Running The App](#running-the-app)
- [First Launch](#first-launch)
- [Recommended First Run](#recommended-first-run)
- [Main UI Areas](#main-ui-areas)
- [Persona Tab](#persona-tab)
- [VSeeFace Tab](#vseeface-tab)
- [MuseTalk Tab](#musetalk-tab)
- [Brain Tab](#brain-tab)
- [Chunking Tab](#chunking-tab)
- [Dry Run Tab](#dry-run-tab)
- [Presets vs Performance Profiles](#presets-vs-performance-profiles)
- [Tutorials and In-App Help](#tutorials-and-in-app-help)
- [Important Folders](#important-folders)
- [Troubleshooting](#troubleshooting)
- [Current Practical Advice](#current-practical-advice)
- [Detailed Reference](#detailed-reference)
- [Core Mental Model](#core-mental-model)
- [Avatar Engine](#avatar-engine)
- [Input Mode](#input-mode)
- [Input Role](#input-role)
- [Stream Mode](#stream-mode)
- [TTS Backend](#tts-backend)
- [MuseTalk VRAM Modes](#musetalk-vram-modes)
- [Persona Tab In Detail](#persona-tab-in-detail)
- [Brain Tab In Detail](#brain-tab-in-detail)
- [Chunking Tab In Detail](#chunking-tab-in-detail)
- [VSeeFace Tabs In Detail](#vseeface-tabs-in-detail)
- [MuseTalk Preprocess In Detail](#musetalk-preprocess-in-detail)
- [Loop Authoring In Detail](#loop-authoring-in-detail)
- [Dry Run In Detail](#dry-run-in-detail)
- [Performance Profiles In Detail](#performance-profiles-in-detail)
- [Why Lower Modes Can Beat Heavier Modes](#why-lower-modes-can-beat-heavier-modes)
- [Practical Advice For Advanced Users](#practical-advice-for-advanced-users)
- [Final Note](#final-note)

## Current Layout

The current top-level tabs are:

- `Persona`
- `VSeeFace`
- `MuseTalk`
- `Brain`
- `Chunking`
- `Dry Run`
- `Tutorials`

### VSeeFace

The `VSeeFace` tab contains nested tabs for:

- `Body`
- `Dynamics`

This is where body presets, pose shaping, hand/body tuning, and live motion-style controls live.

### MuseTalk

The `MuseTalk` tab contains nested tabs for:

- `Preprocess`
- `Loop Authoring`

This split is deliberate:

- `Preprocess` is for building and tuning MuseTalk avatars
- `Loop Authoring` is for creating or importing source loops, currently with experimental Wan2GP-oriented tooling

## What The App Does

At a high level, the app can:

- listen to the microphone or use push-to-talk
- send user input to a local LM Studio model
- generate spoken replies with TTS
- drive either `MuseTalk` or `VSeeFace`
- stream speech and avatar output progressively
- tune startup/chunking behavior with `Dry Run`
- save and load `Performance Profiles`
- author MuseTalk source loops through an experimental local workflow

## Main Features

- Streaming and non-streaming conversation modes
- `PocketTTS` and `Chatterbox / TurboTTS`
- `MuseTalk` VRAM modes:
  - `Quality`
  - `Balanced`
  - `Low VRAM`
  - `Very Low VRAM`
- built-in `MuseTalk Preview` dock
- MuseTalk avatar preprocessing into `MuseTalk/results/v15/avatars/<avatar_id>`
- MuseTalk first-frame debug testing for mask tuning
- MuseTalk one-frame audio test using a scratch avatar
- metadata-driven MuseTalk emotion tags via `avatar_pose.json`
- experimental `Loop Authoring` flow for local emotion-loop creation
- `Dry Run` hardware tuning
- `Performance Profiles`
- persona presets
- built-in tutorials

## Requirements

Before using the app, make sure you have:

- Windows
- Python 3.11
- `LM Studio` installed and running when you want live inference
- a local LM Studio model available
- `FFmpeg` available for MuseTalk and loop-authoring video handling
- the required MuseTalk model/runtime files if you want the MuseTalk engine

For MuseTalk, a CUDA-capable NVIDIA GPU is strongly recommended.

## Python Dependencies

The current top-level [requirements.txt](/E:/Tools/Python_Scripts/NeuralInterface/requirements.txt) is minimal and currently lists:

- `chatterbox-tts`
- `gradio`
- `nltk`

The actual application also depends on the packages imported by:

- [qt_app.py](/E:/Tools/Python_Scripts/NeuralInterface/qt_app.py)
- [engine.py](/E:/Tools/Python_Scripts/NeuralInterface/engine.py)
- [MuseTalk/musetalk_engine.py](/E:/Tools/Python_Scripts/NeuralInterface/MuseTalk/musetalk_engine.py)

That includes Qt / PySide6 and the runtime dependencies used by the local TTS and avatar pipelines.

## Installation

The project does not yet ship with a fully locked, one-command installer, so the current installation flow is still practical rather than polished.

### 1. Create or activate a Python environment

Use Python `3.11`.

Example:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 2. Install the current Python requirements

Start with the top-level requirements file:

```powershell
pip install -r requirements.txt
```

Important note:

- this is currently only the minimal top-level list
- the app also depends on packages imported by:
  - [qt_app.py](/E:/Tools/Python_Scripts/NeuralInterface/qt_app.py)
  - [engine.py](/E:/Tools/Python_Scripts/NeuralInterface/engine.py)
  - [MuseTalk/musetalk_engine.py](/E:/Tools/Python_Scripts/NeuralInterface/MuseTalk/musetalk_engine.py)

So if you are setting up from scratch, you may still need to install missing runtime packages the first time you launch.

### 3. Install and prepare LM Studio

- install `LM Studio`
- load at least one local model
- make sure LM Studio is running before you initialize the app

### 4. Make sure FFmpeg is available

`FFmpeg` is used by:

- MuseTalk-related video handling
- Loop Authoring
- Wan2GP handoff/stitching workflows

It should be available from your shell / PATH.

### 5. Prepare MuseTalk if you plan to use it

If you want to use the MuseTalk engine, make sure:

- the required MuseTalk runtime/model files are present under [MuseTalk](/E:/Tools/Python_Scripts/NeuralInterface/MuseTalk)
- the MuseTalk worker can start correctly

Main MuseTalk worker/runtime entry points:

- [MuseTalk/musetalk_worker.py](/E:/Tools/Python_Scripts/NeuralInterface/MuseTalk/musetalk_worker.py)
- [MuseTalk/musetalk_engine.py](/E:/Tools/Python_Scripts/NeuralInterface/MuseTalk/musetalk_engine.py)

### 6. Optional: prepare Wan2GP for Loop Authoring

If you want to use the experimental `MuseTalk > Loop Authoring` workflow, install and prepare your local Wan2GP environment separately.

The app can point to:

- a local Wan2GP root
- a specific Python executable for that Wan2GP install

### 7. Launch the app

Once the environment, LM Studio, and optional avatar tooling are in place, start the Qt app with:

```powershell
python qt_app.py
```

## Running The App

Start the Qt application with:

```powershell
python qt_app.py
```

Main entry point:

- [qt_app.py](/E:/Tools/Python_Scripts/NeuralInterface/qt_app.py)

## First Launch

On first launch, the app can offer an interactive onboarding flow.

Tutorials are always available later from:

- `Tutorials` tab

Current tutorial files include:

- [getting_started.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/getting_started.json)
- [first_run.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/first_run.json)
- [dry_run_optimization.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/dry_run_optimization.json)
- [startup_self_check.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/startup_self_check.json)
- [vision_supervisors_overview.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/vision_supervisors_overview.json)
- [screen_supervisor.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/screen_supervisor.json)
- [clipboard_supervisor.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/clipboard_supervisor.json)
- [webcam_supervisor.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/webcam_supervisor.json)
- [heart_rate_threshold_rules.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/heart_rate_threshold_rules.json)
- [visual_reply_controls.json](/E:/Tools/Python_Scripts/NeuralInterface/tutorials/visual_reply_controls.json)

## Recommended First Run

A broadly safe first path is:

1. Start `LM Studio`.
2. Launch the app.
3. Choose `MuseTalk` as Avatar Engine.
4. Turn `Stream Mode` on.
5. Use `PocketTTS`.
6. Set MuseTalk VRAM to `Low VRAM` or `Very Low VRAM`.
7. Pick an LM Studio model.
8. Click `INITIALIZE SYSTEM`.

## Main UI Areas

### Left Side

The left side contains the main setup controls, including:

- `Avatar Engine`
- `Input Mode`
- `Input Role`
- `Stream Mode`
- `TTS Backend`
- `MuseTalk VRAM`
- `LLM Model`
- `Preset`

It also contains the tabbed authoring and tuning areas listed above.

### Right Side

The right side contains:

- `System Console`
- `Chat`
- runtime action buttons:
  - `Regenerate`
  - `Retry Input`
  - `Pause / Resume`
  - `Skip Speech`
- system controls:
  - `INITIALIZE SYSTEM`
  - `TERMINATE`
  - `RESET CHAT MEMORY`

There is also a separate `MuseTalk Preview` dock that can be shown when needed.

## Persona Tab

Use `Persona` for:

- voice file / clone selection
- technical expressive rules / tags
- system prompt shaping
- advanced PocketTTS override if you intentionally need a custom interpreter

This is where the assistant’s speaking identity and behavioral framing are configured.

## VSeeFace Tab

### Body

`VSeeFace > Body` is where you shape pose and body behavior.

It includes:

- pose/body sliders
- saved body configuration workflows
- hand/body shaping utilities

### Dynamics

`VSeeFace > Dynamics` is where you shape motion feel.

It includes parameters such as:

- eye activity
- breath speed
- shoulder lift
- body sway speed
- body sway intensity

These affect feel and movement style, not LLM sampling.

## MuseTalk Tab

### Preprocess

Use `MuseTalk > Preprocess` to:

- choose a prepared avatar or a new source clip/folder
- preprocess a source video or PNG frame folder into:
  - `MuseTalk/results/v15/avatars/<avatar_id>`
- tune mask-related parameters before committing to a full preprocess
- attach emotion tags to a prepared avatar

The preprocess UI is currently organized into:

- `Source`
- `Mask Settings`
- `Debug & Testing`

#### Mask Settings

These currently include:

- `BBox Shift`
- `Parsing Mode`
- `Extra Margin`
- `Left Cheek`
- `Right Cheek`

These controls define how much of the lower face / jaw / cheek region MuseTalk is allowed to regenerate.

#### Debug First Frame

`Debug First Frame` is the fast tuning tool.

It:

- uses a warmed MuseTalk helper worker
- renders only a debug first-frame preview
- writes to MuseTalk runtime scratch space
- does **not** modify your prepared avatar folders

This is the recommended way to tune mask settings before a real preprocess.

#### Audio Frame Test

`Audio Frame Test` is a slower, more realistic one-frame lip-sync spot check.

It:

- uses a temporary scratch avatar
- renders a single frame from test audio
- cleans the scratch data afterward

Use this when you want to sanity-check lip-sync behavior without risking your production avatar folder.

#### Emotion Tags

Prepared avatars can store emotion tags in:

- `MuseTalk/results/v15/avatars/<avatar_id>/avatar_pose.json`

Those tags are used to route bracket-tagged LLM output such as:

```text
[angry] No, absolutely not. [shy] Well... maybe.
```

Avatar selection is now metadata-driven rather than relying only on hardcoded mappings.

### Loop Authoring

`MuseTalk > Loop Authoring` is currently experimental.

Its purpose is to help create reusable source loops for MuseTalk emotional/body variants without forcing users out into unrelated third-party tools.

Current capabilities include:

- source image selection
- optional reference video
- preset-based prompt templates
- local Wan2GP integration
- draft package creation under:
  - [LoopAuthoring/drafts](/E:/Tools/Python_Scripts/NeuralInterface/LoopAuthoring/drafts)
- direct handoff of a generated loop back into MuseTalk preprocessing

The current workflow is centered around local authoring, not realtime generation.

#### Wan2GP Integration

The current experimental integration supports:

- choosing a local Wan2GP installation
- choosing the Python executable for that install
- launching generation from the Qt app
- importing or directly using generated videos

The app writes generation assets into the current draft folder so each authoring attempt stays grouped together.

#### Long Sequence Modes

Loop Authoring currently supports both:

- `Single Run (Sliding Window)`
- `Continue Video Segments`

And continuation can be based on:

- full last rendered video for better consistency
- tail-context continuation for lower memory pressure

This area is still experimental and intentionally evolving.

## Brain Tab

Use `Brain` for language-model sampling behavior:

- `Temperature`
- `Top P`
- `Top K`
- `Repeat Penalty`
- `Min P`
- optional response-length limiting

These settings shape the assistant’s reply style, not the avatar pipeline directly.

## Chunking Tab

Use `Chunking` for global pipeline tuning.

It currently contains grouped controls for:

- `Standard`
- `MuseTalk Non-Stream`
- `Streaming`

It also contains:

- `Reset Chunking Defaults`
- `Performance Profiles`

These chunking values are global runtime controls and are not stored as persona identity.

## Dry Run Tab

`Dry Run` profiles the current hardware and recommends safer startup/chunking values without rewriting the live pipeline while measuring.

Current Dry Run controls include:

- `Target Reply Samples`
- `Hands-Free` auto-follow-up mode
- `Arm Dry Run`
- `Stop Dry Run`
- `Apply Recommendation`

It also exposes:

- a summary / recommendation area
- saved `Performance Profiles`

Dry Run is especially useful in streaming mode.

## Presets vs Performance Profiles

These are separate systems.

### Persona Presets

Persona presets live in:

- [presets](/E:/Tools/Python_Scripts/NeuralInterface/presets)

They are used for identity-style settings such as:

- prompt/personality framing
- voice settings
- expressive rules
- brain behavior values

### Performance Profiles

Performance profiles live in:

- [performance_profiles](/E:/Tools/Python_Scripts/NeuralInterface/performance_profiles)

Current shipped examples include:

- [Recommended_Stream.json](/E:/Tools/Python_Scripts/NeuralInterface/performance_profiles/Recommended_Stream.json)
- [Very_Low_VRAM_Stream.json](/E:/Tools/Python_Scripts/NeuralInterface/performance_profiles/Very_Low_VRAM_Stream.json)
- [Expressive_Stream.json](/E:/Tools/Python_Scripts/NeuralInterface/performance_profiles/Expressive_Stream.json)

Profiles are for pipeline/performance settings such as:

- stream mode
- TTS backend
- MuseTalk VRAM mode
- chunking values
- model name

They are not the same thing as persona presets.

## Tutorials and In-App Help

Tutorial logic lives in:

- [tutorial_framework.py](/E:/Tools/Python_Scripts/NeuralInterface/tutorial_framework.py)
- [tutorials](/E:/Tools/Python_Scripts/NeuralInterface/tutorials)

The app can also inject help knowledge for the tutorial persona from:

- [app_help/knowledge.json](/E:/Tools/Python_Scripts/NeuralInterface/app_help/knowledge.json)

That retrieval logic lives in:

- [app_help.py](/E:/Tools/Python_Scripts/NeuralInterface/app_help.py)

## Important Folders

- [qt_app.py](/E:/Tools/Python_Scripts/NeuralInterface/qt_app.py)
  - main Qt application shell
- [engine.py](/E:/Tools/Python_Scripts/NeuralInterface/engine.py)
  - main runtime / orchestration layer
- [MuseTalk](/E:/Tools/Python_Scripts/NeuralInterface/MuseTalk)
  - MuseTalk worker/runtime/models
- [LoopAuthoring](/E:/Tools/Python_Scripts/NeuralInterface/LoopAuthoring)
  - local draft packages and generated loop experiments
- [body_configs](/E:/Tools/Python_Scripts/NeuralInterface/body_configs)
  - saved VSeeFace/body-side configurations
- [performance_profiles](/E:/Tools/Python_Scripts/NeuralInterface/performance_profiles)
  - saved performance profiles
- [presets](/E:/Tools/Python_Scripts/NeuralInterface/presets)
  - persona presets
- [runtime](/E:/Tools/Python_Scripts/NeuralInterface/runtime)
  - runtime files and logs
- [voices](/E:/Tools/Python_Scripts/NeuralInterface/voices)
  - voice reference files

## Troubleshooting

### No model appears in the model list

- Make sure `LM Studio` is running
- Make sure a model is actually loaded in LM Studio

### MuseTalk uses too much VRAM

Try:

- `Low VRAM`
- `Very Low VRAM`

These modes are the safer starting points.

### PocketTTS does not work

- PocketTTS should normally work from the bundled setup
- if you changed the advanced PocketTTS override, point it back to the bundled interpreter

### MuseTalk avatar tuning is slow

Use:

- `Debug First Frame`

before doing a full preprocess. That is the intended fast mask-tuning path.

### Loop Authoring feels experimental

That is accurate. The current Loop Authoring tab is an evolving local authoring helper, not a finished production pipeline.

## Current Practical Advice

For a new user:

1. Start `LM Studio`.
2. Get one successful `MuseTalk + PocketTTS` run working.
3. Use a lower MuseTalk VRAM mode first.
4. Use the tutorials.
5. Run `Dry Run` later for machine-specific tuning.

For MuseTalk avatar authoring:

1. Tune `BBox Shift` and the cheek/margin settings with `Debug First Frame`.
2. Only then run `Preprocess Avatar`.
3. Add emotion tags if you want the avatar variant to be reachable from bracket-tagged LLM output.

For loop creation:

1. Use `MuseTalk > Loop Authoring` to create a draft.
2. Generate a loop locally through Wan2GP or your chosen backend.
3. Use the resulting video as the MuseTalk source.
4. Preprocess it into a tagged avatar variant.

## Detailed Reference

This section is for users who want the reasoning behind the major controls and tradeoffs, not just the UI labels.

## Core Mental Model

In streaming mode, the app is balancing several competing goals at once:

- start the first spoken chunk early
- avoid awkward pauses between later chunks
- keep chunks large enough to sound natural
- keep the avatar engine responsive enough that it does not fall behind the speech

That means many settings are tradeoffs, not simple “higher is better” or “lower is better” controls.

## Avatar Engine

### MuseTalk

MuseTalk is the main built-in lip-sync pipeline.

Use MuseTalk when you want:

- integrated local lip-sync rendering
- streamed avatar replies
- MuseTalk VRAM modes
- Dry Run tuning
- local avatar preprocessing and mask tuning

MuseTalk is also where the app now includes:

- prepared avatar management
- first-frame debugging
- emotion-tagged avatar variants
- experimental local loop authoring handoff

### VSeeFace

VSeeFace is the alternate avatar-engine path.

Use it when you want:

- the VSeeFace-based avatar route exposed by the app
- body and dynamics tuning that is separate from MuseTalk preprocessing

## Input Mode

### Voice Activation

The microphone listens automatically for speech.

This is convenient for hands-free interaction, but it is also more sensitive to room noise and unintended triggers.

### Push-to-Talk

Push-to-Talk requires a deliberate talk action before speaking.

Use it when:

- the room is noisy
- you want fewer accidental triggers
- you prefer more explicit turn-taking

## Input Role

Recognized speech can currently be inserted as either:

- a `user` message
- or a `system` message

### User Message

This is the normal conversational mode.

### System Message

This is a more forceful instruction mode, because the recognized speech is treated more like a system-level directive than ordinary dialogue.

Use it carefully.

## Stream Mode

### Stream Mode On

When stream mode is on:

- the app starts speaking before the full reply is complete
- `PocketTTS` becomes the default TTS backend
- chunking becomes much more important
- Dry Run becomes especially useful

This is the mode most of the app’s advanced startup and overlap tuning is built around.

### Stream Mode Off

When stream mode is off:

- the app waits longer before speaking
- the TTS backend defaults back toward `Chatterbox / TurboTTS`
- chunking matters less for startup feel

This mode can be simpler, but less responsive.

## TTS Backend

### PocketTTS

PocketTTS is usually the more streaming-oriented choice.

Practical characteristics:

- faster startup
- often easier to pair with MuseTalk in streamed mode
- useful when responsiveness matters more than expressive richness

### Chatterbox / TurboTTS

Chatterbox is usually the more expressive choice.

Practical characteristics:

- richer vocal expression
- often better for nonverbal sounds and expressive tags
- usually heavier in streaming mode than PocketTTS

## MuseTalk VRAM Modes

These modes affect more than memory usage. They also change how heavy the MuseTalk pipeline is on the GPU and how agile it feels in streaming use.

### Quality

- highest-resource mode
- heaviest GPU behavior

### Balanced

- middle-ground mode

### Low VRAM

- lower GPU pressure
- often one of the best practical compromises

### Very Low VRAM

- widest hardware compatibility
- safest fallback starting point

## Persona Tab In Detail

The `Persona` tab is about identity and speaking style.

It includes:

- voice selection
- technical expressive rules / tags
- system prompt shaping
- optional advanced PocketTTS override

### Technical Rules / Tags

This field is about expressive guidance, not hardware tuning.

There are two important categories:

- state-like tags
  - for example visual mood tags such as `[happy]`, `[angry]`, `[shy]`
- action-like tags
  - for example brief vocal actions such as `[laugh]`, `[sigh]`, `[gasp]`

Important note:

- common mood tags still exist as part of the assistant’s expressive language
- MuseTalk avatar routing is now also metadata-driven, so additional visual mood tags can be introduced through avatar metadata such as `avatar_pose.json`

Example:

```text
[angry] No, absolutely not. [shy] Well... maybe. [laugh]
```

### System Prompt

This is one of the most important settings in the whole app. It shapes the assistant’s identity and behavioral framing far more than any performance setting.

## Brain Tab In Detail

The `Brain` tab controls how the language model samples text.

These settings affect style and variability, not the avatar pipeline directly.

### Temperature

Higher temperature:

- more variety
- more spontaneity
- more risk of drift or inconsistency

Lower temperature:

- more predictability
- less creative variation

### Top P

Lower `Top P` is more conservative.

Higher `Top P` is more open-ended.

### Top K

Lower `Top K` is tighter and more conservative.

Higher `Top K` allows broader variety.

### Repeat Penalty

Higher repeat penalty discourages repetition, but can also make the model avoid natural reuse too aggressively.

### Min P

Higher `Min P` can make output more focused, but sometimes more rigid.

### Response Length Limiting

Use this when you want:

- shorter replies
- more predictable response sizes
- less rambling

## Chunking Tab In Detail

The `Chunking` tab is one of the most important advanced tuning areas in the app.

It controls how text is split into spoken/rendered chunks.

### Standard

These values affect ordinary non-MuseTalk chunking behavior.

### MuseTalk Non-Stream

These values affect chunking when MuseTalk is used outside the streaming path.

This section also contains the `Quickstart` controls, which shape the early acceleration window of MuseTalk startup.

The idea is:

- the earliest chunks may need a different size regime than later steady-state chunks
- this helps balance startup speed against later stability

### Streaming

These are the most important chunking settings for stream mode.

#### Streaming Target Chars

Smaller values:

- earlier chunk release
- more responsiveness
- more risk of awkwardly small chunks

Larger values:

- more natural chunk boundaries
- more patience for punctuation
- more risk of delayed startup

#### Streaming Max Chars

This is the streaming safety ceiling.

#### First Chunk Min

This affects how soon the first chunk becomes eligible to emit.

#### First Flush / Later Flush

These are patience limits for chunk emission.

Higher values:

- more time for natural punctuation-aware cuts

Lower values:

- more aggressive flushing
- more risk of awkward boundaries

## VSeeFace Tabs In Detail

### Body

`VSeeFace > Body` is about pose and body shaping.

Use it to influence how the avatar physically behaves.

### Dynamics

`VSeeFace > Dynamics` is about how active or animated the motion feels.

This is more about animation feel than LLM behavior or pipeline performance.

## MuseTalk Preprocess In Detail

The `MuseTalk > Preprocess` area is now an authoring workflow, not just a one-shot import button.

The intended flow is:

1. choose source clip or frame folder
2. choose avatar id
3. tune mask settings
4. use `Debug First Frame`
5. optionally do `Audio Frame Test`
6. preprocess the real avatar
7. attach or edit emotion tags

### Why Debug First Frame Matters

Different source loops can vary a lot in:

- head distance from camera
- jaw proportions
- cheek width
- movement amplitude

So a one-size-fits-all mask is often not enough.

The first-frame debug tool exists to catch problems early, before you waste time doing a full preprocess on bad settings.

## Loop Authoring In Detail

The `MuseTalk > Loop Authoring` tab is meant to close a workflow gap:

- MuseTalk emotional loops are useful
- but users also need a practical way to create those loops

The current experimental direction is:

- author a source loop locally
- keep the flow inside the app as much as practical
- then hand the result directly into MuseTalk preprocessing

### Current Long-Sequence Tradeoff

There is currently a real tradeoff between:

- quality / continuity
- memory usage

Using the full previously rendered video usually preserves consistency better.

Using only tail context is usually more memory-safe for very long runs, but can drift sooner.

That tradeoff is why the current long-sequence modes are still marked experimental.

## Dry Run In Detail

Dry Run exists because the best startup and chunking settings are highly machine-dependent.

Dry Run tries candidate settings, measures them, and recommends a better configuration for the current hardware.

### What Dry Run Optimizes For

Dry Run tries to balance:

- first audio startup speed
- visual startup timing
- follow-up chunk readiness
- chunk quality
- practical chunk size

The goal is not:

- smallest chunks at all costs

or:

- biggest chunks at all costs

The goal is:

- early enough startup
- while keeping the pipeline stable and natural

## Performance Profiles In Detail

Performance Profiles store pipeline behavior, not persona identity.

They can contain things like:

- stream mode
- TTS backend
- MuseTalk VRAM mode
- chunking values
- quickstart values
- model name

They are useful because one user may want separate tuned profiles for:

- fast streaming
- expressive streaming
- low VRAM fallback

## Why Lower Modes Can Beat Heavier Modes

A lower VRAM mode can outperform a heavier mode even if the GPU has enough memory.

That is because:

- VRAM fit is only one part of the problem
- GPU workload and responsiveness also matter

So a heavier mode may fit in memory but still feel less agile in streaming use.

That is why Dry Run and real measurements matter more than assumptions like:

- “Quality must always be best”

## Practical Advice For Advanced Users

If you want to tune manually:

1. Start from a known good profile.
2. Change only one or two chunking values at a time.
3. Test in the same engine and TTS mode.
4. Watch startup feel, chunk rhythm, and avatar continuity.
5. Save good results as a new profile.

If you want the safest general strategy:

1. Start from a known-good profile.
2. Get one successful run working.
3. Use Dry Run afterward.

## Final Note

This project now has several substantial subsystems:

- local LLM
- TTS
- MuseTalk
- VSeeFace
- chunking / streaming
- performance profiling
- loop authoring

The app becomes much easier to work with if you treat it as layers:

1. get one stable path working
2. tune that path
3. only then expand into advanced MuseTalk authoring, Dry Run optimization, and loop creation
