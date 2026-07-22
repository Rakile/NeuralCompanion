"""Focused smoke checks for Claude's frozen and legacy chat paths."""

from __future__ import annotations

import json
import os
import sys
import types
import urllib.request
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

from addons.claude_provider.main import Addon, PROVIDER_ID
from core import chat_providers
from core.runtime_chat import ChatProviderRuntime


class _Logger:
    def info(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass


class _ChatService:
    def __init__(self) -> None:
        self.registration: dict[str, Any] = {}
        self.setting_reads: list[str] = []

    def register_provider(self, **kwargs):
        self.registration = dict(kwargs)
        return chat_providers.register_provider(**kwargs).to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        return chat_providers.unregister_provider(provider_id)

    def get_provider_setting(self, provider_id: str, field_id: str) -> str:
        assert provider_id == PROVIDER_ID
        self.setting_reads.append(field_id)
        return chat_providers.get_provider_setting(provider_id, field_id)


class _Context:
    def __init__(self, service: _ChatService) -> None:
        self.service = service
        self.logger = _Logger()

    def get_service(self, service_id: str):
        assert service_id == "qt.chat_providers"
        return self.service


class _ResponseHeaders:
    @staticmethod
    def get_content_charset() -> str:
        return "utf-8"


class _Response:
    def __init__(self, *, payload: dict[str, Any] | None = None, lines=()) -> None:
        self._payload = dict(payload or {})
        self._lines = tuple(lines)
        self.headers = _ResponseHeaders()

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __iter__(self):
        return iter(self._lines)


def _request_headers(request: urllib.request.Request) -> dict[str, str]:
    return {key.lower(): value for key, value in request.header_items()}


def test_frozen_completion_and_stream_use_one_captured_preparation() -> None:
    original_settings = chat_providers.get_provider_settings()
    original_urlopen = urllib.request.urlopen
    original_env = {
        name: os.environ.get(name)
        for name in (
            "ANTHROPIC_API_KEY",
            "NC_CHAT_CLAUDE_API_KEY",
            "NC_CHAT_CLAUDE_BASE_URL",
            "NC_CHAT_CLAUDE_API_VERSION",
        )
    }
    captured_secret = "captured-claude-secret"
    replacement_secret = "replacement-claude-secret"
    calls: list[dict[str, Any]] = []
    prepare_calls: list[int] = []
    dispatch_request_ids: list[int] = []
    service = _ChatService()
    addon = Addon()

    original_prepare = addon._prepare_frozen_request
    original_complete = addon._complete_frozen_chat
    original_stream = addon._stream_frozen_chat

    def counted_prepare(binding, params, additional_params):
        prepare_calls.append(1)
        return original_prepare(binding, params, additional_params)

    def counted_complete(request, **kwargs):
        dispatch_request_ids.append(id(request))
        return original_complete(request, **kwargs)

    def counted_stream(request, **kwargs):
        dispatch_request_ids.append(id(request))
        return original_stream(request, **kwargs)

    addon._prepare_frozen_request = counted_prepare  # type: ignore[method-assign]
    addon._complete_frozen_chat = counted_complete  # type: ignore[method-assign]
    addon._stream_frozen_chat = counted_stream  # type: ignore[method-assign]

    def fake_urlopen(request: urllib.request.Request, timeout: float):
        payload = json.loads(bytes(request.data or b"{}").decode("utf-8"))
        calls.append(
            {
                "url": request.full_url,
                "headers": _request_headers(request),
                "payload": payload,
                "timeout": timeout,
            }
        )
        if payload.get("stream"):
            return _Response(
                lines=(
                    b"event: content_block_delta\n",
                    b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"stream "}}\n',
                    b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"reply"}}\n',
                    b'data: {"type":"message_stop"}\n',
                )
            )
        return _Response(
            payload={
                "content": [
                    {"type": "text", "text": "frozen "},
                    {"type": "tool_use", "name": "ignored"},
                    {"type": "text", "text": "reply"},
                ]
            }
        )

    runtime_config: dict[str, Any] = {
        "chat_provider": PROVIDER_ID,
        "model_name": "claude-captured-model",
        "chat_provider_generation_settings": {
            PROVIDER_ID: {
                "max_tokens": 321,
                "temperature": 0.25,
                "top_k": 9,
            }
        },
    }
    raw_params: dict[str, Any] = {
        "model": "ignored-before-runtime-normalization",
        "messages": [
            {"role": "system", "content": "First system rule."},
            {
                "role": "system",
                "content": [{"type": "text", "text": "Second system rule."}],
            },
            {"role": "developer", "content": "Developer becomes user."},
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Look at this."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
                    },
                ],
            },
            {"role": "assistant", "content": "I see it."},
            {"role": "assistant", "content": "Anything else?"},
        ],
        "stop": ["END", ""],
    }

    try:
        chat_providers.set_provider_settings(
            {
                PROVIDER_ID: {
                    "api_key": captured_secret,
                    "base_url": "https://captured.example/v1",
                    "anthropic_version": "2025-01-01",
                    "max_tokens": "777",
                }
            }
        )
        addon.initialize(_Context(service))
        assert callable(service.registration.get("frozen_prepare_handler"))
        assert callable(service.registration.get("frozen_completion_handler"))
        assert callable(service.registration.get("frozen_stream_handler"))
        assert service.registration.get("frozen_execution_version") == 1
        assert service.registration.get("model_capabilities_handler") is None
        registered = chat_providers.get_provider(PROVIDER_ID)
        assert registered is not None
        assert registered.normal_chat_available is True

        runtime = ChatProviderRuntime(lambda: runtime_config)
        context = runtime.capture_frozen_context()
        reads_after_capture = list(service.setting_reads)
        assert context.model_name == "claude-captured-model"
        assert dict(context.provider_config) == {
            "provider_is_remote": True,
        }
        assert context.strict_relay_available is False

        runtime_config["chat_provider"] = "replacement-provider"
        runtime_config["model_name"] = "replacement-model"
        runtime_config["chat_provider_generation_settings"][PROVIDER_ID].update(
            {"max_tokens": 999, "temperature": 0.99, "top_k": 99}
        )
        chat_providers.set_provider_settings(
            {
                PROVIDER_ID: {
                    "api_key": replacement_secret,
                    "base_url": "https://replacement.example",
                    "anthropic_version": "2099-12-31",
                    "max_tokens": "999",
                }
            }
        )
        os.environ["ANTHROPIC_API_KEY"] = replacement_secret
        os.environ["NC_CHAT_CLAUDE_API_VERSION"] = "2099-env-version"

        def fail_live_read(*_args, **_kwargs):
            raise AssertionError("frozen execution attempted a live Claude read")

        addon._setting = fail_live_read  # type: ignore[method-assign]
        addon._headers = fail_live_read  # type: ignore[method-assign]
        addon._max_tokens = fail_live_read  # type: ignore[method-assign]
        addon._api_version = fail_live_read  # type: ignore[method-assign]
        addon._url = fail_live_read  # type: ignore[method-assign]
        addon._request_json = fail_live_read  # type: ignore[method-assign]

        raw_params.update({"max_tokens": 321, "temperature": 0.99, "top_k": 99})
        request = runtime.prepare_frozen_request(context, raw_params, {"ignored": True})
        expected_payload = {
            "model": "claude-captured-model",
            "max_tokens": 321,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Developer becomes user."},
                        {"type": "text", "text": "Look at this."},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "aW1hZ2U=",
                            },
                        },
                    ],
                },
                {"role": "assistant", "content": "I see it.\n\nAnything else?"},
            ],
            "system": "First system rule.\n\nSecond system rule.",
            "temperature": 0.25,
            "top_k": 9,
            "stop_sequences": ["END"],
        }
        assert request.params_copy() == expected_payload
        assert prepare_calls == [1]

        raw_params["messages"][0]["content"] = "mutated after preparation"
        chat_providers.register_provider(
            provider_id=PROVIDER_ID,
            label="Replacement Claude",
            frozen_prepare_handler=lambda *_args: ({}, {}),
            frozen_completion_handler=lambda *_args, **_kwargs: "replacement",
            frozen_stream_handler=lambda *_args, **_kwargs: iter(("replacement",)),
        )
        urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]

        assert runtime.complete_frozen(request, timeout=1.0) == "frozen reply"
        assert "".join(runtime.stream_frozen(request, timeout=2.0)) == "stream reply"
        assert prepare_calls == [1]
        assert dispatch_request_ids == [id(request), id(request)]
        assert service.setting_reads == reads_after_capture
        assert len(calls) == 2

        for call in calls:
            assert call["url"] == "https://captured.example/v1/messages"
            assert call["headers"]["x-api-key"] == captured_secret
            assert call["headers"]["anthropic-version"] == "2025-01-01"
            assert call["timeout"] == 120.0
            assert {key: value for key, value in call["payload"].items() if key != "stream"} == expected_payload
        assert calls[0]["payload"].get("stream") is None
        assert calls[1]["payload"]["stream"] is True

        visible = " ".join(
            (
                repr(context),
                repr(request),
                repr(vars(context)),
                repr(vars(request)),
                repr(context.to_summary()),
                repr(request.to_summary()),
            )
        )
        assert captured_secret not in visible
        assert replacement_secret not in visible
        assert "captured.example" not in visible
        assert runtime.upgrade_frozen_context_for_relay(context).strict_relay_available is False
    finally:
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
        chat_providers.unregister_provider(PROVIDER_ID)
        chat_providers.set_provider_settings(original_settings)
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_frozen_capture_preserves_environment_api_version() -> None:
    original_settings = chat_providers.get_provider_settings()
    original_urlopen = urllib.request.urlopen
    original_version = os.environ.get("NC_CHAT_CLAUDE_API_VERSION")
    service = _ChatService()
    addon = Addon()
    captured_headers: list[dict[str, str]] = []

    def fake_urlopen(request: urllib.request.Request, timeout: float):
        assert timeout == 120.0
        captured_headers.append(_request_headers(request))
        return _Response(payload={"content": [{"type": "text", "text": "ok"}]})

    try:
        chat_providers.set_provider_settings(
            {
                PROVIDER_ID: {
                    "api_key": "captured-key",
                    "base_url": "https://captured.example/v1",
                    "anthropic_version": "",
                }
            }
        )
        os.environ["NC_CHAT_CLAUDE_API_VERSION"] = "2025-06-30"
        addon.initialize(_Context(service))
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": PROVIDER_ID, "model_name": "claude-captured-model"}
        )
        context = runtime.capture_frozen_context()
        binding = context._binding
        assert binding is not None
        assert chat_providers.provider_base_url(PROVIDER_ID) == "https://captured.example/v1"
        private_config = binding._provider_config_copy()
        assert private_config["anthropic_version"] == "2025-06-30"
        assert "anthropic_version" not in context.provider_config

        os.environ["NC_CHAT_CLAUDE_API_VERSION"] = "2099-12-31"

        def fail_env_read(*_args, **_kwargs):
            raise AssertionError("frozen execution attempted a live environment read")

        addon._env_value = fail_env_read  # type: ignore[method-assign]
        addon._api_version = fail_env_read  # type: ignore[method-assign]
        request = runtime.prepare_frozen_request(
            context,
            {"messages": [{"role": "user", "content": "hello"}]},
        )
        urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
        assert runtime.complete_frozen(request) == "ok"
        assert "".join(runtime.stream_frozen(request)) == ""
        assert len(captured_headers) == 2
        assert captured_headers[0]["anthropic-version"] == "2025-06-30"
        assert captured_headers[1]["anthropic-version"] == "2025-06-30"
    finally:
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
        chat_providers.unregister_provider(PROVIDER_ID)
        chat_providers.set_provider_settings(original_settings)
        if original_version is None:
            os.environ.pop("NC_CHAT_CLAUDE_API_VERSION", None)
        else:
            os.environ["NC_CHAT_CLAUDE_API_VERSION"] = original_version


