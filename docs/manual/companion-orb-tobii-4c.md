# Companion Orb: Tobii Eye Tracker 4C Known-Good Setup

This document records the exact eye-tracking setup verified working with the
Companion Orb on 2026-07-14. Use it as the recovery baseline if eye tracking
stops working later.

> Important: Do not replace drivers, install unrelated Tobii SDKs, copy DLLs,
> or change the working configuration unless a verification step below shows
> that something is missing.

## Known-Good Configuration

| Component | Verified value |
| --- | --- |
| Eye tracker | Tobii Eye Tracker 4C |
| USB hardware ID | `VID_2104&PID_0127` |
| Tobii software | Tobii Experience Software For Windows (IS4C) |
| Tobii software version | `4.124.0.15937` |
| Stream Engine DLL | `C:\Program Files\Tobii\Tobii EyeX\tobii_stream_engine.dll` |
| DLL file/product version | `4.17.0.6` |
| DLL SHA256 | `AD5F4C7A9104033F85F9A8494DCEE859D12733F8D0570B2178B8022B297533DF` |
| Tobii services | `Tobii Service` and `TobiiIS4LTOBIIPERIPHERAL` |
| NC DLL setting | Blank/automatic discovery |
| NC default eye mode | Dwell Focus |
| NC default screen | Primary screen (`-1`) |
| NC default X/Y offsets | `0 px` / `0 px` |

The full USB device serial is deliberately not recorded here.

## Why This Setup Works

NeuralCompanion does not use PyGaze, the Tobii Pro Python SDK, or the
`tobii_research` Python package for the Companion Orb. It uses Python `ctypes`
to load Tobii Stream Engine directly from the Tobii Experience installation.

The working data path is:

1. Tobii Experience installs the 4C driver, local Tobii runtime, services, and
   `tobii_stream_engine.dll`.
2. The Tobii services communicate with the connected and calibrated 4C.
3. NC automatically finds the DLL below `C:\Program Files\Tobii`.
4. NC calls the native Stream Engine API to enumerate the local tracker,
   subscribe to combined gaze points, and process callbacks.
5. The Companion Orb maps normalized gaze coordinates to the selected Windows
   display, smooths the samples, and applies the selected tracking mode.

The actual NeuralCompanion process was verified to have loaded this exact DLL.
No `TOBII_STREAM_ENGINE_DLL` environment variable or manually copied DLL is
needed on this machine.

## One-Time User Setup

Installing Tobii Experience `4.124.0.15937` supplies the software NC needs, but
installation alone is not the complete setup. Perform these steps once:

1. Mount the Tobii 4C correctly below the monitor.
2. Connect it directly to a reliable USB port. Tobii recommends USB 2.0 for the
   Eye Tracker 4C; avoid an unreliable or unpowered hub.
3. Open Tobii Experience and complete display setup for the monitor where the
   tracker is mounted.
4. Create or select a Tobii user profile and complete gaze calibration.
5. Restart Windows once after the initial driver/runtime installation.
6. Confirm Tobii Experience detects the tracker and gaze works there.
7. Start or restart NeuralCompanion after Tobii Experience is installed.

Calibration and correct display setup are required for accurate Orb movement.
If Tobii Experience is reinstalled, it may be necessary to repeat both.

## NeuralCompanion Settings

Open the **Eye Tracking** tab in the Companion Orb addon settings. The status
indicator is green when connected, red when the tracker or runtime is
unavailable, amber while connecting/reconnecting, and gray when eye tracking
is inactive. The runtime line shows the Stream Engine DLL selected by automatic
discovery or the manual path.

In the Eye Tracking tab:

- Enable the Companion Orb and make sure its display mode is not **Off**.
- Set **Eye Tracking** to **Dwell Focus** or **Continuous Follow**.
- Use **Manual Only** when gaze should be tracked without moving the Orb until
  a command or hotkey is used.
- **Off** disconnects eye tracking from the Orb.
- Select the calibrated monitor. The primary screen default is correct only if
  the tracker is mounted and calibrated for that screen.
- Leave the Stream Engine DLL path blank for automatic discovery.
- Use **Reconnect Eye Tracking** after changing eye-tracking settings.
- Use **X offset** and **Y offset** to fine-tune Orb placement after gaze
  mapping. Negative X moves the Orb left; negative Y moves it up.
- **Stable Gaze Preset** uses smoother Dwell Focus tuning, centers the Orb for
  its current size, and disables idle, aware, mouse-avoidance, and playful-
  nudge movement that could compete when no gaze target is active.

Both Dwell Focus and Continuous Follow move the Orb continuously from the
smoothed gaze stream. In Dwell Focus, the approximately 700 ms dwell and 60 px
stability radius gate only the visual snapshot/comment action; they do not
delay Orb movement.

### Long-Gaze Radial Menu

