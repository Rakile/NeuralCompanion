# Phone Native audio

Durable app-local Kotlin sources are copied by `with-phone-native-audio` during
Expo prebuild. Expo Go/web/iOS report `native_build_required`; Backend HQ remains
the default in the consuming app. No new backend speech endpoints are needed.

`src/native/phoneNativeAudio.ts` exports the bridge. Empty language resolves to the
device locale. English prefers explicitly installed Sherpa Moonshine STT / Kitten
TTS (speaker IDs 0–7). Matching installed Android on-device recognition and local
TTS voices are the only fallback. API 31–32 recognition is conservatively reported
unavailable because installed language readiness cannot be proved there. Sherpa
still works on these versions. API 33+ checks installed on-device languages.

Model install is explicit (~61 MB compressed for both English packs), fixed-URL,
SHA-256 verified and bounded. Model files live in app-private no-backup storage.
It sends no speech, pairing details or credentials. Network TTS voices and generic
cloud-capable recognizers are excluded. An engine failure emits a safe error and
uses a matching offline engine if ready. Recognition failure cannot replay captured
PCM into Android's system recognizer; fallback begins a fresh listening utterance.

TTS returns an owned `file://` WAV and optional `durationSeconds` from real WAV PCM
metadata. It never plays it. JS must release playback then call `deleteAudio(uri)`;
cancel does not remove a file already delivered to the player. `cancelSynthesis()`
preserves microphone capture for barge-in; `cancel()` stops recognition, synthesis
and install. Backgrounding cancels capture and outstanding work. Native engine
pointers are released only on their serial owning workers after inference exits.

Capture is 16 kHz mono with bounded utterances (60 s), sustained speech detection,
900 ms silence endpoints and 10 Hz metering. Live capture uses VOICE_COMMUNICATION
and available platform echo cancellation. Playback/audio focus remains owned by
the existing Expo player. Native TTS input is limited to 3000 characters; the app
queue splits longer replies. Transcript events have stable session IDs, unique
utterance IDs, provider/language and final text; the native module never submits
chat messages itself.

Builds fetch the pinned official sherpa-onnx 1.13.2 AAR, verify size/hash and add
Commons Compress 1.28.0 for bounded tar.bz2 extraction. To reuse a local build cache,
set `NC_PHONE_SHERPA_AAR` to that AAR; the same verification still applies. No model
packs are included in the APK. `THIRD_PARTY_NOTICES.txt` is copied into APK assets.
Review the GPLv3 eSpeak NG component/source provenance before redistribution.

Tests: run `node scripts/smoke-phone-native-plugin.cjs`,
`node scripts/smoke-phone-native-adapter.cjs` and, after prebuild,
`gradlew :app:testDebugUnitTest`. The optional `androidTest` fixture probe is test
APK source only: stage it under generated app/src/androidTest, use the platform
InstrumentationTestRunner and Gradle `useLibrary 'android.test.runner'` plus
`useLibrary 'android.test.base'`, and place verified model archives in the test target's
private files/speech-fixtures directory. It loads real models, decodes the official
test WAV and validates generated local WAV duration. No production debug/file API
is exposed. Pass `-e class com.neuralcompanion.phonespeech.LocalModelsInstrumentedTest`
to avoid expensive whole-app discovery. Physical Android microphone, echo cancellation, installed system voice
and 16 KB-device validation are still required in addition to emulator tests.
