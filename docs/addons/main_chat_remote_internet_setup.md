# Main Chat Remote: Secure Internet Setup

Internet access lets the **NC Main Chat Remote** phone app reach the same
desktop Main Chat runtime when the phone is away from the home network. It uses
**NC Relay** for account, presence, and signaling, then connects the phone and
desktop over an **encrypted WebRTC peer connection**. It is not a second AI
backend, and it is not a LAN pairing-code tunnel exposed to the internet.

> **Current setup does not require Dynamic DNS, a user-managed TLS certificate,
> or an inbound web server on the PC.** Do not port-forward a desktop HTTPS port.
> The old DDNS onboarding is not the current Internet flow.

Internet is optional. LAN pairing remains local and does not require an NC Relay
account. Disabling or disconnecting Internet does not remove LAN support.

## Before You Start

- Use a **native NC phone build**. The standard Expo Go client cannot load the
  required native WebRTC module. Install the project's Android APK or a
  purpose-built iPhone app.
- Enable **Main Chat Remote** in the Addons workspace and restart Neural
  Companion if the toggle says **Enabled after restart**.
- Have one working desktop chat provider and be ready to initialize the normal
  NC runtime. Opening the Internet tab does not start the language model or TTS.
- Use an email address you can access. Desktop registration requires a verified
  email.
- Expect one registered desktop per NC Relay account. Replacing it is explicit.

## Setup Versus Activation

| Stage | What it establishes | What it does not establish |
| --- | --- | --- |
| **Setup** | The native app is installed, the isolated relay runtime is prepared, the account exists and is verified, and the desktop is registered | A connected phone or an active chat session |
| **Activation** | The desktop and phone are signed in, the relay is connected, and a peer connection is open | That the NC engine, model, microphone, or TTS is ready |

The normal chat runtime is separate again. Choose its providers in **Runtime**,
select **Initialize NC**, and wait for **NC ready** when you want replies.

## 1. Prepare The Desktop Internet Runtime

Open **Main Chat Remote → Internet**. The **Internet access** card describes the
current account state.

If dependencies are missing, select **Prepare Internet runtime**. This prepares
the isolated NC Relay runtime used for web signaling and WebRTC. It does not
install or launch the phone app, and it does not replace the normal NC Python
environment.

The relay uses an isolated runtime and validates messages against the shared
relay protocol. Node.js is used for that shared schema validation. If
preparation reports a missing prerequisite, resolve it before continuing.

## 2. Create And Verify The Account

The desktop and phone must sign into the **same account**.

On the desktop Internet card:

1. Enter a username or email in **Username or email**.
2. Enter the account email in **Email for registration / password reset**.
3. Enter a password of at least 12 characters in **Password**.
4. Select **Create account**.
5. Open **Email verification / password help** and enter the code from the
   email in **Verification or password-reset code**.
6. Select **Verify email**.

If the account is signed in but still unverified, **Resend verification** is
available. Use **Forgot password** and **Reset password** from the same account
help area when needed.

A desktop cannot complete registration until its account email is verified.
Do not put passwords, verification codes, or tokens into a chat, screenshot, or
support report.

## 3. Sign In And Connect The Desktop

On the desktop Internet card:

1. Select **Sign in** with the verified account.
2. Confirm the card shows **Signed in as** the expected username.
3. Wait for **Desktop online** and note the active peer count.

A successful **Sign in** registers the desktop and starts the relay connection
automatically. If the account is already signed in but Internet access is
disconnected, use **Connect** when it is shown—for example, after **Disconnect**
or after verifying an already signed-in account. These actions leave the NC
language model's initialization separate.

The first registration belongs to that installation. If the service reports
`DESKTOP_REPLACEMENT_REQUIRED`, the account already has a registered desktop.
Review the warning, tick **Replace the registered desktop and disconnect it**,
enter the password, and select **Confirm desktop replacement** only when you
intend to replace it.

## 4. Connect The Phone

In the native phone app, open the connection screen and choose the **NC Relay ·
Internet** area:

1. Select **Sign in**, or create the account here with the same email and
   verified identity.
2. Sign into the **same account** used on the desktop.
3. Select **Connect Internet**.
4. Wait for the desktop to appear online, then for the peer connection to
   become active.

The phone does not use the LAN pairing code in Internet mode. If both LAN and
Internet are configured, choose **Internet** explicitly when you need to prove
that the relay path is being used. An automatic mode may try LAN first.

### Presence is not a peer connection

There are three separate states:

1. The account is signed in.
2. The desktop is published as online.
3. The phone and desktop have completed a WebRTC peer connection.

A desktop can be listed as online while ICE negotiation is still failing. Treat
a usable connection as **both** a completed phone connection and an active peer,
not merely as "Desktop online" or "Backend Ready".

## 5. Verify The Whole Path

Before relying on Internet access:

1. Confirm the phone reports a connected Internet peer.
2. Send a short typed message and confirm the reply appears in the shared
   desktop Main Chat.
3. Play one short voice reply.
4. Try a longer reply and the phone's pause/resume controls.
5. If enabled, test the avatar and one Visual Reply.
6. Disconnect Internet and confirm LAN still works locally; reconnect and
   confirm the peer returns.

Stop and reconnect after changing connection mode if the phone does not refresh
its route.

## Network Requirements

Internet mode is **outbound from the PC and phone**. It does not require an
inbound port forward, a public IP on the desktop, DDNS, a user-managed
certificate, or a router rule pointing at the PC.

Allow outbound access as needed for:

