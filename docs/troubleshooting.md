# Troubleshooting

This page is the technical reference for installation, environment, and runtime diagnostics. For a symptom-first walkthrough with the current UI controls, see the [manual troubleshooting guide](manual/troubleshooting.md).

Do not paste API keys, tokens, private chats, voice recordings, or personal documents into a public issue. Remove them from logs before sharing.

## Start with evidence

- **Conversation console.** Open **Conversation** and read the console for provider and runtime errors.
- **Session setup → Communication logging.** When enabled, it can write a local transcript and open its folder. It can record visible and hidden messages, prompts, and replies, so treat the log as private.
- **Performance information.** Use Performance Check and pipeline timing controls, together with provider readiness and the console. Open **Runtime → Runtime Session → Resources** to inspect reported resident resources and eligible idle cleanup. See [Resources](manual/resources.md) and [Performance](manual/performance.md).
- **Addon status.** Addon Manager and provider cards distinguish a missing component from a service that is installed but offline.
- **Installer output.** Keep the final summary when a component fails.

## Installation and environment

### Python 3.11

NeuralCompanion expects Python 3.11. The installer validates the selected interpreter and can rebuild an isolated environment that uses a different version.

```powershell
py -3.11 --version
py -3.11 install_neural_companion.py --doctor-only
```

If detection selects the wrong interpreter:

```powershell
py -3.11 install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe" --main --non-interactive
```

In the graphical installer, use **Detect**, **Browse**, or **Get Python 3.11**. A build failure mentioning `numpy` or `pkgutil.ImpImporter` is a strong sign that an older or unexpected interpreter was used.

### Isolated environments

The main app and the optional engines do not share one environment:

- main app: `.venv/`
- MuseTalk: `MuseTalk/.venv/`
- Ditto: `Ditto/.venv/`
- PocketTTS: `.venvs/pockettts/`

Do not copy packages between them or install every requirements file into the main environment. Use the installer target for the component that is missing. If you moved the project after installation, rerun preflight or the installer; environment launchers can contain absolute paths.

### Launching directly

`run_neural_companion.bat` uses the installed environment. The direct equivalent is:

```powershell
.\.venv\Scripts\python.exe qt_app.py
```

If the batch launcher offers a project update, review the prompt. An update can overwrite local changes if you accept it without reading.

### CUDA and PyTorch

MuseTalk needs an NVIDIA CUDA setup. Ditto uses its own environment with a CUDA 12.8 stack for standard RTX and Blackwell cards.

For RTX 50 / Blackwell cards, use the graphical **Force CUDA 12.8 / RTX 50** option, or:

```powershell
py -3.11 install_neural_companion.py --main --torch-stack cu128 --non-interactive
```

Apply the same CUDA choice to the MuseTalk target when needed. Do not assume the main app's PyTorch stack is the one an isolated engine uses.

### FFmpeg and ffprobe

Audio Story Mode and some media utilities need both tools. Check them from a terminal:

```powershell
ffmpeg -version
ffprobe -version
```

If they are missing, rerun the installer preflight or the relevant install target so bundled tools can be placed under `tools/ffmpeg/bin`.

## Language providers

### Viewing is not activating

In **Runtime → Runtime Session → LLM**, selecting a provider card only opens its settings. The active route is the provider with the **Active language provider** badge. Use **Make active** to switch normal chat.

### Local server problems

- LM Studio or Ollama must be running and serving a model, not merely installed.
- Check the base URL and port in the provider's **Model and connection** section.
- Choose **Refresh** after starting the server or loading a model.
- A downloaded model that is not loaded in the server can still produce an empty model list.

### Hosted provider problems

- Check the API key, selected model, account access, and available credit.
- A separate chat-app subscription does not configure API access.
- A model that does not accept images will fail on an attached image; use **Vision-capable models only** and test a simple image.

### Persona overrides

A saved persona can override the language provider and model. If the connection or model is unavailable, the request reports an error rather than falling back. Configure the connection in Runtime and confirm the override was saved. See [Personas](manual/personas.md).

## Speech output and input

### Activation controls

- Speech output: **Text-to-speech → Use for voice output**.
- Speech input: **Speech-to-text → Use for speech input**.
- The active card shows **Active provider**.

Opening a provider's settings does not activate it. **None** disables speech output. For speech input, the No STT provider is labeled **None**; a fallback off choice appears as **Disabled** when that addon is unavailable.

### No audible speech

1. Confirm a speech-output provider other than **None** is active.
2. Check the header **Audio** output device and level.
3. Check the provider's readiness, isolated runtime, model download, and first-load state.
4. Check the voice reference on **Persona → Voice**. A preview does not assign it.
5. Check playback state. A paused response or **Skip speech** can explain silence.
6. Read the provider error in the console.

