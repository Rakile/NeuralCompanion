from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import urllib.error
from collections.abc import Mapping
from typing import Any, Iterable
from urllib.request import Request, urlopen

from openai import OpenAI

from core.addons.base import BaseAddon
from core import chat_providers, lmstudio_runtime
from addons.lmstudio_provider.responses import (
    build_responses_payload,
    decode_http_text,
    extract_response_text,
    http_error_text,
    iter_response_sse,
    response_charset,
    responses_url,
)


PROVIDER_ID = "lmstudio"
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_API_KEY = "lm-studio"
_CHANNEL_START = "<|channel>"
_CHANNEL_END = "<channel|>"
_FROZEN_REASONING_METADATA_FIELD = "_lmstudio_catalog_reasoning_metadata"
_FROZEN_COMPATIBILITY_PROTOCOL = "lmstudio-responses-reasoning-none-v1"
_COMPATIBILITY_STATE_INIT_LOCK = threading.Lock()


class _CompatibilityFlight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.error: BaseException | None = None


class _FrozenCatalogReasoningField(Mapping[str, Any]):
    """Runtime-only generation field that snapshots the selected catalog entry."""

    def __init__(self, capture) -> None:
        self._capture = capture

    def __getitem__(self, key: str) -> Any:
        if key == "id":
            return _FROZEN_REASONING_METADATA_FIELD
        if key == "default":
            return self._capture()
        raise KeyError(key)

    def __iter__(self):
        return iter(("id", "default"))

    def __len__(self) -> int:
        return 2

    def __repr__(self) -> str:
        return "<_FrozenCatalogReasoningField>"


def _ui_yield_seconds() -> float:
    try:
        return max(0.0, min(0.03, float(os.environ.get("NC_LMSTUDIO_UI_YIELD_SECONDS", "0.002") or "0.002")))
    except Exception:
        return 0.002


def _yield_ui():
    delay = _ui_yield_seconds()
    _yield_ui_for_seconds(delay)


def _yield_ui_for_seconds(delay: float) -> None:
    if delay <= 0:
        time.sleep(0)
    else:
        time.sleep(delay)


def _worker_timeout_seconds() -> float:
    try:
        return max(30.0, min(3600.0, float(os.environ.get("NC_LMSTUDIO_WORKER_TIMEOUT_SECONDS", "900") or "900")))
    except Exception:
        return 900.0


def _worker_poll_interval_seconds() -> float:
    try:
        return max(0.02, min(0.5, float(os.environ.get("NC_LMSTUDIO_WORKER_POLL_SECONDS", "0.05") or "0.05")))
    except Exception:
        return 0.05


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


