# Neural Companion Manual

Neural Companion is a local Windows desktop companion app for chat, speech,
avatar output, visual replies, and addon-driven workflows.

This manual is the user-facing starting point. For developer and addon docs,
see the broader `docs/` folder.

## Manual Sections

- [Installation](installation.md)
- [First Run](first-run.md)
- [Chat And TTS](chat-and-tts.md)
- [Avatars](avatars.md)
- [MuseTalk](musetalk.md)
- [PocketTTS](pockettts.md)
- [Visual Reply And Sensory Features](visual-reply-and-sensory.md)
- [Addons](addons.md)
- [Troubleshooting](troubleshooting.md)

## Recommended First Path

1. Install with the graphical installer.
2. Launch Neural Companion.
3. Select `LM Studio` or another working chat provider.
4. Select `None` as Avatar Engine.
5. Select a TTS backend.
6. Press `Initialize System`.
7. Verify basic chat and speech before enabling heavier avatar or vision features.

## Important Notes

- Windows and Python 3.11 are the expected baseline.
- FFmpeg should be available on PATH or installed through the bundled installer tools.
- MuseTalk works best with an NVIDIA CUDA GPU.
- Voice samples, avatar packs, model weights, logs, and runtime files are local
  user data and are not included in the main repository.
