# Public Release Checklist

Use this checklist before tagging or publishing a public release.

## Repository Hygiene

- Run `python tools/release_preflight.py` in the sync/release checkout.
- Run `python tools/addon_smoke.py` in the sync/release checkout.
- Confirm `git status --short` is clean.
- Confirm no model weights, voice samples, avatar packs, frame caches, generated images, logs, or session files are staged.
- Keep demo avatar packs outside the main repo, in `Rakile/NeuralCompanion-AvatarPacks` release assets.
- Keep `avatar_packs/` and `voices/` as placeholder folders only in the main repo.
- Confirm the developer-folder runtime-tested changes have been synced to the release checkout before tagging.

## Release-Candidate Gate

- Finish manual runtime testing for any developer-folder change that touches startup, Qt UI, addon lifecycle, audio, STT/TTS, avatar runtime, Visual Reply, or session restore.
- After manual runtime approval, sync only the intended touched files into the release checkout.
- Re-run `python tools/release_preflight.py` and `python tools/addon_smoke.py` after sync.
- Commit a cohesive release-candidate batch.
- Push the release branch and verify the remote contains the final commit.

## Minimal Smoke Test

- Start the app with the legacy UI: `py qt_app.py`.
- Start the app with the Designer UI: `py qt_app.py --ui-real main.ui`.
- Load the `DryRun_MuseTalk` preset and confirm the app can initialize with Avatar Engine `None`.
- Load the `Tutorial_Persona` preset and confirm the first-run tutorial can start.
- Verify Chat Runtime can select provider/model and save/reload a preset.
- Verify TTS Runtime can select a backend and save/reload non-secret settings.

## Addon-Disabled Smoke Test

- Disable MuseTalk and confirm the app starts, session restore does not crash, and non-MuseTalk avatar options remain usable.
- Disable VaM and confirm the app starts, session restore does not crash, and VaM controls/surfaces are hidden or inert.
- Disable Visual Reply and confirm the app starts, Visual Reply dock/buttons are hidden or inert, and Audio Story still opens.
- Disable Audio Story Mode and confirm the app starts with the rest of the Visuals surfaces intact.
- Disable the `avatar` category and confirm the app starts with no avatar-provider crash.
- Disable the `visuals` category and confirm the app starts with no Visual Reply or Audio Story crash.

## MuseTalk Smoke Test

- Confirm MuseTalk model weights are installed locally, not committed.
- Confirm at least one local avatar pack exists under `avatar_packs/<pack_id>/`.
- Confirm the public demo pack install path in `docs/avatar_packs.md` matches the current external release.
- Confirm selected avatar pack default resolves to the intended pack-local variant.
- Run MuseTalk with one short reply and verify preview playback, shutdown, and VRAM release.
- If using startup frame cache, confirm `.npy` or `.npz` files remain ignored.

## Asset And Rights Check

- Review `docs/third_party_and_assets.md`.
- Do not ship voice samples unless rights and consent are clear.
- Do not ship generated avatar/video assets in the main repo.
- Document any demo asset source, license, and usage limits wherever that asset is distributed.
- Keep paid or Patreon-only addon packages outside the main repo unless intentionally released.

## Documentation Pass

- Check `README.md`, `docs/install.md`, `docs/troubleshooting.md`, and `docs/known_limitations.md`.
- Draft release notes from `docs/release_notes_template.md`.
- Ensure Discord/community links are updated before public announcement.
- Ensure addon docs explain that session state may contain secrets, while presets should not.

## Tag And Publish

- Tag only after the sync checkout is clean and both release preflight helpers pass.
- Use a conservative release label for the first public build, such as `v0.1.0-rc1` or `v0.1.0-beta`.
- Attach large demo avatar packs only to the external avatar-pack repository release, not to the main repo.
- Include known limitations, required external installs, and asset/voice rights notes in the release notes.
