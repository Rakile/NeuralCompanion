"""Adversarial smoke checks for request-scoped frozen chat provider dispatch."""

from __future__ import annotations

import importlib.util
import operator
import pickle
import sys
import types
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core import chat_providers
from core.runtime_chat import ChatProviderRuntime


def _assert_raises(error_type: type[BaseException], callback: Callable[[], Any]) -> BaseException:
    try:
        callback()
    except error_type as exc:
        return exc
    raise AssertionError(f"Expected {error_type.__name__} to be raised")


def _passthrough_prepare(_binding, params, additional_params):
    return params, additional_params


def _register_compatible_provider(**kwargs):
    kwargs.setdefault(
        "frozen_execution_version",
        chat_providers.FROZEN_EXECUTION_CAPABILITY_VERSION,
    )
    kwargs.setdefault("frozen_prepare_handler", _passthrough_prepare)
    kwargs.setdefault(
        "frozen_completion_handler",
        lambda _request, **_kwargs: "",
    )
    kwargs.setdefault(
        "frozen_stream_handler",
        lambda _request, **_kwargs: iter(()),
    )
    return chat_providers.register_provider(**kwargs)


def test_shipped_provider_template_negotiates_and_uses_frozen_execution_v1() -> None:
    template_path = ROOT_DIR / "docs" / "templates" / "chat_provider_addon" / "main.py"
    spec = importlib.util.spec_from_file_location(
        "nc_test_chat_provider_template",
        template_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    provider_id = module.PROVIDER_ID
    original_settings = chat_providers.get_provider_settings()
    calls: list[tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]] = []

    class ChatService:
        register_provider = staticmethod(chat_providers.register_provider)
        unregister_provider = staticmethod(chat_providers.unregister_provider)
        get_provider_setting = staticmethod(chat_providers.get_provider_setting)

    class Context:
        logger = SimpleNamespace(
            warning=lambda _message: None,
            info=lambda _message: None,
        )

        @staticmethod
        def get_service(name):
            return ChatService() if name == "qt.chat_providers" else None

    chat_providers.unregister_provider(provider_id)
    chat_providers.set_provider_settings(
        {
            provider_id: {
                "api_key": "captured-key",
                "base_url": "https://captured.example/v1",
            }
        }
    )
    addon = module.Addon()
    try:
        addon.initialize(Context())
        provider = chat_providers.get_provider(provider_id)
        assert provider is not None
        assert provider.normal_chat_available is True
        assert provider.frozen_execution_version == 1
        assert callable(provider.frozen_prepare_handler)
        assert callable(provider.frozen_completion_handler)
        assert callable(provider.frozen_stream_handler)
        assert callable(provider.frozen_private_config_getter)
        assert provider.frozen_public_config_fields == (
            "base_url",
            "provider_is_remote",
        )

        def complete(config, params, additional_params):
            calls.append(
                (
                    "complete",
                    dict(config),
                    dict(params),
                    dict(additional_params or {}),
                )
            )
            return "template completion"

        def stream(config, params, additional_params):
            calls.append(
                (
                    "stream",
                    dict(config),
                    dict(params),
                    dict(additional_params or {}),
                )
            )
            return iter(("template ", "stream"))

        addon._complete_provider_request = complete
        addon._stream_provider_request = stream
        runtime = ChatProviderRuntime(
            lambda: {
                "chat_provider": provider_id,
                "model_name": "captured-model",
                "chat_provider_generation_settings": {
                    provider_id: {
                        "temperature": 0.25,
                        "max_tokens": 64,
                    }
                },
            }
        )
        context = runtime.capture_frozen_context()
        chat_providers.set_provider_settings(
            {
                provider_id: {
                    "api_key": "changed-key",
                    "base_url": "https://changed.example/v1",
                }
            }
        )
        request = runtime.prepare_frozen_request(
            context,
            {
                "model": "live-model-must-not-win",
                "messages": [{"role": "user", "content": "hello"}],
                "temperature": 1.5,
                "max_tokens": 999,
            },
            {"route": "captured"},
        )

        assert runtime.complete_frozen(request) == "template completion"
        assert "".join(runtime.stream_frozen(request)) == "template stream"
        assert context.provider_config == {
            "base_url": "https://captured.example/v1",
            "provider_is_remote": True,
        }
        assert all(call[1]["api_key"] == "captured-key" for call in calls)
        assert all(
            call[1]["base_url"] == "https://captured.example/v1"
            for call in calls
        )
        assert all(call[2]["model"] == "captured-model" for call in calls)
        assert all(call[2]["temperature"] == 0.25 for call in calls)
        assert all(call[2]["max_tokens"] == 64 for call in calls)
        assert all(call[3] == {"route": "captured"} for call in calls)
    finally:
        addon.shutdown()
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)


def test_nested_state_is_immutable_and_copy_failures_are_closed() -> None:
    generation_fields = {"temperature": 0.25, "stop": ["first", "second"]}
    params = {
        "model": "model-a",
        "messages": [{"role": "user", "content": ["hello"]}],
    }
    additional_params = {"options": {"stop": ["done"]}}

    context = chat_providers.FrozenChatProviderContext(
        provider_name="freeze-immutable",
        model_name="model-a",
        generation_fields=generation_fields,
    )
    request = chat_providers.FrozenChatProviderRequest(
        context=context,
        params=params,
        additional_params=additional_params,
    )

    generation_fields["stop"].append("changed")
    params["messages"][0]["content"].append("changed")
    additional_params["options"]["stop"].append("changed")

    assert context.generation_fields["stop"] == ("first", "second")
    assert request.params["messages"][0]["content"] == ("hello",)
    assert request.additional_params["options"]["stop"] == ("done",)
    _assert_raises(TypeError, lambda: operator.setitem(context.generation_fields, "x", 1))

    class CopyResistantMutable:
        def __init__(self) -> None:
            self.values = []

        def __deepcopy__(self, _memo):
            return self

    resistant = CopyResistantMutable()
    error = _assert_raises(
        TypeError,
        lambda: chat_providers.FrozenChatProviderRequest(
            context=context,
            params={"unsupported": resistant},
        ),
    )
    assert "unsupported" in str(error).lower()


