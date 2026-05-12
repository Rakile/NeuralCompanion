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
install_neural_companion_gui.bat
```

You can double-click the batch file from Explorer. If you prefer a terminal, run:

```powershell
py install_neural_companion_gui.py
```

The graphical installer:

- detects Python 3.11 automatically when possible
- lets you browse to another Python 3.11 executable
- installs the main Neural Companion runtime
- optionally installs the isolated MuseTalk runtime
- optionally installs the isolated PocketTTS runtime
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

If Python 3.11 is not your default Python:

```powershell
py install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe" --all
```

## Requirements

Recommended baseline:

- Windows
- Python 3.11
- FFmpeg on PATH
- a local or API chat provider
- NVIDIA CUDA GPU for MuseTalk

Useful external tools:

- LM Studio for local LLMs
- VSeeFace for VRM-style avatar output
- VaM plus the Neural Companion bridge/plugin for VaM output

## Running

Start Neural Companion:

```bat
run_neural_companion.bat
```

Or directly:

```powershell
py qt_app.py
```

The legacy fallback UI can be launched with:

```powershell
py qt_app.py --legacy-ui
```
