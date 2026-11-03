# LiquidAI TTS addon

Local LFM3-Audio-2B speech output with built-in and automatically discovered local LoRA voices, a managed Python 3.12 environment, an owned worker process and Resources integration.

See [the user guide](../../docs/manual/liquidai-tts.md) for setup, settings, troubleshooting and model licensing. The NC main-runtime installer includes LiquidAI using this addon's existing setup pipeline and reuses a ready installation. The in-app **Setup** tab retains **Check setup**, **Install / Repair** and **Cancel setup**. Discovery does not install dependencies or load models. NC keeps its existing completed-audio speech-chunk contract.

Only main-installer setup opts into automatic Python provisioning. When no usable
Python 3.12 is found on Windows x64, `python_bootstrap.py` downloads a pinned
[Astral python-build-standalone release](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026):
CPython 3.12.16, `x86_64-pc-windows-msvc-install_only`, 47,113,364 bytes,
SHA-256 `590dfcbe3a34c07301e6332e13e2188b98655cd072b08afa45a7998dc4c22bc5`.
All archive files, including its license, are retained in the private installation
after extraction at `.venvs/liquidai_python312`; the temporary downloaded archive
is removed. Size/hash and isolated `ssl`, `venv` and `ensurepip` imports are checked
before publishing. No system installer, registry registration, PATH edit or main
`.venv` change occurs. Keep this base interpreter for LiquidAI's virtual environment.
Unknown/incomplete destination contents are preserved and reported for repair.
In-app setup still uses an available Python 3.12 and does not initiate a bootstrap.

Put compatible LoRA folders directly under `models`, then use **Refresh voices** in LiquidAI settings. Folder names supply default voice names; optional `voice.json` metadata keeps display labels separate from trained prompt names.

Run focused tests from the NC source root:



The NC-side code uses only existing dependencies. Private synthesis pins are in `requirements.txt`; Torch CUDA 12.8 is installed separately by the setup worker. Native audio-to-audio integration is outside this addon.
