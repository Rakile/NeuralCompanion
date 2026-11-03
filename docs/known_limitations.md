# Known Limitations

NeuralCompanion is a local desktop companion application under active development. These are the limitations to expect in the current release. They are not promises about a future version.

The documentation describes the current native Qt Quick/QML interface. Older screenshots, videos, or written guides may use earlier UI names; the in-app **Tutorials** workspace follows the current controls.

## Platform and installation

- **Windows is the supported desktop platform in this repository.** Linux work is maintained separately in the [NeuralCompanion-Linux repository](https://github.com/Rakile/NeuralCompanion-Linux).
- **Python 3.11 is the expected runtime.** The installer validates 3.11 and can rebuild an isolated environment that uses another version. Python 3.12 or newer is not a supported substitute.
- **Optional engines are separate environments.** MuseTalk, Ditto, and PocketTTS do not share the main app's packages. A component can be installed while still missing its models, prepared assets, or external service.
- **Local avatars need appropriate hardware.** MuseTalk requires an NVIDIA CUDA setup. Ditto uses its own CUDA 12.8 stack for standard RTX and Blackwell cards. Other GPU paths are not documented.
- **The installer does not install or start every external service.** LM Studio, Ollama, VSeeFace, ComfyUI, Discord, and hosted providers have their own setup. Voice Studio is an NC addon with provider-specific requirements, rather than a requirement to run a separate application of that name.
- **Disk use grows with models and generated media.** Model weights, prepared packs, caches, rendered frames, and audio can be large. Startup caches improve speed but consume disk space.

## Assets and services

- **Only a limited approved set of assets is bundled.** NC ships approved voice references and persona assets recorded in the [release asset policy](release_asset_policy.md). Most voice samples, model weights, prepared avatar packs, and generated media are not shipped in the source repository.
- **Screenshots show examples, not bundled content.** A persona, voice, avatar, or image shown in documentation may depend on assets you supply.
- **Prepared packs are engine-specific.** A MuseTalk pack is not a Ditto package. Installing one engine does not make another engine's assets usable.
- **You must have rights to the media you use.** This applies to voices, portraits, avatar packs, generated character media, and documents.
- **Hosted providers can change terms, pricing, models, or availability.** API access is separate from a consumer subscription, and provider outages are outside NC's control.

## UI and navigation

- **Controls can be hidden.** Conversation toolbar buttons, addon icons, and workspaces can be hidden. Use **Controls**, **Unhide addon**, or the NeuralCompanion logo/name menu to restore them.
- **Some addon changes require a restart.** Follow the status shown in Addon Manager rather than assuming a toggle took effect immediately.
- **Installing, enabling, configuring, and activating are separate.** A provider can be installed but not active; a pack can be installed but not selected.
- **Older written material may lag the current UI.** Prefer the in-app tutorials for the current labels and locations.

## Speech

- **Speech quality and latency depend on the provider and hardware.** First use can be slower while models load or download.
- **Reference voices require a compatible provider.** A recording that works with one speech backend may not work with another. Previewing a voice does not assign it.
- **PocketTTS cloning may require model-term acceptance and a Hugging Face login.** A successful login does not prove that gated terms were accepted.
- **Speech-to-text and speech output are independent.** Choosing a different speaking voice does not repair microphone transcription.
- **Off choices are intentional.** Speech output **None** gives silent text replies. Speech-to-text **None** turns transcription off; when the No STT addon is unavailable, its fallback off choice is labeled **Disabled**. **Text Only** disables microphone input as a session mode.
- **Streaming is a tradeoff.** Smaller chunks can start sooner; larger chunks can sound smoother. Very aggressive settings can produce unstable fragments or heavier overlapping work.

## Avatars and visuals

- **Avatar preparation and runtime are separate.** Preparing a MuseTalk or Ditto asset does not activate it. **Use this avatar** selects the active route.
- **MuseTalk startup can be slow.** The first pack/model load is usually slower than later loads. Caches and model warm-up affect this.
- **Avatar quality depends on the prepared asset.** Source framing, masks, emotion variants, and pack quality matter more than most runtime sliders.
- **Ditto packages are not interchangeable with MuseTalk packs.** Each engine has its own preparation workflow and runtime.
- **Scenic and VSeeFace have their own prerequisites.** Scenic needs a compatible image pack; VSeeFace needs an external avatar application and VMC receiver.
- **Avatar Preview does not start a model.** An idle preview or still image can mean the runtime is stopped, not that the avatar is broken.
- **Heavy stacks compete for memory.** A large language model, speech model, avatar model, and visual model may not fit comfortably together on one GPU.

## Conversation memory

- **Conversation memory requires a saved or loaded named chat.** Its controls are inactive for an unsaved conversation.
- **Keeping a summary and using it are separate.** A summary can exist without contributing to replies.
- **A summary is lossy.** It is compressed notes, not a complete transcript, and long conversations can exceed what it keeps.
- **Storing older messages and recalling them are separate.** An archive can grow while recall is off.
- **Automatic updates and archiving require their Memory controls to be enabled.** Automatic summarization additionally requires **Enable Conversation Memory summarization** in Advanced settings.
- **Saved and indexed counts can differ.** Batches wait for a complete group and idle time. A pending batch is not the same as a failed index.
- **Semantic memory search is optional and separable.** Keyword search works without embeddings. An embedding provider is independent of the chat provider. OpenAI embeddings send text to that API and incur charges.
- **Memory is not unlimited context.** Recall adds selected material to the prompt; it does not expand the model's context window or guarantee that a detail is found.
- **Do not assume a cloud backup.** Treat chats, memories, voices, and documents as local data that you back up yourself.

## Document Memory

- **Document Memory is separate from conversation memory.** It has its own packages, settings, embedding model, index, and source snapshots.
- **Only supported text formats are accepted.** The current importer reads `.txt`, `.md`, `.markdown`, `.json`, `.log`, and text-based `.pdf`.
- **PDFs need extractable text.** NC does not perform OCR or request passwords. Image-only scans need preprocessing; a file that cannot open without a password cannot be imported.
- **Each package has its own embedding model setting.** Changing the package model requires re-splitting and re-indexing its saved snapshots.
- **Saved snapshots are not live originals.** Editing a source file does not update the package automatically. Use **Refresh from sources** to reread it.
- **Rebuilding saved embeddings uses snapshots.** It does not reread changed originals.
- **Indexing waits for idle time.** A large package can remain unindexed for a while, and recall is incomplete until indexing is ready.
- **Enabling recall is a separate switch.** A package can be selected and indexed while **Use Document Memory in chat** is off.
- **Retrieved documents are reference material, not instructions.** The model can still ignore or misunderstand an excerpt; verify important answers.

## Personas and multi-character use

- **Persona overrides do not fall back.** An unavailable provider or model reports an error when requested.
- **A persona is not a separate chat history.** Switching personas does not create a new transcript or merge histories.
- **A persona Document Memory package is referenced, not copied.** When recall is enabled, an unavailable package contributes no excerpts.
- **Main chat and Local Room cannot run at the same time.** Switching requires stopping one and handling any unsaved-chat prompt.
- **Multi-character, roleplay, and story workflows are optional and token-heavy.** Test a short exchange or chapter before starting a long run.
- **Moderator and roleplay behavior is not a guarantee of factual accuracy or character consistency.** Review generated content.

## Main Chat Remote

- **A new Android download is deferred.** Desktop 0.5.0 includes phone source, but its new signed APK still requires separate signing and physical-phone acceptance. The existing public alpha is a legacy download with unverified compatibility with desktop 0.5.0.

- **The phone does not replace the desktop model runtime.** The desktop must remain running for the features it serves.
- **Internet mode requires a matching native phone build and an NC Relay account.** A browser page or unrelated client is not a substitute.
- **Some media paths have hardware requirements.** Continuous Android avatar video needs desktop NVIDIA NVENC H.264 encoding; that path has no CPU fallback.
- **Physical-device coverage is not universal.** A passing desktop or mocked test is not evidence for every phone, OS version, network, or device.

## Performance

- **Measurements depend on the configured stack.** Results for a text-only session do not predict an avatar session.
- **Recommendations are guidance, not guarantees.** Apply one change at a time and compare the same prompt.
- **External services add separate latency and memory use.** NC cannot tune a provider's network or unload another application's models.
- **First runs are not steady-state runs.** Model loading, downloads, and cold caches can dominate the first measurement.

## Addons and privacy

- **MCP tools require several explicit choices.** A connection, consumer approval,
  exact tool grants and persona assignments are separate. Native tool calling
  also depends on the selected model and endpoint; support metadata does not
  establish reliable tool use. See [MCP](addons/mcp.md).

- **Addons are loosely coupled and some are experimental.** A missing key, service, or model can make an addon inactive without breaking the rest of the app.
- **Addons run as local application code.** Install addons from sources you trust.
- **Local-first does not mean offline-only.** Hosted chat, speech, embeddings, image generation, web search, and remote access send data to the services you configure.
- **Sensory features can capture sensitive content.** Review enabled sources, retention, and recipients before using screen, webcam, clipboard, or companion-orb awareness with a hosted provider.
- **Communication logs are private.** They can contain visible and hidden messages, prompts, and replies. Review and remove sensitive material before sharing logs.
- **Protect the project folder and runtime data.** Treat chats, memories, voice recordings, documents, and credentials as private local data.

## Related reading

- [Installation](install.md) and [First run](manual/first-run.md)
- [Memory](manual/memory.md) and [Personas](manual/personas.md)
- [Avatars](manual/avatars.md), [MuseTalk](manual/musetalk.md), and [Ditto](manual/ditto.md)
- [Troubleshooting](manual/troubleshooting.md)
