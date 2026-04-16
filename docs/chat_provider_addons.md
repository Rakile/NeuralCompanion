# Chat Provider Addons

Chat providers can be added without editing `qt_app.py` or the core runtime. Built-in providers stay in `core/chat_providers.py`; third-party providers register themselves through the addon service `qt.chat_providers`.

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

Provider settings saved by the Host card can be read with:

```python
chat_service.get_provider_setting("my_provider", "api_key")
chat_service.get_provider_settings("my_provider")
```

## Runtime payload shape

NC currently calls provider handlers with an OpenAI-style chat payload:

```python
{
    "model": "model-id",
    "messages": [{"role": "system|user|assistant", "content": "..."}],
    "temperature": 0.8,
    "top_p": 0.95,
    "max_tokens": 1024,
}
```

If a provider uses another API shape, translate inside the addon. The Claude addon is the reference example: it converts system messages into the Anthropic `system` field, converts chat turns to `messages`, maps `stop` to `stop_sequences`, and parses server-sent streaming text deltas.

## Disable behavior

When an addon is disabled in the Addons tab, it will not register on the next launch. Built-in providers continue to work. If the disabled provider was selected, NC falls back to the default available provider.
