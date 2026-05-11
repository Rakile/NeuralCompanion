# PocketTTS

PocketTTS is installed into an isolated runtime so its dependencies do not
collide with the main app.

## Installation

Use the graphical installer and keep `Isolated PocketTTS runtime` selected, or
run:

```powershell
py install_neural_companion.py --pockettts --non-interactive
```

The installer creates:

```text
.venvs/pockettts/
```

## Hugging Face Login

PocketTTS can install without Hugging Face login, but voice cloning may require:

1. Accepting the terms at:

```text
https://huggingface.co/kyutai/pocket-tts
```

2. Logging in with the isolated PocketTTS Hugging Face command:

```powershell
.\.venvs\pockettts\Scripts\hf.exe auth login
```

The graphical installer can prompt for this after PocketTTS installation if it
detects that login is missing.

## Troubleshooting

If the `hf.exe` command is missing, reinstall or upgrade the Hugging Face CLI in
the PocketTTS runtime:

```powershell
.\.venvs\pockettts\Scripts\python.exe -m pip install --upgrade "huggingface_hub[cli]"
```
