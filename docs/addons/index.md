# Addon guide catalog

NeuralCompanion uses addons for providers, creative tools, conversation modes,
and integrations. Some appear as their own workspace; others supply a choice
inside **Runtime**. Several related addons share one guide so their setup is
explained together. The [coverage inventory](../README.md) lists
each current addon manifest and its guide; workspace titles can be shorter than
manifest names.

For installing, enabling, hiding, and finding addons, read
[Addon management](../manual/addons.md). For an introduction to the whole app,
start with the [README](../../README.md) or [user guide index](../manual/index.md).

## Characters and conversations

| Addon or feature | What it adds | Instructions |
| --- | --- | --- |
| Buddy Chat | Several companions in the main conversation | [Buddy Chat](buddy_chat.md) |
| Discord Voice Bridge / Local Room | Discord voice bots and a separate local persona room | [Local Room](local_room.md), [Discord Voice](discord_voice.md) |
| Multi Persona Roleplay | Cast, narrator, scenes, and story Play | [Roleplay](roleplay.md) |
| Audio Story Mode | Chapters, transcripts, illustrations, and narration | [Audio Story Mode](audio_story_mode.md) |
| Voice Studio | Voice creation, comparison, and library | [Voice Studio](voice_studio.md) |
| NC Identity Relay | Reviewed continuity imports from external AI conversations | [Identity Relay](identity_relay.md) |
| User Identity | Your profile and optional image reference | [User Identity](user_identity.md) |
| Document Memory | Knowledge packages from selected documents | [Memory and document knowledge](../manual/memory.md) |
| Main Chat Remote | Access to desktop main chat from a phone | [Phone setup](main_chat_remote.md), [Internet mode](main_chat_remote_internet_setup.md) |

**Persona** is the central character editor rather than a separate manifest
addon. See [Personas](../manual/personas.md) for identity, voice assignment,
portraits, and provider overrides.

## Language, speech, and avatars

Open **Runtime → Runtime Session**, then choose **LLM**, **Speech-to-text**,
**Text-to-speech**, or **Avatar** and review the stack in **Session setup**.
Select **Initialize NC**
to load that stack. Opening provider settings and loading a provider are separate
actions.

| Addons | Purpose | Instructions |
| --- | --- | --- |
| LM Studio Chat Provider; Ollama Chat Provider | Local language-model servers; LM Studio uses the Python SDK by default | [LM Studio](lmstudio_sdk.md), [chat and speech](../manual/chat-and-tts.md) |
| LM Studio (REST) Chat Provider | Optional Responses API alternative; disabled by default | [LM Studio transports](lmstudio_sdk.md), [chat and speech](../manual/chat-and-tts.md) |
| OpenAI Chat Provider; xAI / Grok Chat Provider; DeepSeek Chat Provider; Claude Chat Provider | Hosted language models | [Chat and speech](../manual/chat-and-tts.md) |
| Whisper English STT; Whisper Multilingual STT; No STT | Whisper transcribes speech; No STT disables transcription and leaves typed chat available | [Chat and speech](../manual/chat-and-tts.md) |
| Chatterbox TTS; Chatterbox Multilingual TTS | Local speech output | [Chat and speech](../manual/chat-and-tts.md) |
| PocketTTS; PocketTTS Multilingual | Local speech in an isolated runtime | [PocketTTS](../manual/pockettts.md) |
| LiquidAI TTS | Local built-in voices in a dedicated environment and process | [LiquidAI](../manual/liquidai-tts.md) |
| ElevenLabs TTS; Gemini TTS Preview | Hosted speech output | [Chat and speech](../manual/chat-and-tts.md) |
| MuseTalk Avatar; MuseTalk Avatar Creator | Prepared talking-avatar packs and creator tools | [MuseTalk](../manual/musetalk.md) |
| Ditto Avatar; Ditto Avatar Creator | Talking avatars from portraits or video | [Ditto](../manual/ditto.md) |
| Scenic Avatar; Scenic Pack Creator | Expression/tag-based image packs and their editor | [Scenic Avatar](scenic_avatar.md), [pack creator](scenic_pack_creator.md) |
| VSeeFace Avatar | External avatar, Echo test model, body presets and speech lip sync | [VSeeFace provider](vseeface.md) |
| No Avatar | Chat and speech without an animated avatar | [Avatars](../manual/avatars.md) |

TTS **None** is also available for silent conversation. Avatar preparation,
local speech families, and hosted providers have different requirements; install
and activate only what you intend to use.

## MCP and games

| Addon | Purpose | Instructions |
| --- | --- | --- |
| MCP Core | Required shared HTTP connections, credentials and exact consumer tool grants | [MCP setup](mcp.md#connect-an-existing-mcp-server) |
| Chat MCP Tools | Native model tool calls filtered by a saved persona's assignments | [Persona tools](mcp.md#give-a-saved-persona-tools-for-normal-chat) |
| Companion Chess | Local persona games, optional Launchpad and online human matches | [Companion Chess](companion_chess.md) |

## Images, awareness, and presence

| Addons | Purpose | Instructions |
| --- | --- | --- |
| Visual Reply; Visual Story Settings | Image generation, browsing, styles, and continuity | [Visual Reply](../manual/visual-reply-and-sensory.md), [toolbar](../visual_reply_toolbar.md), [ComfyUI](../visual_reply_comfyui.md) |
| Screen Source; Webcam Source; Clipboard Source | Selected images as model context | [Vision Sensors](../manual/visual-reply-and-sensory.md) |
| Screen Supervisor; Webcam Supervisor; Clipboard Supervisor | Source-specific proactive reaction rules | [Vision Sensors and permissions](../manual/visual-reply-and-sensory.md) |
| Companion Orb Overlay | Desktop targeting and explicitly enabled watches | [Companion Orb](ai_presence_companion_orb.md#companion-orb) |
| AI Presence Mode | Floating or fullscreen audio-reactive visuals | [AI Presence](ai_presence_companion_orb.md#ai-presence) |
| Spotify Sense | Music controls, track awareness, and ducking | [Spotify Sense](spotify_sense.md) |
| Web Search | MCP search evidence for chat | [Web Search](web_search.md) |
| Mock Heart Rate; Heart Rate Behavior | Simulated BPM and experimental behavior input | [Tools and integrations](tools-and-integrations.md#mock-heart-rate-and-heart-rate-behavior) |
| Ua Companion Orb Overlay | Separate external Unreal overlay integration | [Unreal overlay bridge](tools-and-integrations.md#ua-companion-orb-overlay) |

Showing a visual overlay does not automatically enable observation. Review source
and shared-awareness permissions before enabling background reactions.

## Everyday tools and hardware

| Addon | Purpose | Instructions |
| --- | --- | --- |
| Hotkeys | Configurable speech, conversation, and window actions | [Hotkeys](tools-and-integrations.md#hotkeys) |
| Conversation Replay | Saved-session replay and context tools | [Conversation Replay](tools-and-integrations.md#conversation-replay) |
| Corsair Visual Instrument | iCUE keyboard lighting driven by NC state and audio | [Corsair LEDs](tools-and-integrations.md#corsair-leds), [detailed iCUE setup](../../addons/corsair_visual_instrument/README.md) |

For the desktop layout and guided tours, use **Tutorials** in the app. For startup
or resource problems, see [Troubleshooting](../troubleshooting.md) and
[Resources and performance](../manual/performance.md).
