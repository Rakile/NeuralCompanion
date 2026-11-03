# Scenic Pack Creator

Create lightweight image packs for the **Scenic Avatar** provider. Unlike MuseTalk
and Ditto, Scenic displays still images selected by reply tags; it does not
prepare lip-sync animation or need avatar AI models.

## Create a pack

1. Open **Scenic Pack Creator** in the sidebar. If it is disabled, enable it in
   **Addons** and restart NC when requested.
2. Stop the chat engine before editing, then choose **New pack** and enter a name.
3. Enter an **Image tag**, such as `neutral`, `happy`, `panic` or `Santa Claus`.
   Tags become lowercase and spaces become underscores (`santa_claus`).
4. Choose **Add / replace image** and select a PNG, JPG/JPEG, WEBP or BMP file.
   NC copies it into the pack; your original file is kept.
5. Repeat for the other images. Image and tag changes save automatically.

Include a `neutral` image for a predictable fallback. You can use any supported
single-word tag; the creator does not restrict you to a fixed emotion list.
Tags that are also speech reactions, such as `laugh`, are best avoided because
NC treats those as voice controls.

## Edit and share

Open an existing pack in the pack list, then select an image to preview it.
Change **Image tag** and choose **Rename selected tag** to rename that entry.
Adding an image to an existing tag asks before replacing its image. **Remove
image** asks before permanently removing the selected entry and its managed
image; images still used by another tag and source files outside the pack are
preserved.

To change the name shown in the list, edit **Pack display name** and choose
**Save name**. The folder and pack ID stay unchanged. **Open pack folder** opens
the complete package for copying or sharing. Keep `scenic_pack.json` and the
`images` folder together. Use **Refresh** after changing packs outside NC.

If NC reports that a pack changed elsewhere, refresh it and review the image
before trying the edit again. A confirmation opened before that change cannot
overwrite the newer version.

## Use it in chat

Choose **Select for Scenic** to save this pack as Scenic's selected pack. This
button does not activate or switch avatar engines. Open **Runtime → Avatar →
Scenic**, choose **Use this avatar**, then initialize NC. The default visual tag
rules use the selected pack's tags; custom provider rules and Persona overrides
remain yours to manage.

A reply tag such as `[happy]` selects the matching image. If the tag is absent
from the pack, Scenic falls back to `neutral`, then the first image.

See [Scenic Avatar](scenic_avatar.md) for provider setup and the portable pack
format.
