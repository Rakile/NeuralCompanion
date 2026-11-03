from __future__ import annotations

import os
from typing import Any, Mapping

from core.addons.base import BaseAddon


PROVIDER_ID = "my_provider"


def _coerce_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        return min(maximum, max(minimum, float(value)))
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(maximum, max(minimum, int(float(value))))
    except (TypeError, ValueError):
        return default


def _frozen_request_params(binding, params: Mapping[str, Any]) -> dict[str, Any]:
    request = dict(params or {})
    generation = binding._generation_fields_copy()
    request["model"] = binding.model_name
    if "temperature" in generation:
        request["temperature"] = _coerce_float(
            generation["temperature"],
            0.7,
            0.0,
            2.0,
        )
    if "max_tokens" in generation:
        request["max_tokens"] = _coerce_int(
            generation["max_tokens"],
            1024,
            1,
            8192,
        )
    return request


def _frozen_binding(request):
    binding = getattr(request.context, "_binding", None)
    if binding is None or binding.provider_name != PROVIDER_ID:
        raise RuntimeError("My Provider frozen request binding is unavailable.")
    return binding


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._chat_service = context.get_service("qt.chat_providers")
        if self._chat_service is None:
            context.logger.warning("Chat provider service is unavailable.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="My Provider",
            description="Example external chat provider.",
            order=900,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            normal_chat_capable=True,
            frozen_execution_version=1,
            frozen_prepare_handler=self._prepare_frozen_chat,
            frozen_completion_handler=self._complete_frozen_chat,
            frozen_stream_handler=self._stream_frozen_chat,
            frozen_private_config_getter=self._frozen_private_config,
            frozen_public_config_fields=("base_url", "provider_is_remote"),
            metadata={
                "config_fields": [
                    {"id": "api_key", "label": "API Key", "env": ["MY_PROVIDER_API_KEY"]},
                    {"id": "base_url", "label": "Base URL", "default": "https://api.example.com"},
                ],
                "generation_fields": [
                    {
                        "id": "temperature",
                        "label": "Temperature",
                        "kind": "float",
                        "min": 0.0,
                        "max": 2.0,
                        "step": 0.01,
                        "decimals": 2,
                        "default": 0.7,
                        "request_location": "params",
                    },
                    {
                        "id": "max_tokens",
                        "label": "Max Tokens",
                        "kind": "int",
                        "min": 1,
                        "max": 8192,
                        "step": 1,
                        "default": 1024,
                        "request_location": "params",
                    },
                ],
                "hint": "Replace the template provider transport methods with your provider API calls.",
                "supports_hosted_runtime": True,
            },
        )
        return None

    def shutdown(self):
        if getattr(self, "_chat_service", None) is not None:
            self._chat_service.unregister_provider(PROVIDER_ID)
        return None

    def _setting(self, field_id: str) -> str:
        getter = getattr(self._chat_service, "get_provider_setting", None)
        return str(getter(PROVIDER_ID, field_id) or "").strip() if callable(getter) else ""

    def _api_key(self) -> str:
        return self._setting("api_key") or str(os.environ.get("MY_PROVIDER_API_KEY", "") or "").strip()

    def _base_url(self) -> str:
        return self._setting("base_url") or "https://api.example.com"

    def _frozen_private_config(self) -> dict[str, Any]:
        return {
            "api_key": self._api_key(),
            "base_url": self._base_url(),
            "provider_is_remote": True,
        }

    def _list_models(self, quiet: bool = False):
        return ["example-chat-model"]

    def _check_connection(self):
        return {"ok": bool(self._api_key()), "detail": "API key configured." if self._api_key() else "API key is required."}

    def _complete_chat(self, params, additional_params=None) -> str:
        return self._complete_provider_request(
            self._frozen_private_config(),
            dict(params or {}),
            dict(additional_params or {}),
        )

    def _stream_chat(self, params, additional_params=None):
        return self._stream_provider_request(
            self._frozen_private_config(),
            dict(params or {}),
            dict(additional_params or {}),
        )

    def _prepare_frozen_chat(self, binding, params, additional_params):
        return (
            _frozen_request_params(binding, params),
            dict(additional_params or {}),
        )

    def _complete_frozen_chat(
        self,
        request,
        *,
        timeout=None,
        cancel_token=None,
    ) -> str:
        del cancel_token
        binding = _frozen_binding(request)
        params = request.params_copy()
        if timeout is not None:
            params["timeout"] = timeout
        return self._complete_provider_request(
            binding._provider_config_copy(),
            params,
            request.additional_params_copy(),
        )

    def _stream_frozen_chat(
        self,
        request,
        *,
        timeout=None,
        cancel_token=None,
    ):
        del cancel_token
        binding = _frozen_binding(request)
        params = request.params_copy()
        if timeout is not None:
            params["timeout"] = timeout
        return self._stream_provider_request(
            binding._provider_config_copy(),
            params,
            request.additional_params_copy(),
        )

    def _complete_provider_request(
        self,
        provider_config: Mapping[str, Any],
        params: Mapping[str, Any],
        additional_params: Mapping[str, Any] | None = None,
    ) -> str:
        raise NotImplementedError(
            "Call your provider API with the supplied frozen config and return one assistant string."
        )

    def _stream_provider_request(
        self,
        provider_config: Mapping[str, Any],
        params: Mapping[str, Any],
        additional_params: Mapping[str, Any] | None = None,
    ):
        raise NotImplementedError(
            "Call your provider API with the supplied frozen config and yield assistant text chunks."
        )
