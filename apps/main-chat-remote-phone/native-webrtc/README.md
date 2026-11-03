# NC local media presentation and standard WebRTC

NC Remote uses the pinned standard `react-native-webrtc` 124.0.8 package with
upstream Jitsi M124 binaries. The data channel carries files; NC's Expo Audio
players and local H.264 segment players own buffered playback. There is no
custom WebRTC SDK installation or SDK build step in the supported app path.

This directory contains maintained Android and iOS presentation code, idle-loop
caching, sequential handoff, frame observation, diagnostics, and their tests.
`android/`, `ios/`, `output/`, and `enroll-module.cjs` remain part of that code
and its verification. Some retained native guard fixtures exercise low-level
media contracts; their presence does not enable a custom SDK build path.

## Native dependency enrollment

Use the phone app's pinned dependency versions and normal installation flow.
Its `postinstall` runs `scripts/apply-native-audio-patches.cjs`, applying the
maintained Expo Audio/Video patches and buffered presentation enrollment.
`scripts/apply-native-av-patch.cjs` selects Android or iOS using
`EAS_BUILD_PLATFORM` (or the local host platform default).

`enroll-module.cjs` verifies the standard WebRTC package's version and source
hashes without installing replacement SDK binaries. It enrolls the maintained
local presentation sources into Expo Audio 1.1.1. Enrollment validates pinned
inputs, accepts an exact repeated application, and rejects unknown edits or
partial enrollment. Reinstall the pinned dependencies when verification reports
an unsupported modified tree; do not bypass the source checks.

Ordinary iOS enrollment retains its existing handoff acceptance gate. Native
diagnostic fingerprints include the platform sources, so changing even a
retained source requires a matching rebuilt native application for comparison.

## Local checks

Run these from `apps/main-chat-remote-phone` with the pinned dependencies present:

```sh
node native-webrtc/tests/test-audio-enrollment.cjs
node native-webrtc/tests/test-ios-audio-enrollment.cjs
node scripts/smoke-idle-enrollment.cjs
node scripts/smoke-av-reinstall.cjs
```

These tests cover bounded enrollment, repeated application, native source
copying, and rejection of unknown edits. They use temporary dependency fixtures;
they do not establish device playback or an installable phone build.

For native host checks, use the existing platform test runners. For example,
`node native-webrtc/tests/run-android-output.cjs` exercises playback accounting
and failure handling with host fixtures and requires the local Java/Kotlin
toolchain. On macOS with the Apple developer toolchain, `npm run test:ios-native`
runs the maintained iOS native checks, including the buffered file codec probe.
Host fixtures do not establish physical audibility, device routing, or smooth
avatar playback.

Before building or installing an Android candidate, run the complete
`npm run verify:android-regression` gate for that exact source and use the gated
`npm run build:apk` entry point. Follow `ANDROID_REGRESSION_GATE.md` for physical
acceptance; passing automated checks alone is insufficient.

The buffered restoration checkpoint and remaining app/native acceptance gates
are recorded in the repository-root document
`docs/NC-REMOTE-BUFFERED-PLAYBACK-LOCAL-CHECKPOINT-20261001.md`.
