from pathlib import Path

from ui.runtime.backend_chat_session_runtime import _format_long_term_memory_archive_progress


ROOT = Path(__file__).resolve().parents[1]


def _text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def main() -> int:
    expected = {
        168: "Archived messages: 168/168. Unarchived messages: 0. Messages until next archive: 4",
        169: "Archived messages: 168/169. Unarchived messages: 1. Messages until next archive: 3",
        170: "Archived messages: 168/170. Unarchived messages: 2. Messages until next archive: 2",
        171: "Archived messages: 168/171. Unarchived messages: 3. Messages until next archive: 1",
    }
    for total_turns, expected_text in expected.items():
        actual = _format_long_term_memory_archive_progress(
            archived_through=168,
            total_turns=total_turns,
            archive_interval=4,
            auto_archive_enabled=True,
        )
        assert actual == expected_text, f"unexpected pending archive progress at {total_turns}: {actual!r}"

    assert _format_long_term_memory_archive_progress(
        archived_through=172,
        total_turns=172,
        archive_interval=4,
        auto_archive_enabled=True,
    ) == "Archived messages: 172/172. Unarchived messages: 0. Messages until next archive: 4"
    assert _format_long_term_memory_archive_progress(
        archived_through=172,
        total_turns=174,
        archive_interval=4,
        auto_archive_enabled=True,
    ) == "Archived messages: 172/174. Unarchived messages: 2. Messages until next archive: 2"
    assert _format_long_term_memory_archive_progress(
        archived_through=176,
        total_turns=176,
        archive_interval=4,
        auto_archive_enabled=True,
    ) == "Archived messages: 176/176. Unarchived messages: 0. Messages until next archive: 4"

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
    assert "_refresh_long_term_memory_archive_progress_hint" in chat_status_body, (
        "chat status refresh must update lightweight Long-Term Memory archive progress"
    )
    assert "_refresh_long_term_memory_archive_hint" not in chat_status_body, (
        "per-line chat status updates must not scan the Long-Term Memory SQLite archive on the Qt thread"
    )

    print("long term memory archive status PoC: per_line_heavy_archive_refresh_calls=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
