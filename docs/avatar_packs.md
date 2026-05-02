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

Current Echos demo download:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks/releases/latest/download/Echos.7z
```

## Install Location

Download and extract a pack so the folder lands here:

```text
avatar_packs/<pack_id>/
```

For example, the Echos demo pack should become:

```text
avatar_packs/Echos/manifest.json
avatar_packs/Echos/echo_neutral/
avatar_packs/Echos/echo_happy/
avatar_packs/Echos/echo_angry/
```

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
