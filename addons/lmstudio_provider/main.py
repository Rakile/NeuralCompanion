from __future__ import annotations

import json
from typing import Any, Iterable
from urllib.request import Request, urlopen

from openai import OpenAI

from core.addons.base import BaseAddon


PROVIDER_ID = "lmstudio"
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"


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
            context.logger.warning("LM Studio provider addon could not find qt.chat_providers service.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="LM Studio",
            description="Local LM Studio models exposed through the OpenAI-compatible API.",
            order=100,
            client_factory=self._client,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            metadata={
                "config_fields": [
                    {"id": "base_url", "label": "Base URL", "source": "addon", "default": DEFAULT_BASE_URL},
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
        context.logger.info("LM Studio chat provider addon initialized.")
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
        return self._setting("api_key") or DEFAULT_API_KEY

    def _base_url(self) -> str:
        return self._setting("base_url") or DEFAULT_BASE_URL

    def _native_api_base_url(self) -> str:
        base_url = str(self._base_url() or DEFAULT_BASE_URL).strip().rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        return base_url.rstrip("/") or "http://127.0.0.1:1234"

    def _client(self) -> OpenAI:
        return OpenAI(base_url=self._base_url(), api_key=self._api_key())

    def _request_kwargs(self, params: dict[str, Any] | None, additional_params: dict[str, Any] | None = None, *, stream: bool = False) -> dict[str, Any]:
        request_kwargs = dict(params or {})
        if additional_params:
            request_kwargs["extra_body"] = dict(additional_params or {})
        if stream:
            request_kwargs["stream"] = True
        return request_kwargs

    def _list_models(self, quiet: bool = False):
        native_models = self._list_native_models(quiet=quiet)
        if native_models is not None:
            return native_models
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
                print(f"Error fetching LM Studio models: {exc}")
            return []

    def _list_native_models(self, quiet: bool = False):
        url = f"{self._native_api_base_url()}/api/v1/models"
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        try:
            request = Request(url, headers=headers, method="GET")
            with urlopen(request, timeout=5.0) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception as exc:
            if not quiet:
                print(f"Error fetching LM Studio native model metadata: {exc}")
            return None
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return None
        catalog = []
        for model in models:
            if not isinstance(model, dict):
                continue
            if str(model.get("type") or "").strip().lower() not in {"", "llm"}:
                continue
            model_id = str(model.get("key") or model.get("id") or "").strip()
            if not model_id:
                continue
            capabilities = model.get("capabilities") if isinstance(model.get("capabilities"), dict) else {}
            catalog.append(
                {
                    "id": model_id,
                    "supports_images": bool(capabilities.get("vision", False)),
                    "source": "lmstudio_native",
                }
            )
        return sorted(catalog, key=lambda item: str(item.get("id") or "").lower())

    def _check_connection(self):
        try:
            client = self._client()
            payload = client.models.list()
            count = len(list(getattr(payload, "data", []) or []))
            return {
                "ok": True,
                "detail": f"Connected to LM Studio ({count} model(s) available)",
                "model_count": count,
            }
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    def _complete_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        client = self._client()
        response = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=False))
        return _extract_text(response)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        client = self._client()
        stream = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=True))
        return _stream_text(stream)
