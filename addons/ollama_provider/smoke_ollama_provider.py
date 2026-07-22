"""Smoke checks for the Ollama chat provider addon."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import types
from pathlib import Path
from urllib.error import URLError


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

from addons.ollama_provider import main as ollama_main
from addons.ollama_provider.main import Addon
from core import chat_providers
from core.runtime_chat import ChatProviderRuntime


class _FakeEvents:
    def subscribe(self, *_args, **_kwargs):
        return None


class _FakeLogger:
    def info(self, *_args, **_kwargs):
        return None

    def warning(self, *_args, **_kwargs):
        return None


class _FakeChatService:
    def __init__(self):
        self.registration = None

    def register_provider(self, **kwargs):
        self.registration = dict(kwargs)
        return {}

    def get_provider_setting(self, provider_id, field_id):
        return chat_providers.get_provider_setting(provider_id, field_id)


class _FakeContext:
    def __init__(self, chat_service):
        self._chat_service = chat_service
        self.events = _FakeEvents()
        self.logger = _FakeLogger()

    def get_service(self, service_id):
        if service_id == "qt.chat_providers":
            return self._chat_service
        return None


class _FakeCompletions:
    def __init__(self, record):
        self._record = record

    def create(self, **kwargs):
        self._record["requests"].append(dict(kwargs))
        if kwargs.get("stream"):
            return iter(
                (
                    types.SimpleNamespace(
                        choices=[
                            types.SimpleNamespace(
                                delta=types.SimpleNamespace(content="frozen ")
                            )
                        ]
                    ),
                    types.SimpleNamespace(
                        choices=[
                            types.SimpleNamespace(
                                delta=types.SimpleNamespace(content="stream")
                            )
                        ]
                    ),
                )
            )
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content="frozen completion")
                )
            ]
        )


class _FakeOpenAI:
    records = []

    def __init__(self, *, api_key, base_url):
        record = {"api_key": api_key, "base_url": base_url, "requests": []}
        self.records.append(record)
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(record))


def test_offline_lifecycle_unload_stays_quiet():
    addon = Addon()
    addon._last_unload_at = 0.0
    addon._last_model_name = ""
    addon._running_model_names = lambda: (_ for _ in ()).throw(URLError("timed out"))  # type: ignore[method-assign]

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        unloaded = addon._unload_running_models(reason="engine_start", force=True)

    assert unloaded == 0
    assert "Could not unload running model" not in output.getvalue()


def test_unexpected_unload_error_still_warns():
    addon = Addon()
    addon._last_unload_at = 0.0
    addon._last_model_name = ""
    addon._running_model_names = lambda: (_ for _ in ()).throw(RuntimeError("unexpected parse failure"))  # type: ignore[method-assign]

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        unloaded = addon._unload_running_models(reason="engine_start", force=True)

    assert unloaded == 0
    assert "Could not unload running model" in output.getvalue()


def test_legacy_completion_and_stream_request_shape_is_unchanged():
    addon = Addon()
    addon._last_model_name = ""
    _FakeOpenAI.records = []
    client = _FakeOpenAI(api_key="legacy-key", base_url="http://legacy.invalid/v1")
    addon._client = lambda: client
    params = {
        "model": "legacy-model",
        "messages": [{"role": "user", "content": "hello"}],
    }
    additional_params = {"top_k": 40}

    assert addon._complete_chat(params, additional_params) == "frozen completion"
    assert "".join(addon._stream_chat(params, additional_params)) == "frozen stream"
    assert addon._last_model_name == "legacy-model"
    assert _FakeOpenAI.records[0]["requests"] == [
        {
            "model": "legacy-model",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {"options": {"top_k": 40}},
        },
        {
            "model": "legacy-model",
            "messages": [{"role": "user", "content": "hello"}],
            "extra_body": {"options": {"top_k": 40}},
            "stream": True,
        },
    ]


def test_frozen_adapter_uses_only_captured_ollama_state():
    provider_id = "ollama"
    original_settings = chat_providers.get_provider_settings()
    original_openai = ollama_main.OpenAI
    original_api_env = os.environ.get("NC_CHAT_OLLAMA_API_KEY")
    original_base_url_env = os.environ.get("NC_CHAT_OLLAMA_BASE_URL")
    chat_service = _FakeChatService()
    addon = Addon()
    _FakeOpenAI.records = []
    ollama_main.OpenAI = _FakeOpenAI

    try:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(
            {
                provider_id: {
                    "api_key": "captured-secret",
                    "base_url": "http://captured.invalid:11434/v1",
                }
            }
        )
        addon.initialize(_FakeContext(chat_service))
        registration = dict(chat_service.registration or {})

        # These hooks are the new frozen adapter contract. This assertion is RED
        # until the addon registers all three execution phases.
        assert callable(registration["frozen_prepare_handler"])
        assert callable(registration["frozen_completion_handler"])
        assert callable(registration["frozen_stream_handler"])
        assert registration["frozen_execution_version"] == 1
        assert callable(registration["model_capabilities_handler"])

        prepare_calls = []
        original_prepare = registration["frozen_prepare_handler"]

        def counted_prepare(*args, **kwargs):
            prepare_calls.append(None)
            return original_prepare(*args, **kwargs)

        registration["frozen_prepare_handler"] = counted_prepare
        chat_providers.register_provider(**registration)
        live_config = {
            "chat_provider": provider_id,
            "model_name": "captured-model",
            "chat_provider_generation_settings": {
                provider_id: {
                    "temperature": 0.25,
                    "top_p": 0.75,
                    "top_k": 17,
                    "min_p": 0.12,
                    "repeat_penalty": 1.2,
                    "reasoning": False,
                    "max_tokens": 55,
                }
            },
            "model_supports_reasoning_toggle": True,
        }
        runtime = ChatProviderRuntime(lambda: live_config)
        context = runtime.capture_frozen_context()
        request = runtime.prepare_frozen_request(
            context,
            {
                "model": "caller-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
            {"num_ctx": 2048},
        )

        assert request.params["model"] == "captured-model"
        assert request.params["temperature"] == 0.25
        assert request.params["top_p"] == 0.75
        assert request.params["reasoning_effort"] == "none"
        assert request.params["max_tokens"] == 55
        assert dict(request.additional_params) == {
            "num_ctx": 2048,
            "top_k": 17,
            "min_p": 0.12,
            "repeat_penalty": 1.2,
        }
        assert prepare_calls == [None]
        assert "captured-secret" not in repr(context)
        assert "captured-secret" not in repr(request)

        chat_providers.set_provider_settings(
            {
                provider_id: {
                    "api_key": "live-secret",
                    "base_url": "http://live.invalid:11434/v1",
                }
            }
        )
        os.environ["NC_CHAT_OLLAMA_API_KEY"] = "env-live-secret"
        os.environ["NC_CHAT_OLLAMA_BASE_URL"] = "http://env-live.invalid:11434/v1"
        live_config["model_name"] = "live-model"
        addon._last_model_name = "live-model"
        addon._setting = lambda _field_id: (_ for _ in ()).throw(
            AssertionError("frozen execution called the live setting getter")
        )
        addon._client = lambda: (_ for _ in ()).throw(
            AssertionError("frozen execution called the live client factory")
        )
        chat_providers.register_provider(
            provider_id=provider_id,
            label="Replacement",
            frozen_prepare_handler=lambda *_args: (_ for _ in ()).throw(
                AssertionError("replacement prepare handler ran")
            ),
            frozen_completion_handler=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("replacement completion handler ran")
            ),
            frozen_stream_handler=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("replacement stream handler ran")
            ),
        )

        assert runtime.complete_frozen(request) == "frozen completion"
        assert "".join(runtime.stream_frozen(request)) == "frozen stream"
        assert prepare_calls == [None]
        assert runtime.upgrade_frozen_context_for_relay(context).strict_relay_available is False

        assert len(_FakeOpenAI.records) == 2
        for record in _FakeOpenAI.records:
            assert record["api_key"] == "captured-secret"
            assert record["base_url"] == "http://captured.invalid:11434/v1"
            assert record["requests"][0]["model"] == "captured-model"
            assert record["requests"][0]["extra_body"] == {
                "options": {
                    "num_ctx": 2048,
                    "top_k": 17,
                    "min_p": 0.12,
                    "repeat_penalty": 1.2,
                }
            }
    finally:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)
        ollama_main.OpenAI = original_openai
        if original_api_env is None:
            os.environ.pop("NC_CHAT_OLLAMA_API_KEY", None)
        else:
            os.environ["NC_CHAT_OLLAMA_API_KEY"] = original_api_env
        if original_base_url_env is None:
            os.environ.pop("NC_CHAT_OLLAMA_BASE_URL", None)
        else:
            os.environ["NC_CHAT_OLLAMA_BASE_URL"] = original_base_url_env


def test_frozen_context_marks_local_and_remote_base_urls():
    provider_id = ollama_main.PROVIDER_ID
    original_settings = chat_providers.get_provider_settings()
    chat_service = _FakeChatService()
    addon = Addon()
    expected_markers = (
        ("http://localhost:11434/v1", False),
        ("http://127.0.0.1:11434/v1", False),
        ("http://[::1]:11434/v1", False),
        ("http://0.0.0.0:11434/v1", False),
        ("http:///v1", False),
        ("https://ollama.remote.example/v1", True),
    )

    try:
        chat_providers.unregister_provider(provider_id)
        addon.initialize(_FakeContext(chat_service))
        registration = dict(chat_service.registration or {})
        chat_providers.register_provider(**registration)
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "captured-model"}
        )

        for base_url, expected_remote in expected_markers:
            chat_providers.set_provider_settings(
                {provider_id: {"base_url": base_url}}
            )
            context = runtime.capture_frozen_context()
            assert dict(context.provider_config) == {
                "base_url": base_url,
                "provider_is_remote": expected_remote,
            }
    finally:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)


def test_frozen_context_uses_one_base_url_for_locality_marker():
    provider_id = ollama_main.PROVIDER_ID
    original_settings = chat_providers.get_provider_settings()
    chat_service = _FakeChatService()
    addon = Addon()
    base_urls = iter(("http://127.0.0.1:11434/v1", "https://ollama.remote.example/v1"))

    def changing_setting(field_id):
        if field_id == "base_url":
            return next(base_urls)
        return ""

    try:
        chat_providers.unregister_provider(provider_id)
        addon._setting = changing_setting
        addon.initialize(_FakeContext(chat_service))
        chat_providers.register_provider(**dict(chat_service.registration or {}))
        context = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "captured-model"}
        ).capture_frozen_context()

        assert dict(context.provider_config) == {
            "base_url": "https://ollama.remote.example/v1",
            "provider_is_remote": True,
        }
    finally:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)


if __name__ == "__main__":
    test_offline_lifecycle_unload_stays_quiet()
    test_unexpected_unload_error_still_warns()
    test_legacy_completion_and_stream_request_shape_is_unchanged()
    test_frozen_adapter_uses_only_captured_ollama_state()
    test_frozen_context_marks_local_and_remote_base_urls()
    test_frozen_context_uses_one_base_url_for_locality_marker()
    print("ollama_provider smoke checks passed.")
