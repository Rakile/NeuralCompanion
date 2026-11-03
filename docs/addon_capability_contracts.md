# Addon Capability Contracts

This is the runtime boundary reference for the native QML desktop. Use the
[quickstart](addon_quickstart.md) for UI integration and the
execution and ownership section below for ownership. Historical widget
builders and typed UI ports under `ui/runtime` are not current extension APIs.

## Invocation and results

[AddonManager](../core/addons/manager.py) owns runtime dispatch:

| Method | Behavior |
| --- | --- |
| `invoke_capability(capability, payload)` | Calls initialized addons until the first non-`None` result |
| `invoke_all_capabilities(capability, payload)` | Collects every non-`None` result from initialized addons |
| `invoke_addon_capability(addon_id, capability, payload)` | Targets one initialized addon |
| `invoke_service_capability(service_id, capability, payload, **metadata_match)` | Resolves a manifest service and targets its initialized addon |

The ordinary manager calls return the addon's value or `None`; failures are
logged. `invoke_addon_capability_strict(...)` exists for callers that must
propagate a handler failure. It still returns `None` for an unavailable addon.
Do not replace an expected no-result contract with implicit initialization.

Native adapters call the UI-facing facade's addon port, which returns a command
result with `accepted`, `value`, and failure information. This differs from the
manager's raw return shape. See
[AddonSessionNativeAdapter](../ui/qml_bridge/adapters/addon_session.py); do not
paste its `.accepted` checks around a direct manager return.

Capability payloads for new integrations are copied value mappings: settings,
identifiers, paths and domain data. Do not carry a main window, QML bridge,
backend, `ApplicationFacade`, `RuntimeContext`, generic service locator,
callable, or arbitrary method name. Existing narrowly owned streaming contracts
must be inspected separately; they are not generic delegation APIs.

Keep names, payload keys and return semantics stable. Add a separate route when
the shape changes, and preserve established nullable behavior when an addon is
disabled, absent or misconfigured.

## Manifest services

Current routing identities include:

- `avatar_provider_registry`, matched with `provider_id`.
- `tts_backend_service`, matched with `backend_id`.
- `chat_provider_registry`.
- `sensory_registry`, matched with `provider_id`.
- `sensory_prompt_contributor`.
- `service_registry` for addon-published peer services.

See [manifest parsing](../core/addons/manifest.py) and
[contribution definitions](../core/addons/contributions.py). A service declaration
is routing metadata; the addon must still register/implement the service.
Historical target/object names in contribution metadata do not require a
Designer widget in the native host.

### Opt-in owner-bound peer services

Providers declaring `services.register` may explicitly use
`context.services.register_consumer_factory(name, factory, metadata=None)`.
The factory receives a host-created `AddonOwnerBinding` for the real consuming
generation. It runs outside registry/owner locks; check the binding on every
port operation. Its `closed` state includes consumer/provider closure and
registration replacement or removal. Unscoped global lookup and catalog entries
do not expose the factory. Ordinary `register/get/list` service behavior remains
unchanged. A caller-supplied addon ID is not proof of ownership.

