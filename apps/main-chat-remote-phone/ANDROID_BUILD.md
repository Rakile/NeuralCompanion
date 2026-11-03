# Android application source

A new signed Android 0.5.0 download is deferred from the desktop source release.
The existing alpha APK remains a legacy download and has not been validated
with desktop 0.5.0. The source and build notes below are for maintainers preparing
and testing a matching native client.

See [phone setup](README.md) for running the production source. Use the official supported phone build for normal use. Use the [project releases](https://github.com/Rakile/NeuralCompanion/releases) for supported builds. Official native builds require the complete regression gate and device acceptance.

The Android application ID is `com.neuralcompanion.mainchatremote`. Builds
with an older application ID are separate Android applications; pair the new
installation with your desktop. Development variants use
`com.neuralcompanion.mainchatremote.dev`. Existing iOS identity and URL schemes
are unchanged.

The phone version prepared for this desktop release is **0.5.0**, Android
version code **12**. Distributable APKs must be release-mode builds with their
JavaScript bundled and a production signing certificate. A debug APK or a build
that needs a Metro development server is not a release download. Keep the
production keystore and passwords outside this source folder. Verify the signed
APK and test it on a phone before distribution.
