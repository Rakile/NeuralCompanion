"""Focused smoke checks for OpenAI request-scoped frozen execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.openai_provider import main as provider_module
from core import chat_providers
from core.addons.qt_host_services import QtChatProviderService
from core.runtime_chat import ChatProviderRuntime


class _Logger:
    def info(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass


class _ChatService:
    def register_provider(self, **kwargs):
        return chat_providers.register_provider(**kwargs).to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        return chat_providers.unregister_provider(provider_id)

    def get_provider_setting(self, provider_id: str, field_id: str) -> str:
        return chat_providers.get_provider_setting(provider_id, field_id)


class _Context:
    logger = _Logger()

    def __init__(self, service) -> None:
        self._service = service

    def get_service(self, name: str):
        return self._service if name == "qt.chat_providers" else None


class _Window:
    def _populate_chat_provider_combo(self, _provider_id=None) -> None:
        pass


class _Completions:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    def create(self, **kwargs):
        request = dict(kwargs)
        self._calls.append(request)
        if "max_tokens" in request:
            raise RuntimeError(
                "Unsupported parameter: max_tokens; use max_completion_tokens instead"
            )
        if request.get("stream"):
            delta = SimpleNamespace(content="streamed")
            return [SimpleNamespace(choices=[SimpleNamespace(delta=delta)])]
        message = SimpleNamespace(content="completed")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _InputTokenCounts:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    def count(self, **kwargs):
        self._calls.append(dict(kwargs))
        return SimpleNamespace(input_tokens=37)


class _Responses:
    def __init__(
        self,
        calls: list[dict[str, object]],
        token_count_calls: list[dict[str, object]],
    ) -> None:
        self._calls = calls
        self.input_tokens = _InputTokenCounts(token_count_calls)

    def create(self, **kwargs):
        request = dict(kwargs)
        self._calls.append(request)
        if request.get("stream"):
            return [
                SimpleNamespace(
                    type="response.output_text.delta",
                    delta="streamed",
                )
            ]
        return SimpleNamespace(output_text="completed", output=[])


class _OpenAIFactory:
    def __init__(self) -> None:
        self.clients: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []
        self.response_calls: list[dict[str, object]] = []
        self.token_count_calls: list[dict[str, object]] = []

    def __call__(self, **kwargs):
        self.clients.append(dict(kwargs))
        completions = _Completions(self.calls)
        return SimpleNamespace(
            chat=SimpleNamespace(completions=completions),
            responses=_Responses(self.response_calls, self.token_count_calls),
        )


class _SamplingParameterError(RuntimeError):
    def __init__(self, parameter: str, message: str) -> None:
        super().__init__(message)
        self.param = parameter
        self.code = "unsupported_parameter"
        self.body = {
            "message": message,
            "type": "invalid_request_error",
            "param": parameter,
            "code": self.code,
        }


def _raise_live_read(*_args, **_kwargs):
    raise AssertionError("frozen execution attempted a live read")


def test_qt_host_forwards_all_frozen_registration_options() -> None:
    captured: dict[str, object] = {}
    original_register = chat_providers.register_provider
    prepare = lambda *_args: ({}, {})
    complete = lambda *_args, **_kwargs: "ok"
    stream = lambda *_args, **_kwargs: iter(("ok",))
    capability = lambda *_args: None
    counter = lambda _messages: 0

    def fake_register(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="bridge", to_summary=lambda: {"id": "bridge"})

    chat_providers.register_provider = fake_register
    try:
        summary = QtChatProviderService(_Window()).register_provider(
            provider_id="bridge",
            label="Bridge",
            frozen_prepare_handler=prepare,
            frozen_completion_handler=complete,
            frozen_stream_handler=stream,
            frozen_execution_version=1,
            model_capabilities_handler=capability,
            token_counter=counter,
            frozen_public_config_fields=("base_url", "provider_is_remote"),
        )
    finally:
        chat_providers.register_provider = original_register

    assert summary == {"id": "bridge"}
    assert captured["frozen_prepare_handler"] is prepare
    assert captured["frozen_completion_handler"] is complete
    assert captured["frozen_stream_handler"] is stream
    assert captured["frozen_execution_version"] == 1
    assert captured["model_capabilities_handler"] is capability
    assert captured["token_counter"] is counter
    assert captured["frozen_public_config_fields"] == ("base_url", "provider_is_remote")


def test_frozen_openai_uses_captured_state_and_preserves_retry() -> None:
    secret = "openai-captured-secret"
    captured_url = "https://captured.openai.invalid/v1"
    original_settings = chat_providers.get_provider_settings()
    original_openai = provider_module.OpenAI
    original_env = {
        name: os.environ.get(name)
        for name in ("NC_CHAT_OPENAI_API_KEY", "OPENAI_API_KEY", "NC_CHAT_OPENAI_BASE_URL")
    }
    factory = _OpenAIFactory()
    config_calls = 0
    allow_config = True
    config = {
        "chat_provider": "openai",
        "model_name": "captured-model",
        "chat_provider_generation_settings": {
            "openai": {"temperature": 0.25, "top_p": 0.75, "max_tokens": 321}
        },
    }

    def get_config():
        nonlocal config_calls
        config_calls += 1
        if not allow_config:
            raise AssertionError("frozen prepare/dispatch reread runtime config")
        return config

    try:
        chat_providers.set_provider_settings(
            {"openai": {"api_key": secret, "base_url": captured_url}}
        )
        os.environ["NC_CHAT_OPENAI_API_KEY"] = "captured-env-key"
        os.environ["NC_CHAT_OPENAI_BASE_URL"] = "https://captured-env.invalid/v1"
        provider_module.OpenAI = factory
        addon = provider_module.Addon()
        prepare_calls: list[int] = []
        original_prepare = addon._prepare_frozen_chat

        def tracked_prepare(*args, **kwargs):
            prepare_calls.append(1)
            return original_prepare(*args, **kwargs)

        addon._prepare_frozen_chat = tracked_prepare
        addon.initialize(_Context(_ChatService()))
        registered = chat_providers.get_provider("openai")
        assert registered is not None
        assert registered.normal_chat_available is True
        assert registered.frozen_execution_version == 1
        runtime = ChatProviderRuntime(get_config)
        context = runtime.capture_frozen_context()
        assert config_calls == 1

        chat_providers.set_provider_settings(
            {"openai": {"api_key": "live-key", "base_url": "https://live.invalid/v1"}}
        )
        os.environ["NC_CHAT_OPENAI_API_KEY"] = "live-env-key"
        os.environ["NC_CHAT_OPENAI_BASE_URL"] = "https://live-env.invalid/v1"
        config["model_name"] = "live-model"
        config["chat_provider_generation_settings"]["openai"] = {
            "temperature": 1.75,
            "top_p": 0.1,
            "max_tokens": 999,
        }
        allow_config = False
        addon._setting = _raise_live_read
        addon._client = _raise_live_read
        chat_providers.register_provider(
            provider_id="openai",
            label="Replacement",
            frozen_prepare_handler=_raise_live_read,
            frozen_completion_handler=_raise_live_read,
            frozen_stream_handler=_raise_live_read,
        )

        request = runtime.prepare_frozen_request(
            context,
            {
                "model": "caller-model",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 2.0,
                "top_p": 0.0,
                "max_tokens": 1000,
            },
            {"ignored_by_openai": "preserved"},
        )
        assert request.params["model"] == "captured-model"
        assert request.params["temperature"] == 0.25
        assert request.params["top_p"] == 0.75
        assert request.params["max_tokens"] == 321
        assert request.additional_params["ignored_by_openai"] == "preserved"
        bounded = runtime.prepare_frozen_request(
            context,
            {
                "messages": [{"role": "user", "content": "judge this"}],
                "max_tokens": 6272,
            },
            {chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE: 6272},
        )
        assert bounded.params["max_tokens"] == 6272
        assert chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE not in bounded.additional_params
        assert dict(context.provider_config) == {
            "base_url": captured_url,
            "provider_is_remote": True,
        }
        visible = " ".join(
            (repr(context), repr(request), repr(vars(context)), repr(vars(request)), repr(context.to_summary()), repr(request.to_summary()))
        )
        assert secret not in visible
        assert context.strict_relay_available is False

        assert runtime.complete_frozen(request, timeout=12.5) == "completed"
        assert "".join(runtime.stream_frozen(request, timeout=7.5)) == "streamed"
        assert prepare_calls == [1, 1]
        assert config_calls == 1
        assert factory.clients == [
            {"api_key": secret, "base_url": captured_url},
            {"api_key": secret, "base_url": captured_url},
        ]
        assert len(factory.calls) == 4
        assert factory.calls[0]["max_tokens"] == 321
        assert factory.calls[0]["timeout"] == 12.5
        assert factory.calls[1]["max_completion_tokens"] == 321
        assert "max_tokens" not in factory.calls[1]
        assert factory.calls[2]["stream"] is True
        assert factory.calls[2]["timeout"] == 7.5
        assert factory.calls[3]["max_completion_tokens"] == 321
        assert factory.calls[3]["stream"] is True
    finally:
        provider_module.OpenAI = original_openai
        chat_providers.unregister_provider("openai")
        chat_providers.set_provider_settings(original_settings)
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_official_openai_uses_opaque_model_id_with_frozen_token_counter() -> None:
    original_settings = chat_providers.get_provider_settings()
    original_openai = provider_module.OpenAI
    original_env = {
        name: os.environ.get(name)
        for name in ("NC_CHAT_OPENAI_API_KEY", "OPENAI_API_KEY", "NC_CHAT_OPENAI_BASE_URL")
    }
    factory = _OpenAIFactory()
    try:
        chat_providers.set_provider_settings(
            {"openai": {"api_key": "frozen-key", "base_url": ""}}
        )
        os.environ.pop("NC_CHAT_OPENAI_API_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("NC_CHAT_OPENAI_BASE_URL", None)
        provider_module.OpenAI = factory
        addon = provider_module.Addon()
        addon.initialize(_Context(_ChatService()))
        runtime = ChatProviderRuntime(
            lambda: {
                "chat_provider": "openai",
                "model_name": "synthetic-model-alpha",
                "chat_provider_generation_settings": {
                    "openai": {"max_tokens": -1}
                },
            }
        )

        context = runtime.capture_frozen_context()
        upgraded = runtime.upgrade_frozen_context_for_relay(context)
        messages = [
            {"role": "system", "content": "You are concise."},
            {"role": "user", "content": "Hello"},
        ]
        request = runtime.prepare_frozen_request(
            upgraded,
            {"model": "caller-model", "messages": messages},
        )

        assert upgraded.strict_relay_available is True
        assert upgraded.capabilities.context_limit is None
        assert request.params_copy() == {
            "model": "synthetic-model-alpha",
            "input": messages,
            "store": False,
            "temperature": 1.0,
            "top_p": 0.9,
        }
        assert chat_providers.count_frozen_chat_tokens(
            upgraded,
            request.params_copy()["input"],
        ) == 37
        assert runtime.complete_frozen(request, timeout=5.0) == "completed"
        assert "".join(runtime.stream_frozen(request, timeout=6.0)) == "streamed"
        assert factory.clients == [
            {"api_key": "frozen-key"},
            {"api_key": "frozen-key"},
            {"api_key": "frozen-key"},
        ]
        assert factory.token_count_calls == [
            {"model": "synthetic-model-alpha", "input": messages}
        ]
        assert factory.calls == []
        assert factory.response_calls == [
            {
                "model": "synthetic-model-alpha",
                "input": messages,
                "store": False,
                "temperature": 1.0,
                "top_p": 0.9,
                "timeout": 5.0,
            },
            {
                "model": "synthetic-model-alpha",
                "input": messages,
                "store": False,
                "temperature": 1.0,
                "top_p": 0.9,
                "stream": True,
                "timeout": 6.0,
            },
        ]
    finally:
        provider_module.OpenAI = original_openai
        chat_providers.unregister_provider("openai")
        chat_providers.set_provider_settings(original_settings)
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_gpt_56_frozen_responses_omit_unsupported_sampling_controls() -> None:
    binding = SimpleNamespace(
        model_name="gpt-5.6-luna",
        _generation_fields_copy=lambda: {
            "temperature": 0.7,
            "top_p": 0.9,
            "max_tokens": -1,
        },
    )

    request = provider_module._frozen_responses_params(
        binding,
        {"messages": [{"role": "user", "content": "Hello"}]},
    )

    assert request["model"] == "gpt-5.6-luna"
    assert "temperature" not in request
    assert "top_p" not in request


def test_responses_retry_only_explicitly_rejected_sampling_controls() -> None:
    calls: list[dict[str, object]] = []

    def create(**kwargs):
        request = dict(kwargs)
        calls.append(request)
        if "temperature" in request:
            raise _SamplingParameterError(
                "temperature",
                "Unsupported value: temperature only supports the provider default.",
            )
        if "top_p" in request:
            raise _SamplingParameterError(
                "top_p",
                "Unsupported parameter: top_p is not supported with this model.",
            )
        return "completed"

    original = {
        "model": "future-reasoning-model",
        "input": "Hello",
        "temperature": 0.7,
        "top_p": 0.9,
    }
    result = provider_module._create_responses_with_sampling_fallback(
        create,
        original,
    )

    assert result == "completed"
    assert original["temperature"] == 0.7
    assert original["top_p"] == 0.9
    assert [set(call) & {"temperature", "top_p"} for call in calls] == [
        {"temperature", "top_p"},
        {"top_p"},
        set(),
    ]


def test_openai_error_detail_uses_structured_safe_fields() -> None:
    error = _SamplingParameterError(
        "top_p",
        "Unsupported parameter: top_p is not supported with this model.",
    )

    assert provider_module._safe_openai_error_detail(error) == (
        "Unsupported parameter: top_p is not supported with this model. "
        "(param=top_p, code=unsupported_parameter)"
    )


def test_legacy_openai_handlers_remain_unchanged() -> None:
    factory = _OpenAIFactory()
    addon = provider_module.Addon()
    addon._client = lambda: factory()

    assert addon._complete_chat({"model": "legacy", "max_tokens": 5}) == "completed"
    assert "".join(addon._stream_chat({"model": "legacy", "max_tokens": 5})) == "streamed"
    assert len(factory.calls) == 4


if __name__ == "__main__":
    test_qt_host_forwards_all_frozen_registration_options()
    test_frozen_openai_uses_captured_state_and_preserves_retry()
    test_official_openai_uses_opaque_model_id_with_frozen_token_counter()
    test_gpt_56_frozen_responses_omit_unsupported_sampling_controls()
    test_responses_retry_only_explicitly_rejected_sampling_controls()
    test_openai_error_detail_uses_structured_safe_fields()
    test_legacy_openai_handlers_remain_unchanged()
    print("OpenAI frozen provider smoke checks passed.")
