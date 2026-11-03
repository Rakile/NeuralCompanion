# ElevenLabs TTS

For current setup and provider activation, see [Chat and speech](../../docs/manual/chat-and-tts.md). Enable the addon in Addon Manager if it is unavailable, then select and activate it in **Runtime → Runtime Session**.

This addon registers ElevenLabs as an external text-to-speech backend for
Neural Companion. It uses the ElevenLabs REST API directly and does not add a
Python SDK dependency.

Open **Runtime → Runtime Session → Text-to-speech**, select **ElevenLabs TTS**,
then configure the following and choose **Use for voice output**:

- enter an ElevenLabs API key
- refresh and select an available voice
- choose a TTS-capable model
- optionally set a language code
- adjust stability, similarity, style, speed, and speaker boost

For interactive chat, use **Eleven Flash v2.5** for the shortest response
time. **Eleven v3 Conversational** balances expressive delivery with realtime
latency. The regular **Eleven v3** model prioritizes maximum expression and
quality, so it can take noticeably longer before playback starts.

Generated audio uses 24 kHz PCM and is handed directly to Neural Companion's
existing speech-output pipeline, which owns the final WAV playback files. API
keys are stored only in the local session configuration and are excluded from
presets.
