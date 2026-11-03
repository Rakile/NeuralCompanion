# Visual Reply Addons

Visual Reply owns generation, image-library state and output files. The native
host presents those values through QML runtime settings and Conversation media
surfaces. Start with the [addon quickstart](addon_quickstart.md); the former
QWidget dock replacement API is not the current extension route.

## Current ownership

Read these implementation files together:

| Concern | Current source |
| --- | --- |
| Headless addon lifecycle and finite capabilities | [Visual Reply main.py](../addons/visual_reply/main.py) |
| Provider choices and settings | [providers.py](../addons/visual_reply/providers.py), [runtime_config.py](../addons/visual_reply/runtime_config.py) |
| Image/library state | [library.py](../addons/visual_reply/library.py) |
| Native runtime controls | [visual_reply_core adapter](../ui/qml_bridge/adapters/visual_reply_core.py) |
| Runtime settings workspace | [VisualReplyRuntimeWorkspace.qml](../ui/qml/workspaces/VisualReplyRuntimeWorkspace.qml) |
| Host generation port | `NativeVisualReplyService` in [native_host_services.py](../ui/qml_bridge/native_host_services.py) |

The user configures generation in **Runtime → Runtime Session → Visual reply**.
Provider availability, model/workflow selection and credentials remain separate
from persona/story prompts. Use the current provider implementation rather than
assuming every provider accepts the same size or reference-image options.

## Addon-facing host port

The named port is:

```python
visual_service = context.capabilities.visual_reply
```

The native host backs it with `NativeVisualReplyService` (also available under
the existing `qt.visual_reply` service name). Verified methods include
`settings_snapshot()`, `refresh_hint()` and `request_generation(...)`. Inspect
the actual signature and an existing caller before using generation; it carries
prompt, caption, provider/model/size selection, source metadata and visibility
options. Generation is an explicit operation, not part of a settings snapshot.
Check for an unavailable port and preserve the existing request/cancellation
ownership instead of starting another generation pipeline.

`attach_settings_widgets(...)`, `replace_panel(...)` and Qt widget panel signals
belong to the removed dock integration. `ui.panel_class` is retained as a
no-result compatibility name in the current addon; it does not return a native
panel class. Do not build a new QWidget replacement or pass a panel through an
addon capability.

## Addon-owned value capabilities

The current entry point handles these groups:

- Generation/config helpers: `runtime.generation`, `runtime.client`,
  `runtime.output_base`, `runtime.normalize_prompt`, `runtime.apply_style_anchor`,
  `runtime.story_style_guide`, `runtime.story_prompt`,
  `runtime.write_image_from_response`.
- State and library operations: `runtime.current_state`, `runtime.set_state`,
  `runtime.clear_state`, `runtime.ensure_storage`, `runtime.load_image`,
  `runtime.navigate_storage`, `runtime.set_caption`,
  `runtime.delete_current_image`, `runtime.delete_all_images`.

These are existing addon-owned routes, not permission to expose arbitrary host
objects. Use the exact payload/return shape in `main.py`; destructive library
operations need an intentional user action. A route name alone does not imply
that it is safe to call from the UI thread or with untrusted paths.

## Native settings contributions

The first-party manifest retains `visual_reply_runtime`, `visuals_host`, and
`runtime_role="visual_reply"` as contribution identity. The typed native adapter
and host workspace implement the actual interface. Additional style controls use
[the Visual Story adapter](../ui/qml_bridge/adapters/visual_story.py) and its
addon-owned state. Native manifest metadata does not automatically load an
arbitrary third-party adapter or replace a workspace; review explicit host
composition as described in the quickstart.

## State, presets and files

The native session store restores runtime settings using the existing session
schemas. Presets use a separate flat format and merge addon exports. In the
tested implementation, Visual Reply's `export_preset_state()` exports its
`_SESSION_KEYS` subset, including provider/model/size/mode and related settings;
do not claim those settings are universally excluded from presets. Compare
[main.py](../addons/visual_reply/main.py) and
[native_presets.py](../ui/qml_bridge/native_presets.py) before changing ownership.

Keep secrets out of new portable exports. Session persistence has explicit
credential handling and compatibility rules; do not copy its private values
into UI snapshots, logs, story packages or new preset fields. See
[state and presets](addon_state_and_presets.md). Generated images, browser
position and current history pointers should not become portable preset assets.

Verify paths before showing images. Do not delete generated files as a side
effect of hiding an image, disabling an addon or loading settings. Keep useful
prompt/caption metadata with the output, and report unavailable services or
failed generation without claiming a new image was produced.
