# Silent avatar video and the iOS audio session

Maintained patch for Expo Video **3.0.16** (MIT). The before-image is included
under `upstream/`; the only native change is an early return in
`VideoManager.setAudioSession()` when no loaded, unmuted player or Now Playing
notification owner needs the session. Ordinary audible video retains upstream
handling. No dependency upgrade or microphone safety changes.

Expo's original manager sets `.playback` / `.moviePlayback` even when its
players are muted. MuseTalk creates a null-source player, mutes it, then loads
silent clips. Those clips must not replace Live Mic's `.playAndRecord` /
`.voiceChat` session. The guard also covers the null-source setup interval.

`postinstall` applies this patch before native builds. The installer accepts
only the pinned version and known original/patched hashes (LF/CRLF equivalent),
rejects unknown or partial source without repair writes, and skips Android.
Run `npm run verify:ios-video-audio-patch` and `npm run smoke:ios-video-audio-patch`.

