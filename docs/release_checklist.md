# Public Release Checklist

Use this checklist before tagging or publishing a public release.

## Repository Hygiene

- Confirm `git status --short` is clean.
- Confirm no model weights, voice samples, avatar packs, frame caches, generated images, logs, or session files are staged.
- Keep demo avatar packs outside the main repo, for example in a release asset or dedicated asset repository.
- Keep `avatar_packs/` and `voices/` as placeholder folders only in the main repo.

## Minimal Smoke Test

- Start the app with the legacy UI: `py qt_app.py`.
- Start the app with the Designer UI: `py qt_app.py --ui-real main.ui`.
- Load the `DryRun` preset and confirm the app can initialize with Avatar Engine `None`.
- Load the `Tutorial Persona` preset and confirm the first-run tutorial can start.
- Verify Chat Runtime can select provider/model and save/reload a preset.
- Verify TTS Runtime can select a backend and save/reload non-secret settings.

## MuseTalk Smoke Test

- Confirm MuseTalk model weights are installed locally, not committed.
- Confirm at least one local avatar pack exists under `avatar_packs/<pack_id>/`.
- Confirm selected avatar pack default resolves to the intended pack-local variant.
- Run MuseTalk with one short reply and verify preview playback, shutdown, and VRAM release.
- If using startup frame cache, confirm `.npy` or `.npz` files remain ignored.

## Asset And Rights Check

- Do not ship voice samples unless rights and consent are clear.
- Do not ship generated avatar/video assets in the main repo.
- Document any demo asset source, license, and usage limits wherever that asset is distributed.
- Keep paid or Patreon-only addon packages outside the main repo unless intentionally released.

## Documentation Pass

- Check `README.md`, `docs/install.md`, `docs/troubleshooting.md`, and `docs/known_limitations.md`.
- Ensure Discord/community links are updated before public announcement.
- Ensure addon docs explain that session state may contain secrets, while presets should not.
