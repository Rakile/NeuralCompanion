# Avatars

Neural Companion can run with several avatar modes:

- `None`
- MuseTalk
- VSeeFace
- VaM

Start with `None` while testing chat and speech. Then enable one avatar engine
at a time.

## VSeeFace

VSeeFace is external software. Neural Companion can send VMC-style avatar
signals to it when configured.

## VaM

VaM integration uses VMC and/or a file bridge through the Neural Companion VaM
bridge/plugin. VaM itself is not included in the repository.

## MuseTalk

MuseTalk is the heaviest avatar mode. It needs an isolated runtime, model
weights, and prepared avatar packs. See [MuseTalk](musetalk.md).

## Avatar Assets

Avatar packs belong in:

```text
avatar_packs/<pack_id>/
```

The main repository intentionally does not include large avatar media.
