# Chatterbox TTS addon

For current setup and provider activation, see [Chat and speech](../../docs/manual/chat-and-tts.md). Enable the addon in Addon Manager if it is unavailable, then select and activate it in **Runtime → Runtime Session**.

Built-in Chatterbox TTS exposed as an addon-backed runtime and settings tab.

This provider runs **English Chatterbox Turbo** (`ChatterboxTurboTTS`), not the
original English `ChatterboxTTS` implementation. The provider ID and saved keys
remain `chatterbox` / `tts_*` for compatibility.

## Supported controls

| Control | Backend parameter / behavior |
| --- | --- |
| Temperature | `temperature` |
| Top P | `top_p`; valid zero values are preserved |
| Top K | `top_k`; `0` disables this filter |
| Repetition penalty | `repetition_penalty`; must be positive, `1` is neutral |
| Normalize loudness | `norm_loudness`; normalizes the voice-reference recording |
| Use cloned voice | Selects reference conditioning through `audio_prompt_path` |
| Seed | Applied independently by NC's Turbo worker; `0` keeps randomized generation |
| Apply audio watermark | NC's watermark wrapper |
| Prewarm on runtime start | NC's existing readiness operation |

Turbo accepts Min P, CFG weight and exaggeration arguments in its Python
signature but explicitly ignores them. NC does not offer those controls or send
them to Turbo. The old `tts_min_p` saved key remains readable without activating
the setting. Multilingual has its own supported controls and settings.

Normal replies use their captured parameters. Voice auditions and direct service
requests without explicit overrides use this provider's configured sampling
values. Existing saved values and NC defaults are preserved.

Official references: [Chatterbox manual](https://github.com/resemble-ai/chatterbox/blob/master/README.md)
and [Turbo implementation](https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/tts_turbo.py).
