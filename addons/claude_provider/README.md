# Claude Chat Provider

This addon registers Anthropic Claude as an NC chat provider through the addon host service.

Configure it in `Host -> Chat Runtime` after selecting `Claude`:

- `API Key`: uses the field value, `NC_CHAT_CLAUDE_API_KEY`, or `ANTHROPIC_API_KEY`.
- `Base URL`: defaults to `https://api.anthropic.com`.
- `API Version`: defaults to `2023-06-01`.
- `Max Tokens`: Claude requires this for Messages API requests.

The provider supports normal replies, streamed replies, model refresh, connection checks, and data-URL image attachments.
