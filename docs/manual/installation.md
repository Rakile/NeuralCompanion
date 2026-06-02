# Installation

Neural Companion is currently a Windows-first Python 3.11 desktop app.

## Clone

Clone the main branch:

```powershell
git clone https://github.com/Rakile/NeuralCompanion.git
cd NeuralCompanion
```

## Graphical Installer

The recommended installer is:

```text
INSTALL_NEURAL_COMPANION.bat
```

You can double-click the batch file from Explorer. If you prefer a terminal, run:

```powershell
py install_neural_companion_gui.py
```

The graphical installer:

- detects Python 3.11 automatically when possible
- lets you browse to another Python 3.11 executable
- opens the official Windows Python downloads page if Python 3.11 is missing
- installs the main Neural Companion runtime
- optionally installs the isolated MuseTalk runtime
- optionally installs the isolated PocketTTS runtime
- installs bundled FFmpeg tools when `ffmpeg` or `ffprobe` are missing
- lets RTX 50 / Blackwell users force the CUDA 12.8 PyTorch stack if detection is wrong
- links to Discord setup help and Hugging Face token/model-term pages
- can run preflight checks before install

MuseTalk and PocketTTS are isolated so their dependencies do not collide with
the main app runtime.

## Command-Line Installer

Install the main runtime:

```powershell
py install_neural_companion.py --main --non-interactive
```

Install the main runtime, MuseTalk, and PocketTTS:

```powershell
py install_neural_companion.py --all
```

Install the default Echo and Eon MuseTalk avatar packs:

```powershell
py install_neural_companion.py --avatar-packs --non-interactive
```

The graphical installer selects both default avatar packs by default. The
command-line `--all` target installs the main, MuseTalk, and PocketTTS runtimes;
combine it with `--avatar-packs` when you also want the avatar packs.

If Python 3.11 is not your default Python:

```powershell
py install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe" --all
```

## Requirements

Required baseline:

- Windows
- Python 3.11
- FFmpeg on PATH, or the installer-bundled FFmpeg tools
- a local or API chat provider
- NVIDIA CUDA GPU for MuseTalk

Python 3.11 is required. Python 3.12+ is not currently supported by the full
runtime stack, and older Python versions may fail during dependency
installation.

Useful external tools:

- LM Studio for local LLMs
- VSeeFace for VRM-style avatar output
- VaM plus the Neural Companion bridge/plugin for VaM output

## Running

Start Neural Companion:

```bat
run_neural_companion.bat
```

This is the recommended launch method because it uses the installed Neural
Companion environment.

If you need to run the app manually from the project folder, use the installed
environment explicitly:

```bat
.venv\Scripts\python.exe qt_app.py
```

Or activate the environment first:

```bat
.venv\Scripts\activate.bat
python qt_app.py
```
