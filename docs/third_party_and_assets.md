# Third-Party Components And Assets

This document summarizes the main third-party surfaces for release review.
It is not legal advice; verify upstream terms before distributing binaries,
models, voice samples, avatar packs, or hosted-service integrations.

## Included Source

- Neural Companion source code is released under the repository `LICENSE`.
- MuseTalk runtime source is included under its upstream license in
  `MuseTalk/LICENSE`.
- The VaM bridge source under `nuralcompanionbridge/` is part of this repo,
  but VaM itself is external software.

## Not Included In The Main Repo

The main repository intentionally does not ship:

- MuseTalk model weights or checkpoints
- prepared MuseTalk avatar packs
- voice reference samples
- generated images, generated videos, frame caches, or `.npy` / `.npz` caches
- local session state, logs, screenshots, or clipboard captures
- VSeeFace, VaM, LM Studio, or other third-party applications

## External Runtime Dependencies

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

Voice references are local user assets and belong under:

```text
voices/
```

Only distribute avatar packs, generated character media, or voice samples when
you have the rights and consent needed for that distribution.
