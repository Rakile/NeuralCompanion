"""Smoke checks for LM Studio chat-model lifecycle decisions."""

from __future__ import annotations

import copy
import os
import sys
import types

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core import lmstudio_runtime


def _load_engine():
    addons_module = types.ModuleType("addons")
    addons_module.__path__ = [os.path.join(ROOT_DIR, "addons")]
    sys.modules["addons"] = addons_module
    import addons.vam_avatar.config  # noqa: F401 - prime repo namespace for engine bootstrap imports

    import engine

    return engine


def test_lmstudio_startup_unloads_before_loading_selected_model():
    calls = []
    ready, active = lmstudio_runtime.prepare_chat_model_lifecycle(
        "lmstudio",
        "demo-model",
        active_model_name="",
        unload_func=lambda reason="": calls.append(("unload", reason)) or True,
        load_func=lambda model_name: calls.append(("load", model_name)) or True,
        reason="LM Studio chat startup",
    )

    assert ready is True
    assert active == "demo-model"
    assert calls == [("unload", "LM Studio chat startup"), ("load", "demo-model")]


def test_lmstudio_model_switch_unloads_old_model_before_loading_new_model():
    calls = []
    ready, active = lmstudio_runtime.prepare_chat_model_lifecycle(
        "lmstudio",
        "new-model",
        active_model_name="old-model",
        unload_func=lambda reason="": calls.append(("unload", reason)) or True,
        load_func=lambda model_name: calls.append(("load", model_name)) or True,
        reason="LM Studio model switch",
    )

    assert ready is True
    assert active == "new-model"
    assert calls == [("unload", "LM Studio model switch"), ("load", "new-model")]


def test_lmstudio_same_active_model_skips_lifecycle_actions():
    calls = []
    ready, active = lmstudio_runtime.prepare_chat_model_lifecycle(
        "lmstudio",
        "demo-model",
        active_model_name="demo-model",
        unload_func=lambda reason="": calls.append(("unload", reason)) or True,
        load_func=lambda model_name: calls.append(("load", model_name)) or True,
        reason="LM Studio model switch",
    )

    assert ready is True
    assert active == "demo-model"
    assert calls == []


def test_non_lmstudio_provider_skips_lifecycle_actions():
    calls = []
    ready, active = lmstudio_runtime.prepare_chat_model_lifecycle(
        "openai",
        "demo-model",
        active_model_name="old-model",
        unload_func=lambda reason="": calls.append(("unload", reason)) or True,
        load_func=lambda model_name: calls.append(("load", model_name)) or True,
        reason="LM Studio chat startup",
    )

    assert ready is True
    assert active == "old-model"
    assert calls == []


def test_engine_chat_completion_prepares_lmstudio_model_before_request():
    engine = _load_engine()

    calls = []
    runtime_snapshot = dict(engine.RUNTIME_CONFIG)
    original_runtime = engine._chat_runtime
    original_prepare = engine.prepare_lmstudio_chat_model_for_runtime
    try:
        engine.RUNTIME_CONFIG.update({"chat_provider": "lmstudio", "model_name": "new-model"})

        class FakeChatRuntime:
            def current_provider(self, provider=None):
                return "lmstudio"

            def complete(self, params, additional_params=None):
                calls.append(("complete", params.get("model")))
                return "ok"

            def stream(self, params, additional_params=None):
                calls.append(("stream", params.get("model")))
                return iter(["ok"])

        engine._chat_runtime = FakeChatRuntime()
        engine.prepare_lmstudio_chat_model_for_runtime = (
            lambda provider=None, model=None, **kwargs: calls.append(("prepare", provider, model, kwargs.get("reason"))) or True
        )

        assert engine._chat_completion_create({"model": "new-model", "messages": []}, {}) == "ok"
        assert calls == [("prepare", "lmstudio", "new-model", "LM Studio model switch"), ("complete", "new-model")]
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(runtime_snapshot)
        engine._chat_runtime = original_runtime
        engine.prepare_lmstudio_chat_model_for_runtime = original_prepare


