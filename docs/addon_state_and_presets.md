# Addon State And Presets

Addon state is split into two related flows:

- Session state remembers what NC should restore when the app restarts.
- Preset state remembers what should change when the user explicitly saves or loads a preset.

This distinction matters because NC compares the current runtime state with the active preset to decide whether `Save` and `Save As` should show as dirty.

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
    self._refresh_ui()

def import_preset_state(self, preset):
    return self.import_session_state(preset)
```

## When Not To Save To Presets

Do not export preset state for addon settings that are global, machine-specific, or workflow-specific rather than persona/preset-specific.

Good examples of session-only state:

- Addon enabled/disabled registry state.
- Hotkey bindings.
- Chat session player state.
- Runtime wiring choices such as input mode, input role, stream mode,
  chat provider/model, TTS backend/voice, and Visual Reply provider/model.
- Tool paths such as a local Python interpreter.
- Preprocess/authoring utility settings.
- Temporary browsing or generated-history UI state.

For these, return `{}` from `export_preset_state()`.

## Dirty State

If an addon setting should affect preset dirty state, call the shell notifier when it changes:

```python
shell = self.context.get_service("qt.shell")
if shell is not None:
    shell.notify_settings_changed()
```

This lets NC save the session and refresh the preset dirty border.

## Import Safety

Import methods should be tolerant:

- Accept missing keys.
- Preserve existing values when a key is absent.
- Normalize old payloads when practical.
- Avoid throwing if a user has an older preset.
- Refresh addon UI after applying imported values.

## Storage Service

Use `context.storage` for addon-owned files that should live outside presets and sessions:

```python
path = context.storage.write_json("state.json", {"seen": True})
payload = context.storage.read_json("state.json")
```

Declare `storage.read` or `storage.write` in `addon.json` when using those methods.
