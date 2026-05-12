# Avatar Packs

Neural Companion keeps avatar media out of the main source repository.

## Demo Packs

Official/demo avatar packs are distributed separately from the main app:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks
```

Large pack archives should be attached to that repository as GitHub Release
assets, not committed directly to git. GitHub regular repository files have a
100 MB hard limit, while MuseTalk packs are usually much larger.

Current Echo demo download:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks/releases/download/v0.1.0/neural-companion-avatar-pack-Echo.zip
```

## Install Location

Download and extract a pack so the folder lands here:

```text
avatar_packs/<pack_id>/
```

For example, the Echo demo pack should become:

```text
avatar_packs/Echo/manifest.json
avatar_packs/Echo/echo_neutral/
avatar_packs/Echo/echo_angry/
avatar_packs/Echo/echo_sad/
```

The default Echo pack provides the `neutral`, `angry`, and `sad` emotion tags.

Then start Neural Companion and select the pack from the MuseTalk avatar pack
dropdown.

## Cache Files

Frame-cache files such as `.npy` or `.npz` are optional local startup caches.
They should not be distributed in the main app repo. Users can let NC create
them locally when `Use .npy startup cache` is enabled.

## Rights

Only distribute avatar packs when you have the rights to share the generated
character media. Document the pack source and any usage limits in the avatar
pack repository or release notes.
