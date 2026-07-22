from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Any, Iterable
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from openai import OpenAI

from core.addons.base import BaseAddon


PROVIDER_ID = "ollama"
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_API_KEY = "ollama"
_LOCAL_BIND_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _is_local_base_url(base_url: Any) -> bool:
    host = str(urlsplit(str(base_url or "").strip()).hostname or "").lower()
    return not host or host in _LOCAL_BIND_HOSTS


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
            frozen_execution_version=1,
            frozen_prepare_handler=self._prepare_frozen_chat,
            frozen_completion_handler=self._complete_frozen_chat,
            frozen_stream_handler=self._stream_frozen_chat,
            model_capabilities_handler=self._frozen_model_capabilities,
            frozen_private_config_getter=self._frozen_private_config,
            frozen_public_config_fields=("base_url", "provider_is_remote"),
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
                        "id": "reasoning",
                        "label": "Enable Thinking",
                        "kind": "bool",
                        "default": True,
                        "request_location": "params",
                        "request_key": "reasoning_effort",
                        "true_value": "medium",
                        "false_value": "none",
                        "requires_model_support": "reasoning_toggle",
                        "description": "Shown when Ollama reports the selected model has the thinking capability. Sends reasoning_effort=medium when enabled and reasoning_effort=none when disabled.",
                    },
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

    def _frozen_private_config(self) -> dict[str, Any]:
        base_url = self._base_url()
        return {
            "base_url": base_url,
            "provider_is_remote": not _is_local_base_url(base_url),
        }

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

    @staticmethod
    def _frozen_binding_config(binding: Any) -> dict[str, Any]:
        copy_config = getattr(binding, "_provider_config_copy", None)
        if not callable(copy_config):
            raise RuntimeError("Ollama frozen execution requires a captured provider binding.")
        config = copy_config()
        if not isinstance(config, dict):
            raise RuntimeError("Ollama frozen execution requires captured provider configuration.")
        return config

    @staticmethod
    def _frozen_generation_fields(binding: Any) -> dict[str, Any]:
        copy_fields = getattr(binding, "_generation_fields_copy", None)
        if not callable(copy_fields):
            raise RuntimeError("Ollama frozen execution requires captured generation fields.")
        fields = copy_fields()
        if not isinstance(fields, dict):
            raise RuntimeError("Ollama frozen execution requires captured generation fields.")
        return fields

    @staticmethod
    def _frozen_number(value: Any, *, minimum: float, maximum: float, default: float) -> float:
        try:
            return max(minimum, min(maximum, float(value)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _frozen_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _prepare_frozen_chat(
        self,
        binding: Any,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Prepare one immutable Ollama request without consulting live addon state."""
        del self
        generation = Addon._frozen_generation_fields(binding)
        prepared_params = dict(params or {})
        prepared_additional = dict(additional_params or {})
        model_name = str(getattr(binding, "model_name", "") or "").strip()
        if not model_name:
            raise RuntimeError("Ollama frozen execution requires a captured model.")
        prepared_params["model"] = model_name

        for field_name, minimum, maximum, default in (
            ("temperature", 0.0, 2.0, 1.0),
            ("top_p", 0.0, 1.0, 0.9),
        ):
            if field_name in generation and generation[field_name] is not None:
                prepared_params[field_name] = Addon._frozen_number(
                    generation[field_name],
                    minimum=minimum,
                    maximum=maximum,
                    default=default,
                )

        for field_name, minimum, maximum, default in (
            ("top_k", 0, 1000, 40),
            ("min_p", 0.0, 1.0, 0.05),
            ("repeat_penalty", 0.0, 2.0, 1.1),
        ):
            if field_name in generation and generation[field_name] is not None:
                value = Addon._frozen_number(
                    generation[field_name],
                    minimum=minimum,
                    maximum=maximum,
                    default=default,
                )
                prepared_additional[field_name] = int(value) if field_name == "top_k" else value

        if bool(generation.get("model_supports_reasoning_toggle", False)) and "reasoning" in generation:
            prepared_params["reasoning_effort"] = (
                "medium" if Addon._frozen_bool(generation["reasoning"]) else "none"
            )

        if "max_tokens" in generation and generation["max_tokens"] is not None:
            try:
                max_tokens = int(float(generation["max_tokens"]))
            except (TypeError, ValueError):
                max_tokens = -1
            max_tokens = max(-1, min(131072, max_tokens))
            if max_tokens == -1:
                prepared_params.pop("max_tokens", None)
            else:
                prepared_params["max_tokens"] = max_tokens

        return prepared_params, prepared_additional

    @staticmethod
    def _frozen_client(binding: Any) -> OpenAI:
        config = Addon._frozen_binding_config(binding)
        return OpenAI(
            api_key=str(config.get("api_key") or "").strip(),
            base_url=str(config.get("base_url") or "").strip(),
        )

    @staticmethod
    def _frozen_request_binding(request: Any) -> Any:
        context = getattr(request, "context", None)
        binding = getattr(context, "_binding", None)
        if binding is None:
            raise RuntimeError("Ollama frozen execution requires a captured provider binding.")
        return binding

    def _complete_frozen_chat(self, request: Any, *, timeout=None, cancel_token=None) -> str:
        """Complete with the private binding captured for this accepted turn."""
        del timeout, cancel_token
        binding = Addon._frozen_request_binding(request)
        client = Addon._frozen_client(binding)
        response = client.chat.completions.create(
            **self._request_kwargs(
                request.params_copy(),
                request.additional_params_copy(),
                stream=False,
            )
        )
        return _extract_text(response)

    def _stream_frozen_chat(self, request: Any, *, timeout=None, cancel_token=None):
        """Stream with the private binding captured for this accepted turn."""
        del timeout, cancel_token
        binding = Addon._frozen_request_binding(request)
        params = request.params_copy()
        additional_params = request.additional_params_copy()

        def _iter_stream():
            client = Addon._frozen_client(binding)
            stream = client.chat.completions.create(
                **self._request_kwargs(
                    params,
                    additional_params,
                    stream=True,
                )
            )
            yield from _stream_text(stream)

        return _iter_stream()

    @staticmethod
    def _frozen_model_capabilities(binding: Any):
        """Keep strict Relay unavailable until Ollama parity can be proven exactly.

        Ollama's OpenAI-compatible endpoint does not expose an exact tokenizer or
        prompt-template identity for the final request. A native ``/api/show``
        context value alone is therefore insufficient for strict Relay capacity
        proof, so this adapter deliberately returns no strict capability data.
        """
        del binding
        return None

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

    def _is_ollama_offline_error(self, exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, ConnectionError, socket.timeout)):
            return True
        if isinstance(exc, URLError):
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, ConnectionError, socket.timeout, OSError)):
                return True
            text = str(reason or exc or "").lower()
        else:
            text = str(exc or "").lower()
        return any(
            token in text
            for token in (
                "timed out",
                "connection refused",
                "actively refused",
                "no connection could be made",
                "failed to establish a new connection",
            )
        )

    def _model_capabilities(self, model_name: str) -> set[str]:
        model = str(model_name or "").strip()
        if not model:
            return set()
        payload = self._native_json_request("api/show", {"model": model}, timeout=5.0)
        capabilities = payload.get("capabilities") if isinstance(payload, dict) else None
        if not isinstance(capabilities, list):
            return set()
        return {
            str(item or "").strip().lower()
            for item in capabilities
            if str(item or "").strip()
        }

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
            if self._is_ollama_offline_error(exc):
                return 0
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
            catalog: list[Any] = []
            for model_id in ids:
                try:
                    capabilities = self._model_capabilities(model_id)
                except Exception as exc:
                    if not quiet:
                        print(f"Error fetching Ollama model capabilities for {model_id}: {exc}")
                    catalog.append(model_id)
                    continue
                supports_thinking = "thinking" in capabilities
                catalog.append(
                    {
                        "id": model_id,
                        "supports_images": "vision" in capabilities,
                        "supports_reasoning": supports_thinking,
                        "supports_reasoning_toggle": supports_thinking,
                        "capabilities": sorted(capabilities),
                        "source": "ollama_show",
                    }
                )
            return catalog
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

        def _iter_stream():
            client = self._client()
            stream = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=True))
            yield from _stream_text(stream)

        return _iter_stream()
