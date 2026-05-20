# Visual Reply Addons

Visual Reply addons connect NC's visual response settings and dock UI to image-generation behavior. The current first-party addon owns the Visuals/Core tab and installs the Visual Reply dock panel.

Use this guide for addons that extend Visual Reply UI or replace the panel. The first-party Visual Reply provider list currently includes OpenAI, xAI/Grok, Runware, and ComfyUI.

## Host Service

Visual Reply UI integration is exposed through:

```python
visual_service = context.get_service("qt.visual_reply")
```

Useful methods include:

- `settings_snapshot()`: current visual reply mode, provider, size, model, and auto-show state.
- `attach_settings_widgets(...)`: lets a controller bind existing settings widgets to core handlers.
- `replace_panel(panel)`: replaces the dock widget with an addon-provided panel.
- `show_image(image_path, caption="", status_text="Visual Reply", auto_show=True)`: displays an image in the dock.
- `set_loading(...)`: updates the dock while generation is running.
- `clear(...)`: clears the dock state.
- `show()` and `hide()`: controls dock visibility.

## Core Tab Pattern

The core Visual Reply runtime settings belong in the dedicated
`visual_reply_runtime` area. The host mounts that contribution into the Visual
Reply Runtime card instead of a normal tab widget:

```python
context.ui.register_tab(
    id="visuals_host",
    title="Visuals",
    area="visual_reply_runtime",
    order=120,
    tooltip="Visual reply runtime settings.",
    metadata={"nested_title": "Core", "runtime_role": "visual_reply"},
    factory=self._build_core_tab,
)
```

Use `metadata.runtime_role="visual_reply"` for the first-party core runtime
card. Use `metadata.nested_title` when a normal host tab should show a nested
child label such as `Core`.

Additional story or visual settings that are not the core runtime card can
still use the regular `host_settings` area.

## Replacing The Dock Panel

The replacement panel should be a Qt widget. If it exposes compatible signals, the host service will connect them:

- `loadRequested`
- `captionRequested`
- `clearRequested`

Minimal pattern:

```python
panel = MyVisualReplyPanel()
visual_service.replace_panel(panel)
```

## State

Visual reply runtime settings currently behave like core Host settings. If an addon owns additional UI preferences, decide whether they are:

- Preset-owned, such as "auto visual replies on/off for this persona".
- Session-only, such as dock browser history or currently selected generated image.

Avoid saving generated images or history pointers into presets.

## Safety

Visual Reply touches user-visible files and generated images. Addons should:

- Verify image paths exist before showing them.
- Avoid deleting files unless the user explicitly requested it.
- Keep generated prompt/caption metadata close to the image when possible.
- Fail softly if the dock service is unavailable.
