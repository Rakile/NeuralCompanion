from __future__ import annotations

import json
import os
import re
import secrets
import threading
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlsplit

from openai import OpenAI


DEFAULT_PROVIDER_ID = "lmstudio"
FROZEN_EXECUTION_CAPABILITY_VERSION = 1

ChatModelListHandler = Callable[[bool], list[Any]]
ChatClientFactory = Callable[[], Any]
StringGetter = Callable[[], str]
ChatCompletionHandler = Callable[[dict[str, Any], dict[str, Any] | None], str]
ChatStreamHandler = Callable[[dict[str, Any], dict[str, Any] | None], Iterable[str]]
ChatConnectionCheckHandler = Callable[[], Any]
ChatTokenCounter = Callable[[Iterable[Mapping[str, Any]]], int]


_IMMUTABLE_VALUE_TYPES = (bool, bytes, complex, float, int, str, type(None))
_SENSITIVE_CONFIG_KEYS = {
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
}
_DROP_PUBLIC_VALUE = object()
_USER_TEXT_FIELDS = {"content", "input", "prompt", "text"}
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ACRONYM_WORD_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_NON_KEY_CHARACTER = re.compile(r"[^a-zA-Z0-9]+")


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {_freeze_value(key): _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_value(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    if type(value) in _IMMUTABLE_VALUE_TYPES:
        return value
    raise TypeError(
        f"Unsupported frozen chat value type: {type(value).__name__}."
    )


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping):
        raise TypeError("Frozen chat data must be a mapping.")
    return _freeze_value(value)


def _mutable_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _mutable_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_mutable_copy(item) for item in value]
    if isinstance(value, frozenset):
        return {_mutable_copy(item) for item in value}
    if type(value) in _IMMUTABLE_VALUE_TYPES:
        return value
    raise TypeError(
        f"Unsupported frozen chat value type: {type(value).__name__}."
    )


def _is_sensitive_config_key(key: Any) -> bool:
    text = _ACRONYM_WORD_BOUNDARY.sub("_", str(key or "").strip())
    text = _CAMEL_CASE_BOUNDARY.sub("_", text)
    normalized = _NON_KEY_CHARACTER.sub("_", text).strip("_").lower()
    compact = _NON_KEY_CHARACTER.sub("", text).lower()
    parts = tuple(part for part in normalized.split("_") if part)
    if normalized in _SENSITIVE_CONFIG_KEYS or any(
        part in _SENSITIVE_CONFIG_KEYS for part in parts
    ):
        return True
    return "apikey" in compact or any(
        left == "api" and right == "key"
        for left, right in zip(parts, parts[1:])
    )


def _is_credential_bearing_url(value: str) -> bool:
    text = str(value or "").strip()
    if "://" not in text:
        return False
    try:
        parsed = urlsplit(text)
        if parsed.username is not None or parsed.password is not None:
            return True
        return any(_is_sensitive_config_key(key) for key, _value in parse_qsl(parsed.query))
    except Exception:
        return "@" in text or "?" in text


def _sanitize_public_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            if _is_sensitive_config_key(key):
                continue
            public_item = _sanitize_public_value(item)
            if public_item is not _DROP_PUBLIC_VALUE:
                sanitized[key] = public_item
        return sanitized
    if isinstance(value, (list, tuple)):
        sanitized_items = []
        for item in value:
            public_item = _sanitize_public_value(item)
            if public_item is not _DROP_PUBLIC_VALUE:
                sanitized_items.append(public_item)
        return sanitized_items
    if isinstance(value, (set, frozenset)):
        sanitized_items = set()
        for item in value:
            public_item = _sanitize_public_value(item)
            if public_item is not _DROP_PUBLIC_VALUE:
                sanitized_items.add(public_item)
        return sanitized_items
    if isinstance(value, str) and _is_credential_bearing_url(value):
        return _DROP_PUBLIC_VALUE
    if type(value) in _IMMUTABLE_VALUE_TYPES or isinstance(value, bytearray):
        return value
    return _DROP_PUBLIC_VALUE


