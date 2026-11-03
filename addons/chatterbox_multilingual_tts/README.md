# Chatterbox Multilingual TTS

For current setup and provider activation, see [Chat and speech](../../docs/manual/chat-and-tts.md). Enable the addon in Addon Manager if it is unavailable, then select and activate it in **Runtime → Runtime Session**.

Separate local TTS backend for ResembleAI Chatterbox Multilingual.

This addon intentionally stays separate from the regular Chatterbox Turbo
backend so English/Turbo behavior remains unchanged.

The multilingual panel exposes the installed backend's language, temperature,
Top P, Min P, repetition penalty, exaggeration and CFG weight controls. CFG
weight can be set to zero for cross-language voice transfer. Valid zero values
are preserved when settings are saved and restored.

Seed belongs to this provider. A positive multilingual seed is applied before
its synthesis, warm-up and voice auditions; zero leaves its random sequence
running. It never falls back to regular Chatterbox's seed. Shared request
routing and worker seed notifications keep provider settings separate.

Top K and Normalize loudness are not exposed for this multilingual backend.
Older saved values remain readable for compatibility but are not used as
multilingual generation settings.

This provider loads `ChatterboxMultilingualTTS` from `mtl_tts.py`; it is not the
English Turbo implementation. Its controls are checked against the installed
package's supported parameters. The settings page does not install or upgrade
the package. Repair a missing runtime through NC's normal installation workflow.

Its factory **Default TTS voice tag rules** contain only:

```text
Do NOT use emojis when speaking!
```

Turbo's default vocal-sound instructions are not included. Explicitly saved
custom provider defaults and persona overrides retain their existing priority.

## Separate worker and CPU usage

Multilingual runs in its own Python process using NC's existing interpreter,
following the Chatterbox Turbo worker pattern. Opening its settings does not
start or load a model. Warmup or the first speech request starts the worker;
Stop/unload closes it and a later request can start a fresh worker. Resources
shows the worker process and includes its launcher/interpreter descendants.
Audio returns to NC as lossless float32 mono samples; NC still owns playback.

For CUDA generation, the worker receives `KMP_BLOCKTIME=0` and
`OMP_WAIT_POLICY=PASSIVE` before native libraries initialize. These settings let
CPU workers sleep between useful operations instead of spending excessive CPU
time waiting. Thread counts, model parameters, CUDA selection and CPU-only
defaults remain unchanged. The policy applies only to this worker, leaving the
NC process and other providers' environments unchanged. No special launcher or
manual environment settings are required for normal use.

The CUDA waiting policy was runtime-tested on Windows with PyTorch's Intel
OpenMP library. LLVM OpenMP supports the same block-time control; GNU OpenMP
documents passive waiting through `OMP_WAIT_POLICY`. Other runtime combinations
still need performance validation. See the [LLVM OpenMP runtime guide](https://openmp.llvm.org/design/Runtimes.html#kmp-blocktime)
and [GNU OpenMP waiting policy](https://gcc.gnu.org/onlinedocs/libgomp/OMP_005fWAIT_005fPOLICY.html).

Cancellation is checked between transformer operations, as in Turbo. If native
work cannot respond, the parent can terminate the owned worker and discard its
pending audio. A cancelled audition does not become a successful audio result;
if termination was necessary, subsequent speech starts a fresh worker.

## Runtime status and errors

Normal model-ready and warmup status, missing-voice warnings and errors remain
available in NC's System console. The temporary per-chunk timing/profiler output
and speech-text debug summaries have been removed. The old `NC_TTS_TIMING` and
`NC_TTS_PROFILE_CUDA` experiment flags no longer enable Multilingual profiling.
Existing diagnostic files are left in place; ordinary speech creates no new
Multilingual timing or CUDA trace files.

Official references: [Chatterbox manual](https://github.com/resemble-ai/chatterbox/blob/master/README.md)
and [Multilingual implementation](https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/mtl_tts.py).
