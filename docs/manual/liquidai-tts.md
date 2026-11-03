# LiquidAI text-to-speech

LiquidAI uses LFM3-Audio-2B to speak NC's reply text with a built-in female or male voice, or an installed voice LoRA adapter. Your selected language model still writes the reply. NC keeps its normal speech chunking, playback, Ditto/MuseTalk animation and lip-sync flow. Native audio-to-audio conversation in NC is deferred.

## Set up and select

1. Open **Runtime → Runtime Session → Text-to-speech → LiquidAI**.
2. The NC **Main runtime** installer includes LiquidAI's private environment and pinned model. On Windows x64 it also downloads a verified private **Python 3.12** into `.venvs/liquidai_python312` if no usable Python 3.12 is found. NC's main Python 3.11 environment, system Python, PATH and registry are unchanged. Keep this private base interpreter alongside `.venvs/liquidai_tts`. Open the **Setup** tab and use **Check setup** to confirm readiness. **Install / Repair** remains available for older installations or repairs and can reuse that interpreter. If no Python 3.12 is available, rerun the main installer or install Python 3.12 yourself before using in-app repair. Internet access is needed when files are missing, with space for the dedicated environment plus the roughly 4.2 GB checkpoint.
3. Wait for **LiquidAI runtime ready**. Progress appears in the setup status. **Cancel setup** stops this install; **Install / Repair** can reuse downloaded files. **Check setup** refreshes readiness on demand.
4. Select the speech language and **Female**, **Male** or a discovered voice adapter, then choose **Use for voice output**.
5. Stop and initialize the chat engine if needed, then send a short message. Use text in the selected speech language; this setting does not translate replies.

Opening settings does not download or load the model. **Prewarm when chat starts** loads it and performs a short discarded synthesis at engine initialization; otherwise the first speech request pays that startup cost. Warm-up uses the active Persona's saved LiquidAI voice and speech language, falling back to provider defaults for unset values. Settings are saved with NC's TTS session/preset settings and apply to subsequent speech chunks.

## Assign a voice to a persona