def test_engine_lmstudio_coalesces_system_messages_for_complete_and_stream():
    engine = _load_engine()
    captured = []
    original_messages = [
        {"role": "system", "content": "base persona"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
            ],
        },
        {"role": "system", "content": "orb guidance"},
        {"role": "assistant", "content": "prior reply"},
        {"role": "system", "content": "memory guidance"},
    ]
    original_params = {"model": "strict-model", "messages": original_messages}
    original_snapshot = copy.deepcopy(original_params)
    expected_non_system = [original_messages[1], original_messages[3]]
    runtime_snapshot = dict(engine.RUNTIME_CONFIG)
    original_runtime = engine._chat_runtime
    original_prepare = engine.prepare_lmstudio_chat_model_for_runtime
    try:
        engine.RUNTIME_CONFIG.update({"chat_provider": "lmstudio", "model_name": "strict-model"})

        class FakeChatRuntime:
            def current_provider(self, provider=None):
                return "lmstudio"

            def complete(self, params, additional_params=None):
                captured.append(("complete", params))
                return "ok"

            def stream(self, params, additional_params=None):
                captured.append(("stream", params))
                return iter(["ok"])

        engine._chat_runtime = FakeChatRuntime()
        engine.prepare_lmstudio_chat_model_for_runtime = lambda *args, **kwargs: True

        assert engine._chat_completion_create(original_params, {}) == "ok"
        assert list(engine._chat_completion_create(original_params, {}, stream=True)) == ["ok"]

        assert [kind for kind, _params in captured] == ["complete", "stream"]
        for _kind, sent_params in captured:
            assert [message["role"] for message in sent_params["messages"]] == ["system", "user", "assistant"]
            assert sent_params["messages"][0]["content"] == (
                "base persona\n\norb guidance\n\nmemory guidance"
            )
            assert sent_params["messages"][1:] == expected_non_system
        assert original_params == original_snapshot
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(runtime_snapshot)
        engine._chat_runtime = original_runtime
        engine.prepare_lmstudio_chat_model_for_runtime = original_prepare


def test_engine_lmstudio_merges_consecutive_main_chat_roles_and_preserves_multimodal_order():
    engine = _load_engine()
    captured = []
    image_part = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}
    original_messages = [
        {"role": "system", "content": "base persona"},
        {"role": "user", "content": "before image"},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "inspect this"},
                image_part,
            ],
        },
        {"role": "system", "content": "orb, spotify, and buddy context"},
        {"role": "user", "content": "after image"},
        {"role": "assistant", "content": "first assistant fragment"},
        {"role": "assistant", "content": "second assistant fragment"},
        {"role": "user", "content": "current turn"},
    ]
    original_params = {"model": "strict-model", "messages": original_messages}
    original_snapshot = copy.deepcopy(original_params)
    runtime_snapshot = dict(engine.RUNTIME_CONFIG)
    original_runtime = engine._chat_runtime
    original_prepare = engine.prepare_lmstudio_chat_model_for_runtime
    try:
        engine.RUNTIME_CONFIG.update({"chat_provider": "lmstudio", "model_name": "strict-model"})

        class FakeChatRuntime:
            def current_provider(self, provider=None):
                return "lmstudio"

            def complete(self, params, additional_params=None):
                captured.append(("complete", params))
                return "ok"

            def stream(self, params, additional_params=None):
                captured.append(("stream", params))
                return iter(["ok"])

        engine._chat_runtime = FakeChatRuntime()
        engine.prepare_lmstudio_chat_model_for_runtime = lambda *args, **kwargs: True

        assert engine._chat_completion_create(original_params, {}) == "ok"
        assert list(engine._chat_completion_create(original_params, {}, stream=True)) == ["ok"]

        assert [kind for kind, _params in captured] == ["complete", "stream"]
        for _kind, sent_params in captured:
            assert [message["role"] for message in sent_params["messages"]] == [
                "system",
                "user",
                "assistant",
                "user",
            ]
            assert sent_params["messages"][0]["content"] == (
                "base persona\n\norb, spotify, and buddy context"
            )
            assert sent_params["messages"][1]["content"] == [
                {"type": "text", "text": "before image"},
                {"type": "text", "text": "inspect this"},
                image_part,
                {"type": "text", "text": "after image"},
            ]
            assert sent_params["messages"][2]["content"] == (
                "first assistant fragment\n\nsecond assistant fragment"
            )
            assert sent_params["messages"][3] == {"role": "user", "content": "current turn"}
        assert original_params == original_snapshot
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(runtime_snapshot)
        engine._chat_runtime = original_runtime
        engine.prepare_lmstudio_chat_model_for_runtime = original_prepare


