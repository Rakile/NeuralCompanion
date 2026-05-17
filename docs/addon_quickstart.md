# Addon Quickstart

This is the starting point for building a Neural Companion addon, including
quick experiments. Use the specialist docs linked below when the addon shape is
clear.

## Pick The Addon Shape

| Goal | Start here | Reference addon |
| --- | --- | --- |
| Add an API or local chat provider | [`docs/templates/chat_provider_addon/`](templates/chat_provider_addon/) | `addons/lmstudio_provider/`, `addons/claude_provider/` |
| Add a screen, clipboard, webcam, file, sensor, or other context source | [`docs/templates/vision_source_addon/`](templates/vision_source_addon/) | `addons/screen_source/`, `addons/webcam_source/` |
| Add proactive rules for an existing source | [`docs/templates/vision_supervisor_addon/`](templates/vision_supervisor_addon/) | `addons/screen_supervisor/`, `addons/webcam_supervisor/` |
| Add Visual Reply controls or replace the Visual Reply panel | [`docs/templates/visual_reply_addon/`](templates/visual_reply_addon/) | `addons/visual_reply/`, `addons/visual_story_settings/` |
| Add a simple workspace/settings tool | copy a small Designer-backed addon | `addons/hotkeys/`, `addons/chat_session_player/` |
| Add TTS or avatar runtime behavior | inspect the closest first-party addon first | `addons/chatterbox_tts/`, `addons/pockettts/`, `addons/vseeface_avatar/`, `addons/vam_avatar/` |

TTS, avatar, and audio-path addons are runtime-sensitive. Prefer copying the
nearest first-party pattern instead of inventing a new lifecycle.

## Copy A Template

Copy a template into `addons/`, then rename the folder, manifest id, provider
ids, class constants, labels, and state keys.

PowerShell:

```powershell
Copy-Item docs\templates\chat_provider_addon addons\my_provider -Recurse
```

Bash:

```bash
cp -R docs/templates/chat_provider_addon addons/my_provider
```

Recommended naming:

- folder: `addons/my_provider`
- manifest id: `nc.my_provider` for bundled/local addons, or a stable unique id
  such as `community.yourname.my_provider` for shared community addons
- provider/source ids: lowercase, stable, and not user-facing
- state keys: prefix with the addon name, for example `my_provider_enabled`

## Minimal Manifest

Every addon needs `addon.json`:

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

Use `permissions` only for capabilities the addon actually needs:

| Permission | Allows |
| --- | --- |
| `ui.tabs` | Register addon UI tabs |
| `storage.read` / `storage.write` | Read/write addon-owned files through `context.storage` |
| `events.subscribe` / `events.publish` | Use the addon event bus |
| `services.register` / `services.consume` | Publish or consume peer addon services |
| `llm.read` | Read the current LLM runtime snapshot |
| `tts.read` | Read the current TTS runtime snapshot |
| `avatar.read` | Read the current avatar runtime snapshot |

Missing permissions fail loudly so addon mistakes are easy to find.

## Minimal Python Entry Point

`main.py` must expose an `Addon` class:

```python
from __future__ import annotations

from core.addons.base import BaseAddon


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        context.logger.info("My addon initialized.")
        return None

    def shutdown(self):
        context = getattr(self, "context", None)
        if context is not None:
            context.logger.info("My addon stopped.")
        return None
```

Keep startup light. Do not load heavy models, open network connections, or start
long-running workers in `initialize()` unless the addon is specifically a
runtime provider and the existing provider pattern does the same.

## Add UI

For quick local experiments, a Python-built tab with `context.ui.register_tab`
is the fastest route. This is useful while exploring an idea.

For release-quality bundled addons, prefer an addon-local Qt Designer file and
register it through `context.ui.register_manifest_designer_tab(...)`.

Manifest UI entry:

```json
{
  "permissions": ["ui.tabs"],
  "ui": [
    {
      "id": "my_addon_tab",
      "title": "My Addon",
      "area": "top_level",
      "ui_path": "ui/my_addon.ui",
      "placeholder": "my_addon_tab",
      "order": 900,
      "tooltip": "My addon settings."
    }
  ]
}
```

