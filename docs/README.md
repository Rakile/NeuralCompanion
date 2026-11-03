# Documentation map

Start with the [user manual](manual/index.md) for the current native desktop
interface. The [addon catalog](addons/index.md) maps every bundled addon to its
setup guide, including provider addons that appear inside Runtime.

## Using NeuralCompanion

| Task | Guide |
| --- | --- |
| Install and get your first reply | [Installation](install.md), [First run](manual/first-run.md) |
| Send, save, edit, and customize chat messages | [Using Main chat](manual/conversation.md) |
| Configure providers, voice input, and spoken replies | [Chat and speech](manual/chat-and-tts.md), [Addon management](manual/addons.md) |
| Create characters and assign their settings | [Personas](manual/personas.md), [Voice Studio](addons/voice_studio.md) |
| Use memory and reference documents | [Memory](manual/memory.md) |
| Inspect RAM/VRAM and unload idle models | [Resources](manual/resources.md) |
| Add an avatar | [Avatars](manual/avatars.md), [Avatar packs](avatar_packs.md) |
| Set up VSeeFace, speech lip sync and the Echo test avatar | [VSeeFace provider](addons/vseeface.md) |
| Use LM Studio, the default SDK-backed provider | [LM Studio](addons/lmstudio_sdk.md) |
| Connect MCP servers and give a persona tools | [MCP connections and persona tools](addons/mcp.md) |
| Play chess locally or online, with optional Launchpad hardware | [Companion Chess](addons/companion_chess.md) |
| Generate and browse images | [Visual Reply and awareness](manual/visual-reply-and-sensory.md), [Image toolbar](visual_reply_toolbar.md), [ComfyUI](visual_reply_comfyui.md) |
| Change the interface palette | [Appearance themes](custom-appearance.md) |
| Run a group conversation | [Buddy Chat](addons/buddy_chat.md), [Local Room](addons/local_room.md), [Discord room](addons/discord_voice.md) |
| Connect a phone | [Main Chat Remote](addons/main_chat_remote.md), [Internet setup](addons/main_chat_remote_internet_setup.md) |
| Manage a phone conversation's cast | [Chat characters](CHAT-CHARACTER-LIBRARY.md) |
| Collect phone connection evidence | [Phone diagnostics](PHONE-CONNECTION-DIAGNOSTICS.md) |
| Diagnose a problem | [Troubleshooting](troubleshooting.md), [Current limitations](known_limitations.md) |

The [manual index](manual/index.md) and [addon catalog](addons/index.md) include
the remaining feature guides. The [current screenshot set](readme_images/2026-10/README.md)
was captured from the native UI on 24 October 2026 with illustrative chat text
and isolated default settings. Assets and optional controls depend on the
installed build and enabled addons.

## Developing addons

Begin with [Addon Quickstart](addon_quickstart.md). The developer references
describe registration, services, state ownership, and native UI integration;
they are separate from the user setup guides.

- [Addon capability contracts](addon_capability_contracts.md)
- [Addon state and presets](addon_state_and_presets.md)
- [Chat provider addons](chat_provider_addons.md)
- [Vision sources](vision_source_addons.md) and [supervisors](vision_supervisor_addons.md)
- [Visual Reply integration](visual_reply_addons.md)
- [Template status](templates/README.md)

