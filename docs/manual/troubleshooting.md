# Troubleshooting

Start with one text reply and no speech or avatar. That separates an installation problem from a provider, activation, or device problem. Most issues do not require reinstalling everything.

For the technical reference, including commands, environment paths, and installer details, see [Troubleshooting](../troubleshooting.md).

## First checks

| Symptom | Check first |
| --- | --- |
| App will not launch | Python 3.11, the project `.venv`, and the launcher; rerun the installer preflight if unsure. |
| No text reply | **Active language provider**, **Test connection**, the selected model, and the Conversation console. |
| Text works but no sound | The active speech-output provider, output device, playback state, and provider readiness. |
| Microphone ignored | **Session setup** mode, the active speech-to-text provider, input device, and Push-to-Talk binding. |
| Avatar missing or still | The active avatar route, the selected prepared pack/package, and working speech. |
| Addon or workspace missing | Addon Manager enabled state, **Unhide addon**, and whether a restart is required. |
| Memory controls disabled | A saved or loaded named conversation. |
| Documents ignored | **Use Document Memory in chat**, the selected package, and index readiness. |

## The app will not launch

- Confirm Python **3.11** is installed. The installer checks this version; Python 3.12 is not a substitute.
- Launch from the project folder with `run_neural_companion.bat`, or run:

```powershell
.\.venv\Scripts\python.exe qt_app.py
```