def _public_provider_config(
    provider_config: Mapping[str, Any],
    allowed_fields: Iterable[str],
) -> Mapping[str, Any]:
    allowed = {str(field or "").strip() for field in allowed_fields if str(field or "").strip()}
    projected: dict[str, Any] = {}
    for key, value in provider_config.items():
        field_name = str(key or "").strip()
        if field_name not in allowed or _is_sensitive_config_key(field_name):
            continue
        public_value = _sanitize_public_value(value)
        if public_value is not _DROP_PUBLIC_VALUE:
            projected[field_name] = public_value
    return _freeze_mapping(projected)


def _assert_no_public_credentials(
    value: Any,
    *,
    allow_user_content: bool = False,
    _user_text_leaf: bool = False,
) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            field_name = str(key or "").strip().lower()
            if _is_sensitive_config_key(key):
                raise TypeError("Credential-bearing data is not allowed in public frozen chat fields.")
            _assert_no_public_credentials(
                item,
                allow_user_content=allow_user_content,
                _user_text_leaf=(
                    allow_user_content and field_name in _USER_TEXT_FIELDS
                ),
            )
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _assert_no_public_credentials(
                item,
                allow_user_content=allow_user_content,
                _user_text_leaf=_user_text_leaf,
            )
        return
    if (
        isinstance(value, str)
        and not (allow_user_content and _user_text_leaf)
        and _is_credential_bearing_url(value)
    ):
        raise TypeError("Credential-bearing data is not allowed in public frozen chat fields.")


class FrozenChatProviderUnsupportedError(RuntimeError):
    """Raised when a provider cannot execute the request-scoped frozen API."""


class FrozenChatProviderCaptureError(RuntimeError):
    """Raised when accepted-turn provider execution state cannot be frozen."""


class FrozenChatProviderPreparationError(RuntimeError):
    """Raised when provider-specific request preparation fails."""


class FrozenChatProviderCapabilityError(RuntimeError):
    """Raised when strict Relay capability capture fails."""


class FrozenChatProviderExecutionError(RuntimeError):
    """Raised when a bound provider handler fails without exposing private state."""


FrozenChatCompletionHandler = Callable[..., str]
FrozenChatStreamHandler = Callable[..., Iterable[str]]
FrozenChatPrepareHandler = Callable[..., tuple[Mapping[str, Any], Mapping[str, Any]]]
FrozenPrivateConfigGetter = Callable[[], Mapping[str, Any]]
FrozenModelCapabilitiesHandler = Callable[
    [Any],
    "FrozenChatProviderCapabilities | Mapping[str, Any] | None",
]

FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE = "_nc_frozen_output_token_budget"


class _FrozenChatExecutionBinding:
    """Private, non-serializable execution state captured for one accepted turn."""

    __slots__ = (
        "_capability_attestation",
        "_capability_handler",
        "_completion_handler",
        "_execution_identity",
        "_generation_fields",
        "_model_name",
        "_prepare_handler",
        "_provider_config",
        "_provider_name",
        "_sealed",
        "_stream_handler",
        "_token_counter",
    )

    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        provider_config: Mapping[str, Any],
        generation_fields: Mapping[str, Any],
        prepare_handler: FrozenChatPrepareHandler | None,
        completion_handler: FrozenChatCompletionHandler | None,
        stream_handler: FrozenChatStreamHandler | None,
        capability_handler: FrozenModelCapabilitiesHandler | None,
        token_counter: ChatTokenCounter | None,
    ) -> None:
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_provider_name", str(provider_name or "").strip().lower())
        object.__setattr__(self, "_model_name", str(model_name or "").strip())
        object.__setattr__(self, "_provider_config", _freeze_mapping(provider_config))
        object.__setattr__(self, "_generation_fields", _freeze_mapping(generation_fields))
        object.__setattr__(self, "_capability_attestation", object())
        object.__setattr__(self, "_execution_identity", secrets.token_urlsafe(32))
        object.__setattr__(self, "_prepare_handler", prepare_handler)
        object.__setattr__(self, "_completion_handler", completion_handler)
        object.__setattr__(self, "_stream_handler", stream_handler)
        object.__setattr__(self, "_capability_handler", capability_handler)
        object.__setattr__(self, "_token_counter", token_counter)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("Frozen chat execution bindings are immutable.")
        object.__setattr__(self, name, value)

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def execution_identity(self) -> str:
        return self._execution_identity

    def _provider_config_copy(self) -> dict[str, Any]:
        return _mutable_copy(self._provider_config)

    def _generation_fields_copy(self) -> dict[str, Any]:
        return _mutable_copy(self._generation_fields)

    def __repr__(self) -> str:
        return (
            f"<_FrozenChatExecutionBinding provider={self.provider_name!r} "
            f"model={self.model_name!r} redacted>"
        )

    def __copy__(self):
        raise TypeError("Private frozen chat execution bindings cannot be copied.")

    def __deepcopy__(self, _memo):
        raise TypeError("Private frozen chat execution bindings cannot be copied.")

    def __reduce__(self):
        raise TypeError("Private frozen chat execution bindings cannot be serialized.")

    def __reduce_ex__(self, _protocol):
        raise TypeError("Private frozen chat execution bindings cannot be serialized.")


