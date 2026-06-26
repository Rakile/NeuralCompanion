"""Smoke checks for LM Studio chat-model lifecycle decisions."""

from __future__ import annotations

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
    addons_module = types.ModuleType("addons")
    addons_module.__path__ = [os.path.join(ROOT_DIR, "addons")]
    sys.modules["addons"] = addons_module
    import addons.vam_avatar.config  # noqa: F401 - prime repo namespace for engine bootstrap imports

    import engine

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


if __name__ == "__main__":
    test_lmstudio_startup_unloads_before_loading_selected_model()
    test_lmstudio_model_switch_unloads_old_model_before_loading_new_model()
    test_non_lmstudio_provider_skips_lifecycle_actions()
    test_engine_chat_completion_prepares_lmstudio_model_before_request()
    print("LM Studio chat lifecycle smoke checks passed.")
