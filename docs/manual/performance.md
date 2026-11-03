# Performance

Performance depends on the stack you selected, not on the application alone. A chat model, speech provider, avatar engine, and vision source can each change startup time, reply latency, and memory use. Measure the configuration you actually run before changing settings.

Start with the two tuning workspaces:

| Workspace | Question it answers |
| --- | --- |
| **Addons → Performance Check** | How does the configured stack behave across bounded reply samples, and what settings does it recommend? |
| **Addons → Speech Timing** | How is response text split for speech and avatar playback? |

## Before measuring

- Get a short text reply working first. Add speech, then an avatar, so you can attribute a change to one component.
- Save the conversation you care about. A performance run can apply temporary configuration changes.
- Confirm the active providers on **Runtime → Runtime Session**. Viewing a provider is not the same as activating it.
- Leave other model work, creator jobs, and heavy applications idle during a run.
- Expect the first model load to be slower than later replies. Do not judge steady-state performance from a cold start alone.

## Check memory use and stop idle models

Use Windows Task Manager to inspect RAM and GPU memory while reproducing the
slowdown. Compare the same short prompt with speech and avatar providers set to
**None**, then add each component back. Record the active providers and whether
the model was already loaded.

Stop the NC runtime and wait for cleanup before starting heavy creator work.
Stop creator previews and use their **Unload models** or **Unload MuseTalk**
actions when finished. A model server such as LM Studio, Ollama, or ComfyUI can
retain its own models after NC stops; inspect that application's loaded models
separately.

Open **Runtime → Runtime Session → Resources** for **Memory overview** and
**Loaded resources**. Use **Refresh** for a new snapshot, expand a row to inspect
its owner and usage, and choose **Unload** for one eligible idle resource or
**Free unused resources** for eligible idle resources together. Active work is
protected. See [Resources: RAM, VRAM, and idle models](resources.md) for shared
memory measurements, automatic refresh, and cleanup behavior.

## Run Performance Check

Open **Addons → Performance Check**. The page uses the established bounded Dry Run workflow.

1. Configure and initialize the intended language, speech, and avatar stack. Confirm a normal short reply works before measuring it; a measurement of a stack you do not use is not useful guidance.
2. Set **Reply samples**. The current control allows 1–100; a small count is enough for a first comparison.
3. Decide whether to enable **Generate automatic sample replies**. With it off, you provide the messages during the run; with it on, NC generates the samples. Keep the sample count small either way.
4. Choose **Start check** and leave other heavy tasks idle. The status changes from **Ready** to **Running**.
5. Read the progress and any error. **Stop** ends the run and restores the saved test configuration; recommendations remain available for review.
6. Wait for **Complete**. Review the resulting normal reply timing and the run output before adopting the result. An interrupted run can have too few samples to be useful.
7. **Apply latest recommendation** becomes available after completion. Apply it, compare a normal reply with the same prompt, and keep it only if the result suits your priorities.

The Dry Run limits response length while measuring, so its replies are not a quality comparison. Use it for timing and resource behavior, then test a normal reply in Conversation.

## Load performance profiles

**Saved performance profiles** appears on the same page. Select a profile and choose **Load profile**. Profiles are loaded through the existing performance-profile validator and apply only its approved keys; a profile does not install a missing runtime or fix an unavailable provider.

A profile is a starting point, not a universal best setting. Hardware, model size, context length, speech backend, and avatar route all change the result.

## Tune speech timing

Open **Addons → Speech Timing**. The workspace shows live pipeline status and three groups of settings:

- **Standard** — target and maximum characters for normal, non-streaming speech chunks.
- **MuseTalk non-stream** — avatar-aware chunk sizes, including the first two quickstart segments that smooth the handoff after speech begins.
- **Streaming** — target and maximum streaming chunk sizes, first-chunk minimum, and the first and later force-flush deadlines.

The tradeoff is usually:

- **Smaller chunks** can start speech sooner but may sound less continuous and create more avatar transitions.
- **Larger chunks** can sound smoother but delay the first sound.
- **Shorter flush deadlines** can reduce waiting but may send unstable fragments.
- **Longer flush deadlines** can produce more natural boundaries at the cost of latency.

Change one control at a time and compare the same short prompt. Use **Reset defaults** when a change makes the result worse. Speech Timing is saved with the current session, not with a persona.

## Practical order of work

1. Establish a text reply with no speech or avatar.
2. Add speech and confirm timing and output on a short reply.
3. Add an avatar only after speech works, then test one short spoken reply.
4. Check RAM/GPU use and unload idle models before loading another heavy stack.
5. Run **Performance Check** with a small sample count.
6. Apply one recommendation or one timing change, then compare the same prompt.
7. Keep the settings that work for your hardware; use saved profiles when available.

## What performance cannot fix

- A missing or inactive provider is a setup problem, not a tuning problem.
- A hosted provider's latency includes the network and the provider's service.
- A local model server may keep models loaded outside NC.
- An avatar pack's first load can be slow while models and frames warm up; startup caches reduce later starts but use disk space.
- A larger conversation context increases prompt work regardless of speech settings.
- Streaming can overlap language, speech, and avatar work. If the computer becomes sluggish, compare with streaming off, then adjust model context or avatar load one setting at a time.

For avatar-specific tuning, see [Avatars](avatars.md), [MuseTalk](musetalk.md), and [Ditto](ditto.md). For memory indexing and embedding costs, see [Memory](memory.md).
