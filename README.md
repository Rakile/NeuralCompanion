# Neural Companion

Neural Companion is a local Windows desktop AI companion for realtime chat,
speech, avatars, visual replies, and addon-driven workflows.

It is designed for users who want a configurable AI companion that can talk,
listen, roleplay, use local or API models, drive avatars, and grow through
addons.

## What It Can Do

- Chat through local or API providers such as LM Studio, OpenAI, xAI/Grok,
  Claude, DeepSeek, Ollama, and addon providers.
- Speak through TTS backends such as Chatterbox, Gemini TTS Preview,
  PocketTTS, and addon backends.
- Drive avatars through MuseTalk, Scenic still-image packs, VSeeFace, VaM, or
  no-avatar mode.
- Use screen, webcam, clipboard, heart-rate, and visual-reply workflows.
- Save and reload chat contexts.
- Use Continuity Memory summaries and Long-Term Memory archive retrieval.
- Run Multi Persona Roleplay Companion, tutorials, presets, hotkeys, chat
  replay, and addon tools.
- Use spellchecking in typed chat and optional dependency repair for supported
  features.

## Current Highlights

- **Multi Persona Roleplay Companion:** story setup, personas, narrator and
  character routing, a dedicated Play view, voice routing, visual prompt
  debugging, and story state tools.
- **Scenic Avatar Engine:** portable still-image avatar packs that map tags to
  images and can be previewed through the MuseTalk Preview window.
- **Memory systems:** per-chat Continuity Memory summaries and Long-Term Memory
  archive retrieval with optional embeddings.
- **Local provider support:** LM Studio and Ollama support for local chat model
  workflows.

For release history, see [CHANGELOG.md](CHANGELOG.md).

## Requirements

Neural Companion currently requires:

- Windows
- Python 3.11
- FFmpeg, either installed on PATH or provided by the bundled installer tools
- A local or API chat provider
- An NVIDIA CUDA GPU for MuseTalk avatar generation and playback

Python 3.11 is required. Python 3.12+ is not currently supported by the full
runtime stack, and older Python versions may fail during dependency
installation.

Useful external tools:

- LM Studio for local LLMs
- VSeeFace for VRM-style avatar output
- VaM plus the Neural Companion bridge/plugin for VaM output

## Install

For most users, use the graphical installer:

```text
INSTALL_NEURAL_COMPANION.bat
```

The installer should be run with Python 3.11 available on the system. If Python
3.11 is not your default Python, choose or provide the Python 3.11 executable
when installing.

For the detailed public install guide, see:

- [docs/install.md](docs/install.md)
- [docs/manual/installation.md](docs/manual/installation.md)

Advanced command-line install options are documented in the manual. They are
intended for users who already know which runtime components they want to
install.

## Run

Start Neural Companion with:

```bat
run_neural_companion.bat
```

This is the recommended launch method because it uses the installed Neural
Companion environment.

If you need to run the app manually from the project folder, use the installed
environment explicitly:

```bat
.venv\Scripts\python.exe qt_app.py
```

Or activate the environment first:

```bat
.venv\Scripts\activate.bat
python qt_app.py
```

## First Run

The simplest first run is to follow the tutorial displayed at first launch.

If you want to start manually:

1. Start LM Studio and load a chat model.
2. Start Neural Companion.
3. Select `LM Studio` as Chat Provider.
4. Select `None` as Avatar Engine.
5. Select a TTS backend.
6. Press `Initialize System`.
7. Use push-to-talk or typed input to verify chat and speech.

Once that works, enable MuseTalk, VSeeFace, VaM, visual replies, or sensory
addons one at a time.

## Voices

The public repo ships with two voice samples.

If you want Chatterbox or another backend to clone a reference voice, place your
own `.wav` files under:

```text
voices/
```

Only use voice files you have the right to use.

## Avatar Packs

MuseTalk avatar packs belong in:

```text
avatar_packs/<pack_id>/
```

Large avatar packs and frame caches are intentionally not stored in the main
repository. Demo packs live in the separate
[NeuralCompanion-AvatarPacks](https://github.com/Rakile/NeuralCompanion-AvatarPacks)
repository.

Useful docs:

- [docs/avatar_packs.md](docs/avatar_packs.md)
- [docs/release_asset_policy.md](docs/release_asset_policy.md)

## Addons

Most runtime capabilities are implemented as addons under `addons/`.

Useful docs:

- [docs/addon_quickstart.md](docs/addon_quickstart.md)
- [docs/chat_provider_addons.md](docs/chat_provider_addons.md)
- [docs/vision_source_addons.md](docs/vision_source_addons.md)
- [docs/visual_reply_addons.md](docs/visual_reply_addons.md)
- [docs/addon_state_and_presets.md](docs/addon_state_and_presets.md)

## More Documentation

See the [Neural Companion Manual](docs/manual/index.md) for installation,
first-run, avatar, TTS, PocketTTS, MuseTalk, addon, and troubleshooting
guidance.

For development and repository details, see:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [docs/release_checklist.md](docs/release_checklist.md)
- [docs/third_party_and_assets.md](docs/third_party_and_assets.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [docs/known_limitations.md](docs/known_limitations.md)

## Licensing

Neural Companion is released under the MIT License. See [LICENSE](LICENSE).

Bundled third-party components may carry their own licenses. MuseTalk is
included under its upstream MIT license in [MuseTalk/LICENSE](MuseTalk/LICENSE).

You are responsible for complying with the terms of any external model,
provider, voice, avatar, or generated asset you use with the app.

## Current Limitations

- Neural Companion is currently Windows only.
- MuseTalk requires an NVIDIA CUDA GPU.
- Some integrations require external applications or plugins.
- Public demo assets are intentionally not bundled in the main repo.

## Community

The project is intended to grow through community feedback, addon development,
and shared workflows. Join the setup/help Discord here:

```text
https://discord.gg/UqnwX46rcK
```
