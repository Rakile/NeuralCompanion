# MuseTalk

MuseTalk renders a prepared talking face locally while NeuralCompanion speaks.
It needs an isolated GPU runtime, downloaded model weights, a compatible prepared
pack, and working text-to-speech. Preparation and chat both use GPU memory, so
they are deliberately separated.

For the other avatar routes and the shared preview, see [Avatars](avatars.md).

## Install the runtime

Use the graphical installer and keep **Isolated MuseTalk runtime** selected, or
run from the installation root:

```powershell
py -3.11 install_neural_companion.py --musetalk --non-interactive
```

The installer creates `MuseTalk/.venv/` and downloads the required MuseTalk
weights when they are missing. Installation can complete without a usable GPU,
so check the reported CUDA/runtime result rather than assuming the main app
environment can render MuseTalk.

## Packs and demo assets

MuseTalk packs belong at:

```text
avatar_packs/<pack_id>/
```

The Echo and Eon demo packs are distributed separately in the
[NeuralCompanion AvatarPacks repository](https://github.com/Rakile/NeuralCompanion-AvatarPacks).

The graphical installer offers the default Echo and Eon packs. From the command
line, install the default pack set with:

```powershell
py -3.11 install_neural_companion.py --avatar-packs --non-interactive
```

A pack must contain a `manifest.json` directly in its folder or the prepared
variant folders must be discoverable by NC. The Echo and Eon demos provide the
`neutral`, `angry`, and `sad` emotion tags. See [Avatar packs](../avatar_packs.md)
for the pack layout and engine differences.

## Prepare an avatar

Avatar creation and mask editing require the chat runtime to be fully stopped.

1. Stop the NC runtime and wait for cleanup to finish.
2. Open **Addons → MuseTalk Avatar Creator**. The workspace title is **MuseTalk
   Avatar Creator**.
3. Choose **New pack** to create a destination, or select **Target avatar pack**
   to add to an existing pack. Use **Refresh packs** if it is not listed.
4. Choose **Choose video**, **Choose still image**, or **Choose frame folder**.
   Review the **Avatar ID** and **Destination** before continuing.
5. Turn off **Continuous Render** for the first test unless you deliberately want
   repeated previews.
6. Select **Render preview**, inspect the source frame, and paint the mouth mask
   if the automatically detected area needs correction. The mask overlay stays
   visible in the editor; the clean image opens in **Avatar Preview**.
7. If an individual frame needs a manual correction, select **Save edited mask
   as override**. The saved frame appears under **Exact-frame edited mask
   overrides**.
8. Select **Preprocess avatar** and confirm the exact destination. Wait for the
   operation stage to finish. For a faster later startup, leave **Faster avatar
   startup cache** enabled unless disk use is a concern.
9. On success, use **Refresh avatars** and confirm that the new entry belongs to
   the intended pack.

Preparing assets does not activate MuseTalk as the chat avatar.

### Mask controls

Left-drag adds mask, right-drag removes it, middle-drag pans, and Alt + mouse
wheel zooms. Mask ranges use source-frame indices, starting at frame 0.

For a changing head angle, set **Range start** and **Range end**, adjust the mask
settings, and use **Add range from current settings**. To change an existing
range, first use **Load** on that saved range, update the settings, then use
**Update**. **Passthrough / no mask** leaves frames untouched. Exact-frame edited
mask overrides handle isolated errors. Test representative frames on both sides
of a range boundary.

Use **Save metadata** to keep the mask settings and **Emotion tags** with the
prepared avatar.

### One frame and one audio test

Leave **Continuous Render: OFF** for the first pass, especially on slower
hardware. After one frame looks right, choose a short file under **Test audio**
and select **Run test**. Inspect the clean result in **Avatar Preview** before
preparing a large frame set.

The first preview loads the dedicated MuseTalk worker. Later previews, edited
mask renders, audio tests, and compatible preprocessing reuse that worker, so
the model is not started repeatedly. Rendering still takes time. Opening the
creator or painting a mask does not load models.

While the worker is loaded, it keeps its GPU memory and exclusive creator
reservation. Leaving the workspace or choosing another addon offers **Unload
MuseTalk** or **Keep loaded**:

- **Unload MuseTalk** waits for active work, then releases the worker.
- **Keep loaded** makes previews faster when you return.
- Dismissing the dialog makes no resource change.

Unfinished fields and the painted mask remain in the editor when you return.
Focus changes and file pickers do not unload the worker. **Initialize NC** and
application shutdown request release.

**Reset chat memory does not release MuseTalk resources.** Turning Live off, pausing
speech, or waiting for the conversation to become idle also does not stop the
chat runtime. Click the header power control while it shows **NC ready** to
stop the session. If cleanup is incomplete, use **Retry cleanup** before
initializing chat or starting another creator job.

The creator reports real operation stages instead of estimating a percentage.
If creator cleanup fails, use **Retry creator cleanup**. There is no force-unlock
action.

## Select and test the finished pack

1. After creator cleanup, open **Runtime → Runtime Session → Avatar → MuseTalk**.
2. Use **Refresh avatar packs**, select **Avatar pack**, and check **Pack default
   avatar**.
3. **Pack emotions** lets you enable optional prepared variants. The base avatar
   stays available.
4. Select **Use this avatar**, initialize the runtime, and request one short
   spoken reply. **Avatar Preview** should show the selected face moving with
   the audio.

In the creator, **Emotion tags** and **Save metadata** associate prepared looks
with reply emotions. **Make default** chooses the base avatar. **Pack emotion
summary** lets you check the mapping before returning to chat. **Enable all
emotions** and **Disable optional emotions** apply to the selected pack.

The optional **Send MuseTalk face mask to Companion Orb** setting in MuseTalk's
**Performance** section routes frames to the external Unreal overlay and
suppresses the normal MuseTalk preview. It requires a working external receiver.
Turn it off to restore normal preview routing.

## Performance

- Use a compatible NVIDIA CUDA GPU. The installer selects a compatible PyTorch
  stack and exposes a manual CUDA-stack override for unusual or missed hardware
  detection.
- The installer selects the CUDA 12.8 stack for detected RTX 50 / Blackwell
  systems. Check its readiness result before troubleshooting inside the app.
- First startup can be slow while models and avatar frames warm up.
- **Render FPS**, **VRAM mode**, and **Loop fade** are on the MuseTalk runtime
  page. Change them after a known-good short reply, not before the first test.
- The **Faster avatar startup cache** created during preparation can improve
  later startup at the cost of disk space.
- **Clear cache** in the creator removes the selected avatar's startup cache
  after confirmation. Check the named target. It does not unload the active
  models.

## Troubleshooting

- **Pack missing:** use **Refresh avatar packs**, confirm `manifest.json` is
  directly in the pack folder, and confirm the folder is a MuseTalk pack.
- **No moving face:** confirm the active route, selected prepared avatar, and
  TTS. Check the runtime status and whether the face-mask routing switch is on.
- **Mouth seams:** compare the clean render in **Avatar Preview**, not the editor
  overlay. Save the intended override or mask metadata and test representative
  range boundaries.
- **Busy or incomplete cleanup:** terminate chat, let creator work finish, and
  use the appropriate cleanup retry. **Reset chat memory** does not free models.
- **Out of memory or slow startup:** finish other creator/GPU jobs, confirm the
  isolated runtime and GPU are ready, and establish one short successful test
  before raising render settings.

## Generated files

Generated MuseTalk data belongs under ignored runtime folders such as:

```text
MuseTalk/runtime/
MuseTalk/results/
```

Do not commit generated frames, videos, model weights, or caches to the main
repository. Keep prepared packs and their rights information together when
distributing or backing them up.

## Delete a package

In **Runtime → Runtime Session → Avatar → MuseTalk**, select the package in the
**Avatar** section and choose **Delete package**. Stop chat or preview and unload
the avatar worker first (MuseTalk workers can be unloaded from **Resources**).
Close an active Creator operation before deleting.

The confirmation names the selected package. **Delete permanently** removes its
managed folder, including prepared avatars, package settings, and source media
stored inside that folder. It cannot be undone. Original media outside the
package folder is preserved. NC blocks deletion while the package is in use or
when another managed package references its files. Cancel leaves it unchanged.

## Manage individual emotions and looks

The Creator shows a visible list of the selected package's prepared entries,
including their thumbnails, reply labels and base marker. Labels are free-form:
`panic`, `Santa Claus` and any other custom labels are supported.

- **Preview** loops the prepared source frames (up to 240 frames), without loading models or generating speech.
- **Redo** prepares it again from the saved original media using current preparation settings.
- **Replace source** selects different media for the same entry. Labels and base role stay unchanged.
- **Delete** asks for named confirmation and permanently removes that entry's managed files from disk.
- **Use as base** chooses the default entry. Choose another base before deleting the current one.

Redo and replacement keep the working version until preparation succeeds; failure
or cancellation keeps it usable. Original source files outside the managed entry
are preserved. Shared or redirected folders cannot be deleted or replaced. Stop
chat before editing. Legacy entries referencing external prepared folders can
still be previewed and used as the base; file mutations require managed entries.

These package labels select prepared source loops. They are separate from
Ditto's fixed set of generated facial expressions.
