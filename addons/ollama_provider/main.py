from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Iterable
from urllib.request import Request, urlopen

from openai import OpenAI

from core.addons.base import BaseAddon


PROVIDER_ID = "ollama"
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_API_KEY = "ollama"


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
        self._last_model_name = ""
        self._last_unload_at = 0.0
        self._chat_service = context.get_service("qt.chat_providers")
        if self._chat_service is None:
            context.logger.warning("Ollama provider addon could not find qt.chat_providers service.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="Ollama",
            description="Local Ollama models exposed through the OpenAI-compatible API.",
            order=150,
            client_factory=self._client,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            metadata={
                "config_fields": [
                    {
                        "id": "base_url",
                        "label": "Base URL",
                        "default": DEFAULT_BASE_URL,
                        "env": ["NC_CHAT_OLLAMA_BASE_URL"],
                    },
                    {
                        "id": "api_key",
                        "label": "API Key",
                        "default": DEFAULT_API_KEY,
                        "env": ["NC_CHAT_OLLAMA_API_KEY"],
                        "description": "Ollama does not require a real API key; this dummy value keeps OpenAI-compatible clients happy.",
                    },
                ],
                "generation_fields": [
                    {"id": "temperature", "label": "Temperature", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.0, "request_location": "params"},
                    {"id": "top_p", "label": "Top P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.9, "request_location": "params"},
                    {"id": "top_k", "label": "Top K", "kind": "int", "min": 0, "max": 1000, "step": 1, "default": 40, "request_location": "additional_params"},
                    {"id": "min_p", "label": "Min P", "kind": "float", "min": 0.0, "max": 1.0, "step": 0.01, "decimals": 2, "default": 0.05, "request_location": "additional_params"},
                    {"id": "repeat_penalty", "label": "Repetition Penalty", "kind": "float", "min": 0.0, "max": 2.0, "step": 0.01, "decimals": 2, "default": 1.1, "request_location": "additional_params"},
                    {
                        "id": "max_tokens",
                        "label": "Max Tokens (-1 = provider default)",
                        "kind": "int",
                        "min": -1,
                        "max": 131072,
                        "step": 1,
                        "default": -1,
                        "omit_if": [-1, "-1"],
                        "request_location": "params",
                        "description": "Use -1 to omit max_tokens and let Ollama/model settings choose the response cap.",
                    },
                ],
                "hint": "Local Ollama provider. Start Ollama and keep the OpenAI-compatible base URL at http://127.0.0.1:11434/v1 unless you changed it.",
                "supports_hosted_runtime": False,
                "supports_streaming": True,
                "supports_images": False,
            },
        )
        context.events.subscribe("runtime.engine_starting", self._on_engine_starting)
        context.events.subscribe("runtime.engine_stop_requested", self._on_engine_stop_requested)
        context.events.subscribe("runtime.engine_stopped", self._on_engine_stopped)
        context.logger.info("Ollama chat provider addon initialized.")
        return None

    def shutdown(self):
        self._unload_running_models(reason="addon_shutdown", quiet=True)
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
        return self._setting("api_key") or str(os.environ.get("NC_CHAT_OLLAMA_API_KEY", "") or DEFAULT_API_KEY).strip()

    def _base_url(self) -> str:
        return self._setting("base_url") or str(os.environ.get("NC_CHAT_OLLAMA_BASE_URL", "") or DEFAULT_BASE_URL).strip()

    def _native_api_base_url(self) -> str:
        base_url = str(self._base_url() or DEFAULT_BASE_URL).strip().rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        return base_url.rstrip("/") or "http://127.0.0.1:11434"

    def _client(self) -> OpenAI:
        return OpenAI(api_key=self._api_key(), base_url=self._base_url())

    def _request_kwargs(
        self,
        params: dict[str, Any] | None,
        additional_params: dict[str, Any] | None = None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        request_kwargs = dict(params or {})
        options = {
            key: value
            for key, value in dict(additional_params or {}).items()
            if value is not None
        }
        if options:
            request_kwargs["extra_body"] = {"options": options}
        if stream:
            request_kwargs["stream"] = True
        return request_kwargs

    def _native_json_request(self, path: str, payload: dict[str, Any] | None = None, *, timeout: float = 5.0):
        url = f"{self._native_api_base_url()}/{str(path or '').lstrip('/')}"
        data = None
        method = "GET"
        headers = {"Accept": "application/json"}
        if payload is not None:
            method = "POST"
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        with urlopen(request, timeout=float(timeout)) as response:
            raw_payload = response.read()
        if not raw_payload:
            return {}
        return json.loads(raw_payload.decode("utf-8", errors="replace"))

    def _running_model_names(self) -> list[str]:
        payload = self._native_json_request("api/ps", timeout=2.0)
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return []
        names: list[str] = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = str(model.get("name") or model.get("model") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    def _unload_model(self, model_name: str) -> bool:
        model = str(model_name or "").strip()
        if not model:
            return False
        payload = {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
        }
        self._native_json_request("api/generate", payload, timeout=15.0)
        return True

    def _unload_running_models(self, *, reason: str = "", quiet: bool = False, force: bool = False) -> int:
        now = time.monotonic()
        if not force and now - float(getattr(self, "_last_unload_at", 0.0) or 0.0) < 1.0:
            return 0
        self._last_unload_at = now
        try:
            names = self._running_model_names()
            if not names and str(getattr(self, "_last_model_name", "") or "").strip():
                names = [str(getattr(self, "_last_model_name", "") or "").strip()]
            unloaded = 0
            for name in names:
                if self._unload_model(name):
                    unloaded += 1
            if unloaded and not quiet:
                detail = f" ({reason})" if reason else ""
                print(f"🧹 [Ollama] Unloaded {unloaded} running model(s){detail}.")
            return unloaded
        except Exception as exc:
            if not quiet:
                print(f"⚠️ [Ollama] Could not unload running model(s): {exc}")
            return 0

    def _unload_running_models_background(self, *, reason: str = "") -> None:
        thread = threading.Thread(
            target=lambda: self._unload_running_models(reason=reason),
            name="nc-ollama-unload",
            daemon=True,
        )
        thread.start()

    def _on_engine_starting(self, payload):
        self._unload_running_models_background(reason="engine_start")

    def _on_engine_stop_requested(self, payload):
        self._unload_running_models_background(reason="engine_stop")

    def _on_engine_stopped(self, payload):
        self._unload_running_models_background(reason="engine_stopped")

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
                print(f"Error fetching Ollama models: {exc}")
            return []

    def _check_connection(self):
        self._unload_running_models(reason="engine_init", quiet=True, force=True)
        try:
            client = self._client()
            payload = client.models.list()
            count = len(list(getattr(payload, "data", []) or []))
            return {
                "ok": True,
                "detail": f"Connected to Ollama ({count} model(s) available)",
                "model_count": count,
            }
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    def _complete_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        self._last_model_name = str((params or {}).get("model") or self._last_model_name or "").strip()
        client = self._client()
        response = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=False))
        return _extract_text(response)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        self._last_model_name = str((params or {}).get("model") or self._last_model_name or "").strip()
        client = self._client()
        stream = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=True))
        return _stream_text(stream)
