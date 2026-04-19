# Gemini TTS Preview addon

This addon registers a Gemini-based external TTS backend for Neural Companion.

It uses the official Gemini preview TTS endpoint and exposes its own Host settings tab for:

- API key
- Base URL
- Model id
- Voice
- Optional language code
- Optional style prompt

The backend is registered as `gemini_tts_preview`.

Current model defaults follow the official Gemini preview TTS docs. If Google changes the preview model id later, the addon can be pointed at the new id from its Model field without changing core NC code.
