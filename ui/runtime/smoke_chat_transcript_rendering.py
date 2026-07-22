from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.runtime import backend_console_chat
from ui.runtime.backend_console_chat import BackendConsoleChatMixin


class _Scrollbar:
    def __init__(self, value=0, maximum=0):
        self._value = int(value)
        self._maximum = int(maximum)
        self.set_calls = []

    def value(self):
        return self._value

    def maximum(self):
        return self._maximum

    def setValue(self, value):
        self._value = int(value)
        self.set_calls.append(int(value))


class _ChatEdit:
    def __init__(self, scrollbar):
        self._scrollbar = scrollbar

    def verticalScrollBar(self):
        return self._scrollbar


class _Backend(BackendConsoleChatMixin):
    def __init__(self, batch_size=200):
        self._test_batch_size = int(batch_size)
        self._chat_visible_history_indexes = ()
        self._chat_total_displayable = 0
        self._chat_render_generation = 0
        self._chat_prepend_active = False
        self.chat_edit = _ChatEdit(_Scrollbar(value=12, maximum=100))

    def _chat_visual_batch_size(self):
        return self._test_batch_size


def _history(count):
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index}"}
        for index in range(count)
    ]


def test_window_state_expands_backwards_in_batches():
    backend = _Backend()
    history = _history(450)
    backend._reset_chat_window_state(history)
    assert backend._chat_visible_history_indexes == tuple(range(250, 450))
    assert backend._chat_total_displayable == 450
    assert backend._extend_chat_window_with_previous_batch(history) == tuple(range(50, 250))
    assert backend._chat_visible_history_indexes == tuple(range(50, 450))
    assert backend._extend_chat_window_with_previous_batch(history) == tuple(range(50))
    assert backend._chat_visible_history_indexes == tuple(range(450))
    assert backend._chat_display_window_status() == "displaying 450/450 messages"


def test_stale_anchor_restore_is_ignored():
    backend = _Backend()
    backend._chat_render_generation = 2
    backend._restore_prepend_anchor(1, 12, 100)
    assert backend.chat_edit.verticalScrollBar().set_calls == []
    backend.chat_edit.verticalScrollBar()._maximum = 160
    backend._restore_prepend_anchor(2, 12, 100)
    assert backend.chat_edit.verticalScrollBar().set_calls == [72]


def test_replay_mapping_uses_full_history_index():
    class _Engine:
        @staticmethod
        def collect_replayable_chat_entries():
            return [
                {"history_index": 10, "replay_index": 11},
                {"history_index": 250, "replay_index": 251},
            ]

    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: _Engine()
    try:
        backend = _Backend()
        backend._chat_visible_history_indexes = (250, 251)
        assert backend._replay_index_for_visible_entry(0) == 251
    finally:
        backend_console_chat._engine = original_engine


def test_edit_snapshot_detects_underlying_history_change():
    backend = _Backend()
    backend._chat_edit_snapshot_full_history = _history(3)
    assert backend._chat_edit_history_is_stale(_history(3)) is False
    changed = _history(3)
    changed[1]["content"] = "changed elsewhere"
    assert backend._chat_edit_history_is_stale(changed) is True


def test_rebuild_scroll_zero_does_not_schedule_prepend_and_requests_coalesce():
    calls = []
    original_single_shot = backend_console_chat.QtCore.QTimer.singleShot
    backend_console_chat.QtCore.QTimer.singleShot = lambda delay, callback: calls.append((delay, callback))
    try:
        backend = _Backend()
        backend._chat_window_rebuild_active = True
        backend._on_chat_scroll_value_changed(0)
        assert calls == []
        backend._chat_window_rebuild_active = False
        backend._on_chat_scroll_value_changed(0)
        backend._on_chat_scroll_value_changed(1)
        assert len(calls) == 1
        backend._chat_render_generation += 1
        calls[0][1]()
        assert backend._chat_prepend_active is False
    finally:
        backend_console_chat.QtCore.QTimer.singleShot = original_single_shot


def test_prefix_trim_invalidates_visible_index_mapping():
    backend = _Backend(batch_size=3)
    history = _history(6)
    backend._reset_chat_window_state(history)
    assert backend._chat_window_mapping_matches_history(history) is True
    assert backend._chat_window_mapping_matches_history(history[2:]) is False


def test_tail_sync_slides_the_initial_window_without_growing_it():
    class _Engine:
        conversation_history = _history(5)

    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: _Engine()
    try:
        backend = _Backend(batch_size=3)
        backend._reset_chat_window_state(_Engine.conversation_history)
        rebuild_requests = []
        backend._schedule_chat_window_rebuild = (
            lambda *, reset_window=True: rebuild_requests.append(bool(reset_window))
        )

        _Engine.conversation_history.append({"role": "assistant", "content": "message 5"})
        assert backend._sync_chat_window_tail_from_history() is True

        assert backend._chat_visible_history_indexes == (3, 4, 5)
        assert backend._chat_total_displayable == 6
        assert rebuild_requests == [False]
    finally:
        backend_console_chat._engine = original_engine


def test_tail_sync_preserves_a_manually_expanded_window_capacity():
    class _Engine:
        conversation_history = _history(8)

    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: _Engine()
    try:
        backend = _Backend(batch_size=3)
        backend._reset_chat_window_state(_Engine.conversation_history)
        backend._extend_chat_window_with_previous_batch(_Engine.conversation_history)
        assert backend._chat_visible_history_indexes == (2, 3, 4, 5, 6, 7)
        backend._schedule_chat_window_rebuild = lambda *, reset_window=True: None

        _Engine.conversation_history.append({"role": "user", "content": "message 8"})
        assert backend._sync_chat_window_tail_from_history() is True

        assert backend._chat_visible_history_indexes == (3, 4, 5, 6, 7, 8)
    finally:
        backend_console_chat._engine = original_engine


def test_tail_sync_remains_uncapped_when_visual_batch_size_is_minus_one():
    class _Engine:
        conversation_history = _history(3)

    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: _Engine()
    try:
        backend = _Backend(batch_size=-1)
        backend._reset_chat_window_state(_Engine.conversation_history)
        rebuild_requests = []
        backend._schedule_chat_window_rebuild = (
            lambda *, reset_window=True: rebuild_requests.append(bool(reset_window))
        )

        _Engine.conversation_history.append({"role": "assistant", "content": "message 3"})
        assert backend._sync_chat_window_tail_from_history() is True

        assert backend._chat_visible_history_indexes == (0, 1, 2, 3)
        assert rebuild_requests == []
    finally:
        backend_console_chat._engine = original_engine


def main():
    test_window_state_expands_backwards_in_batches()
    test_stale_anchor_restore_is_ignored()
    test_replay_mapping_uses_full_history_index()
    test_edit_snapshot_detects_underlying_history_change()
    test_rebuild_scroll_zero_does_not_schedule_prepend_and_requests_coalesce()
    test_prefix_trim_invalidates_visible_index_mapping()
    test_tail_sync_slides_the_initial_window_without_growing_it()
    test_tail_sync_preserves_a_manually_expanded_window_capacity()
    test_tail_sync_remains_uncapped_when_visual_batch_size_is_minus_one()
    print("smoke_chat_transcript_rendering: ok")


if __name__ == "__main__":
    main()
