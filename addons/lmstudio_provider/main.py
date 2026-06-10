from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
from typing import Any, Iterable
from urllib.request import Request, urlopen

from openai import OpenAI

from core.addons.base import BaseAddon
from core import lmstudio_runtime


PROVIDER_ID = "lmstudio"
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
_NATIVE_REASONING_VALUES = {"off", "low", "medium", "high", "on"}
_THINK_TOKEN = "<|think|>"
_CHANNEL_START = "<|channel>"
_CHANNEL_END = "<channel|>"
_PROMPT_TOKEN_REASONING_FRAGMENTS = ("gemma-4",)


def _ui_yield_seconds() -> float:
    try:
        return max(0.0, min(0.03, float(os.environ.get("NC_LMSTUDIO_UI_YIELD_SECONDS", "0.002") or "0.002")))
    except Exception:
        return 0.002


def _yield_ui():
    delay = _ui_yield_seconds()
    if delay <= 0:
        time.sleep(0)
    else:
        time.sleep(delay)


def _worker_timeout_seconds() -> float:
    try:
        return max(30.0, min(3600.0, float(os.environ.get("NC_LMSTUDIO_WORKER_TIMEOUT_SECONDS", "900") or "900")))
    except Exception:
        return 900.0


def _strip_channel_blocks(text: Any) -> str:
    value = str(text or "")
    if _CHANNEL_START not in value:
        return value.strip()
    parts: list[str] = []
    position = 0
    while position < len(value):
        start = value.find(_CHANNEL_START, position)
        if start < 0:
            parts.append(value[position:])
            break
        parts.append(value[position:start])
        end = value.find(_CHANNEL_END, start + len(_CHANNEL_START))
        if end < 0:
            break
        position = end + len(_CHANNEL_END)
    return "".join(parts).strip()


def _filter_channel_blocks_stream(chunks: Iterable[str]):
    buffer = ""
    in_channel = False
    keep = max(len(_CHANNEL_START), len(_CHANNEL_END)) - 1

    for chunk in chunks:
        if not chunk:
            continue
        buffer += str(chunk)
        while buffer:
            if in_channel:
                end = buffer.find(_CHANNEL_END)
                if end < 0:
                    buffer = buffer[-keep:]
                    break
                buffer = buffer[end + len(_CHANNEL_END):]
                in_channel = False
                continue

            start = buffer.find(_CHANNEL_START)
            if start >= 0:
                if start:
                    yield buffer[:start]
                buffer = buffer[start + len(_CHANNEL_START):]
                in_channel = True
                continue

            if len(buffer) <= keep:
                break
            yield buffer[:-keep]
            buffer = buffer[-keep:]
            break

    if buffer and not in_channel:
        yield buffer


def _extract_text(response: Any) -> str:
    if isinstance(response, str):
        return _strip_channel_blocks(response)
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
        return _strip_channel_blocks("".join(parts))
    return _strip_channel_blocks(content)


def _raw_stream_text(stream: Iterable[Any]):
    for event in stream:
        _yield_ui()
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


def _stream_text(stream: Iterable[Any]):
    yield from _filter_channel_blocks_stream(_raw_stream_text(stream))


def _native_chat_delta_stream(response: Iterable[bytes]):
    for raw_line in response:
        _yield_ui()
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        raw_payload = line[5:].strip()
        if not raw_payload:
            continue
        try:
            payload = json.loads(raw_payload)
        except Exception:
            continue
        event_type = str(payload.get("type") or "").strip()
        if event_type == "message.delta" and payload.get("content"):
            yield str(payload.get("content"))
        elif event_type == "error":
            message = str(payload.get("message") or payload.get("error") or "LM Studio native chat error")
            raise RuntimeError(message)


def _string_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return str(content or "").strip()
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(part.strip() for part in parts if part and part.strip()).strip()


