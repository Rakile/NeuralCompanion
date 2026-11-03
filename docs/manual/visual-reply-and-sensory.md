# Visual Reply and sensory awareness

Visual Reply creates images. Sensory sources supply observations such as a
screenshot, webcam snapshot, copied image, or music metadata. Supervisors add
optional reaction rules. Capture, model calls, and permission to react are three
different things; set them up in that order.

Start with ordinary chat and speech working before adding image generation or
background awareness.

## Generate one image

1. Open **Runtime → Runtime Session → Visual reply**, select an image provider, and fill in its
   connection and model settings. Hosted providers require your own credentials;
   ComfyUI requires a running server and a compatible workflow.
2. Use **Make active** when the settings are ready.
3. Set **Visual reply mode** to **Automatic** so an image request can run.
4. In **Addons → Persona → Visual replies**, check that the persona’s
   **Visual Reply behavior** is **Generate when asked** or **Generate when asked
   or spontaneously**. Initialize chat and ask:
   "Create a watercolor image of a lighthouse at dusk."
5. Wait for the image in Conversation or the **Visual Reply** workspace, or read
   the provider error shown there.

Viewing a provider card does not activate it. Quick personas store image
behavior with their identity. Complete session presets can also restore
addon-declared settings; review the active provider and connection after loading
a setup.

The assistant can request an image with a hidden `[visualize: ...]` instruction;
NC removes that instruction from the visible reply text. You do not need to type
tags yourself.

For supported xAI or Runware setups, open **Image-to-image**, turn on
**Use image-to-image when a reference image is supplied**, and select the
**Image-to-image model**. Stage a valid image in Conversation and ask, for example,
"Keep this composition but make it a pencil sketch." Runware also exposes
**Transformation strength**. Requests without a valid reference use the standard
image model.

For an explicit image-only request or a prompt you can refine and review first,
see [Visual Reply slash commands](visual-reply-commands.md). These commands have
their own explicit generation flow.

See [ComfyUI setup](../visual_reply_comfyui.md),
[Visual Reply toolbar](../visual_reply_toolbar.md), and
[appearance freedom](../visual-reply-appearance-freedom.md).

## Configure one sensory source

Open **Runtime → Vision Sensors**. Each source page contains its own **Setup**,
prompts, and source-specific awareness controls. The **Shared Awareness Policy**
is the master gate for background review.

![Vision Sensors and shared awareness controls](../readme_images/2026-10/vision-sensors.png)

| Source | What it provides | First check |
| --- | --- | --- |
| **Screen** | A whole screen, monitor, region, or square from the desktop | Select a harmless area and use **Test capture** |
| **Webcam** | A camera snapshot | **Refresh cameras**, choose **Capture camera**, then **Test capture** |
| **Clipboard** | Copied images, not arbitrary text | Choose next-turn, immediate-send, or background delivery |
| **Companion Orb Target** | The Orb's independently selected window, region, or screen | Confirm the Orb target is visible and available |
| **Spotify Sense** | Current playback metadata, not raw audio | Connect Spotify and check **Now playing** |
| **Mock Heart Rate** (shown as **Heart Rate**) | Simulated BPM text for demonstrations | Confirm the value is a simulation, not a health device |

**Test capture** takes a source sample without calling a language model. Inspect
**Sensory capture result** before enabling background checks. A successful
capture only proves that source; it does not prove that a rule will react.

The **Screen** source has its own target. Choosing a monitor or region there does
not replace the **Companion Orb Target** selection.

## Clipboard delivery

Clipboard handles images rather than arbitrary copied text.

- **Attach to the next user turn** waits for your next message.
- **Send copied images immediately** submits a turn without waiting and requires
  a running runtime.
- **Use copied images in background awareness** lets the shared awareness loop
  consider copied images.

Immediate sending and background use are mutually exclusive. Choose the one that
matches when you want the image to be considered, rather than enabling both.

## Permit a background reaction deliberately

1. Verify the intended source and its destination model. Images can be sent to
   the configured remote/API provider even when the review itself is hidden.
2. Enable that source and **Shared Awareness Policy**. Set a moderate
   **Check-in interval** and an appropriate **Sensory history depth**.
3. If using a supervisor, configure and enable a concrete rule. For example:
   **Screen Supervisor** trigger "A new slide title is visible" with action
   "Briefly summarize the visible title." A selected profile alone is not an
   active rule.
4. Enable **Allow hidden proactive speech** only if eligible reviews may speak.
   Enable **Allow hidden visual generation** separately if a reviewed scene may
   request an image.
5. Test a visible matching change. A valid capture and an appropriate reaction
   are separate results. Silence can be correct when nothing relevant changed.

**Shared ping/pong prompt**, source prompts, and supervisor **Advanced Prompt
Rules** shape the review. **Combined hidden review prompt preview** shows the
assembled text with sample payloads; it does not prove that a live capture
occurred. Treat captured content as observations, not as instructions to follow.

## Orb watches and stopping

Showing the Orb does not enable watching. Select its target, verify the vision
model, and review **Enable watching** consent, including the image recipients and
other enabled sensors affected by shared background permissions. Then ask for a
bounded task such as "Tell me when the visible video title changes." Check the
active-watch status: a registered watch is not necessarily running.

See [Companion Orb and AI Presence](../addons/ai_presence_companion_orb.md) for
the Orb's activation and target controls.

Stop at the right layer:

- Disable a rule or its supervisor to stop that reaction.
- Disable a source to stop its background contribution.
- Disable **Shared Awareness Policy** to suspend background sources while
  remembering their selection.
- Review independent clipboard immediate-send, next-turn delivery, screen
  next-turn attachment, and Orb watches separately.
- Remove a watch to stop that watch; hide the Orb separately if you no longer
  want the overlay visible.

## Troubleshooting

If a reaction is missing, check in this order:

1. Does **Test capture** return the expected content?
2. Is the conversation runtime initialized and the destination model ready?
3. Is **Shared Awareness Policy** enabled?
4. Is the specific supervisor rule enabled and matching?
5. Is the expected response type allowed: speech, image, or neither?
6. Has a cooldown or history limit suppressed the reaction?

If the wrong area is captured, correct that source's target instead of widening
capture. Captures are snapshots, and a vision model can misread an image.
