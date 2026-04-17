from __future__ import annotations

import json
import os
import threading
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from openai import OpenAI


DEFAULT_PROVIDER_ID = "lmstudio"
LMSTUDIO_BASE_URL = "http://127.0.0.1:1234/v1"
LMSTUDIO_API_KEY = "lm-studio"

ChatModelListHandler = Callable[[bool], list[Any]]
ChatClientFactory = Callable[[], Any]
StringGetter = Callable[[], str]
ChatCompletionHandler = Callable[[dict[str, Any], dict[str, Any] | None], str]
ChatStreamHandler = Callable[[dict[str, Any], dict[str, Any] | None], Iterable[str]]
ChatConnectionCheckHandler = Callable[[], Any]


def _env_value(*names: str, fallback: str = "") -> str:
    for name in names:
        value = str(os.environ.get(name, "") or "").strip()
        if value:
            return value
    return str(fallback or "").strip()


def _fetch_json_with_bearer(url, api_key, *, timeout=10.0):
    headers = {"Accept": "application/json"}
    token = str(api_key or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(str(url), headers=headers)
    with urllib.request.urlopen(request, timeout=float(timeout)) as response:
        raw_payload = response.read()
        charset = None
        try:
            charset = response.headers.get_content_charset()
        except Exception:
            charset = None
        encoding = charset or "utf-8"
        return json.loads(raw_payload.decode(encoding, errors="replace"))


@dataclass
class ChatProvider:
    id: str
    label: str
    description: str = ""
    order: int = 1000
    client_factory: ChatClientFactory | None = None
    model_list_handler: ChatModelListHandler | None = None
    completion_handler: ChatCompletionHandler | None = None
    stream_handler: ChatStreamHandler | None = None
    connection_check_handler: ChatConnectionCheckHandler | None = None
    api_key_getter: StringGetter | None = None
    base_url_getter: StringGetter | None = None
    metadata: dict[str, Any] | None = None

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": str(self.id or "").strip(),
            "label": str(self.label or "").strip(),
            "description": str(self.description or "").strip(),
            "order": int(self.order),
            "metadata": dict(self.metadata or {}),
        }


class ChatProviderRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._providers: dict[str, ChatProvider] = {}

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        description: str = "",
        order: int = 1000,
        client_factory: ChatClientFactory | None = None,
        model_list_handler: ChatModelListHandler | None = None,
        completion_handler: ChatCompletionHandler | None = None,
        stream_handler: ChatStreamHandler | None = None,
        connection_check_handler: ChatConnectionCheckHandler | None = None,
        api_key_getter: StringGetter | None = None,
        base_url_getter: StringGetter | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatProvider:
        provider = ChatProvider(
            id=str(provider_id or "").strip().lower(),
            label=str(label or "").strip(),
            description=str(description or "").strip(),
            order=int(order),
            client_factory=client_factory,
            model_list_handler=model_list_handler,
            completion_handler=completion_handler,
            stream_handler=stream_handler,
            connection_check_handler=connection_check_handler,
            api_key_getter=api_key_getter,
            base_url_getter=base_url_getter,
            metadata=dict(metadata or {}),
        )
        if not provider.id:
            raise ValueError("Chat provider id is required.")
        if not provider.label:
            raise ValueError(f"Chat provider '{provider.id}' is missing a label.")
        with self._lock:
            self._providers[provider.id] = provider
        return provider

    def unregister_provider(self, provider_id: str) -> bool:
        provider_key = str(provider_id or "").strip().lower()
        if not provider_key:
            return False
        with self._lock:
            return self._providers.pop(provider_key, None) is not None

    def get_provider(self, provider_id: str) -> ChatProvider | None:
        provider_key = str(provider_id or "").strip().lower()
        if not provider_key:
            return None
        with self._lock:
            return self._providers.get(provider_key)

    def list_providers(self) -> list[ChatProvider]:
        with self._lock:
            providers = list(self._providers.values())
        return sorted(providers, key=lambda item: (int(item.order), str(item.label or "").lower(), str(item.id or "").lower()))


_REGISTRY = ChatProviderRegistry()
_SETTINGS_LOCK = threading.RLock()
_RUNTIME_PROVIDER_SETTINGS: dict[str, dict[str, str]] = {}


def register_provider(**kwargs) -> ChatProvider:
    return _REGISTRY.register_provider(**kwargs)


def unregister_provider(provider_id: str) -> bool:
    return _REGISTRY.unregister_provider(provider_id)


def get_provider(provider_id: str) -> ChatProvider | None:
    return _REGISTRY.get_provider(provider_id)


def list_providers() -> list[ChatProvider]:
    return _REGISTRY.list_providers()