def test_frozen_max_tokens_preserves_normal_chat_precedence() -> None:
    original_settings = chat_providers.get_provider_settings()
    service = _ChatService()
    addon = Addon()

    try:
        chat_providers.set_provider_settings({PROVIDER_ID: {"max_tokens": "777"}})
        addon.initialize(_Context(service))

        provider_runtime = ChatProviderRuntime(
            lambda: {"chat_provider": PROVIDER_ID, "model_name": "claude-model"}
        )
        provider_context = provider_runtime.capture_frozen_context()
        chat_providers.set_provider_settings({PROVIDER_ID: {"max_tokens": "999"}})
        provider_request = provider_runtime.prepare_frozen_request(
            provider_context,
            {"messages": [{"role": "user", "content": "provider fallback"}]},
        )
        assert provider_request.params["max_tokens"] == 777

        chat_providers.set_provider_settings({PROVIDER_ID: {}})
        cap_config = {
            "chat_provider": PROVIDER_ID,
            "model_name": "claude-model",
            "limit_response_length": True,
            "max_response_tokens": 600,
        }
        cap_runtime = ChatProviderRuntime(lambda: cap_config)
        cap_context = cap_runtime.capture_frozen_context()
        cap_params = {"messages": [{"role": "user", "content": "global cap"}]}
        cap_additional: dict[str, Any] = {}
        cap_runtime.apply_generation_fields(cap_params, cap_additional)
        assert cap_params["max_tokens"] == 600
        cap_config["max_response_tokens"] = 900
        cap_request = cap_runtime.prepare_frozen_request(cap_context, cap_params, cap_additional)
        assert cap_request.params["max_tokens"] == 600

        chat_providers.set_provider_settings({PROVIDER_ID: {"max_tokens": "777"}})
        explicit_config = {
            "chat_provider": PROVIDER_ID,
            "model_name": "claude-model",
            "chat_provider_generation_settings": {PROVIDER_ID: {"max_tokens": 345}},
        }
        explicit_runtime = ChatProviderRuntime(lambda: explicit_config)
        explicit_context = explicit_runtime.capture_frozen_context()
        explicit_params = {"messages": [{"role": "user", "content": "explicit override"}]}
        explicit_additional: dict[str, Any] = {}
        explicit_runtime.apply_generation_fields(explicit_params, explicit_additional)
        assert explicit_params["max_tokens"] == 345
        explicit_config["chat_provider_generation_settings"][PROVIDER_ID]["max_tokens"] = 999
        explicit_request = explicit_runtime.prepare_frozen_request(
            explicit_context,
            explicit_params,
            explicit_additional,
        )
        assert explicit_request.params["max_tokens"] == 345
    finally:
        chat_providers.unregister_provider(PROVIDER_ID)
        chat_providers.set_provider_settings(original_settings)


