"""Chat provider runtime facade.

This module turns the chat-provider registry into a reusable runtime service
without changing the existing provider registry or engine call surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Iterable

from core import chat_providers
from core.runtime.config import RuntimeConfigSnapshot
from core.runtime_contracts import ChatProviderAdapter, ProviderDescriptor, RuntimeStatus


ConfigSource = Mapping[str, Any] | RuntimeConfigSnapshot
ConfigGetter = Callable[[], ConfigSource]

_FROZEN_GENERATION_CONFIG_KEYS = (
    "temperature",
    "top_p",
    "top_k",
    "min_p",
    "repeat_penalty",
    "max_tokens",
    "max_completion_tokens",
    "enable_thinking",
    "reasoning",
    "limit_response_length",
    "max_response_tokens",
)
_ASSISTANT_PREFIX_ANCHOR_THRESHOLD = 5


class ChatProviderRuntime(ChatProviderAdapter):
    """Runtime-facing facade around the pluggable chat provider registry."""

    def __init__(self, config_getter: ConfigGetter):
        self._config_getter = config_getter

    @property
    def descriptor(self) -> ProviderDescriptor:
        provider_id = self.current_provider()
        metadata = chat_providers.provider_metadata(provider_id)
        return ProviderDescriptor(
            id=provider_id,
            label=chat_providers.provider_label(provider_id),
            description=str(metadata.get("description") or "").strip(),
            config_fields=tuple(),
            generation_fields=tuple(),
            metadata=metadata,
        )

    def _config(self) -> dict[str, Any]:
        try:
            config = _config_mapping(self._config_getter())
        except Exception:
            return {}
        return dict(config)

    def _capture_config(
        self,
        config_source: ConfigSource | None = None,
    ) -> Mapping[str, Any]:
        try:
            source = self._config_getter() if config_source is None else config_source
            config = _config_mapping(source)
        except Exception:
            raise chat_providers.FrozenChatProviderCaptureError(
                "Frozen runtime config capture failed."
            ) from None
        return config

    def current_provider(self, provider: str | None = None) -> str:
        config = self._config()
        return chat_providers.normalize_provider_id(
            provider or config.get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )

    def provider_label(self, provider: str | None = None) -> str:
        return chat_providers.provider_label(provider or self.current_provider())

    def provider_api_key(self, provider: str | None = None) -> str:
        return chat_providers.provider_api_key(provider or self.current_provider())

    def provider_base_url(self, provider: str | None = None) -> str:
        return chat_providers.provider_base_url(provider or self.current_provider())

    def provider_model_error(self, provider: str | None = None) -> str:
        return chat_providers.provider_model_error(provider or self.current_provider())

    def create_client(self, provider: str | None = None) -> Any:
        return chat_providers.create_client(provider or self.current_provider())

    def generation_settings(self, provider: str | None = None) -> dict[str, Any]:
        provider_key = self.current_provider(provider)
        raw_map = self._config().get("chat_provider_generation_settings", {}) or {}
        if not isinstance(raw_map, Mapping):
            return {}
        raw_settings = raw_map.get(provider_key, {})
        return dict(raw_settings or {}) if isinstance(raw_settings, Mapping) else {}

    def _coerce_generation_value(self, field: dict[str, Any], value: Any) -> Any:
        if value is None:
            return None
        kind = str((field or {}).get("kind") or "text").strip().lower()
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)
        if kind == "int":
            if value == "":
                return None
            parsed = int(float(value))
            if "min" in (field or {}):
                parsed = max(int((field or {}).get("min")), parsed)
            if "max" in (field or {}):
                parsed = min(int((field or {}).get("max")), parsed)
            return parsed
        if kind == "float":
            if value == "":
                return None
            parsed = float(value)
            if "min" in (field or {}):
                parsed = max(float((field or {}).get("min")), parsed)
            if "max" in (field or {}):
                parsed = min(float((field or {}).get("max")), parsed)
            return parsed
        return value

    def _omit_generation_value(self, field: dict[str, Any], value: Any) -> bool:
        if value is None:
            return True
        if value == "" and not bool((field or {}).get("required", False)):
            return True
        omit_values = (field or {}).get("omit_if", [])
        if not isinstance(omit_values, list):
            omit_values = [omit_values]
        for omit_value in omit_values:
            if value == omit_value or str(value) == str(omit_value):
                return True
        return False

    def _max_tokens_omit_cap_value(self, field: dict[str, Any]) -> Any:
        field_id = str((field or {}).get("id") or "").strip()
        if field_id not in {"max_tokens", "max_completion_tokens"}:
            return None
        omit_values = (field or {}).get("omit_if", [])
        if not isinstance(omit_values, list):
            omit_values = [omit_values]
        if any(str(value) == "-1" for value in omit_values):
            return -1
        return None

    def _legacy_generation_value(self, field: dict[str, Any], provider: str) -> Any:
        config = self._config()
        field_id = str((field or {}).get("id") or "").strip()
        if field_id in {"enable_thinking", "reasoning"} and str((field or {}).get("kind") or "").strip().lower() == "bool":
            return bool((field or {}).get("default", True))
        if field_id in {"temperature", "top_p", "repeat_penalty", "min_p"}:
            return config.get(field_id, (field or {}).get("default"))
        if field_id == "top_k":
            return config.get("top_k", (field or {}).get("default"))
        if field_id in {"max_tokens", "max_completion_tokens"}:
            provider_settings = chat_providers.get_provider_settings(provider)
            if isinstance(provider_settings, dict) and provider_settings.get("max_tokens") not in {None, ""}:
                return provider_settings.get("max_tokens")
            omit_cap_value = self._max_tokens_omit_cap_value(field)
            if omit_cap_value is not None:
                return omit_cap_value
            if bool(config.get("limit_response_length", False)):
                return max(1, int(config.get("max_response_tokens", 600) or 600))
            if provider == "lmstudio":
                return -1
        return (field or {}).get("default")

    def apply_generation_fields(self, params: dict[str, Any], additional_params: dict[str, Any], provider: str | None = None) -> None:
        config = self._config()
        provider_key = self.current_provider(provider)
        metadata = chat_providers.provider_metadata(provider_key)
        fields = [dict(item) for item in list(metadata.get("generation_fields") or []) if isinstance(item, dict)]
        if not fields:
            if "temperature" in config:
                params["temperature"] = float(config["temperature"])
            if "top_p" in config:
                params["top_p"] = float(config["top_p"])
            if bool(config.get("limit_response_length")):
                params["max_tokens"] = max(1, int(config.get("max_response_tokens", 600) or 600))
            elif provider_key == "lmstudio":
                # LM Studio applies its own generation cap when max_tokens is omitted.
                # Sending -1 matches LM Studio's documented "no explicit response cap" behavior.
                params["max_tokens"] = -1
            if "top_k" in config:
                additional_params["top_k"] = int(config["top_k"])
            if "min_p" in config:
                additional_params["min_p"] = float(config["min_p"])
            if "repeat_penalty" in config:
                additional_params["repeat_penalty"] = float(
                    config["repeat_penalty"]
                )
            return

        settings = self.generation_settings(provider_key)
        max_token_applied = False
        for field in fields:
            field_id = str(field.get("id") or "").strip()
            if not field_id or str(field.get("kind") or "").strip().lower() == "note":
                continue
            required_support = str(field.get("requires_model_support") or "").strip().lower()
            if required_support:
                support_key = f"model_supports_{required_support}"
                if not bool(config.get(support_key, False)):
                    continue
            if field_id in settings:
                raw_value = settings[field_id]
            elif metadata.get("legacy_generation_fallback", True) is False:
                raw_value = field.get("default")
            else:
                raw_value = self._legacy_generation_value(field, provider_key)
            try:
                value = self._coerce_generation_value(field, raw_value)
            except Exception:
                value = field.get("default")
            if str(field.get("kind") or "").strip().lower() == "bool":
                if value is True and "true_value" in field:
                    value = field.get("true_value")
                elif value is False and "false_value" in field:
                    value = field.get("false_value")
            if self._omit_generation_value(field, value):
                continue
            request_key = str(field.get("request_key") or field_id).strip()
            request_location = str(field.get("request_location") or "params").strip().lower()
            if not request_key or request_location == "none":
                continue
            if request_location == "additional_params":
                additional_params[request_key] = value
            else:
                params[request_key] = value
            if request_key in {"max_tokens", "max_completion_tokens"}:
                max_token_applied = True

        if not max_token_applied:
            has_omitted_max_token_field = any(
                self._max_tokens_omit_cap_value(field) is not None
                for field in fields
                if isinstance(field, dict)
            )
            if bool(config.get("limit_response_length")) and not has_omitted_max_token_field:
                params["max_tokens"] = max(1, int(config.get("max_response_tokens", 600) or 600))
            elif provider_key == "lmstudio":
                params["max_tokens"] = -1

    def _capture_generation_fields(
        self,
        config: Mapping[str, Any],
        provider: chat_providers.ChatProvider,
    ) -> dict[str, Any]:
        provider_id = str(provider.id or "").strip().lower()
        raw_map = config.get("chat_provider_generation_settings", {}) or {}
        raw_settings = raw_map.get(provider_id, {}) if isinstance(raw_map, Mapping) else {}
        captured = dict(raw_settings) if isinstance(raw_settings, Mapping) else {}
        metadata = dict(provider.metadata or {})
        legacy_fallback = metadata.get("legacy_generation_fallback", True) is not False
        fields = [field for field in metadata.get("generation_fields", []) or []
                  if isinstance(field, Mapping)]
        provider_field_ids = {str(field.get("id") or "").strip() for field in fields}
        for key in _FROZEN_GENERATION_CONFIG_KEYS:
            if not legacy_fallback and key in provider_field_ids:
                continue
            if key in config and key not in captured:
                captured[key] = config[key]
        for key, value in config.items():
            if str(key).startswith("model_supports_") and key not in captured:
                captured[str(key)] = value
        for field in fields:
            field_id = str(field.get("id") or "").strip()
            if not field_id or field_id in captured:
                continue
            if legacy_fallback and field_id in config:
                captured[field_id] = config[field_id]
            elif "default" in field:
                captured[field_id] = field.get("default")
        return captured

    def capture_frozen_context(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        provider_config: Mapping[str, Any] | None = None,
        generation_fields: Mapping[str, Any] | None = None,
        runtime_config: ConfigSource | None = None,
    ) -> chat_providers.FrozenChatProviderContext:
        config = self._capture_config(runtime_config)
        provider_registration = chat_providers._resolve_provider(
            provider or config.get("chat_provider", chat_providers.DEFAULT_PROVIDER_ID),
            chat_providers.DEFAULT_PROVIDER_ID,
        )
        if provider_registration is None:
            raise chat_providers.FrozenChatProviderUnsupportedError(
                "No chat provider is registered for frozen capture."
            )
        if not provider_registration.normal_chat_available:
            raise chat_providers.FrozenChatProviderUnsupportedError(
                provider_registration.normal_chat_status_message
            ) from None
        model_name = str(model if model is not None else config.get("model_name", "") or "").strip()
        captured_generation_fields = (
            generation_fields
            if generation_fields is not None
            else self._capture_generation_fields(config, provider_registration)
        )
        return chat_providers.capture_frozen_provider_context(
            provider_registration,
            model_name=model_name,
            provider_config=provider_config,
            generation_fields=captured_generation_fields,
        )

    def prepare_frozen_request(
        self,
        context: chat_providers.FrozenChatProviderContext,
        params: Mapping[str, Any],
        additional_params: Mapping[str, Any] | None = None,
    ) -> chat_providers.FrozenChatProviderRequest:
        prepared_params = dict(params or {})
        if context.model_name:
            prepared_params["model"] = context.model_name
        return chat_providers.prepare_frozen_chat_request(
            context=context,
            params=prepared_params,
            additional_params=additional_params,
        )

    def normalize_request_params(
        self,
        provider: str,
        params: dict[str, Any],
        *,
        runtime_config: ConfigSource | None = None,
    ) -> dict[str, Any]:
        config = self._config() if runtime_config is None else runtime_config
        return normalize_provider_request_params(
            provider,
            params,
            runtime_config=config,
        )

    def frozen_execution_available(
        self,
        context: chat_providers.FrozenChatProviderContext,
        *,
        stream: bool = False,
    ) -> bool:
        return chat_providers.frozen_execution_available(context, stream=stream)

    def strict_relay_capability_available(
        self,
        context: chat_providers.FrozenChatProviderContext,
    ) -> bool:
        return context.strict_relay_available

    def upgrade_frozen_context_for_relay(
        self,
        context: chat_providers.FrozenChatProviderContext,
    ) -> chat_providers.FrozenChatProviderContext:
        return chat_providers.upgrade_frozen_context_for_relay(context)

    def complete_frozen(
        self,
        request: chat_providers.FrozenChatProviderRequest,
        *,
        timeout: float | None = None,
        cancel_token: Any = None,
    ) -> Any:
        return chat_providers.complete_frozen_chat(
            request,
            timeout=timeout,
            cancel_token=cancel_token,
        )

    def stream_frozen(
        self,
        request: chat_providers.FrozenChatProviderRequest,
        *,
        timeout: float | None = None,
        cancel_token: Any = None,
    ) -> Iterable[str]:
        return chat_providers.stream_frozen_chat(
            request,
            timeout=timeout,
            cancel_token=cancel_token,
        )

    def list_models(self, *, quiet: bool = False, provider: str | None = None) -> list[Any]:
        return chat_providers.list_models(self.current_provider(provider), quiet=quiet)

    def complete(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> Any:
        return chat_providers.complete_chat(self.current_provider(), params, additional_params)

    def stream(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> Iterable[str]:
        return chat_providers.stream_chat(self.current_provider(), params, additional_params)

    def check_connection(self, provider: str | None = None) -> RuntimeStatus:
        provider_id = self.current_provider(provider)
        label = self.provider_label(provider_id)
        try:
            result = dict(chat_providers.check_connection(provider_id) or {})
            ok = bool(result.get("ok"))
            detail = str(result.get("detail") or ("Connected to " + label if ok else "Could not connect to " + label)).strip()
            return RuntimeStatus(ok=ok, label=label, message=detail, metadata=result)
        except Exception as exc:
            return RuntimeStatus(ok=False, label=label, message=f"Could not connect to {label}: {exc}")


def _config_mapping(source: ConfigSource) -> Mapping[str, Any]:
    if isinstance(source, RuntimeConfigSnapshot):
        return source.values
    if isinstance(source, Mapping):
        return source
    raise TypeError("Chat runtime configuration must be a mapping or snapshot.")


def normalize_provider_request_params(
    provider: str,
    params: dict[str, Any],
    *,
    runtime_config: ConfigSource,
) -> dict[str, Any]:
    if str(provider or "").strip().lower() != "lmstudio":
        return params
    return _coalesce_lmstudio_system_messages(
        params,
        runtime_config=_config_mapping(runtime_config),
    )


def _lmstudio_message_content_parts(content: object) -> list[object] | None:
    if isinstance(content, list):
        return list(content)
    if isinstance(content, str):
        if not content:
            return []
        return [{"type": "text", "text": content}]
    return None


def _merge_lmstudio_message_content(
    first_content: object,
    second_content: object,
) -> object | None:
    if isinstance(first_content, str) and isinstance(second_content, str):
        if not first_content:
            return second_content
        if not second_content:
            return first_content
        return f"{first_content}\n\n{second_content}"
    first_parts = _lmstudio_message_content_parts(first_content)
    second_parts = _lmstudio_message_content_parts(second_content)
    if first_parts is None or second_parts is None:
        return None
    return first_parts + second_parts


def _lmstudio_message_envelope(message: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in dict(message or {}).items()
        if key not in {"role", "content"}
    }


def _merge_lmstudio_consecutive_role_messages(
    messages: Iterable[object],
) -> list[object]:
    merged_messages: list[object] = []
    for message in list(messages or []):
        if not isinstance(message, dict):
            merged_messages.append(message)
            continue
        role = str(message.get("role", "") or "").strip().lower()
        previous = merged_messages[-1] if merged_messages else None
        previous_role = (
            str(previous.get("role", "") or "").strip().lower()
            if isinstance(previous, dict)
            else ""
        )
        if role not in {"user", "assistant"} or role != previous_role:
            merged_messages.append(message)
            continue
        if _lmstudio_message_envelope(previous) != _lmstudio_message_envelope(message):
            merged_messages.append(message)
            continue
        merged_content = _merge_lmstudio_message_content(
            previous.get("content"),
            message.get("content"),
        )
        if merged_content is None:
            merged_messages.append(message)
            continue
        combined_message = dict(previous)
        combined_message["role"] = role
        combined_message["content"] = merged_content
        merged_messages[-1] = combined_message
    return merged_messages


def _coalesce_lmstudio_system_messages(
    params: dict[str, Any],
    *,
    runtime_config: Mapping[str, Any],
) -> dict[str, Any]:
    from core import conversation_history as conversation_history_runtime

    if not isinstance(params, dict):
        return params
    messages = params.get("messages")
    if not isinstance(messages, list):
        return params

    system_messages: list[str] = []
    non_system_messages: list[object] = []
    system_count = 0
    first_system_message: dict[str, object] | None = None
    for message in messages:
        if not isinstance(message, dict) or str(
            message.get("role", "") or ""
        ).strip().lower() != "system":
            non_system_messages.append(message)
            continue
        system_count += 1
        content = message.get("content")
        if not isinstance(content, str):
            return params
        if first_system_message is None:
            first_system_message = message
        if content.strip():
            system_messages.append(content)

    if first_system_message is None:
        return params

    combined_system_message = dict(first_system_message)
    combined_system_message["role"] = "system"
    combined_system_message["content"] = (
        str(first_system_message.get("content") or "")
        if system_count == 1
        else "\n\n".join(system_messages)
    )
    repaired_non_system_messages = (
        conversation_history_runtime.repair_model_history_window(
            non_system_messages,
            policy=conversation_history_runtime.chat_context_overflow_policy(
                runtime_config
            ),
            assistant_prefix_anchor_threshold=_ASSISTANT_PREFIX_ANCHOR_THRESHOLD,
        )
    )
    normalized_messages = [combined_system_message]
    normalized_messages.extend(
        _merge_lmstudio_consecutive_role_messages(repaired_non_system_messages)
    )
    if normalized_messages == messages:
        return params

    normalized_params = dict(params)
    normalized_params["messages"] = normalized_messages
    return normalized_params
