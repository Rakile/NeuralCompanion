# Addon Templates

Copy one of these folders into `addons/` when starting a new addon:

| Template | Use for |
| --- | --- |
| `chat_provider_addon/` | API or local chat providers |
| `vision_source_addon/` | New hidden sensory/context sources |
| `vision_supervisor_addon/` | Behavior rules for an existing sensory source |
| `visual_reply_addon/` | Visual Reply controls or panel extensions |

After copying a template:

1. Rename the folder.
2. Update `addon.json` id, name, description, category, permissions, and service/UI metadata.
3. Rename provider/source ids and state keys in `main.py`.
4. Run `python tools/addon_smoke.py`.

See [Addon Quickstart](../addon_quickstart.md) for the full workflow.
