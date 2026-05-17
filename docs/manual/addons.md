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

- [Addon Quickstart](../addon_quickstart.md)
- [Addon Templates](../templates/README.md)
- [Addon Lego Box Contract](../addon_lego_box_contract.md)
- [Addon Capability Contracts](../addon_capability_contracts.md)
- [Addon Designer UI Migration](../addon_designer_ui_migration.md)
- [Addon State And Presets](../addon_state_and_presets.md)
- [Chat Provider Addons](../chat_provider_addons.md)
- [Vision Source Addons](../vision_source_addons.md)
- [Vision Supervisor Addons](../vision_supervisor_addons.md)
- [Visual Reply Addons](../visual_reply_addons.md)