def test_private_frozen_config_hook_captures_once_and_stays_private() -> None:
    provider_id = "freeze-private-config"
    original_settings = chat_providers.get_provider_settings()
    calls: list[int] = []
    hook_value = {"anthropic_version": "2025-06-30", "nested": ["captured"]}

    def private_config() -> Mapping[str, Any]:
        calls.append(1)
        return hook_value

    try:
        provider = _register_compatible_provider(
            provider_id=provider_id,
            label="Private Config",
            frozen_private_config_getter=private_config,
            frozen_public_config_fields=("transport_mode",),
        )
        chat_providers.set_provider_settings({provider_id: {"transport_mode": "captured"}})
        context = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        ).capture_frozen_context()
        binding = context._binding
        assert binding is not None
        hook_value["nested"].append("changed")

        assert calls == [1]
        assert dict(context.provider_config) == {"transport_mode": "captured"}
        assert binding._provider_config_copy() == {
            "transport_mode": "captured",
            "anthropic_version": "2025-06-30",
            "nested": ["captured"],
        }
    finally:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)


def test_explicit_provider_config_bypasses_private_frozen_config_hook() -> None:
    provider_id = "freeze-explicit-private-config"
    calls: list[int] = []

    def private_config() -> Mapping[str, Any]:
        calls.append(1)
        return {"hook_value": "must-not-capture"}

    try:
        provider = _register_compatible_provider(
            provider_id=provider_id,
            label="Explicit Private Config",
            frozen_private_config_getter=private_config,
        )
        context = chat_providers.capture_frozen_provider_context(
            provider,
            model_name="model-a",
            provider_config={"explicit_value": "captured"},
        )
        binding = context._binding
        assert binding is not None
        assert calls == []
        assert binding._provider_config_copy() == {"explicit_value": "captured"}
    finally:
        chat_providers.unregister_provider(provider_id)


def test_private_frozen_config_hook_failures_are_redacted() -> None:
    provider_id = "freeze-private-config-failure"
    secret = "private-config-hook-secret"

    def raising_hook() -> Mapping[str, Any]:
        raise RuntimeError(secret)

    for hook in (raising_hook, lambda: secret):
        try:
            provider = _register_compatible_provider(
                provider_id=provider_id,
                label="Private Config Failure",
                frozen_private_config_getter=hook,
            )
            error = _assert_raises(
                chat_providers.FrozenChatProviderCaptureError,
                lambda: chat_providers.capture_frozen_provider_context(
                    provider,
                    model_name="model-a",
                ),
            )
            assert secret not in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None
            assert error.__suppress_context__ is True
            assert secret not in repr(
                (error, error.__cause__, error.__context__)
            )
        finally:
            chat_providers.unregister_provider(provider_id)


def test_qt_host_forwards_private_frozen_config_hook() -> None:
    captured: dict[str, Any] = {}
    hook = lambda: {"private_value": "captured"}
    original_register = chat_providers.register_provider
    module_names = ("PySide6", "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets")
    original_modules = {name: sys.modules.get(name) for name in module_names}
    original_host_module = sys.modules.pop("core.addons.qt_host_services", None)
    qt_module = types.ModuleType("PySide6")
    qt_core = types.ModuleType("PySide6.QtCore")
    qt_core.QObject = object
    qt_gui = types.ModuleType("PySide6.QtGui")
    qt_widgets = types.ModuleType("PySide6.QtWidgets")
    qt_module.QtCore = qt_core
    qt_module.QtGui = qt_gui
    qt_module.QtWidgets = qt_widgets
    sys.modules.update(
        {
            "PySide6": qt_module,
            "PySide6.QtCore": qt_core,
            "PySide6.QtGui": qt_gui,
            "PySide6.QtWidgets": qt_widgets,
        }
    )
    from core.addons.qt_host_services import QtChatProviderService

    def fake_register(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="bridge", to_summary=lambda: {"id": "bridge"})

    class Window:
        def _populate_chat_provider_combo(self, _provider_id=None) -> None:
            pass

    chat_providers.register_provider = fake_register
    try:
        summary = QtChatProviderService(Window()).register_provider(
            provider_id="bridge",
            label="Bridge",
            frozen_private_config_getter=hook,
            frozen_execution_version=1,
            normal_chat_capable=True,
        )
    finally:
        chat_providers.register_provider = original_register
        sys.modules.pop("core.addons.qt_host_services", None)
        if original_host_module is not None:
            sys.modules["core.addons.qt_host_services"] = original_host_module
        for name, module in original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    assert summary == {"id": "bridge"}
    assert captured["frozen_private_config_getter"] is hook
    assert captured["frozen_execution_version"] == 1
    assert captured["normal_chat_capable"] is True


