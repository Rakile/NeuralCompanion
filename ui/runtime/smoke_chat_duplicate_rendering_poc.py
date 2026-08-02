from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import sys


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtWidgets

from ui.runtime import backend_console_chat
from ui.runtime.backend_console_chat import BackendConsoleChatMixin


ASSISTANT_TEXT = "one authoritative reply"


class _Engine:
    RUNTIME_CONFIG = {"chat_message_timestamps_enabled": False}
    conversation_history = [
        {
            "role": "assistant",
            "origin": "assistant_reply",
            "content": ASSISTANT_TEXT,
        }
    ]


class _Backend(BackendConsoleChatMixin):
    def __init__(self):
        self.chat_edit = QtWidgets.QTextEdit()
        self.chat_edit_mode = False
        self.chat_auto_scroll = False
        self._chat_append_preserve_scroll_active = False
        self._chat_visible_history_indexes = ()
        self._chat_visible_history_keys = ()
        self._chat_total_displayable = 0
        self._chat_render_generation = 0
        self._chat_prepend_active = False
        self._chat_prepend_request_pending = False
        self._chat_window_rebuild_active = False
        self._chat_window_rebuild_scheduled = False
        self._chat_window_rebuild_reset_window = False
        self._console_redirect = SimpleNamespace(chat_line_count=0)

    def _chat_visual_batch_size(self):
        return 200

    def _current_chat_font_size(self):
        return 12

    def _update_chat_status(self, _lines, _auto_scroll):
        return None

    def _update_control_action_buttons(self):
        return None


def _visible_reply_copies(backend):
    return backend.chat_edit.toPlainText().count(ASSISTANT_TEXT)


def main():
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    original_engine = backend_console_chat._engine
    backend_console_chat._engine = lambda: _Engine()
    try:
        legacy = _Backend()
        legacy._rebuild_chat_view_from_history(force=True)
        assert _visible_reply_copies(legacy) == 1
        legacy._insert_chat_text_now(
            f"🤖 Assistant: {ASSISTANT_TEXT}\n",
            cursor_position=backend_console_chat.QtGui.QTextCursor.End,
            allow_auto_scroll=False,
        )
        legacy_copies = _visible_reply_copies(legacy)

        fixed = _Backend()
        fixed._rebuild_chat_view_from_history(force=True)
        assert _visible_reply_copies(fixed) == 1
        fixed._append_chat_text_now(f"🤖 Assistant: {ASSISTANT_TEXT}\n")
        fixed_copies = _visible_reply_copies(fixed)
    finally:
        backend_console_chat._engine = original_engine

    assert legacy_copies == 2, "legacy stdout append must reproduce the duplicate rendering bug"
    assert fixed_copies == 1, "history-backed stdout handling must render one authoritative reply"
    print(
        "chat duplicate rendering PoC: "
        f"legacy_visible_copies={legacy_copies} fixed_visible_copies={fixed_copies}"
    )


if __name__ == "__main__":
    main()
