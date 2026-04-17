# Chat Provider Addons

Chat providers can be added without editing `qt_app.py` or the core runtime. NC ships its release providers as addons, and third-party providers register themselves through the addon service `qt.chat_providers`.

This guide describes the currently supported provider-addon contract. Treat the field names and handler expectations below as the interface NC expects third-party providers to follow.

## Where to put an addon

Create a folder under `addons/`:

```text
addons/my_provider/
  addon.json
  main.py
```

The manifest needs an addon id, a name, `entry_point`, and `enabled: true`. Chat provider addons usually do not need UI tab permissions unless they also create custom tabs.

## Provider contract

Inside `Addon.initialize(context)`, get the service:

```python
chat_service = context.get_service("qt.chat_providers")
```

Then call `register_provider(...)` with:

- `provider_id`: stable lowercase id, for example `claude`.
- `label`: user-facing dropdown label.
- `description`: short provider description.
- `model_list_handler(quiet)`: returns model ids or model dicts with at least `id`.
- `completion_handler(params, additional_params)`: returns one complete assistant string.
- `stream_handler(params, additional_params)`: yields assistant text chunks.
- `connection_check_handler()`: returns `{"ok": bool, "detail": str}`.
- `api_key_getter` and `base_url_getter`: optional helpers used by shared UI/runtime checks.
- `metadata["config_fields"]`: Host-card fields to render for this provider.
- `metadata["generation_fields"]`: provider-specific generation controls rendered in the Chat Runtime card.

### Handler expectations

The provider registry currently accepts these handlers:

- `model_list_handler(quiet: bool) -> list[Any]`
- `completion_handler(params: dict[str, Any], additional_params: dict[str, Any] | None) -> str`
- `stream_handler(params: dict[str, Any], additional_params: dict[str, Any] | None) -> Iterable[str]`
- `connection_check_handler() -> dict[str, Any]`

If a handler is omitted, NC may fall back to shared defaults where possible, but a real provider addon should implement the full set if it wants normal model refresh, completion, streaming, and connection reporting.

Recommended return conventions:

- `model_list_handler` may return plain model ids or dicts with at least `id`.
- `completion_handler` should return one complete assistant text string.
- `stream_handler` should yield assistant text chunks in order.
- `connection_check_handler` should return `{"ok": bool, "detail": str}` and may include extra diagnostics.

### Lifecycle

Register providers in `Addon.initialize(context)` and unregister them in `shutdown()`.

The reference pattern is:

```python
def initialize(self, context):
    super().initialize(context)
    self._chat_service = context.get_service("qt.chat_providers")
    if self._chat_service is None:
        return None
    self._chat_service.register_provider(...)
    return None

def shutdown(self):
    if getattr(self, "_chat_service", None) is not None:
        self._chat_service.unregister_provider(PROVIDER_ID)
    return None
```

When an addon is disabled in the Addons tab, it will not register on the next launch. If the disabled provider was selected, NC falls back to the default available provider.

### What belongs to the addon

The addon should own provider-specific concerns such as:

- API key lookup and base URL selection.
- Translating NC payloads into the provider API shape.
- Provider-specific request fields such as `max_tokens`, `top_k`, or API version headers.
- Streaming protocol differences.
- Connection checks and provider-specific error reporting.

The core should remain responsible for:

- listing registered providers,
- rendering provider metadata,
- choosing the current provider and model,
- and routing chat requests to the selected provider handlers.

Provider settings saved by the Host card can be read with:

```python
chat_service.get_provider_setting("my_provider", "api_key")
chat_service.get_provider_settings("my_provider")
```

## Runtime payload shape

NC calls provider handlers with a mostly OpenAI-style chat payload. The core always supplies `model` and `messages`; provider `generation_fields` decide which generation parameters are added.

```python
{
    "model": "model-id",
    "messages": [{"role": "system|user|assistant", "content": "..."}],
    "temperature": 0.8,
    "top_p": 0.95,
    "max_tokens": 1024,
}
```

Each `generation_fields` entry can include:

- `id`: stable setting id, for example `temperature`.
- `label`: user-facing label.
- `kind`: `float`, `int`, `bool`, `text`, `select`, or `note`.
- `default`, `min`, `max`, `step`, `decimals`: renderer and fallback values.
- `request_key`: optional request payload key if it differs from `id`.
- `request_location`: `params`, `additional_params`, or `none`.
- `omit_if`: optional value or list of values that should not be sent.
- `description`: tooltip/help text.

### Metadata shape

`config_fields` are rendered in the Host card under `Provider Settings`.
`generation_fields` are rendered in the Chat Runtime card under `Generation Settings`.

Common field kinds:

- `float`
- `int`
- `bool`
- `text`
- `select`
- `note`

For `select` fields, the addon should provide stable option ids and user-facing labels. For `note`, NC should treat the field as informational only.

Useful metadata conventions:

- `request_key` lets a field map to a different request field name than its `id`.
- `request_location` controls whether the value goes into `params`, `additional_params`, or stays UI-only.
- `omit_if` can suppress a value when it is a default or disabled sentinel.

### Model list shape

NC accepts either:

- a list of model ids, or
- a list of model dicts with at least `id`.

If a model dict includes capability flags such as `supports_images`, the UI may use them for filtering and capability summaries.

If a provider uses another API shape, translate inside the addon. The Claude addon is the reference example: it converts system messages into the Anthropic `system` field, converts chat turns to `messages`, maps `stop` to `stop_sequences`, and parses server-sent streaming text deltas.

### Contract stability

The goal is for this provider contract to stay stable for third-party addons. Prefer additive metadata keys and optional handlers over changing existing meanings.
