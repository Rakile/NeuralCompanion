# Third-Party Components And Assets

This document summarizes the main third-party surfaces for release review.
It is not legal advice; verify upstream terms before distributing binaries,
models, voice samples, avatar packs, or hosted-service integrations.

## Included Source

- Neural Companion source code is released under the repository `LICENSE`.
- MuseTalk runtime source is included under its upstream license in
  `MuseTalk/LICENSE`.
- PocketTTS 3.3.0 is included as the reviewed local wheel in `vendor/pockettts/`,
  from upstream commit `b94db177bc0f77517d9b124843e25605d6f9aed8`.
  Its original MIT notice is retained in `vendor/pockettts/LICENSE` and inside
  the wheel. The provenance manifest records exact file sizes and SHA256 values.
  This includes the Python package only; dependency and model/voice asset terms
  remain separate.

## Not Included In The Main Repo

The main repository intentionally does not ship:

- MuseTalk model weights or checkpoints
- prepared MuseTalk avatar packs
- voice reference samples beyond the selected bundled examples
- local session state, logs, screenshots, or clipboard captures
- VSeeFace, LM Studio, or other third-party applications

## External Runtime Dependencies

Stockfish is not included in the main installation. Companion Chess offers an explicit optional Windows download of pinned official Stockfish 19 universal binaries for x64 or ARM64 into a `Stockfish` subfolder of a user-selected folder, or selection of an existing engine. Stockfish is a separate GPLv3 chess-engine process; its original `Copying.txt`, `README.md`, and complete packaged `src/` tree are retained beside the downloaded executable. The setup helper records and verifies archive/file checksums. Runtime binaries must not be committed; source provenance is the official `sf_19` release at https://github.com/official-stockfish/Stockfish/releases/tag/sf_19.

The installer and requirements files may install packages from PyPI or external
model/tool ecosystems. Those packages keep their own licenses and terms.

Important examples:

- `chatterbox-tts` for local Chatterbox speech generation
- `faster-whisper` and related speech/transcription dependencies
- `openai` for OpenAI-compatible APIs and providers
- `PySide6` for the Qt desktop UI
- MuseTalk dependencies listed in `requirements.musetalk.txt`
- PocketTTS/Hugging Face assets, when users enable PocketTTS voice cloning

## Hosted Providers

Hosted providers and APIs are optional and require user-supplied credentials:

- OpenAI
- xAI / Grok
- DeepSeek
- Anthropic Claude
- Google Gemini TTS

Presets should not contain API keys or secrets. Session state may contain local
runtime settings and should not be committed.

## Avatar Packs And Voices

Avatar packs are local user assets and belong under:

```text
avatar_packs/<pack_id>/
```

Demo avatar packs are distributed through:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks
```

The public repository ships the approved Echo and Eon default voice references
and owner-approved Broid (`voices/broken android.wav`) and Nixie (`voices/nixie.wav`)
reference samples. Their starter persona definitions and available portraits are
under `ui/assets/personas/`. The Nixie LiquidAI LoRA configuration and weights
are included at `models/LFM3-Audio-2B-Nixie-LoRA`; the LiquidAI base model remains
a separate setup download. The owner-selected conversation background is included
at `ui/assets/backgrounds/stars_space_galaxy_117958_1920x1080.jpg`.

Selected additional example voices also live in `voices/`.
Other voice references are local user assets and belong under:

```text
voices/
```

Only distribute avatar packs, generated character media, or voice samples when
you have the rights and consent needed for that distribution.

## NC VSeeFace speech bridge

The owner-approved Echo test avatar and matching body preset are included at
`avatar_packs/VSeeFace/Echo/Echo.vrm` and `body_configs/Echo.json`. They are
separate from the MuseTalk Echo pack and from VSeeFace itself. See the [bundled asset guide](release_asset_policy.md) for general guidance.

NC distributes its bridge source/build instructions and prebuilt DLL under
`addons/vseeface_avatar/bridge_source/` and `bridge_payload/`. Users download VSeeFace themselves
and approve adding the loader/bridge to their selected installation. No VSeeFace EXE or managed
assemblies are distributed or modified.

The original BepInEx 5.4.23.3 Windows x64 archive is pinned by SHA256 in the payload manifest.
Its root license is MIT. Bundled components have separate notices in `bridge_payload/licenses/`,
including UnityDoorstop under LGPL-2.1. UnityDoorstop's exact corresponding source is retained in
`bridge_payload/third_party_source/UnityDoorstop-851712b.zip`. Installed copies retain these notices
and source archive. VSeeFace's extension policy requests freely available mods; the NC bridge
source is included in the NC package for inspection and self-compilation.
