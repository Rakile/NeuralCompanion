from __future__ import annotations

import os
from typing import Any, Iterable

from openai import OpenAI

from core.addons.base import BaseAddon


PROVIDER_ID = "openai"


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
            context.logger.warning("OpenAI provider addon could not find qt.chat_providers service.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="OpenAI",
            description="Hosted OpenAI models.",
            order=200,
            client_factory=self._client,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            metadata={
                "config_fields": [
                    {"id": "api_key", "label": "API Key", "env": ["NC_CHAT_OPENAI_API_KEY", "OPENAI_API_KEY"]},
                    {"id": "base_url", "label": "Base URL", "env": ["NC_CHAT_OPENAI_BASE_URL"]},
                ],
                "generation_fields": [
                    {"id": "temperature", "label": "Temperature", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.0, "request_location": "params"},
                    {"id": "top_p", "label": "Top P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.9, "request_location": "params"},
                    {"id": "max_tokens", "label": "Max Tokens", "kind": "int", "min": 1, "max": 131072, "step": 1, "default": 2048, "request_location": "params"},
                ],
                "hint": "Hosted OpenAI provider. API key is required.",
                "supports_hosted_runtime": True,
            },
        )
        context.logger.info("OpenAI chat provider addon initialized.")
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
        return self._setting("api_key") or str(os.environ.get("NC_CHAT_OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "") or "").strip()

    def _base_url(self) -> str:
        return self._setting("base_url") or str(os.environ.get("NC_CHAT_OPENAI_BASE_URL", "") or "").strip()

    def _client(self) -> OpenAI:
        base_url = self._base_url()
        api_key = self._api_key()
        if base_url:
            return OpenAI(api_key=api_key, base_url=base_url)
        return OpenAI(api_key=api_key)

    def _list_models(self, quiet: bool = False):
        try:
            client = self._client()
            payload = client.models.list()
            ids = sorted(
                {
                    str(getattr(model, "id", "") or "").strip()
                    for model in list(getattr(payload, "data", []) or [])
                    if str(getattr(model, "id", "") or "").strip()
                }
            )
            return ids
        except Exception as exc:
            if not quiet:
                print(f"Error fetching OpenAI models: {exc}")
            return []

    def _check_connection(self):
        if not self._api_key():
            return {"ok": False, "detail": "OpenAI API key is required."}
        try:
            client = self._client()
            payload = client.models.list()
            count = len(list(getattr(payload, "data", []) or []))
            return {
                "ok": True,
                "detail": f"Connected to OpenAI ({count} model(s) available)",
                "model_count": count,
            }
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    def _complete_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        client = self._client()
        response = client.chat.completions.create(**dict(params or {}))
        return _extract_text(response)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        client = self._client()
        stream = client.chat.completions.create(**{**dict(params or {}), "stream": True})
        return _stream_text(stream)
