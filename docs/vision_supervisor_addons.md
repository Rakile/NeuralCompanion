# Vision Supervisor Addons

Vision supervisor addons add behavior rules to an existing Vision source. They usually do not capture images themselves. Instead, they register prompt contributors that teach the hidden Vision loop how to interpret a source.

Existing examples include Screen Supervisor, Webcam Supervisor, Clipboard Supervisor, and Heart Rate Behavior.

## Concept

A source addon answers: "What sensory input is available?"

A supervisor addon answers: "What should NC do when that input shows a meaningful pattern?"

For example:

- Screen Source captures the monitor.
- Screen Supervisor adds rules for what screen patterns should trigger proactive speech.

## Register A Prompt Contributor

Use `qt.sensory.register_prompt_contributor(...)`:

```python
sensory_service = context.get_service("qt.sensory")
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

## Child Tabs

Supervisor tabs normally live under the matching source:

```python
context.ui.register_tab(
    id="my_screen_supervisor_tab",
    title="Supervisor",
    area="vision_source",
    parent_tab_id="screen",
    order=220,
    metadata={"checkable": True},
    factory=self._build_tab,
)
```

If `metadata.checkable` is used, the parent UI can toggle the child tab state through `invoke_capability("ui.tab_enabled", ...)`.

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

Supervisor prompts should be strict and bounded:

- State which source they apply to.
- Tell the hidden loop when to set `should_speak=true`.
- Tell it when to stay silent.
- Avoid vague "always be helpful" instructions.
- Include repeat/anti-spam guidance if proactive speech is possible.
- Prefer short proactive candidates.

## State

Supervisor personas and behavior rules usually belong in both session and preset state because loading a persona preset should restore them.

Use `export_preset_state() == export_session_state()` unless the setting is clearly global or machine-specific.
