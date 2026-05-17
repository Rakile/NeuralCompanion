# Troubleshooting

## The Installer Uses The Wrong Python

Neural Companion expects Python 3.11. If installation fails while building
packages such as `numpy` or reports `pkgutil.ImpImporter`, rerun the installer
with a Python 3.11 executable:

```powershell
py install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe"
```

## No Chat Response

- Check that the selected chat provider is reachable.
- For LM Studio, make sure the server is running and a model is loaded.
- For API providers, check the provider API key environment variable or provider settings.
- Refresh the model list after changing provider settings.

## No Speech

- Confirm a TTS backend is selected.
- If using Chatterbox voice cloning, provide your own permitted `.wav` reference
  under `voices/`.
- If no voice reference is configured, the app should still try to run without
  a cloned reference voice where the backend supports it.

## MuseTalk Is Slow Or Uses Too Much VRAM

- MuseTalk works best on an NVIDIA CUDA GPU.
- RTX 50 / Blackwell GPUs should use the installer CUDA 12.8 PyTorch stack.
  Use the graphical installer's PyTorch CUDA stack selector, or pass
  `--torch-stack cu128`, if auto-detection misses the card.
- Run Dry Run and save a local performance profile to reduce load on your hardware.
- Use shorter or fewer avatar variants when testing.
- `.npy` startup frame caches improve avatar-pack startup after the first run,
  but they use disk space.

## FFmpeg Or ffprobe Is Missing

Audio Story Mode and some media utilities need both `ffmpeg` and `ffprobe`.
The installer can place bundled FFmpeg tools under `tools/ffmpeg/bin` when they
are missing from PATH. Rerun the installer preflight or install target if these
warnings appear after moving to a new machine.

## Avatar Packs Are Not Found

Avatar packs belong here:

```text
avatar_packs/<pack_id>/
```

If an older local setup has packs under MuseTalk's result folders, move or
copy each pack folder into `avatar_packs/` so manifests remain portable.

## GPU Memory Does Not Drop Immediately

Terminate the engine from the UI first. If a worker process or external avatar
application is still running, close it separately. Local LLM servers such as LM
Studio may intentionally keep models loaded outside Neural Companion.

## Runtime Files Keep Appearing

Generated files under `runtime/`, `MuseTalk/runtime/`, `voices/`, and
`avatar_packs/` are local data and are ignored by Git. They are expected during
normal use.
