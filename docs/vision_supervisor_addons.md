# Vision Supervisor Addons

Vision supervisor addons add behavior rules to an existing Vision source. They usually do not capture images themselves. Instead, they register prompt contributors that teach the hidden Vision loop how to interpret a source.

Existing examples include Screen Supervisor, Webcam Supervisor, Clipboard
Supervisor, and Heart Rate Behavior. Start with the
[native addon quickstart](addon_quickstart.md). The
[Screen Supervisor entry point](../addons/screen_supervisor/main.py) uses
[the shared SensorySupervisorAddon runtime](../core/addons/sensory_supervisor.py).

## Concept

A source addon answers: "What sensory input is available?"

A supervisor addon answers: "What should NC do when that input shows a meaningful pattern?"

For example:

- Screen Source captures the monitor.
- Screen Supervisor adds rules for what screen patterns should trigger proactive speech.

## Register A Prompt Contributor

Use `context.capabilities.sensory_targets.register_prompt_contributor(...)`
(the port is backed by `qt.sensory`):

```python
sensory_service = context.capabilities.sensory_targets
if sensory_service is None:
    context.logger.warning("Sensory capability is unavailable.")
    return None
sensory_service.register_prompt_contributor(
    contributor_id="nc.my_screen_supervisor.behavior",
    source_id="screen",
    label="My Screen Supervisor",
    prompt=self._render_prompt(),
    order=220,
    metadata={"type": "behavior_rule"},
)
```

Use a stable `contributor_id`. If the prompt changes, call `register_prompt_contributor` again with the same id to replace the old contribution.

Always unregister in `shutdown()`:

```python
sensory_service.unregister_prompt_contributor("nc.my_screen_supervisor.behavior")
```

## Native behavior settings

The supervisor's manifest `vision_source` contribution identifies its source
family through `parent_tab_id`. Current behavior controls are typed native
surfaces composed by [supervisors.py](../ui/qml_bridge/adapters/supervisors.py),
not Python-built child widgets. Inspect the
[Screen Supervisor manifest](../addons/screen_supervisor/addon.json) alongside
that adapter and the shared runtime before adding a new family.

The retained `ui.tab_enabled` capability carries enabled state as plain data; its
name does not mean a QWidget is constructed. `SensorySupervisorRuntime` also
exposes `runtime.supervisor.snapshot` and `runtime.supervisor.reset_prompt`.
The generic native session adapter uses `runtime.session.export` / `.import`.
Keep these existing names stable.

## Checkable Child State

Support this capability when the tab can be enabled or disabled:

```python
def invoke_capability(self, capability, payload=None):
    if capability != "ui.tab_enabled":
        return None
    request = dict(payload or {})
    if request.get("action") == "set":
        self.enabled = bool(request.get("enabled", True))
        self._publish_state()
    return {"enabled": bool(self.enabled)}
```

When disabled, unregister or stop publishing the contributor so the hidden loop does not include stale rules.

## Prompt Style

Supervisor prompts should be strict and bounded. Screen/Clipboard managed
prompts use detector tags consumed by the runtime; preserve their structured
contract rather than generating finished dialogue inside the detector. Inspect
[shared supervisor rendering](../core/addons/sensory_supervisor.py) and
[the sensory schema](../core/sensory.py) before changing that behavior.

For a custom prompt:

- State which source they apply to.
- Tell the hidden loop when to set `should_speak=true`.
- Tell it when to stay silent.
- Avoid vague "always be helpful" instructions.
- Include repeat/anti-spam guidance if proactive speech is possible.
- Prefer short proactive candidates.

## State

Supervisor personas and behavior rules usually belong in both session and preset state because loading a persona preset should restore them.

Use `export_preset_state() == export_session_state()` unless the setting is clearly global or machine-specific.