def set_provider_settings(settings_map: dict[str, Any] | None) -> None:
    normalized: dict[str, dict[str, str]] = {}
    if isinstance(settings_map, dict):
        for provider_id, raw_fields in settings_map.items():
            provider_key = str(provider_id or "").strip().lower()
            if not provider_key or not isinstance(raw_fields, dict):
                continue
            field_values = {
                str(field_id or "").strip(): str(value or "").strip()
                for field_id, value in raw_fields.items()
                if str(field_id or "").strip()
            }
            normalized[provider_key] = field_values
    with _SETTINGS_LOCK:
        _RUNTIME_PROVIDER_SETTINGS.clear()
        _RUNTIME_PROVIDER_SETTINGS.update(normalized)


def get_provider_settings(provider_id: str | None = None) -> dict[str, Any]:
    with _SETTINGS_LOCK:
        if provider_id is None:
            return {key: dict(value) for key, value in _RUNTIME_PROVIDER_SETTINGS.items()}
        provider_key = str(provider_id or "").strip().lower()
        return dict(_RUNTIME_PROVIDER_SETTINGS.get(provider_key, {}))


def get_provider_setting(provider_id: str | None, field_id: str | None) -> str:
    provider_key = str(provider_id or "").strip().lower()
    field_key = str(field_id or "").strip()
    if not provider_key or not field_key:
        return ""
    with _SETTINGS_LOCK:
        return str(_RUNTIME_PROVIDER_SETTINGS.get(provider_key, {}).get(field_key, "") or "").strip()


def provider_metadata(provider_id: str | None) -> dict[str, Any]:
    provider = get_provider(normalize_provider_id(provider_id))
    return dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}


def normalize_provider_id(provider_id: str | None, fallback: str = DEFAULT_PROVIDER_ID) -> str:
    requested = str(provider_id or "").strip().lower()
    if requested and get_provider(requested) is not None:
        return requested
    default_value = str(fallback or DEFAULT_PROVIDER_ID).strip().lower()
    if default_value and get_provider(default_value) is not None:
        return default_value
    providers = list_providers()
    return str(providers[0].id if providers else DEFAULT_PROVIDER_ID)


def provider_label(provider_id: str | None) -> str:
    provider = get_provider(normalize_provider_id(provider_id))
    return str(getattr(provider, "label", "") or provider_id or DEFAULT_PROVIDER_ID)


def provider_model_error(provider_id: str | None) -> str:
    return f"Error: Check {provider_label(provider_id)}"


def provider_api_key(provider_id: str | None) -> str:
    provider = get_provider(normalize_provider_id(provider_id))
    if provider is None or provider.api_key_getter is None:
        return ""
    try:
        return str(provider.api_key_getter() or "").strip()
    except Exception:
        return ""


def provider_base_url(provider_id: str | None) -> str:
    provider = get_provider(normalize_provider_id(provider_id))
    if provider is None or provider.base_url_getter is None:
        return ""
    try:
        return str(provider.base_url_getter() or "").strip()
    except Exception:
        return ""


def create_client(provider_id: str | None):
    normalized = normalize_provider_id(provider_id)
    provider = get_provider(normalized)
    if provider is None:
        raise RuntimeError(f"Unknown chat provider: {provider_id}")
    if provider.client_factory is not None:
        return provider.client_factory()
    api_key = provider_api_key(normalized)
    base_url = provider_base_url(normalized)
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _request_kwargs(provider_id: str | None, params: dict[str, Any] | None, additional_params: dict[str, Any] | None = None, *, stream: bool = False) -> dict[str, Any]:
    normalized = normalize_provider_id(provider_id)
    request_kwargs = dict(params or {})
    if normalized == "lmstudio" and additional_params:
        request_kwargs["extra_body"] = dict(additional_params or {})
    if stream:
        request_kwargs["stream"] = True
    return request_kwargs


def _extract_completion_text(response: Any) -> str:
    if isinstance(response, str):
        return str(response)
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None) if message is not None else None
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            text_value = getattr(item, "text", None)
            if text_value:
                parts.append(str(text_value))
                continue
            if isinstance(item, dict):
                dict_text = item.get("text")
                if dict_text:
                    parts.append(str(dict_text))
        return "".join(parts).strip()
    return str(content or "").strip()


def _default_completion_text(provider_id: str | None, params: dict[str, Any] | None, additional_params: dict[str, Any] | None = None) -> str:
    client = create_client(provider_id)
    response = client.chat.completions.create(**_request_kwargs(provider_id, params, additional_params, stream=False))
    return _extract_completion_text(response)