def test_engine_lmstudio_reuses_normal_chat_leading_assistant_repair():
    engine = _load_engine()
    captured = []
    original_params = {
        "model": "strict-model",
        "messages": [
            {"role": "system", "content": "base persona"},
            {"role": "assistant", "content": "orphaned assistant reply"},
            {"role": "user", "content": "current turn"},
        ],
    }
    original_snapshot = copy.deepcopy(original_params)
    runtime_snapshot = dict(engine.RUNTIME_CONFIG)
    original_runtime = engine._chat_runtime
    original_prepare = engine.prepare_lmstudio_chat_model_for_runtime
    try:
        engine.RUNTIME_CONFIG.update({"chat_provider": "lmstudio", "model_name": "strict-model"})

        class FakeChatRuntime:
            def current_provider(self, provider=None):
                return "lmstudio"

            def complete(self, params, additional_params=None):
                captured.append(params)
                return "ok"

        engine._chat_runtime = FakeChatRuntime()
        engine.prepare_lmstudio_chat_model_for_runtime = lambda *args, **kwargs: True

        assert engine._chat_completion_create(original_params, {}) == "ok"
        assert [message["role"] for message in captured[0]["messages"]] == ["system", "user"]
        assert captured[0]["messages"][1] == {"role": "user", "content": "current turn"}
        assert original_params == original_snapshot
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(runtime_snapshot)
        engine._chat_runtime = original_runtime
        engine.prepare_lmstudio_chat_model_for_runtime = original_prepare


def test_engine_non_lmstudio_preserves_system_message_payload():
    engine = _load_engine()
    captured = []
    original_params = {
        "model": "cloud-model",
        "messages": [
            {"role": "system", "content": "base"},
            {"role": "system", "content": "extra"},
            {"role": "user", "content": "hello"},
        ],
    }
    runtime_snapshot = dict(engine.RUNTIME_CONFIG)
    original_runtime = engine._chat_runtime
    original_ensure = engine._ensure_chat_provider_model_ready
    try:
        engine.RUNTIME_CONFIG.update({"chat_provider": "xai", "model_name": "cloud-model"})

        class FakeChatRuntime:
            def current_provider(self, provider=None):
                return "xai"

            def complete(self, params, additional_params=None):
                captured.append(params)
                return "ok"

        engine._chat_runtime = FakeChatRuntime()
        engine._ensure_chat_provider_model_ready = lambda provider, model: True

        assert engine._chat_completion_create(original_params, {}) == "ok"
        assert captured == [original_params]
        assert captured[0] is original_params
    finally:
        engine.RUNTIME_CONFIG.clear()
        engine.RUNTIME_CONFIG.update(runtime_snapshot)
        engine._chat_runtime = original_runtime
        engine._ensure_chat_provider_model_ready = original_ensure


if __name__ == "__main__":
    test_lmstudio_startup_unloads_before_loading_selected_model()
    test_lmstudio_model_switch_unloads_old_model_before_loading_new_model()
    test_lmstudio_same_active_model_skips_lifecycle_actions()
    test_non_lmstudio_provider_skips_lifecycle_actions()
    test_engine_chat_completion_prepares_lmstudio_model_before_request()
    test_engine_lmstudio_coalesces_system_messages_for_complete_and_stream()
    test_engine_lmstudio_merges_consecutive_main_chat_roles_and_preserves_multimodal_order()
    test_engine_lmstudio_reuses_normal_chat_leading_assistant_repair()
    test_engine_non_lmstudio_preserves_system_message_payload()
    print("LM Studio chat lifecycle smoke checks passed.")