def test_same_id_reregistration_cannot_change_captured_execution() -> None:
    provider_id = "freeze-reregister"
    original_settings = chat_providers.get_provider_settings()
    calls: list[tuple[str, int, str]] = []

    def first_prepare(binding, params, additional_params):
        config = binding._provider_config_copy()
        prepared = dict(params)
        prepared["prepared_by"] = "first"
        prepared["captured_endpoint"] = config["base_url"]
        return prepared, additional_params

    def first_complete(request, *, timeout=None, cancel_token=None) -> str:
        calls.append(("first-complete", id(request), request.params["prepared_by"]))
        return "first completion"

    def first_stream(request, *, timeout=None, cancel_token=None):
        calls.append(("first-stream", id(request), request.params["prepared_by"]))
        return iter(("first ", "stream"))

    def second_prepare(_binding, params, additional_params):
        prepared = dict(params)
        prepared["prepared_by"] = "second"
        return prepared, additional_params

    def second_complete(_request, *, timeout=None, cancel_token=None) -> str:
        return "second completion"

    def second_stream(_request, *, timeout=None, cancel_token=None):
        return iter(("second stream",))

    try:
        chat_providers.set_provider_settings({provider_id: {"transport_mode": "captured"}})
        _register_compatible_provider(
            provider_id=provider_id,
            label="First Registration",
            frozen_prepare_handler=first_prepare,
            frozen_completion_handler=first_complete,
            frozen_stream_handler=first_stream,
            base_url_getter=lambda: "https://first.invalid/v1",
            frozen_public_config_fields=("transport_mode",),
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        context = runtime.capture_frozen_context()

        _register_compatible_provider(
            provider_id=provider_id,
            label="Second Registration",
            frozen_prepare_handler=second_prepare,
            frozen_completion_handler=second_complete,
            frozen_stream_handler=second_stream,
            base_url_getter=lambda: "https://second.invalid/v1",
        )

        assert runtime.frozen_execution_available(context) is True
        assert runtime.frozen_execution_available(context, stream=True) is True
        request = runtime.prepare_frozen_request(
            context,
            {"model": "caller-model", "messages": [{"role": "user", "content": "hello"}]},
        )
        assert request.params["model"] == "model-a"
        assert request.params["prepared_by"] == "first"
        assert request.params["captured_endpoint"] == "https://first.invalid/v1"
        assert "".join(runtime.stream_frozen(request)) == "first stream"
        assert runtime.complete_frozen(request) == "first completion"
        assert calls == [
            ("first-stream", id(request), "first"),
            ("first-complete", id(request), "first"),
        ]
    finally:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)


def test_relay_off_capture_does_no_strict_work_and_relay_on_upgrade_is_explicit() -> None:
    provider_id = "freeze-strict-upgrade"
    capability_calls: list[tuple[str, str, str]] = []

    def capability(binding):
        config = binding._provider_config_copy()
        capability_calls.append(
            (binding.provider_name, binding.model_name, config["base_url"])
        )
        identity = binding.execution_identity
        return {
            "context_limit": 8192,
            "token_counter": lambda messages: len(list(messages)),
            "capability_identity": identity,
            "token_counter_identity": identity,
        }

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Strict Upgrade",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
            frozen_stream_handler=lambda _request, **_kwargs: iter(("ok",)),
            model_capabilities_handler=capability,
            token_counter=lambda _messages: (_ for _ in ()).throw(
                AssertionError("Relay-OFF must not call the registered counter")
            ),
            base_url_getter=lambda: "https://captured.invalid/v1",
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-exact"}
        )

        relay_off_context = runtime.capture_frozen_context()
        assert capability_calls == []
        assert runtime.strict_relay_capability_available(relay_off_context) is False

        _register_compatible_provider(
            provider_id=provider_id,
            label="Replacement Strict Upgrade",
            model_capabilities_handler=lambda _binding: (_ for _ in ()).throw(
                AssertionError("strict upgrade must use the captured capability hook")
            ),
        )

        relay_on_context = runtime.upgrade_frozen_context_for_relay(relay_off_context)
        assert capability_calls == [
            (provider_id, "model-exact", "https://captured.invalid/v1")
        ]
        assert relay_on_context is not relay_off_context
        assert runtime.strict_relay_capability_available(relay_off_context) is False
        assert runtime.strict_relay_capability_available(relay_on_context) is True
        assert relay_on_context.capabilities.context_limit == 8192
        assert chat_providers.count_frozen_chat_tokens(
            relay_on_context,
            [{"role": "user"}],
        ) == 1
    finally:
        chat_providers.unregister_provider(provider_id)


def test_strict_capability_is_attested_to_exact_core_binding() -> None:
    source_id = "freeze-identity-source"
    target_id = "freeze-identity-target"
    observed: dict[str, str] = {}

    arbitrary = chat_providers.FrozenChatProviderCapabilities(context_limit=4096)
    assert arbitrary.strict_relay_available is False

    def capability(binding):
        if binding.provider_name == source_id:
            identity = binding.execution_identity
            observed["source_identity"] = identity
        else:
            identity = observed["source_identity"]
        return {
            "context_limit": 8192,
            "token_counter": lambda messages: len(list(messages)),
            "capability_identity": identity,
            "token_counter_identity": identity,
        }

    try:
        for provider_id in (source_id, target_id):
            _register_compatible_provider(
                provider_id=provider_id,
                label=provider_id,
                frozen_prepare_handler=_passthrough_prepare,
                frozen_completion_handler=lambda _request, **_kwargs: "ok",
                model_capabilities_handler=capability,
            )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": source_id, "model_name": "live-model"}
        )
        source_context = runtime.capture_frozen_context(
            provider=source_id,
            model="source-model",
            provider_config={
                "base_url": "https://source.invalid/v1",
                "route": "source",
            },
            generation_fields={"temperature": 0.1},
        )
        target_context = runtime.capture_frozen_context(
            provider=target_id,
            model="target-model",
            provider_config={
                "base_url": "https://target.invalid/v2",
                "route": "target",
            },
            generation_fields={"temperature": 0.9},
        )

        source_upgraded = runtime.upgrade_frozen_context_for_relay(source_context)
        assert source_upgraded.strict_relay_available is True
        raw_identity = observed["source_identity"]
        assert raw_identity
        visible = " ".join(
            (
                repr(source_upgraded),
                repr(vars(source_upgraded)),
                repr(source_upgraded.capabilities),
                repr(source_upgraded.to_summary()),
                repr(source_upgraded.capabilities.to_summary()),
            )
        )
        assert raw_identity not in visible

        cross_bound = replace(
            target_context,
            capabilities=source_upgraded.capabilities,
        )
        assert cross_bound.strict_relay_available is False

        mismatch_error = _assert_raises(
            chat_providers.FrozenChatProviderCapabilityError,
            lambda: runtime.upgrade_frozen_context_for_relay(target_context),
        )
        assert raw_identity not in str(mismatch_error)
    finally:
        chat_providers.unregister_provider(source_id)
        chat_providers.unregister_provider(target_id)


