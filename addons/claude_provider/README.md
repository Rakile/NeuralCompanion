# Claude Chat Provider

For current setup and provider activation, see [Chat and speech](../../docs/manual/chat-and-tts.md). Enable the addon in Addon Manager if it is unavailable, then select and activate it in **Runtime → Runtime Session**.

This addon registers Anthropic Claude as an NC chat provider through the addon host service.

Open **Runtime → Runtime Session → LLM**, select **Claude**, and configure
**Model and connection** (generation controls are under **Advanced provider settings**).
Use **Test connection**, then **Make active**:

- `API Key`: uses the value entered in the provider settings and saved in `qt_session.json`.
- `Base URL`: defaults to `https://api.anthropic.com`.
- `API Version`: defaults to `2023-06-01`.
- `Max Tokens`: Claude requires this for Messages API requests.

The provider supports normal replies, streamed replies, model refresh, connection checks, and data-URL image attachments.
