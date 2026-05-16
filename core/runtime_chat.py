"""Chat provider runtime facade.

This module turns the chat-provider registry into a reusable runtime service
without changing the existing provider registry or engine call surface.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from core import chat_providers
from core.runtime_contracts import ChatProviderAdapter, ProviderDescriptor, RuntimeStatus


ConfigGetter = Callable[[], dict[str, Any]]


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
            config = self._config_getter()
        except Exception:
            config = {}
        return config if isinstance(config, dict) else {}

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
        if not isinstance(raw_map, dict):
            return {}
        raw_settings = raw_map.get(provider_key, {})
        return dict(raw_settings or {}) if isinstance(raw_settings, dict) else {}

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
            params["temperature"] = float(config["temperature"])
            params["top_p"] = float(config["top_p"])
            if bool(config.get("limit_response_length")):
                params["max_tokens"] = max(1, int(config.get("max_response_tokens", 600) or 600))
            elif provider_key == "lmstudio":
                # LM Studio applies its own generation cap when max_tokens is omitted.
                # Sending -1 matches LM Studio's documented "no explicit response cap" behavior.
                params["max_tokens"] = -1
            additional_params.update({
                "top_k": int(config["top_k"]),
                "min_p": float(config["min_p"]),
                "repeat_penalty": float(config["repeat_penalty"]),
            })
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
            raw_value = settings[field_id] if field_id in settings else self._legacy_generation_value(field, provider_key)
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
            if bool(config.get("limit_response_length")):
                params["max_tokens"] = max(1, int(config.get("max_response_tokens", 600) or 600))
            elif provider_key == "lmstudio":
                params["max_tokens"] = -1

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
