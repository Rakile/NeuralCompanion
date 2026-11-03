# PocketTTS Multilingual

For current setup and provider activation, see [Chat and speech](../../docs/manual/chat-and-tts.md). Enable the addon in Addon Manager if it is unavailable, then select and activate it in **Runtime → Runtime Session**. See [PocketTTS setup](../../docs/manual/pockettts.md) for its separate runtime and voice access.

Separate TTS backend for PocketTTS language-specific models.

This addon uses the same isolated PocketTTS Python runtime configured by the regular PocketTTS addon, but it requires a PocketTTS install that supports multilingual model loading from `kyutai-labs/pocket-tts`.

Use the regular PocketTTS backend for the bundled English runtime. Use this backend when you explicitly want French, German, Spanish, Portuguese, or Italian PocketTTS output.

The factory **Default TTS voice tag rules** contain only:

```text
Do NOT use emojis when speaking!
```

The upstream text-and-reference-voice API does not document Turbo-style vocal
sound tags, so the defaults do not advertise them. Saved custom provider rules
and persona overrides retain their existing priority.
