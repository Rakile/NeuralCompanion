# First Run

Start with the smallest working setup, then enable heavier features one at a
time.

## Basic Chat And Speech

1. Start LM Studio and load a chat model, or configure an API provider.
2. Launch Neural Companion.
3. Select the chat provider and model.
4. Select `None` as Avatar Engine.
5. Select a TTS backend.
6. Press `Initialize System`.
7. Type a message or use push-to-talk.
8. Confirm the assistant replies and speech plays.

## After Basic Startup Works

Enable optional pieces one at a time:

- Chatterbox voice reference cloning
- PocketTTS
- VSeeFace
- VaM
- MuseTalk
- Visual Reply
- screen, webcam, clipboard, or heart-rate sensory features

This makes failures much easier to identify.

## Stopping

Use the UI terminate/stop control before closing external avatar tools or local
LLM servers. Some providers intentionally keep models loaded outside Neural
Companion.