For a local backend, the first reply after startup can be much slower while models load. Test a second short reply before changing generation settings.

### Microphone input

1. **Session setup** must use **Voice Activation**, **Push-to-Talk**, or **Always On**. **Text Only** disables microphone transcription.
2. The speech-to-text provider must be active, not merely viewed.
3. Select the input device in the header **Audio** menu and confirm live levels.
4. For Push-to-Talk, the default binding is **Right Ctrl**; check **Addons → Hotkeys**.
5. Check Windows microphone privacy and device exclusivity.
6. The first Whisper use may download or load a model.

Input and output providers are independent. Changing the speaking voice does not repair microphone transcription.

### PocketTTS cloning

PocketTTS cloning may need model-term acceptance and a Hugging Face login in its isolated environment:

```powershell
.\.venvs\pockettts\Scripts\hf.exe auth login
```

A login does not prove that gated model terms were accepted. Keep tokens private. If the CLI is missing:

```powershell
.\.venvs\pockettts\Scripts\python.exe -m pip install --upgrade "huggingface_hub[cli]"
```

This repairs the isolated environment only. It is not a general upgrade instruction. See [PocketTTS](manual/pockettts.md).

## Avatars

### Engine, pack, and active route are separate

- MuseTalk needs the MuseTalk runtime, model weights, and a prepared MuseTalk pack.
- Ditto needs its own runtime, models, and a prepared Ditto package.
- Scenic needs a compatible image pack.
- VSeeFace needs an external application and a configured VMC receiver.
- **None** is audio-only and does not render an animated avatar.

Installing an engine does not select a pack. Preparing a pack does not activate the route. In **Runtime → Runtime Session → Avatar**, choose the provider, select the prepared asset, and use **Use this avatar**.

### Packs are not discovered

Packs belong under:

```text
avatar_packs/<pack_id>/
```

The `manifest.json` must be directly in the pack folder. Confirm that the pack matches the engine; a MuseTalk pack is not a Ditto package. Use **Refresh avatar packs** after adding assets. Older setups with packs inside MuseTalk result folders should move or copy each complete pack folder into `avatar_packs/`.

### Slow startup or high VRAM

- Use an NVIDIA CUDA GPU for MuseTalk and check the isolated runtime readiness.
- RTX 50 / Blackwell cards need the CUDA 12.8 stack when auto-detection misses them.
- Terminate chat before creator work or heavy configuration changes.
- Let an active creator job finish, and use the visible retry-cleanup action if cleanup is incomplete.
- Check available performance information and stop other model-heavy applications.
- Startup frame caches improve later loads but consume disk space. **Clear cache** removes acceleration data, not loaded models.

## GPU memory does not drop

Terminate the conversation runtime from the UI first. If cleanup is incomplete, use the available retry action. Stop creator previews and finish creator jobs.

External applications keep their own memory. Close LM Studio, Ollama, VoiceStudio, VSeeFace, ComfyUI, or another model server separately if it is holding the GPU. NC's unload/cleanup controls cannot release a resource that is still in use or owned by another process. A development build's **Free unused resources** action has the same ownership limit.

## Addons and workspaces

- Check the addon's enabled state in the Addons manager.
- Changes marked **after restart** need an application restart.
- Use **Unhide addon** if the icon is hidden.
- Restore a hidden view from the NeuralCompanion logo/name menu.
- Enable the addon and then configure its provider; enabling does not activate a provider.
- Some addons need external services or credentials before they can do useful work.

## Conversation memory and Document Memory

### Conversation memory

- A named saved or loaded conversation is required before the summary and archive controls become active.
- The summary **On** switch and **Use the summary in replies** are separate.
- **Automatically store older messages** and **Allow NC to search stored messages** are separate.
- A pending archive batch can make saved and indexed counts differ. **Retry indexing** appears when completed work needs attention.
- The memory-search model is independent of the chat model. Check its server, model, and confirmation state separately.

### Document Memory

- **Use Document Memory in chat** must be on for the selected package to contribute.
- **Enabled** controls what can be recalled; **Indexed** reports whether the saved snapshot has a compatible index.
- Indexing waits for idle time. A package can be selected before its index is ready.
- Switching packages uses saved snapshots. **Refresh from sources** rereads originals; **Rebuild saved embeddings** uses snapshots.
- **Test search** shows what the package retrieves before chat recall is enabled.
- PDFs need extractable text. NC does not perform OCR or request passwords; preprocess image-only scans and use a copy that opens without a password.
- A persona Document Memory override can disable recall or select a different package. When recall is enabled, an unavailable package contributes no excerpts.

