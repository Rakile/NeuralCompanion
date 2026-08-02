# Phone Fullscreen Dual-VU Design

## Goal

Keep the fullscreen audio circle visually stable for long TTS replies and make live phone microphone activity visible, including while the user interrupts TTS.

## Confirmed behavior

- The outer ring contains the existing 48 TTS spectrum channels.
- While TTS is speaking, every channel keeps a fixed angular position. Audio changes bar length and glow only.
- The phone microphone uses inward-facing bars anchored to the same circumference as the outward TTS bars. It must not create a second circle.
- Listening also uses fixed angular positions. No procedural traveling or rotational microphone pattern is used.
- The rotation setting applies only to non-audio idle/thinking decoration. A value of zero means no rotation.
- If an analyzed TTS frame is briefly unavailable at a chunk boundary, the last real spectrum decays in place. It must not switch to a rotating fallback.

## Smallest safe implementation

1. Add pure spectrum helpers for activity-aware rotation and a stable 48-band microphone envelope.
2. Gate circular-spectrum rotation by activity so `speaking` and `listening` always use zero angular phase.
3. Render playback outward and microphone activity inward from the same circle when microphone activity clears the existing noise threshold.
4. Replace the time-driven listening pattern with microphone-level-derived bars and retain existing smoothing.
5. Preserve current audio capture, TTS playback, barge-in policy, bridge APIs, settings schema, and backend spectrum format.

## Verification

- Unit/smoke coverage proves speaking and listening never rotate, including with a nonzero rotation setting.
- Tests prove microphone dB changes produce stable 48-band values without time-dependent travel.
- Tests cover simultaneous TTS and microphone layers.
- Tests cover a TTS spectrum transition beyond 18 seconds and fixed-position fallback decay.
- Run phone TypeScript checks and the existing fullscreen smoke suite.
- Copy only the changed phone source/test files into the runtime worktree and compare them byte-for-byte.
- Validate on a physical Android device because microphone metering and long playback timing cannot be fully proven by desktop tests.

## Scope and risk

This is an app-only visualization correction. No desktop core runtime, addon bridge route, message format, recording lifecycle, or audio-routing behavior is intentionally changed. The primary physical-device risk is tuning the microphone visibility threshold so ambient noise stays quiet while normal speech remains obvious.
