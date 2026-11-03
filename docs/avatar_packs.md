# Avatar Packs

MuseTalk and Ditto packs keep reusable prepared character media outside the main source repository.
A pack belongs to one avatar engine: MuseTalk and Ditto both use
`avatar_packs/<pack_id>/`, but their contents and manifests are different.
Scenic uses a separate `ScenicPacks/` format.

## Demo packs

The official Echo and Eon **MuseTalk** demos are distributed separately:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks
```

The current demo archives are:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks/releases/download/v0.1.0/neural-companion-avatar-pack-Echo.zip
https://github.com/Rakile/NeuralCompanion-AvatarPacks/releases/download/v0.1.0/neural-companion-avatar-pack-Eon.zip
```

The graphical installer offers them as the default MuseTalk pack set. From the
command line:

```powershell
py -3.11 install_neural_companion.py --avatar-packs --non-interactive
```

These are MuseTalk packs. They do not install the MuseTalk runtime itself; keep
**Isolated MuseTalk runtime** selected in the installer or run
`py -3.11 install_neural_companion.py --musetalk --non-interactive`.

Large pack archives are published as release assets separately from the
application source.

## VSeeFace avatars

VSeeFace loads its VRM avatar in the external application. The supplied VSeeFace
test model is `avatar_packs/VSeeFace/Echo/Echo.vrm`, with its matching NC body
preset at `body_configs/Echo.json`. These files are separate from the downloadable
MuseTalk Echo demo above and do not require MuseTalk or Ditto preprocessing.

See the [VSeeFace provider guide](addons/vseeface.md#start-with-the-echo-test-avatar)
for loading Echo, applying its body preset, receiver settings and speech lip sync.

## MuseTalk packs

Extract a MuseTalk pack so its folder lands here:

```text
avatar_packs/<pack_id>/
```

The demo layout is:

```text
avatar_packs/Echo/manifest.json
avatar_packs/Echo/echo_neutral/
avatar_packs/Echo/echo_angry/
avatar_packs/Echo/echo_sad/
avatar_packs/Eon/manifest.json
avatar_packs/Eon/Eon_neutral/
avatar_packs/Eon/Eon_angry/
avatar_packs/Eon/Eon_sad/
```

A distributed pack normally has `manifest.json` directly inside the pack folder.
It names the pack, its default variant, and its variants. Variant tags supply
reply emotions; the Echo and Eon demos use `neutral`, `angry`, and `sad`.
Prepared variant folders contain MuseTalk's expected `avator_info.json`/frames
data (the spelling is part of the existing format). MuseTalk can also discover a
folder of prepared variant directories without a manifest, but a manifest is the
clearer format to share.

In **Runtime → Runtime Session → Avatar → MuseTalk**, use **Refresh avatar packs**, choose the
**Avatar pack**, and check **Pack default avatar** and its **Pack emotions**.
Preparing a pack does not automatically make it active.

## Ditto packages

Ditto also uses:

```text
avatar_packs/<pack_id>/
```

Its `manifest.json` is marked with `avatar_engine: ditto` and points at prepared
variant folders. Each prepared variant has its own Ditto `avatar.json` and frame
data. Ditto's creator writes this structure; you normally do not need to build it
by hand.

A MuseTalk pack will not appear as a usable Ditto package, and a Ditto package
will not appear in MuseTalk. To move an avatar between engines, prepare it again
with the other creator rather than renaming or copying the folder.

## Scenic packs

See the [Scenic Avatar guide](addons/scenic_avatar.md) for selection, a minimal
manifest example and emotion-image fallbacks.

Scenic uses a different root:

```text
ScenicPacks/<PackName>/
ScenicPacks/<PackName>/scenic_pack.json
ScenicPacks/<PackName>/images/
```

`scenic_pack.json` lists image tags and relative image paths. Use the Scenic
editor or create the pack there, then refresh **Runtime → Runtime Session → Avatar → Scenic**. Do
not place a Scenic pack under `avatar_packs/`.

## Startup caches

MuseTalk can create a local startup cache beside a prepared avatar
(`full_imgs_cache.npy` and a small manifest). The cache trades disk space for
faster later startup. It is optional and should not be distributed in the main
application repository. Enable **Faster avatar startup cache** while preparing
the avatar, or remove the cache with **Clear cache** in the MuseTalk Avatar
Creator after checking the named target.

Ditto preparation and model files are separate from MuseTalk caches. Keep them
inside the package when backing it up.

## Verifying an installation

1. Confirm the top-level folder is the installation's `avatar_packs/` (or
   `ScenicPacks/` for Scenic), not a folder inside the downloaded archive.
2. For a manifest pack, confirm the manifest is directly inside the pack folder
   and is valid JSON.
3. Open the matching runtime page and refresh the pack list.
4. Select the pack and inspect its default asset or preview before activating it.
5. Send one short spoken reply after initialization.

If a pack is missing, check its engine marker, manifest location, and folder
name before editing the manifest. Preserve the complete package rather than
moving individual prepared files.

## Rights

Only distribute avatar media when you have the rights to share it. Record the
pack's source, license, and any usage limits with the pack or its release notes.
Do not redistribute a character's source media, voice, or likeness without the
necessary permission.