The long-gaze menu is optional and off by default, so enabling this version
does not change existing dwell behavior until **Enable long-gaze radial menu**
is selected.

- **Long gaze** is an exact millisecond input. Its default is `3000 ms` and its
  supported range is `1000-15000 ms`. If it is set below the normal dwell time,
  NC keeps the effective long threshold at least 250 ms after normal dwell.
- **Button gaze** is the uninterrupted time required to select one radial
  button. Its default is `650 ms` and its supported range is `250-3000 ms`.
- **Radial menu opacity** controls the complete Orbital Glass menu without
  changing gaze target geometry. Its default is `0.90` and its supported range
  is `0.35-1.00`.
- **Charging focus beam** is enabled by default. It connects the center button
  to the current gaze target with a red-to-amber-to-yellow pulse that brightens
  with button-gaze progress. Disabling it leaves button fill and selection
  behavior unchanged.
- **Expand area for text** is enabled by default. It doubles only the radial
  **Read text** capture width toward the right while preserving its height.
  Near the selected display's right edge, NC shifts the expanded crop left so
  the original focused crop remains included. Disabling it restores the
  existing centered Read text crop.
- **Gaze timer color** selects the color that fades into the current Orb theme
  while a normal dwell, long dwell, or radial-button dwell is progressing. The
  default is `#facc15`.

After one focus remains stable through the long threshold, the Orb holds its
position and opens a fixed radial menu. Eye movement then selects menu buttons
without moving the menu or replacing the original context point. The center
button closes the main menu and returns from Voice or Reply style pages.

The radial menu uses the direct mapped Tobii gaze point. Orb X/Y placement
offsets do not shift radial button selection. Its buttons are spaced 25 percent
farther from the center, use a forgiving entry area, and keep the active button
through small edge jitter. The selected button fills with the configured
gaze-timer color and a soft glow while its button-gaze timer advances.

The main radial actions are:

- **React**, **Describe**, **Explain**, and **Summarize** capture the original
  focused crop and reuse Main Chat's existing image-response pipeline with an
  action-specific prompt. A gaze selection waits briefly if an automatic visual
  reaction is already being prepared, so the explicit action is not discarded.
- **Read text** sends the same focused area through the existing selected-area
  OCR and delegated TTS path, using the optional expanded text area described
  above. The other visual response actions keep their original capture size.
- **Voice** opens paged gaze-selectable voice files and uses the existing TTS
  voice setter.
- **Reply style** opens the existing Companion Orb reply-style choices.
- **Action** opens system-wide control selection when **Enable Action gaze
  button** is enabled in the Eye Tracking tab. It stays visibly disabled and
  performs no discovery or capture work while that option is off.

The crop can be processed by local OCR or the configured vision provider when
needed. Raw gaze samples and gaze-derived desktop coordinates are not added to
Main Chat prompts, vision OCR prompts, session state, or Orb debug logs.

## Software That Is Not Required

Do not install these solely for the Companion Orb integration:

- PyGaze
- Tobii Pro SDK for Python
- `tobii_research`
- Legacy SDK development headers, import libraries, or example projects
- A separately downloaded Stream Engine DLL
- A `TOBII_STREAM_ENGINE_DLL` environment variable on this known-good setup

The Tobii Pro SDK targets research/analytical integrations. The Orb uses the
interactive Stream Engine runtime delivered by Tobii Experience.

## Read-Only Verification

Run these commands in PowerShell. They inspect the installation and do not
change it.

### Verify the DLL

```powershell
Get-Item 'C:\Program Files\Tobii\Tobii EyeX\tobii_stream_engine.dll' |
    Select-Object FullName, Length, @{Name='FileVersion';Expression={$_.VersionInfo.FileVersion}}

Get-FileHash 'C:\Program Files\Tobii\Tobii EyeX\tobii_stream_engine.dll' -Algorithm SHA256
```

Expected DLL version: `4.17.0.6`.

Expected SHA256:
`AD5F4C7A9104033F85F9A8494DCEE859D12733F8D0570B2178B8022B297533DF`.

### Verify services and processes

```powershell
Get-Service -Name 'Tobii Service','TobiiIS4LTOBIIPERIPHERAL' |
    Select-Object Name, Status, StartType

Get-CimInstance Win32_Process |
    Where-Object Name -in @(
        'Tobii.Service.exe',
        'Tobii.EyeX.Engine.exe',
        'Tobii.EyeX.Interaction.exe',
        'platform_runtime_IS4LTOBIIPERIPHERAL_service.exe'
    ) |
    Select-Object Name, ProcessId, ExecutablePath
```

Both services should normally report `Running` and `Automatic` while the Tobii
runtime is available.

### Verify the USB device

```powershell
Get-PnpDevice -PresentOnly |
    Where-Object InstanceId -match 'VID_2104&PID_0127' |
    Select-Object Status, Class, FriendlyName, InstanceId
```