- If the launcher offers an update, read the prompt before accepting it. Do not let an update overwrite local changes without reviewing them.
- If installation or the environment is incomplete, rerun the installer preflight. If you moved the project after installing, rerun preflight or the installer so the isolated environments resolve from the new location.
- For the installer itself, see [The installer uses the wrong Python](#the-installer-uses-the-wrong-python).

## No text reply

1. Open **Runtime → Runtime Session → LLM**.
2. Select the provider you intend to use and check that **Active language provider** is shown for it. If it is only **Viewing settings**, choose **Make active**.
3. Choose **Test connection** and read the result. It probes the provider’s model catalog. A successful catalog check still needs a short chat reply to verify generation with the selected model.
4. For LM Studio or Ollama, confirm the server is running, the base URL is correct, and a chat model is available. Choose **Refresh** and select the model. A downloaded model is not a running server.
5. For OpenAI, xAI / Grok, DeepSeek, or Claude, check the API credentials, model name, account access, and available credit.
6. Open **Conversation** and read the console for the request error. A provider error is more useful than a generic "no reply" symptom.

If a persona is active, check **Persona → Overrides**. A persona can select a different language model for its requests. If that connection or model is unavailable, the request reports an error; it does not silently use the global default.

**Text Only** disables microphone input, not language replies. A speech-to-text provider is not required for typed chat.

## Text works but there is no speech

1. Open **Runtime → Runtime Session → Text-to-speech**.
2. Select a provider, configure it, and choose **Use for voice output**. Confirm the **Active provider** marker. Merely viewing the provider does not activate it.
3. Check that the provider is not **None**. **None** is the silent text-only choice.
4. Open the header **Audio** menu and select the correct output device. Check the level while speech should be playing.
5. Read the provider's readiness message. A local provider may still need its runtime, a model download, or a first-time model load.
6. For a reference voice, check the assignment in **Persona → Voice** and whether the recording is valid for that provider. A preview does not assign the voice.
7. Check whether playback is paused, whether **Skip speech** was used, and whether a response action left the queue waiting.

If speech starts late, that is usually a model/startup or chunking issue, not a missing output device. See [Speech starts late or sounds choppy](#speech-starts-late-or-sounds-choppy).

For PocketTTS, see [PocketTTS](pockettts.md) and the Hugging Face login section below.

## The microphone is ignored

1. Open **Runtime → Runtime Session → Session setup**. Choose **Voice Activation**, **Push-to-Talk**, or **Always On**. **Text Only** intentionally disables microphone transcription.
2. Open **Speech-to-text**, select **Whisper English STT** or **Whisper Multilingual STT**, and choose **Use for speech input**. A provider that is only being viewed is not active.
3. Open the header **Audio** menu and select the input device. Speak and watch the live input level.
4. For Push-to-Talk, check the binding in **Addons → Hotkeys**. The default is **Right Ctrl**. Hold the binding while speaking.
5. Check Windows microphone privacy settings and whether another application has exclusive use of the device.
6. Select **None** (or **Disabled** when the No STT addon is unavailable) under speech-to-text when you deliberately want no transcription. This is different from choosing **Text Only**, which also changes the conversation input mode.

Speech-to-text and speech output are independent. Fixing the voice that reads replies does not fix microphone input.

## Speech starts late or sounds choppy

- Test a short plain sentence with the provider's defaults before changing advanced generation controls.
- Open **Addons → Speech Timing**. Change either the standard chunk sizes or the streaming settings, not several controls at once.
- Smaller chunks can start sooner; larger chunks can sound more continuous. The first and later flush deadlines bound how long NC waits for a better boundary.
- For MuseTalk, the first two quickstart chunks smooth the handoff after speech begins. Test with the actual avatar route you use.
- A cold model load can make the first reply much slower. Compare later replies before concluding the configuration is bad.
- For a reference voice, try a clean, short recording. Unusual source audio can affect the result regardless of timing settings.
- Hosted providers add network and service latency. Check their status separately from local timing.

Use [Performance Check](performance.md) if you need measurements rather than a listening comparison.

## Avatar is missing, still, or slow

1. Open **Runtime → Runtime Session → Avatar**. Select the intended route and choose **Use this avatar**.
2. Confirm the selected route is not **None**.
3. For MuseTalk, choose **Refresh avatar packs**, select an **Avatar pack**, and check the base avatar. MuseTalk needs the isolated MuseTalk runtime, models, and a prepared MuseTalk pack.
4. For Ditto, check **Avatar package** and **Fixed avatar**. Ditto needs its own runtime and a prepared Ditto package; a MuseTalk pack is not a Ditto package.
5. Open **Avatar Preview** after a short spoken reply. The face should move with the audio. A stopped session or a route without local rendered frames may show a still image or no live output.
6. Stop the chat runtime before preparing or changing heavy avatar assets. An active creator job or incomplete cleanup can block initialization.
7. If initialization is slow, let the first pack/model load finish. Startup caches can reduce later loads but use disk space.

Do not assume that installing the avatar engine selected a pack, or that preparing a pack activated the avatar. Engine, pack, and active route are three separate states. See [Avatars](avatars.md).

## GPU memory stays high

- Terminate the NC runtime first and let cleanup finish. If the header reports incomplete cleanup, use the available retry action before initializing again.
- Stop creator previews and finish or cancel creator jobs.
- Close external applications that keep their own models loaded. LM Studio, Ollama, VoiceStudio, VSeeFace, and ComfyUI are separate processes.
- Inspect RAM and GPU memory in Windows Task Manager and **Runtime → Runtime Session → Resources**. The page's unload actions release only eligible idle resources. On an older installation without this page, inspect the external model server and Task Manager directly.
- Restarting NC is not a substitute for stopping an external server that still holds GPU memory.

## An addon or workspace is missing

- Open the **Addons** manager in the Addons workspace and check whether the addon is enabled.
- If the change is marked **after restart**, restart the application.
- Search the Addons rail, and use **Unhide addon** for a hidden icon.
- Restore a hidden view from the NeuralCompanion logo/name menu.
- Installing an addon, enabling it, configuring it, and activating its provider are separate steps.

## Memory controls are disabled or recall does not work

- Save or load a named conversation. Conversation memory is inactive for an unsaved chat.
- For a summary, check the **Conversation summary** switch and **Use the summary in replies** separately.
- For older messages, check **Automatically store older messages** and **Allow NC to search stored messages** separately.
- Check **Memory search** for the selected embedding model and any **Retry indexing** status. A pending batch can make saved and indexed counts differ.
- For Document Memory, check **Use Document Memory in chat**, the selected package, **Enabled** sources, index readiness, and **Test search**.
- If an original document changed but the reply did not, use **Refresh from sources**. Switching packages uses saved snapshots.
- Check any persona **Document Memory override**. An unavailable package contributes no excerpts.

See [Memory](memory.md) for the full model.

## A persona override fails

- Configure the connection and model in **Runtime → Runtime Session → LLM** first. **Overrides** uses existing configured connections.
- An unavailable override connection or model reports an error when requested; it does not fall back to another model.
- For Document Memory, select an available package. When recall is enabled, a package that is unavailable or not ready produces a warning and no excerpts, but the conversation continues.
- Confirm **Save overrides** was chosen. An edited draft is not active.
- Persona changes follow that persona's new requests and do not change other personas or combine chat histories.

## The installer uses the wrong Python

NeuralCompanion expects Python 3.11. Pass the interpreter explicitly:

```powershell
py -3.11 install_neural_companion.py --python-exe "C:\Path\To\Python311\python.exe" --main --non-interactive
```

Use the graphical installer's **Detect**, **Browse**, or **Get Python 3.11** controls if you prefer not to type a path. For a repair, run **RUN PREFLIGHT ONLY** first and select only the component that needs attention.

## MuseTalk is slow or uses too much VRAM

- Confirm the isolated MuseTalk runtime is installed and its readiness check passes.
- Check the installer’s CUDA readiness result. It selects the CUDA 12.8 PyTorch stack for detected RTX 50 / Blackwell cards; **Force CUDA 12.8 / RTX 50** or `--torch-stack cu128` provides an override when detection misses the card.
- Start with shorter packs and one avatar before enabling optional emotion variants.
- Inspect GPU memory in Windows Task Manager and stop other heavy work before loading another stack.
- Use **Performance Check** and compare its applied recommendation on your hardware.
- Startup caches improve later starts but consume disk space. **Clear cache** removes acceleration data; it is not a general GPU unload.

## FFmpeg or ffprobe is missing

Audio Story Mode and some media utilities need both `ffmpeg` and `ffprobe`. Rerun the installer preflight or the relevant install target so it can place bundled tools under `tools/ffmpeg/bin` when they are not on `PATH`.

## PocketTTS cloning is not ready

Accept the PocketTTS model terms and authenticate inside the isolated environment:

```powershell
.\.venvs\pockettts\Scripts\hf.exe auth login
```

A successful account login does not prove that gated model terms were accepted. If the CLI is missing, repair it in that environment only:

```powershell
.\.venvs\pockettts\Scripts\python.exe -m pip install --upgrade "huggingface_hub[cli]"
```

Keep tokens private. Enter them through the login command, not through chat, a persona prompt, or a saved preset. See [PocketTTS](pockettts.md).

## Main chat and Local Room conflict

Main chat and Local Room share runtime resources and cannot run at the same time. Stop one before starting the other. If NC asks about unsaved changes, choose **Save**, **Don't Save**, or **Cancel** deliberately. Stopping a room is different from saving its transcript.

## A saved chat did not update

**Save** writes the current transcript to the named file. Editing, deleting, or regenerating messages does not automatically update it. Save again after changes.

If a load or replacement prompts about unsaved changes, choose **Save** to keep them. Do not delete `runtime/` to resolve a save prompt; it can contain saved chats, memory, and generated state.

## What to include in a bug report

- The exact action and the visible error or status text.
- The active language, speech, and avatar providers.
- Whether the problem happens with **Text Only**, **None** speech, and **None** avatar.
- Relevant installer or console output with API keys, tokens, and personal content removed.
- The result of **Test connection** or the provider readiness check, when applicable.

Do not post credentials, voice recordings, private chats, or personal documents in a public issue.