With LiquidAI selected for speech, **Addons → Persona → Voice** offers the same built-in and installed LoRA voices plus speech language. Choose **Apply to Persona** to save those choices with the selected persona, or **Use provider default** to inherit the session setting. Refresh the list after installing a voice. Each persona can have its own assignment without changing the provider defaults. See [Personas](personas.md#assign-a-voice).

## Install voice LoRA folders

Put each compatible LFM3 Audio LoRA folder directly in your running NC
installation's `models` folder. Keep `adapter_config.json` and
`adapter_model.safetensors` together:

```text
models/
  LFM3-Audio-2B/             (base model)
  Femdemon/
    adapter_config.json
    adapter_model.safetensors
    voice.json              (optional)
```

Open LiquidAI settings and select **Refresh voices**, then choose the voice.
Discovery also runs when the settings surface first checks setup. Adding a
folder does not require Python/config.py edits, model merging or downloading
another base model. Only compatible, complete top-level LoRA folders are listed;
unrelated models, nested checkpoints and malformed/incomplete packages are ignored.
Adapters must use standard LoRA without base-changing initializers, trained base
biases, full modules/token updates or layer replication, so switching can preserve
the original voices.

By default the folder name supplies the display and trained voice name. The
common `LFM3-Audio-2B-` prefix and `-LoRA`/`_LoRA` suffix are removed. A folder
named `Femdemon` uses `Perform TTS in American English using Femdemon's voice.`
when American English is selected. Use the adapter's trained language.

If you rename a folder or want a different display label, include optional
`voice.json` alongside the two adapter files:

```json
{"name": "Femdemon six epochs", "prompt_name": "Femdemon"}
```

`prompt_name` must match the voice name used during training. Adapter weights
do not contain that text instruction, so NC cannot infer it from arbitrary
checkpoint names. Packaging this metadata once lets other users drop the whole
folder into `models` without editing settings code. Keep it with the weights
when sharing or renaming the folder.

The models directory beside the selected base-model override is an additional
search location for existing installations. NC's own `models` directory takes
priority if both locations contain the same folder name, including when the
primary package is incomplete. Remove or rename a conflicting primary folder
before using a secondary package with that name. Old saved voice names
continue working when they identify one installed adapter unambiguously.
Saved missing voices remain visible and produce an error instead of silently
switching to a built-in voice; refresh and select an installed folder to fix it.

The private environment needs PEFT; **Install / Repair** installs it. Python
executable overrides must provide compatible dependencies themselves. Discovery
only reads small local config/metadata files; it does not load models or weights.
The worker loads the selected adapter lazily. Switching to Female/Male disables
it. Switching to another custom voice unloads the previous adapter without
merging it into the base model, keeping one custom adapter resident. Completed,
progressive and prewarm speech all use the same selection and prompt metadata.

## Generation settings

| Setting | Meaning |
| --- | --- |
| Seed | `0` randomizes each chunk. A fixed value makes variation more repeatable with the same text and setup; exact audio can vary across hardware. |
| Audio temperature | Lower values constrain variation. Start with `1.0`; high values may reduce clarity. |
| Audio top-k | Keeps the most likely audio choices. Default `128`; `0` disables the filter. |
| Audio repetition penalty | Discourages repeated audio patterns. Default `1.1`; `1.0` disables it. Large values may distort speech. |
| Generation budget | Maximum generation slots for one NC chunk. A slot can carry a text token or roughly 80 ms of audio. If the budget is exhausted, NC reports an error instead of accepting clipped speech. Increase it or reduce speech chunk size. |

Use **Speech Timing** for the text context sent to speech: enough words help pronunciation and phrasing. Flush deadlines determine when eligible text is sent, including while the language model pauses between tokens. They do not set how many seconds of audio must be generated before playback.

## Earlier local playback

**Experimental progressive audio** is off by default. Enable it in LiquidAI's provider settings to try lower latency with **No Avatar**, **Scenic**, **Ditto** or **MuseTalk** and local desktop speakers. LiquidAI can then supply small pieces of mono 24 kHz audio while it generates the rest of the same text chunk. NC retains one logical speech chunk, its playback controls and approximate highlighting.

**Progressive startup audio (seconds)** measures seconds of sound ready to play, not a fixed extra delay. Start with `1.0 s`. Smaller values may start sooner but can cause gaps if generation falls behind playback. A successful short utterance can start as soon as it finishes, even below that buffer. Pause holds the device clock; interrupting or skipping an utterance cancels that request while keeping the loaded model ready for the next reply. An unresponsive or invalid worker is terminated for recovery. Highlighting follows that clock through gaps and pauses; it remains approximate rather than phoneme alignment.

With **Scenic**, audio uses the same progressive path as No Avatar. Still images change with the speech chunk’s emotion when playback starts; there is no animation-frame buffer to wait for. The LiquidAI startup-audio setting still controls how much sound is buffered before playback begins.

With **Ditto**, the same logical speech chunk feeds overlapping render windows through its existing continuous worker and RAM frame buffers. Playback advances only through audio whose matching frames are ready; if rendering falls behind, speech waits and the animation follows the held playback clock. The configured startup-audio duration also sets a minimum ready-animation lead. Ditto’s existing adaptive buffer policy can request more lead when delivery slows; its measured rate includes gaps between internal render windows. After an underrun, playback rebuilds that lead instead of restarting for each individual frame. Short final tails drain once their remaining frames are ready. Internal audio-window gaps do not restart partial motion inference: Ditto accumulates normal motion-model windows while more audio is expected, then flushes the final tail. RAM-pressure relief can explicitly flush pending motion so playback can release its frame storage. Speech Timing still controls the text chunks. Long fade-out settings need extra future audio before rendering can commit the tail, which can increase startup latency.

With **MuseTalk**, progressive playback uses its existing worker, configured FPS, PNG frame files and audio clock. Later render windows remain two seconds and retain phase-aligned audio context. Only matching completed frames admit audio, and the picture holds during buffering or pause. The selected avatar/emotion and source-video position remain bound to the logical speech chunk. Pose connections that need a complete chunk wait for audio EOF and use MuseTalk's established transition renderer. MuseTalk still requires GPU capacity alongside LiquidAI; this option does not reduce quality settings.

Other avatar engines and addon routes that need a file continue receiving complete audio through the established path. Their lip-sync behavior is unchanged by this option. With No Avatar, if the local device cannot open before any audio is submitted, NC can finish that request into a real WAV and use the existing playback path. Progressive Ditto and MuseTalk report a local-output error instead of falling back to playback that cannot enforce frame readiness. It does not replay a prefix after an error once audio has been submitted.

Phone/remote capture uses completed audio by default. An updated custom Android app can separately opt into **Settings → Voice & audio → Experimental progressive LiquidAI audio** for Backend HQ with No Avatar. The phone switch and this provider's progressive option must both be enabled; switching the phone option off restores completed-file delivery for future replies. This experimental phone route is audio-only, uses more network data, preserves a completed recording for Replay and does not add avatar streaming to the phone.

Phone-owned LiquidAI speech keeps each existing planned text segment intact instead of adding extra synthesis calls at commas and dashes. This preserves LiquidAI's punctuation and sentence flow, including privately prepared Continuous Mode speech. The normal chunk-size limits still apply. Very short streaming flush deadlines can still cut a sentence before it is complete; increase **Speech Timing → First flush** and **Later flush** if you prefer smoother phrases over the earliest possible start.

Leave the option off to use completed audio for every route. LiquidAI does not introduce another sentence splitter and does not support reference-voice cloning or Chatterbox speech tags.

### How the timing controls fit together

| Control | What it measures |
| --- | --- |
| **Speech Timing → Avatar streaming** | Text characters and flush deadlines. This decides when a text chunk is sent to TTS while LLM streaming is on. With LLM streaming off, the avatar non-stream settings apply instead. |
| **LiquidAI → Progressive startup audio** | The minimum duration of generated sound before progressive playback can start. This is a minimum, not a cap on audio preparation. |
| **MuseTalk → Progressive animation buffer** | The first render-window size and minimum matching animation lead at startup and after an underrun. Later render windows remain 2 seconds. |

For progressive MuseTalk playback, the larger audio/animation buffer requirement governs the synchronized lead, rounded to supported frame timing. Audio at 2 seconds and animation at 4 seconds generally requires 4 seconds of matching ready material, not a fixed 6-second delay. A finished short chunk or final tail can use less. The actual wait depends on synthesis and rendering speed. These controls apply per speech chunk; they do not replace Speech Timing's text context.

MuseTalk's **VRAM mode** also affects throughput. **Quality** uses larger batches and disables VAE slicing; it can prepare frames faster but needs more GPU memory. **Balanced** saves memory and can leave less throughput headroom when LiquidAI shares the GPU. Check available VRAM before choosing a profile; progressive audio does not change it automatically.

The two progressive buffer settings apply only when **Experimental progressive audio** is enabled. Disabling it uses completed audio through the normal avatar workflow.

The **Render** bar follows the contiguous rendered frames of each known speech chunk. **Playback** follows the audio clock and holds during buffering or pause. Percentages are estimates while text/audio is still arriving and can change as more chunks or the final duration become known. For the currently known chunks, rendering reaches 100% after their full audio and matching frames are ready; playback reaches 100% after their audio finishes. These bars cannot predict text the LLM has not produced yet.

### Progressive timing diagnostics

The existing `NC_TTS_TIMING=1` switch also enables progressive LiquidAI/MuseTalk timing lines in NC's system console. Enabling the temporary speech-performance capture does the same on the next NC restart. Output is limited to chunk/window boundaries and contains timings and counts rather than conversation text or audio.

- **LiquidAI rate** compares generated audio duration with generation wall time. Below `1.0x` cannot sustain uninterrupted speech indefinitely.
- **MuseTalk job** measures one render window, including its worker request and publication. **Input wait** is time waiting for enough incoming audio/context to submit that window.
- **Between windows** includes input waiting and other gaps; do not add it to input wait as a separate cost. The saved report's **render_including_gaps_fps** measures delivery across those gaps, while **render_delivery_fps** covers active render jobs only.

The bounded metadata file is `runtime/logs/speech_performance.jsonl`. Capture can be enabled or disabled with `python -m core.speech_performance enable` / `disable` from the running installation; restart NC afterward. The console flag can enable summaries without creating a capture file.

## Runtime and resources

The managed environment is `.venvs/liquidai_tts` under your running NC installation. The pinned checkpoint is `models/LFM3-Audio-2B`; private model caches and temporary worker files stay under `runtime`. Model libraries run in a separate process using the dedicated environment, so stopping the **chat engine** releases its process memory and CUDA allocations. Ordinary speech Skip/interruption keeps the healthy worker warm; the next chat can load it again after a full engine stop.

**Runtime → Resources** reports the worker and its children. **Unload** / **Free unused resources** can unload it while idle; active synthesis is protected. Unloading does not delete the environment or model.

Advanced Python/model overrides use existing compatible files. Blank values select the managed paths. **Install / Repair** updates only the managed copies and preserves external overrides. **Check setup** reports the managed installation; the worker validates any selected override when it starts. Stop active speech before repairing the runtime.

## Troubleshooting

- **Missing Python/model:** use Install / Repair, or correct the advanced override. Setup requires Python 3.12; NC's regular Python 3.11 environment is insufficient for this provider.
- **Incompatible/unverified checkpoint:** use the pinned model installed by setup, including its codec, custom code, original license and `PINNED_REVISION` marker.
- **CUDA unavailable:** select a working TTS device or use CPU. CPU is supported, but may be much slower.
- **Generation budget exhausted:** increase the budget or use smaller Speech Timing chunks.
- **Setup failed/cancelled:** read the setup status and retry Install / Repair. Other providers remain available.

Model: [LiquidAI/LFM3-Audio-2B](https://huggingface.co/LiquidAI/LFM3-Audio-2B), pinned to revision `cddb56b5ec9b4703f9b3b2d0500143d1fff2fee0`. The download retains the model's original `LICENSE`; review it before redistribution or deployment.

## Temporary speech performance capture

For a diagnostic run, use the NC environment from your installation folder:

```powershell
.venv/Scripts/python.exe -B -m core.speech_performance enable
```

Fully restart NC, keep your normal MuseTalk + LiquidAI setup, and try a few replies. A metadata-only capture is written to `runtime/logs/speech_performance.jsonl`; one rotated file is retained. It records queue/admission waits, first PCM, ready-audio buffering, actual playback starts, pauses/underruns, and MuseTalk render-window wall times. Conversation text, audio and credentials are excluded. The existing bounded background writer handles disk I/O, and instrumentation never synchronizes the GPU or changes scheduling.

After a run:

```powershell
.venv/Scripts/python.exe -B -m core.speech_performance report
.venv/Scripts/python.exe -B -m core.speech_performance disable
```

Restart NC again to disable capture. The enable marker is read once per process, without a polling loop. Reports separate observed buffering from user pauses and show audio production rate and render delivery FPS. These measurements identify waiting and throughput limits; they do not prove the GPU has reached its absolute maximum. Missing/rotated/dropped events or interrupted chunks limit the available measurements. Default operation remains uninstrumented unless capture is explicitly enabled.

## Adjust MuseTalk startup buffering

In the **MuseTalk avatar provider → Performance**, use **Progressive animation buffer (seconds)**. The default is **2.0 seconds**, with a range of **0.5–4.0 seconds**. Try **1.0**, then **0.5** to compare startup delay and speech continuity; **2.0** restores the previous policy.

This sets the first render segment of each progressive speech chunk and the minimum ready-animation lead before startup or recovery from a buffer underrun. Later render segments stay two seconds. Lower values can start sooner, but may increase pauses or render overhead. Playback still waits for matching animation frames, preserving lip-sync.

Changes are saved with the MuseTalk runtime settings and apply when a **new speech chunk** starts preparing. Existing prepared or playing chunks keep their previous value. Values round upward to supported model feature steps (**0.5 seconds at 24 FPS**); LiquidAI's own startup-audio buffer remains a minimum and may require additional lead. Pose transitions that require a complete audio chunk still wait for its generation to finish. This setting affects progressive local audio only.