The known-good installation exposes an `EyeChip`, a `Tobii Hello sensor`, and a
USB composite device with status `OK`.

### Verify NC automatic DLL discovery

From the NeuralCompanion repository root:

```powershell
.\.venv\Scripts\python.exe -B -c "from addons.companion_orb_overlay.companion_orb.eye_tracking import find_stream_engine_dll; print(find_stream_engine_dll())"
```

Expected output:

```text
C:\Program Files\Tobii\Tobii EyeX\tobii_stream_engine.dll
```

## Blink Click

Blink click uses short, explicit losses of Tobii gaze validity. It is an
optional heuristic, not a hardware blink stream, so it always starts disabled
and never persists its enabled state.

To enable it:

1. Enable **Allow blink-click gestures** in the Eye Tracking tab.
2. Open the long-gaze radial menu.
3. Look at an enabled radial button until its gaze timer starts.
4. Blink slowly twice. A short rising tone confirms that click mode is enabled
   and the radial menu closes.

With no radial menu visible, one quick blink clicks beneath the center of the
visible Orb. NC briefly hides the Orb before dispatching the click so the
underlying application receives it even when Orb click-through is disabled.
Two slow blinks disable click mode and play a short falling tone. Slow blinks
are reserved for toggling and never perform a mouse click. Tracking loss, mode
changes, Orb shutdown, and blink-setting changes reset click mode without a
sound.

### System-Wide Action

**Action** is an optional Eye Tracking extension. It is disabled by default.
Enable **Enable Action gaze button** near the top of the **Eye Tracking** tab
to make the existing Action node selectable. When disabled, Action remains
gray and NC performs no UI Automation import, accessibility traversal, screen
capture, OCR, preview encoding, or source-highlight work.

With the extension enabled, NC scans the bounded area around the Orb for
accessible controls. Only semantic UI Automation controls with a stable
identity are presented as direct role/name targets, such as
**Button - Save**, **Link - Download**, **Tab - Settings**, or **Input -
Search**. This works across Windows applications that publish an accessibility
tree, including supported application controls and browser chrome/page
controls in Chrome, Edge, and Firefox when those controls are exposed.

Looking at a direct target outlines its exact source rectangle and opens a
220 px circular preview beside the selected radial button. The preview repeats
the target role, full name, crop, exact click-point crosshair, and the same
gaze-progress countdown as the smaller button. Its position is screen-aware:
it prefers the outside of the ring and searches clear edge/corner positions
when space is constrained. Moving gaze along the connector into the enlarged
preview keeps the original target and countdown active. The enlarged preview
is fully opaque, keeps its bold role/name at the top, leaves the screenshot
clear below it, and uses only the perimeter countdown instead of an interior
fill. The centered **Back** target and the other target buttons remain
available while selecting a target. UI Automation targets are
revalidated by role, name, Runtime ID, and
bounds before NC clicks them. When UI Automation omits a control, a named
Win32/native or OCR region can still appear as a visual coordinate fallback.
These visual targets may not have a reliable semantic role and use the existing
cloak-and-click path rather than UI Automation stale-target validation.
The same enlarged-preview behavior is applied automatically to every radial
target that includes a context image, including direct controls and
**Inspect nearby** candidates.
When the separate Orb runtime is active, NC waits briefly for that runtime to
confirm that the Orb is hidden before scanning or clicking. If confirmation
does not arrive in time, the scan or click is cancelled and the local cloak is
released.

Choose **Inspect nearby** to open a paged visual selector with up to four
enlarged candidates per page. If the direct page is empty but visual candidates
exist, NC opens this visual page automatically. Each candidate has context, a
numbered source marker, and a crosshair marking the exact dispatch point.
Selecting a candidate opens a second gaze menu with **Inspect**, **Read text**,
**Read + comment**, and **Comment**. Inspect sends that selected visual context
through the existing vision-reaction path. The reading choices reuse the same
private OCR/TTS/comment paths as the Orb's right-click reading commands. Back
from the action menu returns to the same visual page. Back from the visual
selector returns to direct targets only when direct targets exist; otherwise
it returns to the main radial menu.

Windows accessibility is not universal. An application can omit or suppress
its accessibility tree; NC cannot inspect an elevated application from a
non-elevated process; and games, video players, canvas content, and other
custom-rendered surfaces often have no semantic controls. Browser pages can
also expose only part of their controls. **Inspect nearby** is the coordinate
fallback for those cases, but it cannot supply a reliable role or name.

The UI Automation dependency is pinned in both NC requirement files. If it is
missing from the runtime interpreter, recover it with:

```powershell
.\.venv\Scripts\python.exe -m pip install uiautomation==2.0.29
```

For another active Python environment, use:

```powershell
python -m pip install uiautomation==2.0.29
```

