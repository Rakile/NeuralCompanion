from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_session_restore_remembers_last_chat_without_activating_memory() -> None:
    source = _text("ui/runtime/main_window_session.py")
    startup_source = _text("ui/runtime/main_window_startup.py")
    assert '"last_chat_context_path"' in source
    assert '"last_chat_context_name"' in source
    assert "def _maybe_prompt_resume_last_chat_context" in source
    assert "self._maybe_prompt_resume_last_chat_context" in startup_source
    assert "Load Previous Chat Session" in source
    assert "reset_chat_session" in source

    restore_start = source.index("self._restore_ai_presence_session_settings(session)")
    restore_end = source.index("continuity_memory_enabled = session.get", restore_start)
    restore_block = source[restore_start:restore_end]
    forbidden = (
        'update_runtime_config("continuity_memory_id"',
        'update_runtime_config("active_chat_context_path"',
        'update_runtime_config("active_chat_context_name"',
    )
    for marker in forbidden:
        assert marker not in restore_block
    assert "_last_chat_context_path" in restore_block
    assert "_last_chat_context_name" in restore_block


def test_load_paths_share_one_loader_and_dialog_uses_last_chat_context() -> None:
    source = _text("ui/runtime/backend_console_chat.py")
    assert "def _load_chat_context_from_path" in source
    assert "_last_chat_context_path" in source
    assert "Load Chat Context" in source
    assert "open_file(" in source
    assert "self._load_chat_context_from_path(path)" in source


def test_memory_hint_labels_unsaved_when_no_active_chat_context() -> None:
    source = _text("ui/runtime/backend_chat_session_runtime.py")
    assert 'active_path = str(config.get("active_chat_context_path"' in source
    assert 'target = active_name if active_path else "unsaved chat"' in source


if __name__ == "__main__":
    test_session_restore_remembers_last_chat_without_activating_memory()
    test_load_paths_share_one_loader_and_dialog_uses_last_chat_context()
    test_memory_hint_labels_unsaved_when_no_active_chat_context()
    print("smoke_chat_context_session_restore_safety: ok")
