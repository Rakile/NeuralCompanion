# Vision Source Addons

Vision source addons provide sensory input that can be included in NC's hidden Vision loop or attached to a user turn. Existing examples include Clipboard, Screen, Webcam, and Heart Rate.

Start with the [native addon quickstart](addon_quickstart.md). Source addons
usually do three things:

- Register a sensory provider through `context.capabilities.sensory_targets`
  (backed by `qt.sensory`).
- Optionally contribute a typed native surface in **Runtime → Vision Sensors**.
- Return a capture snapshot when NC asks for hidden sensory context.

## Manifest

```json
{
  "id": "nc.my_vision_source",
  "name": "My Vision Source",
  "category": "vision",
  "version": "0.1.0",
  "entry_point": "main.py",
  "description": "Example Vision source addon.",
  "permissions": ["ui.tabs"],
  "enabled": true
}
```

`ui.tabs` is only needed if the addon contributes UI.

## Register A Provider

```python
sensory_service = context.capabilities.sensory_targets
if sensory_service is None:
    context.logger.warning("Sensory capability is unavailable.")
    return None
sensory_service.register_provider(
    provider_id="my_source",
    label="My Source",
    instruction="Short description used for hidden sensory context.",
    order=150,
    capture_handler=self._capture_sensory_snapshot,
    metadata={"kind": "image"},
)
```

Always unregister in `shutdown()`:

```python
sensory_service.unregister_provider("my_source")
```

## Capture Snapshot

Capture handlers accept one optional context mapping, for example
`_capture_sensory_snapshot(self, capture_context=None)`. Return `None` when
there is no useful context, otherwise a small value dictionary. See
[core/sensory.py](../core/sensory.py) and the current
[Mock Heart Rate entry point](../addons/mock_heart_rate/main.py).

Image source example:

```python
return {
    "captured_at": time.time(),
    "image_path": str(self.latest_image_path),
    "source": "my_source",
    "content_text": "Hidden sensory feedback only, not a user request.",
}
```

Text source example:

```python
return {
    "captured_at": time.time(),
    "source": "my_source",
    "content": "Simulated heart rate is 92 BPM.",
    "metadata": {"kind": "physiology", "unit": "bpm", "value": 92},
}
```

Keep observation text factual and short. Current image sources use
`content_text`; Mock Heart Rate uses `content` plus structured metadata. Match the
consumer and nearest source instead of assuming arbitrary payload keys will be
rendered. The hidden sensory loop is ambient context, not a direct user message.

## Native source settings

The `vision_source` area and stable `parent_tab_id` identify a source family in
manifest metadata. They do not construct a QWidget or discover a native adapter
automatically. Compare the [Mock Heart Rate manifest](../addons/mock_heart_rate/addon.json)
with its [native adapter](../ui/qml_bridge/adapters/mock_heart_rate.py).
The adapter describes `NativeControl` values, and the host registers it in
[application_bridge.py](../ui/qml_bridge/application_bridge.py).

For a session-backed surface, `AddonSessionNativeAdapter` uses explicit
`runtime.session.export` and `runtime.session.import` capabilities. Match that
state contract and the shared Vision Sensors routing before adding a new source.
Do not revive `factory=self._build_tab` or Designer `.ui` construction.

Registering a source is separate from the user's source enable switch,
background-review policy, vision model selection, and proactive speech/image
permissions. A new source must respect the existing sensory gates; initialization
must not silently activate observation.

## State

Source settings that change chat behavior usually belong in both session and preset state. Machine-specific paths, caches, and last captured file paths usually do not.

If changing a setting should mark the preset dirty, call:

```python
self.context.capabilities.shell_session.notify_settings_changed()
```

Use the native adapter persistence callback as appropriate. See
[state and presets](addon_state_and_presets.md) for ownership and restore rules.
