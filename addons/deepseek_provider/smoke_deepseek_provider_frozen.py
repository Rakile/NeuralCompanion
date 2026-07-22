"""Focused smoke checks for DeepSeek request-scoped frozen execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from addons.deepseek_provider import main as provider_module
from core import chat_providers
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

    def __init__(self) -> None:
        self._service = _ChatService()

    def get_service(self, name: str):
        return self._service if name == "qt.chat_providers" else None


class _OpenAIFactory:
    def __init__(self) -> None:
        self.clients: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs):
        self.clients.append(dict(kwargs))

        def create(**request):
            self.calls.append(dict(request))
            if request.get("stream"):
                delta = SimpleNamespace(content="deepseek-stream")
                return [SimpleNamespace(choices=[SimpleNamespace(delta=delta)])]
            message = SimpleNamespace(content="deepseek-complete")
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )


def _raise_live_read(*_args, **_kwargs):
    raise AssertionError("frozen execution attempted a live read")


def test_frozen_deepseek_uses_captured_state_and_thinking_shape() -> None:
    secret = "deepseek-captured-secret"
    captured_url = "https://captured.deepseek.invalid/v1"
    original_settings = chat_providers.get_provider_settings()
    original_openai = provider_module.OpenAI
    env_names = (
        "NC_CHAT_DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEY",
        "NC_CHAT_DEEPSEEK_BASE_URL",
    )
    original_env = {name: os.environ.get(name) for name in env_names}
    factory = _OpenAIFactory()
    config_calls = 0
    allow_config = True
    config = {
        "chat_provider": "deepseek",
        "model_name": "deepseek-captured",
        "chat_provider_generation_settings": {
            "deepseek": {
                "thinking_mode": "disabled",
                "reasoning_effort": "high",
                "temperature": 0.6,
                "top_p": 0.7,
                "frequency_penalty": 0.2,
                "presence_penalty": -0.3,
                "max_tokens": 444,
            }
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
            {"deepseek": {"api_key": secret, "base_url": captured_url}}
        )
        os.environ["NC_CHAT_DEEPSEEK_API_KEY"] = "captured-env-key"
        os.environ["NC_CHAT_DEEPSEEK_BASE_URL"] = "https://captured-env.invalid/v1"
        provider_module.OpenAI = factory
        addon = provider_module.Addon()
        prepare_calls: list[int] = []
        original_prepare = addon._prepare_frozen_chat

        def tracked_prepare(*args, **kwargs):
            prepare_calls.append(1)
            return original_prepare(*args, **kwargs)

        addon._prepare_frozen_chat = tracked_prepare
        addon.initialize(_Context())
        registered = chat_providers.get_provider("deepseek")
        assert registered is not None
        assert registered.normal_chat_available is True
        assert registered.frozen_execution_version == 1
        runtime = ChatProviderRuntime(get_config)
        context = runtime.capture_frozen_context()
        assert config_calls == 1

        chat_providers.set_provider_settings(
            {"deepseek": {"api_key": "live-key", "base_url": "https://live.invalid/v1"}}
        )
        os.environ["NC_CHAT_DEEPSEEK_API_KEY"] = "live-env-key"
        os.environ["NC_CHAT_DEEPSEEK_BASE_URL"] = "https://live-env.invalid/v1"
        config["model_name"] = "deepseek-live"
        config["chat_provider_generation_settings"]["deepseek"] = {
            "thinking_mode": "enabled",
            "reasoning_effort": "max",
            "temperature": 1.8,
            "top_p": 0.1,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "max_tokens": 999,
        }
        allow_config = False
        addon._setting = _raise_live_read
        addon._client = _raise_live_read
        chat_providers.register_provider(
            provider_id="deepseek",
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
                "thinking_mode": "enabled",
                "reasoning_effort": "max",
                "temperature": 2.0,
                "top_p": 0.0,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0,
                "max_tokens": 1000,
                "extra_body": {"preserved": True},
            },
        )
        assert request.params["model"] == "deepseek-captured"
        assert request.params["reasoning_effort"] == "high"
        assert request.params["temperature"] == 0.6
        assert request.params["top_p"] == 0.7
        assert request.params["frequency_penalty"] == 0.2
        assert request.params["presence_penalty"] == -0.3
        assert request.params["max_tokens"] == 444
        assert "thinking_mode" not in request.params
        assert request.params["extra_body"] == {
            "preserved": True,
            "thinking": {"type": "disabled"},
        }
        assert dict(context.provider_config) == {
            "base_url": captured_url,
            "provider_is_remote": True,
        }
        visible = " ".join(
            (repr(context), repr(request), repr(vars(context)), repr(vars(request)), repr(context.to_summary()), repr(request.to_summary()))
        )
        assert secret not in visible
        assert context.strict_relay_available is False

        assert runtime.complete_frozen(request, timeout=9.0) == "deepseek-complete"
        assert "".join(runtime.stream_frozen(request, timeout=11.0)) == "deepseek-stream"
        assert prepare_calls == [1]
        assert config_calls == 1
        assert factory.clients == [
            {"api_key": secret, "base_url": captured_url},
            {"api_key": secret, "base_url": captured_url},
        ]
        assert factory.calls[0]["timeout"] == 9.0
        assert factory.calls[0]["extra_body"]["thinking"] == {"type": "disabled"}
        assert factory.calls[1]["stream"] is True
        assert factory.calls[1]["timeout"] == 11.0
        assert factory.calls[1]["extra_body"]["thinking"] == {"type": "disabled"}
    finally:
        provider_module.OpenAI = original_openai
        chat_providers.unregister_provider("deepseek")
        chat_providers.set_provider_settings(original_settings)
        for name, value in original_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_legacy_deepseek_handlers_remain_unchanged() -> None:
    factory = _OpenAIFactory()
    addon = provider_module.Addon()
    addon._client = lambda: factory()
    params = {
        "model": "legacy",
        "thinking_mode": "enabled",
        "extra_body": {"preserved": True},
    }

    assert addon._complete_chat(params) == "deepseek-complete"
    assert "".join(addon._stream_chat(params)) == "deepseek-stream"
    assert factory.calls[0]["extra_body"] == {
        "preserved": True,
        "thinking": {"type": "enabled"},
    }
    assert factory.calls[1]["stream"] is True


if __name__ == "__main__":
    test_frozen_deepseek_uses_captured_state_and_thinking_shape()
    test_legacy_deepseek_handlers_remain_unchanged()
    print("DeepSeek frozen provider smoke checks passed.")
