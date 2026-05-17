# Troubleshooting

## Installer Uses The Wrong Python

Neural Companion expects Python 3.11. If the installer selects the wrong Python,
pass the interpreter explicitly:

```powershell
py install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe" --all
```

## No Chat Response

- Check that the selected chat provider is reachable.
- For LM Studio, make sure the server is running and a model is loaded.
- For API providers, check provider keys and settings.
- Refresh the model list after changing provider settings.

## No Speech

- Confirm a TTS backend is selected.
- Check audio output device settings.
- If using voice cloning, provide your own permitted `.wav` reference under
  `voices/`.

## MuseTalk Is Slow Or Uses Too Much VRAM

- Use an NVIDIA CUDA GPU.
- RTX 50 / Blackwell GPUs should use the installer CUDA 12.8 PyTorch stack.
  Use the graphical installer's PyTorch CUDA stack selector, or pass
  `--torch-stack cu128`, if auto-detection misses the card.
- Start with shorter or simpler avatar packs.
- Run Dry Run and save a performance profile.
- Enable startup caches only if you have disk space available.

## FFmpeg Or ffprobe Is Missing

Audio Story Mode and media utilities need both `ffmpeg` and `ffprobe`. Rerun
the installer preflight or install target so it can place bundled FFmpeg tools
under `tools/ffmpeg/bin` when they are not available on PATH.

## Avatar Packs Are Not Found

Avatar packs belong here:

```text
avatar_packs/<pack_id>/
```

Each pack should include its own `manifest.json`.

## PocketTTS Cloning Is Not Ready

Accept the model terms and log in:

```powershell
.\.venvs\pockettts\Scripts\hf.exe auth login
```

If `hf.exe` is missing:

```powershell
.\.venvs\pockettts\Scripts\python.exe -m pip install --upgrade "huggingface_hub[cli]"
```

## Runtime Files Keep Appearing

Generated files under these folders are expected and ignored by Git:

```text
runtime/
MuseTalk/runtime/
avatar_packs/
voices/
```

They can usually be cleaned when troubleshooting, but avoid deleting personal
voice references or avatar packs you want to keep.
