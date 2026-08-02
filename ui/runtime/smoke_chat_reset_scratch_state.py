from __future__ import annotations

from ui.runtime import backend_console_chat


class _Checkbox:
    def __init__(self) -> None:
        self.checked = True

    def setChecked(self, value) -> None:
        self.checked = bool(value)


class _Engine:
    def __init__(self) -> None:
        self.RUNTIME_CONFIG = {
            "active_chat_context_path": "runtime/chat_contexts/loaded.json",
            "active_chat_context_name": "loaded",
            "continuity_memory_id": "loaded",
            "long_term_memory_db_path": "runtime/long_term_memory/loaded.sqlite3",
            "long_term_memory_db_id": "loaded",
            "quick_chat_context_active": False,
            "continuity_memory_enabled": True,
            "continuity_memory_auto_summarize": True,
            "continuity_memory_update_on_save": True,
            "continuity_memory_inject": True,
            "long_term_memory_retrieval_enabled": True,
            "long_term_memory_embedding_enabled": True,
        }

    def reset_session_state(self) -> None:
        self.RUNTIME_CONFIG.update(
            {
                "active_chat_context_path": "",
                "active_chat_context_name": "",
                "continuity_memory_id": "fresh-memory",
                "long_term_memory_db_path": "runtime/long_term_memory/fresh.sqlite3",
                "long_term_memory_db_id": "fresh-memory",
                "quick_chat_context_active": False,
            }
        )


class _Backend(backend_console_chat.BackendConsoleChatMixin):
    def __init__(self) -> None:
        self.clear_count = 0
        self.save_control_refreshes = 0
        self.continuity_hint_refreshes = 0
        self.archive_hint_refreshes = 0
        for name in (
            "long_term_memory_enabled_checkbox",
            "long_term_memory_update_on_save_checkbox",
            "long_term_memory_inject_checkbox",
            "long_term_memory_retrieval_enabled_checkbox",
            "long_term_memory_embedding_enabled_checkbox",
        ):
            setattr(self, name, _Checkbox())

    def clear_chat(self) -> None:
        self.clear_count += 1

    def _refresh_chat_context_save_controls(self) -> None:
        self.save_control_refreshes += 1

    def _refresh_continuity_memory_hint(self) -> None:
        self.continuity_hint_refreshes += 1

    def _refresh_long_term_memory_archive_hint(self) -> None:
        self.archive_hint_refreshes += 1


def test_restart_current_conversation_enters_scratch_chat_state() -> None:
    fake_engine = _Engine()
    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: fake_engine
    try:
        backend = _Backend()
        backend.reset_chat_session()

        config = fake_engine.RUNTIME_CONFIG
        assert config["quick_chat_context_active"] is True
        assert config["active_chat_context_path"] == ""
        assert config["active_chat_context_name"] == ""
        assert config["continuity_memory_id"] == ""
        assert config["long_term_memory_db_path"] == ""
        assert config["long_term_memory_db_id"] == ""
        assert config["continuity_memory_enabled"] is False
        assert config["continuity_memory_auto_summarize"] is False
        assert config["continuity_memory_update_on_save"] is False
        assert config["continuity_memory_inject"] is False
        assert config["long_term_memory_retrieval_enabled"] is False
        assert config["long_term_memory_embedding_enabled"] is False
        assert backend.clear_count == 1
        assert backend.continuity_hint_refreshes >= 1
        assert backend.archive_hint_refreshes >= 1
        for name in (
            "long_term_memory_enabled_checkbox",
            "long_term_memory_update_on_save_checkbox",
            "long_term_memory_inject_checkbox",
            "long_term_memory_retrieval_enabled_checkbox",
            "long_term_memory_embedding_enabled_checkbox",
        ):
            assert getattr(backend, name).checked is False
    finally:
        backend_console_chat._engine = original_engine


if __name__ == "__main__":
    test_restart_current_conversation_enters_scratch_chat_state()
    print("smoke_chat_reset_scratch_state: ok")
