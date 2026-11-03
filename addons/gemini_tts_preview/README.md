# Gemini TTS Preview addon

For current setup and provider activation, see [Chat and speech](../../docs/manual/chat-and-tts.md). Enable the addon in Addon Manager if it is unavailable, then select and activate it in **Runtime → Runtime Session**.

This addon registers a Gemini-based external TTS backend for Neural Companion.

It uses the official Gemini preview TTS endpoint and exposes settings through **Runtime → Runtime Session → Text-to-speech**.
Select **Gemini TTS Preview**, configure it, then choose **Use for voice output**.
Its settings include:

- API key
- Base URL
- Model id
- Voice
- Optional language code
- Optional style prompt

The backend is registered as `gemini_tts_preview`.

Current model defaults follow the official Gemini preview TTS docs. If Google changes the preview model id later, the addon can be pointed at the new id from its Model field without changing core NC code.
