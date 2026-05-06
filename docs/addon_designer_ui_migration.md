# Addon Designer UI Migration

Neural Companion now treats `main.ui` as the product UI and addon-owned Designer files as the preferred contract for addon settings surfaces.

## Contract

Addons that can describe their UI in Qt Designer should declare each surface in `addon.json` and register it through `context.ui.register_manifest_designer_tab(...)`.

The addon remains responsible for:

- Owning the `.ui` file under its own addon folder.
- Declaring tab title, mount area, order, placeholder, tooltip, icon path, and runtime metadata in `addon.json`.
- Binding runtime behavior to named widgets in the addon controller.
- Treating the addon `.ui` file as the required layout contract for bundled addon tabs.
- Avoiding assumptions that `qt_app.py` knows about addon-specific controls.

The core framework remains responsible for:

- Loading the addon `.ui` relative to the addon manifest root.
- Calling the addon binder after Designer load.
- Validating addon-owned UI and service metadata during `--validate-ui`.

`python qt_app.py --validate-ui main.ui` now also scans bundled addon entry points and reports any remaining direct `context.ui.register_tab(...)` usage as a migration failure.
It also verifies that bundled addons use manifest-backed Designer registration without Python-built fallback factories, that each manifest UI file exists, and that manifest UI/service entries are well-formed.

## Manifest UI Contract

Each addon-owned tab should use an `addon.json` `ui` entry:

```json
{
  "id": "example_runtime_tab",
  "title": "Example",
  "area": "top_level",
  "ui_path": "ui/example.ui",
  "placeholder": "example_tab",
  "icon_path": "ui/icons/example.png",
  "order": 100,
  "tooltip": "Example addon settings.",
  "metadata": {
    "runtime_role": "example_role"
  }
}
```

Supported mount areas are owned by `core.addons.contributions.ADDON_UI_MOUNTS`:

- `top_level` -> `left_tabs`
- `host_settings` -> `host_settings_tabs`
- `operational_view` -> `right_tabs`
- `musetalk` -> `musetalk_tabs`
- `tts_runtime` -> `tts_runtime_addon_tabs`
- `vision_source` -> `sensory_feedback_tabs`

Provider-only addons that do not own a tab should still declare their runtime service contribution:

```json
{
  "services": [
    {
      "id": "chat_provider_registry",
      "provider_id": "example_provider"
    }
  ]
}
```

Known service ids include `chat_provider_registry`, `avatar_provider_registry`, `tts_backend_service`, `sensory_registry`, `sensory_prompt_contributor`, and `service_registry`.

The shell/live addon mount logic has moved out of `qt_app.py` into `ui/runtime/shell_addon_mounts.py`. The bridge still receives injected dependencies from `qt_app.py`, but addon tab discovery, live mounting, and live-addon cleanup now live behind that runtime module boundary.

The local expression/MuseTalk preview HTTP API has moved out of `qt_app.py` into `core/expression_api.py`; `qt_app.py` now only starts it.

Designer-loaded addon widgets can expose their named controls back to the runtime host through the optional `qt.bind_designer_widgets` host service. This lets runtime code read and save controls by object name without requiring `qt_app.py` to construct the addon page itself.

Addon tabs should own their icons as addon-local files. Pass `icon_path="ui/icons/<name>.png"` to `register_designer_tab(...)`; the framework resolves the path relative to the addon root and applies it when the tab is mounted/adopted. `python qt_app.py --validate-ui main.ui` verifies declared addon icon paths exist.

## Converted In This Slice

- `addons/hotkeys/ui/hotkeys.ui`
- `addons/chat_session_player/ui/chat_session_player.ui`
- `addons/clipboard_source/ui/clipboard_source.ui`
- `addons/mock_heart_rate/ui/mock_heart_rate.ui`
- `addons/chatterbox_tts/ui/chatterbox_tts.ui`
- `addons/pockettts/ui/pockettts.ui`
- `addons/gemini_tts_preview/ui/gemini_tts_preview.ui`
- `addons/visual_reply/ui/visual_reply_core.ui`
- `addons/visual_story_settings/ui/visual_story_settings.ui`
- `addons/clipboard_supervisor/ui/clipboard_supervisor.ui`
- `addons/screen_supervisor/ui/screen_supervisor.ui`
- `addons/webcam_supervisor/ui/webcam_supervisor.ui`
- `addons/heart_rate_behavior/ui/heart_rate_behavior.ui`
- `addons/audio_story_mode/ui/audio_story_mode.ui`
- `addons/musetalk_preprocess/ui/musetalk_preprocess.ui`
- `addons/vseeface_avatar/ui/vseeface_avatar.ui`
- `addons/musetalk_avatar/ui/musetalk_avatar.ui`
- `addons/vam_avatar/ui/vam_avatar.ui`

## Boundary-Mounted Tabs

These tabs now register through manifest-backed Designer registration, but their complex inner controls are still built by addon-local controllers and mounted into an addon-owned Designer shell:

- `audio_story_mode`
- `musetalk_preprocess`
- `clipboard_supervisor`
- `screen_supervisor`
- `webcam_supervisor`
- `heart_rate_behavior`

The avatar engine UI pages for VSeeFace, MuseTalk, and VaM are now addon-owned Designer tabs. `qt_app.py` no longer builds those pages directly; it only provides shared runtime services and adopts the addon contribution into the shell.

`main.ui` no longer carries static preview copies of addon pages. It keeps only stable shell containers and core/runtime pages; addon pages are mounted from addon-local `.ui` files at shell startup/runtime adoption.

## Notes

- The Visual Reply image dock panel is intentionally still a custom Python widget because it is not just a static settings form. It owns polling, storage navigation, zoom behavior, and image display state. The static Designer placeholder has been removed from `main.ui`; the runtime panel is mounted by the Visual Reply runtime bridge.
- The supervisor addons share large repeated behavior-editor forms. Their current Designer shell removes `qt_app.py` ownership of the tab boundary; a later pass can extract and Designer-bind the repeated inner editor itself.
- Audio Story Mode and MuseTalk Preprocess are runtime-heavy tabs. Their current Designer shells avoid importing or starting heavy runtime objects before the addon binder mounts the existing controller widget.
- `python qt_app.py` now launches `main.ui` by default. Use `python qt_app.py --legacy-ui` only as a temporary fallback while the old Python-built shell still exists.