def _default_stream_text(provider_id: str | None, params: dict[str, Any] | None, additional_params: dict[str, Any] | None = None):
    client = create_client(provider_id)
    stream = client.chat.completions.create(**_request_kwargs(provider_id, params, additional_params, stream=True))
    for event in stream:
        choices = getattr(event, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None) if delta is not None else None
        if isinstance(content, list):
            for item in content:
                if isinstance(item, str) and item:
                    yield item
                    continue
                text_value = getattr(item, "text", None)
                if text_value:
                    yield str(text_value)
                    continue
                if isinstance(item, dict):
                    dict_text = item.get("text")
                    if dict_text:
                        yield str(dict_text)
        elif content:
            yield str(content)


def _default_connection_check(provider_id: str | None) -> dict[str, Any]:
    normalized = normalize_provider_id(provider_id)
    label = provider_label(normalized)
    client = create_client(normalized)
    models = client.models.list()
    count = len(getattr(models, "data", []) or [])
    return {
        "ok": True,
        "detail": f"Connected to {label} ({count} model(s) available)",
        "model_count": count,
    }


def _default_model_catalog(provider_id: str | None) -> list[str]:
    normalized = normalize_provider_id(provider_id)
    client = create_client(normalized)
    models = client.models.list()
    ids = sorted(
        {
            str(getattr(model, "id", "") or "").strip()
            for model in list(getattr(models, "data", []) or [])
            if str(getattr(model, "id", "") or "").strip()
        }
    )
    if normalized == "xai":
        ids = [model_id for model_id in ids if not str(model_id or "").strip().lower().startswith("grok-imagine")]
    return ids


def list_models(provider_id: str | None, quiet: bool = False) -> list[Any]:
    normalized = normalize_provider_id(provider_id)
    provider = get_provider(normalized)
    if provider is None:
        return [provider_model_error(provider_id)]
    try:
        if provider.model_list_handler is not None:
            result = list(provider.model_list_handler(bool(quiet)) or [])
        else:
            result = list(_default_model_catalog(normalized) or [])
        return result or [provider_model_error(normalized)]
    except Exception as exc:
        if not quiet:
            print(f"Error fetching {provider_label(normalized)} models: {exc}")
        return [provider_model_error(normalized)]


def complete_chat(provider_id: str | None, params: dict[str, Any] | None, additional_params: dict[str, Any] | None = None) -> str:
    normalized = normalize_provider_id(provider_id)
    provider = get_provider(normalized)
    if provider is None:
        raise RuntimeError(f"Unknown chat provider: {provider_id}")
    if provider.completion_handler is not None:
        return str(provider.completion_handler(dict(params or {}), dict(additional_params or {})) or "")
    return _default_completion_text(normalized, params, additional_params)


def stream_chat(provider_id: str | None, params: dict[str, Any] | None, additional_params: dict[str, Any] | None = None):
    normalized = normalize_provider_id(provider_id)
    provider = get_provider(normalized)
    if provider is None:
        raise RuntimeError(f"Unknown chat provider: {provider_id}")
    if provider.stream_handler is not None:
        return provider.stream_handler(dict(params or {}), dict(additional_params or {}))
    return _default_stream_text(normalized, params, additional_params)


def check_connection(provider_id: str | None) -> dict[str, Any]:
    normalized = normalize_provider_id(provider_id)
    provider = get_provider(normalized)
    if provider is None:
        return {"ok": False, "detail": f"Unknown chat provider: {provider_id}"}
    if provider.connection_check_handler is not None:
        result = provider.connection_check_handler()
        if isinstance(result, dict):
            payload = dict(result)
            payload.setdefault("ok", bool(payload.get("ok")))
            return payload
        if isinstance(result, tuple) and len(result) >= 2:
            return {"ok": bool(result[0]), "detail": str(result[1] or "")}
        if isinstance(result, bool):
            return {"ok": bool(result), "detail": ""}
    return _default_connection_check(normalized)


def _lmstudio_api_key() -> str:
    return get_provider_setting("lmstudio", "api_key") or LMSTUDIO_API_KEY


def _lmstudio_base_url() -> str:
    return get_provider_setting("lmstudio", "base_url") or LMSTUDIO_BASE_URL


def _openai_api_key() -> str:
    return get_provider_setting("openai", "api_key") or _env_value("NC_CHAT_OPENAI_API_KEY", "OPENAI_API_KEY")


def _openai_base_url() -> str:
    return get_provider_setting("openai", "base_url") or _env_value("NC_CHAT_OPENAI_BASE_URL")


def _xai_api_key() -> str:
    return get_provider_setting("xai", "api_key") or _env_value("NC_CHAT_XAI_API_KEY", "XAI_API_KEY", "NC_VISUAL_REPLY_XAI_API_KEY")


def _xai_base_url() -> str:
    return get_provider_setting("xai", "base_url") or _env_value("NC_CHAT_XAI_BASE_URL", fallback="https://api.x.ai/v1")


def _lmstudio_client():
    return OpenAI(base_url=_lmstudio_base_url(), api_key=_lmstudio_api_key())


