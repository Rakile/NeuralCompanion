# MCP Core

User setup: [MCP connections and persona tools](../../docs/addons/mcp.md).
This README describes Core's consumer and storage contracts.

MCP Core owns shared Streamable HTTP client connections to externally managed
MCP servers. Open **Runtime → MCP Core** to configure a server, enable overall
access, and connect manually. Saved servers always start disconnected. Test
connection opens a temporary client session and then disconnects it. Refresh
tools reads the complete catalog before changing permissions.

MCP Core is required Runtime infrastructure and always loads at NC startup,
including when old optional-addon or Tools-category disable flags are saved.
It has no optional-addon loading switch or duplicate Add-ons workspace. Use
**Allow MCP access** on its Runtime page to allow or block MCP use. Turning
access off keeps the core service loaded and disconnects its client sessions.

The optional YouTube Transcript POC is a standalone consumer. Normal chat uses
Core through the optional Chat MCP Tools consumer; Web Search retains its
separate setup. MCP Core itself never installs, launches or stops a server.
Turning overall access off disconnects NC's clients and blocks addon calls.

## Collapsible tool groups

Tools are displayed in independent Show tools/Hide tools sections. Each
configured MCP endpoint remains a single server connection. Tools whose names
use a `namespace__tool` convention appear under that namespace; names without
it stay under the configured server name. This is a display convention, not a
standard MCP field for identifying servers behind a gateway. NC does not infer
origins from ordinary names such as `browser_click` or tool descriptions.

Grouping uses only the catalog received over MCP. It performs no vendor-specific
CLI calls or profile lookups, starts no processes, and makes no server changes.
Groups start collapsed, retain their expansion state during page updates, and
are scoped to the selected connection. Permissions and invocations continue to
use the original connection ID and complete tool name, including any namespace.

An aggregating server must expose a namespace to allow these subgroups. For
example, Docker Gateway can enable its `tool-name-prefix` feature and advertise
names such as `playwright__browser_click` after a gateway restart. NC does not
enable that setting or restart the gateway. Renamed tools require fresh tool
selections; existing permissions are never silently transferred.

