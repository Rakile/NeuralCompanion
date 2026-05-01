# Install Guide

Neural Companion is currently a Windows-first Python 3.11 desktop app.

The recommended public install path is the unified installer:

```powershell
py install_neural_interface.py --main --non-interactive
```

For a fuller local setup:

```powershell
py install_neural_interface.py --all
```

If Python 3.11 is not your default Python, pass the interpreter explicitly:

```powershell
py install_neural_interface.py --python-exe "C:\Path\To\Python311\python.exe"
```

## Requirement Files

- `requirements.txt` is the small baseline requirement list.
- `requirements.companion.txt` is the broader main-app runtime set used by the installer.
- `requirements.musetalk.txt` is the separate MuseTalk runtime set.

Most users should prefer the installer over manually installing requirement
files. The installer keeps incompatible runtime stacks separated where needed.

## Optional Runtime Pieces

MuseTalk:

```powershell
py install_neural_interface.py --musetalk --non-interactive
```

PocketTTS:

```powershell
py install_neural_interface.py --pockettts --non-interactive
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
- Existing legacy packs under `MuseTalk/results/v15/avatar_packs/` are still detected.

See `docs/release_asset_policy.md` for the asset policy.