def test_legacy_completion_and_stream_paths_remain_unchanged() -> None:
    addon = Addon()
    calls: list[tuple[Any, ...]] = []
    payload = {"model": "legacy-model", "messages": [{"role": "user", "content": "hello"}]}

    addon._build_messages_payload = lambda params: calls.append(("build", params)) or dict(payload)  # type: ignore[method-assign]
    addon._url = lambda path: calls.append(("url", path)) or "https://legacy.example/v1/messages"  # type: ignore[method-assign]
    addon._request_json = (  # type: ignore[method-assign]
        lambda method, url, request_payload, timeout: calls.append(
            ("request", method, url, request_payload, timeout)
        )
        or {"content": [{"type": "text", "text": "legacy reply"}]}
    )

    params = {"model": "legacy-model", "messages": []}
    assert addon._complete_chat(params, {"ignored": True}) == "legacy reply"
    assert calls == [
        ("build", params),
        ("url", "/v1/messages"),
        ("request", "POST", "https://legacy.example/v1/messages", payload, 120.0),
    ]

    calls.clear()
    original_urlopen = urllib.request.urlopen
    addon._headers = lambda accept: calls.append(("headers", accept)) or {"Accept": accept}  # type: ignore[method-assign]

    def fake_urlopen(request: urllib.request.Request, timeout: float):
        calls.append(("stream_request", request.full_url, timeout, json.loads(request.data or b"{}")))
        return _Response(
            lines=(
                b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"legacy stream"}}\n',
            )
        )

    try:
        urllib.request.urlopen = fake_urlopen  # type: ignore[assignment]
        assert "".join(addon._stream_chat(params, {"ignored": True})) == "legacy stream"
    finally:
        urllib.request.urlopen = original_urlopen  # type: ignore[assignment]
    assert calls == [
        ("build", params),
        ("headers", "text/event-stream"),
        ("url", "/v1/messages"),
        (
            "stream_request",
            "https://legacy.example/v1/messages",
            120.0,
            {**payload, "stream": True},
        ),
    ]


if __name__ == "__main__":
    test_frozen_completion_and_stream_use_one_captured_preparation()
    test_frozen_capture_preserves_environment_api_version()
    test_frozen_max_tokens_preserves_normal_chat_precedence()
    test_legacy_completion_and_stream_paths_remain_unchanged()
    print("claude_provider smoke checks passed.")
