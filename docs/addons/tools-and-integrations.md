# Tools and integrations

These smaller addons add shortcuts, saved-conversation replay, keyboard
lighting, a simulated presence signal, and an external Unreal face-mask bridge.
They are independent: enabling one does not enable another. For addon
enablement, see [Addon management](../manual/addons.md). For sensory
permissions, see [Vision Sensors](../manual/visual-reply-and-sensory.md).

For generic external tools and persona permissions, see [MCP](mcp.md). The
[Companion Chess guide](companion_chess.md) covers the separate game workspace,
its MCP setup, online play and optional Launchpad hardware.

## Hotkeys

**Purpose:** assign keyboard shortcuts to push-to-talk and common runtime,
conversation, and window actions.

**Find it:** **Addons → Hotkeys**. The page is divided into **Input**,
**Conversation controls**, and **Window controls**.

### Configure

Edit a binding in place and check its displayed group and scope before relying
on it. Test a new shortcut with NC focused first; test outside the window only
when the listed scope supports it. Avoid combinations already used by other
applications.

| Group | Action | Default |
| --- | --- | --- |
| Input | Push-to-Talk | `Right Ctrl` |
| Conversation controls | Regenerate response | `Alt+R` |
| Conversation controls | Retry user input | `Alt+Y` |
| Conversation controls | Pause or resume speech | `Alt+P` |
| Conversation controls | Skip speech | `Alt+Enter` |
| Conversation controls | Skip user reply | `Alt+U` |
| Window controls | Start runtime, Stop runtime, Reset chat session, Clear console, Clear chat, Show MuseTalk Preview, Toggle MuseTalk Avatar Focus, Show Visual Reply | Unassigned |

Push-to-Talk is a hold-and-release shortcut. It needs the runtime's
**Push-to-Talk** input mode and a ready speech-input provider; hold the
configured key while speaking and release to finish. Orb-specific shortcuts are
configured in the Orb addon rather than here.

**Start and stop:** Hotkeys has no master switch. When the addon is enabled, its
bindings are handled by the running NC app. To control the runtime from the
keyboard, assign **Start runtime** and/or **Stop runtime** under **Window
controls**—both are unassigned by default. **Restore default hotkeys** resets
every group, not only the current section.

**Limitations:**

- A combination can conflict with another application or with a reserved
  system shortcut. Change a conflicting combination; optional conversation and
  window bindings can be cleared.
- Push-to-talk follows the active speech-input runtime; it does not provide its
  own recorder.
- Application shortcuts and global input shortcuts are not interchangeable. Check
  the scope shown with the binding.

## Conversation Replay

**Purpose:** load a saved chat context into the shared conversation and replay
the chat from a selected point or the whole chat through normal speech output.
The built-in tutorial calls this workflow **Chat Session Player**.

**Find it:** **Addons → Conversation Replay**. The page has **Overview**,
**Session**, **Messages**, and **Replay voices** sections.

### Configure

1. Save your current conversation before loading another one.
2. In **Session**, use **Load chat context** to choose a saved context, or
   **Quick Load** to use NeuralCompanion's quick-save context. Use **Refresh**
   to update the view.
3. Check **Overview** for the session summary, replayable message count, and
   whether the runtime is stopped, live, or in offline replay.
4. In **Messages**, select a replayable message. **Previous** and **Next** only
   move the selection; they do not skip currently playing speech.
5. Use **Replay from selected**, **Replay latest reply**, or **Replay complete
   chat**.
6. In **Replay voices**, set **Assistant voice** and **User voice** from the
   local `voices/*.wav` references, or leave **Use current TTS voice**. Use
   **Refresh voices** after adding files.

**Start and stop:** the replay buttons start speech through NC's shared
speech/runtime service, including offline replay when the live runtime is
stopped. The addon has no pause, skip, or stop transport of its own. Use the
normal **Pause** or **Skip speech** conversation controls where available, or
stop the runtime.

**Limitations:**

- Loading a context changes the shared conversation; this is not an isolated
  preview player. Save first if you need the current chat.
- **Previous** and **Next** are selection controls, not playback transport.
- Separate role voices require a reference-capable speech backend. The voice
  list contains only WAV files found in the local `voices` folder.
- Replay actions are unavailable when no replayable messages are loaded; check
  the message list and **Replay status**.

## Corsair LEDs

**Purpose:** render NeuralCompanion's idle, listening, thinking, and speaking
states, mood tint, and speech-reactive animations on Corsair keyboards exposed
through iCUE.

**Find it:** **Addons → Corsair LEDs**. For official SDK setup, device-discovery
behavior, audio fallback, and failure handling, see the
[detailed Corsair Visual Instrument README](../../addons/corsair_visual_instrument/README.md).

### Configure

- **Connection** contains **Enable Corsair visual lighting at startup**,
  **Connection status**, **Status detail**, and **Reconnect & Rescan**. Keep
  iCUE running, leave Device Memory Mode, and enable SDK/game integrations
  before reconnecting.
- **Devices** lists **Detected keyboards**. Automatic mode uses each keyboard's
  LED layout; **Force zone renderer** and **Force per-key renderer** are
  optional overrides. **Zone display mode** offers **State Lanes** and
  **Unified**.
- **State colors & mood** sets **Idle**, **Listening**, **Thinking**, and
  **Speaking** colors, plus **Tint state colors with the current mood** and
  **Mood tint** strength.
- **Keyboard animation designer** provides **State to edit**, **Animation**,
  **Speed**, **Intensity**, **Animation size**, **Trail / softness**, **Audio
  reactivity**, **Effect detail**, **Test audio level**, and a preview action.
  **Preview Speaking** (or the selected state) sends an explicit test effect.
