# Install NeuralCompanion

NeuralCompanion is a Windows desktop application built on Python 3.11 and a native Qt Quick/QML interface. The main runtime is required. MuseTalk, Ditto, and PocketTTS are optional isolated runtimes for local talking avatars and local speech.

Installation only puts components on disk. It does not choose a chat model, activate a speech provider, or select an avatar. Those are separate steps inside the application; see [First run](manual/first-run.md).

## Before you begin

- **Windows x64 and Python 3.11.** Select installed Python 3.11 for NC's main environment. LiquidAI TTS is included with the main runtime. If no usable Python 3.12 is found, the main installer automatically downloads a verified private copy for LiquidAI. It does not change NC's Python 3.11 environment, system Python, PATH or registry settings.
- **A chat provider for your first reply.** LM Studio or Ollama needs its server running and a model available. A hosted provider needs its own API credentials and available credit.
- **Disk space and time.** Main runtime installation includes LiquidAI's private environment and roughly 4.2 GB pinned model. MuseTalk models, Ditto models, and prepared avatar packs add further downloads.
- **An NVIDIA CUDA GPU for local talking avatars.** MuseTalk requires a CUDA setup. Ditto uses its own environment and a CUDA 12.8 stack for standard RTX and Blackwell cards. Neither is needed for text chat or ordinary speech.
- **Media tools if you plan to use media workflows.** Audio Story Mode and some media utilities need FFmpeg and ffprobe. The installer can place bundled tools under `tools/ffmpeg/bin` when they are missing from `PATH`.

