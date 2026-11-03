# Scenic Avatar

Scenic is a lightweight avatar route that selects a still image from a tagged
pack. It does not generate lip-sync frames or require MuseTalk/Ditto models.
Speech remains the responsibility of the selected text-to-speech provider.

Create and edit packs with the separate [Scenic Pack Creator](scenic_pack_creator.md).

## Select a pack

1. Enable **Scenic Avatar** in Addons if needed, then restart when requested.
2. Open **Runtime → Runtime Session → Avatar → Scenic**.
3. Choose **Refresh packs**, select a discovered pack, and inspect **Pack
   availability**, the preview, and its image/tag details.
4. Choose **Use this avatar**, initialize NC, and test a short reply.

Selecting a pack and activating the avatar route are separate steps. An
unavailable saved pack is shown as unavailable; selecting its name does not
restore missing files.

Scenic output appears in **Avatar Preview**. With LiquidAI’s **Experimental
progressive audio** enabled, speech can start while LiquidAI is still generating
the chunk, just as with No Avatar. Images follow the emotion of the chunk being
played; preparing a later chunk does not change the displayed image early.

## Pack format

Keep each pack under `ScenicPacks/<pack_id>/`, with `scenic_pack.json` directly
inside its folder. For example:

```text
ScenicPacks/MyScenic/
  scenic_pack.json
  images/neutral.png
  images/happy.png
```

`scenic_pack.json`:

```json
{
  "engine": "Scenic",
  "pack_name": "My Scenic",
  "images": [
    {"tag": "neutral", "image_path": "images/neutral.png"},
    {"tag": "happy", "image_path": "images/happy.png"}
  ]
}
```

Use pack-relative paths and supported PNG, JPG/JPEG, WEBP, or BMP images. Keep
the complete folder together when moving or backing up the pack. Refresh the
catalog after adding it. Use **Scenic Pack Creator** to create packs or edit
images and tags; the Scenic provider settings select and preview them.

Reply emotion tags select corresponding images. When a requested tag has no
matching image, the pack falls back to `neutral`, then its first image. Include
a neutral image and give the persona the [avatar mood tag instructions](../manual/personas.md#avatar-mood-tags).
A still image during speech is expected for Scenic.

## Troubleshooting

- **No packs:** check the exact folder and manifest layout, then Refresh packs.
- **Pack listed but no image:** check its `images` entries and referenced files.
- **Image does not change:** check the reply's mood tag and whether the pack has
  that tag; do not diagnose this as a TTS or MuseTalk problem.
- **No speech:** test the selected TTS provider separately with Avatar **None**.

See [Avatars](../manual/avatars.md) for activation and preview, and
[Avatar packs](../avatar_packs.md) for the other pack formats. The format and
fallback behavior are implemented in [pack_runtime.py](../../addons/scenic_avatar/pack_runtime.py).
