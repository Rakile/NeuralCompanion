# LM Studio

**LM Studio** is NeuralCompanion's default chat provider and uses the installed
`lmstudio` Python SDK. Its internal provider ID remains `lmstudio_sdk`, so existing
SDK settings, personas and saved references keep working. Diagnostic logs still
identify this transport as **LM Studio SDK**.

The original implementation is available as **LM Studio (REST)**, disabled by
default. To use it, enable **LM Studio (REST) Chat Provider** in Add-ons, restart
NC, then select it in the provider settings. It retains the `lmstudio` ID and
its separate saved settings. Existing explicit add-on choices are preserved;
changing defaults does not overwrite them. Disabling it removes its provider
entry after restart, while its Add-ons entry remains available.

Reach it in **Runtime → Runtime Session → LLM** after enabling the addon and
restarting NC if the addon was newly discovered. The shared
[Chat and speech](../manual/chat-and-tts.md) guide covers activation, personas,
memory search, and speech.

## Requirements

- LM Studio is installed and its local server is running with at least one
  downloaded model.
- NC's Python environment already contains the `lmstudio` SDK (the current
  integration targets SDK 1.5.0). This addon does
  not install or upgrade the SDK or LM Studio.
- The SDK server is normally local, for example `http://127.0.0.1:1234`. A
  loopback connection is the intended setup.

The provider uses a plain `http` host and port. It rejects URL credentials,
query strings, fragments, custom paths, and HTTPS. A trailing `/v1` is accepted
and normalized away. Do not put an API token in the address.

## Connect and activate

1. Start LM Studio's local server and confirm a model is downloaded.
2. Open **Runtime → Runtime Session → LLM → LM Studio**.
3. Check **SDK server address**, normally `http://127.0.0.1:1234`.
4. Select **Refresh** if the model list is empty. The list also refreshes
   automatically when you open or return to these settings.
5. Select a model, then choose **Test connection**.
6. Choose **Make active**, then send a short message from Conversation.

**Test connection** checks the SDK server and its downloaded-model catalog. It
does not prove that a particular model can generate a reply. The first real
message is the generation check.

## Settings

### Context length

**Context Length** controls model loading, not the number of recent chat
messages.

- `0` reuses the selected loaded model's current context, or NC's normal
  profile default when that model is not loaded.
- A nonzero value must be 512–1,048,576 tokens.
- A matching loaded model is reused. If the selected instance has a different
  context, NC reloads that named instance; other loaded model instances stay
  loaded. LM Studio may round the allocation to a 256-token boundary.

Changing this value can therefore reload the model on its next use. It does not
unload unrelated models.

### Sampling

The generation controls are:

| Setting | Range and default |
| --- | --- |
| Temperature | 0.00–2.00, default 0.70 |
| Top P | 0.00–1.00, default 0.90 |
| Top K | -1–100,000, default 40 |
| Repetition Penalty | 0.00–3.00, default 1.00 (neutral) |
| Min P | 0.00–1.00, default 0.00 (disabled) |
| Max Tokens | -1–131,072, default -1 |

**Max Tokens** `-1` means no explicit output cap; it is not a one-token limit.
This provider does not expose a seed, frequency penalty, or presence penalty.
An unsupported sampling field is rejected explicitly rather than being silently
ignored.

Unset fields use the defaults above in both the UI and request preparation.
Legacy global sampling values do not replace this provider's defaults. Saved
SDK values take precedence, including when only some fields have been saved;
the other fields keep the defaults above. Existing saved settings are not reset
or migrated, and explicit frozen-request overrides remain authoritative. Context
Length stays at `0` and Enable Thinking defaults to off where the toggle is supported.

The default provider maps Top K, Repetition Penalty, and Min P for you. The optional
**LM Studio (REST)** provider cannot override those three settings; it requires them to
be configured in LM Studio. That difference is one reason to use the SDK
provider, and one reason the two providers have independent settings.

### Thinking

**Enable Thinking** appears only when LM Studio reports the selected model with
both `off` and `on` reasoning modes. The choice is frozen for the turn, including
MCP continuations, and NC verifies the server's acknowledgement. If the server
does not report the mode, the request fails explicitly instead of pretending the
setting applied. Reasoning text is kept out of the visible answer and speech.

When LM Studio's native capability metadata is unavailable, the model list still
works through SDK discovery, but models keep their default thinking behavior and
the toggle is not offered.

### Images, structured output, and tools

- Images prepared by NC as image data URLs are supported for image-capable
  models.