See [Memory](manual/memory.md) for the full control flow.

## Main chat and Local Room

Main chat and Local Room cannot run simultaneously, including in Text Only mode.
Stop the active workflow before starting the other. Resolve the main chat's
**Save**, **Don't Save**, or **Cancel** prompt deliberately. Local Room keeps its
own history and saves continuation on **Stop room**; that does not save a main
chat file. See [Local Room](addons/local_room.md).

### Discord accounts, voice, and room replies

- A verified bot token does not prove that the bot is a member of the server or can access the voice channel. Check the invite, **View Channel**, and **Connect** permissions when Discord reports Missing Access.
- In **Bot accounts**, **Check all accounts** refreshes account verification; it does not join voice. Account assignment happens on Persona cards in the room.
- Discord controls who joins. NC's incoming-voice filter controls which received speech is accepted for transcription/routing. **Listed users** with an empty ID list accepts everyone.
- Check room speaker locks, participant mute, and protected-speech settings separately if received speech is not routed as expected.
- A complete reply can appear before its audio is ready. Highlighting tracks playback; context and participant memory track delivered speech.

See [Discord room setup and troubleshooting](addons/discord_voice.md) for the current workflow.

## Files that appear during use

Generated files under these folders are expected and ignored by Git:

```text
runtime/
MuseTalk/runtime/
MuseTalk/results/
avatar_packs/
voices/
```

They can include saved chats, memory, imported documents, recordings, packs, caches, and rendered output. Do not delete the whole folder to clean a cache. Back up personal data and target one cache or artifact deliberately.

## When to reset versus repair

Try these in order:

1. Read the provider or addon error and the Conversation console.
2. Test a text-only session with **None** speech and **None** avatar.
3. Run the installer preflight.
4. Repair only the failing component.
5. Restart NC after an addon or environment change.
6. Back up personal data before any broader reset.

Reinstalling every component is slow, can overwrite local changes, and often does not address an inactive provider, a stopped server, or a missing model. Preserve `voices/`, `avatar_packs/`, and runtime data unless you have a specific reason and a backup.

## VSeeFace speech lip sync

For the complete setup, Echo test avatar, body presets and persona mood tags,
start with the [VSeeFace provider guide](addons/vseeface.md).

Use the VSeeFace addon's **Speech lip sync** section with the normal NC launcher:

1. Download/extract VSeeFace from https://www.vseeface.icu/ (c5 is recommended; inspected c4 also works).
2. Choose the folder containing `VSeeFace.exe`, then **Check setup / refresh status**.
3. Close VSeeFace before approving **Install bridge** or **Update / repair bridge**. The confirmation
   names the destination and loader/DLL. A recognized existing installation can instead be adopted
   with **Use installed bridge**, without copying files when no update is needed.
4. Use **Overview → Start VSeeFace**, or open VSeeFace yourself, and apply the settings below.
5. Initialize the chat after enabling setup or changing its folder. A normal NC launcher works;
   the old prototype environment variable is not needed and cannot override a disabled setting.

In **VSeeFace → General settings → VMC protocol**, use this checklist:

| Option | Required setting |
| --- | --- |
| VMC receiver (disables tracking) | **On**, port **39539** |
| Apply VSeeFace tracking | **On** |
| Track face features | **On** |
| Track blendshapes | **On** |
| Send data with VMC protocol | **Off** |
| Apply expressions | **Off** |
| Track eye bones | **Off** |
| Track jaw bone | **Off** |
| Track head and neck | **Off** |

Start with **Blendshape smoothing** and **Bone smoothing** at minimum. Also enable **Audio lip sync**
in VSeeFace's General settings. NC supplies the body, head, eye movement and emotional expressions;
VSeeFace adds speech lip sync. These options must be set inside VSeeFace; NC does not change them automatically.

**Last checked status** is refreshed with the check button. Installed does not mean running/ready;
a current bridge heartbeat must match the selected VSeeFace process and installation. A legacy
bridge can need an update for heartbeat status. If NC was moved, approve Repair to update the
shared directory. Do not manually guess an AppData path.

Disabling speech lip sync stops its current analysis immediately while audible NC speech continues.
Removal requires VSeeFace to be closed and preserves changed/unknown files, settings, avatars and
other plugins. If NC reports a conflicting loader or changed owned files, it will not overwrite
those files; inspect them or use a clean extracted VSeeFace copy. Recovery copies are kept under
`runtime/vseeface_bridge_backups/` for changed owned files.

**Open bridge source** and **Self-build instructions** expose the included C# sources and offline
`Build-Bridge.ps1`. Compile against your own supported VSeeFace folder; no game assemblies are
bundled. The build regenerates the DLL/source inventory, and its installation still requires approval.
