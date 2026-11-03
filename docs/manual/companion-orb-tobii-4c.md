# Companion Orb and Tobii Eye Tracker 4C

The Companion Orb can follow gaze from a Tobii Stream Engine tracker, offer a
gaze-controlled menu, and use the focused screen area for reading or a visual
reply. Eye tracking is optional. Set up the ordinary Orb and a working chat
first; see [Companion Orb and AI Presence](../addons/ai_presence_companion_orb.md).

## Connect the tracker

1. Install the appropriate Tobii runtime for your tracker, connect it, and
   complete its display setup and calibration. Confirm it works in Tobii's own
   application before diagnosing NC.
2. Start NC and open **Addons → Companion Orb**. In **Overview → Activation**,
   enable and show the Orb; its display mode must permit it to be visible.
3. Open **Eye Tracking → Tracking and reactions**. Select the screen where the
   tracker is mounted and calibrated.
4. Choose **Dwell Focus** or **Continuous Follow** for the tracking mode. Use
   **Manual Only** to keep gaze available without automatic Orb movement;
   **Off** disconnects tracking.
5. In **Runtime and tools**, leave the DLL path blank for automatic discovery
   and choose **Reconnect**. Read the tracking status and selected runtime path.
6. Look around a harmless desktop area. Confirm the Orb follows the intended
   screen before enabling reading, automatic reactions, or click actions.

NC uses Tobii Stream Engine through the locally installed DLL. It does not need
PyGaze or the Tobii Pro Python SDK. Automatic discovery looks in the Tobii
installation; a common 4C path is
`C:\Program Files\Tobii\Tobii EyeX\tobii_stream_engine.dll`.
Use **Browse** only when discovery fails and you know the installed DLL's path.
Do not copy an arbitrary DLL into the project as a repair.

## Calibrate and tune placement

The **Eye Tracking** page groups the controls by task:

| Card | Use it for |
| --- | --- |
| **Calibration** | Choose **Start** and follow the five on-screen targets. Read the result; **Cancel** stops the attempt and **Reset** removes NC's saved correction. |
| **Gaze tuning** | Adjust dwell delay, stability radius, smoothing, and comment cooldown. |
| **Gaze placement** | Fine-tune X/Y placement after selecting the correct screen and calibrating. |
| **Pointer clearance** | **Move Orb away from pointer** temporarily moves it out of the mouse's way. Review its status if the Orb seems to resist a gaze position. |
| **Runtime and tools** | Reconnect, inspect the DLL path, use **React now**, or apply **Stable Gaze Preset**. |

NC's calibration correction supplements the tracker setup; it does not replace
Tobii's calibration. Keep the monitor, resolution, and tracker placement
consistent. A failed or unstable calibration reports its result rather than
silently replacing a usable correction.

**Stable Gaze Preset** changes several movement and smoothing settings. Review
its confirmation before applying it to a customized Orb. Change one tuning value
at a time after a known-good baseline.

Dwell Focus and Continuous Follow both use smoothed gaze for movement. Dwell
and reaction controls determine when a focused area can trigger commentary;
movement by itself is not proof that an image was captured or a model replied.

## Reactions and privacy

Choose the **Companion Orb Eye Tracking Reaction Mode** deliberately: **Meaningful changes**, **Every new
dwell**, or **Off**. For an explicit first test, use **React now** with a harmless
area and verify the returned reply.

Reading and image commentary also need working speech or a vision-capable model,
as appropriate. Open **Runtime → Vision Sensors → Companion Orb Target** for
its **Setup**, **Watches**, and **Actions** controls. Review **Shared Awareness
Policy** in Vision Sensors before allowing repeated reactions or watches. These
sensory controls are separate from the Addons rail. A visible Orb, connected
eye tracker, and active conversational watch are separate states.

A reading or visual action can send the selected screen content to the configured
provider. Check the target and provider before testing on private material.
See [Visual Reply and sensory awareness](visual-reply-and-sensory.md) for the
shared awareness permissions and stop controls.

