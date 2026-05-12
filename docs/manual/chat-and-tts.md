# Chat And TTS

Neural Companion separates chat providers and TTS backends through addons.

## Chat Providers

Supported provider families include:

- LM Studio
- OpenAI
- xAI / Grok
- DeepSeek
- Anthropic Claude
- addon-provided providers

Hosted providers require user-supplied API keys or local provider settings. Do
not commit API keys to presets or session files.

## TTS Backends

Supported TTS families include:

- Chatterbox
- Gemini TTS Preview
- PocketTTS
- addon-provided backends

If a backend supports voice references, place your own permitted `.wav` files in:

```text
voices/
```

Only use voices you have the right to use.

## Good First Test

For the first launch, use:

- one known working chat provider
- `None` avatar mode
- one TTS backend

Once that works, add avatar and sensory features.
