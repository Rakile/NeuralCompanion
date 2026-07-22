from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.runtime.real_ui_sync_copy import RealUiSyncCopyMixin


class _LineEdit:
    def __init__(self, text, *, focused=False, modified=False):
        self._text = str(text)
        self._focused = bool(focused)
        self._modified = bool(modified)

    def text(self):
        return self._text

    def hasFocus(self):
        return self._focused

    def isModified(self):
        return self._modified


class _Spin:
    def __init__(self, value, *, text=None, focused=False, modified=False):
        self._value = int(value)
        self._line_edit = _LineEdit(
            str(value) if text is None else text,
            focused=focused,
            modified=modified,
        )

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = int(value)
        self._line_edit._text = str(value)
        self._line_edit._modified = False

    def lineEdit(self):
        return self._line_edit

    def blockSignals(self, _blocked):
        return None

    def toolTip(self):
        return ""

    def setToolTip(self, _tooltip):
        return None


class _SyncHarness(RealUiSyncCopyMixin):
    def __init__(self, front, back):
        self.front = front
        self.back = back

    @staticmethod
    def _combo_sync_names():
        return ()

    @staticmethod
    def _checkbox_sync_names():
        return ()

    @staticmethod
    def _spin_sync_names():
        return ("chat_visual_batch_size_spin",)

    @staticmethod
    def _line_edit_sync_names():
        return ()

    def _ui_object(self, name):
        return self.front if name == "chat_visual_batch_size_spin" else None

    def _backend_widget(self, name):
        return self.back if name == "chat_visual_batch_size_spin" else None

    @staticmethod
    def _sync_musetalk_runtime_visibility():
        return None

    @staticmethod
    def _copy_runtime_plain_text_state(*_args, **_kwargs):
        return None

    def __getattr__(self, name):
        if name.startswith("_mirror_") or name in {
            "_copy_runtime_plain_text_state",
            "_sync_musetalk_runtime_visibility",
            "_refresh_frontend_theme_controls",
            "_enforce_frontend_runtime_collapsed_visibility",
        }:
            return lambda *args, **kwargs: None
        raise AttributeError(name)


def test_pending_manual_chat_batch_edit_is_not_overwritten():
    front = _Spin(200, text="1", focused=True, modified=True)
    harness = _SyncHarness(front, _Spin(200))

    harness._sync_backend_to_ui()

    assert front.lineEdit().text() == "1"
    assert front.value() == 200


def test_committed_chat_batch_value_still_mirrors():
    front = _Spin(200, text="200", focused=False, modified=False)
    harness = _SyncHarness(front, _Spin(75))

    harness._sync_backend_to_ui()

    assert front.lineEdit().text() == "75"
    assert front.value() == 75


def main():
    test_pending_manual_chat_batch_edit_is_not_overwritten()
    test_committed_chat_batch_value_still_mirrors()
    print("smoke_real_ui_spin_sync: ok")


if __name__ == "__main__":
    main()
