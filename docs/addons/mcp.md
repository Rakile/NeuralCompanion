# MCP connections and persona tools

NC can use tools exposed by externally managed Model Context Protocol (MCP)
servers. The core and its consumers have different responsibilities:

| Component | Purpose | Where to configure it |
| --- | --- | --- |
| **MCP Core** | Shared connections, credentials, addon approval and exact tool grants | **Runtime → MCP Core** |
| **Chat MCP Tools** | Lets normal chat offer approved tools to a saved persona | **Persona → MCP** |

MCP Core is required runtime infrastructure. It stays loaded; **Allow MCP access**
controls whether it can be used. Optional consumers have their own addon loading
and access settings. NC's separate [Web Search](web_search.md) workflow retains
its own setup; enabling one does not configure the other.

## Connect an existing MCP server

1. Start the server outside MCP Core and obtain its **Streamable HTTP** endpoint.
   Use the URL supplied by the server, including its `/mcp` path when applicable.
2. Open **Runtime → MCP Core**, turn on **Allow MCP access**, and choose **New server**.
3. Enter a recognizable **Name**, the **Endpoint**, and authentication:
   - **none** for an unauthenticated server;
   - **bearer** with the token in **Secret**;
   - an API-key header with its required header name and secret value.
4. For authenticated servers, set **Account identity** to a label identifying
   the account/principal. It is not an automatically verified username.
5. Choose **Save server**, select the saved connection and click **Connect**.
6. Use **Refresh tools** to obtain its current catalog. **Test connection** uses
   a temporary session; it does not leave a persistent connection open.

Paste a bearer token value into Secret, rather than a whole `Authorization:`
header. Credentials use the Windows credential vault and are not returned to
the form or included in normal session exports. A blank secret preserves an
existing credential only for the same endpoint/account configuration. Follow
the form's prompt to re-enter it after changing authentication or principal.

Saved connections start **disconnected after restarting NC**. Reconnect them
explicitly. Turning overall access off disconnects NC's sessions without
unloading Core or stopping the external servers. Saving connection edits also
requires reconnection. Changing the endpoint/account can invalidate grants.

The current Core client supports Streamable HTTP with the authentication modes
above. It does not expose stdio launch commands, OAuth login, MCP resources or
prompts browsing. Core does not install, launch or stop third-party servers.

## Approve an addon and choose its tools

An addon first submits an access request, including its purpose and declared
tool needs. In MCP Core, review the requesting addon's name, selected server
and requested tools. Approve the addon, then select its **exact tools**.

**Approval alone grants no tools.** Approval, enabled addon access and checked
tool grants are separate controls. A grant for Chat MCP Tools does not grant
access to Companion Chess. Revoking access or changing a tool's
schema can make it unavailable until you review and select it again.

Tool sections can be expanded independently. A tool-name namespace such as
`namespace__get_transcript` allows display grouping. An aggregating endpoint
without such names remains one server group; NC does not guess hidden server
origins or use gateway-specific discovery commands.

## Give a saved persona tools for normal chat

1. Enable **Chat MCP Tools** in Addon Manager if it is not loaded, then restart
   NC when requested. Connect the server in MCP Core.
2. Select a saved persona, open its **MCP** settings and choose the connection.
3. Use **Request bridge access**, describing the intended tool when useful.
4. In **Runtime → MCP Core**, approve **Chat MCP Tools** and grant the exact
   tools it needs.
5. Return to the persona's MCP page and check which of those granted tools this
   persona may use. Other personas start without those assignments.
6. Use that persona in normal chat with a provider/model supporting native tool
   calling, and ask it to perform the task.

For example, assign a granted transcript tool and ask:

> Retrieve the transcript for this YouTube URL and explain what the clip is about: …

The model receives tool descriptions and JSON argument schemas and chooses
calls. You do not need to invent a separate argument protocol in the persona's
prompt. The tools offered are limited by the connected server, Core grants,
persona assignments and supported provider/model. An assignment does not make
an offline server available or make a model reliable at tool use.

NC checks assigned connections before offering tools each turn. An unavailable
or busy server can be omitted for that turn while its saved assignments remain.
Explicitly unsupported models do not receive MCP offers; unknown capability
metadata is not evidence that the model supports reliable tool calling.

**Regenerate** can use the persona's currently allowed MCP tools like a normal
reply, so it can cause fresh remote actions. It is not just a replay of old
tool results. Review the task before regenerating a reply that changes state.

Streaming assistant text can reach chat and speech as it arrives. Tool arguments,
internal reasoning and raw protocol messages are not speech. Large tool results
still consume the model's input context; leave room for the answer within the
provider's context budget. See [Chat and speech](../manual/chat-and-tts.md).

### Failures and a correction opportunity

A completed server-reported tool error is returned to the model with one
recovery episode for the turn. It can re-read state and submit a corrected call
within the normal execution budget. A second tool error ends that recovery.
Transport failures, lost permissions, cancellation and uncertain completion do
not trigger automatic replay. A cancelled call may already have changed remote
state; verify its result before requesting the action again.

## Local state and troubleshooting

Core state lives under `runtime/addons/nc.mcp_core/mcp-state-v1.json`; credentials
remain in the vault. Persona tool assignments are addon-local, tied to stable
persona IDs and excluded from ordinary persona/session/preset exports. Keep the
relevant addon state when moving an installation, and recheck grants and secrets.
Do not edit credentials into a JSON state file. Damaged state blocks access and
requires recovery rather than silently granting defaults.

| Symptom | Check |
| --- | --- |
| Saved server is disconnected | Select it and Connect; saving or restarting does not auto-connect |
| Addon approved but no tool works | Allow MCP access, enabled addon access, exact grants and a live connection |
| Persona sees no tools | Grant Chat MCP Tools, assign tools to that saved persona, and check provider/model support |
| Tools vanished after refreshing | Review changed names or schemas and select the current tools again |
| Long transcript fails at the model | Read the provider's error and increase the available context or reduce the requested result |
| One long gateway tool list | Namespace information must come from the server; grouping cannot invent it |

Developer contracts: [MCP Core](../../addons/mcp_core/README.md),
[Chat MCP Tools](../../addons/chat_mcp_tools/README.md), and
[addon capability contracts](../addon_capability_contracts.md).
For a state-changing example, see [Companion Chess](companion_chess.md).
