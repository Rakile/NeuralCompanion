# Addon Templates (Legacy Reference)

These folders preserve older addon examples. Their Python-built widget and
Designer integration is **reference-only**, not production-native scaffolding.
Copying one into `addons/` does not establish compatibility with the current QML
desktop. Do not follow an example's widget factory, `.ui` registration, panel
replacement or old UI validation instructions as the current integration route.

Start with the [current addon quickstart](../addon_quickstart.md), which links
small shipped runtime entry points, typed native adapters and host composition.
The template files themselves have not been migrated by this documentation pass.

| Reference folder | Reusable subject matter to inspect | Current guide |
| --- | --- | --- |
| `chat_provider_addon/` | Provider metadata and frozen execution v1 transport hooks | [Chat providers](../chat_provider_addons.md) |
| `vision_source_addon/` | Sensory provider identity and capture payloads | [Sources](../vision_source_addons.md) |
| `vision_supervisor_addon/` | Source-specific prompt contribution | [Supervisors](../vision_supervisor_addons.md) |
| `visual_reply_addon/` | Historical Visual Reply integration | [Visual Reply](../visual_reply_addons.md) |

Preserve valid provider contracts and stable IDs when adapting useful logic.
Review current context ports, manifest metadata, native adapter registration,
state/secret ownership and shutdown separately. The presence of a template is
not a claim that its UI or lifecycle passes current release gates.