| Purpose | Destination |
| --- | --- |
| Account and HTTPS API | `nc-relay.online` over TCP 443 |
| WebSocket signaling | `signal.nc-relay.online` over TCP 443 |
| STUN/TURN | `turn.nc-relay.online` on TCP/UDP 3478 |
| TURN relay media fallback | UDP 49160–49260 |

A direct peer path is preferred. TURN is the fallback when the networks cannot
connect directly. Restrictive corporate or public Wi-Fi may block UDP; the
connection can still succeed through a permitted TURN path, but this is not
guaranteed. Carrier-grade NAT does not by itself prevent Internet mode because
the PC is not receiving an inbound connection.

Do not expose the LAN backend or the NC loopback bridge to the internet as a
workaround.

## What Travels Where

- The relay's HTTPS API and signaling WebSocket handle account, presence, and
  connection metadata.
- Prompts, replies, microphone recordings, TTS audio, images, and avatar media
  are carried over the encrypted WebRTC peer channel.
- When TURN is needed, it forwards encrypted WebRTC packets. It is not given
  plaintext chat or audio through the relay application API.
- The signaling service still sees connection metadata. Encryption does not
  make traffic invisible at the network level.

NC stores the phone's refresh token in the phone's secure store and the desktop
refresh token in Windows Credential Manager. Access tokens are kept in memory.
Refresh tokens rotate and are single-use.

## Android Animated Avatar Requirement

The **continuous Android avatar path** — both streamed MuseTalk video chunks and
complete cached idle loops — requires **NVIDIA NVENC hardware H.264 encoding on
the desktop PC**. NC does not silently fall back to CPU encoding. It also does
not implement Intel Quick Sync or AMD AMF for this path. The phone does not need
an NVIDIA GPU.

The streamed path stays at **24 fps**. Your selected bitrate and resolution are
used, subject to the app's quality limits. NVENC offloads H.264 compression, not
PNG loading, scaling, mixing, audio encoding, or validation.

Check the desktop from the same environment used to launch NC:

```powershell
where.exe ffmpeg
ffmpeg -hide_banner -encoders | findstr h264_nvenc
```

Then run a real hardware encode. This writes no media file:

```powershell
ffmpeg -hide_banner -f lavfi -i color=c=black:s=320x240:r=24 -frames:v 12 -an -c:v h264_nvenc -preset p4 -profile:v baseline -bf 0 -pix_fmt yuv420p -f null -
```

Success means exit code 0, twelve encoded frames, and `h264_nvenc` in the output.
An encoder listing alone does not prove that the driver, GPU, or available NVENC
session works. Close other applications that may be holding NVENC sessions.

For cached idle validation, NC also needs its isolated relay media environment
to decode the finished H.264 file:

```powershell
.venvs\nc_relay\Scripts\python.exe -c "import av; print('PyAV', av.__version__); print(av.Codec('h264','r').name)"
```

If that environment is missing, use **Prepare Internet runtime**. PyAV is used
to validate output; it is not the NVENC encoder.

## Security And Account Care

- Use a unique password and keep the verification email private.
- Sign out on any phone or desktop you still control before disposing of it.
- Use the password-reset flow from **Email verification / password help** if
  account access is at risk.
- The current desktop Internet panel shows active peer count, not a per-phone
  device inventory. Do not assume a desktop replacement revokes every phone
  session; the available per-device action is **Sign out** on that phone.
- Replacing the registered desktop disconnects the previous desktop
  registration. It is not a routine troubleshooting step.
- Never share a password, verification code, access token, refresh token, or
  account recovery code in chat or diagnostics.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| **Prepare Internet runtime** keeps appearing | Read the preparation result; a missing isolated runtime or Node.js schema validator must be resolved first |
| Account created but desktop will not register | Verify the email, sign in, and wait for automatic registration. Use **Connect** if already signed in but disconnected |
| Desktop online, phone never connects | Wait for ICE/TURN negotiation, confirm both devices use the same account, allow outbound TCP 443, TURN TCP/UDP 3478, and UDP 49160–49260, then reconnect both ends |
| Works on one network but not another | The direct path may be blocked. Check whether the phone reports a relay/TURN path and whether UDP or TCP fallback is allowed |
| `DESKTOP_REPLACEMENT_REQUIRED` | The account already has a registered desktop. Use the explicit replacement flow only if intended |
| `TOKEN_REUSED` or repeated sign-in failure | Clear the stored session by signing in again; do not retry refresh indefinitely |
| Phone app opens but WebRTC is unavailable | Expo Go or an old APK cannot provide the native module. Install a matching native build |
| Animated avatar fails with GPU/NVENC errors | Run both FFmpeg checks above from NC's environment and free any busy NVENC session |
| Chat connects but there is no reply | Choose the normal providers in **Runtime**, select **Initialize NC**, and wait for **NC ready**; remote connectivity alone does not start chat |

## Current Limits

- NC Relay is a service dependency. Internet mode is not an offline or
  peer-to-peer-only feature.
- The desktop must be awake, connected, and running NC.
- One account has one registered desktop at a time.
- Android animated avatars require NVENC. Intel, AMD, and CPU-only desktops can
  still use audio and non-animated presentation, but not this path.
- Phone features depend on the capabilities advertised by the connected desktop
  and on the installed native build.
- Presence, relay connection, peer connection, and chat-runtime readiness are
  separate states and should be checked separately.

## Related Guides

- [Main Chat Remote overview](main_chat_remote.md)
- [Local Room](local_room.md)
- [Addon setup and index](../manual/addons.md)