## Use the long-gaze menu

In **Eye Tracking → Long gaze menu**, turn on **Enable long-gaze radial menu**.
Hold a stable gaze through the configured long-gaze threshold. The menu holds its
position while gaze moves between its buttons. Wait for the button's progress
indicator to complete; use the center button to return or close it.

The main actions include:

- **React**, **Describe**, **Explain**, and **Summarize** use the focused area
  with an action-specific request.
- **Read text** uses the reading and speech path. **Expand area for text** widens
  its crop; review the actual area before reading sensitive text.
- **Chat** opens a nearby text input.
- **Scrolling** starts or stops gaze-driven scrolling of the underlying window.
- **Voice** and **Reply style** change the corresponding Orb conversation choice.
- **Action** opens nearby control selection when **Enable Action gaze button**
  is enabled under **Tracking and reactions**.

**Long Gaze Ms** and **Radial Button Gaze Ms** set the opening and button dwell
times. Timer color, opacity, and **Charging focus beam** change the visual cue.
Start with the saved defaults and adjust only after an intentional action works.

## Action and grounded regions

**Action** can discover named Windows accessibility controls near the Orb.
Inspect the highlighted control and preview before completing the gaze
selection. **Inspect nearby** provides visual candidates when a useful semantic
control is unavailable. A coordinate-based candidate may lack a reliable role
or name; check its displayed click point carefully.

Applications differ in what they expose. Elevated windows, games, video, and
custom-rendered surfaces can lack usable controls. An unsuccessful discovery is
not a reason to keep activating the same uncertain target. Disable **Enable
Action gaze button** when you do not want this control-discovery path.

**Show vision-model bounding boxes** is a separate optional overlay. Its
**Grounded-region overlay**, color, and **Visible region types** cards tune what
is shown. A detected region is a model's interpretation, not a verified Windows
control. Follow the visible selection and confirmation indicators before acting.

## Blink and eye commands

**Allow blink and eye commands** is separate from click mode. Blink detection
uses short gaze-validity gaps, so tracking noise can be mistaken for a gesture.
Click mode starts disabled and is not restored as enabled after restarting.

With the permission on and tracking active:

1. Open the long-gaze menu and look at an enabled button until its timer starts.
2. Blink slowly twice. A rising tone confirms click mode is armed and closes
   the menu.
3. With no gaze menu open, a quick blink clicks at the Orb's position. Verify
   the target before using it.
4. Slow-double-blink again to disarm click mode; a falling tone confirms it.

Three quick blinks send the application's **Back** command (Alt+Left). A deliberate
long closure can toggle the long-gaze menu setting. Tracking loss or mode changes
reset click mode. Turn **Allow blink and eye commands** off to disable the gesture
path; use the mouse to recover if gaze becomes unreliable.

Keep **Blink detection** and **Eye commands** timing values at their defaults
until ordinary tracking is stable. Recalibration and placement should come before
trying to compensate for poor tracking with gesture thresholds.

## Recovery order

| Symptom | Check first |
| --- | --- |
| No runtime DLL | The Tobii installation, automatic discovery, and the runtime path NC reports |
| DLL loads but tracker is missing | USB connection and detection in Tobii's application |
| Wrong display or persistent offset | Selected screen, Tobii display setup, then NC calibration and placement |
| Jitter or unintended reactions | Calibration, smoothing, dwell radius, and reaction mode |
| Orb moves away near the mouse | **Pointer clearance** status and **Move Orb away from pointer** |
| Gaze works but no commentary | Reaction mode, vision provider, runtime readiness, and awareness permissions |
| Unexpected blink action | Disarm click mode or disable **Allow blink and eye commands** |
| Action finds no usable control | Application accessibility support; inspect a visual candidate before activating it |

Reconnect after correcting the configuration. Repair the Tobii installation only
when its own detection or NC's runtime discovery shows a missing component.
Retain a working tracker setup instead of replacing drivers to solve a provider
or screen-selection problem.
