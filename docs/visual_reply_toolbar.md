# Visual Reply toolbar

Open **Visual Reply** from the top navigation to inspect generated images and
reuse images from the local Visual Reply history.

The toolbar shows the current status plus **Tools**, **Float**, and **Clear**.
When the window is wide enough, it can also show **Previous**, **Load Image**,
**Next**, **Load Current Story Image**, **Use Current Image Style**, **Caption**,
**Delete Image**, and **Delete All** as individual buttons.

## Expand or collapse the tools

Open **Tools** and choose **Show tools as buttons**. The preference is remembered
across restarts.

Even when the preference is on, a narrow window may keep the buttons in the
**Tools** menu so they remain usable. **Float** opens the workspace in its own
window; it does not duplicate or move the stored images.

## Browse and load images

- **Previous** and **Next** step through supported images in the history folder,
  ordered by modification time. They are disabled when history is empty.
- **Load Image** opens a file picker for PNG, JPEG, WebP, or BMP images. It first
  prepares the history folder, so the picker opens there by default.
- Loading an image from outside the history folder displays it but does not copy
  it into history.
- **Clear** resets the displayed selection. It does not delete the file.

The status area reports when an image, history entry, or file operation is
unavailable. A failed load leaves the previous selection in place.

## Caption and image actions

**Caption** edits the caption shown below the current image. The caption is
display-state only; it does not rewrite image metadata or embed text into the
file. Loading another image may replace it with that image's embedded caption or
leave it blank.

**Delete Image** permanently removes the displayed image file after confirmation.
This also applies to a file loaded from outside the history folder. If the
deleted file was part of history, the workspace advances to the next available
image.

**Delete All** permanently removes supported image files directly inside the
history folder. It does not remove nested folders, symbolic links, or unrelated
file types. Export or copy anything you want to keep before confirming either
delete action. Delete All cannot be undone.

## Audio Story actions

**Load Current Story Image** asks Audio Story Mode for the illustration at its
current playback position and displays it in Visual Reply. If that scene has no
cached image yet, Audio Story can start the generation request. It requires a
loaded story project.

**Use Current Image Style** refreshes the current Audio Story's visual style and
restarts its story-image generation from the current playback position using the
current style settings. It does not reverse-engineer a style from an arbitrary
image loaded into Visual Reply.

These actions remain owned by Audio Story Mode. If no story is loaded, they
report that the action is unavailable rather than changing the current image.

## Related guides

- [Visual Reply and sensory awareness](manual/visual-reply-and-sensory.md)
- [ComfyUI setup](visual_reply_comfyui.md)
- [Appearance consistency and freedom](visual-reply-appearance-freedom.md)
