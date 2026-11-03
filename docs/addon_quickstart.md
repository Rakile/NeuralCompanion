# Addon Quickstart

The production desktop uses native QML. Addon runtime behavior belongs in the
addon; its settings are presented by typed native adapters. `main.ui`, Designer
loaders, and the QWidget desktop are removed from the tested native checkout.
The old [templates](templates/README.md) are reference material, not current
production scaffolds.

## Choose a current reference

| Goal | Runtime reference | Presentation / contract reference |
| --- | --- | --- |
| Chat provider | [Claude entry point](../addons/claude_provider/main.py) | [Chat provider contract](chat_provider_addons.md) |
| Sensory source | [Mock Heart Rate entry point](../addons/mock_heart_rate/main.py) | [Small native adapter](../ui/qml_bridge/adapters/mock_heart_rate.py), [source guide](vision_source_addons.md) |
| Behavior for a source | [Screen Supervisor entry point](../addons/screen_supervisor/main.py) | [Shared supervisor runtime](../core/addons/sensory_supervisor.py), [supervisor guide](vision_supervisor_addons.md) |
| Settings / actions | [Hotkeys entry point](../addons/hotkeys/main.py) | [Hotkeys adapter](../ui/qml_bridge/adapters/hotkeys.py) |
| Visual Reply integration | [Visual Reply entry point](../addons/visual_reply/main.py) | [Visual Reply guide](visual_reply_addons.md) |
| MCP consumer | [Chat MCP Tools entry point](../addons/chat_mcp_tools/main.py) | [MCP capability contract](addon_capability_contracts.md), [user setup](addons/mcp.md) |
| TTS / avatar runtime | Closest first-party addon in `addons/` | Its matching adapter under `ui/qml_bridge/adapters/` and existing runtime tests |

Start from the smallest relevant implementation. TTS, audio, avatar, model
startup, Qt dispatch, and shutdown require their existing ownership/lifecycle
patterns; a generic settings example does not establish a new runtime contract.

## Manifest and lifecycle

Create `addons/<name>/addon.json` and `main.py`. A headless addon can start with:

```json
{
  "id": "nc.my_addon",
  "name": "My Addon",
  "category": "global",
  "version": "0.1.0",
  "entry_point": "main.py",
  "description": "Short user-facing description.",
  "permissions": [],
  "enabled": true
}
```

Use a stable unique manifest ID, stable lowercase provider/source IDs, and
addon-prefixed state keys. See [manifest parsing](../core/addons/manifest.py)
and [BaseAddon](../core/addons/base.py). The minimal entry point is still:

```python
from core.addons.base import BaseAddon


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        context.logger.info("My addon initialized.")

    def shutdown(self):
        return None
```

This only initializes a headless addon. It does not create a settings page,
register a provider, or load a model. Register only the services the addon owns;
unregister them and stop owned work in `shutdown()`.

The manager supplies an `AddonContext`, which exposes a generation-scoped
`AddonHostContext` through `context.host` and named ports through
`context.capabilities`. The implementation is in
[context.py](../core/addons/context.py) and
[runtime/addons.py](../core/runtime/addons.py). Use those finite ports instead of
passing the main window, facade, backend or runtime context into addon calls.

Common named ports are `providers`, `sensory_targets`, `runtime_config`,
`shell_session`, `hotkeys`, and `visual_reply`. They can be unavailable; check
before use and follow the closest addon's failure behavior. The older
`context.get_service("qt.chat_providers")` lookup still exists, but new examples
should follow the named port used by the current addon.

Permissions remain explicit:

| Permission | Addon-context operation |
| --- | --- |
| `ui.tabs` | Register a UI contribution identity |
| `storage.read` / `storage.write` | Read/write addon-owned files through `context.storage` |
| `events.subscribe` / `events.publish` | Use the addon event port |
| `services.register` / `services.consume` | Publish/consume peer services |
| `llm.read`, `tts.read`, `avatar.read` | Read the respective runtime snapshot |