@dataclass(frozen=True, init=False)
class FrozenChatProviderCapabilities:
    """Sanitized strict Relay capability summary for one frozen context."""

    context_limit: int | None = None
    _strict_relay_available: bool = field(default=False, repr=False, compare=False)

    def __init__(self, context_limit: int | None = None) -> None:
        if context_limit is not None and (
            type(context_limit) is not int or context_limit <= 0
        ):
            raise ValueError("Frozen chat context limit must be a positive integer.")
        object.__setattr__(self, "context_limit", context_limit)
        object.__setattr__(self, "_strict_relay_available", False)

    @property
    def strict_relay_available(self) -> bool:
        return self._strict_relay_available

    def to_summary(self) -> dict[str, Any]:
        return {
            "strict_relay_available": self.strict_relay_available,
            "context_limit": self.context_limit if self.strict_relay_available else None,
        }


class _FrozenChatCapacityBinding:
    """Private, non-serializable exact-capacity state for one frozen context."""

    __slots__ = (
        "_attestation",
        "_capabilities",
        "_sealed",
        "_token_counter",
    )

    def __init__(
        self,
        *,
        attestation: object,
        capabilities: FrozenChatProviderCapabilities,
        token_counter: ChatTokenCounter,
    ) -> None:
        object.__setattr__(self, "_sealed", False)
        object.__setattr__(self, "_attestation", attestation)
        object.__setattr__(self, "_capabilities", capabilities)
        object.__setattr__(self, "_token_counter", token_counter)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("Frozen chat capacity bindings are immutable.")
        object.__setattr__(self, name, value)

    def matches(
        self,
        execution_binding: _FrozenChatExecutionBinding,
        capabilities: FrozenChatProviderCapabilities,
    ) -> bool:
        return (
            self._attestation is execution_binding._capability_attestation
            and self._capabilities is capabilities
            and callable(self._token_counter)
        )

    def __repr__(self) -> str:
        return "<_FrozenChatCapacityBinding redacted>"

    def __copy__(self):
        raise TypeError("Private frozen chat capacity bindings cannot be copied.")

    def __deepcopy__(self, _memo):
        raise TypeError("Private frozen chat capacity bindings cannot be copied.")

    def __reduce__(self):
        raise TypeError("Private frozen chat capacity bindings cannot be serialized.")

    def __reduce_ex__(self, _protocol):
        raise TypeError("Private frozen chat capacity bindings cannot be serialized.")


