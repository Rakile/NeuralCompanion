from __future__ import annotations

import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))

addons_module = types.ModuleType("addons")
addons_module.__path__ = [str(ROOT / "addons")]
sys.modules["addons"] = addons_module
import addons.vam_avatar.config  # noqa: F401 - prime repo namespace for engine bootstrap imports

import engine


def test_replace_rejects_stale_expected_history() -> None:
    original_history = list(engine.conversation_history)
    original_limit = engine.RUNTIME_CONFIG.get("stored_chat_history_limit")
    try:
        current = [{"role": "user", "content": "newer message", "origin": "input"}]
        engine.conversation_history = list(current)
        result = engine.replace_chat_conversation_history(
            [{"role": "user", "content": "edited message", "origin": "input"}],
            allow_pending_loaded_user=False,
            expected_history=[{"role": "user", "content": "old message", "origin": "input"}],
        )
        assert result["replaced"] is False
        assert result["reason"] == "history_changed"
        assert engine.conversation_history == current
    finally:
        engine.conversation_history = original_history
        engine.RUNTIME_CONFIG["stored_chat_history_limit"] = original_limit


def test_replace_accepts_matching_expected_history() -> None:
    original_history = list(engine.conversation_history)
    original_limit = engine.RUNTIME_CONFIG.get("stored_chat_history_limit")
    try:
        current = [{"role": "user", "content": "old message", "origin": "input"}]
        engine.conversation_history = list(current)
        result = engine.replace_chat_conversation_history(
            [{"role": "user", "content": "edited message", "origin": "input"}],
            allow_pending_loaded_user=False,
            expected_history=current,
        )
        assert result["replaced"] is True
        assert engine.conversation_history[0]["content"] == "edited message"
    finally:
        engine.conversation_history = original_history
        engine.RUNTIME_CONFIG["stored_chat_history_limit"] = original_limit


if __name__ == "__main__":
    test_replace_rejects_stale_expected_history()
    test_replace_accepts_matching_expected_history()
    print("smoke_chat_history_atomic_replace: ok")
