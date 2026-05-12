# MuseTalk

MuseTalk provides local avatar video generation. It is powerful, but it is also
the most hardware-sensitive part of Neural Companion.

## Installation

Use the graphical installer and keep `Isolated MuseTalk runtime` selected, or
run:

```powershell
py install_neural_companion.py --musetalk --non-interactive
```

The installer creates:

```text
MuseTalk/.venv/
```

It also downloads the expected MuseTalk model weights when they are missing.

## Avatar Packs

Avatar packs belong here:

```text
avatar_packs/<pack_id>/
```

Example:

```text
avatar_packs/Echo/manifest.json
avatar_packs/Echo/echo_neutral/
avatar_packs/Echo/echo_angry/
avatar_packs/Echo/echo_sad/
```

Demo packs are distributed separately:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks
```

The current Echo demo pack uses the `neutral`, `angry`, and `sad` emotion tags.

## Performance

- Use an NVIDIA CUDA GPU.
- First startup can be slow while models and avatar frames warm up.
- Use Dry Run and performance profiles to tune settings.
- `.npy` startup frame caches can improve avatar-pack startup time, but use disk
  space.

## Generated Files

MuseTalk generated data belongs under ignored runtime folders such as:

```text
MuseTalk/runtime/
MuseTalk/results/
```

Do not commit generated frames, videos, model weights, or caches to the main
repository.