@dataclass(frozen=True)
class FrozenChatProviderContext:
    """Provider execution state captured once when a chat turn is accepted."""

    provider_name: str
    model_name: str
    provider_config: Mapping[str, Any] = field(default_factory=dict, repr=False)
    generation_fields: Mapping[str, Any] = field(default_factory=dict, repr=False)
    capabilities: FrozenChatProviderCapabilities = field(
        default_factory=FrozenChatProviderCapabilities,
        repr=False,
    )
    _binding: _FrozenChatExecutionBinding | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _capacity_binding: _FrozenChatCapacityBinding | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_name", str(self.provider_name or "").strip().lower())
        object.__setattr__(self, "model_name", str(self.model_name or "").strip())
        object.__setattr__(
            self,
            "provider_config",
            _public_provider_config(self.provider_config, self.provider_config.keys()),
        )
        _assert_no_public_credentials(self.generation_fields)
        object.__setattr__(self, "generation_fields", _freeze_mapping(self.generation_fields))
        if not isinstance(self.capabilities, FrozenChatProviderCapabilities):
            raise TypeError("Frozen chat capabilities must use FrozenChatProviderCapabilities.")
        if self._binding is not None:
            if not isinstance(self._binding, _FrozenChatExecutionBinding):
                raise TypeError("Frozen chat contexts require a private execution binding.")
            if (
                self._binding.provider_name != self.provider_name
                or self._binding.model_name != self.model_name
            ):
                raise TypeError("Frozen chat context does not match its execution binding.")
        if self._capacity_binding is not None:
            if self._binding is None or not isinstance(
                self._capacity_binding,
                _FrozenChatCapacityBinding,
            ):
                raise TypeError("Frozen chat contexts require a private capacity binding.")

    @property
    def strict_relay_available(self) -> bool:
        return (
            self.capabilities.strict_relay_available
            and self._binding is not None
            and self._capacity_binding is not None
            and self._capacity_binding.matches(self._binding, self.capabilities)
        )

    def to_summary(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "strict_relay_available": self.strict_relay_available,
        }