Entry point:

```python
class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        context.ui.register_manifest_designer_tab(
            id="my_addon_tab",
            binder=self._bind_tab,
        )
        return None

    def _bind_tab(self, widget, context):
        self._widget = widget
```

Do not add addon-specific widgets directly to `main.ui`. The main window should
own stable host containers; addon UI belongs under the addon folder.

Supported UI mount areas:

| Area | Where it appears |
| --- | --- |
| `top_level` | Workspace tabs |
| `host_settings` | System Shaping |
| `operational_view` | Operational View |
| `avatar_tools` | Avatar/MuseTalk tools |
| `tts_runtime` | TTS Runtime |
| `vision_source` | Vision/Sensory source tabs |
| `visual_reply_runtime` | Visual Reply runtime card |

If a bundled addon declares a Designer UI file, treat that `.ui` file as
required. A missing `.ui` means the addon is broken and should be fixed or
disabled, not silently replaced by a fallback layout.

## Save State

Use session state for local UI/session restore. Use preset state only for
persona or workflow settings that should move with a preset.

```python
def export_session_state(self):
    return {"my_addon_enabled": bool(self.enabled)}

def import_session_state(self, session):
    payload = dict(session or {})
    if "my_addon_enabled" in payload:
        self.enabled = bool(payload["my_addon_enabled"])
    return None

def export_preset_state(self):
    return self.export_session_state()

def import_preset_state(self, preset):
    return self.import_session_state(preset)
```

Do not store API keys, local absolute paths, generated files, model weights, or
cache paths in presets.

When a UI setting should mark the current preset dirty:

```python
shell = self.context.get_service("qt.shell")
if shell is not None:
    shell.notify_settings_changed()
```

## Use Host Services

Common host services:

| Service | Use |
| --- | --- |
| `qt.chat_providers` | Register chat providers |
| `qt.sensory` | Register sensory sources and prompt contributors |
| `qt.visual_reply` | Extend Visual Reply runtime/panel behavior |
| `qt.shell` | Notify settings changes or use safe shell helpers |
| `qt.runtime_config` | Read/write runtime-facing config helpers |
| `qt.bind_designer_widgets` | Let the host index named Designer widgets |

If the service is unavailable, fail safely and log a warning. Addons may be
disabled, unavailable, or loaded in smoke-test contexts.

## Vibe-Coding Prompt

When asking a coding assistant to build an addon, give it this kind of prompt:

```text
Create a Neural Companion addon under addons/<name>.
Follow docs/addon_quickstart.md and the closest docs/templates/* example.
Keep the addon isolated: do not edit qt_app.py, engine.py, shared_state.py, or
core/addons unless there is no addon-local solution.
Use stable addon-prefixed state keys.
If it contributes UI and is meant for release, use addon.json ui metadata plus
context.ui.register_manifest_designer_tab(...).
Run python tools/addon_smoke.py before finishing.
```

For runtime-sensitive work, add:

```text
This touches audio/TTS/avatar/model startup. Copy the nearest first-party addon
pattern and keep startup/shutdown behavior narrow and reversible.
```

## Validate Before Sharing

Run these from the repo root:

```bash
python tools/addon_smoke.py
python tools/release_preflight.py
```

If the addon has release-quality Designer UI, also run:

```bash
python qt_app.py --validate-ui main.ui
```

That UI validation is intentionally stricter than quick experimentation: bundled
release addons should use manifest-backed Designer tabs rather than Python-built
fallback tabs.

Also start the app once with the addon enabled, then disable the addon in the
Addons UI and restart. The app should still launch and related UI should
disappear or become inactive.

## Deeper Docs

- [Chat Provider Addons](chat_provider_addons.md)
- [Vision Source Addons](vision_source_addons.md)
- [Vision Supervisor Addons](vision_supervisor_addons.md)
- [Visual Reply Addons](visual_reply_addons.md)
- [Addon State And Presets](addon_state_and_presets.md)
- [Addon Designer UI Migration](addon_designer_ui_migration.md)
- [Addon Capability Contracts](addon_capability_contracts.md)
- [Addon Lego Box Contract](addon_lego_box_contract.md)
