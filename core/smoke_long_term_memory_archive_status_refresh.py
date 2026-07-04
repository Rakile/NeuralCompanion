from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main() -> int:
    backend_runtime = _text("ui/runtime/backend_chat_session_runtime.py")
    alias_start = backend_runtime.index("def _refresh_long_term_memory_hint")
    alias_end = backend_runtime.index("def _refresh_long_term_memory_archive_hint", alias_start)
    alias_body = backend_runtime[alias_start:alias_end]
    assert "_refresh_continuity_memory_hint" in alias_body, "long-term memory hint alias must update Conversation Memory status"
    assert "_refresh_long_term_memory_archive_hint" in alias_body, "long-term memory hint alias must update Long-Term Memory archive status"

    frontend_actions = _text("ui/runtime/real_ui_actions_chat_sensory.py")
    refresh_start = frontend_actions.index("def _refresh_chat_session_runtime_frontend")
    refresh_end = frontend_actions.index("def _on_frontend_allow_proactive_changed", refresh_start)
    refresh_body = frontend_actions[refresh_start:refresh_end]

    assert "_refresh_long_term_memory_hint" in refresh_body, "frontend runtime refresh must update Conversation Memory status"
    assert "_refresh_long_term_memory_archive_hint" in refresh_body, "frontend runtime refresh must update Long-Term Memory archive status"

    backend_console = _text("ui/runtime/backend_console_chat.py")
    chat_status_start = backend_console.index("def _update_chat_status")
    chat_status_end = backend_console.index("def toggle_console_autoscroll", chat_status_start)
    chat_status_body = backend_console[chat_status_start:chat_status_end]
    assert "_refresh_continuity_memory_hint" in chat_status_body, "chat status refresh must update Conversation Memory status"
    assert "_refresh_long_term_memory_archive_hint" in chat_status_body, "chat status refresh must update Long-Term Memory archive status"

    print("long term memory archive status refresh smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