def test_attested_token_counter_allows_unknown_dynamic_context_limit() -> None:
    provider_id = "synthetic-capacity-provider"

    def capability(binding):
        return {
            "context_limit": None,
            "token_counter": lambda messages: len(tuple(messages)),
            "capability_identity": binding.execution_identity,
            "token_counter_identity": binding.execution_identity,
        }

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Synthetic Capacity Provider",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
            model_capabilities_handler=capability,
        )
        runtime = ChatProviderRuntime(
            lambda: {
                "chat_provider": provider_id,
                "model_name": "opaque-model-zeta",
            }
        )
        context = runtime.upgrade_frozen_context_for_relay(
            runtime.capture_frozen_context()
        )

        assert context.strict_relay_available is True
        assert context.capabilities.context_limit is None
        assert chat_providers.count_frozen_chat_tokens(
            context,
            ({"role": "user"}, {"role": "assistant"}),
        ) == 2
    finally:
        chat_providers.unregister_provider(provider_id)


def test_credential_key_normalization_redacts_public_config() -> None:
    provider_id = "freeze-credential-keys"
    secret = "normalized-key-secret"
    original_settings = chat_providers.get_provider_settings()
    credential_fields = (
        "openai_api_key",
        "openaiApiKey",
        "openAIApiKey",
        "openAIAPIKey",
        "OpenAIApiKey",
        "OpenAIAPIKey",
        "OPENAI_API_KEY",
        "x_api_key",
        "x-api-key",
        "bearerToken",
    )

    try:
        settings = {field: secret for field in credential_fields}
        settings["safe_mode"] = "captured"
        chat_providers.set_provider_settings({provider_id: settings})
        _register_compatible_provider(
            provider_id=provider_id,
            label="Credential Keys",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
            frozen_public_config_fields=(*credential_fields, "safe_mode"),
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        context = runtime.capture_frozen_context()

        assert dict(context.provider_config) == {"safe_mode": "captured"}
        assert secret not in repr(context.provider_config)
    finally:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)


def test_structured_message_credentials_are_rejected_but_text_is_opaque() -> None:
    provider_id = "freeze-structured-credentials"
    secret = "structured-message-secret"
    credential_fields = (
        "openai_api_key",
        "openaiApiKey",
        "openAIApiKey",
        "openAIAPIKey",
        "OpenAIApiKey",
        "OpenAIAPIKey",
        "OPENAI_API_KEY",
        "x_api_key",
        "x-api-key",
        "bearerToken",
    )

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Structured Credentials",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        context = runtime.capture_frozen_context()

        for field_name in credential_fields:
            error = _assert_raises(
                chat_providers.FrozenChatProviderPreparationError,
                lambda field_name=field_name: runtime.prepare_frozen_request(
                    context,
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "structured",
                                        "metadata": {field_name: secret},
                                    }
                                ],
                            }
                        ]
                    },
                ),
            )
            assert secret not in str(error)

        text = (
            "Discuss the literal fields api_key, openAIApiKey, and x-api-key "
            "and this text URL: "
            f"https://user:{secret}@example.invalid/?token={secret}"
        )
        request = runtime.prepare_frozen_request(
            context,
            {"messages": [{"role": "user", "content": text}]},
        )
        assert request.params["messages"][0]["content"] == text
    finally:
        chat_providers.unregister_provider(provider_id)


def test_capability_normalization_sanitizes_hostile_results() -> None:
    provider_id = "freeze-hostile-capability"
    secret = "hostile-capability-secret"
    mode = {"value": "mapping"}

    class HostileMapping(Mapping):
        def __getitem__(self, _key):
            raise RuntimeError(secret)

        def __iter__(self):
            return iter(("context_limit",))

        def __len__(self):
            return 1

    class HostileIdentity:
        def __str__(self) -> str:
            raise RuntimeError(secret)

    def capability(_binding):
        if mode["value"] == "mapping":
            return HostileMapping()
        return {
            "context_limit": 8192,
            "token_counter": lambda _messages: 0,
            "capability_identity": HostileIdentity(),
            "token_counter_identity": "unused",
        }

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Hostile Capability",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
            model_capabilities_handler=capability,
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        context = runtime.capture_frozen_context()

        for hostile_mode in ("mapping", "value"):
            mode["value"] = hostile_mode
            error = _assert_raises(
                chat_providers.FrozenChatProviderCapabilityError,
                lambda: runtime.upgrade_frozen_context_for_relay(context),
            )
            assert secret not in str(error)
            assert error.__cause__ is None
            assert error.__suppress_context__ is True
    finally:
        chat_providers.unregister_provider(provider_id)


