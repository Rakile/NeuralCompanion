# Voice Studio

Open **Addons → Voice Studio** to create or organize reusable voice recordings.
Enable the addon in Addon Manager first and restart if the manager requests it.

The workspace has **Create Voices**, **Voice Library**, and **Settings**. For
provider setup, generation review, saved cast drafts, library details, and
cleanup, follow the [Voice Studio guide](../addons/voice_studio.md).

Voice Studio publishes saved WAVs to the same `voices/` library that Persona
lists. Test auditions are stored separately and are not added to the library;
**Save test recording…** copies one to a new WAV and does not overwrite an
existing file. Removing an entry with **Remove from library** hides it from both
lists without deleting the WAV, so saved persona assignments keep working.

Saving a recording does not assign it to your companion. Open **Addons → Persona
→ Voice**, select a compatible reference, preview it, then choose **Use this
voice for …**. Original playback and a generated test are separate from the saved
assignment. See [Personas](personas.md#assign-a-voice).

The active speech provider is selected separately in **Runtime → Runtime Session
→ Text-to-speech**. See [Chat and speech](chat-and-tts.md#add-spoken-replies).
