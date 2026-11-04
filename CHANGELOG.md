# Changelog

All notable user-facing changes to Neural Companion are documented here.

## v0.5.1

### Installer fixes

- LiquidAI TTS is an optional install target, checked by default. Uncheck it to skip its environment, Python 3.12 setup and model download; existing LiquidAI files remain intact when it is unselected.
- Installer HTTPS downloads retry certificate-verification failures with trusted CA data already installed with Python, pip or NC. Hostname and certificate-chain verification stay enabled; certificate failures no longer trigger an unrelated GitHub authentication retry.
- Component space estimates, installation progress, command-line options and installation guidance follow the separate LiquidAI choice.

## v0.5.0

### Added

- Native Qt Quick/QML workspaces for chat, runtime providers, Personas, addon settings and guided tutorials.
- LiquidAI local text-to-speech with a dedicated managed environment, selectable voices and experimental progressive audio delivery.
- Ditto Avatar Creator with crop preview, custom emotion labels, per-avatar settings and package management.
- A separate Scenic Pack Creator addon and Scenic display in Avatar Preview.
- MCP Core connections and explicit tool permissions for supported addons and saved Personas.
- Saved Speech Timing profiles with optional restoration of the associated providers and models.

### Changed

- Overlapped reply generation and speech preparation so supported speech routes can begin earlier. Speech Timing still controls how much text is supplied to synthesis.
- Improved Local Room controls, participant actions, guidance, Skip speech, full-reply display and speech highlighting.
- Improved resource reporting, safe unloading and model cleanup after stopping chat or Local Room.
- Updated installer component choices, storage estimates, progress reporting, repair behavior and log scrolling.
- Updated tutorials and documentation for the native interface. New installations start with no active text-to-speech provider; Audio Story Mode is optional and disabled by default.
- Updated the phone application source to version 0.5.0 with a project-owned application identifier. A new signed Android download is deferred to a separately tested release; existing alpha downloads remain legacy versions.

### Installation and compatibility

- This release starts a clean public `main` history. Users of the earlier public version should keep their old folder as a backup, clone into a new folder and run the installer.
- The main installer provisions LiquidAI's isolated environment and pinned model. Installing a speech or avatar engine does not activate it.
- Older public tags and their downloads remain available. Future updates after the new installation use the normal launcher update flow.
- Local avatar engines require suitable hardware. Experimental progressive speech and avatar combinations depend on available GPU throughput; see the known limitations and provider guides.

## v0.2.0 - 2026-06-06

### Added

- Added Multi Persona Roleplay Companion runtime with story setup, personas, narrator/character routing, a dedicated Play tab, floating Play view, story state panels, memory/state panels, voice routing, visual prompt debugging, story package assets, and tutorial data.
- Added Scenic Avatar engine with portable Scenic Packs that map tags such as `[neutral]`, `[angry]`, `[surprised]`, or custom scene tags to still images.
- Added Scenic Pack editor, Scenic Pack selection in System Shaping, MuseTalk Preview integration, speech-synced expression changes, tag/image rename and overwrite behavior, and a Scenic side-tab icon.
- Added Ollama chat provider using an OpenAI-compatible interface, with model listing, unload behavior, generation settings, and model capability detection for vision and thinking models.
- Added spellchecking for normal typed chat and edit mode, including underlined misspellings, right-click suggestions, dictionary language selection, and spellcheck enable/disable controls.
- Added shared dependency repair support for optional features and addons.
- Added per-chat Continuity Memory Summary support with automatic summarization rules, review/forget controls, saved-session identity handling, and summary status UI.
- Added per-chat Long-Term Memory Archive with SQLite storage, RAG-like retrieval, raw chunk storage, embedding support, LM Studio embedding model picker, per-session embedding model/context tracking, and retrieval injection into chat.
- Added still-image MuseTalk avatar preprocessing.
- Added app icon and additional side-tab icons.

### Changed

- Improved LM Studio reasoning handling so reasoning output is not treated like normal assistant speech.
- Improved TTS tag handling so unsupported tags are not spoken aloud by backends such as PocketTTS.
- Improved MuseTalk mask editing performance and added brush transparency control.
- Improved Visual Reply Runtime UI behavior and provider settings layout.
- Cleaned up ComfyUI, OpenAI, xAI, and Runware settings display.
- Improved workspace UI with colored workspace tabs, better floating/docking behavior, larger resize hit zones, and a Workspace menu button.
- Updated README and installation documentation with clearer Python 3.11 requirements and safer launch guidance.

### Notes

- This is a large foundation update that brings roleplay, memory, avatars, voice, visual replies, and local model providers closer together into a more complete companion runtime.
- Some new systems are still expected to have rough edges as they are tested across more user setups.