Obtain the project from the [NeuralCompanion repository](https://github.com/Rakile/NeuralCompanion), or clone it:

```powershell
git clone --single-branch --branch main --no-tags https://github.com/Rakile/NeuralCompanion.git
cd NeuralCompanion
```

Choose a new folder for this installation. The clone command selects the current
`main` history without downloading legacy release tags. If you already have NC
installed from the earlier public history, follow [Updating NeuralCompanion](manual/updating.md)
instead of copying the new source over the old installation.

## Choose components

| Install target | What it adds | Notes |
| --- | --- | --- |
| **Main runtime** | The application, native QML interface, local speech stack including isolated LiquidAI TTS, MCP Core, and phone-pairing QR support | Required. Automatically provisions private Python 3.12 for LiquidAI when missing and downloads its pinned model. |
| **MuseTalk runtime** | Local MuseTalk talking-head engine | Separate environment, NVIDIA CUDA, model weights, and a prepared MuseTalk pack. |
| **Ditto runtime** | Local Ditto talking-head engine | Separate environment, models, and prepared Ditto packages. Ditto packages are not MuseTalk packs. |
| **PocketTTS runtime** | Local PocketTTS and PocketTTS Multilingual speech | Separate environment. Reference cloning may need Hugging Face terms and a login. |
| **Default avatar packs** | The prepared Echo and Eon MuseTalk packs | Downloaded separately from the runtimes. They are not Ditto packages and do not install MuseTalk for you. |

PocketTTS uses the verified local wheel shipped under `vendor/pockettts/` rather
than a moving GitHub download. Its source, version, license and checksum are
recorded there. Normal dependency installation and model access remain separate;
this does not make the full installation offline. A damaged/missing wheel bundle
stops before PocketTTS environment changes and must be restored from the same NC
release. An existing package with the same version is refreshed from the bundled
wheel without forcing its dependencies to reinstall.

The main runtime includes Chatterbox and Whisper-based local speech plus LiquidAI TTS. LiquidAI uses the same addon-owned setup pipeline as its in-app **Setup → Install / Repair** action, keeping its Python 3.12 environment at `.venvs/liquidai_tts` and pinned model at `models/LFM3-Audio-2B`. An existing ready installation is reused; missing dependencies or model files are prepared by the main installer. If Python 3.12 is unavailable, the Windows x64 main installer downloads a pinned standalone interpreter into `.venvs/liquidai_python312`, verifies its size, SHA-256 and runtime imports, and uses it only for LiquidAI. Keep this private base interpreter alongside the LiquidAI environment. Unknown folder contents are preserved instead of overwritten. Setup failures stop installation instead of reporting success. The Setup tab still provides **Check setup**, **Install / Repair**, and **Cancel setup**, and can reuse the private interpreter afterward. Installing LiquidAI does not make it the active voice provider. Add the optional MuseTalk, Ditto and PocketTTS runtimes only when needed.

The main installer includes the tested `mcp==1.26.0` SDK through
`addons/mcp_core/requirements.txt`, JSON Schema validation, chess rules, and
`qrcode[pil]==8.2` for phone pairing. It validates those imports before reporting
the main runtime ready. MCP connections, credentials, addon permissions and
Persona tool assignments still require setup inside NC; installation grants no
tool access.

Run the installer from the folder containing the intended NC release or updated
branch. It installs dependencies for that source folder; it does not pull Git
updates or replace application code. Preserve existing sessions, addon settings,
personas, models and voices when updating the source.

The main installer does not download or install Stockfish. Companion Chess uses
the basic engine for new setups. In **Companion Chess → Setup → Engine**, choose
**Install Stockfish…** on Windows to download and verify official Stockfish 19
into a `Stockfish` subfolder of a folder you choose, or **Select existing engine…**
to use an executable you already have. The optional download retains upstream
license and source files and requires no separate Python environment.

Saved custom paths and legacy bundled selections are preserved. Clear the engine
path to use the basic engine. Start a new game after changing engines. For repair,
choose **Install Stockfish…** and the same parent folder; verified files are reused
and damaged NC-owned installations are repaired. See the [Companion Chess guide](addons/companion_chess.md).

## Recommended: graphical installer

From the project folder, open `INSTALL_NEURAL_COMPANION.bat`. From a terminal, the equivalent is:

```powershell
py -3.11 install_neural_companion_gui.py
```

1. **Check the Python card.** It shows the detected Python 3.11 interpreter. Use **Detect** or **Browse** if needed. **Get Python 3.11** opens the Windows download page. Correct the interpreter before installing anything.
2. **Review Install targets.** The current installer preselects the main runtime, MuseTalk, PocketTTS, Echo, and Eon, with Ditto off. Accept or change those choices deliberately; the presets are a starting point, not a recommendation for every computer.
3. **Choose Default avatar packs separately.** Echo and Eon are prepared MuseTalk packs. Installing an avatar engine and installing prepared packs are different operations.
4. **Run preflight.** Choose **RUN PREFLIGHT ONLY** and read every warning before installing. It can distinguish a missing component from a service that is merely offline.
5. **Install.** Choose **INSTALL SELECTED** and wait for each selected component. If one component fails, keep the final summary and repair that component before reinstalling everything.
6. **Handle the expected follow-ups.** PocketTTS can offer a Hugging Face login after installation. For RTX 50 / Blackwell cards, check the PyTorch stack selection. The installer can auto-detect the GPU, keep the default CUDA stack, or **Force CUDA 12.8 / RTX 50**.

The installer may offer FFmpeg tools, PocketTTS model-access links, and a final command summary. It does not start LM Studio, Ollama, VoiceStudio, VSeeFace, ComfyUI, or any hosted account.

## Command-line installation

Run commands from the project folder. A minimal main-runtime installation is:

```powershell
py -3.11 install_neural_companion.py --main --non-interactive
```

Install optional runtimes individually:

```powershell
py -3.11 install_neural_companion.py --musetalk --non-interactive
py -3.11 install_neural_companion.py --ditto --non-interactive
py -3.11 install_neural_companion.py --pockettts --non-interactive
```

`--all` installs the main app, MuseTalk, Ditto, and PocketTTS. It does **not** download the default avatar packs:

```powershell
py -3.11 install_neural_companion.py --all --non-interactive
py -3.11 install_neural_companion.py --avatar-packs --non-interactive
```

`--avatar-packs` selects both default packs. `--avatar-pack-echo` and `--avatar-pack-eon` select them individually. Combine `--all --avatar-packs` when you want the four runtimes and both packs. Install the MuseTalk runtime as well if you intend to use those packs.

If interpreter detection is wrong, provide Python 3.11 explicitly:

```powershell
py -3.11 install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe" --main --non-interactive
```

To inspect setup without installing components:

```powershell
py -3.11 install_neural_companion.py --doctor-only
```

For the main and/or MuseTalk RTX 50 path, add `--torch-stack cu128` to the install command when automatic selection misses the card:

```powershell
py -3.11 install_neural_companion.py --main --musetalk --torch-stack cu128 --non-interactive
```

Prefer the installer to combining every requirements file in one environment. `requirements.txt` is a small baseline, while `requirements.companion.txt` and the separate runtime requirements serve different environments.

## Launch and verify

Open `run_neural_companion.bat`. It uses the project's installed environment. In a Git checkout, the launcher may offer to update the project; read that prompt before accepting an update.

For a direct launch from the project folder:

```powershell
.\.venv\Scripts\python.exe qt_app.py
```

Opening the window does not load models. Follow [First run](manual/first-run.md) to configure an active language provider, choose **Text Only**, select **None** for both speech output and avatar, then use the header power control, **Initialize NC**. A successful text reply verifies the basic path before you add speech or animation.

The important distinction is:

- Installing the main runtime does not make a chat provider active.
- Opening a provider's settings does not activate it.
- Installing MuseTalk does not select a pack or make MuseTalk the active avatar.
- Installing a voice runtime does not assign a voice to a persona.

## Voices, avatars, and personal data

Voice references belong in `voices/`; prepared MuseTalk packs belong in `avatar_packs/<pack_id>/` and include a `manifest.json`. NC includes a limited, explicitly approved set of voice samples and persona assets. Most additional voice samples, model weights, prepared avatar packs, and generated outputs are not shipped in the source repository.

MuseTalk setup checks the size and SHA256 of its eight weights and five required JSON configurations against `musetalk-model-manifest.json`. The inventory pins the revisions already used by the existing runtime. Setup reads existing files to verify them, downloads only missing or invalid files into staging, and verifies every staged repair before replacing any destination. Download or verification failure preserves the existing files. Publication is atomic per file; a later filesystem error can leave some files repaired and others unchanged, and rerunning setup verifies and completes the remaining repairs.

See the [release asset policy](release_asset_policy.md) for bundled component guidance and the [avatar-pack guide](avatar_packs.md) for pack layout. Use assets you have permission to use.

Do not delete `voices/`, `avatar_packs/`, `runtime/`, or `MuseTalk/runtime/` as a general cleanup step. They can contain your recordings, packs, personas, and conversation state. Cleaning generated caches is different from deleting a pack or a saved chat.

## Next steps

- [First run](manual/first-run.md) for a text-only verification.
- [Chat and speech](manual/chat-and-tts.md) for speech output and microphone input.
- [PocketTTS](manual/pockettts.md) for its isolated runtime and cloning access.
- [Troubleshooting](troubleshooting.md) if a component is missing or initialization fails.