def _image_data_urls(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    urls: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").strip().lower() != "image_url":
            continue
        image_url = item.get("image_url")
        if isinstance(image_url, dict):
            url = str(image_url.get("url") or "").strip()
        else:
            url = str(image_url or "").strip()
        if url:
            urls.append(url)
    return urls


def _native_chat_text(payload: Any) -> str:
    if isinstance(payload, str):
        return _strip_channel_blocks(payload)
    if not isinstance(payload, dict):
        return ""
    output = payload.get("output")
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "message":
                parts.append(str(item.get("content") or ""))
        return _strip_channel_blocks("".join(parts))
    return _strip_channel_blocks(payload.get("content") or payload.get("text") or "")


def _model_uses_prompt_token_reasoning(model_id: str | None) -> bool:
    value = str(model_id or "").strip().lower()
    return bool(value) and any(fragment in value for fragment in _PROMPT_TOKEN_REASONING_FRAGMENTS)


def _apply_think_token(system_prompt: str, reasoning: str | None) -> str:
    prompt = str(system_prompt or "").lstrip()
    while prompt.startswith(_THINK_TOKEN):
        prompt = prompt[len(_THINK_TOKEN):].lstrip()
    if str(reasoning or "").strip().lower() in {"on", "low", "medium", "high"}:
        return f"{_THINK_TOKEN}\n{prompt}".strip()
    return prompt


def _without_reasoning(additional_params: dict[str, Any] | None) -> dict[str, Any]:
    cleaned = dict(additional_params or {})
    cleaned.pop("reasoning", None)
    return cleaned


def _is_native_reasoning_unsupported_error(exc: urllib.error.HTTPError) -> bool:
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace"))
    except Exception:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return False
    message = str(error.get("message") or "").lower()
    param = str(error.get("param") or "").strip().lower()
    return param == "reasoning" and "does not expose reasoning configuration" in message


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._native_reasoning_control_by_model: dict[str, str] = {}
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
                    {
                        "id": "reasoning",
                        "label": "Enable Thinking",
                        "kind": "bool",
                        "default": True,
                        "request_location": "additional_params",
                        "request_key": "reasoning",
                        "true_value": "on",
                        "false_value": "off",
                        "requires_model_support": "reasoning_toggle",
                        "description": "Shown when LM Studio reports public reasoning options with both off and on support.",
                    },
                ],
                "hint": "Uses LM Studio's local OpenAI-compatible endpoint. In LM Studio, open Developer -> Local Server and make sure Status is Running.",
                "supports_local_runtime": True,
            },
        )
        context.logger.info("LM Studio chat provider addon initialized.")
        return None

    def _responsiveness_guard(self):
        return lmstudio_runtime.local_inference_responsiveness_guard(logger=print)

    def _worker_enabled(self) -> bool:
        value = str(os.environ.get("NC_LMSTUDIO_HELPER_PROCESS", "1") or "1").strip().lower()
        return value not in {"0", "false", "no", "off"}

    def _worker_path(self) -> Path:
        return Path(__file__).resolve().with_name("worker.py")

    def _worker_creation_flags(self) -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _openai_chat_url(self) -> str:
        return f"{self._base_url().rstrip('/')}/chat/completions"

    def _native_chat_url(self) -> str:
        return f"{self._native_api_base_url()}/api/v1/chat"

    def _worker_request_config(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None, *, emit_chunks: bool = False) -> dict[str, Any]:
        if self._should_use_native_chat(params, additional_params):
            payload = self._native_chat_payload(params, additional_params, stream=True)
            fallback_payload = None
            if "reasoning" in dict(additional_params or {}):
                control = "prompt_token" if _model_uses_prompt_token_reasoning((params or {}).get("model")) else ""
                retry_params = additional_params if control else _without_reasoning(additional_params)
                fallback_payload = self._native_chat_payload(
                    params,
                    retry_params,
                    stream=True,
                    reasoning_control=control or None,
                )
            return {
                "url": self._native_chat_url(),
                "api_key": self._api_key(),
                "native": True,
                "payload": payload,
                "fallback_payload": fallback_payload,
                "emit_chunks": bool(emit_chunks),
            }
        force_non_stream = bool(isinstance(params, dict) and params.get("response_format") is not None)
        payload = self._request_kwargs(params, additional_params, stream=not force_non_stream)
        return {
            "url": self._openai_chat_url(),
            "api_key": self._api_key(),
            "native": False,
            "payload": payload,
            "emit_chunks": bool(emit_chunks) and not force_non_stream,
            "force_non_stream": force_non_stream,
        }

    def _start_worker(self) -> subprocess.Popen:
        worker_path = self._worker_path()
        if not worker_path.exists():
            raise RuntimeError(f"LM Studio helper process is missing: {worker_path}")
        return subprocess.Popen(
            [sys.executable, "-u", str(worker_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=self._worker_creation_flags(),
        )

    def _send_worker_config(self, process: subprocess.Popen, config: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("LM Studio helper process did not expose stdin.")
        process.stdin.write(json.dumps(dict(config or {}), ensure_ascii=False))
        process.stdin.close()

    def _complete_chat_via_worker(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        process = self._start_worker()
        config_text = json.dumps(
            self._worker_request_config(params, additional_params, emit_chunks=False),
            ensure_ascii=False,
        )
        try:
            stdout, stderr = process.communicate(input=config_text, timeout=_worker_timeout_seconds())
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=5)
            raise RuntimeError("LM Studio helper process timed out.")
        payload = self._last_worker_payload(stdout)
        if payload.get("ok"):
            return str(payload.get("text") or "").strip()
        error = str(payload.get("error") or stderr or "LM Studio helper process failed.").strip()
        raise RuntimeError(error)

    def _stream_chat_via_worker(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        process = self._start_worker()
        self._send_worker_config(process, self._worker_request_config(params, additional_params, emit_chunks=True))
        final_payload: dict[str, Any] = {}
        return_code = None
        try:
            if process.stdout is None:
                raise RuntimeError("LM Studio helper process did not expose stdout.")
            for line in process.stdout:
                payload = self._parse_worker_line(line)
                if not payload:
                    continue
                if "chunk" in payload:
                    chunk = str(payload.get("chunk") or "")
                    if chunk:
                        yield chunk
                    continue
                final_payload = payload
            return_code = process.wait(timeout=5)
        finally:
            if process.poll() is None:
                process.kill()
        stderr = ""
        try:
            stderr = process.stderr.read() if process.stderr is not None else ""
        except Exception:
            stderr = ""
        if final_payload.get("ok"):
            return
        error = str(final_payload.get("error") or stderr or f"LM Studio helper process exited with code {return_code}.").strip()
        raise RuntimeError(error)

    def _parse_worker_line(self, line: str) -> dict[str, Any]:
        try:
            payload = json.loads(str(line or "").strip())
            return dict(payload or {}) if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _last_worker_payload(self, stdout: str) -> dict[str, Any]:
        last_payload: dict[str, Any] = {}
        for line in str(stdout or "").splitlines():
            payload = self._parse_worker_line(line)
            if payload:
                last_payload = payload
        return last_payload

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

    def _should_use_native_chat(self, params: dict[str, Any] | None, additional_params: dict[str, Any] | None = None) -> bool:
        reasoning = str((additional_params or {}).get("reasoning") or "").strip().lower()
        if reasoning not in _NATIVE_REASONING_VALUES:
            return False
        # LM Studio's native chat endpoint supports reasoning, but the existing
        # OpenAI-compatible endpoint is still used for JSON response_format calls.
        if isinstance(params, dict) and params.get("response_format") is not None:
            return False
        return True

    def _native_reasoning_control_for_model(self, model_id: str | None) -> str:
        clean_model_id = str(model_id or "").strip()
        cached = str(getattr(self, "_native_reasoning_control_by_model", {}).get(clean_model_id) or "").strip()
        if cached:
            return cached
        return "prompt_token" if _model_uses_prompt_token_reasoning(clean_model_id) else "native"

    def _native_chat_payload(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
        *,
        stream: bool = False,
        reasoning_control: str | None = None,
    ) -> dict[str, Any]:
        source = dict(params or {})
        extras = dict(additional_params or {})
        messages = list(source.get("messages") or [])
        model_id = str(source.get("model") or "").strip()
        reasoning = str(extras.get("reasoning") or "").strip().lower()
        reasoning_control = str(reasoning_control or self._native_reasoning_control_for_model(model_id) or "native").strip().lower()
        system_parts: list[str] = []
        transcript_parts: list[str] = []
        input_items: list[dict[str, str]] = []

        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user").strip().lower() or "user"
            text = _string_content(message.get("content"))
            if role == "system":
                if text:
                    system_parts.append(text)
                continue
            label = "Assistant" if role == "assistant" else "User"
            if text:
                transcript_parts.append(f"{label}: {text}")
            for url in _image_data_urls(message.get("content")):
                if text:
                    transcript_parts.append(f"{label}: [attached image]")
                input_items.append({"type": "image", "data_url": url})

        payload: dict[str, Any] = {
            "model": model_id,
            "store": False,
            "stream": bool(stream),
        }
        system_prompt = "\n\n".join(part for part in system_parts if part)
        if reasoning and reasoning_control == "prompt_token":
            system_prompt = _apply_think_token(system_prompt, reasoning)
        if system_prompt:
            payload["system_prompt"] = system_prompt

        transcript = "\n".join(part for part in transcript_parts if part).strip()
        if input_items:
            if transcript:
                input_items.insert(0, {"type": "text", "content": transcript})
            payload["input"] = input_items
        else:
            payload["input"] = transcript

        for key in ("temperature", "top_p"):
            if source.get(key) is not None:
                payload[key] = source.get(key)
        max_tokens = source.get("max_tokens", source.get("max_completion_tokens"))
        try:
            max_tokens = int(max_tokens)
        except Exception:
            max_tokens = None
        if max_tokens is not None and max_tokens > 0:
            payload["max_output_tokens"] = max_tokens
        for key in ("top_k", "repeat_penalty", "min_p"):
            if extras.get(key) is not None:
                payload[key] = extras.get(key)
        if reasoning and reasoning_control != "prompt_token":
            payload["reasoning"] = reasoning
        return payload

    def _native_chat_request(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
        *,
        stream: bool = False,
        reasoning_control: str | None = None,
    ):
        payload = self._native_chat_payload(params, additional_params, stream=stream, reasoning_control=reasoning_control)
        request = Request(
            f"{self._native_api_base_url()}/api/v1/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        return urlopen(request, timeout=300.0)

    def _complete_native_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        parts: list[str] = []
        try:
            for chunk in self._stream_native_chat(params, additional_params):
                if chunk:
                    parts.append(str(chunk))
            text = _strip_channel_blocks("".join(parts))
            if text:
                return text
        except Exception:
            if parts:
                return _strip_channel_blocks("".join(parts))
        try:
            with self._native_chat_request(params, additional_params, stream=False) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if "reasoning" not in dict(additional_params or {}) or not _is_native_reasoning_unsupported_error(exc):
                raise
            control = "prompt_token" if _model_uses_prompt_token_reasoning((params or {}).get("model")) else ""
            retry_params = additional_params if control else _without_reasoning(additional_params)
            with self._native_chat_request(params, retry_params, stream=False, reasoning_control=control or None) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        return _native_chat_text(payload)

    def _stream_native_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        try:
            response = self._native_chat_request(params, additional_params, stream=True)
        except urllib.error.HTTPError as exc:
            if "reasoning" not in dict(additional_params or {}) or not _is_native_reasoning_unsupported_error(exc):
                raise
            control = "prompt_token" if _model_uses_prompt_token_reasoning((params or {}).get("model")) else ""
            retry_params = additional_params if control else _without_reasoning(additional_params)
            response = self._native_chat_request(params, retry_params, stream=True, reasoning_control=control or None)
        with response:
            yield from _filter_channel_blocks_stream(_native_chat_delta_stream(response))

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
        reasoning_control_by_model = {}
        for model in models:
            if not isinstance(model, dict):
                continue
            if str(model.get("type") or "").strip().lower() not in {"", "llm"}:
                continue
            model_id = str(model.get("key") or model.get("id") or "").strip()
            if not model_id:
                continue
            capabilities = model.get("capabilities") if isinstance(model.get("capabilities"), dict) else {}
            reasoning = capabilities.get("reasoning") if isinstance(capabilities.get("reasoning"), dict) else {}
            reasoning_options = {
                str(option or "").strip().lower()
                for option in list(reasoning.get("allowed_options") or [])
                if str(option or "").strip()
            }
            supports_native_reasoning_toggle = bool({"off", "on"}.issubset(reasoning_options))
            supports_prompt_token_reasoning = bool(
                not supports_native_reasoning_toggle and _model_uses_prompt_token_reasoning(model_id)
            )
            reasoning_control = "native" if supports_native_reasoning_toggle else ("prompt_token" if supports_prompt_token_reasoning else "")
            if reasoning_control:
                reasoning_control_by_model[model_id] = reasoning_control
            catalog.append(
                {
                    "id": model_id,
                    "supports_images": bool(capabilities.get("vision", False)),
                    "supports_reasoning": bool(reasoning or supports_prompt_token_reasoning),
                    "supports_reasoning_toggle": bool(supports_native_reasoning_toggle or supports_prompt_token_reasoning),
                    "reasoning_options": sorted(reasoning_options),
                    "reasoning_control": reasoning_control,
                    "source": "lmstudio_native",
                }
            )
        self._native_reasoning_control_by_model = reasoning_control_by_model
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
            return {
                "ok": False,
                "detail": (
                    f"{exc}. In LM Studio, open Developer -> Local Server and make sure Status is Running."
                ),
            }

    def _complete_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        with self._responsiveness_guard():
            if self._worker_enabled():
                return self._complete_chat_via_worker(params, additional_params)
            if self._should_use_native_chat(params, additional_params):
                return self._complete_native_chat(params, additional_params)
            parts: list[str] = []
            if not (isinstance(params, dict) and params.get("response_format") is not None):
                try:
                    client = self._client()
                    stream = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=True))
                    for chunk in _stream_text(stream):
                        if chunk:
                            parts.append(str(chunk))
                    text = _strip_channel_blocks("".join(parts))
                    if text:
                        return text
                except Exception:
                    if parts:
                        return _strip_channel_blocks("".join(parts))
            client = self._client()
            response = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=False))
            return _extract_text(response)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        def guarded_stream():
            with self._responsiveness_guard():
                if self._worker_enabled():
                    yield from self._stream_chat_via_worker(params, additional_params)
                    return
                if self._should_use_native_chat(params, additional_params):
                    yield from self._stream_native_chat(params, additional_params)
                    return
                client = self._client()
                stream = client.chat.completions.create(**self._request_kwargs(params, additional_params, stream=True))
                yield from _stream_text(stream)

        return guarded_stream()
