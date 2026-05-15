# Neural Companion Install

## Quick Start

Neural Companion currently expects **Python 3.11**.

1. Make sure Python 3.11 is installed.
2. Open PowerShell in this folder.
3. Run the graphical installer:

```text
INSTALL_NEURAL_COMPANION.bat
```

Or run the command-line installer:

```powershell
py install_neural_companion.py
```

This installer can:
- validate Python 3.11
- check for FFmpeg, NVIDIA / CUDA, LM Studio, and an optional bundled VSeeFace folder
- install the main app runtime
- optionally install MuseTalk
- optionally install PocketTTS
- validate the created runtimes at the end

If Python 3.11 is not your default Python, run:

```powershell
py install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe"
```

If the installer ever shows an error mentioning `pkgutil.ImpImporter` or says it failed while building `numpy`, that almost always means it ran under Python 3.12 instead of Python 3.11. Use a Python 3.11 interpreter and rerun the installer.

If the installer instead fails while building `pandas`, that usually means pip fell back to a source build. This package now pins a compatible `pandas` wheel, so just rerun the installer with the updated package.

To install everything in one go instead of using the interactive prompts:

```powershell
py install_neural_companion.py --all
```

To install only the main app non-interactively:

```powershell
py install_neural_companion.py --main --non-interactive
```

Legacy PowerShell wrapper scripts are still present, but they now just forward into the unified Python installer:
- `install_neural_companion.ps1`
- `install_musetalk.ps1`
- `install_pockettts.ps1`

4. Start the app with:

```bat
run_neural_companion.bat
```

5. Optional: if you skipped PocketTTS during the unified install, you can still add it later with:

```powershell
py install_neural_companion.py --pockettts --non-interactive
```

PocketTTS voice cloning still needs two manual steps:

1. Accept the terms at [kyutai/pocket-tts](https://huggingface.co/kyutai/pocket-tts)
2. Log in locally before first use:

```powershell
.\.venvs\pockettts\Scripts\hf.exe auth login
```

Without that login, PocketTTS can still use its built-in catalog voices, but cloning from your own reference voice will fail.
The graphical installer can also open this login command after the PocketTTS install step and can offer to install the Hugging Face CLI into the isolated PocketTTS runtime if `hf.exe` is missing.

6. Optional: if you skipped MuseTalk during the unified install, you can still add it later with:

```powershell
py install_neural_companion.py --musetalk --non-interactive
```


## External Tools Still Needed

- `LM Studio` running locally with at least one model loaded
- `FFmpeg` available on PATH
- NVIDIA / CUDA if you want good MuseTalk performance

## Notes

- `VSeeFace-v1.13.38c4` is optional. If the folder is absent, the installer will warn but continue.
- The main app installer uses the validated CUDA 12.6 torch stack for the main runtime: `torch==2.6.0`, `torchaudio==2.6.0`, `torchvision==0.21.0`. On RTX 50 / Blackwell cards it switches the main app torch stack to CUDA 12.8 wheels.
- After the main requirements and any torch override, the installer force-repairs the compiled scientific ABI group: `numpy==1.24.4`, `pandas==1.5.3`, `scipy==1.11.4`, and `scikit-learn==1.3.2`. This avoids NumPy/Pandas binary mismatch errors after CUDA 12.8 installs.
- The installer also applies the known-good runtime pins: `pillow==11.2.1` and `PyAudio==0.2.14`.
- `MuseTalk` runtime code is included, but MuseTalk model weights and prepared avatar packs are intentionally omitted from this Git package.
- `MuseTalk/data` demo media is intentionally omitted from this repo to keep it lighter.
- The unified installer downloads MuseTalk model weights during the MuseTalk install step.
- To use MuseTalk after install, preprocess/import an avatar pack into `avatar_packs` or add one manually.
- This package omits TensorFlow / TensorBoard training dependencies because they are not needed for normal runtime use and they conflict with Chatterbox on Python 3.11.
The package also pins `chatterbox-tts==0.1.6`, `transformers==4.46.3`, and `numpy==1.24.4` together, because newer Chatterbox releases pull incompatible dependency combinations for this app.
`diffusers` is pinned to `0.29.0` to stay compatible with the pinned Chatterbox runtime stack.
`gradio` is pinned to `5.44.1` to stay aligned with the pinned Chatterbox runtime stack; the main Qt app does not depend on Gradio directly.
`moviepy` is omitted because it is only used by the bundled MuseTalk Gradio demo path, not by the main Qt runtime, and old resolver paths can fail to build on modern Python setups.
PocketTTS is installed into the separate `.venvs\pockettts` runtime when selected in the installer, so its `numpy>=2` dependency does not conflict with the pinned Chatterbox + MuseTalk runtime stack.
Use `install_neural_companion.py --pockettts --non-interactive` to recreate that separate runtime if needed.
Use `install_neural_companion.py --musetalk --non-interactive` to create the separate `MuseTalk\.venv` runtime that the app expects for the MuseTalk backend. On older CUDA cards the installer uses the same MuseTalk torch stack as the original working setup: `torch==2.0.1+cu118`, `torchaudio==2.0.2+cu118`, and `torchvision==0.15.2+cu118`. On RTX 50 / Blackwell cards it switches the isolated MuseTalk runtime to CUDA 12.8 with `torch==2.10.0`, `torchvision`, and `torchaudio`, then reapplies that torch stack after the pinned requirement pass so the backend keeps sm_120 support. That cu128 path skips the old `mmcv` bootstrap, filters the OpenMMLab preprocessing packages from the pinned requirement pass, and installs `mediapipe` instead; MuseTalk will use MediaPipe as the avatar-preprocessing fallback when OpenMMLab cannot load.
The packaged MuseTalk requirement export is trimmed to remove stale environment-only packages like `chumpy` that are not used by the runtime path but can fail to build on a fresh machine.
The MuseTalk installer now installs `mmcv==2.0.1` through `openmim` instead of asking plain pip to build it, and it omits `mmcv-full` from the packaged requirement export.
The MuseTalk installer also preinstalls `chumpy==0.70` with `--no-build-isolation` before the main requirement pass, because the normal isolated build path can fail on fresh Windows machines.
`huggingface_hub` is pinned to `0.33.5` so it remains compatible with the pinned Gradio and Diffusers runtime stack.
- Local temp/session files were intentionally left out.
- If `torch` installation needs a custom CUDA wheel on the target machine, rerun the installer with:

```powershell
.\install_neural_companion.ps1 -SkipTorch
```

and install the correct `torch`/`torchaudio` pair manually first.