Accessibility names, bounds, runtime IDs, preview images, and visual-selector
crops are ephemeral. They are used only in memory for the current scan; the
temporary capture is scheduled for immediate deletion after preview encoding
and none of this data is written to Companion Orb logs, session state, or
sidecar files. If Windows temporarily locks the capture, NC uses bounded
background deletion retries for about 45 seconds. A later enabled Action
scan also schedules deletion of stale `companion_orb_read_*.jpg`, `.jpeg`, and
`.png` captures in the dedicated `runtime/companion_orb/click_targets`
directory. Unrelated files and files outside that directory are not swept. A
capture held by a permanent OS lock can remain until the lock clears and a
deferred retry or later scan can remove it.

The tuning controls are:

- **Minimum blink** rejects very short validity noise.
- **Slow blink** separates toggle blinks from quick click blinks.
- **Maximum blink** rejects longer tracking loss.
- **Recovery stability** requires valid gaze after the eyes reopen.
- **Double-blink window** controls the maximum gap between slow blinks.
- **Click cooldown** prevents duplicate quick-blink clicks.

Start with the defaults. Increase **Minimum blink** or **Recovery stability**
if tracking noise causes false detections. Increase **Slow blink** if ordinary
blinks are being reserved instead of clicking. Reduce **Maximum blink** if head
movement is mistaken for a blink.

## Recovery Order

If eye tracking stops, use this order and stop as soon as it works again:

1. Check that the 4C is connected and visible in Tobii Experience.
2. Confirm the correct Tobii profile, display setup, and calibration.
3. Confirm both Tobii services are running using the read-only command above.
4. Restart Windows, then test Tobii Experience before starting NC.
5. Confirm NC eye tracking is not **Off**, the Orb is visible, and the correct
   screen is selected.
6. Use **Reconnect Eye Tracking** in the Companion Orb settings.
7. Confirm automatic DLL discovery returns the known-good DLL path.
8. If discovery alone fails, set the NC DLL path explicitly to the known-good
   DLL. Do not copy the DLL into the repository.
9. Only if the Tobii runtime or DLL is missing, reinstall the same Tobii
   Experience `4.124.0.15937` package, restart Windows, and repeat display setup
   and calibration.

Because Tobii Experience support for the 4C is a legacy beta, retain the known-
good offline installer and avoid unnecessary driver/runtime upgrades while this
configuration is working.

## Symptom Guide

| Symptom | Check first |
| --- | --- |
| NC reports no Stream Engine DLL | Automatic discovery and the exact DLL path |
| DLL loads but no tracker is found | USB device, Tobii services, and Tobii Experience detection |
| Orb follows the wrong screen | Tobii display setup and NC selected screen |
| Orb position is offset | Repeat display setup and calibration |
| Movement is too jittery | NC smoothing, dwell radius, and dwell duration |
| Orb moves between gaze and a previous drop | Apply Stable Gaze Preset and verify the current X/Y offsets |
| Orb does not move at all | Orb visibility/display mode and eye mode not set to Off or Manual Only |
| Tracking stopped after reinstall | Repeat display setup and calibration; verify version and DLL hash |

## Relevant NeuralCompanion Code

- `addons/companion_orb_overlay/companion_orb/eye_tracking.py` contains DLL
  discovery, the native Stream Engine session, gaze subscription, callback
  processing, smoothing, and dwell policy.
- `addons/companion_orb_overlay/companion_orb/companion_orb_controller.py`
  connects eye tracking to Qt signals, screen mapping, Orb movement, and the
  external Orb runtime.
- `addons/companion_orb_overlay/companion_orb/gaze_radial_menu.py` contains the
  fixed themed radial surface and its one-shot button dwell selector.

Raw gaze samples are used in memory for current targeting. The eye-tracking
provider does not persist a gaze history or write raw gaze coordinates to a log.

## Official References

- [Tobii 4C and 4L Stream Engine development guidance](https://developer.tobii.com/how-to-get-started-with-developing-software-for-the-eye-tracker-with-the-pdk/)
- [Tobii Eye Tracker 4C setup](https://help.tobii.com/hc/en-us/articles/115003827934-Get-started)
- [Tobii display setup](https://help.tobii.com/hc/en-us/articles/360003101733-How-to-do-a-display-setup)
- [Tobii Experience beta for Eye Tracker 4C](https://help.tobii.com/hc/en-us/articles/4402879502993-Eye-Tracker-4C-joins-the-Tobii-Experience-family-with-a-new-beta)
- [Tobii Experience 4C beta release notes](https://help.tobii.com/hc/en-us/articles/4402880067857-Tobii-Experience-BETA-ONLY-for-Eye-Tracker-4C-Release-notes)
- [Tobii Pro SDK scope](https://developer.tobii.com/tobii-pro-sdk/)
