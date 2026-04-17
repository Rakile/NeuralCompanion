# Vision Source Addons

Vision source addons provide sensory input that can be included in NC's hidden Vision loop or attached to a user turn. Existing examples include Clipboard, Screen, Webcam, and Heart Rate.

Source addons usually do three things:

- Register a sensory provider with `qt.sensory`.
- Optionally add a source tab under the Vision workspace.
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
sensory_service = context.get_service("qt.sensory")
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

Capture handlers should return `None` when there is no useful context. When there is context, return a small dictionary.

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
    "content_text": "Heart rate is elevated at 92 BPM.",
}
```

Keep `content_text` factual and short. The hidden Vision loop is ambient context, not a direct user message.

## Source Tabs

Use the `vision_source` area to put a child tab under Vision:

```python
context.ui.register_tab(
    id="my_source_tab",
    title="Source",
    area="vision_source",
    parent_tab_id="my_source",
    order=100,
    factory=self._build_tab,
)
```

If the source has child supervisor/behavior tabs, use one stable `parent_tab_id` for the source family.

## State

Source settings that change chat behavior usually belong in both session and preset state. Machine-specific paths, caches, and last captured file paths usually do not.

If changing a setting should mark the preset dirty, call:

```python
shell = self.context.get_service("qt.shell")
if shell is not None:
    shell.notify_settings_changed()
```

See `addon_state_and_presets.md` for the full rule.
