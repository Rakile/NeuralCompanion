# Changelog

All notable user-facing changes to Neural Companion are documented here.

## Unreleased

- No unreleased changes yet.

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
