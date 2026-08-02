from __future__ import annotations

from ui.runtime import backend_console_chat, main_window_startup


class _Engine:
    def __init__(self) -> None:
        self.conversation_history = []
        self.RUNTIME_CONFIG = {}
        self.reset_count = 0

    def reset_session_state(self) -> None:
        self.reset_count += 1
        self.conversation_history = []


class _Backend(backend_console_chat.BackendConsoleChatMixin):
    def __init__(self, engine) -> None:
        self.engine = engine
        self.decisions = []
        self.save_results = []
        self.save_exception = None
        self.save_count = 0
        self.clear_count = 0
        self._mark_chat_context_history_saved()

    def _prompt_unsaved_chat_context_decision(self, action_label):
        assert action_label
        return self.decisions.pop(0)

    def save_chat_context(self):
        self.save_count += 1
        if self.save_exception is not None:
            raise self.save_exception
        result = self.save_results.pop(0) if self.save_results else True
        if result:
            self._mark_chat_context_history_saved()
        return result

    def clear_chat(self) -> None:
        self.clear_count += 1

    def _detach_active_chat_context_path(self) -> None:
        return None

    def _disable_memory_for_quick_chat_context(self) -> None:
        return None

    def _refresh_chat_context_save_controls(self) -> None:
        return None


class _CloseBase:
    def closeEvent(self, event) -> None:
        event.base_close_count += 1


class _CloseBackend(main_window_startup.MainWindowStartupMixin, _CloseBase):
    def _confirm_unsaved_chat_context(self, action_label) -> bool:
        assert action_label == "exiting Neural Companion"
        return False


class _CloseEvent:
    def __init__(self) -> None:
        self.ignore_count = 0
        self.base_close_count = 0

    def ignore(self) -> None:
        self.ignore_count += 1


def test_dirty_state_tracks_history_since_last_successful_save() -> None:
    fake_engine = _Engine()
    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: fake_engine
    try:
        backend = _Backend(fake_engine)
        assert backend._chat_context_has_unsaved_history() is False

        fake_engine.conversation_history.append({"role": "user", "content": "Hello"})
        assert backend._chat_context_has_unsaved_history() is True

        backend._mark_chat_context_history_saved()
        assert backend._chat_context_has_unsaved_history() is False

        fake_engine.conversation_history[0]["content"] = "Edited"
        assert backend._chat_context_has_unsaved_history() is True
    finally:
        backend_console_chat._engine = original_engine


def test_unsaved_guard_requires_a_successful_save_or_explicit_discard() -> None:
    fake_engine = _Engine()
    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: fake_engine
    try:
        backend = _Backend(fake_engine)
        fake_engine.conversation_history.append({"role": "user", "content": "Keep me"})

        backend.decisions = ["cancel"]
        assert backend._confirm_unsaved_chat_context("resetting the conversation") is False
        assert backend.save_count == 0

        backend.decisions = ["save"]
        backend.save_results = [False]
        assert backend._confirm_unsaved_chat_context("resetting the conversation") is False
        assert backend.save_count == 1

        backend.decisions = ["save"]
        backend.save_results = [True]
        assert backend._confirm_unsaved_chat_context("resetting the conversation") is True
        assert backend.save_count == 2

        fake_engine.conversation_history.append({"role": "assistant", "content": "New reply"})
        backend.decisions = ["save"]
        backend.save_exception = OSError("disk unavailable")
        backend._show_chat_context_save_failure = lambda error: setattr(backend, "shown_save_error", str(error))
        assert backend._confirm_unsaved_chat_context("exiting Neural Companion") is False
        assert backend.shown_save_error == "disk unavailable"
        backend.save_exception = None

        backend.decisions = ["discard"]
        assert backend._confirm_unsaved_chat_context("loading another conversation") is True
    finally:
        backend_console_chat._engine = original_engine


def test_reset_does_not_destroy_history_when_unsaved_guard_is_cancelled() -> None:
    fake_engine = _Engine()
    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: fake_engine
    try:
        backend = _Backend(fake_engine)
        fake_engine.conversation_history.append({"role": "user", "content": "Keep me"})
        backend.decisions = ["cancel"]

        assert backend.reset_chat_session() is False
        assert fake_engine.reset_count == 0
        assert fake_engine.conversation_history == [{"role": "user", "content": "Keep me"}]
        assert backend.clear_count == 0

        backend.decisions = ["discard"]
        assert backend.reset_chat_session() is True
        assert fake_engine.reset_count == 1
        assert fake_engine.conversation_history == []
        assert backend.clear_count == 1
        assert backend._chat_context_has_unsaved_history() is False
    finally:
        backend_console_chat._engine = original_engine


def test_window_close_stops_before_shutdown_when_unsaved_guard_is_cancelled() -> None:
    backend = _CloseBackend()
    backend._closing = False
    event = _CloseEvent()

    backend.closeEvent(event)

    assert event.ignore_count == 1
    assert event.base_close_count == 0
    assert backend._closing is False


if __name__ == "__main__":
    test_dirty_state_tracks_history_since_last_successful_save()
    test_unsaved_guard_requires_a_successful_save_or_explicit_discard()
    test_reset_does_not_destroy_history_when_unsaved_guard_is_cancelled()
    test_window_close_stops_before_shutdown_when_unsaved_guard_is_cancelled()
    print("smoke_unsaved_chat_context_warning: ok")
