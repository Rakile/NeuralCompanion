# VSeeFace avatar provider

The VSeeFace provider lets NeuralCompanion (NC) animate a 3D avatar in the external
VSeeFace application. NC sends body, head, eye and facial-expression data through
VMC. The optional NC speech bridge feeds NC's speech into VSeeFace's lip-sync
analyzer while NC remains responsible for audible playback.

Use this guide for initial setup, the Echo test avatar, body presets, persona
emotion tags and bridge maintenance. For other avatar engines, see
[Avatars](../manual/avatars.md).

## What you need

- NC and VSeeFace on the same Windows PC.
- An extracted VSeeFace installation. NC's packaged bridge recognizes the
  inspected **1.13.38c4** and **1.13.38c5** builds; use c5 for this setup.
  Download VSeeFace yourself from its [official download page](https://www.vseeface.icu/#download).
- A compatible avatar loaded inside VSeeFace. Its official download page specifies
  **VRM0**, rather than VRM 1.0. You can start with the supplied Echo files below.
- A working NC chat and text-to-speech provider for testing spoken replies.

Body movement and expressions use VMC. File-based speech lip sync additionally
needs the installed and enabled NC bridge. A bridge installation is separate
from selecting an avatar or loading a body preset.

## Start with the Echo test avatar

If you do not have your own avatar yet, look for these files relative to the NC
folder:

```text
avatar_packs/VSeeFace/Echo/Echo.vrm
body_configs/Echo.json
```

1. In VSeeFace's avatar selection/import screen, open **Echo.vrm**, select it and
   start the avatar.
2. In NC, open **Runtime → Runtime Session → Avatar**, then select **VSeeFace**.
3. Expand **Body**, choose **Echo** in **Body preset**, and click **Load**.
4. Continue with the receiver and bridge setup below.

Choosing the preset name alone does not load it. The VRM file is the avatar's
appearance; `Echo.json` supplies matching body poses, dynamics and hand
calibration. Loading one does not automatically select the other.

This is the **VSeeFace Echo** asset, separate from the Echo MuseTalk demo pack
described in [Avatar packs](../avatar_packs.md). It does not need MuseTalk or
Ditto preprocessing. If an older installation lacks these files, use a copy of
NC containing the supplied Echo assets, or load your own compatible avatar.

## Configure VSeeFace's receiver

Open **General settings** inside **VSeeFace** and find **VMC protocol**. Apply
these settings for NC-controlled movement, expressions and speech lip sync:

| VSeeFace option | Setting | Purpose |
| --- | --- | --- |
| **VMC receiver (disables tracking)** | **On**, port **39539** | Receives NC's VMC messages |
| **Apply VSeeFace tracking** | **On** | Allows VSeeFace's local lip-sync processing |
| **Track face features** | **On** | Enables the face-feature processing path |
| **Track blendshapes** | **On** | Allows the speech mouth shapes to be applied |
| **Send data with VMC protocol** | **Off** | This setup uses VSeeFace as the receiver |
| **Apply expressions** | **Off** | Leaves emotional expression selection to NC |
| **Track eye bones** | **Off** | Leaves eye-bone movement to NC |
| **Track jaw bone** | **Off** | Leaves jaw-bone control outside local tracking |
| **Track head and neck** | **Off** | Leaves head and neck movement to NC |

Start with **Blendshape smoothing** and **Bone smoothing** at minimum. Adjust
them later if you want additional smoothing.

Also enable **Audio lip sync** in VSeeFace's General settings. This is a separate
option from the VMC receiver settings above.

These are settings in VSeeFace itself. Installing the NC bridge does not set
these checkboxes automatically. In particular, **Track blendshapes on** and
**Apply expressions off** allow speech mouth movement and NC's emotional mouth
expressions to work together with the bridge.

## Install and enable the speech bridge

1. In NC's VSeeFace provider settings, expand **Speech lip sync**.
2. Use **Choose VSeeFace folder** to select the extracted folder containing both
   `VSeeFace.exe` and `VSeeFace_Data`.
3. Click **Check setup / refresh status**.
4. Close VSeeFace before an installation, update, repair or removal. Choose the
   offered action and review its destination and confirmation:
   - **Install bridge** installs the packaged loader and NC bridge.
   - **Use installed bridge** adopts a recognized compatible installation when
     no file update is needed.
   - **Update / repair bridge** updates an owned older build or repairs its NC
     folder configuration.
5. Turn on **Enable speech lip sync**.
6. Open VSeeFace again. NC's **Start VSeeFace** button uses the saved folder and
   avoids starting another copy of that installation. It is in the first
   **Provider settings** card, called **Overview** in the addon workspace.
7. Load the avatar in VSeeFace if necessary. Click **Check setup / refresh status**
   again and check for **Bridge ready**.
8. Select **Use this avatar** to make VSeeFace the active NC avatar route, then
   initialize the chat. If the chat was already initialized before enabling the
   bridge or changing its folder, stop and initialize it again.

NC remembers the folder and enable setting. It does not start VSeeFace
automatically when NC opens. Use NC's normal launcher; a prototype launcher or
environment variable is not required.

The setup actions manage the loader and bridge files without replacing the
original VSeeFace EXE or managed game assemblies. VSeeFace remains a separate
application supplied by the user.

### Check a spoken reply

Ask for a short spoken response, then another one. Confirm that:

- Speech is audible through NC's selected output device.
- The avatar lip-syncs successive replies, including replies delivered in chunks.
- Stopping or interrupting NC speech also stops the lip sync.
- Body movement continues and the selected emotional expression is retained.

The bridge's analysis playback is silent; NC supplies the audible speech. This
setup does not require routing NC through a virtual microphone cable.

## Body presets, moods and dynamics

Expand **Body** to choose a body preset and control which emotion you are
editing. Expand **Dynamics** for breathing, sway and eye activity controls.

| Control | Behavior |
| --- | --- |
| **Body preset → Load** | Applies the selected JSON preset, including its saved hand calibration |
| **Save** | Writes the current poses and hand calibration to the selected body preset file |
| **Save As** | Writes a separate named preset under `body_configs/` |
| **Delete** | Deletes the selected preset after confirmation; Default is protected |
| **Body emotion** | Chooses the mood to preview and edit when Live Sync is off |
| **Live Sync off** | Previews the selected body emotion and its facial expression |
| **Live Sync on** | Follows chat emotion changes; pose/dynamics edits target the Neutral profile |

To adjust Echo without replacing its supplied preset, use **Save As** to make
your own named copy. Turn **Live Sync off**, choose a **Body emotion**, then
adjust its pose and dynamics. Repeat for the other moods and save the preset.
Turn **Live Sync on** again when you want the avatar to follow the conversation.

NC remembers current edited settings, Live Sync, the selected body preset and
card visibility across restarts. This session persistence is separate from
**Save / Save As**, which writes the reusable preset JSON. Back up `body_configs/`
if you want to preserve your named presets.

Loading a body preset does not load or switch the VRM inside VSeeFace. When
changing avatars, select the model in VSeeFace and load its matching body preset
in NC.

### Hand Doctor

**Hand Doctor** adjusts the Relaxed and Fist hand-calibration slots:

1. Choose a **Calibration preset**.
2. Click **Load preset to edit** to copy that slot into the debug controls.
3. With **Activate Debug Override** enabled, adjust the Finger and Thumb X/Y/Z
   rotations while watching the avatar.
4. Click **Save calibration preset** to retain those values in the chosen slot.
5. Turn off Debug Override to return to animated hand blending.
6. Use the Body section's **Save / Save As** to include the calibration in a
   reusable body preset file.

## Let the persona trigger facial expressions

VSeeFace supports these NC visual mood tags:

```text
[neutral] [sad] [angry] [happy] [shy] [surprised]
```

The model needs instructions to emit the tags, and **Live Sync must be on** for
chat-driven expressions. See [Persona: avatar mood tags](../manual/personas.md#avatar-mood-tags)
for the copyable instruction block, the current provider-specific override
controls, and the older Technical rules editor.

A persona portrait or generated mood image does not configure a VRM's facial
expressions. VSeeFace uses the loaded avatar's expression blendshapes. Their
visible strength and appearance depend on the avatar.

For a quick test, ask the persona to give a short happy greeting using `[happy]`.
If manual previews work but chat expressions do not, check its actual emitted
tags, active persona rules and Live Sync before changing body settings.

## Hide setup cards after configuration

Each main VSeeFace settings section has **Show / Hide**. Hide **Speech lip sync**
after setup to make Body and Dynamics easier to reach. Hiding a section changes
its visibility, not whether the bridge or avatar is enabled. The choice is saved.

## Update, disable, remove or build the bridge

| Action | When to use it |
| --- | --- |
| **Check setup / refresh status** | Refresh the last checked installation and running bridge status |
| **Update / repair bridge** | Update an owned bridge build or point it at NC after moving the NC folder |
| **Enable speech lip sync off** | Stop lip-sync analysis immediately while NC's audible speech continues |
| **Remove bridge** | Remove the recognized owned bridge/loader files after closing VSeeFace |
| **Open bridge source** | Open the complete included C# source |
| **Self-build instructions** | Open the offline build steps |

Installing or updating requires approval. A conflicting loader or changed owned
file is reported instead of being silently overwritten. Removal preserves
settings, avatars, other plugins and unknown/changed files. Recovery copies of
changed owned files are kept under NC's `runtime/vseeface_bridge_backups/`.

The complete bridge source and build instructions ship with NC at
`addons/vseeface_avatar/bridge_source/`. A verified prebuilt DLL, pinned loader and
third-party notices are in `addons/vseeface_avatar/bridge_payload/`. See
[Bridge source and self-build](../../addons/vseeface_avatar/bridge_source/README.md)
for compiler requirements, the build command and installation of your own build.
Building is optional for normal setup; VSeeFace's assemblies are not bundled.

After updating or replacing VSeeFace itself, check the folder and bridge setup
again. An unrecognized VSeeFace build needs compatibility inspection before the
packaged installer can support it.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Avatar does not move | A model is loaded in VSeeFace; VMC receiver is on at port 39539; VSeeFace is the active NC route; chat was initialized |
| Body moves but there is no lip sync | Enable Audio lip sync, Apply VSeeFace tracking, Track face features and Track blendshapes; check Bridge ready and reinitialize after enabling the bridge |
| Lip sync works but emotions do not | Apply expressions is off; Live Sync is on; the persona emits supported mood tags; the loaded model has the corresponding expression shapes |
| Avatar stays in the manually selected mood | Turn Live Sync on to resume chat-driven expressions |
| Pose changes affect Neutral instead of another mood | Turn Live Sync off before selecting and editing the other Body emotion |
| Preset selection seems to do nothing | Click Load after choosing the preset name |
| Echo is absent | Check the two file paths above; older installations may not include the supplied VSeeFace assets |
| Installed status but no ready bridge | Start the selected VSeeFace installation and refresh status; update a recognized older bridge if offered |
| Bridge refers to another NC folder | Close VSeeFace, check the selected folder and approve Update / repair bridge |
| Speech is silent | Test the NC TTS provider and output device; VSeeFace's bridge analysis is intentionally silent |
| Older bridge stops after the first reply | Close VSeeFace and use the offered Update / repair bridge, then test two successive replies |

**Last checked status** updates when you use the check button. An installed DLL
does not prove that VSeeFace is running. A ready speech bridge also does not
prove that the VMC receiver settings for body movement are correct.

See [Troubleshooting](../troubleshooting.md#vseeface-speech-lip-sync),
[Personas](../manual/personas.md), and the
[official VSeeFace manual](https://www.vseeface.icu/#manual) for related help.
