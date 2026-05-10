# Addon Lego Box Contract

This document captures the post-transition addon boundary. It is intentionally
short: use it as a checklist when moving new behavior into addons.

For the concrete capability names and payload conventions used by the runtime,
see `docs/addon_capability_contracts.md`.

## Host Responsibilities

- Discover, load, initialize, and unload addons through `core.addons.manager`.
- Provide stable host services through `core.addons.qt_host_services`.
- Route addon-owned UI and runtime requests through manifest contributions,
  addon capabilities, or service capabilities.
- Keep compatibility wrappers for existing presets, sessions, UI object names,
  and external HTTP routes.

## Addon Responsibilities

- Own addon-specific runtime state, parsing, UI bridges, and provider defaults.
- Register services in `addon.json` instead of requiring static host imports.
- Fail safely when disabled, unavailable, or partially configured.
- Preserve public config keys unless a migration is explicitly added.

## Compatibility Shims

The following names are intentionally still visible because sessions, presets,
UI files, or external callers depend on them:

- `musetalk_*` runtime config keys.
- `vam_*` runtime config keys.
- Designer object names such as `musetalk_tabs`.
- `/get-musetalk-preview`, which aliases `/get-avatar-preview`.
- Core facades such as `core.musetalk_preview_runtime` and VaM helpers in
  `core.runtime_paths`.

Compatibility shims should delegate lazily to addon-owned modules and should not
grow new behavior.

## Preferred Patterns

- Use `AddonManager.invoke_service_capability(...)` for provider-specific host
  requests.
- Use `AddonManager.invoke_addon_capability(...)` for known addon IDs.
- Use manifest `ui` entries for tab/panel ownership.
- Use generic host terms in new code, such as `avatar_tools` and
  `avatar_preview_state_module`.
- Keep legacy names only as aliases where removing them would break user data or
  existing UI files.
