from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
try:
    sys.path.remove(str(ROOT))
except ValueError:
    pass
sys.path.insert(0, str(ROOT))

from ui.runtime import backend_chat_session_runtime


class _FakeButton:
    def __init__(self, text):
        self.text = str(text)


class _FakeMessageBox:
    Information = 1
    AcceptRole = 2
    RejectRole = 3
    Ok = 4
    choose = "later"
    instances = []

    def __init__(self, parent=None):
        self.parent = parent
        self.title = ""
        self.text = ""
        self.buttons = []
        self.standard_buttons = None
        self.default_button = None
        self.clicked = None
        type(self).instances.append(self)

    def setIcon(self, icon):
        self.icon = icon

    def setWindowTitle(self, title):
        self.title = str(title)

    def setText(self, text):
        self.text = str(text)

    def addButton(self, text, role):
        button = _FakeButton(text)
        self.buttons.append((button, role))
        return button

    def setDefaultButton(self, button):
        self.default_button = button

    def setStandardButtons(self, buttons):
        self.standard_buttons = buttons

    def exec(self):
        if self.buttons:
            wanted = "Rebuild Embeddings Now" if type(self).choose == "rebuild" else "Later"
            self.clicked = next(button for button, _role in self.buttons if button.text == wanted)

    def clickedButton(self):
        return self.clicked


def _migration_result(*, messages=2, chunks=3, embeddings=4):
    return {
        "conversation_content_migration": {
            "migrated": True,
            "source_version": 0,
            "target_version": 1,
            "cleaned_assistant_turns": messages,
        },
        "long_term_memory_content_migration": {
            "source_version": 0,
            "target_version": 1,
            "cleaned_chunks": chunks,
            "invalidated_embeddings": embeddings,
        },
    }


def test_notice_shows_repair_counts_and_rebuild_choice() -> None:
    _FakeMessageBox.instances.clear()
    _FakeMessageBox.choose = "rebuild"
    decision = backend_chat_session_runtime._run_memory_content_migration_notice_dialog(
        object(),
        _migration_result(),
        message_box_type=_FakeMessageBox,
    )

    box = _FakeMessageBox.instances[-1]
    assert decision == "rebuild"
    assert box.title == "Saved Memory Updated"
    assert "Assistant messages repaired: 2" in box.text
    assert "Archive chunks repaired: 3" in box.text
    assert "Archive embeddings requiring rebuild: 4" in box.text
    assert "memory records, images, and asset links were preserved" in box.text
    assert [button.text for button, _role in box.buttons] == ["Rebuild Embeddings Now", "Later"]
    assert box.default_button.text == "Later"


def test_notice_without_missing_embeddings_uses_ok() -> None:
    _FakeMessageBox.instances.clear()
    decision = backend_chat_session_runtime._run_memory_content_migration_notice_dialog(
        object(),
        _migration_result(embeddings=0),
        message_box_type=_FakeMessageBox,
    )

    box = _FakeMessageBox.instances[-1]
    assert decision == "acknowledged"
    assert box.standard_buttons == _FakeMessageBox.Ok
    assert box.buttons == []


def test_current_content_does_not_show_notice() -> None:
    _FakeMessageBox.instances.clear()
    decision = backend_chat_session_runtime._run_memory_content_migration_notice_dialog(
        object(),
        {
            "conversation_content_migration": {"migrated": False},
            "long_term_memory_content_migration": None,
        },
        message_box_type=_FakeMessageBox,
    )
    assert decision is None
    assert _FakeMessageBox.instances == []


def test_rebuild_choice_acknowledges_notice_and_schedules_existing_action() -> None:
    calls = []
    original_dialog = backend_chat_session_runtime._run_memory_content_migration_notice_dialog
    original_acknowledge = backend_chat_session_runtime.long_term_memory.acknowledge_content_migration_report
    original_single_shot = backend_chat_session_runtime.QtCore.QTimer.singleShot

    class _Backend:
        def rebuild_long_term_memory_embeddings_now(self):
            calls.append("rebuilt")

    try:
        backend_chat_session_runtime._run_memory_content_migration_notice_dialog = lambda _parent, _result: "rebuild"
        backend_chat_session_runtime.long_term_memory.acknowledge_content_migration_report = lambda: calls.append("acknowledged")
        backend_chat_session_runtime.QtCore.QTimer.singleShot = lambda delay, callback: (
            calls.append(("scheduled", delay)),
            callback(),
        )
        backend_chat_session_runtime.BackendChatSessionRuntimeMixin._show_memory_content_migration_notice(
            _Backend(),
            _migration_result(),
        )
    finally:
        backend_chat_session_runtime._run_memory_content_migration_notice_dialog = original_dialog
        backend_chat_session_runtime.long_term_memory.acknowledge_content_migration_report = original_acknowledge
        backend_chat_session_runtime.QtCore.QTimer.singleShot = original_single_shot

    assert calls == ["acknowledged", ("scheduled", 0), "rebuilt"]


if __name__ == "__main__":
    test_notice_shows_repair_counts_and_rebuild_choice()
    test_notice_without_missing_embeddings_uses_ok()
    test_current_content_does_not_show_notice()
    test_rebuild_choice_acknowledges_notice_and_schedules_existing_action()
    print("smoke_memory_content_migration_notice: ok")
