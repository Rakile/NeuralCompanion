# Known Limitations

Neural Companion is powerful, but it is still a local experimental companion
application. These are the main limitations to expect during the first public
release.

## Platform

- Windows is the primary supported platform.
- Python 3.11 is the expected runtime.
- CUDA/NVIDIA is strongly recommended for MuseTalk.

## Setup Complexity

- Some features require separate tools or services, such as LM Studio, VaM,
  VSeeFace, external API keys, or MuseTalk model weights.
- The unified installer handles the expected paths, but manual GPU/Python
  environments can still need local adjustment.

## Assets

- Voice samples and avatar packs are not bundled in the main repository.
- Users must provide assets they have the right to use.
- Demo avatar packs should be distributed outside the main repo.

## UI State

- The Designer-backed `main.ui` path is the default startup UI.
- The older Python-built Qt shell remains available through `--legacy-ui` as a
  temporary fallback.

## Runtime Behavior

- Real-time TTS, STT, avatar rendering, and visual generation depend heavily on
  local hardware and selected providers.
- MuseTalk startup can be slow the first time an avatar pack is loaded.
- External providers may change API behavior or pricing independently of this repo.

## Addons

- Addons are intentionally loosely coupled.
- Some experimental addons may need provider keys, model weights, or external
  services before they are useful.
