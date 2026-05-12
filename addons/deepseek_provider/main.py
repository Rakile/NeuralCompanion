from __future__ import annotations

import os
from typing import Any, Iterable

from openai import OpenAI

from core.addons.base import BaseAddon


PROVIDER_ID = "deepseek"
DEFAULT_BASE_URL = "https://api.deepseek.com"

FALLBACK_MODELS = [
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        "supports_images": False,
        "source": "deepseek_fallback",
    },
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "supports_images": False,
        "source": "deepseek_fallback",
    },
]


def _extract_text(response: Any) -> str:
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


def _stream_text(stream: Iterable[Any]):
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


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._chat_service = context.get_service("qt.chat_providers")
        if self._chat_service is None:
            context.logger.warning("DeepSeek provider addon could not find qt.chat_providers service.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="DeepSeek",
            description="Hosted DeepSeek V4 models through the OpenAI-compatible API.",
            order=350,
            client_factory=self._client,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            metadata={
                "config_fields": [
                    {"id": "api_key", "label": "API Key", "env": ["NC_CHAT_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"]},
                    {"id": "base_url", "label": "Base URL", "default": DEFAULT_BASE_URL, "env": ["NC_CHAT_DEEPSEEK_BASE_URL"]},
                ],
                "generation_fields": [
                    {
                        "id": "thinking_mode",
                        "label": "Thinking",
                        "kind": "select",
                        "default": "enabled",
                        "request_location": "params",
                        "description": "DeepSeek V4 supports thinking and non-thinking modes. Thinking is enabled by default.",
                        "options": [
                            {"label": "Enabled", "value": "enabled"},
                            {"label": "Disabled", "value": "disabled"},
                        ],
                    },
                    {
                        "id": "reasoning_effort",
                        "label": "Reasoning Effort",
                        "kind": "select",
                        "default": "",
                        "omit_if": [""],
                        "request_location": "params",
                        "description": "Optional DeepSeek V4 reasoning effort. Leave blank for DeepSeek's default.",
                        "options": [
                            {"label": "Default", "value": ""},
                            {"label": "High", "value": "high"},
                            {"label": "Max", "value": "max"},
                        ],
                    },
                    {"id": "temperature", "label": "Temperature", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.0, "request_location": "params"},
                    {"id": "top_p", "label": "Top P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 1.0, "request_location": "params"},
                    {"id": "frequency_penalty", "label": "Frequency Penalty", "kind": "float", "min": -2.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 0.0, "omit_if": [0.0, "0.0", "0"], "request_location": "params"},
                    {"id": "presence_penalty", "label": "Presence Penalty", "kind": "float", "min": -2.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 0.0, "omit_if": [0.0, "0.0", "0"], "request_location": "params"},
                    {"id": "max_tokens", "label": "Max Tokens", "kind": "int", "min": 1, "max": 393216, "step": 1, "default": 2048, "request_location": "params"},
                ],
                "hint": "Hosted DeepSeek provider. API key is required. Current V4 models are deepseek-v4-flash and deepseek-v4-pro.",
                "supports_hosted_runtime": True,
                "supports_streaming": True,
                "supports_images": False,
            },
        )
        context.logger.info("DeepSeek chat provider addon initialized.")
        return None

    def shutdown(self):
        chat_service = getattr(self, "_chat_service", None)
        if chat_service is not None:
            try:
                chat_service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        return None

    def _setting(self, field_id: str) -> str:
        chat_service = getattr(self, "_chat_service", None)
        getter = getattr(chat_service, "get_provider_setting", None)
        if callable(getter):
            try:
                return str(getter(PROVIDER_ID, field_id) or "").strip()
            except Exception:
                return ""
        return ""

    def _api_key(self) -> str:
        return self._setting("api_key") or str(
            os.environ.get("NC_CHAT_DEEPSEEK_API_KEY", "") or os.environ.get("DEEPSEEK_API_KEY", "") or ""
        ).strip()

    def _base_url(self) -> str:
        return self._setting("base_url") or str(os.environ.get("NC_CHAT_DEEPSEEK_BASE_URL", "") or DEFAULT_BASE_URL).strip()

    def _client(self) -> OpenAI:
        return OpenAI(api_key=self._api_key(), base_url=self._base_url())

    def _request_kwargs(self, params: dict[str, Any] | None, *, stream: bool = False) -> dict[str, Any]:
        request_kwargs = dict(params or {})
        thinking_mode = str(request_kwargs.pop("thinking_mode", "") or "").strip().lower()
        if thinking_mode in {"enabled", "disabled"}:
            extra_body = dict(request_kwargs.get("extra_body") or {})
            extra_body["thinking"] = {"type": thinking_mode}
            request_kwargs["extra_body"] = extra_body
        if stream:
            request_kwargs["stream"] = True
        return request_kwargs

    def _fallback_model_entries(self) -> list[dict[str, Any]]:
        return [dict(item) for item in FALLBACK_MODELS]

    def _list_models(self, quiet: bool = False):
        if not self._api_key():
            return self._fallback_model_entries()
        try:
            client = self._client()
            payload = client.models.list()
            models = []
            for model in list(getattr(payload, "data", []) or []):
                model_id = str(getattr(model, "id", "") or "").strip()
                if not model_id:
                    continue
                models.append(
                    {
                        "id": model_id,
                        "supports_images": False,
                        "source": "deepseek_models",
                    }
                )
            return models or self._fallback_model_entries()
        except Exception as exc:
            if not quiet:
                print(f"Error fetching DeepSeek models: {exc}")
            return self._fallback_model_entries()

    def _check_connection(self):
        if not self._api_key():
            return {"ok": False, "detail": "DeepSeek API key is required."}
        try:
            client = self._client()
            payload = client.models.list()
            count = len(list(getattr(payload, "data", []) or []))
            return {
                "ok": True,
                "detail": f"Connected to DeepSeek ({count} model(s) available)",
                "model_count": count,
            }
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    def _complete_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        client = self._client()
        response = client.chat.completions.create(**self._request_kwargs(params, stream=False))
        return _extract_text(response)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        client = self._client()
        stream = client.chat.completions.create(**self._request_kwargs(params, stream=True))
        return _stream_text(stream)