def _openai_client():
    base_url = _openai_base_url()
    api_key = _openai_api_key()
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


def _xai_client():
    return OpenAI(api_key=_xai_api_key(), base_url=_xai_base_url())


def _xai_language_model_catalog():
    base_url = str(_xai_base_url() or "").strip().rstrip("/")
    if not base_url:
        return []
    payload = _fetch_json_with_bearer(f"{base_url}/language-models", _xai_api_key(), timeout=15.0)
    entries = []
    if isinstance(payload, dict):
        entries = list(payload.get("data") or payload.get("models") or payload.get("items") or [])
    elif isinstance(payload, list):
        entries = list(payload)
    catalog = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id") or item.get("model") or item.get("name") or "").strip()
        if not model_id:
            continue
        input_modalities = [
            str(modality or "").strip().lower()
            for modality in list(item.get("input_modalities") or [])
            if str(modality or "").strip()
        ]
        output_modalities = [
            str(modality or "").strip().lower()
            for modality in list(item.get("output_modalities") or [])
            if str(modality or "").strip()
        ]
        supports_images = "image" in input_modalities
        catalog.append(
            {
                "id": model_id,
                "supports_images": bool(supports_images),
                "source": "xai_language_models",
                "input_modalities": list(input_modalities),
                "output_modalities": list(output_modalities),
            }
        )
    return catalog


def _xai_models(quiet: bool = False) -> list[Any]:
    catalog = _xai_language_model_catalog()
    if catalog:
        return catalog
    return _default_model_catalog("xai")


def _register_builtin_providers():
    register_provider(
        provider_id="lmstudio",
        label="LM Studio",
        description="Local LM Studio models exposed through the OpenAI-compatible API.",
        order=100,
        client_factory=_lmstudio_client,
        api_key_getter=_lmstudio_api_key,
        base_url_getter=_lmstudio_base_url,
        metadata={
            "config_fields": [
                {"id": "base_url", "label": "Base URL", "source": "builtin", "default": LMSTUDIO_BASE_URL},
            ],
            "generation_fields": [
                {"id": "temperature", "label": "Temperature", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.22, "request_location": "params"},
                {"id": "top_p", "label": "Top P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.9, "request_location": "params"},
                {"id": "top_k", "label": "Top K", "kind": "int", "min": 0, "max": 1000, "step": 1, "default": 40, "request_location": "additional_params"},
                {"id": "repeat_penalty", "label": "Repetition Penalty", "kind": "float", "min": 1.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.15, "request_location": "additional_params"},
                {"id": "min_p", "label": "Min P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.05, "request_location": "additional_params"},
                {"id": "max_tokens", "label": "Max Tokens (-1 = no cap)", "kind": "int", "min": -1, "max": 131072, "step": 1, "default": -1, "request_location": "params"},
            ],
            "hint": "Uses LM Studio's local OpenAI-compatible endpoint.",
            "supports_local_runtime": True,
        },
    )
    register_provider(
        provider_id="openai",
        label="OpenAI",
        description="Hosted OpenAI models.",
        order=200,
        client_factory=_openai_client,
        api_key_getter=_openai_api_key,
        base_url_getter=_openai_base_url,
        metadata={
            "config_fields": [
                {"id": "api_key", "label": "API Key", "env": ["NC_CHAT_OPENAI_API_KEY", "OPENAI_API_KEY"]},
                {"id": "base_url", "label": "Base URL", "env": ["NC_CHAT_OPENAI_BASE_URL"]},
            ],
            "generation_fields": [
                {"id": "temperature", "label": "Temperature", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.0, "request_location": "params"},
                {"id": "top_p", "label": "Top P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.9, "request_location": "params"},
            ],
            "hint": "Hosted OpenAI provider. API key is required.",
            "supports_hosted_runtime": True,
        },
    )
    register_provider(
        provider_id="xai",
        label="xAI / Grok",
        description="Hosted xAI Grok models through the xAI API.",
        order=300,
        client_factory=_xai_client,
        model_list_handler=_xai_models,
        api_key_getter=_xai_api_key,
        base_url_getter=_xai_base_url,
        metadata={
            "config_fields": [
                {"id": "api_key", "label": "API Key", "env": ["NC_CHAT_XAI_API_KEY", "XAI_API_KEY"]},
                {"id": "base_url", "label": "Base URL", "env": ["NC_CHAT_XAI_BASE_URL"], "default": "https://api.x.ai/v1"},
            ],
            "generation_fields": [
                {"id": "temperature", "label": "Temperature", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.0, "request_location": "params"},
                {"id": "top_p", "label": "Top P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.9, "request_location": "params"},
            ],
            "hint": "Hosted xAI / Grok provider. API key is required.",
            "supports_hosted_runtime": True,
        },
    )


_register_builtin_providers()