def test_context_limit_is_validated_without_hostile_conversion() -> None:
    provider_id = "freeze-hostile-context-limit"
    secret = "hostile-context-limit-secret"
    values: list[Any] = [False, 0, -1, "8192"]
    selected = {"value": values[0]}
    counter_calls: list[int] = []
    conversion_calls: list[str] = []

    class HostileLimit:
        def __repr__(self) -> str:
            conversion_calls.append("repr")
            return secret

        def __str__(self) -> str:
            conversion_calls.append("str")
            raise RuntimeError(secret)

        def __int__(self) -> int:
            conversion_calls.append("int")
            raise RuntimeError(secret)

        def __index__(self) -> int:
            conversion_calls.append("index")
            raise RuntimeError(secret)

    def counter(_messages) -> int:
        counter_calls.append(1)
        return 0

    def capability(binding):
        return {
            "context_limit": selected["value"],
            "token_counter": counter,
            "capability_identity": binding.execution_identity,
            "token_counter_identity": binding.execution_identity,
        }

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Hostile Context Limit",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
            model_capabilities_handler=capability,
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        context = runtime.capture_frozen_context()
        identity = context._binding.execution_identity
        values.extend((identity, HostileLimit()))

        for value in values:
            selected["value"] = value
            error = _assert_raises(
                chat_providers.FrozenChatProviderCapabilityError,
                lambda: runtime.upgrade_frozen_context_for_relay(context),
            )
            assert secret not in str(error)
            assert identity not in str(error)
            assert error.__cause__ is None
            assert error.__suppress_context__ is True
            assert context.strict_relay_available is False

        assert counter_calls == []
        assert conversion_calls == []
    finally:
        chat_providers.unregister_provider(provider_id)


def test_counter_and_attestation_stay_in_private_capacity_binding() -> None:
    provider_id = "freeze-private-counter"
    counter_secret = "hostile-counter-repr-secret"
    observed: dict[str, str] = {}
    counter_calls: list[int] = []

    class HostileCounter:
        def __call__(self, messages) -> int:
            counter_calls.append(1)
            return len(list(messages))

        def __repr__(self) -> str:
            return counter_secret

    counter = HostileCounter()

    def capability(binding):
        observed["identity"] = binding.execution_identity
        return {
            "context_limit": 12288,
            "token_counter": counter,
            "capability_identity": binding.execution_identity,
            "token_counter_identity": binding.execution_identity,
        }

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Private Counter",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
            model_capabilities_handler=capability,
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        relay_off_context = runtime.capture_frozen_context()
        assert counter_calls == []

        context = runtime.upgrade_frozen_context_for_relay(relay_off_context)
        identity = observed["identity"]
        public_capability_vars = vars(context.capabilities)
        visible = " ".join(
            (
                repr(context.capabilities),
                repr(public_capability_vars),
                repr(vars(context)),
                repr(context.capabilities.to_summary()),
                repr(context.to_summary()),
            )
        )

        assert public_capability_vars == {
            "context_limit": 12288,
            "_strict_relay_available": True,
        }
        assert not any(callable(value) for value in public_capability_vars.values())
        assert counter_secret not in visible
        assert identity not in visible
        assert "object at 0x" not in repr(public_capability_vars)
        assert counter_calls == []
        assert chat_providers.count_frozen_chat_tokens(
            context,
            [{"role": "user"}, {"role": "assistant"}],
        ) == 2
        assert counter_calls == [1]
    finally:
        chat_providers.unregister_provider(provider_id)


def test_registered_counter_is_frozen_without_relay_off_invocation() -> None:
    provider_id = "freeze-counter-fallback"
    calls = {"captured": 0, "replacement": 0}

    def captured_counter(messages) -> int:
        calls["captured"] += 1
        return len(list(messages))

    def replacement_counter(_messages) -> int:
        calls["replacement"] += 1
        return 999

    def capability(binding):
        return {
            "context_limit": 16384,
            "capability_identity": binding.execution_identity,
            "token_counter_identity": binding.execution_identity,
        }

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Counter Fallback",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "ok",
            model_capabilities_handler=capability,
            token_counter=captured_counter,
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        relay_off_context = runtime.capture_frozen_context()
        assert calls == {"captured": 0, "replacement": 0}
        assert relay_off_context.strict_relay_available is False

        _register_compatible_provider(
            provider_id=provider_id,
            label="Replacement Counter",
            model_capabilities_handler=lambda _binding: (_ for _ in ()).throw(
                AssertionError("replacement capability hook must not run")
            ),
            token_counter=replacement_counter,
        )
        relay_on_context = runtime.upgrade_frozen_context_for_relay(relay_off_context)

        assert calls == {"captured": 0, "replacement": 0}
        assert relay_on_context.strict_relay_available is True
        assert chat_providers.count_frozen_chat_tokens(
            relay_on_context,
            [{"role": "user"}],
        ) == 1
        assert calls == {"captured": 1, "replacement": 0}
    finally:
        chat_providers.unregister_provider(provider_id)