- JSON structured output is supported when the selected model supports it.
- Persona-approved MCP tools use NC's normal tool execution. The addon does not
  use the SDK's `.act()` call and never dispatches actions itself. Tool support
  and reliability depend on the selected model.
- Native tool calls retain their SDK call IDs and arguments, and tool schemas are
  checked before the SDK request is started.
- In the model list, **Tool-capable models only** hides only models reported
  without tool support; unknown support remains visible. The vision filter uses
  the catalog's reported capability, with NC's model-name fallback when the
  catalog omits it.

## Connection and lifecycle

The provider runs SDK requests in an isolated helper process, separating the
Python client lifetime from NC. Requests through this provider are serialized.
Both LM Studio providers can still use the same LM Studio server, so server-side
model loading and unloading can affect that shared server.

- Cancelling a request or closing a stream closes its helper process.
- The caller's deadline and cancellation token control helper lifetime; the
  addon does not add a second model-reply deadline.
- Generation goes through the Python SDK. There is no REST generation fallback.
  SDK or helper errors are reported rather than retried through another
  transport.
- Model preparation reuses NC's existing LM Studio inspection, loading, and
  cleanup rules, so a correctly loaded selected model can be reused at startup
  and between turns.
- A model change, incompatible load setting, or context change can reload the
  selected model. Enabling the addon alone does not unload models.
- The addon does not install, upgrade, or patch the `lmstudio` package. An
  incompatible SDK API fails explicitly.

## Authentication

This provider exposes no API-token field. It passes only the server address to
the SDK, and it rejects credentials embedded in the address. NC does not
add or manage a token for this provider.

Use an ordinary local LM Studio server without enforced token authentication.
The optional **LM Studio (REST)** provider also has no user-facing token control. LM
Studio's own Python SDK documentation describes API-token support and environment
variables; that SDK-level behavior is outside NC's provider settings. See
[LM Studio Python SDK authentication](https://lmstudio.ai/docs/python/getting-started/authentication)
and the [Python SDK documentation](https://lmstudio.ai/docs/python).

## Differences from the optional REST provider

| Behavior | LM Studio (REST) | LM Studio (default SDK) |
| --- | --- | --- |
| Transport | LM Studio Responses API over HTTP | Installed Python SDK in a helper process |
| Fresh-install state | Disabled; enable in Add-ons and restart | Enabled and selected as the default chat provider |
| Settings and model | Separate | Separate |
| Context Length | 512–1,048,576; default 8,192 | `0` or 512–1,048,576; default `0` |
| Top K, Repetition Penalty, Min P | Set in LM Studio; NC cannot override | Exposed and mapped by NC |
| Enable Thinking | Catalog-dependent | Catalog-dependent, with per-turn verification |
| API token field | None | None |
| Generation fallback | None | No REST fallback |

## Troubleshooting

| Symptom | Check |
| --- | --- |
| **LM Studio** is not listed | Enable LM Studio Chat Provider and restart NC; provider addons are discovered at startup |
| SDK unavailable or import error | Confirm the `lmstudio` package exists in NC's Python environment; the addon does not install it |
| Connection refused | Start LM Studio's local server and confirm the host and port |
| Address rejected | Remove `https://`, credentials, query strings, and custom paths; use `http://host:port` |
| No models in the list | Download a model in LM Studio, then choose **Refresh** |
| **Enable Thinking** is missing | The model does not report both `off` and `on`, or the server does not expose reasoning metadata; the model keeps its default behavior |
| Thinking setting fails | The server did not acknowledge the requested mode; check the LM Studio version and model |
| The model reloads after changing Context Length | Expected. Changing the load context replaces that named instance |
| A request waits behind another | Requests are serialized by design; cancel the active request or wait for it to finish |
| A helper process error appears | Read the provider error and NC log; this provider does not retry through REST |

## Current limits

- The SDK provider requires a local SDK server and an SDK installation that NC
  can import. It does not manage either.
- It has no API-token or HTTPS setting. Use a local, unauthenticated server.
- It does not expose a seed or frequency/presence penalty.
- Thinking support, images, structured output, and tools depend on the selected
  model and on LM Studio's reported capabilities.
- Requests are serialized; this is not a parallel SDK pool.
- **LM Studio (REST)** remains available as an optional HTTP transport. Its
  generation behavior and independent settings are unchanged.

## Related guides

- [Chat and speech](../manual/chat-and-tts.md)
- [Addon management](../manual/addons.md)
- [Troubleshooting](../manual/troubleshooting.md)
- [Addon guide catalog](index.md)
