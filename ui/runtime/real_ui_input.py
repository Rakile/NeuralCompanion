from PySide6 import QtCore


def configure_real_ui_input_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI input mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealInputMixin:
    """Frontend event-filter and push-to-talk helpers for the runtime-backed main.ui bridge."""

    def _watched_belongs_to_frontend(self, watched):
            if watched is None:
                return False
            if watched is self.window:
                return True
            current = watched
            visited = set()
            while current is not None and id(current) not in visited:
                visited.add(id(current))
                if current is self.window:
                    return True
                try:
                    current = current.parent()
                except Exception:
                    current = None
            return False

    def _frontend_push_to_talk_mode_active(self):
            input_mode_combo = self._ui_object("input_mode_combo")
            if input_mode_combo is None or not hasattr(input_mode_combo, "currentText"):
                return False
            try:
                return str(input_mode_combo.currentText() or "").strip().lower() == "push-to-talk"
            except Exception:
                return False

    def _frontend_hotkey_pressed_names(self, event):
            names = set()
            if event is None:
                return names
            try:
                scan_code = int(event.nativeScanCode() or 0)
            except Exception:
                scan_code = 0
            if scan_code:
                for name, codes in dict(getattr(engine, "EXACT_HOTKEY_SCAN_CODES", {}) or {}).items():
                    try:
                        if scan_code in tuple(int(code) for code in (codes or ())):
                            names.add(str(name or "").strip().lower())
                    except Exception:
                        continue
            try:
                modifiers = event.modifiers()
            except Exception:
                modifiers = QtCore.Qt.NoModifier
            if modifiers & QtCore.Qt.ControlModifier:
                names.update({"ctrl", "control"})
            if modifiers & QtCore.Qt.AltModifier:
                names.add("alt")
            if modifiers & QtCore.Qt.ShiftModifier:
                names.add("shift")
            if modifiers & QtCore.Qt.MetaModifier:
                names.update({"windows", "win"})
            key_map = {
                QtCore.Qt.Key_Control: {"ctrl", "control"},
                QtCore.Qt.Key_Alt: {"alt"},
                QtCore.Qt.Key_Shift: {"shift"},
                QtCore.Qt.Key_Meta: {"windows", "win"},
                QtCore.Qt.Key_Return: {"return", "enter"},
                QtCore.Qt.Key_Enter: {"enter", "return"},
                QtCore.Qt.Key_Space: {"space"},
                QtCore.Qt.Key_Tab: {"tab"},
                QtCore.Qt.Key_Backtab: {"tab"},
                QtCore.Qt.Key_Escape: {"escape", "esc"},
                QtCore.Qt.Key_Backspace: {"backspace"},
                QtCore.Qt.Key_Delete: {"delete"},
            }
            try:
                names.update(key_map.get(event.key(), set()))
            except Exception:
                pass
            try:
                text = str(event.text() or "").strip()
            except Exception:
                text = ""
            if text:
                normalized = str(engine.normalize_hotkey_text(text) or "").strip().lower()
                if normalized:
                    names.add(normalized)
            return names

    def _consume_frontend_push_to_talk_event(self, event):
            if event is None:
                return False
            event_type = event.type()
            if event_type not in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                return False
            if not self._frontend_push_to_talk_mode_active():
                return False
            binding = str(engine.get_push_to_talk_hotkey() or "").strip()
            if not binding:
                return False
            pressed_names = self._frontend_hotkey_pressed_names(event)
            if not engine.runtime_hotkeys._binding_matches_pressed_names(binding, pressed_names):
                return False
            if event_type == QtCore.QEvent.ShortcutOverride:
                event.accept()
                return True
            if event_type == QtCore.QEvent.KeyPress:
                if not bool(getattr(event, "isAutoRepeat", lambda: False)()):
                    self._input_action_service.set_push_to_talk_hold(True)
                event.accept()
                return True
            if not bool(getattr(event, "isAutoRepeat", lambda: False)()):
                self._input_action_service.set_push_to_talk_hold(False)
            event.accept()
            return True

    def _backend_widget(self, name):
            widget = getattr(self.backend, str(name), None)
            if widget is not None:
                return widget
            try:
                return self.backend.findChild(QtCore.QObject, str(name))
            except Exception:
                return None
