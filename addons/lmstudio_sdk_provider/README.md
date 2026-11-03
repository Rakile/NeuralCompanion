# LM Studio (Python SDK)

NC's default **LM Studio** chat provider uses the installed `lmstudio` Python
SDK. Its ID remains `lmstudio_sdk`; settings and saved references are preserved.
The original **LM Studio (REST)** provider is disabled by default and can be
enabled in Add-ons, followed by a restart. It retains its separate `lmstudio`
settings. Existing explicit add-on choices are not overwritten.

Fresh sampling defaults are Temperature **0.7**, Top P **0.9**, Top K **40**,
Repetition Penalty **1.0** (neutral), Min P **0** (disabled), and Max Tokens **-1**
(no explicit cap). Unset fields use these same values in the UI and requests,
without inheriting legacy global samplers. Saved SDK settings and explicit
frozen-request overrides take precedence; existing settings are not reset.
Context Length remains **0** and Enable Thinking defaults to off where supported.

## Use

1. Restart NC to discover the new addon.
2. Open Runtime → Runtime Session → LLM → **LM Studio**.
3. Set the SDK server address, normally `http://127.0.0.1:1234`.
4. Choose a downloaded model from the automatically populated list and make
   this provider active. **Refresh** also updates the list manually.
5. Configure its sampling controls and, if wanted, a context length. Zero uses
   the current loaded/model default. New instances use the actual model name,
   matching the original provider. Changing context reloads that named instance;
   other model instances stay loaded.
6. Use normal chat, a persona, and the persona's already approved MCP tools.
   Tool support and reliability still depend on the chosen model.

The **Memory search model** card is available here as well as in the REST
provider. It configures NC's independent LM Studio embedding connection through
`/v1/embeddings`; chat still uses the Python SDK. Both pages share the same
memory-search selection and index, so enabling the REST chat addon is unnecessary.
If another search provider is selected, a new LM Studio search draft starts with
this page's server address. Existing saved memory-search settings are preserved.

Temperature, Top P, Top K, Repetition Penalty, Min P and maximum output tokens
are mapped to SDK prediction configuration. `-1` means no explicit output cap.
NC's `-1` is translated to the SDK's disabled limit. SDK 1.5.0 incorrectly
serializes its documented `False` value as an enabled boolean limit; this addon
corrects that field in its own request before the channel starts. The installed
SDK and other providers are unchanged. The disabled wire field's positive value
is an inactive schema placeholder, not a limit on the generated reply.
Images prepared by NC as image data URLs and JSON structured output are supported.
SDK errors retain their diagnostics; there is no REST generation fallback.

Like the original provider, SDK history combines all system/developer context
into one leading system message for model-template compatibility (including
Qwen templates). Conversation order, empty turns and native tool identities
remain intact. Generation and exact token counting use the same conversion.

The model catalog refreshes automatically when opening or returning to this
provider's settings. A single read-only native `/api/v1/models` request supplies
model IDs, vision/tool flags and thinking modes, matching the original provider's
catalog discovery. It avoids importing the SDK or opening a WebSocket just to
populate the menu. Discovery stays in the existing cancellable helper process.
Older servers lacking native metadata fall back to SDK model discovery, without
advertising an unverified thinking switch. This does not change SDK generation.
Reported tool-support flags enable the normal tool-capable-model filter; unknown
tool support remains visible. REST generation behavior is unchanged.

## SDK boundaries

Verified against installed Python SDK **1.5.0**. **Enable Thinking** appears only
for models explicitly reporting both `off` and `on` in LM Studio's read-only
`/api/v1/models` metadata. Catalog discovery still works if that metadata is
unavailable; those models retain their default thinking behavior.

SDK 1.5.0 omits the typed thinking option, so an addon-local compatibility adapter
adds the server's `llm.prediction.reasoning.enableThinking` boolean to the checked
SDK request before its channel starts. The choice and model capability are frozen
per turn, including MCP continuations. The adapter checks the raw server-returned
mode before SDK parsing drops the unknown field. A missing or different mode
fails explicitly; it is never silently treated as applied. Other prediction
settings and tool schemas are preserved. The installed package is not patched.
Recognized reasoning fragments are excluded from visible/spoken answers, while
private tool continuations retain the original SDK history.

The installed SDK 1.5.0 client accepts a server host and port but
does not expose server authentication-token or HTTPS/WSS configuration.
Upstream added API-token support in the newer **1.6.0b1 prerelease**, as described
in its [authentication documentation](https://lmstudio.ai/docs/python/getting-started/authentication)
and [release notes](https://github.com/lmstudio-ai/lmstudio-python/releases).
That support must not be confused with the installed stable client's interface.
These are connection capabilities, not model-token settings, and are unnecessary
for the ordinary local `127.0.0.1:1234` connection. The original LM Studio provider
also has no user-facing API-token control. An unsupported address or connection
fails explicitly. No package is installed or upgraded by this addon.

NC's registry, settings, frozen requests, persona permissions and MCP execution
remain authoritative. SDK `.act()` is not used and never dispatches actions.
The SDK's public iterator discards native tool events, so a narrowly checked
`PredictionStream._iter_events()` bridge reads original SDK call IDs and arguments.
Actual SDK serializer/event fixtures cover this dependency. An incompatible SDK
stream fails clearly. Tool JSON schemas are preserved and checked at the SDK
serializer boundary instead of being reconstructed from Python function signatures.

The SDK executes in an isolated helper process so SDK global settings, output and
client lifetime cannot alter the REST provider. The caller's deadline and cancel
token control helper lifetime; no extra model-reply deadline is imposed. Closing
or cancelling a stream reaps its helper. Requests through this provider are
serialized, including cancellation/deadline checks while waiting for that lock.

Both providers execute the original model-preparation policy, including its
profile comparator, active-main tracking, inference lock and preserved auxiliary
leases. A correctly loaded selected model is reused at startup and between turns.
Context rounding uses the original rule; changing two requested values that both
match the current allocation does not force a reload. Reported incompatible
batch size, parallelism, Flash Attention, KV offload or context triggers the same
reload as the original provider. Missing models and cold recovery follow the
original cleanup rules. No addon-local readiness cache bypasses inspection.

SDK settings and its captured server remain independent. Context zero uses the
currently loaded selected model's context, or the original NC profile default
when none is loaded. The existing original inspection and profiled loading
helpers handle model management because SDK 1.5 cannot express the original
parallel-prediction setting. Generation, sampling, thinking, streaming and MCP
rounds continue through the Python SDK. Matching loaded aliases, including older
SDK identifiers, are reused without renaming through an unnecessary reload.

MuseTalk warmup keeps the original cleanup and auxiliary-preservation guard.
Installing/enabling the addon alone does no cleanup. Cancellation controls helper
lifetime; a failed preparation releases the shared lifecycle state.

