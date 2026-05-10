# Addon Compatibility Shim Register

This document classifies the compatibility shims left after the addon
transition. It is intentionally conservative: shims should remain unless their
removal condition is met and the related presets, sessions, UI files, or
external callers have a migration path.

## Status Labels

- Permanent: keep indefinitely as public compatibility.
- Long-lived: keep until a specific external or data-compatibility migration is
  completed.
- Cleanup candidate: safe to remove only after direct call sites are migrated
  and smoke/runtime checks prove the replacement path.
- Internal alias: not public API, but retained to avoid broad churn in old host
  naming.

## Permanent Shims

These names are user-data or external-contract surfaces. Do not rename them
without an explicit migration.

| Shim | Location | Reason |
| --- | --- | --- |
| `musetalk_*` runtime config keys | addon manifests, `engine.py`, presets/sessions | Existing presets, sessions, env overrides, and UI object bindings expect these keys. |
| `vam_*` runtime config keys | addon manifests, `engine.py`, `core.runtime_paths` callers | Existing VaM configs and env overrides expect these keys. |
| `visual_reply_*` runtime config keys | `addons/visual_reply/addon.json`, engine/UI runtime | Existing sessions and presets store Visual Reply settings under these keys. |
| TTS backend IDs `chatterbox`, `pockettts`, `gemini_tts_preview` | TTS addon manifests, `core.tts_runtime`, UI runtime | Presets and runtime settings store backend IDs directly. |
| `/get-musetalk-preview` | `core/expression_api.py`, legacy `app.py` | External browser/overlay clients may still poll the old MuseTalk endpoint. It aliases the generic avatar preview route. |
| Designer object names such as `musetalk_tab`, `musetalk_tabs`, `vam_tab`, `tts_chatterbox_tab`, `tts_pockettts_tab`, and Visual Reply widget names | `main.ui`, addon `.ui` files, `ui/validation.py`, UI runtime | Qt Designer files, stylesheets, session restore, validation, and mirror bindings rely on these object names. |

## Long-Lived Shims

These are not ideal new extension points, but they protect old import paths or
state names while delegating lazily to addon-owned modules.

| Shim | Location | Replacement for new code | Removal condition |
| --- | --- | --- | --- |
| `shared_state.py` MuseTalk and Visual Reply state functions/attributes | `shared_state.py` | Addon capabilities or addon-owned state modules | Only after external scripts and old runtime callers no longer import `shared_state` for avatar preview or Visual Reply state. |
| MuseTalk state proxy | `engine.py` | `nc.musetalk_avatar` capabilities | Only after engine no longer needs legacy `musetalk_state` attribute-style access and external extension points do not depend on it. |
| MuseTalk and Visual Reply state proxies | `ui/runtime/qt_app_runtime_namespace.py` | Runtime services/capabilities | Only after the compatibility namespace stops exporting those old state names to `qt_app.py` era code. |
| `core.musetalk_preview_runtime` | `core/musetalk_preview_runtime.py` | MuseTalk preview capabilities on `nc.musetalk_avatar` | Only after internal and external imports of `core.musetalk_preview_runtime` are gone. |
| VaM path helper facade | `core/runtime_paths.py` | VaM addon `runtime.vam_config` and addon-owned path helpers | Keep while `core.runtime_paths` remains the stable place for startup/path normalization. |
| `ui.runtime.engine_access` re-export | `ui/runtime/engine_access.py` | `core.engine_access` | Keep while UI runtime modules still import the old UI-local facade. This is not addon-specific, but it is part of the same compatibility layer. |

## Static Boundary Allow-List

`tools/addon_smoke.py` treats these addon module references as intentional
compatibility shims. Keep this list in sync with
`ALLOWED_ADDON_MODULE_REFERENCES`; the smoke helper fails if either the file or
module reference is undocumented here.

| File | Allowed addon module reference |
| --- | --- |
| `core/musetalk_preview_runtime.py` | `addons.musetalk_avatar.preview_runtime` |
| `core/runtime_paths.py` | `addons.vam_avatar.path_helpers` |
| `engine.py` | `addons.musetalk_avatar.state` |
| `shared_state.py` | `addons.musetalk_avatar.state` |
| `shared_state.py` | `addons.visual_reply.state` |
| `ui/runtime/qt_app_runtime_namespace.py` | `addons.musetalk_avatar.state` |
| `ui/runtime/qt_app_runtime_namespace.py` | `addons.visual_reply.state` |

## Cleanup Candidates

These can be removed later, but only after their call sites are migrated to
manifest UI entries or direct addon capability routing.

| Shim | Location | Preferred replacement |
| --- | --- | --- |
| `legacy.build_utility_buttons` | MuseTalk addon capability used by backend compatibility builders | Manifest `ui` entries plus `real_ui.*` bindings. |
| `legacy.build_runtime_widgets` | MuseTalk, VaM, and Visual Reply addon capabilities | Designer-backed addon UI and `real_ui.bind_runtime_controls`. |
| `legacy.build_utility_button` and `legacy.build_settings_tab` | Visual Reply addon capabilities | Visual Reply dock/settings manifest UI and `real_ui.*` capabilities. |
| Bootstrap addon entrypoint loading before the full manager exists | `ui/runtime/backend_system_shaping_builders.py` | Normal initialized `AddonManager` capability calls. |
| Legacy dock helpers | `ui/runtime/legacy_dock_titles.py`, `ui/runtime/legacy_workspace_docks.py` | Real UI dock ownership and addon manifest dock metadata. |

## Retired Cleanup Shims

These cleanup candidates have already been removed after internal call sites
were migrated or confirmed absent.

| Removed shim | Former location | Replacement |
| --- | --- | --- |
| `ui.panels.visual_reply_panel` | `ui/panels/visual_reply_panel.py` | Visual Reply capability routing and addon-owned panel classes. |
| `ui.panels.musetalk_preview_panel` | `ui/panels/musetalk_preview_panel.py` | MuseTalk capability routing and addon-owned preview panel classes. |
| `ui.panels.hand_doctor_dialog` | `ui/panels/hand_doctor_dialog.py` | VSeeFace capability routing and addon-owned dialog classes. |
| `_mount_musetalk_addon_tabs` | `ui/runtime/backend_addon_tab_mounts.py` | `_mount_avatar_tools_addon_tabs`. |

## Internal Aliases

These names are kept to avoid risky broad churn even though the conceptual model
has moved to generic addon terms.

| Alias | Preferred concept |
| --- | --- |
| `musetalk_tabs` mount target | `avatar_tools` addon UI area |
| `musetalk_*focus*` method names | avatar preview/focus controls |
| `MUSE_*` preview constants/state fields | avatar preview state |
| `visual_reply_panel_legacy` | replaced backend placeholder after real UI surface redirection |

## Removal Rules

Before removing or renaming a shim:

- Search runtime code, `main.ui`, addon `.ui` files, docs/templates, and known
  external bridge examples.
- Confirm `tools/addon_smoke.py` passes with static-boundary checks enabled.
- Run at least the addon-disabled permutations for the affected addon category.
- For user-data keys, add a migration before changing names.
- For HTTP routes or public imports, keep the old entrypoint as an alias for at
  least one release after the new entrypoint exists.
- Do not add new behavior to compatibility shims. New behavior belongs in the
  owning addon or in a generic host service/capability.
