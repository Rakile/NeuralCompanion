# Addon State And Presets

Addon state is split into two related flows:

- Session state remembers what NC should restore when the app restarts.
- Preset state remembers what should change when the user explicitly saves or loads a preset.

The native desktop has separate session and preset stores. Preserve their
existing formats and ownership; changing UI technology does not authorize a
state-key migration. Start with the [native quickstart](addon_quickstart.md).

## Saved Session Namespaces

Individual addon settings must not be saved directly at the root of
`qt_session.json`. Use a stable top-level group, such as `ditto`, or an explicitly
owned subtree of a shared section such as `tts_runtime`. This keeps the file
readable and separates settings belonging to different addons. Prefixing an
individual key is not a substitute for grouping it.

Declare the namespace, canonical paths and ownership in
`core/session_persistence_contract.py`. Legacy flat exports may remain at the
addon API boundary for compatibility, but the host must normalize them into
the declared group before writing. An import must read its own saved group and
validate values through its owner. When migrating an existing layout, retain
legacy reads, preserve disabled-addon data, and remove old root aliases on save.
Do not change preset or avatar-package formats as a side effect.

## Lifecycle Methods

Every addon may implement these methods:

```python
def export_session_state(self):
    return {}

def import_session_state(self, session):
    return None

def export_preset_state(self):
    return {}

def import_preset_state(self, preset):
    return None
```

Use stable, addon-prefixed keys such as `clipboard_source_auto_attach_next_user_turn`. Do not reuse generic names like `enabled`, `mode`, or `model`.

## The Important Rule

Session state should remember at least as much user-configurable state as preset state.

If preset state contains a key that session state does not restore, NC can start with a value that differs from the active preset even though the user did nothing after launch. That creates false dirty states.

For most preset-owned addon settings, this is the safest pattern:

```python
def export_session_state(self):
    return {
        "my_addon_enabled": bool(self.enabled),
        "my_addon_prompt": str(self.prompt or ""),
    }

def export_preset_state(self):
    return self.export_session_state()

def import_session_state(self, session):
    payload = dict(session or {})
    if "my_addon_enabled" in payload:
        self.enabled = bool(payload["my_addon_enabled"])
    if "my_addon_prompt" in payload:
        self.prompt = str(payload["my_addon_prompt"] or "")
    # Notify the owning native adapter through its existing refresh path.

def import_preset_state(self, preset):
    return self.import_session_state(preset)
```

## When Not To Save To Presets

Do not export preset state for addon settings that are global, machine-specific, or workflow-specific rather than persona/preset-specific.

Good examples of session-only state:

- Addon enabled/disabled registry state.
- Hotkey bindings.
- Chat session player state.
- Host-owned runtime wiring such as input mode, input role, stream mode and
  chat provider/model. Check each addon export separately: this is not a promise
  that every runtime-related field is excluded from existing presets.
- Tool paths such as a local Python interpreter.
- Preprocess/authoring utility settings.
- Temporary browsing or generated-history UI state.

For new session-only addon settings, return `{}` from `export_preset_state()`.
Do not silently remove an already-shipped preset key during a UI migration.
For example, the tested Visual Reply addon exports its `_SESSION_KEYS` subset
from both session and preset hooks, while Gemini TTS Preview exports no preset
state. Check the owning implementation before claiming a setting is session-only.

## Dirty State

For addon-owned setting changes, the current named notification port is:

```python
self.context.capabilities.shell_session.notify_settings_changed()
```

Native adapters also use host persistence callbacks and emit their `changed`
signal after accepted mutations. See
[AddonSessionNativeAdapter](../ui/qml_bridge/adapters/addon_session.py) and its
registration in [application_bridge.py](../ui/qml_bridge/application_bridge.py).
The native addon host does not write a session from its legacy `save_session()`
placeholder; do not assume a shell notification alone proves disk persistence.

## Import Safety

Import methods should be tolerant:

- Accept missing keys.
- Preserve existing values when a key is absent.
- Normalize old payloads when practical.
- Avoid throwing if a user has an older preset.
- Refresh the owning native adapter after applying imported values; do not
  revive widget binding to restore state.

## Storage Service

Use `context.storage` for addon-owned files that should live outside presets and sessions:

```python
path = context.storage.write_json("state.json", {"seen": True})
payload = context.storage.read_json("state.json")
```

Declare `storage.read` or `storage.write` in `addon.json` when using those methods.

## Native session and preset contracts

- [NativeSessionStore](../ui/qml_bridge/native_session.py) canonicalizes session
  contributions through existing schemas and writes the session atomically.
- [Session persistence policy](../core/session_persistence_contract.py) defines
  field ownership, restore phases and credential sanitization. Some existing
  provider credential leaves are explicitly allowlisted for local session
  compatibility; that is not a blanket permission to persist new secrets.
- [NativePresetStore](../ui/qml_bridge/native_presets.py) retains the established
  flat preset format. It combines its explicit host config keys with addon
  `export_preset_state()` values, and passes loaded preset data to addon imports.
- [AddonManager](../core/addons/manager.py) owns addon session contributions and
  preset hook dispatch. Keep exports plain, JSON-compatible and narrowly owned.

Credentials, tokens, local caches and generated media must not be added to new
portable preset exports. Do not reuse a private session payload as a preset or
UI snapshot. Preserve the existing exact credential compatibility paths and
provider private/public frozen-request separation instead of broadening a
serializer's allowlist. The native session's policy does not make arbitrary
addon preset exports automatically safe to share.

Verify restart/restore and preset save/load separately. Confirm absent-key
imports, addon-disabled behavior, migration of established keys, and that new
secret values are absent from presets, logs and public snapshots.