def test_failed_capture_cannot_report_strict_available_or_leak_exception_secret() -> None:
    provider_id = "freeze-capture-failure"
    secret = "capture-error-secret"
    capability_calls: list[str] = []

    def failed_endpoint() -> str:
        raise RuntimeError(f"endpoint failed with {secret}")

    def capability(_binding):
        capability_calls.append("called")
        return {
            "context_limit": 4096,
            "token_counter": lambda _messages: 0,
            "capability_identity": "false-valid",
            "token_counter_identity": "false-valid",
        }

    for getter_name in ("api_key_getter", "base_url_getter"):
        try:
            _register_compatible_provider(
                provider_id=provider_id,
                label="Capture Failure",
                frozen_prepare_handler=_passthrough_prepare,
                frozen_completion_handler=lambda _request, **_kwargs: "ok",
                model_capabilities_handler=capability,
                **{getter_name: failed_endpoint},
            )
            runtime = ChatProviderRuntime(
                lambda: {"chat_provider": provider_id, "model_name": "model-a"}
            )
            error = _assert_raises(
                chat_providers.FrozenChatProviderCaptureError,
                runtime.capture_frozen_context,
            )
            assert secret not in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None
            assert error.__suppress_context__ is True
            assert secret not in repr(
                (error, error.__cause__, error.__context__)
            )
            assert capability_calls == []
        finally:
            chat_providers.unregister_provider(provider_id)


