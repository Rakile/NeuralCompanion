# Addons

Most Neural Companion capabilities are provided by addons under:

```text
addons/
```

Addon categories include:

- chat providers
- TTS backends
- avatar providers
- sensory sources
- supervisors
- workspace tools

## Disabling Addons

Addons are intended to fail safely when disabled or unavailable. If an addon is
disabled, related UI panels or runtime features should disappear or become
inactive without preventing the app from starting.

## User Data

Addon settings may be reflected in presets or local session state. Avoid
committing local runtime/session files.

## Developer Docs

Developer-facing addon documentation lives in the main `docs/` folder:

- `docs/addon_lego_box_contract.md`
- `docs/addon_capability_contracts.md`
- `docs/addon_state_and_presets.md`
- `docs/chat_provider_addons.md`
- `docs/vision_source_addons.md`
- `docs/vision_supervisor_addons.md`
- `docs/visual_reply_addons.md`