References: [MCP tool definitions](https://modelcontextprotocol.io/specification/2025-11-25/server/tools),
[Docker Gateway prefix implementation](https://github.com/docker/mcp-gateway/blob/v0.44.2/pkg/gateway/capabilitites.go).

## Authentication and local state

Supported authentication is none, bearer token, or a custom secret API-key
header. Credentials use Windows Credential Manager through an addon-local
ctypes adapter following NC's existing pattern, scoped to installation path
and server ID. There is no plaintext fallback. Stored values are never returned
to forms; only credential availability is displayed. Credential IO and file
writes run on the addon-owned worker, with nonblocking cached UI snapshots.

The account identity field is a user-maintained label for the authenticated
principal: keep it for a credential refresh of the same account and change it
when switching accounts. Opaque API keys and bearer tokens do not provide a
standard principal introspection API. Editing an authenticated endpoint, account,
authentication mode or header requires re-entering the credential. Endpoint or
principal changes clear grants; same-account credential refresh preserves them.
Saving edits disconnects the current client; reconnect manually.

Configuration, catalogs and permission choices are written atomically to
`runtime/addons/nc.mcp_core/mcp-state-v1.json` in the active installation. That
file contains no credentials, live owner tokens or saved connection state.
Session and preset exports remain empty. Invalid or incompatible stored state
fails closed and requires repair before MCP can be enabled. Vault/state save
failures restore the previous configuration and credential where possible;
failed credential rollback disables access and requires manual repair.

Endpoints must be HTTP(S) without URL user info, query strings or fragments.
Credentials belong in the dedicated authentication fields. HTTP redirects,
environment proxies, OAuth, stdio, resource/prompt browsing, sampling, roots,
elicitation and asynchronous MCP task workflows are not exposed by this addon.
TLS certificate verification uses the HTTP client's defaults. Remote JSON Schema
references are not fetched. Invocation uses the SDK's public request API to
avoid its convenience method's implicit output-schema fetches and discovery.

## Permissions

The page separates request review, addon/server selection and exact tool grants.
Requests show the addon's real display name, purpose, server and declared tool
needs. Requested tools and any already granted tools remain visible; other tools
are available through Show other tools. Approval still grants zero tools.

Consumers can pass `requested_tools=[{"name":"get_transcript", "match":"name_or_namespace"}]`
to `request_access(server_id, reason, ...)`. Match defaults to `exact`; the
explicit `name_or_namespace` mode also recognizes `namespace__get_transcript`.
These are descriptive declarations for user review, never wildcard permissions,
automatic selection, inference from addon identity, or authorization rules.
The user grants each actual full tool name. Existing reason-only requests and
version-one saved state remain readable; optional per-server requested_tools
metadata is persisted with an annotated request. Legacy requests without it are
labelled as undeclared rather than guessed. Removing a server removes its tool
declarations as well as its grants.
Background descriptive refresh uses `update_only=True`; Core checks eligibility
under its policy lock and updates only an existing pending/approved request. It
cannot create a request or reopen rejected/revoked access. An explicit user
request uses the default mode and may submit a fresh request normally.

The Runtime page remembers selected server/addon and open tool groups while NC
is running, including when its Loader recreates the page. This UI-only memory
does not change connection state, reconnect a server or retain form secrets.

Each requesting addon starts pending and denied. Approval alone grants zero
tools. Individual selections and Enable all/Disable all are scoped to one
selected addon and server. Enable all includes only the current catalog.
New, removed/reappearing or input-schema-changed tools require selection again.
Removing a server clears its grants and creates a different ID if re-added.
Temporary disable retains selections; revoke clears approval and selections.

Authorization checks the real host-created owner binding at admission and
immediately before dispatch, including the exact registration/provider and
consumer generations. Cached ports close on unregister, replacement, unload
or consumer reinitialization. Queued work is rejected after grant invalidation;
affected in-flight work is cancelled where possible. Cancellation cannot undo
an operation already performed by the external server. Lost connections and
timeouts never automatically replay tool invocations.

This is an in-process capability boundary for cooperating addons, not operating
system isolation against malicious code with access to Python internals.

## Consumer contract: `mcp.core.v1`

A future consumer declares `services.consume` and obtains its own port using
`context.services.get('mcp.core.v1')`. It needs no MCP SDK objects or imports from
this addon. No method accepts an addon identity or changes approval/grants.

| Method | Result data |
| --- | --- |
| `list_servers()` | Saved connection IDs, display names and status; no endpoints, authentication or grants; grants no access |
| `request_access(server_id, reason='')` | Request/access state for the actual caller |
| `access_status(server_id='')` | Approval, enabled state and overall switch |
| `list_tools(server_id)` | Copied permitted tool descriptions, schemas and server identity |
| `probe_servers(server_ids)` | IDs of currently connected, responsive servers on which this caller has permitted tools |
| `invoke_tool(server_id, tool_name, arguments)` | An immediately returned `call_id` |
| `call_status(call_id)` | Queued/running state or the eventual tool result |
| `cancel_call(call_id)` | Cancellation acknowledgement; completion is not guaranteed |

`probe_servers` accepts up to 32 server IDs and checks existing connected
sessions in parallel using one read-only MCP `tools/list` request per server.
Checks have a two-second bound, do not start connections or invoke tools, and
return only servers for which the caller currently has permitted tools. A busy,
unresponsive, disconnected or revoked server is omitted. This is a point-in-time
check; dispatch still rechecks permissions and connection status.

Every return is a detached JSON-compatible mapping with `ok`, `status`, `error`
and `data`. Poll queued/running calls until terminal. Successful/tool-error data
contains `result` (including MCP `content`, `structuredContent`, `isError` and
other useful result fields) and `completion_confirmed`. Statuses distinguish
`denied`, `unavailable`, `protocol`, `tool_error`, `cancelled`, `unconfirmed`,
`busy`, `invalid_arguments` and `invalid_configuration`. Error codes are static;
raw SDK/HTTP/vault exceptions are not exposed. `unconfirmed` and cancellation
mean the server may already have performed the operation. Call IDs and their
results are restricted to the submitting owner generation.

Limits: eight connections, 32 outstanding calls, one dispatched call per server,
10-second connect/catalog timeout and 30-second tool timeout. Completed results
retain at most 128 entries; catalogs, argument size and result size are bounded.
The supervised loop owns each connection's async context in a single task.

Management is separate: finite `runtime.mcp_core.snapshot` and
`runtime.mcp_core.manage` capabilities serve the native adapter. They are never
part of the consumer port. Context-local diagnostic suppression protects SDK and
HTTP logs, including newly created backend loggers, without suppressing unrelated
tasks. Known connection secrets are redacted from returned remote values.