def test_secrets_exist_only_in_the_private_redacted_binding() -> None:
    provider_id = "freeze-secrets"
    api_secret = "api-secret-value"
    url_secret = "url-secret-value"
    original_settings = chat_providers.get_provider_settings()

    try:
        chat_providers.set_provider_settings(
            {
                provider_id: {
                    "transport_mode": "captured",
                    "auth_token": api_secret,
                    "safe_url": f"https://user:{url_secret}@example.invalid/v1?token={api_secret}",
                }
            }
        )
        _register_compatible_provider(
            provider_id=provider_id,
            label="Secret Capture",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: (_ for _ in ()).throw(
                RuntimeError(f"provider failed with {api_secret}")
            ),
            api_key_getter=lambda: api_secret,
            base_url_getter=lambda: f"https://user:{url_secret}@example.invalid/v1",
            frozen_public_config_fields=(
                "transport_mode",
                "auth_token",
                "safe_url",
                "api_key",
                "base_url",
            ),
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        context = runtime.capture_frozen_context()
        request = runtime.prepare_frozen_request(context, {"messages": []})

        assert dict(context.provider_config) == {"transport_mode": "captured"}
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
        assert api_secret not in visible
        assert url_secret not in visible
        assert "https://user:" not in visible
        assert "redacted" in repr(vars(context)).lower()

        serialization_error = _assert_raises(TypeError, lambda: pickle.dumps(context))
        assert api_secret not in str(serialization_error)
        credential_error = _assert_raises(
            chat_providers.FrozenChatProviderPreparationError,
            lambda: runtime.prepare_frozen_request(
                context,
                {"messages": []},
                {"api_key": api_secret},
            ),
        )
        assert api_secret not in str(credential_error)
        execution_error = _assert_raises(
            chat_providers.FrozenChatProviderExecutionError,
            lambda: runtime.complete_frozen(request),
        )
        assert api_secret not in str(execution_error)
    finally:
        chat_providers.unregister_provider(provider_id)
        chat_providers.set_provider_settings(original_settings)


def test_provider_sanitized_execution_error_remains_actionable() -> None:
    provider_id = "freeze-public-execution-error"
    detail = (
        "OpenAI request failed: Unsupported parameter: top_p is not supported "
        "with this model. (param=top_p, code=unsupported_parameter)"
    )

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Public Execution Error",
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: (
                (_ for _ in ()).throw(
                    chat_providers.FrozenChatProviderExecutionError(detail)
                )
            ),
            frozen_stream_handler=lambda _request, **_kwargs: (
                (_ for _ in ()).throw(
                    chat_providers.FrozenChatProviderExecutionError(detail)
                )
            ),
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        request = runtime.prepare_frozen_request(
            runtime.capture_frozen_context(),
            {"messages": []},
        )

        completion_error = _assert_raises(
            chat_providers.FrozenChatProviderExecutionError,
            lambda: runtime.complete_frozen(request),
        )
        stream_error = _assert_raises(
            chat_providers.FrozenChatProviderExecutionError,
            lambda: list(runtime.stream_frozen(request)),
        )
        assert str(completion_error) == detail
        assert str(stream_error) == detail
        assert completion_error.__cause__ is None
        assert stream_error.__cause__ is None
    finally:
        chat_providers.unregister_provider(provider_id)


def test_provider_prepare_runs_once_and_request_is_reused_for_fallback() -> None:
    provider_id = "freeze-prepare-once"
    prepare_calls: list[int] = []
    dispatch_ids: list[int] = []

    def prepare(_binding, params, additional_params):
        prepare_calls.append(1)
        prepared_params = dict(params)
        prepared_params["prepared"] = True
        prepared_additional = dict(additional_params)
        prepared_additional["adapter"] = "exact"
        return prepared_params, prepared_additional

    def stream(request, *, timeout=None, cancel_token=None):
        dispatch_ids.append(id(request))
        raise chat_providers.FrozenChatProviderUnsupportedError("stream unavailable")

    def complete(request, *, timeout=None, cancel_token=None) -> str:
        dispatch_ids.append(id(request))
        assert request.params["prepared"] is True
        assert request.additional_params["adapter"] == "exact"
        return "fallback completion"

    try:
        _register_compatible_provider(
            provider_id=provider_id,
            label="Prepare Once",
            frozen_prepare_handler=prepare,
            frozen_completion_handler=complete,
            frozen_stream_handler=stream,
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        context = runtime.capture_frozen_context()
        params = {"messages": [{"role": "user", "content": ["hello"]}]}
        additional_params = {"options": {"stop": ["done"]}}
        request = runtime.prepare_frozen_request(context, params, additional_params)

        params["messages"][0]["content"].append("changed")
        additional_params["options"]["stop"].append("changed")
        _assert_raises(
            chat_providers.FrozenChatProviderUnsupportedError,
            lambda: runtime.stream_frozen(request),
        )
        assert runtime.complete_frozen(request) == "fallback completion"
        assert prepare_calls == [1]
        assert dispatch_ids == [id(request), id(request)]
        assert request.params["messages"][0]["content"] == ("hello",)
        assert request.additional_params["options"]["stop"] == ("done",)
    finally:
        chat_providers.unregister_provider(provider_id)


def test_missing_frozen_hooks_are_unsupported_without_legacy_fallback() -> None:
    provider_id = "freeze-unsupported"
    legacy_calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def legacy_complete(params, additional_params) -> str:
        legacy_calls.append(("complete", params, additional_params))
        return "legacy completion"

    def legacy_stream(params, additional_params):
        legacy_calls.append(("stream", params, additional_params))
        return iter(("legacy stream",))

    try:
        legacy = chat_providers.register_provider(
            provider_id=provider_id,
            label="Freeze Unsupported",
            completion_handler=legacy_complete,
            stream_handler=legacy_stream,
        )
        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": provider_id, "model_name": "model-a"}
        )
        capture_error = _assert_raises(
            chat_providers.FrozenChatProviderUnsupportedError,
            runtime.capture_frozen_context,
        )
        assert "frozen_execution_version=1" in str(capture_error)
        assert legacy_calls == []
        direct_capture_error = _assert_raises(
            chat_providers.FrozenChatProviderUnsupportedError,
            lambda: chat_providers.capture_frozen_provider_context(
                legacy,
                model_name="model-a",
            ),
        )
        assert str(direct_capture_error) == str(capture_error)

        partial = chat_providers.register_provider(
            provider_id=provider_id,
            label="Freeze Prepare Only",
            frozen_execution_version=1,
            completion_handler=legacy_complete,
            stream_handler=legacy_stream,
            frozen_prepare_handler=_passthrough_prepare,
        )
        assert partial.normal_chat_available is False
        partial_error = _assert_raises(
            chat_providers.FrozenChatProviderUnsupportedError,
            runtime.capture_frozen_context,
        )
        assert "frozen_completion_handler" in str(partial_error)
        partial_direct_error = _assert_raises(
            chat_providers.FrozenChatProviderUnsupportedError,
            lambda: chat_providers.capture_frozen_provider_context(
                partial,
                model_name="model-a",
            ),
        )
        assert str(partial_direct_error) == str(partial_error)
        assert legacy_calls == []

        hidden = chat_providers.register_provider(
            provider_id=provider_id,
            label="Hidden Legacy Path",
            normal_chat_capable=False,
            completion_handler=legacy_complete,
            stream_handler=legacy_stream,
        )
        assert hidden.normal_chat_capable is False
        legacy_params = {
            "model": "legacy-model",
            "messages": [{"role": "user", "content": "hello"}],
        }
        legacy_additional = {"top_k": 17}
        assert chat_providers.complete_chat(provider_id, legacy_params, legacy_additional) == "legacy completion"
        assert "".join(chat_providers.stream_chat(provider_id, legacy_params, legacy_additional)) == "legacy stream"
        assert legacy_calls == [
            ("complete", legacy_params, legacy_additional),
            ("stream", legacy_params, legacy_additional),
        ]
    finally:
        chat_providers.unregister_provider(provider_id)


def test_registration_negotiates_frozen_normal_chat_before_provider_calls() -> None:
    legacy_id = "freeze-negotiation-legacy"
    compatible_id = "freeze-negotiation-compatible"
    hidden_id = "freeze-negotiation-hidden"
    provider_calls: list[str] = []

    def called(name: str):
        def handler(*_args, **_kwargs):
            provider_calls.append(name)
            if name == "models":
                return ["late-model"]
            if name == "connection":
                return {"ok": True, "detail": "late healthy"}
            if name == "stream":
                return iter(("late stream",))
            return "late completion"

        return handler

    try:
        legacy = chat_providers.register_provider(
            provider_id=legacy_id,
            label="Legacy Provider",
            model_list_handler=called("models"),
            completion_handler=called("legacy-completion"),
            stream_handler=called("legacy-stream"),
            connection_check_handler=called("connection"),
            frozen_private_config_getter=called("private-config"),
        )
        legacy_status = legacy.to_summary()["normal_chat"]
        assert legacy_status["available"] is False
        assert legacy_status["claimed"] is True
        assert legacy_status["required_frozen_execution_version"] == 1
        assert "frozen_execution_version=1" in legacy_status["message"]
        assert "frozen_prepare_handler" in legacy_status["message"]
        assert "frozen_completion_handler" in legacy_status["message"]
        assert "frozen_stream_handler" in legacy_status["message"]

        runtime = ChatProviderRuntime(
            lambda: {"chat_provider": legacy_id, "model_name": "model-a"}
        )
        error = _assert_raises(
            chat_providers.FrozenChatProviderUnsupportedError,
            runtime.capture_frozen_context,
        )
        assert legacy_status["message"] == str(error)
        assert chat_providers.list_models(legacy_id) == [legacy_status["message"]]
        assert chat_providers.check_connection(legacy_id) == {
            "ok": False,
            "detail": legacy_status["message"],
            "normal_chat_available": False,
        }
        assert provider_calls == []

        compatible = chat_providers.register_provider(
            provider_id=compatible_id,
            label="Compatible Provider",
            frozen_execution_version=1,
            frozen_prepare_handler=_passthrough_prepare,
            frozen_completion_handler=lambda _request, **_kwargs: "completed",
            frozen_stream_handler=lambda _request, **_kwargs: iter(("streamed",)),
        )
        compatible_status = compatible.to_summary()["normal_chat"]
        assert compatible_status == {
            "available": True,
            "claimed": True,
            "frozen_execution_version": 1,
            "required_frozen_execution_version": 1,
            "message": "Frozen normal-chat execution is available.",
        }
        compatible_runtime = ChatProviderRuntime(
            lambda: {"chat_provider": compatible_id, "model_name": "model-a"}
        )
        context = compatible_runtime.capture_frozen_context()
        request = compatible_runtime.prepare_frozen_request(context, {"messages": []})
        assert compatible_runtime.complete_frozen(request) == "completed"
        assert "".join(compatible_runtime.stream_frozen(request)) == "streamed"

        hidden = chat_providers.register_provider(
            provider_id=hidden_id,
            label="Hidden Legacy Path",
            normal_chat_capable=False,
            completion_handler=called("hidden-completion"),
        )
        hidden_status = hidden.to_summary()["normal_chat"]
        assert hidden_status["available"] is False
        assert hidden_status["claimed"] is False
        assert chat_providers.complete_chat(hidden_id, {}, {}) == "late completion"
        assert provider_calls == ["hidden-completion"]
    finally:
        chat_providers.unregister_provider(legacy_id)
        chat_providers.unregister_provider(compatible_id)
        chat_providers.unregister_provider(hidden_id)


def test_provider_selector_exposes_incompatible_registration() -> None:
    from ui.runtime.backend_chat_provider_selection import (
        BackendChatProviderSelectionMixin,
    )

    class Item:
        def __init__(self) -> None:
            self.enabled = True

        def setEnabled(self, enabled: bool) -> None:
            self.enabled = bool(enabled)

    class Combo:
        def __init__(self) -> None:
            self.rows: list[dict[str, Any]] = []
            self.current_index = -1

        def blockSignals(self, _blocked: bool) -> None:
            pass

        def clear(self) -> None:
            self.rows.clear()

        def addItem(self, label: str, provider_id: str) -> None:
            self.rows.append(
                {
                    "label": label,
                    "provider_id": provider_id,
                    "tooltip": "",
                    "item": Item(),
                }
            )

        def setItemData(self, index: int, value: Any, _role: Any) -> None:
            self.rows[index]["tooltip"] = value

        def model(self):
            return self

        def item(self, index: int):
            return self.rows[index]["item"]

        def findData(self, provider_id: str) -> int:
            for index, row in enumerate(self.rows):
                if row["provider_id"] == provider_id:
                    return index
            return -1

        def count(self) -> int:
            return len(self.rows)

        def setCurrentIndex(self, index: int) -> None:
            self.current_index = index

    reason = (
        "Legacy Provider is unavailable for normal chat. Update the provider addon "
        "to register frozen_execution_version=1."
    )

    class Harness(BackendChatProviderSelectionMixin):
        def __init__(self) -> None:
            self.chat_provider_combo = Combo()

        def _chat_provider_summaries(self):
            return [
                {
                    "id": "legacy-provider",
                    "label": "Legacy Provider",
                    "normal_chat": {"available": False, "message": reason},
                },
                {
                    "id": "compatible-provider",
                    "label": "Compatible Provider",
                    "normal_chat": {"available": True, "message": "available"},
                },
            ]

    harness = Harness()
    harness._populate_chat_provider_combo("legacy-provider")
    legacy_row = harness.chat_provider_combo.rows[0]
    compatible_row = harness.chat_provider_combo.rows[1]

    assert legacy_row["label"] == "Legacy Provider [Update required]"
    assert legacy_row["tooltip"] == reason
    assert legacy_row["item"].enabled is False
    assert compatible_row["label"] == "Compatible Provider"
    assert compatible_row["item"].enabled is True
    assert harness.chat_provider_combo.current_index == 0


if __name__ == "__main__":
    test_shipped_provider_template_negotiates_and_uses_frozen_execution_v1()
    test_nested_state_is_immutable_and_copy_failures_are_closed()
    test_private_frozen_config_hook_captures_once_and_stays_private()
    test_explicit_provider_config_bypasses_private_frozen_config_hook()
    test_private_frozen_config_hook_failures_are_redacted()
    test_qt_host_forwards_private_frozen_config_hook()
    test_same_id_reregistration_cannot_change_captured_execution()
    test_relay_off_capture_does_no_strict_work_and_relay_on_upgrade_is_explicit()
    test_strict_capability_is_attested_to_exact_core_binding()
    test_attested_token_counter_allows_unknown_dynamic_context_limit()
    test_credential_key_normalization_redacts_public_config()
    test_structured_message_credentials_are_rejected_but_text_is_opaque()
    test_capability_normalization_sanitizes_hostile_results()
    test_context_limit_is_validated_without_hostile_conversion()
    test_counter_and_attestation_stay_in_private_capacity_binding()
    test_registered_counter_is_frozen_without_relay_off_invocation()
    test_failed_capture_cannot_report_strict_available_or_leak_exception_secret()
    test_secrets_exist_only_in_the_private_redacted_binding()
    test_provider_sanitized_execution_error_remains_actionable()
    test_provider_prepare_runs_once_and_request_is_reused_for_fallback()
    test_missing_frozen_hooks_are_unsupported_without_legacy_fallback()
    test_registration_negotiates_frozen_normal_chat_before_provider_calls()
    test_provider_selector_exposes_incompatible_registration()
    print("chat provider freeze smoke checks passed.")
