"""RealUiSyncScrollMixin extracted from real_ui_sync.py."""

from PySide6 import QtCore, QtGui, QtWidgets


def configure_real_ui_sync_scroll_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiSyncScrollMixin:
    def _scroll_text_to_bottom(self, widget):
            if widget is None or not hasattr(widget, "verticalScrollBar"):
                return
            try:
                if hasattr(widget, "moveCursor"):
                    widget.moveCursor(QtGui.QTextCursor.End)
                if hasattr(widget, "ensureCursorVisible"):
                    widget.ensureCursorVisible()
                scrollbar = widget.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            except Exception:
                pass

    def _schedule_text_scroll_to_bottom(self, widget):
            self._scroll_text_to_bottom(widget)
            for delay_ms in (0, 50, 150):
                QtCore.QTimer.singleShot(delay_ms, lambda w=widget: self._scroll_text_to_bottom(w))

    def _capture_text_scroll_state(self, widget):
            if widget is None or not hasattr(widget, "verticalScrollBar"):
                return None
            try:
                scrollbar = widget.verticalScrollBar()
                maximum = max(1, int(scrollbar.maximum()))
                value = int(scrollbar.value())
                return {"value": value, "ratio": float(value) / float(maximum)}
            except Exception:
                return None

    def _restore_text_scroll_state(self, widget, state):
            if widget is None or not state or not hasattr(widget, "verticalScrollBar"):
                return
            try:
                scrollbar = widget.verticalScrollBar()
                maximum = int(scrollbar.maximum())
                value = int(state.get("value", 0) or 0)
                ratio = float(state.get("ratio", 0.0) or 0.0)
                target = min(max(value, 0), maximum)
                if maximum > 0 and target == 0 and ratio > 0.0:
                    target = int(round(maximum * ratio))
                scrollbar.setValue(min(max(target, 0), maximum))
            except Exception:
                pass
