from __future__ import annotations

from pathlib import Path
import sys

from PySide6 import QtWidgets


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.runtime import real_ui_bindings
from ui.runtime.real_ui_bindings import MainUiRealBindingMixin


class _Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in tuple(self.callbacks):
            callback(*args)


class _Scrollbar:
    def __init__(self, value=0, maximum=0):
        self._value = int(value)
        self._maximum = int(maximum)
        self._properties = {}
        self._signals_blocked = False
        self.valueChanged = _Signal()
        self.actionTriggered = _Signal()

    def value(self):
        return self._value

    def maximum(self):
        return self._maximum

    def sliderPosition(self):
        return self._value

    def setValue(self, value):
        value = int(value)
        changed = value != self._value
        self._value = value
        if changed and not self._signals_blocked:
            self.valueChanged.emit(value)

    def blockSignals(self, blocked):
        previous = self._signals_blocked
        self._signals_blocked = bool(blocked)
        return previous

    def property(self, name):
        return self._properties.get(str(name))

    def setProperty(self, name, value):
        self._properties[str(name)] = value


class _ChatEdit:
    def __init__(self, text, scrollbar, replacement_maximum=None):
        self._text = str(text)
        self._scrollbar = scrollbar
        self._replacement_maximum = replacement_maximum
        self.customContextMenuRequested = _Signal()

    def setContextMenuPolicy(self, _policy):
        return None

    def verticalScrollBar(self):
        return self._scrollbar

    def toPlainText(self):
        return self._text

    def setPlainText(self, text):
        self._text = str(text)
        if self._replacement_maximum is not None:
            self._scrollbar._maximum = int(self._replacement_maximum)


class _Backend:
    def __init__(self, *, edit_mode=False):
        self.chat_edit_mode = bool(edit_mode)
        self._chat_render_generation = 3
        self._chat_prepend_active = False
        self._chat_window_rebuild_active = False
        self._chat_visible_history_indexes = (2, 3)
        self.chat_edit = _ChatEdit("tail original", _Scrollbar())
        self.load_calls = 0

    def _load_previous_chat_batch(self, expected_generation=None):
        assert expected_generation == self._chat_render_generation
        self.load_calls += 1
        self._chat_visible_history_indexes = (0, 1, 2, 3)
        self.chat_edit.setPlainText("older\n" + self.chat_edit.toPlainText())


class _BindingHarness(MainUiRealBindingMixin):
    def __init__(self, *, edit_mode=False):
        self.backend = _Backend(edit_mode=edit_mode)
        self.frontend_chat = _ChatEdit(
            "tail edited" if edit_mode else "tail original",
            _Scrollbar(value=0, maximum=100),
            replacement_maximum=160,
        )

    def _ui_object(self, name):
        return self.frontend_chat if name == "chat_edit" else None

    def _backend_widget(self, name):
        return self.backend.chat_edit if name == "chat_edit" else None

    @staticmethod
    def _set_readonly_text_if_changed(target, text):
        if target.toPlainText() == str(text):
            return False
        target.setPlainText(str(text))
        return True


def _emit_scroll_action(scrollbar):
    original_single_shot = real_ui_bindings.QtCore.QTimer.singleShot
    real_ui_bindings.QtCore.QTimer.singleShot = lambda _delay, callback: callback()
    try:
        scrollbar.actionTriggered.emit(QtWidgets.QAbstractSlider.SliderMove)
    finally:
        real_ui_bindings.QtCore.QTimer.singleShot = original_single_shot


def test_visible_chat_scroll_loads_one_batch_and_preserves_anchor():
    harness = _BindingHarness()
    harness._bind_chat_edit_controls()
    harness._bind_chat_edit_controls()
    scrollbar = harness.frontend_chat.verticalScrollBar()
    assert len(scrollbar.actionTriggered.callbacks) == 1
    assert len(scrollbar.valueChanged.callbacks) == 0

    _emit_scroll_action(scrollbar)

    assert harness.backend.load_calls == 1
    assert harness.frontend_chat.toPlainText() == "older\ntail original"
    assert scrollbar.value() == 60


def test_visible_chat_scroll_preserves_unsaved_edit_text():
    harness = _BindingHarness(edit_mode=True)
    harness._bind_chat_edit_controls()

    _emit_scroll_action(harness.frontend_chat.verticalScrollBar())

    assert harness.backend.chat_edit.toPlainText() == "older\ntail edited"
    assert harness.frontend_chat.toPlainText() == "older\ntail edited"


def test_stale_delayed_anchor_does_not_override_a_newer_batch():
    harness = _BindingHarness()
    scrollbar = harness.frontend_chat.verticalScrollBar()
    scrollbar._maximum = 160

    harness._restore_frontend_chat_prepend_anchor(harness.frontend_chat, 0, 100, 1)

    assert scrollbar.value() == 0


def test_layout_value_events_do_not_request_more_batches():
    harness = _BindingHarness()
    harness._bind_chat_edit_controls()
    scrollbar = harness.frontend_chat.verticalScrollBar()

    scrollbar.valueChanged.emit(0)
    scrollbar.valueChanged.emit(0)
    scrollbar.valueChanged.emit(0)
    assert harness.backend.load_calls == 0

    _emit_scroll_action(scrollbar)
    assert harness.backend.load_calls == 1

    scrollbar.valueChanged.emit(0)
    assert harness.backend.load_calls == 1


def test_scroll_action_loads_when_a_one_message_batch_has_no_scroll_range():
    harness = _BindingHarness()
    harness.frontend_chat.verticalScrollBar()._maximum = 0
    harness._bind_chat_edit_controls()

    _emit_scroll_action(harness.frontend_chat.verticalScrollBar())

    assert harness.backend.load_calls == 1


def main():
    test_visible_chat_scroll_loads_one_batch_and_preserves_anchor()
    test_visible_chat_scroll_preserves_unsaved_edit_text()
    test_stale_delayed_anchor_does_not_override_a_newer_batch()
    test_layout_value_events_do_not_request_more_batches()
    test_scroll_action_loads_when_a_one_message_batch_has_no_scroll_range()
    print("smoke_real_ui_chat_history_scroll: ok")


if __name__ == "__main__":
    main()
