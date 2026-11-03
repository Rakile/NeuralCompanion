# Chat MCP Tools

For setup and troubleshooting, use [MCP connections and persona tools](../../docs/addons/mcp.md).

Optional addon `nc.chat_mcp_tools`: generic MCP tools in ordinary chat, with no YouTube/Docker/chess special cases and no dependency on Orb. Requires MCP Core and a restart after installation.

## Try it

1. In Runtime → MCP Core, allow MCP access and connect your HTTP server.
2. In Persona → MCP, select a saved persona and Core connection. Request bridge access, optionally naming the desired tool (for example `get_transcript`).
3. In Runtime → MCP Core, approve **Chat MCP Tools**, then explicitly grant its required tools. Approval alone grants nothing. Other addons require their own grants.
4. Return to Persona → MCP and check the granted tool(s) this persona may use. Other personas start with no tools. Checkboxes refer to the selected connection; the saved summary covers all connections.
5. With a tool-capable model selected, open normal chat with that persona and ask: “Get the transcript for this URL and explain what the clip is about: <YouTube URL>”. The model supplies schema arguments and can follow returned pagination cursors. Captions are retrieved; the addon does not transcribe audio or watch a video.

Native adapters: **LM Studio, LM Studio SDK, OpenAI (official Responses or a tool-compatible Chat Completions endpoint), Claude, Ollama, DeepSeek and xAI**. The selected model and endpoint must support native tool calling. Future adapters opt in through the same versioned provider capability and implement the native round contract. Undeclared adapters retain ordinary text chat. Provider/model selection is never changed automatically. Conflicting structured-output constraints and models without native tool support cannot execute this flow. Text/structured JSON MCP results are supported; image/audio/blob MCP results fail explicitly. No server startup/installation, Docker-specific discovery, OAuth, stdio or arbitrary client-side execution is added.

## Authority and lifetime

Before each normal-chat tool offer, Chat MCP Tools checks its assigned,
permitted connections through Core. Only servers whose existing sessions respond
to the bounded read-only check are advertised to the model. Checks run in
parallel and can add up to two seconds; busy or unresponsive servers are omitted
for that turn. Saved persona assignments and grants are retained for reconnection.
If a server fails after the check, the normal execution guards still apply.

`persona-tools-v1.json` in this addon's local storage maps stable persona IDs to exact Core connection ID, full tool name and schema fingerprint. It is excluded from persona/session/preset exports. Existing IDs are preserved; new/imported records saved into empty slots receive unique IDs. Renaming/reordering keeps identity. Schema changes require a fresh selection. Core connection, approval and exact grants remain authoritative.

Model-facing aliases include a readable, provider-safe tool name and a stable identity suffix, and map to one exact connection/tool. Collisions fail closed. Each tool-enabled request instructs the model to call the appropriate tool and report success only after confirmation; models may still fail to follow those instructions. Dispatch requires the same accepted-turn persona and live persona, unchanged assignment generation, current turn/caller and current Core grants/schema/connection. A local optional `is_current` callable narrows Core admission, queued dispatch and in-flight validity. It cannot grant authority and is never model-supplied, persisted or serialized. Core evaluates it under the policy lock, so it must not call into Core. Cancellation cannot undo remote execution; uncertain outcomes are not retried.

Limits: 32 assigned tools/persona, 256 personas in local policy, 32 calls/turn, 12 model rounds, 120 seconds per pending MCP call, 32,000 characters/schema and 256,000 characters/result. The MCP call timer does not expire a valid chat turn while its model generates an answer or speech is delivered. Core also enforces argument schemas, caller/connection isolation and queue/time limits. Stale/cancelled output is discarded. Results are external evidence, never permission grants. Tool-call protocol and internal reasoning do not reach speech.

MCP and Orb offers compose, preserving Orb-only behavior and ordinary chat without assignments. With streaming enabled, native assistant answer-text deltas reach the existing chat preview and speech chunker as they arrive; completed tool arguments are validated before invocation. Tool JSON and internal reasoning stay silent. Providers advertise this through `native_tool_streaming_v1`, captured with the frozen turn. Completion mode remains buffered. UI commands enqueue addon-owned work; UI snapshots read memory only. This addon persists no credentials, transcripts or tool arguments. Disable Chat MCP Tools in Add-ons to remove its behavior after restart.

