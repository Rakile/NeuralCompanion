# Chat playback and headphone controls — 2 October 2026

The Desktop Controls sheet uses phone-aware actions for Pause/Play, Skip,
Interrupt response, Retry, Regenerate, Skip User, and retained-audio replay.
Reset Chat keeps its existing confirmation. Engine Stop closes phone output
before stopping the desktop engine. No desktop API contract changes are required.

- Pause preserves the file player and stops playback timeout clocks. Streamed
  replies use the existing authenticated continuation manifest and saved position.
- Play resumes the original response without sending a new user message.
- Skip releases the original phone reply so queued messages can proceed.
- Retry, Regenerate and Skip User target the current canonical conversation
  action rather than sending an unscoped desktop shortcut.
- Replay Last plays retained chunks for the latest reply. Replay Chat plays the
  retained phone audio in order; expired or cleared audio is unavailable.
- A reply-level Android MediaSession / iOS MPRemoteCommandCenter receives Play,
  Pause, Toggle and Stop. Audio settings includes **Headphone Next toggles pause /
  play**, enabled by default. This supports headphones that translate double-tap
  to Next. The app cannot change a headset's gesture firmware.
- Headphone events carry a local opaque playback scope. Events from an old
  reply/session are ignored. Background Live retains its existing control owner.

## Changed areas

`App.tsx`, `useAudioQueue.ts`, the ControlsBar/DesktopControlsSheet, Audio settings,
`usePhoneMediaControls.ts`, and the platform `ReplyMediaControls` adapters exposed
by `NcLiveCaptureModule`. The media adapter dispatches commands only; it does not
create another audio player or microphone pipeline.

