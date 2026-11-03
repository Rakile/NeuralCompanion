# Current native desktop screenshots

These 22 images were captured on **24 October 2026** from NC's production Qt
Quick/QML interface, using the tested desktop source at revision
`12b78ad144afa1ebcbe9310da572e8b216f9aed1` plus the integrated application changes.
They include the refreshed guide set, five Main chat examples, and Resources.
Older images in dated engineering records are historical.

The app ran in an isolated copy of authored code and public assets. Personal
chats, credentials, user settings, memories, and models were not copied. Images
are native window captures without added UI elements or pixel retouching.

- **main-chat**, **chat-controls**, **chat-appearance**, and **chat-commands**
  show supplied illustrative messages. The runtime is stopped; unavailable
  actions are shown as such. The commands image opens suggestions without
  executing a command.
- **chat-reading** uses the real chat renderer with a display-only speech
  position to illustrate **Reading current** and **Rounded focus**. No audio
  was generated or played for that capture.
- **resources** shows a read-only inspection of system memory in the isolated
  native app. No model was initialized or unloaded for that capture.
- The remaining 16 images show the current settings and addon pages with
  isolated default or example state. Provider selection, green addon-loaded
  indicators, and visible controls do not establish a working external service,
  trained voice, connected phone, or running room.

See [Using Main chat](../../manual/conversation.md), the [user manual](../../manual/index.md),
and the [addon catalog](../../addons/index.md) for setup and usage. Capture checks
confirm native rendering and image dimensions; they do not replace release
gates or live model, microphone, Discord, phone, and hardware tests.
