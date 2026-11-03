# Conversation voice selection

`/voice` opens the Voice tab on the phone. The desktop composer also lists voices
when typing `/voice`; choose an entry to apply it. Both use the existing desktop
Conversation voice-reference library (including built-in/default), not a second
TTS system or provider configuration. The current selection is marked.

Only future generated speech uses the new choice. Saved persona records are not
edited. Selecting another persona restores its saved voice through the existing
Quick Persona activation pipeline. Personas without a saved voice keep the
existing desktop fallback behavior.

Implementation touches the phone command registry, QuickPersonaSheet, VoicePicker,
API types/client; the Main Chat Remote voice routes and relay allowlist; and the
native host callbacks plus ConversationCommands. The existing desktop voice setter
is shared. Library scanning runs in its existing executor; selection runs on Qt's
thread. Phone requests use catalog IDs, never desktop paths.

Restart the desktop to register its updated host callbacks, and install the updated
Android APK (or rebuild iOS). Connect, run `/voice`, choose a different voice, send
a message, switch persona, and send another message to hear its configured voice.
Confirm that queued audio retains its original voice and that saved persona
settings are unchanged.

Validation: TypeScript, phone slash-command and voice-picker smoke checks,
authenticated voice-route/privacy tests, asynchronous library scan and persona
voice restoration tests, desktop command tests, persona voice persistence and
native remote adapter checks. The broader persona-preset ownership smoke is
currently blocked by its existing probe missing `_identity_relay_timer`; its
failure occurs in unchanged persona activation code. The old skill-referenced
`smoke_main_chat_remote.py` no longer exists; the focused native tests were used.
Physical phone playback and iOS build verification remain required.
