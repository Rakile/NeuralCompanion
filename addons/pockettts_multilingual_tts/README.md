# PocketTTS Multilingual

Separate TTS backend for PocketTTS language-specific models.

This addon uses the same isolated PocketTTS Python runtime configured by the regular PocketTTS addon, but it requires a PocketTTS install that supports multilingual model loading from `kyutai-labs/pocket-tts`.

Use the regular PocketTTS backend for the bundled English runtime. Use this backend when you explicitly want French, German, Spanish, Portuguese, or Italian PocketTTS output.