@dataclass(frozen=True)
class FrozenChatProviderRequest:
    """Final generic provider request prepared once for completion or stream."""

    context: FrozenChatProviderContext
    params: Mapping[str, Any] = field(default_factory=dict, repr=False)
    additional_params: Mapping[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.context, FrozenChatProviderContext):
            raise TypeError("Frozen chat requests require a FrozenChatProviderContext.")
        _assert_no_public_credentials(self.params, allow_user_content=True)
        _assert_no_public_credentials(self.additional_params)
        object.__setattr__(self, "params", _freeze_mapping(self.params))
        object.__setattr__(self, "additional_params", _freeze_mapping(self.additional_params))

    def params_copy(self) -> dict[str, Any]:
        return _mutable_copy(self.params)

    def additional_params_copy(self) -> dict[str, Any]:
        return _mutable_copy(self.additional_params)

    def to_summary(self) -> dict[str, Any]:
        return {
            "provider_name": self.context.provider_name,
            "model_name": self.context.model_name,
            "prepared": True,
            "strict_relay_available": self.context.strict_relay_available,
        }


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
    frozen_prepare_handler: FrozenChatPrepareHandler | None = None
    frozen_completion_handler: FrozenChatCompletionHandler | None = None
    frozen_stream_handler: FrozenChatStreamHandler | None = None
    model_capabilities_handler: FrozenModelCapabilitiesHandler | None = None
    token_counter: ChatTokenCounter | None = None
    frozen_private_config_getter: FrozenPrivateConfigGetter | None = None
    frozen_public_config_fields: tuple[str, ...] = ()
    normal_chat_capable: bool = True
    frozen_execution_version: int | None = None
    normal_chat_available: bool = False
    normal_chat_status_message: str = ""

    def normal_chat_status(self) -> dict[str, Any]:
        return {
            "available": bool(self.normal_chat_available),
            "claimed": bool(self.normal_chat_capable),
            "frozen_execution_version": self.frozen_execution_version,
            "required_frozen_execution_version": FROZEN_EXECUTION_CAPABILITY_VERSION,
            "message": str(self.normal_chat_status_message or "").strip(),
        }

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": str(self.id or "").strip(),
            "label": str(self.label or "").strip(),
            "description": str(self.description or "").strip(),
            "order": int(self.order),
            "metadata": dict(self.metadata or {}),
            "normal_chat": self.normal_chat_status(),
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
        frozen_prepare_handler: FrozenChatPrepareHandler | None = None,
        frozen_completion_handler: FrozenChatCompletionHandler | None = None,
        frozen_stream_handler: FrozenChatStreamHandler | None = None,
        model_capabilities_handler: FrozenModelCapabilitiesHandler | None = None,
        token_counter: ChatTokenCounter | None = None,
        frozen_private_config_getter: FrozenPrivateConfigGetter | None = None,
        frozen_public_config_fields: Iterable[str] | None = None,
        normal_chat_capable: bool = True,
        frozen_execution_version: int | None = None,
    ) -> ChatProvider:
        public_config_fields = (
            (frozen_public_config_fields,)
            if isinstance(frozen_public_config_fields, str)
            else tuple(frozen_public_config_fields or ())
        )
        provider_key = str(provider_id or "").strip().lower()
        provider_label = str(label or "").strip()
        claims_normal_chat = bool(normal_chat_capable)
        negotiated_version = (
            int(frozen_execution_version)
            if type(frozen_execution_version) is int
            else None
        )
        required_hooks = (
            ("frozen_prepare_handler", frozen_prepare_handler),
            ("frozen_completion_handler", frozen_completion_handler),
            ("frozen_stream_handler", frozen_stream_handler),
        )
        missing_hooks = [name for name, handler in required_hooks if not callable(handler)]
        normal_chat_available = bool(
            claims_normal_chat
            and negotiated_version == FROZEN_EXECUTION_CAPABILITY_VERSION
            and not missing_hooks
        )
        if normal_chat_available:
            normal_chat_status_message = "Frozen normal-chat execution is available."
        elif not claims_normal_chat:
            normal_chat_status_message = (
                f"{provider_label or provider_key or 'This provider'} does not claim "
                "normal-chat capability."
            )
        else:
            normal_chat_status_message = (
                f"{provider_label or provider_key or 'This provider'} is unavailable for "
                "normal chat. Update the provider addon to register "
                f"frozen_execution_version={FROZEN_EXECUTION_CAPABILITY_VERSION} with "
                "frozen_prepare_handler, frozen_completion_handler, and "
                "frozen_stream_handler."
            )
        provider = ChatProvider(
            id=provider_key,
            label=provider_label,
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
            frozen_prepare_handler=frozen_prepare_handler,
            frozen_completion_handler=frozen_completion_handler,
            frozen_stream_handler=frozen_stream_handler,
            model_capabilities_handler=model_capabilities_handler,
            token_counter=token_counter,
            frozen_private_config_getter=frozen_private_config_getter,
            frozen_public_config_fields=tuple(
                str(field or "").strip()
                for field in public_config_fields
                if str(field or "").strip()
            ),
            normal_chat_capable=claims_normal_chat,
            frozen_execution_version=negotiated_version,
            normal_chat_available=normal_chat_available,
            normal_chat_status_message=normal_chat_status_message,
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

    def resolve_provider(
        self,
        provider_id: str | None,
        fallback: str = DEFAULT_PROVIDER_ID,
    ) -> ChatProvider | None:
        requested = str(provider_id or "").strip().lower()
        fallback_id = str(fallback or DEFAULT_PROVIDER_ID).strip().lower()
        with self._lock:
            if requested and requested in self._providers:
                return self._providers[requested]
            if fallback_id and fallback_id in self._providers:
                return self._providers[fallback_id]
            providers = list(self._providers.values())
        if not providers:
            return None
        return sorted(
            providers,
            key=lambda item: (
                int(item.order),
                str(item.label or "").lower(),
                str(item.id or "").lower(),
            ),
        )[0]


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


def _resolve_provider(
    provider_id: str | None,
    fallback: str = DEFAULT_PROVIDER_ID,
) -> ChatProvider | None:
    return _REGISTRY.resolve_provider(provider_id, fallback)


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


def _capture_provider_config(
    provider: ChatProvider,
    provider_config: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if provider_config is not None:
        try:
            frozen_provider_config = _freeze_mapping(provider_config)
        except Exception:
            pass
        else:
            return frozen_provider_config
        raise FrozenChatProviderCaptureError(
            f"Frozen provider config capture failed for '{provider.id}'."
        ) from None

    captured = get_provider_settings(provider.id)
    for field_name, getter in (
        ("api_key", provider.api_key_getter),
        ("base_url", provider.base_url_getter),
    ):
        if getter is None:
            continue
        try:
            value = str(getter() or "").strip()
        except Exception:
            pass
        else:
            if value or field_name not in captured:
                captured[field_name] = value
            continue
        raise FrozenChatProviderCaptureError(
            f"Frozen provider config capture failed for '{provider.id}'."
        ) from None
    if provider.frozen_private_config_getter is not None:
        private_capture_failed = False
        try:
            extra_config = provider.frozen_private_config_getter()
            if not isinstance(extra_config, Mapping):
                raise TypeError("Frozen private config getter must return a mapping.")
            captured.update(extra_config)
        except Exception:
            private_capture_failed = True
        if private_capture_failed:
            raise FrozenChatProviderCaptureError(
                f"Frozen provider config capture failed for '{provider.id}'."
            ) from None
    try:
        frozen_captured = _freeze_mapping(captured)
    except Exception:
        pass
    else:
        return frozen_captured
    raise FrozenChatProviderCaptureError(
        f"Frozen provider config capture failed for '{provider.id}'."
    ) from None


def capture_frozen_provider_context(
    provider: ChatProvider,
    *,
    model_name: str,
    provider_config: Mapping[str, Any] | None = None,
    generation_fields: Mapping[str, Any] | None = None,
) -> FrozenChatProviderContext:
    """Bind one exact provider registration and its accepted-turn execution state."""
    if not isinstance(provider, ChatProvider):
        raise TypeError("Frozen provider capture requires a ChatProvider registration.")
    if not provider.normal_chat_available:
        raise FrozenChatProviderUnsupportedError(
            provider.normal_chat_status_message
        ) from None
    provider_name = str(provider.id or "").strip().lower()
    frozen_model_name = str(model_name or "").strip()
    private_config = _capture_provider_config(provider, provider_config)
    try:
        private_generation_fields = _freeze_mapping(generation_fields)
        public_config = _public_provider_config(
            private_config,
            provider.frozen_public_config_fields,
        )
        binding = _FrozenChatExecutionBinding(
            provider_name=provider_name,
            model_name=frozen_model_name,
            provider_config=private_config,
            generation_fields=private_generation_fields,
            prepare_handler=provider.frozen_prepare_handler,
            completion_handler=provider.frozen_completion_handler,
            stream_handler=provider.frozen_stream_handler,
            capability_handler=provider.model_capabilities_handler,
            token_counter=provider.token_counter,
        )
        return FrozenChatProviderContext(
            provider_name=provider_name,
            model_name=frozen_model_name,
            provider_config=public_config,
            generation_fields=private_generation_fields,
            _binding=binding,
        )
    except FrozenChatProviderCaptureError:
        raise
    except Exception:
        raise FrozenChatProviderCaptureError(
            f"Frozen provider state capture failed for '{provider_name}'."
        ) from None


def capture_provider_config(provider_id: str) -> dict[str, Any]:
    """Return only the provider's allowlisted, sanitized public config projection."""
    provider = _resolve_provider(provider_id, fallback="")
    if provider is None or provider.id != str(provider_id or "").strip().lower():
        raise FrozenChatProviderUnsupportedError(
            f"Unknown chat provider for frozen capture: {provider_id}"
        )
    context = capture_frozen_provider_context(provider, model_name="")
    return _mutable_copy(context.provider_config)


def capture_provider_capabilities(
    provider_id: str,
    model_name: str,
) -> FrozenChatProviderCapabilities:
    """Reject model-only strict capture; callers must upgrade a frozen context."""
    del provider_id, model_name
    raise FrozenChatProviderUnsupportedError(
        "Strict Relay capability capture requires a frozen provider context."
    )


def _binding_for_context(
    context: FrozenChatProviderContext,
) -> _FrozenChatExecutionBinding | None:
    if not isinstance(context, FrozenChatProviderContext):
        return None
    return context._binding


def frozen_execution_available(
    context: FrozenChatProviderContext,
    *,
    stream: bool = False,
) -> bool:
    binding = _binding_for_context(context)
    if binding is None or not callable(binding._prepare_handler):
        return False
    handler = binding._stream_handler if stream else binding._completion_handler
    return callable(handler)


def upgrade_frozen_context_for_relay(
    context: FrozenChatProviderContext,
) -> FrozenChatProviderContext:
    """Run the bound adapter's strict capability hook against frozen execution state."""
    binding = _binding_for_context(context)
    if binding is None:
        raise FrozenChatProviderUnsupportedError(
            "Strict Relay capability upgrade requires a captured provider binding."
        )
    try:
        handler = binding._capability_handler
        if not callable(handler):
            return replace(
                context,
                capabilities=FrozenChatProviderCapabilities(),
                _capacity_binding=None,
            )
        result = handler(binding)
        if result is None:
            capabilities = FrozenChatProviderCapabilities()
            capacity_binding = None
        elif type(result) is FrozenChatProviderCapabilities:
            capabilities = FrozenChatProviderCapabilities()
            capacity_binding = None
        else:
            if isinstance(result, Mapping):
                context_limit = result.get("context_limit")
                if context_limit is not None and (
                    type(context_limit) is not int or context_limit <= 0
                ):
                    raise ValueError("Invalid frozen chat context limit.")
                direct_counter = result.get("token_counter")
                capability_identity = result.get("capability_identity")
                token_counter_identity = result.get("token_counter_identity")
            else:
                raise TypeError("Unsupported frozen capability result.")

            if (
                type(capability_identity) is not str
                or type(token_counter_identity) is not str
                or capability_identity != binding.execution_identity
                or token_counter_identity != binding.execution_identity
            ):
                raise ValueError("Frozen capability identity mismatch.")
            token_counter = (
                direct_counter
                if callable(direct_counter)
                else binding._token_counter
                if callable(binding._token_counter)
                else None
            )
            if token_counter is None:
                capabilities = FrozenChatProviderCapabilities()
                capacity_binding = None
            else:
                capabilities = FrozenChatProviderCapabilities(
                    context_limit=context_limit,
                )
                object.__setattr__(capabilities, "_strict_relay_available", True)
                capacity_binding = _FrozenChatCapacityBinding(
                    attestation=binding._capability_attestation,
                    capabilities=capabilities,
                    token_counter=token_counter,
                )
        return replace(
            context,
            capabilities=capabilities,
            _capacity_binding=capacity_binding,
        )
    except Exception:
        raise FrozenChatProviderCapabilityError(
            "Strict Relay capability capture failed."
        ) from None


def count_frozen_chat_tokens(
    context: FrozenChatProviderContext,
    messages: Iterable[Mapping[str, Any]],
) -> int:
    """Count tokens with the exact counter privately bound to a strict context."""
    binding = _binding_for_context(context)
    capacity_binding = (
        context._capacity_binding
        if isinstance(context, FrozenChatProviderContext)
        else None
    )
    if (
        binding is None
        or capacity_binding is None
        or not context.strict_relay_available
        or not capacity_binding.matches(binding, context.capabilities)
    ):
        raise FrozenChatProviderCapabilityError(
            "Strict Relay token counting is unavailable."
        )
    try:
        count = capacity_binding._token_counter(messages)
        if type(count) is not int or count < 0:
            raise ValueError("Invalid frozen token count.")
        return count
    except Exception:
        raise FrozenChatProviderCapabilityError(
            "Strict Relay token counting failed."
        ) from None


def prepare_frozen_chat_request(
    context: FrozenChatProviderContext,
    params: Mapping[str, Any],
    additional_params: Mapping[str, Any] | None = None,
) -> FrozenChatProviderRequest:
    """Run bound provider preparation once, then freeze the final outbound payload."""
    binding = _binding_for_context(context)
    handler = binding._prepare_handler if binding is not None else None
    if not callable(handler):
        raise FrozenChatProviderUnsupportedError(
            f"Frozen request preparation is unsupported for provider '{context.provider_name}'."
        )
    try:
        detached_params = _mutable_copy(_freeze_mapping(params))
        detached_additional = _mutable_copy(_freeze_mapping(additional_params))
        result = handler(binding, detached_params, detached_additional)
        if not isinstance(result, tuple) or len(result) != 2:
            raise TypeError("Frozen provider preparation must return two mappings.")
        prepared_params, prepared_additional = result
        if not isinstance(prepared_params, Mapping) or not isinstance(
            prepared_additional,
            Mapping,
        ):
            raise TypeError("Frozen provider preparation must return two mappings.")
        return FrozenChatProviderRequest(
            context=context,
            params=prepared_params,
            additional_params=prepared_additional,
        )
    except FrozenChatProviderUnsupportedError:
        raise
    except Exception:
        raise FrozenChatProviderPreparationError(
            f"Frozen request preparation failed for provider '{context.provider_name}'."
        ) from None


def provider_metadata(provider_id: str | None) -> dict[str, Any]:
    provider = get_provider(normalize_provider_id(provider_id))
    if provider is None:
        return {}
    metadata = dict(getattr(provider, "metadata", {}) or {})
    metadata["normal_chat"] = provider.normal_chat_status()
    return metadata


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
    provider = get_provider(normalize_provider_id(provider_id))
    if provider is not None and not provider.normal_chat_available:
        return str(provider.normal_chat_status_message or "").strip()
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
    request_kwargs = dict(params or {})
    if additional_params:
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
    return ids


def list_models(provider_id: str | None, quiet: bool = False) -> list[Any]:
    normalized = normalize_provider_id(provider_id)
    provider = get_provider(normalized)
    if provider is None:
        return [provider_model_error(provider_id)]
    if not provider.normal_chat_available:
        return [str(provider.normal_chat_status_message or "").strip()]
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


def complete_frozen_chat(
    request: FrozenChatProviderRequest,
    *,
    timeout: float | None = None,
    cancel_token: Any = None,
) -> str:
    if not isinstance(request, FrozenChatProviderRequest):
        raise TypeError("Frozen completion requires a FrozenChatProviderRequest.")
    binding = _binding_for_context(request.context)
    handler = binding._completion_handler if binding is not None else None
    if not callable(handler):
        raise FrozenChatProviderUnsupportedError(
            f"Frozen completion is unsupported for provider '{request.context.provider_name}'."
        )
    try:
        return str(handler(request, timeout=timeout, cancel_token=cancel_token) or "")
    except FrozenChatProviderUnsupportedError:
        raise FrozenChatProviderUnsupportedError(
            f"Frozen completion is unsupported for provider '{request.context.provider_name}'."
        ) from None
    except FrozenChatProviderExecutionError as exc:
        raise FrozenChatProviderExecutionError(str(exc)) from None
    except Exception:
        raise FrozenChatProviderExecutionError(
            f"Frozen completion failed for provider '{request.context.provider_name}'."
        ) from None


def stream_frozen_chat(
    request: FrozenChatProviderRequest,
    *,
    timeout: float | None = None,
    cancel_token: Any = None,
) -> Iterable[str]:
    if not isinstance(request, FrozenChatProviderRequest):
        raise TypeError("Frozen stream requires a FrozenChatProviderRequest.")
    binding = _binding_for_context(request.context)
    handler = binding._stream_handler if binding is not None else None
    if not callable(handler):
        raise FrozenChatProviderUnsupportedError(
            f"Frozen stream is unsupported for provider '{request.context.provider_name}'."
        )
    try:
        stream = handler(request, timeout=timeout, cancel_token=cancel_token)
    except FrozenChatProviderUnsupportedError:
        raise FrozenChatProviderUnsupportedError(
            f"Frozen stream is unsupported for provider '{request.context.provider_name}'."
        ) from None
    except FrozenChatProviderExecutionError as exc:
        raise FrozenChatProviderExecutionError(str(exc)) from None
    except Exception:
        raise FrozenChatProviderExecutionError(
            f"Frozen stream failed for provider '{request.context.provider_name}'."
        ) from None

    def _protected_stream() -> Iterable[str]:
        try:
            yield from stream
        except FrozenChatProviderUnsupportedError:
            raise FrozenChatProviderUnsupportedError(
                f"Frozen stream is unsupported for provider '{request.context.provider_name}'."
            ) from None
        except FrozenChatProviderExecutionError as exc:
            raise FrozenChatProviderExecutionError(str(exc)) from None
        except Exception:
            raise FrozenChatProviderExecutionError(
                f"Frozen stream failed for provider '{request.context.provider_name}'."
            ) from None

    return _protected_stream()


def check_connection(provider_id: str | None) -> dict[str, Any]:
    normalized = normalize_provider_id(provider_id)
    provider = get_provider(normalized)
    if provider is None:
        return {"ok": False, "detail": f"Unknown chat provider: {provider_id}"}
    if not provider.normal_chat_available:
        return {
            "ok": False,
            "detail": str(provider.normal_chat_status_message or "").strip(),
            "normal_chat_available": False,
        }
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