For background work, inspect `execution_lanes` and owner-scoped task/process
handling in the [capability contracts](addon_capability_contracts.md#execution-and-ownership). Keep startup
light; do not introduce an unsupervised worker or a second model/audio runtime.

## Add a native settings surface

Read these together:

- [NativeControl / NativeSurface](../ui/qml_bridge/native_contracts.py): immutable
  descriptions of control IDs, labels, sections, values, choices and metadata.
- [NativeSurfaceAdapter / registry](../ui/qml_bridge/native_registry.py):
  `snapshot()`, `set_value(...)`, `trigger(...)`, optional
  `trigger_with_payload(...)`, and the `changed` signal.
- [AddonSessionNativeAdapter](../ui/qml_bridge/adapters/addon_session.py): a small
  pattern for explicit `runtime.session.export` / `runtime.session.import`
  capabilities and a persistence callback.
- [Application bridge composition](../ui/qml_bridge/application_bridge.py):
  where the shipped adapter instances are registered.

The manifest describes ownership and placement. For example, a native workspace
contribution uses this shape inside its `ui` list:

```json
{
  "id": "my_addon_tab",
  "title": "My Addon",
  "area": "top_level",
  "order": 900,
  "metadata": {"native_qml": true}
}
```

This metadata **does not load an arbitrary adapter module automatically**. The
shipped native surfaces are explicitly composed in the application bridge. A new
UI addon needs an actual adapter, registration in that composition, and routing
to the intended workspace. Match the surface ID to the declared UI ID. Review
that integration before assuming a third-party page will appear.

Keep `snapshot()` fast and free of generation, capture, network calls or model
loading. Use finite commands for mutations and keep enabled/busy/error state
truthful. `NativeSurfaceRegistry` dispatches actions according to their execution
metadata; inspect its implementation and the nearest action adapter before
choosing the UI or worker path.

`register_designer_tab(...)` now raises. The old
`register_manifest_designer_tab(...)` method has a compatibility path for native
metadata that registers contribution identity without constructing a Designer
file. That is not support for new `.ui` pages. Do not use the legacy widget
factories or edit `main.ui` to add a native addon.

## State and secrets

Implement session and preset exports deliberately; do not copy session state
wholesale into presets if it contains machine-specific values or credentials.
Session restore and preset loading are different operations. Preserve existing
keys and schemas; tolerate absent keys on import.

For a small preset-owned setting, the current notification port is:

```python
self.context.capabilities.shell_session.notify_settings_changed()
```

Native adapters also receive persistence callbacks from the host. Keep their
snapshot refresh, session save, and preset ownership consistent with the existing
adapter; a legacy shell notification alone is not proof of persistence.

Use `context.storage` for addon-owned files and declare its permissions. Do not
export API keys, tokens, generated media, model weights, or cache paths into
portable presets. Follow [state and presets](addon_state_and_presets.md) and the
existing native session/secret policy instead of inventing a parallel writer.

## Validate before sharing

From the repository root, run the relevant deterministic gates:



The coverage gate checks declared native surfaces, adapters, controls and
bindings. The no-legacy gate checks the removed widget paths and production
imports. Passing documentation checks or one synthetic adapter test does not
prove a provider, microphone, device, or model works.

Test enabled and disabled startup, setting edits, restart/restore, preset
round-trips where applicable, explicit errors, and shutdown. For providers, test
frozen normal-chat requests and cancellation; for audio/avatar code, use its
specific runtime checks. `python qt_app.py` launches the current desktop. The
old `--validate-ui main.ui` workflow belongs to the historical Designer migration.

## Further contracts

- [Chat provider addons](chat_provider_addons.md)
- [Vision source addons](vision_source_addons.md)
- [Vision supervisor addons](vision_supervisor_addons.md)
- [Visual Reply addons](visual_reply_addons.md)
- [State and presets](addon_state_and_presets.md)
- [Capability contracts](addon_capability_contracts.md)
