# Neural Companion

Neural Companion is a local desktop AI companion shell for realtime chat,
speech, avatar output, visual replies, and addon-driven workflows.

The project is designed as a box of LEGO pieces:

- chat providers are addons
- TTS backends are addons
- avatar engines are addons
- vision/sensory sources are addons
- workspace tabs and tools can be extended over time

The app runs locally on Windows and is built around a PySide6 desktop UI.

## Status

This repository is approaching its first public release. It is usable, but still
an experimental local AI/avatar application. Expect sharp edges around GPU
setup, third-party model installs, external avatar engines, and local device
configuration.

## Highlights

- Local or API chat providers: LM Studio, OpenAI, xAI/Grok, Claude, and addon providers.
- TTS backends: Chatterbox, Gemini TTS Preview, PocketTTS, and addon backends.
- Avatar engines: MuseTalk, VSeeFace, VaM, or no-avatar mode.
- Dockable Qt workspace with system shaping, runtime console/chat, preview panels, and addon tabs.
- MuseTalk preview and avatar-pack support.
- VaM bridge support through VMC and file-bridge flows.
- Vision and sensory supervisors for screen, webcam, clipboard, heart-rate, and visual replies.
- Presets, performance profiles, tutorials, hotkeys, and chat replay tools.

## Requirements

Recommended baseline:

- Windows
- Python 3.11
- FFmpeg on PATH
- a local or API chat provider
- NVIDIA CUDA GPU for MuseTalk

Useful external tools:

- LM Studio for local LLMs
- VSeeFace for VRM-style avatar output
- VaM plus the Neural Companion bridge/plugin for VaM output
- MuseTalk model weights if using MuseTalk

## Install

Open PowerShell in the repository root.

For the detailed public install guide, see [docs/install.md](docs/install.md).

For the main app:

```powershell
py install_neural_interface.py --main --non-interactive
```

For a fuller install:

```powershell
py install_neural_interface.py --all
```

If Python 3.11 is not your default Python:

```powershell
py install_neural_interface.py --python-exe "C:\Path\To\Python311\python.exe"
```

Optional installs:

```powershell
py install_neural_interface.py --musetalk --non-interactive
py install_neural_interface.py --pockettts --non-interactive
```

## Run

```bat
run_neural_companion.bat
```

Or directly:

```powershell
py qt_app.py
```

The Designer-backed UI can be launched with:

```powershell
py qt_app.py --ui-real main.ui
```

## First Run

The simplest first run is:

1. Start LM Studio and load a chat model.
2. Start Neural Companion.
3. Select `LM Studio` as Chat Provider.
4. Select `None` as Avatar Engine.
5. Select a TTS backend.
6. Press `Initialize System`.
7. Use push-to-talk or type input to verify chat and speech.

Once that path works, enable MuseTalk, VSeeFace, VaM, visual replies, or sensory
addons one at a time.

## Voice References

The public repo does not ship voice samples.

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
repository. See [docs/avatar_packs.md](docs/avatar_packs.md) and
[docs/release_asset_policy.md](docs/release_asset_policy.md).

## Runtime Data

Generated files are ignored by Git. Important generated locations include:

- `runtime/`
- `MuseTalk/runtime/`
- `avatar_packs/`
- `voices/`

Diagnostic file logs are off by default. Enable only when debugging:

```powershell
$env:NC_MUSETALK_WORKER_LOG = "1"
$env:NC_MUSETALK_PREVIEW_LOG = "1"
```

## Addons

Most runtime capabilities are implemented as addons under `addons/`.

Useful docs:

- [docs/chat_provider_addons.md](docs/chat_provider_addons.md)
- [docs/vision_source_addons.md](docs/vision_source_addons.md)
- [docs/vision_supervisor_addons.md](docs/vision_supervisor_addons.md)
- [docs/visual_reply_addons.md](docs/visual_reply_addons.md)
- [docs/addon_state_and_presets.md](docs/addon_state_and_presets.md)

## Repository Hygiene

The main repository should not contain local runtime outputs, model weights,
avatar packs, voice samples, generated images, logs, or local virtual
environments.

See:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [docs/avatar_packs.md](docs/avatar_packs.md)
- [docs/release_checklist.md](docs/release_checklist.md)
- [docs/release_asset_policy.md](docs/release_asset_policy.md)
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

- Setup is still Windows/Python-heavy.
- MuseTalk requires separate model weights and benefits strongly from CUDA.
- Some integrations require external applications or plugins.
- The new Designer-backed UI is still being integrated alongside the legacy Qt shell.
- Public demo assets are intentionally not bundled in the main repo.

## Community

The project is intended to grow through community feedback, addon development,
and shared workflows. Discord/community links can be added here for the public
release.
