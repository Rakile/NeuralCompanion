from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Iterable

from core.addons.base import BaseAddon


PROVIDER_ID = "claude"
DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 1024
DEFAULT_REQUEST_TIMEOUT = 120.0

FALLBACK_MODELS = [
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4-6",
]


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._chat_service = context.get_service("qt.chat_providers")
        if self._chat_service is None:
            context.logger.warning("Claude provider addon could not find qt.chat_providers service.")
            return None

        self._chat_service.register_provider(
            provider_id=PROVIDER_ID,
            label="Claude",
            description="Hosted Anthropic Claude models through the Messages API.",
            order=400,
            model_list_handler=self._list_models,
            completion_handler=self._complete_chat,
            stream_handler=self._stream_chat,
            frozen_execution_version=1,
            frozen_prepare_handler=self._prepare_frozen_request,
            frozen_completion_handler=self._complete_frozen_chat,
            frozen_stream_handler=self._stream_frozen_chat,
            connection_check_handler=self._check_connection,
            api_key_getter=self._api_key,
            base_url_getter=self._base_url,
            frozen_private_config_getter=self._frozen_private_config,
            frozen_public_config_fields=("provider_is_remote",),
            metadata={
                "config_fields": [
                    {
                        "id": "api_key",
                        "label": "API Key",
                        "env": ["NC_CHAT_CLAUDE_API_KEY", "ANTHROPIC_API_KEY"],
                    },
                    {
                        "id": "base_url",
                        "label": "Base URL",
                        "default": DEFAULT_BASE_URL,
                        "env": ["NC_CHAT_CLAUDE_BASE_URL"],
                    },
                    {
                        "id": "anthropic_version",
                        "label": "API Version",
                        "default": DEFAULT_ANTHROPIC_VERSION,
                        "env": ["NC_CHAT_CLAUDE_API_VERSION"],
                    },
                ],
                "generation_fields": [
                    {
                        "id": "max_tokens",
                        "label": "Max Tokens",
                        "kind": "int",
                        "min": 1,
                        "max": 8192,
                        "step": 1,
                        "default": DEFAULT_MAX_TOKENS,
                        "request_location": "params",
                        "description": "Maximum tokens in one Claude reply. Claude requires this value.",
                    },
                    {
                        "id": "temperature",
                        "label": "Temperature",
                        "kind": "float",
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.01,
                        "decimals": 2,
                        "default": 0.7,
                        "request_location": "params",
                        "description": "Claude models reject requests that set both Temperature and Top P, so this addon exposes Temperature only by default.",
                    },
                    {
                        "id": "top_k",
                        "label": "Top K (0 = off)",
                        "kind": "int",
                        "min": 0,
                        "max": 500,
                        "step": 1,
                        "default": 0,
                        "omit_if": [0, "0"],
                        "request_location": "params",
                    },
                ],
                "hint": "Hosted Anthropic Claude provider. API key is required. Max Tokens is required by Claude.",
                "supports_hosted_runtime": True,
                "supports_streaming": True,
                "supports_images": True,
            },
        )
        context.logger.info("Claude chat provider addon initialized.")
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

    def _env_value(self, *names: str, fallback: str = "") -> str:
        for name in names:
            value = str(os.environ.get(name, "") or "").strip()
            if value:
                return value
        return str(fallback or "").strip()

    def _api_key(self) -> str:
        return self._setting("api_key") or self._env_value("NC_CHAT_CLAUDE_API_KEY", "ANTHROPIC_API_KEY")

    def _base_url(self) -> str:
        return self._setting("base_url") or self._env_value("NC_CHAT_CLAUDE_BASE_URL", fallback=DEFAULT_BASE_URL)

    def _api_version(self) -> str:
        return self._setting("anthropic_version") or self._env_value(
            "NC_CHAT_CLAUDE_API_VERSION",
            fallback=DEFAULT_ANTHROPIC_VERSION,
        )

    def _frozen_private_config(self) -> dict[str, Any]:
        return {
            "anthropic_version": self._api_version(),
            "provider_is_remote": True,
        }

    def _max_tokens(self, params: dict[str, Any]) -> int:
        raw_value = (
            params.get("max_tokens")
            or params.get("max_completion_tokens")
            or self._setting("max_tokens")
            or DEFAULT_MAX_TOKENS
        )
        try:
            value = int(raw_value)
        except Exception:
            value = DEFAULT_MAX_TOKENS
        return max(1, value)

    def _url(self, path: str) -> str:
        base = str(self._base_url() or DEFAULT_BASE_URL).strip().rstrip("/")
        suffix = str(path or "").strip()
        if not suffix.startswith("/"):
            suffix = "/" + suffix
        if base.endswith("/v1") and suffix.startswith("/v1/"):
            suffix = suffix[3:]
        return base + suffix

    def _headers(self, *, accept: str = "application/json") -> dict[str, str]:
        headers = {
            "Accept": accept,
            "Content-Type": "application/json",
            "anthropic-version": self._api_version(),
        }
        api_key = self._api_key()
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    def _request_json(self, method: str, url: str, payload: dict[str, Any] | None = None, *, timeout: float = 60.0):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(str(url), data=data, headers=self._headers(), method=str(method or "GET").upper())
        try:
            with urllib.request.urlopen(request, timeout=float(timeout)) as response:
                raw_payload = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
                return json.loads(raw_payload.decode(encoding, errors="replace"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._format_http_error(exc)) from exc

    def _format_http_error(self, exc: urllib.error.HTTPError) -> str:
        try:
            raw_payload = exc.read()
            payload = json.loads(raw_payload.decode("utf-8", errors="replace"))
            if isinstance(payload, dict):
                error_payload = payload.get("error")
                if isinstance(error_payload, dict):
                    message = error_payload.get("message") or error_payload.get("type")
                    if message:
                        return f"Claude API HTTP {exc.code}: {message}"
                if payload.get("message"):
                    return f"Claude API HTTP {exc.code}: {payload.get('message')}"
        except Exception:
            pass
        return f"Claude API HTTP {exc.code}: {getattr(exc, 'reason', '')}"

    def _fallback_model_entries(self) -> list[dict[str, Any]]:
        return [
            {
                "id": model_id,
                "supports_images": True,
                "source": "claude_fallback",
            }
            for model_id in FALLBACK_MODELS
        ]

    def _list_models(self, quiet: bool = False) -> list[Any]:
        if not self._api_key():
            return self._fallback_model_entries()
        try:
            payload = self._request_json("GET", self._url("/v1/models"), timeout=15.0)
            entries = list(payload.get("data") or []) if isinstance(payload, dict) else []
            models = []
            for item in entries:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id") or "").strip()
                if not model_id:
                    continue
                models.append(
                    {
                        "id": model_id,
                        "label": str(item.get("display_name") or model_id).strip(),
                        "supports_images": True,
                        "source": "anthropic_models",
                    }
                )
            return models or self._fallback_model_entries()
        except Exception as exc:
            if not quiet:
                print(f"Error fetching Claude models: {exc}")
            return self._fallback_model_entries()

    def _check_connection(self) -> dict[str, Any]:
        if not self._api_key():
            return {"ok": False, "detail": "Claude API key is required."}
        try:
            payload = self._request_json("GET", self._url("/v1/models"), timeout=15.0)
            entries = list(payload.get("data") or []) if isinstance(payload, dict) else []
            model_count = len(entries)
            return {
                "ok": True,
                "detail": f"Connected to Claude ({model_count} model(s) available)",
                "model_count": model_count,
            }
        except Exception as exc:
            return {"ok": False, "detail": str(exc)}

    def _complete_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        payload = self._build_messages_payload(params)
        response = self._request_json("POST", self._url("/v1/messages"), payload, timeout=120.0)
        return self._extract_response_text(response)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> Iterable[str]:
        payload = self._build_messages_payload(params)
        payload["stream"] = True
        data = json.dumps(payload).encode("utf-8")
        headers = self._headers(accept="text/event-stream")
        request = urllib.request.Request(self._url("/v1/messages"), data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120.0) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    event_payload = line[5:].strip()
                    if not event_payload or event_payload == "[DONE]":
                        continue
                    event = json.loads(event_payload)
                    event_type = str(event.get("type") or "").strip()
                    if event_type == "error":
                        error_payload = event.get("error") or {}
                        if isinstance(error_payload, dict):
                            raise RuntimeError(str(error_payload.get("message") or error_payload.get("type") or "Claude stream error"))
                        raise RuntimeError("Claude stream error")
                    if event_type != "content_block_delta":
                        continue
                    delta = event.get("delta") or {}
                    if isinstance(delta, dict) and delta.get("type") == "text_delta":
                        text = str(delta.get("text") or "")
                        if text:
                            yield text
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._format_http_error(exc)) from exc

    def _prepare_frozen_request(self, binding, params: dict[str, Any], additional_params: dict[str, Any]):
        del additional_params
        provider_config = binding._provider_config_copy()
        generation_fields = binding._generation_fields_copy()
        effective_params = dict(params)
        effective_params["model"] = binding.model_name or effective_params.get("model")

        if "temperature" in generation_fields:
            effective_params.pop("top_p", None)
            temperature = generation_fields.get("temperature")
            if temperature is None:
                effective_params.pop("temperature", None)
            else:
                effective_params["temperature"] = temperature
        elif "top_p" in generation_fields:
            effective_params.pop("temperature", None)
            top_p = generation_fields.get("top_p")
            if top_p is None:
                effective_params.pop("top_p", None)
            else:
                effective_params["top_p"] = top_p
        if "top_k" in generation_fields:
            effective_params.pop("top_k", None)
            top_k = generation_fields.get("top_k")
            if top_k not in {None, "", 0, "0"}:
                effective_params["top_k"] = top_k

        resolved_max_tokens = self._resolved_frozen_max_tokens(
            effective_params,
            generation_fields,
            provider_config,
        )
        payload = self._build_messages_payload(
            effective_params,
            resolved_max_tokens=resolved_max_tokens,
            resolved_model=binding.model_name,
        )
        return payload, {"request_timeout": DEFAULT_REQUEST_TIMEOUT}

    def _complete_frozen_chat(self, request, *, timeout=None, cancel_token=None) -> str:
        del timeout, cancel_token
        provider_config = self._frozen_provider_config(request)
        payload = request.params_copy()
        response = self._request_frozen_json(
            "POST",
            self._url_from_base(provider_config.get("base_url"), "/v1/messages"),
            self._headers_from_config(provider_config),
            payload,
            timeout=self._frozen_request_timeout(request),
        )
        return self._extract_response_text(response)

    def _stream_frozen_chat(self, request, *, timeout=None, cancel_token=None) -> Iterable[str]:
        del timeout, cancel_token
        provider_config = self._frozen_provider_config(request)
        payload = request.params_copy()
        payload["stream"] = True
        data = json.dumps(payload).encode("utf-8")
        headers = self._headers_from_config(provider_config, accept="text/event-stream")
        url = self._url_from_base(provider_config.get("base_url"), "/v1/messages")
        transport_request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(
                transport_request,
                timeout=self._frozen_request_timeout(request),
            ) as response:
                yield from self._iter_stream_text(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._format_http_error(exc)) from exc

    def _frozen_provider_config(self, request) -> dict[str, Any]:
        context = getattr(request, "context", None)
        binding = getattr(context, "_binding", None)
        if binding is None or binding.provider_name != PROVIDER_ID:
            raise RuntimeError("Claude frozen request binding is unavailable.")
        return binding._provider_config_copy()

    def _resolved_frozen_max_tokens(
        self,
        params: dict[str, Any],
        generation_fields: dict[str, Any],
        provider_config: dict[str, Any],
    ) -> int:
        raw_value = (
            params.get("max_tokens")
            or params.get("max_completion_tokens")
            or provider_config.get("max_tokens")
            or generation_fields.get("max_tokens")
            or generation_fields.get("max_completion_tokens")
            or DEFAULT_MAX_TOKENS
        )
        try:
            value = int(raw_value)
        except Exception:
            value = DEFAULT_MAX_TOKENS
        return max(1, value)

    def _frozen_request_timeout(self, request) -> float:
        try:
            return float(request.additional_params.get("request_timeout", DEFAULT_REQUEST_TIMEOUT))
        except Exception:
            return DEFAULT_REQUEST_TIMEOUT

    def _url_from_base(self, base_url: Any, path: str) -> str:
        base = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        suffix = str(path or "").strip()
        if not suffix.startswith("/"):
            suffix = "/" + suffix
        if base.endswith("/v1") and suffix.startswith("/v1/"):
            suffix = suffix[3:]
        return base + suffix

    def _headers_from_config(
        self,
        provider_config: dict[str, Any],
        *,
        accept: str = "application/json",
    ) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "Content-Type": "application/json",
            "anthropic-version": str(
                provider_config.get("anthropic_version") or DEFAULT_ANTHROPIC_VERSION
            ).strip(),
        }
        api_key = str(provider_config.get("api_key") or "").strip()
        if api_key:
            headers["x-api-key"] = api_key
        return headers

    def _request_frozen_json(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any] | None = None,
        *,
        timeout: float,
    ):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            str(url),
            data=data,
            headers=dict(headers),
            method=str(method or "GET").upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=float(timeout)) as response:
                raw_payload = response.read()
                encoding = response.headers.get_content_charset() or "utf-8"
                return json.loads(raw_payload.decode(encoding, errors="replace"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(self._format_http_error(exc)) from exc

    def _iter_stream_text(self, response) -> Iterable[str]:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or not line.startswith("data:"):
                continue
            event_payload = line[5:].strip()
            if not event_payload or event_payload == "[DONE]":
                continue
            event = json.loads(event_payload)
            event_type = str(event.get("type") or "").strip()
            if event_type == "error":
                error_payload = event.get("error") or {}
                if isinstance(error_payload, dict):
                    raise RuntimeError(
                        str(
                            error_payload.get("message")
                            or error_payload.get("type")
                            or "Claude stream error"
                        )
                    )
                raise RuntimeError("Claude stream error")
            if event_type != "content_block_delta":
                continue
            delta = event.get("delta") or {}
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                text = str(delta.get("text") or "")
                if text:
                    yield text

    def _build_messages_payload(
        self,
        params: dict[str, Any],
        *,
        resolved_max_tokens: int | None = None,
        resolved_model: str | None = None,
    ) -> dict[str, Any]:
        raw_messages = list(params.get("messages") or [])
        system_prompt, messages = self._convert_messages(raw_messages)
        model = str(resolved_model or params.get("model") or "").strip() or FALLBACK_MODELS[0]
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": (
                self._max_tokens(params)
                if resolved_max_tokens is None
                else max(1, int(resolved_max_tokens))
            ),
            "messages": messages or [{"role": "user", "content": "Continue."}],
        }
        if system_prompt:
            payload["system"] = system_prompt
        if params.get("temperature") is not None:
            payload["temperature"] = params.get("temperature")
        elif params.get("top_p") is not None:
            payload["top_p"] = params.get("top_p")
        if params.get("top_k") is not None:
            payload["top_k"] = params.get("top_k")
        stop_value = params.get("stop")
        if isinstance(stop_value, str) and stop_value:
            payload["stop_sequences"] = [stop_value]
        elif isinstance(stop_value, (list, tuple)):
            stop_sequences = [str(item) for item in stop_value if str(item or "")]
            if stop_sequences:
                payload["stop_sequences"] = stop_sequences
        return payload

    def _convert_messages(self, raw_messages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        messages: list[dict[str, Any]] = []
        for raw_message in raw_messages:
            if not isinstance(raw_message, dict):
                continue
            role = str(raw_message.get("role") or "user").strip().lower()
            content = raw_message.get("content")
            if role == "system":
                text = self._content_to_text(content).strip()
                if text:
                    system_parts.append(text)
                continue
            anthropic_role = "assistant" if role == "assistant" else "user"
            anthropic_content = self._content_to_anthropic(content)
            if self._content_is_empty(anthropic_content):
                continue
            self._append_turn(messages, anthropic_role, anthropic_content)
        return "\n\n".join(system_parts).strip(), messages

    def _append_turn(self, messages: list[dict[str, Any]], role: str, content: str | list[dict[str, Any]]) -> None:
        if messages and messages[-1].get("role") == role:
            messages[-1]["content"] = self._merge_content(messages[-1].get("content"), content)
            return
        messages.append({"role": role, "content": content})

    def _merge_content(self, left: Any, right: Any) -> str | list[dict[str, Any]]:
        if isinstance(left, str) and isinstance(right, str):
            return "\n\n".join([part for part in (left, right) if part])
        merged = self._content_as_blocks(left)
        merged.extend(self._content_as_blocks(right))
        return merged

    def _content_as_blocks(self, content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "text", "text": content}] if content else []
        if isinstance(content, list):
            return [dict(item) for item in content if isinstance(item, dict)]
        return []

    def _content_is_empty(self, content: Any) -> bool:
        if isinstance(content, str):
            return not bool(content.strip())
        if isinstance(content, list):
            return not bool(content)
        return True

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content or "")
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)

    def _content_to_anthropic(self, content: Any) -> str | list[dict[str, Any]]:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content or "")
        blocks: list[dict[str, Any]] = []
        for item in content:
            if isinstance(item, str):
                if item:
                    blocks.append({"type": "text", "text": item})
                continue
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type in {"text", "input_text"}:
                text = str(item.get("text") or item.get("content") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
                continue
            if item_type == "image" and isinstance(item.get("source"), dict):
                blocks.append(dict(item))
                continue
            if item_type == "image_url":
                image_url = item.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                image_block = self._image_url_to_block(str(image_url or ""))
                if image_block is not None:
                    blocks.append(image_block)
                continue
            text = item.get("text")
            if text:
                blocks.append({"type": "text", "text": str(text)})
        return blocks

    def _image_url_to_block(self, image_url: str) -> dict[str, Any] | None:
        value = str(image_url or "").strip()
        if not value.startswith("data:") or "," not in value:
            return None
        header, payload = value.split(",", 1)
        media_type = header[5:].split(";", 1)[0].strip() or "image/png"
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": payload,
            },
        }

    def _extract_response_text(self, response: Any) -> str:
        if not isinstance(response, dict):
            return ""
        parts: list[str] = []
        for block in list(response.get("content") or []):
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts).strip()
