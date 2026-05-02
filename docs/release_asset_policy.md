# Release Asset Policy

Neural Companion keeps the main repository focused on source code, manifests,
documentation, and small UI assets.

## Not Stored In The Main Repo

Do not commit these to the main repository:

- model weights or checkpoints
- prepared MuseTalk avatar packs
- generated `.npy`, `.npz`, frame caches, rendered chunks, or videos
- voice reference samples
- user screenshots, clipboard captures, visual replies, or story outputs
- logs, runtime snapshots, temporary files, or local session files
- bundled third-party applications or local virtual environments

## Avatar Packs

MuseTalk avatar packs belong in:

```text
avatar_packs/<pack_id>/
```

Demo avatar packs should be distributed outside the main repo. The intended
demo-pack repository is:

```text
https://github.com/Rakile/NeuralCompanion-AvatarPacks
```

Large archives should be attached as GitHub Release assets rather than
committed directly to git.

## Voice Samples

Voice reference files belong in:

```text
voices/
```

They are ignored by Git by default. Only distribute voice samples when you have
clear rights and consent to do so.

## Generated Runtime Data

Runtime outputs belong under:

```text
runtime/
MuseTalk/runtime/
```

These folders are ignored and can be safely cleaned when troubleshooting.

Diagnostic file logs are opt-in:

- `NC_MUSETALK_WORKER_LOG=1`
- `NC_MUSETALK_PREVIEW_LOG=1`