def _normalize_openai_base_url(base_url: str | None) -> str:
    url = str(base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not url:
        return DEFAULT_BASE_URL
    if url.endswith("/v1"):
        return url
    if "://" not in url:
        return url
    path_start = url.find("/", url.find("://") + 3)
    if path_start < 0:
        return f"{url}/v1"
    path = url[path_start:].strip("/")
    if not path:
        return f"{url[:path_start]}/v1"
    return url


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._model_catalog_by_id: dict[str, dict[str, Any]] = {}
        self._responses_compatibility_cache: dict[tuple[str, str], bool] = {}
        self._responses_compatibility_lock = threading.Lock()
        self._responses_compatibility_flights: dict[
            tuple[str, str], _CompatibilityFlight
        ] = {}
        self._chat_service = context.get_service("qt.chat_providers")
        if self._chat_service is None:
            context.logger.warning("LM Studio provider addon could not find qt.chat_providers service.")
            return None

        provider_kwargs = {
            "provider_id": PROVIDER_ID,
            "label": "LM Studio",
            "description": "Local LM Studio models exposed through the OpenAI-compatible Responses API.",
            "order": 100,
            "client_factory": self._client,
            "model_list_handler": self._list_models,
            "completion_handler": self._complete_chat,
            "stream_handler": self._stream_chat,
            "connection_check_handler": self._check_connection,
            "api_key_getter": self._api_key,
            "base_url_getter": self._base_url,
            "metadata": {
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
                    *self._frozen_catalog_reasoning_fields(),
                ],
                "hint": "Requires LM Studio 0.4.7 or newer and its local Responses API. In LM Studio, open Developer -> Local Server and make sure Status is Running.",
                "supports_local_runtime": True,
            },
        }
        frozen_hooks = self._frozen_registration_hooks()
        register_provider = self._chat_service.register_provider
        try:
            signature = inspect.signature(register_provider)
            parameters = signature.parameters.values()
            supports_frozen_hooks = any(
                parameter.kind == inspect.Parameter.VAR_KEYWORD
                for parameter in parameters
            ) or all(name in signature.parameters for name in frozen_hooks)
        except Exception:
            supports_frozen_hooks = False
        if supports_frozen_hooks:
            provider_kwargs.update(frozen_hooks)
        else:
            context.logger.warning(
                "LM Studio frozen chat execution is unavailable because qt.chat_providers "
                "does not expose the additive frozen registration hooks."
            )

        register_provider(**provider_kwargs)
        context.logger.info("LM Studio chat provider addon initialized.")
        return None

    def _frozen_registration_hooks(self) -> dict[str, Any]:
        transport = {
            "worker_enabled": self._worker_enabled(),
            "worker_timeout": _worker_timeout_seconds(),
            "worker_poll_interval": _worker_poll_interval_seconds(),
            "ui_yield_seconds": _ui_yield_seconds(),
            "direct_timeout": 300.0,
            "worker_command": (sys.executable, "-u", str(self._worker_path())),
            "worker_creation_flags": self._worker_creation_flags(),
        }
        complete_direct = self._complete_prepared_direct
        stream_direct = self._stream_prepared_direct
        complete_worker = self._complete_prepared_worker
        stream_worker = self._stream_prepared_worker
        ensure_compatibility = self._ensure_frozen_responses_compatibility
        responsiveness_guard = lmstudio_runtime.local_inference_responsiveness_guard
        sdk_loader = lmstudio_runtime.get_sdk

        def private_config():
            base_url = self._base_url()
            return {
                "base_url": base_url,
                "provider_is_remote": not lmstudio_runtime.is_local_base_url(base_url),
            }

        def prepare(binding, params, additional_params):
            provider_config, generation_fields = self._frozen_binding_values(binding)
            base_url = _normalize_openai_base_url(
                provider_config.get("base_url") or DEFAULT_BASE_URL
            )
            api_key = str(provider_config.get("api_key") or DEFAULT_API_KEY)
            model_name = str(binding.model_name or "").strip()
            if not model_name:
                raise RuntimeError("LM Studio frozen chat requires a selected model.")

            source = dict(params or {})
            extras = dict(additional_params or {})
            output_budget_override = extras.pop(
                chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE,
                None,
            )
            source["model"] = model_name
            for key in ("temperature", "top_p"):
                if key in generation_fields:
                    source[key] = generation_fields[key]
            if output_budget_override is not None:
                source.pop("max_completion_tokens", None)
                source["max_tokens"] = output_budget_override
            else:
                for key in ("max_tokens", "max_completion_tokens"):
                    if key in generation_fields:
                        source[key] = generation_fields[key]
            for key in ("top_k", "repeat_penalty", "min_p", "reasoning"):
                if key in generation_fields:
                    extras[key] = generation_fields[key]
            if "reasoning" not in extras and "enable_thinking" in generation_fields:
                extras["reasoning"] = "on" if bool(generation_fields["enable_thinking"]) else "off"

            metadata = self._frozen_reasoning_metadata(
                provider_config,
                generation_fields,
                model_name=model_name,
            )
            payload = build_responses_payload(source, extras, metadata, stream=False)
            url = responses_url(base_url)
            fingerprint = self._frozen_compatibility_fingerprint(
                url=url,
                model=model_name,
            )
            return (
                {"lmstudio_responses_payload": payload},
                {
                    "lmstudio_transport": {
                        "compatibility_protocol": _FROZEN_COMPATIBILITY_PROTOCOL,
                        "compatibility_fingerprint": fingerprint,
                        "local_responsiveness": lmstudio_runtime.is_local_base_url(base_url),
                        "worker": bool(transport["worker_enabled"]),
                    }
                },
            )

        def complete(request, *, timeout=None, cancel_token=None):
            del timeout, cancel_token
            state = self._frozen_execution_state(request)
            with self._captured_responsiveness_guard(
                state["local_responsiveness"],
                responsiveness_guard,
            ):
                ensure_compatibility(
                    url=state["url"],
                    api_key=state["api_key"],
                    model=state["model"],
                    timeout=transport["direct_timeout"],
                )
                payload = dict(state["payload"])
                payload["stream"] = False
                if state["worker"]:
                    return complete_worker(
                        config={
                            "url": state["url"],
                            "api_key": state["api_key"],
                            "payload": payload,
                            "emit_chunks": False,
                            "stream": False,
                        },
                        timeout=transport["worker_timeout"],
                        poll_interval=transport["worker_poll_interval"],
                        ui_yield_seconds=transport["ui_yield_seconds"],
                        command=transport["worker_command"],
                        creationflags=transport["worker_creation_flags"],
                    )
                return complete_direct(
                    url=state["url"],
                    api_key=state["api_key"],
                    payload=payload,
                    timeout=transport["direct_timeout"],
                )

        def stream(request, *, timeout=None, cancel_token=None):
            del timeout, cancel_token
            state = self._frozen_execution_state(request)

            def guarded_stream():
                with self._captured_responsiveness_guard(
                    state["local_responsiveness"],
                    responsiveness_guard,
                ):
                    ensure_compatibility(
                        url=state["url"],
                        api_key=state["api_key"],
                        model=state["model"],
                        timeout=transport["direct_timeout"],
                    )
                    payload = dict(state["payload"])
                    payload["stream"] = True
                    if state["worker"]:
                        yield from stream_worker(
                            config={
                                "url": state["url"],
                                "api_key": state["api_key"],
                                "payload": payload,
                                "emit_chunks": True,
                                "stream": True,
                            },
                            timeout=transport["worker_timeout"],
                            poll_interval=transport["worker_poll_interval"],
                            ui_yield_seconds=transport["ui_yield_seconds"],
                            command=transport["worker_command"],
                            creationflags=transport["worker_creation_flags"],
                        )
                        return
                    yield from stream_direct(
                        url=state["url"],
                        api_key=state["api_key"],
                        payload=payload,
                        timeout=transport["direct_timeout"],
                    )

            return guarded_stream()

        def capabilities(binding):
            return self._strict_local_capability(binding, sdk_loader=sdk_loader)

        return {
            "frozen_execution_version": 1,
            "frozen_prepare_handler": prepare,
            "frozen_completion_handler": complete,
            "frozen_stream_handler": stream,
            "model_capabilities_handler": capabilities,
            "frozen_private_config_getter": private_config,
            "frozen_public_config_fields": ("base_url", "provider_is_remote"),
        }

    def _frozen_catalog_reasoning_fields(self) -> tuple[Mapping[str, Any], ...]:
        return (_FrozenCatalogReasoningField(self._capture_catalog_reasoning_metadata),)

    def _capture_catalog_reasoning_metadata(self) -> dict[str, Any]:
        model_key = self._setting("model_name")
        metadata = dict(
            getattr(self, "_model_catalog_by_id", {}).get(model_key) or {}
        )
        options = metadata.get("reasoning_options", ())
        if isinstance(options, str):
            options = [options]
        return {
            "model_key": model_key,
            "supports_reasoning": bool(metadata.get("supports_reasoning", False)),
            "supports_reasoning_toggle": bool(
                metadata.get("supports_reasoning_toggle", False)
            ),
            "reasoning_options": [
                str(option or "").strip().lower()
                for option in list(options or ())
                if str(option or "").strip()
            ],
            "reasoning_default": str(
                metadata.get("reasoning_default") or ""
            ).strip().lower(),
        }

    def _frozen_binding_values(self, binding) -> tuple[dict[str, Any], dict[str, Any]]:
        provider_config_copy = getattr(binding, "_provider_config_copy", None)
        generation_fields_copy = getattr(binding, "_generation_fields_copy", None)
        if not callable(provider_config_copy) or not callable(generation_fields_copy):
            raise RuntimeError("LM Studio frozen execution received an invalid binding.")
        provider_config = provider_config_copy()
        generation_fields = generation_fields_copy()
        if not isinstance(provider_config, dict) or not isinstance(generation_fields, dict):
            raise RuntimeError("LM Studio frozen execution received invalid captured state.")
        return provider_config, generation_fields

    def _frozen_reasoning_metadata(
        self,
        provider_config: Mapping[str, Any],
        generation_fields: Mapping[str, Any],
        *,
        model_name: str,
    ) -> dict[str, Any]:
        catalog_metadata = generation_fields.get(_FROZEN_REASONING_METADATA_FIELD)
        if isinstance(catalog_metadata, Mapping) and str(
            catalog_metadata.get("model_key") or ""
        ).strip() == str(model_name or "").strip():
            options = catalog_metadata.get("reasoning_options", ())
            if isinstance(options, str):
                options = [options]
            return {
                "supports_reasoning": bool(
                    catalog_metadata.get("supports_reasoning", False)
                ),
                "reasoning_options": [
                    str(option or "").strip().lower()
                    for option in list(options or ())
                    if str(option or "").strip()
                ],
                "reasoning_default": str(
                    catalog_metadata.get("reasoning_default") or ""
                ).strip().lower(),
            }

        captured_metadata = provider_config.get("model_metadata")
        metadata = dict(captured_metadata) if isinstance(captured_metadata, Mapping) else {}
        supports_reasoning = bool(
            generation_fields.get(
                "model_supports_reasoning",
                metadata.get("supports_reasoning", False),
            )
        )
        options = generation_fields.get(
            "reasoning_options",
            metadata.get("reasoning_options", ()),
        )
        if isinstance(options, str):
            options = [options]
        normalized_options = [
            str(option or "").strip().lower()
            for option in list(options or ())
            if str(option or "").strip()
        ]
        if (
            not normalized_options
            and bool(generation_fields.get("model_supports_reasoning_toggle", False))
        ):
            normalized_options = ["off", "on"]
        return {
            "supports_reasoning": supports_reasoning,
            "reasoning_options": normalized_options,
            "reasoning_default": str(
                generation_fields.get(
                    "reasoning_default",
                    metadata.get("reasoning_default", ""),
                )
                or ""
            ).strip().lower(),
        }

    def _frozen_compatibility_fingerprint(self, *, url: str, model: str) -> str:
        value = json.dumps(
            {
                "model": str(model or "").strip(),
                "protocol": _FROZEN_COMPATIBILITY_PROTOCOL,
                "url": str(url or "").strip().rstrip("/"),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _frozen_execution_state(self, request) -> dict[str, Any]:
        context = getattr(request, "context", None)
        binding = getattr(context, "_binding", None)
        provider_config, _generation_fields = self._frozen_binding_values(binding)
        params_copy = getattr(request, "params_copy", None)
        additional_copy = getattr(request, "additional_params_copy", None)
        if not callable(params_copy) or not callable(additional_copy):
            raise RuntimeError("LM Studio frozen execution received an invalid request.")
        params = params_copy()
        additional = additional_copy()
        payload = params.get("lmstudio_responses_payload")
        transport = additional.get("lmstudio_transport")
        if not isinstance(payload, dict) or not isinstance(transport, dict):
            raise RuntimeError("LM Studio frozen execution received an unprepared request.")
        model_name = str(getattr(binding, "model_name", "") or "").strip()
        base_url = _normalize_openai_base_url(
            provider_config.get("base_url") or DEFAULT_BASE_URL
        )
        url = responses_url(base_url)
        expected_fingerprint = self._frozen_compatibility_fingerprint(
            url=url,
            model=model_name,
        )
        if (
            transport.get("compatibility_protocol") != _FROZEN_COMPATIBILITY_PROTOCOL
            or transport.get("compatibility_fingerprint") != expected_fingerprint
            or str(payload.get("model") or "").strip() != model_name
        ):
            raise RuntimeError("LM Studio frozen compatibility attestation mismatch.")
        return {
            "api_key": str(provider_config.get("api_key") or DEFAULT_API_KEY),
            "local_responsiveness": bool(transport.get("local_responsiveness")),
            "model": model_name,
            "payload": payload,
            "url": url,
            "worker": bool(transport.get("worker")),
        }

    @contextlib.contextmanager
    def _captured_responsiveness_guard(self, enabled: bool, guard_factory):
        if not enabled:
            yield
            return
        with guard_factory(logger=print):
            yield

    def _prepared_responses_request(
        self,
        *,
        url: str,
        api_key: str,
        payload: Mapping[str, Any],
        timeout: float,
    ):
        request = Request(
            str(url),
            data=json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            return urlopen(request, timeout=float(timeout))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(http_error_text(exc)) from exc

    def _probe_frozen_responses(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        timeout: float,
    ) -> bool:
        payload = {
            "model": str(model or "").strip(),
            "input": [{"role": "user", "content": "Reply with exactly OK."}],
            "max_output_tokens": 16,
            "store": False,
            "stream": False,
            "reasoning": {"effort": "none"},
        }
        try:
            with self._prepared_responses_request(
                url=url,
                api_key=api_key,
                payload=payload,
                timeout=timeout,
            ) as response:
                body = json.loads(
                    decode_http_text(response.read(), response_charset(response))
                )
            extract_response_text(body)
            return True
        except Exception as exc:
            raise RuntimeError(
                "LM Studio 0.4.7 or newer is required for NeuralCompanion chat. "
                "The configured server must support POST /v1/responses and reasoning.effort=none. "
                f"Probe failed: {exc}"
            ) from exc

    def _ensure_frozen_responses_compatibility(
        self,
        *,
        url: str,
        api_key: str,
        model: str,
        timeout: float,
    ) -> None:
        clean_url = str(url or "").strip().rstrip("/")
        clean_model = str(model or "").strip()
        if not clean_url or not clean_model:
            raise RuntimeError(
                "LM Studio frozen chat requires a captured endpoint and model before checking compatibility."
            )
        key = (clean_url, clean_model)
        self._run_compatibility_probe(
            key,
            lambda: self._probe_frozen_responses(
                url=clean_url,
                api_key=str(api_key or DEFAULT_API_KEY),
                model=clean_model,
                timeout=float(timeout),
            ),
        )

    def _compatibility_state(self):
        with _COMPATIBILITY_STATE_INIT_LOCK:
            cache = getattr(self, "_responses_compatibility_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._responses_compatibility_cache = cache
            lock = getattr(self, "_responses_compatibility_lock", None)
            if not callable(getattr(lock, "acquire", None)):
                lock = threading.Lock()
                self._responses_compatibility_lock = lock
            flights = getattr(self, "_responses_compatibility_flights", None)
            if not isinstance(flights, dict):
                flights = {}
                self._responses_compatibility_flights = flights
        return cache, lock, flights

    def _run_compatibility_probe(self, key, probe) -> None:
        cache, lock, flights = self._compatibility_state()
        with lock:
            if bool(cache.get(key)):
                return
            flight = flights.get(key)
            owner = flight is None
            if owner:
                flight = _CompatibilityFlight()
                flights[key] = flight

        if not owner:
            flight.event.wait()
            with lock:
                if bool(cache.get(key)):
                    return
                error = flight.error
            if error is None:
                raise RuntimeError(
                    "LM Studio compatibility probe ended without a shared result."
                )
            raise RuntimeError(str(error)) from error

        try:
            probe()
        except BaseException as exc:
            with lock:
                flight.error = exc
                if flights.get(key) is flight:
                    flights.pop(key, None)
                flight.event.set()
            raise
        else:
            with lock:
                cache[key] = True
                if flights.get(key) is flight:
                    flights.pop(key, None)
                flight.event.set()

    def _complete_prepared_direct(
        self,
        *,
        url: str,
        api_key: str,
        payload: Mapping[str, Any],
        timeout: float,
    ) -> str:
        with self._prepared_responses_request(
            url=url,
            api_key=api_key,
            payload=payload,
            timeout=timeout,
        ) as response:
            body = json.loads(
                decode_http_text(response.read(), response_charset(response))
            )
        return _strip_channel_blocks(extract_response_text(body))

    def _stream_prepared_direct(
        self,
        *,
        url: str,
        api_key: str,
        payload: Mapping[str, Any],
        timeout: float,
    ):
        with self._prepared_responses_request(
            url=url,
            api_key=api_key,
            payload=payload,
            timeout=timeout,
        ) as response:
            charset = response_charset(response)
            lines = (decode_http_text(raw_line, charset) for raw_line in response)
            yield from _filter_channel_blocks_stream(iter_response_sse(lines))

    def _start_prepared_worker(
        self,
        *,
        command: Iterable[str],
        creationflags: int,
    ) -> subprocess.Popen:
        command_parts = [str(part) for part in command]
        if len(command_parts) < 3 or not Path(command_parts[-1]).exists():
            raise RuntimeError("LM Studio helper process is missing.")
        return subprocess.Popen(
            command_parts,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=int(creationflags),
        )

    def _complete_prepared_worker(
        self,
        *,
        config: Mapping[str, Any],
        timeout: float,
        poll_interval: float,
        ui_yield_seconds: float,
        command: Iterable[str],
        creationflags: int,
    ) -> str:
        process = self._start_prepared_worker(
            command=command,
            creationflags=creationflags,
        )
        config_text = json.dumps(dict(config), ensure_ascii=True)
        try:
            stdout, stderr = self._communicate_worker(
                process,
                config_text,
                timeout=timeout,
                poll_interval=poll_interval,
                ui_yield_seconds=ui_yield_seconds,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("LM Studio helper process timed out.")
        result = self._last_worker_payload(stdout)
        if result.get("ok"):
            return str(result.get("text") or "").strip()
        error = str(
            result.get("error") or stderr or "LM Studio helper process failed."
        ).strip()
        raise RuntimeError(error)

    def _stream_prepared_worker(
        self,
        *,
        config: Mapping[str, Any],
        timeout: float,
        poll_interval: float,
        ui_yield_seconds: float,
        command: Iterable[str],
        creationflags: int,
    ):
        process = self._start_prepared_worker(
            command=command,
            creationflags=creationflags,
        )
        self._send_worker_config(process, dict(config))
        final_payload: dict[str, Any] = {}
        return_code = None
        try:
            for line in self._iter_worker_stdout_lines(
                process,
                timeout=timeout,
                poll_interval=poll_interval,
                ui_yield_seconds=ui_yield_seconds,
            ):
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
        try:
            stderr = process.stderr.read() if process.stderr is not None else ""
        except Exception:
            stderr = ""
        if final_payload.get("ok"):
            return
        error = str(
            final_payload.get("error")
            or stderr
            or f"LM Studio helper process exited with code {return_code}."
        ).strip()
        raise RuntimeError(error)

    def _strict_local_capability(self, binding, *, sdk_loader):
        try:
            provider_config, _generation_fields = self._frozen_binding_values(binding)
            base_url = _normalize_openai_base_url(
                provider_config.get("base_url") or DEFAULT_BASE_URL
            )
            if not lmstudio_runtime.is_local_base_url(base_url):
                return None
            model_name = str(binding.model_name or "").strip()
            if not model_name:
                return None
            sdk = sdk_loader()
            client_type = getattr(sdk, "Client", None) if sdk is not None else None
            chat_type = getattr(sdk, "Chat", None) if sdk is not None else None
            from_history = getattr(chat_type, "from_history", None)
            if not callable(client_type) or not callable(from_history):
                return None
            client = lmstudio_runtime.sdk_client(sdk, base_url)
            if client is None:
                return None
            llm_namespace = getattr(client, "llm", None)
            list_loaded = getattr(llm_namespace, "list_loaded", None)
            if not callable(list_loaded):
                return None
            matches = []
            for model in list(list_loaded()):
                identity = self._loaded_model_identity(model)
                if identity is not None and identity[0] == model_name:
                    matches.append((model, identity))
            if len(matches) != 1:
                return None
            model, identity = matches[0]
            context_limit = model.get_context_length()
            if type(context_limit) is not int or context_limit <= 0:
                return None
            if not callable(getattr(model, "apply_prompt_template", None)) or not callable(
                getattr(model, "tokenize", None)
            ):
                return None
            execution_identity = binding.execution_identity

            def exact_token_counter(messages) -> int:
                current_identity = self._loaded_model_identity(model)
                if current_identity != identity:
                    raise RuntimeError("LM Studio loaded model instance changed.")
                current_context = model.get_context_length()
                if current_context != context_limit:
                    raise RuntimeError("LM Studio loaded context length changed.")
                history = []
                for message in messages:
                    if not isinstance(message, Mapping):
                        raise TypeError("LM Studio strict counting requires message mappings.")
                    role = str(message.get("role") or "").strip().lower()
                    content = message.get("content")
                    if role not in {"system", "user", "assistant"} or not isinstance(
                        content,
                        str,
                    ):
                        raise ValueError(
                            "LM Studio strict counting supports plain text chat messages only."
                        )
                    if role == "system" and history and history[-1]["role"] == "system":
                        history[-1]["content"] = (
                            f"{history[-1]['content']}\n\n{content}"
                        )
                    else:
                        history.append({"role": role, "content": content})
                chat = from_history({"messages": history})
                formatted = model.apply_prompt_template(chat)
                if not isinstance(formatted, str):
                    raise TypeError("LM Studio prompt template did not return text.")
                tokens = model.tokenize(formatted)
                count = len(tokens)
                if type(count) is not int or count < 0:
                    raise ValueError("LM Studio tokenizer returned an invalid count.")
                return count

            return {
                "context_limit": context_limit,
                "token_counter": exact_token_counter,
                "capability_identity": execution_identity,
                "token_counter_identity": execution_identity,
            }
        except Exception:
            return None

    def _loaded_model_identity(self, model) -> tuple[str, str, str] | None:
        try:
            info = model.get_info()
        except Exception:
            return None

        def info_value(*names: str):
            for name in names:
                if isinstance(info, Mapping) and info.get(name) not in {None, ""}:
                    return info.get(name)
                value = getattr(info, name, None)
                if value not in {None, ""}:
                    return value
            return None

        model_keys = {
            str(value).strip()
            for value in (
                info_value("model_key"),
                info_value("modelKey"),
                info_value("key"),
            )
            if str(value or "").strip()
        }
        if len(model_keys) != 1:
            return None
        model_key = next(iter(model_keys))
        handle_identifier = str(getattr(model, "identifier", None) or "").strip()
        info_identifier = str(info_value("identifier") or "").strip()
        if not info_identifier or (
            handle_identifier and handle_identifier != info_identifier
        ):
            return None
        identifier = info_identifier
        instance_reference = str(
            info_value("instanceReference", "instance_reference") or ""
        ).strip()
        if not identifier or not instance_reference:
            return None
        return model_key, identifier, instance_reference

    def _responsiveness_guard(self):
        if not lmstudio_runtime.is_local_base_url(self._base_url()):
            return contextlib.nullcontext()
        return lmstudio_runtime.local_inference_responsiveness_guard(logger=print)

    def _worker_enabled(self) -> bool:
        value = str(os.environ.get("NC_LMSTUDIO_HELPER_PROCESS", "1") or "1").strip().lower()
        return value not in {"0", "false", "no", "off"}

    def _worker_path(self) -> Path:
        return Path(__file__).resolve().with_name("worker.py")

    def _worker_creation_flags(self) -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def _responses_url(self) -> str:
        return responses_url(self._base_url())

    def _worker_request_config(
        self,
        params: dict[str, Any],
        additional_params: dict[str, Any] | None = None,
        *,
        emit_chunks: bool = False,
        stream: bool = False,
    ) -> dict[str, Any]:
        return {
            "url": self._responses_url(),
            "api_key": self._api_key(),
            "payload": self._responses_payload(params, additional_params, stream=stream),
            "emit_chunks": bool(emit_chunks) and bool(stream),
            "stream": bool(stream),
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
        process.stdin.write(json.dumps(dict(config or {}), ensure_ascii=True))
        process.stdin.close()

    def _communicate_worker(
        self,
        process: subprocess.Popen,
        input_text: str,
        *,
        timeout: float,
        poll_interval: float | None = None,
        ui_yield_seconds: float | None = None,
    ) -> tuple[str, str]:
        deadline = time.monotonic() + max(1.0, float(timeout or _worker_timeout_seconds()))
        poll_seconds = (
            _worker_poll_interval_seconds()
            if poll_interval is None
            else max(0.001, float(poll_interval))
        )
        first_attempt = True
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                stdout, stderr = process.communicate(timeout=5)
                raise subprocess.TimeoutExpired(process.args, timeout, output=stdout, stderr=stderr)
            try:
                if first_attempt:
                    return process.communicate(
                        input=input_text,
                        timeout=min(poll_seconds, remaining),
                    )
                return process.communicate(timeout=min(poll_seconds, remaining))
            except subprocess.TimeoutExpired:
                first_attempt = False
                if ui_yield_seconds is None:
                    _yield_ui()
                else:
                    _yield_ui_for_seconds(float(ui_yield_seconds))

    def _iter_worker_stdout_lines(
        self,
        process: subprocess.Popen,
        *,
        timeout: float,
        poll_interval: float | None = None,
        ui_yield_seconds: float | None = None,
    ):
        if process.stdout is None:
            raise RuntimeError("LM Studio helper process did not expose stdout.")
        line_queue: queue.Queue[object] = queue.Queue()

        def reader() -> None:
            try:
                for line in process.stdout:
                    line_queue.put(line)
            except Exception as exc:
                line_queue.put(exc)
            finally:
                line_queue.put(None)

        threading.Thread(target=reader, name="nc-lmstudio-worker-stdout", daemon=True).start()
        deadline = time.monotonic() + max(1.0, float(timeout or _worker_timeout_seconds()))
        poll_seconds = (
            _worker_poll_interval_seconds()
            if poll_interval is None
            else max(0.001, float(poll_interval))
        )
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                raise subprocess.TimeoutExpired(process.args, timeout)
            try:
                item = line_queue.get(timeout=min(poll_seconds, remaining))
            except queue.Empty:
                if ui_yield_seconds is None:
                    _yield_ui()
                else:
                    _yield_ui_for_seconds(float(ui_yield_seconds))
                continue
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield str(item)

    def _complete_chat_via_worker(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        process = self._start_worker()
        config_text = json.dumps(
            self._worker_request_config(params, additional_params, emit_chunks=False, stream=False),
            ensure_ascii=True,
        )
        try:
            stdout, stderr = self._communicate_worker(process, config_text, timeout=_worker_timeout_seconds())
        except subprocess.TimeoutExpired:
            raise RuntimeError("LM Studio helper process timed out.")
        payload = self._last_worker_payload(stdout)
        if payload.get("ok"):
            return str(payload.get("text") or "").strip()
        error = str(payload.get("error") or stderr or "LM Studio helper process failed.").strip()
        raise RuntimeError(error)

    def _stream_chat_via_worker(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        process = self._start_worker()
        self._send_worker_config(process, self._worker_request_config(params, additional_params, emit_chunks=True, stream=True))
        final_payload: dict[str, Any] = {}
        return_code = None
        try:
            for line in self._iter_worker_stdout_lines(process, timeout=_worker_timeout_seconds()):
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
        return _normalize_openai_base_url(self._setting("base_url") or DEFAULT_BASE_URL)

    def _native_api_base_url(self) -> str:
        base_url = str(self._base_url() or DEFAULT_BASE_URL).strip().rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        return base_url.rstrip("/") or "http://127.0.0.1:1234"

    def _client(self) -> OpenAI:
        return OpenAI(base_url=self._base_url(), api_key=self._api_key())

    def _model_metadata(self, model_id: str) -> dict[str, Any]:
        clean_model_id = str(model_id or "").strip()
        metadata = dict(getattr(self, "_model_catalog_by_id", {}).get(clean_model_id) or {})
        if not metadata and clean_model_id:
            self._list_native_models(quiet=True)
            metadata = dict(getattr(self, "_model_catalog_by_id", {}).get(clean_model_id) or {})
        return metadata

    def _responses_payload(
        self,
        params: dict[str, Any] | None,
        additional_params: dict[str, Any] | None = None,
        *,
        stream: bool = False,
    ) -> dict[str, Any]:
        source = dict(params or {})
        model_id = str(source.get("model") or "").strip()
        return build_responses_payload(
            source,
            dict(additional_params or {}),
            self._model_metadata(model_id),
            stream=stream,
        )

    def _responses_request(self, payload: dict[str, Any]):
        request = Request(
            self._responses_url(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            return urlopen(request, timeout=300.0)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(http_error_text(exc)) from exc

    def _post_responses_probe(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._responses_request(payload) as response:
            return json.loads(decode_http_text(response.read(), response_charset(response)))

    def _ensure_responses_compatibility(self, model_id: str) -> None:
        clean_model_id = str(model_id or "").strip()
        if not clean_model_id:
            raise RuntimeError("LM Studio chat requires a selected model before checking Responses compatibility.")
        key = (self._responses_url().rstrip("/"), clean_model_id)

        payload = {
            "model": clean_model_id,
            "input": [{"role": "user", "content": "Reply with exactly OK."}],
            "max_output_tokens": 16,
            "store": False,
            "stream": False,
            "reasoning": {"effort": "none"},
        }
        def probe() -> None:
            try:
                response_payload = self._post_responses_probe(payload)
                extract_response_text(response_payload)
            except Exception as exc:
                raise RuntimeError(
                    "LM Studio 0.4.7 or newer is required for NeuralCompanion chat. "
                    "The configured server must support POST /v1/responses and reasoning.effort=none. "
                    f"Probe failed: {exc}"
                ) from exc

        self._run_compatibility_probe(key, probe)

    def _complete_responses(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None) -> str:
        payload = self._responses_payload(params, additional_params, stream=False)
        with self._responses_request(payload) as response:
            body = json.loads(decode_http_text(response.read(), response_charset(response)))
        return _strip_channel_blocks(extract_response_text(body))

    def _stream_responses(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        payload = self._responses_payload(params, additional_params, stream=True)
        with self._responses_request(payload) as response:
            charset = response_charset(response)
            lines = (decode_http_text(raw_line, charset) for raw_line in response)
            yield from _filter_channel_blocks_stream(iter_response_sse(lines))

    def _list_models(self, quiet: bool = False):
        native_models = self._list_native_models(quiet=quiet)
        return native_models if native_models is not None else []

    def _list_native_models(self, quiet: bool = False):
        url = f"{self._native_api_base_url()}/api/v1/models"
        headers = {"Authorization": f"Bearer {self._api_key()}"}
        try:
            request = Request(url, headers=headers, method="GET")
            with urlopen(request, timeout=5.0) as response:
                payload = json.loads(decode_http_text(response.read(), response_charset(response)))
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
            reasoning = capabilities.get("reasoning") if isinstance(capabilities.get("reasoning"), dict) else {}
            reasoning_options = {
                str(option or "").strip().lower()
                for option in list(reasoning.get("allowed_options") or [])
                if str(option or "").strip()
            }
            catalog.append(
                {
                    "id": model_id,
                    "supports_images": bool(capabilities.get("vision", False)),
                    "supports_reasoning": bool(reasoning),
                    "supports_reasoning_toggle": bool(reasoning_options),
                    "reasoning_options": sorted(reasoning_options),
                    "reasoning_default": str(reasoning.get("default") or "").strip().lower(),
                    "source": "lmstudio_native",
                }
            )
        self._model_catalog_by_id = {str(item.get("id") or ""): dict(item) for item in catalog}
        return sorted(catalog, key=lambda item: str(item.get("id") or "").lower())

    def _check_connection(self):
        try:
            models = self._list_native_models(quiet=False)
            if not models:
                raise RuntimeError("LM Studio returned no available LLM models from /api/v1/models")
            selected_model_id = self._setting("model_name")
            available_ids = {str(item.get("id") or "").strip() for item in models}
            model_id = selected_model_id if selected_model_id in available_ids else str(models[0].get("id") or "").strip()
            self._ensure_responses_compatibility(model_id)
            count = len(models)
            return {
                "ok": True,
                "detail": f"Connected to LM Studio Responses ({count} model(s) available)",
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
            self._ensure_responses_compatibility(str((params or {}).get("model") or ""))
            if self._worker_enabled():
                return self._complete_chat_via_worker(params, additional_params)
            return self._complete_responses(params, additional_params)

    def _stream_chat(self, params: dict[str, Any], additional_params: dict[str, Any] | None = None):
        def guarded_stream():
            with self._responsiveness_guard():
                self._ensure_responses_compatibility(str((params or {}).get("model") or ""))
                if self._worker_enabled():
                    yield from self._stream_chat_via_worker(params, additional_params)
                    return
                yield from self._stream_responses(params, additional_params)

        return guarded_stream()
