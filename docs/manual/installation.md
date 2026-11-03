# Installation

This page walks through installation. For command-line examples and environment details, see the [installation reference](../install.md).

## What you need first

- Windows.
- Installed Python **3.11** for NC. Keep the installer's Python selector on 3.11; the main installer automatically provisions a private Python **3.12** for LiquidAI if no usable installation is found (Windows x64).
- Enough disk space for the runtimes and models you select.
- A chat provider for the first reply: a running LM Studio or Ollama server with a model, or credentials for a supported API provider.
- An NVIDIA CUDA GPU for the supported MuseTalk or Ditto installation. Hardware needs for chat and speech depend on your selected providers; use hosted providers or compatible local models for your machine.

Linux work is maintained in the separate [NeuralCompanion-Linux repository](https://github.com/Rakile/NeuralCompanion-Linux).

## Choose what to install

| Component | Required? | What it is for |
| --- | --- | --- |
| **Main runtime** | Yes | The app, native QML interface, standard chat/speech stack including isolated LiquidAI TTS and its pinned model, MCP Core and phone-pairing QR support. Stockfish is optional: install it or select an existing engine in Companion Chess → Setup. |
| **MuseTalk runtime** | Optional | Prepared talking-face avatars. Needs CUDA, models, and a MuseTalk pack. |
| **Ditto runtime** | Optional | Talking avatars prepared from a portrait or short video. Uses its own environment and packages. |
| **PocketTTS runtime** | Optional | Local PocketTTS speech. Reference cloning may need a Hugging Face login. |
| **Echo / Eon avatar packs** | Optional | Prepared MuseTalk demo packs. Separate from the MuseTalk engine. |

Adding a runtime does not activate it, and installing a pack does not select it. Configuration happens in the app.

LiquidAI is installed as part of **Main runtime**, using its existing private
environment and roughly 4.2 GB model download. Existing downloaded models are retained.
If Python 3.12 is missing, the installer verifies and installs a private copy at
`.venvs/liquidai_python312`. System Python and PATH stay unchanged. Retain this private base interpreter with the LiquidAI environment.
Its in-app **Setup** tab remains available for checks and **Install / Repair**;
the main installer does not change your voice, language or provider selection.

The main runtime includes the pinned MCP SDK and chess dependencies. You still
connect the chess server and approve its tools in NC; installation does not grant
permissions. For an update, use the latest intended release or branch files
before rerunning the installer. The installer does not fetch application updates.

## Install with the graphical installer

1. Open `INSTALL_NEURAL_COMPANION.bat` from the project folder, or run `py -3.11 install_neural_companion_gui.py`.
2. On the Python card, confirm the detected interpreter is Python 3.11. Use **Detect** or **Browse** to correct it, or **Get Python 3.11** to install the right version.
3. Under **Install targets**, review the preselected runtimes. The current installer preselects the main runtime, MuseTalk, Ditto, PocketTTS, Echo, and Eon. Change those choices to match what you actually intend to use.
4. Under **Default avatar packs**, keep Echo and Eon only if you are installing MuseTalk and want those prepared packs.
5. Choose **RUN PREFLIGHT ONLY** and read the warnings.
6. Choose **INSTALL SELECTED** and wait for each component.
7. Keep the final summary. If one component failed, repair that component rather than reinstalling everything.

For RTX 50 / Blackwell cards, review the PyTorch stack selector. **Auto-detect GPU** is the normal choice; **Force CUDA 12.8 / RTX 50** is available when detection misses the card.

## Space, progress and retries

Select the components you want, then choose **INSTALL SELECTED**. The space
summary updates with your choices and shows the installation and temporary-drive
budgets separately, or combines them when they share a drive. **Refresh space**
updates the available-space reading without changing your choices.

Sizes are approximate Windows CUDA figures, rounded upward from a measured
installation: main runtime including LiquidAI about **16.5 GB**, MuseTalk
**16 GB**, Ditto **10.5 GB**, PocketTTS **1 GB**, Echo **0.9 GB**, and Eon
**0.8 GB** (decimal GB). The installer budgets additional safety and working
space. These are estimates, not a guarantee of peak usage. Other models fetched
on first use, such as your chosen local language model, need additional space.

If space is insufficient, a **Retry / Cancel** dialog keeps the installer open.
Free space on the indicated drive and choose **Retry**. Space is checked before
installation, between components and during controlled download/extraction
writes; no idle disk-space watchdog runs. Package tools such as pip cannot be
safely paused halfway through changing packages. If one fails, free space and
select that component again.

The progress bar counts completed components, rather than estimating remaining
time. The status shows the current component and operation; avatar extraction
also reports percentage progress. Scroll up in the live output to read earlier
messages; scroll back to the bottom to resume following new output.

Selecting an installed runtime gives it a fresh managed Python environment.
Only that component's environment is replaced: models, custom voices, avatar
packages, settings and conversations remain in place. Close NC first and use
**INSTALL_NEURAL_COMPANION.bat**, which runs outside NC's own environment.
A failed installation can be retried by selecting the same component again.

Echo and Eon are validated against their downloaded archives. An incomplete pack
is staged and checked on the destination drive before replacement. An earlier
incomplete or different pack is preserved under
`avatar_packs/.previous-installs/` so additional personal files cannot be lost.
A verified existing pack and its additional files stay in place.

Disposable installer-owned pip/uv caches are removed after successful
validation. Failed installs retain resumable caches. Runtime caches, downloaded
models, and shared pip/uv/Hugging Face caches used by other applications are
preserved.

## Install from the command line

A minimal main-runtime install:

```powershell
py -3.11 install_neural_companion.py --main --non-interactive
```

Optional runtimes:

```powershell
py -3.11 install_neural_companion.py --musetalk --non-interactive
py -3.11 install_neural_companion.py --ditto --non-interactive
py -3.11 install_neural_companion.py --pockettts --non-interactive
```

`--all` installs the main app, MuseTalk, Ditto, and PocketTTS, but not the avatar packs. Add `--avatar-packs` for both default packs, or use `--avatar-pack-echo` / `--avatar-pack-eon` for one.

If the wrong Python is detected, pass it explicitly:

```powershell
py -3.11 install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe" --main --non-interactive
```

Use `--doctor-only` to inspect prerequisites without installing. See the [installation guide](../install.md) for the CUDA override and other options.

## Verify the installation

1. Launch `run_neural_companion.bat`. The window opening is not the same as starting the runtime.
2. Follow [First run](first-run.md) to select a language provider, use **Test connection**, and choose **Make active**.
3. In **Session setup**, choose **Text Only**. In **Text-to-speech** and **Avatar**, choose **None** for a silent text test.
4. Use the header power control, **Initialize NC**, once. Wait for **NC ready**.
5. Send a short message from **Conversation**.

If text works, add speech or an avatar one component at a time. See [Chat and speech](chat-and-tts.md) and [Troubleshooting](troubleshooting.md).

## Where your data lives

- `voices/` holds voice references, including the approved bundled samples and any recordings you add.
- `avatar_packs/<pack_id>/` holds prepared avatar packs and their `manifest.json`.
- `presets/` holds saved reusable setup presets.
- `runtime/quick_personas.json` holds the quick-persona cards; `runtime/quick_personas/` holds their portrait assets. Preserve both, along with referenced voice recordings in `voices/` or any other location you selected.
- `runtime/` and `MuseTalk/runtime/` hold generated state, caches, and saved sessions.

These folders are local user data, not disposable installation files. Preserve them when updating the app, and only use media you have the right to use.