Consumers still declare `services.consume` and use `context.services.get(name)`.
This is an in-process contract, not a sandbox against malicious Python code.
See [MCP Core's versioned consumer contract](../addons/mcp_core/README.md) for a
concrete use with separate user management and per-addon tool grants.

## Addon context and host ports

`initialize(context)` receives
[AddonContext](../core/addons/context.py). It exposes `context.host`, a
generation-scoped `AddonHostContext`, and named `context.capabilities` ports.
[AddonCapabilities](../core/runtime/addons.py) maps those ports to the native
host services. Examples:

| Named port | Existing service identity / purpose |
| --- | --- |
| `providers` | `qt.chat_providers`: provider registration and request operations |
| `sensory_targets` | `qt.sensory`: source and prompt-contributor registration |
| `runtime_config` | `qt.runtime_config`: finite runtime settings operations |
| `shell_session` | Session snapshot / settings-change notification projection |
| `visual_reply` | `qt.visual_reply`: native visual settings/generation operations |
| `hotkeys` | `qt.hotkeys`: finite binding and action operations |

The native composition is in
[native_addons.py](../ui/qml_bridge/native_addons.py) and
[native_host_services.py](../ui/qml_bridge/native_host_services.py); shared finite
implementations are in [runtime_services.py](../ui/qml_bridge/runtime_services.py).
The former `core.addons.qt_host_services` / `ui/runtime` widget host is removed.
Do not manufacture a port by passing a raw facade into addon initialization.

## Current capability examples

These are examples verified against the named addon entry points, not an
exhaustive discovery API. Check the implementation for each payload and result.

### Session-backed native controls

`runtime.session.export` returns explicit addon state.
`runtime.session.import` accepts `{"state": ...}` and applies that state.
[Mock Heart Rate](../addons/mock_heart_rate/main.py) and
[shared sensory supervisors](../core/addons/sensory_supervisor.py) implement this
pair for [AddonSessionNativeAdapter](../ui/qml_bridge/adapters/addon_session.py).
This routing pair does not replace the manager's session/preset lifecycle hooks.

Supervisors also expose `runtime.supervisor.snapshot`,
`runtime.supervisor.reset_prompt`, and `ui.tab_enabled`. The latter is a plain
state command/query despite the retained `ui` prefix; it does not construct a
widget or grant capture/proactive-speech permission.

### TTS and avatars

Existing compatibility names such as `runtime.collect_config`,
`runtime.update_config_from_widgets`, `runtime.status_snapshot`,
`runtime.restart_sensitive_widgets`, and `runtime.refresh_resource_widgets`
remain on some TTS addons. The native implementations can use config mappings,
empty lists or no-op results rather than widgets. Preserve those exact meanings
where callers depend on them; do not infer a new widget API from the name.
See [PocketTTS](../addons/pockettts/main.py) and
[Chatterbox](../addons/chatterbox_tts/main.py).

PocketTTS retains `ui.ensure_python_path`, `ui.apply_python_changed`,
`ui.reset_python_to_default`, and `ui.browse_python`. Native file selection owns
the picker; `ui.browse_python` returns no result in the current entry point.
Gemini's finite routes include `runtime.gemini_tts.snapshot`, `.update`,
`.models`, and `.check_connection`; see
[Gemini TTS Preview](../addons/gemini_tts_preview/main.py).

[MuseTalk](../addons/musetalk_avatar/main.py) owns pack operations such as
`runtime.discover_avatar_packs`, `runtime.get_avatar_pack`,
`runtime.normalize_enabled_pack_emotions`, `runtime.pack_catalog`,
`runtime.select_pack`, and its `runtime.preview.*` / `runtime.pipeline.*`
operations. Preview streaming has its own lifecycle and payload contract.
[VSeeFace](../addons/vseeface_avatar/main.py) owns `runtime.body_profiles.*`,
`runtime.hand.*`, and `runtime.create_adapter`. Neither is a generic backend
reach-through surface.

### Visual Reply

[Visual Reply](../addons/visual_reply/main.py) handles `runtime.generation`,
`runtime.current_state`, `runtime.set_state`, `runtime.output_base`,
`runtime.client`, style/prompt helpers, response-image writing, and finite
library operations. See [Visual Reply addons](visual_reply_addons.md).
The retained `ui.panel_class` / `visual_reply.build_runtime_panel` names return
no result; there is no native QWidget panel replacement contract.

## MCP Core consumer connection discovery

Consumers obtain the owner-bound `mcp.core.v1` port through
`context.services.get(...)` with `services.consume`. Its additive
`list_servers()` query returns the normal result envelope with `data` entries
containing only `id`, `name` and connection `status`. It is available before
approval so a consumer can choose a connection for `request_access(server_id)`;
it grants no tool access and returns no endpoints, authentication, credentials,
permission maps or other addons' state. Closed/stale bindings are denied.
The optional `nc.chat_mcp_tools` demonstrates requesting access,
discovering granted tools, invoking and polling/cancelling through this port.

`request_access(server_id, reason='', requested_tools=[...])` accepts optional
keyword-only descriptive tool requirements. Each declaration is `{name,match}`;
match is `exact` by default, or explicitly `name_or_namespace` to also recognize
`namespace__name`. Core displays declarations and available matching full names
for human review; they never grant access or authorize a pattern. Approval alone
still grants zero tools, and only individually selected exact names are usable.
Legacy reason-only requests remain valid. `access_status` returns the caller's
own `requested` flag and `requested_tools` for that connection, allowing an
addon to update descriptive metadata for an existing request without changing
approval or grants. Requested-tool metadata is optional in existing v1 state.
For descriptive background refresh, pass `update_only=True`. Under the policy
lock this updates only an existing pending/approved request and cannot reopen a
concurrently rejected/revoked request or create one. Ordinary explicit access
requests keep their existing re-request behavior.

## Native UI boundary

A native adapter retains the UI-facing facade and publishes immutable
`NativeSurface` / `NativeControl` descriptions. Addon domain behavior stays
behind finite commands and snapshots. The host explicitly registers adapters;
manifest `native_qml` metadata alone does not auto-discover them. See
[native contracts](../ui/qml_bridge/native_contracts.py),
[registry](../ui/qml_bridge/native_registry.py), and
[application bridge](../ui/qml_bridge/application_bridge.py).

Names such as `real_ui.*`, `legacy.*`, and older `shell.*` factories in migration
records describe earlier integrations or retained compatibility routes. Do not
advertise them as a new native extension mechanism.

## Execution and ownership

Commands must preserve runtime/session/turn/route/addon-owner authority. Queries
return immutable snapshots or copied data rather than mutable runtime services.
Events carry low-frequency notifications. Provider tokens, audio samples, TTS
chunks, amplitude samples and image bytes use their owned streaming paths, not
the general addon event bus.

Manifest `execution_lanes` describe allowed `ui`, `worker`, `external_process`
and narrowly approved `realtime` work. The host owns lane construction and
teardown. Register background work, child processes and resources through the
owner-scoped task facilities in `context.tasks`; do not create unsupervised
long-lived threads or processes. Qt work uses the host UI dispatcher. Do not
cancel or replace another addon's tasks, services or generation.

Closing the addon context invalidates queued UI work, subscriptions, service
registrations, tasks, resources and processes for that generation. Check
shutdown behavior as well as initialization.

## Persona chat MCP consumer

Optional `nc.chat_mcp_tools` consumes only `mcp.core.v1`; its `chat_mcp.conversation`
capability offers native schemas, dispatches exact alias bindings and guards result
publication. `chat_mcp.snapshot` reads memory and `chat_mcp.command` enqueues settings
work. Persona assignments are installation-local addon storage, separate from Core
approval/grants and portable persona/session data. Runtime projects the active stable
persona ID into accepted-turn snapshots. New/imported personas get fresh identities;
existing personas retain theirs. Native provider adapters declare
`metadata.native_tool_protocol_v1` (`responses`, `chat_completions`, `anthropic`,
or `openai` for its official/custom endpoint selection). This is captured in the
immutable provider binding and exposed as `FrozenChatProviderContext.native_tool_protocol`.
The shared loop uses capability rather than a provider-ID allowlist. Adapters
must handle `nc_conversation_tools_v1` and return a validated ToolRound envelope;
ordinary chat stays unchanged. Installed LM Studio/OpenAI/Claude/Ollama/DeepSeek/xAI
adapters implement the contract; actual models/endpoints must support tools.
Opaque reasoning/thinking continuation is replayed only inside the native round,
with exact call IDs/results, and omitted from speech/history/communication traces.
`metadata.native_tool_streaming_v1: true` additionally opts the frozen adapter into
typed native stream frames: answer-text deltas followed by one validated ToolRound.
All installed native adapters support this. Tool argument/reasoning deltas never
enter speech; only completed, validated calls can execute. LM Studio direct and
worker paths use the same frame codec. Chat preview/TTS receive answer deltas
before the provider finishes. Persona/turn publication guards remain active for
each chunk. MCP IO timeouts bound pending calls and do not expire valid model
generation or speech. Token-limit failures expose allowlisted explanations/counts,
not raw provider bodies or generic exception-class-only messages.

`ConsumerPort.invoke_tool(..., is_current=callable)` optionally narrows an existing
grant at admission, queued dispatch and in-flight invalidation. The trusted local
callable must be cheap, fail closed, and never call Core (it runs under Core's policy
lock). It is not a model argument, grant, SDK object or serializable contract field.
`expected_schema_fingerprint` optionally requires an exact advertised schema at
admission: SHA-256 of UTF-8 JSON with sorted keys, compact comma/colon separators,
and no non-finite numbers. Queued jobs retain it and cannot dispatch after schema
drift, even when Core grants the newer schema.

## Prohibited backdoors and compatibility

Do not import `engine`, `core.engine_access` or `ui.runtime.engine_access` from
new addon production code. Do not add arbitrary backend delegation or give an
addon the application's composition root. Compatibility facades may protect
existing sessions, presets, config keys and public routes; they must not grow
new domain behavior or initialize a disabled addon to satisfy an old lookup.

Preserve current provider frozen execution v1 and private/public configuration
separation; see [chat provider contracts](chat_provider_addons.md). Preserve
session schemas, portable preset keys and secret policy; see
[state and presets](addon_state_and_presets.md).
