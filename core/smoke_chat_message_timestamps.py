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


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_chat_message_builder_can_include_or_omit_timestamps():
    from core import conversation_history

    turn = {"role": "user", "content": "Hello there", "created_at": 1783202400.0}
    image_turn = {"role": "user", "content": "", "attachment_image_path": "runtime/example.png", "created_at": 1783202400.0}

    plain = conversation_history.build_chat_message_from_turn(
        turn,
        data_url_for_local_image=lambda _path: "",
        include_timestamp=False,
    )
    stamped = conversation_history.build_chat_message_from_turn(
        turn,
        data_url_for_local_image=lambda _path: "",
        include_timestamp=True,
    )

    assert plain == {"role": "user", "content": "Hello there"}
    assert stamped["role"] == "user"
    assert "Hello there" in stamped["content"]
    assert stamped["content"].startswith("[")
    assert "created_at" not in stamped["content"]

    stamped_image = conversation_history.build_chat_message_from_turn(
        image_turn,
        data_url_for_local_image=lambda _path: "data:image/png;base64,AAAA",
        include_timestamp=True,
    )
    assert isinstance(stamped_image["content"], list)
    assert stamped_image["content"][0]["type"] == "text"
    assert stamped_image["content"][0]["text"].startswith("[")


def test_engine_stamps_and_preserves_chat_turn_created_at():
    addons_module = types.ModuleType("addons")
    addons_module.__path__ = [str(ROOT / "addons")]
    sys.modules["addons"] = addons_module
    import addons.vam_avatar.config  # noqa: F401 - prime repo namespace for engine bootstrap imports

    import engine

    original_history = list(engine.conversation_history or [])
    try:
        engine.conversation_history[:] = []
        engine._append_chat_turn({"role": "user", "content": "Stamped"})
        assert isinstance(engine.conversation_history[0].get("created_at"), float)

        saved = engine.export_chat_session_state()
        assert isinstance(saved["conversation_history"][0].get("created_at"), float)

        engine.replace_chat_conversation_history(
            [{"role": "assistant", "content": "Preserved", "created_at": 1234.5}],
            allow_pending_loaded_user=False,
        )
        assert engine.conversation_history[0]["created_at"] == 1234.5
    finally:
        engine.conversation_history[:] = original_history


def test_chat_timestamp_ui_preference_wiring_exists():
    session = _read("ui/runtime/main_window_session.py")
    panel = _read("ui/runtime/backend_operational_panel.py")
    console = _read("ui/runtime/backend_console_chat.py")
    bindings = _read("ui/runtime/real_ui_bindings.py")
    mirrors = _read("ui/runtime/real_ui_sync_mirrors.py")
    real_ui = _read("main.ui")

    assert "chat_message_timestamps_enabled" in session
    assert "chat_timestamp_toggle_button" in panel
    assert "chat_timestamp_toggle_button" in real_ui
    assert "toggle_chat_message_timestamps" in console
    assert "chat_message_timestamps_enabled" in console
    assert "chat_timestamp_toggle_button" in bindings
    assert "chat_timestamp_toggle_button" in mirrors


if __name__ == "__main__":
    test_chat_message_builder_can_include_or_omit_timestamps()
    test_engine_stamps_and_preserves_chat_turn_created_at()
    test_chat_timestamp_ui_preference_wiring_exists()
    print("smoke_chat_message_timestamps: ok")
