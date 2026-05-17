# Install Guide

Neural Companion is currently a Windows-first Python 3.11 desktop app.

The recommended public install path is the unified installer:

Graphical installer:

```text
INSTALL_NEURAL_COMPANION.bat
```

If you prefer launching it from a terminal:

```powershell
py install_neural_companion_gui.py
```

The graphical installer detects Python 3.11, offers a Windows Python download
link when it is missing, can install bundled FFmpeg tools when `ffmpeg` or
`ffprobe` are not available, and includes links for Discord setup help plus the
Hugging Face token/model-term pages used by PocketTTS.

For RTX 50 / Blackwell GPUs, the installer can auto-select or manually force
the CUDA 12.8 PyTorch stack used by the main runtime and MuseTalk.

Command-line installer:

```powershell
py install_neural_companion.py --main --non-interactive
```

For a fuller local setup:

```powershell
py install_neural_companion.py --all
```

If Python 3.11 is not your default Python, pass the interpreter explicitly:

```powershell
py install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe"
```

The installer also tries to find Python 3.11 automatically through the Windows
Python launcher, PATH, and common install folders. The graphical installer shows
the detected interpreter and lets you browse to another `python.exe`.

## Requirement Files

- `requirements.txt` is the small baseline requirement list.
- `requirements.companion.txt` is the broader main-app runtime set used by the installer.
- `requirements.musetalk.txt` is the separate MuseTalk runtime set.

Most users should prefer the installer over manually installing requirement
files. The installer keeps incompatible runtime stacks separated where needed.

## Optional Runtime Pieces

MuseTalk:

```powershell
py install_neural_companion.py --musetalk --non-interactive
```

PocketTTS:

```powershell
py install_neural_companion.py --pockettts --non-interactive
```

The main app can run without MuseTalk, PocketTTS, VaM, VSeeFace, or API
providers. Start with `None` avatar mode and one working chat provider first.

## First Run Checklist

1. Start LM Studio or configure an API chat provider.
2. Run `run_neural_companion.bat` or `py qt_app.py`.
3. Select a chat provider and model.
4. Select `None` as Avatar Engine.
5. Select a TTS backend.
6. Press `Initialize System`.
7. Verify chat and speech before enabling heavier avatar or vision features.

## Assets

The public repo does not ship voice samples, avatar packs, model weights, or
generated images.

- Put your own voice references in `voices/`.
- Put MuseTalk avatar packs in `avatar_packs/<pack_id>/`.

Demo avatar packs live in:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks
```

See `docs/avatar_packs.md` and `docs/release_asset_policy.md` for the asset
policy.
