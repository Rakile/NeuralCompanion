# NC Main Chat Remote

The phone companion connects to NeuralCompanion on Windows through LAN pairing or an Internet relay. It supports chat, microphone input, spoken replies, characters, stories, Visual Reply and supported avatar playback.

For everyday setup, follow [Main Chat Remote](../../docs/addons/main_chat_remote.md) and [Internet setup](../../docs/addons/main_chat_remote_internet_setup.md). Obtain the supported phone build through the project release instructions. This source folder is not an installed phone application.

## Download availability

The desktop 0.5.0 source release precedes the new signed Android download.
The existing alpha release remains a legacy download, with unverified
compatibility with desktop 0.5.0. Build and validate the included native source
if you need a current client before a supported phone release is published.

## Run the phone source locally

Use Node.js 24 and npm. From this directory run:

```powershell
npm ci
npm start
```

`npm ci` applies the pinned native dependency patches. Do not replace the lockfile or upgrade dependencies as part of setup. `npm run android`, `npm run ios`, and `npm run web` select their respective Expo targets. Some features require the matching native phone build and are unavailable in Expo Go or web mode.

## Native phone builds

The production source and native dependency enrollment inputs are included here. Use the [project releases](https://github.com/Rakile/NeuralCompanion/releases) for supported builds. Official native builds require device acceptance and the complete build regression gate. The public snapshot does not include development tests or their build launchers. Removing tests from this distribution does not waive the regression gate for an official APK.

## Connection and privacy

Pair with your own desktop and keep its pairing code, tokens and relay credentials private. LAN and Internet connections have different network requirements. See the setup guides above before forwarding ports.