- **Speech response** provides **Speech sensitivity** and **Speech smoothing**.
  These shape playback-energy visualization, not microphone capture.
- **Global output** limits **Brightness**, **Animation speed**, and **Frame cap**.
- **Advanced SDK** shows the **64-bit SDK DLL** path and **Browse for SDK DLL**.

**Start and stop:** **Enable Corsair visual lighting at startup** is also the
master switch. Turning it off releases the addon's active keyboard layers and
disconnects from iCUE; turning it on starts output without restarting NC.
Unloading the addon has the same releasing effect. Use **Reconnect & Rescan**
after changing iCUE devices or permissions.

**Limitations:**

- iCUE must stay running with SDK access and a compatible 64-bit SDK DLL.
  Missing DLLs, disabled integrations, disconnected devices, and per-device
  write failures appear in **Connection status** / **Status detail**.
- Keyboards that expose no controllable LEDs are not active lighting targets.
- Speech response uses the PC's mixed audio output, so other audible PC audio
  can affect the effect. TTS routed only to a phone is not captured. If spectrum
  data is unavailable the addon falls back to NC's scalar speech level; if both
  are unavailable, the state-only Speaking indication remains.
- Lower **Brightness** first when the effect is too intense; lower **Frame cap**
  if the lighting update rate is excessive.

## Mock Heart Rate and Heart Rate Behavior

Mock Heart Rate is a **simulated development source**. It publishes a
text-only BPM value; it is not a heart-rate sensor, wearable, medical device,
diagnosis, or health monitor.

**Find them:** **Runtime → Vision Sensors → Heart Rate**. The provider's
**Setup** tab contains **Mock Heart Rate** and **Heart Rate Behavior** controls.
**Test capture** checks the registered source without calling an LLM.

### Configure the simulated source

- Set **Heart rate** between 0 and 200 BPM. The default is 72.
- **Show floating heart-rate monitor** stores the monitor preference. The
  current workspace does not render a separate heart-rate window; use **Test
  capture** to confirm the current simulated value.
- Enable the **Heart Rate** source with its switch or **Enable this sensory
  source**, and also enable **Shared Awareness Policy**. Background checks need
  both.

### Configure behavior

Heart Rate Behavior adds persona-driven threshold rules to the simulated source:

- Enable **Heart Rate Behavior** and choose an **Active Reaction Profile**.
  **Add Profile**, **Rename Profile**, **Delete Profile**, and **Speaking
  style** manage the profile.
- Under **Reaction Rules**, use **Add Rule** and **Reaction rule** to select a
  rule. The rule's **Enabled**, **Signal Trigger**, **Action**, **Strictness**,
  **Emotion override**, **Repeat mode**, and **Nth match interval** controls
  define when and how it reacts. **Advanced Prompt Rules** and **Review Prompt
  Preview** expose the underlying prompt.
- The default **Coach** profile contains one disabled rule for a heart rate
  above 120 BPM.

For a demo, enable that rule, set **Heart rate** to 125, and start the
conversation runtime. A spoken reaction also needs **Allow hidden proactive
speech** in **Shared Awareness Policy**. Changing the BPM alone does not enable
a rule or prove that a reaction occurred.

**Start and stop:** enable the source and **Shared Awareness Policy** for
background checks; enable the behavior and a rule for interpretation. To stop,
disable the **Heart Rate** source, disable **Heart Rate Behavior**, turn off
**Show floating heart-rate monitor** if it is no longer wanted, and disable
**Shared Awareness Policy** when no background awareness is needed.

**Limitations:**

- The BPM is simulated rather than measured from the user.
- The source is text-only BPM. It provides no pulse waveform, device connection,
  or hardware sensor.
- The value is clamped to 0–200 BPM. Missing or invalid BPM cannot establish a
  threshold match.
- A matching rule still depends on the running conversation, the active
  profile, the shared awareness policy, and the proactive-speech permission.

## Ua Companion Orb Overlay

**Purpose:** stream MuseTalk face-mask frames to a separate Unreal-rendered
Companion Orb. This is an external integration, not the normal desktop
Companion Orb. See [Companion Orb and AI Presence](ai_presence_companion_orb.md)
for the normal Orb's targeting, watches, movement, and display controls.

**Find it:** there is no separate addon settings tab. Open **Runtime → Runtime
Session → Avatar → MuseTalk → Performance** and use **Send MuseTalk face mask to
Companion Orb**.

### Configure

1. Set up and run MuseTalk so it produces avatar frames.
2. Start the external Unreal overlay/receiver.
3. Enable **Send MuseTalk face mask to Companion Orb**.

The switch routes frames over a Windows named pipe to the external receiver. It
does not launch MuseTalk or the Unreal application, and it provides no local Orb
preview. While it is enabled the normal MuseTalk preview is suppressed; turn the
switch off to restore normal preview routing.

**Start and stop:** there is no separate start button. Frames flow while
MuseTalk is producing output, the switch is on, and a receiver is available.
Turn the switch off, stop MuseTalk, or stop the runtime to stop the stream.

**Limitations and prerequisites:**

- Requires working MuseTalk avatar output and an external receiver that
  understands the overlay's named-pipe stream. NeuralCompanion provides the
  sender only; the Unreal side is a separate application.
- Only MuseTalk frames are bridged. Other avatar providers and the normal
  Companion Orb are unaffected.
- With no receiver connected, frames cannot be displayed. The stream is
  best-effort and does not create a local preview.
- The normal MuseTalk preview is unavailable while this routing is enabled.
