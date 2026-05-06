from __future__ import annotations

import threading
import time

from PySide6 import QtCore, QtWidgets
from core import runtime_hotkeys


class HotkeysController(QtCore.QObject):
    bindingCaptured = QtCore.Signal(str)
    bindingCaptureFailed = QtCore.Signal(str)

    def __init__(self, context=None):
        super().__init__()
        self.context = context
        self.hotkeys = context.get_service("qt.hotkeys") if context is not None else None
        self.hotkeys_tab_widget = None
        self._entries = []
        self._entry_by_action = {}
        self._refresh_timer = None
        self._capture_in_progress = False
        self.bindingCaptured.connect(self._on_binding_captured)
        self.bindingCaptureFailed.connect(self._on_binding_capture_failed)

    def bind_designer_tab(self, widget):
        self._bind_ui_objects(widget)
        return self._finalize_tab_widget(widget)

    def _bind_ui_objects(self, widget):
        required = {
            "hotkey_list": QtWidgets.QListWidget,
            "hotkey_label": QtWidgets.QLabel,
            "hotkey_meta": QtWidgets.QLabel,
            "hotkey_description": QtWidgets.QLabel,
            "hotkey_binding_edit": QtWidgets.QLineEdit,
            "hotkey_default_label": QtWidgets.QLabel,
            "btn_hotkey_record": QtWidgets.QPushButton,
            "btn_hotkey_apply": QtWidgets.QPushButton,
            "btn_hotkey_clear": QtWidgets.QPushButton,
            "btn_hotkey_reset_one": QtWidgets.QPushButton,
            "btn_hotkey_refresh": QtWidgets.QPushButton,
            "btn_hotkey_reset_all": QtWidgets.QPushButton,
            "hotkey_status": QtWidgets.QLabel,
        }
        missing = []
        for name, widget_type in required.items():
            child = widget.findChild(widget_type, name)
            if child is None:
                missing.append(name)
            setattr(self, name, child)
        if missing:
            raise RuntimeError(f"Hotkeys UI is missing required object(s): {', '.join(missing)}")
        self.hotkey_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.btn_hotkey_record.clicked.connect(self._start_record_binding)
        self.btn_hotkey_apply.clicked.connect(self._apply_current_binding)
        self.btn_hotkey_clear.clicked.connect(self._clear_current_binding)
        self.btn_hotkey_reset_one.clicked.connect(self._reset_selected_to_default)
        self.btn_hotkey_refresh.clicked.connect(self.refresh_state)
        self.btn_hotkey_reset_all.clicked.connect(self._reset_all_defaults)

    def _finalize_tab_widget(self, widget):
        self.hotkeys_tab_widget = widget
        self._refresh_timer = QtCore.QTimer(widget)
        self._refresh_timer.setInterval(2000)
        self._refresh_timer.timeout.connect(self._soft_refresh)
        self._refresh_timer.start()
        self.refresh_state()
        return widget

    def _selected_action(self):
        item = self.hotkey_list.currentItem() if hasattr(self, "hotkey_list") else None
        if item is None:
            return ""
        return str(item.data(QtCore.Qt.UserRole) or "").strip()

    def _selected_entry(self):
        return self._entry_by_action.get(self._selected_action())

    def _apply_entries(self, entries):
        self._entries = list(entries or [])
        self._entry_by_action = {str(item.get("action", "") or ""): dict(item) for item in self._entries}
        selected_action = self._selected_action()
        self.hotkey_list.clear()
        for entry in self._entries:
            binding = str(entry.get("binding", "") or "").strip()
            suffix = binding if binding else "Unbound"
            item = QtWidgets.QListWidgetItem(f"{entry.get('label', entry.get('action', 'Action'))}  [{suffix}]")
            item.setData(QtCore.Qt.UserRole, str(entry.get("action", "") or ""))
            self.hotkey_list.addItem(item)
        if selected_action:
            for row in range(self.hotkey_list.count()):
                item = self.hotkey_list.item(row)
                if str(item.data(QtCore.Qt.UserRole) or "") == selected_action:
                    self.hotkey_list.setCurrentRow(row)
                    break
        if self.hotkey_list.count() and self.hotkey_list.currentRow() < 0:
            self.hotkey_list.setCurrentRow(0)
        self._on_selection_changed()

    def refresh_state(self):
        if self.hotkeys is None:
            self.hotkey_status.setText("Hotkey service is unavailable.")
            return
        entries = list(self.hotkeys.list_bindings() or [])
        self._apply_entries(entries)
        self.hotkey_status.setText(f"{len(entries)} hotkey action(s) available.")

    def _soft_refresh(self):
        if self.hotkeys is None or self.hotkeys_tab_widget is None or not self.hotkeys_tab_widget.isVisible():
            return
        current_entry = self._selected_entry()
        current_binding = str(self.hotkey_binding_edit.text().strip() or "")
        if current_entry and current_binding != str(current_entry.get("binding", "") or "").strip():
            return
        self.refresh_state()

    def _on_selection_changed(self):
        entry = self._selected_entry()
        has_entry = bool(entry)
        self.hotkey_binding_edit.setEnabled(has_entry)
        self.btn_hotkey_record.setEnabled(has_entry and not self._capture_in_progress)
        self.btn_hotkey_apply.setEnabled(has_entry)
        self.btn_hotkey_clear.setEnabled(has_entry)
        self.btn_hotkey_reset_one.setEnabled(has_entry)
        if not has_entry:
            self.hotkey_label.setText("Select a hotkey action.")
            self.hotkey_meta.setText("")
            self.hotkey_description.setText("")
            self.hotkey_binding_edit.setText("")
            self.hotkey_default_label.setText("")
            return
        label = str(entry.get("label", entry.get("action", "Hotkey")) or "Hotkey")
        category = str(entry.get("category", "other") or "other").replace("_", " ").title()
        scope = str(entry.get("scope", "window") or "window").replace("_", " ").title()
        self.hotkey_label.setText(label)
        self.hotkey_meta.setText(f"Category: {category}\nScope: {scope}")
        self.hotkey_description.setText(str(entry.get("description", "") or ""))
        self.hotkey_binding_edit.setText(str(entry.get("binding", "") or ""))
        default_binding = str(entry.get("default_binding", "") or "").strip() or "Unbound"
        self.hotkey_default_label.setText(default_binding)

    def _format_recorded_binding(self, key_names):
        ordered = []
        seen = set()
        for raw in list(key_names or []):
            normalized = runtime_hotkeys.normalize_hotkey_text(raw)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(normalized)
        if not ordered:
            return ""
        modifier_order = {
            "left ctrl": 0,
            "right ctrl": 0,
            "ctrl": 0,
            "control": 0,
            "left alt": 1,
            "right alt": 1,
            "alt": 1,
            "left shift": 2,
            "right shift": 2,
            "shift": 2,
            "left windows": 3,
            "right windows": 3,
            "windows": 3,
            "win": 3,
        }
        indexed = list(enumerate(ordered))
        indexed.sort(key=lambda pair: (modifier_order.get(pair[1].lower(), 99), pair[0]))
        ordered = [item for _index, item in indexed]
        pretty = []
        for item in ordered:
            words = [part.capitalize() if len(part) > 1 else part.upper() for part in str(item).split(" ")]
            pretty.append(" ".join(words))
        return "+".join(pretty)

    def _record_binding_worker(self):
        captured_order = []
        pressed = set()
        started = False
        finished = threading.Event()
        try:
            if runtime_hotkeys.PYNPUT_HOTKEY_AVAILABLE and runtime_hotkeys.pynput_keyboard is not None:
                def on_press(key):
                    nonlocal started
                    normalized = runtime_hotkeys.canonicalize_pynput_key(key)
                    if not normalized:
                        return
                    started = True
                    pressed.add(normalized)
                    if normalized not in captured_order:
                        captured_order.append(normalized)

                def on_release(key):
                    normalized = runtime_hotkeys.canonicalize_pynput_key(key)
                    if not normalized:
                        return
                    pressed.discard(normalized)
                    if started and not pressed:
                        finished.set()

                with runtime_hotkeys.pynput_keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                    timeout_at = time.time() + 8.0
                    while time.time() < timeout_at:
                        if finished.wait(timeout=0.05):
                            break
                    listener.stop()
            else:
                hook = None

                def callback(event):
                    nonlocal started
                    try:
                        event_type = str(getattr(event, "event_type", "") or "").lower()
                        raw_name = str(getattr(event, "name", "") or "").strip()
                        normalized = runtime_hotkeys.normalize_hotkey_text(raw_name).lower()
                        if not normalized:
                            return
                        if event_type == "down":
                            started = True
                            pressed.add(normalized)
                            if normalized not in captured_order:
                                captured_order.append(normalized)
                        elif event_type == "up":
                            pressed.discard(normalized)
                            if started and not pressed:
                                finished.set()
                    except Exception:
                        pass

                hook = runtime_hotkeys.keyboard.hook(callback)
                timeout_at = time.time() + 8.0
                while time.time() < timeout_at:
                    if finished.wait(timeout=0.05):
                        break
                if hook is not None:
                    try:
                        runtime_hotkeys.keyboard.unhook(hook)
                    except Exception:
                        pass
            binding = self._format_recorded_binding(captured_order)
            if binding:
                self.bindingCaptured.emit(binding)
            else:
                self.bindingCaptureFailed.emit("No binding captured. Try again and press the full combo once.")
        except Exception as exc:
            self.bindingCaptureFailed.emit(f"Recording failed: {exc}")

    def _start_record_binding(self):
        if self._capture_in_progress:
            return
        entry = self._selected_entry()
        if not entry:
            return
        self._capture_in_progress = True
        self.hotkey_status.setText(
            "Recording binding... press the exact combo now, then release it."
        )
        self.btn_hotkey_record.setEnabled(False)
        worker = threading.Thread(target=self._record_binding_worker, daemon=True)
        worker.start()

    def _on_binding_captured(self, binding):
        self._capture_in_progress = False
        self.hotkey_binding_edit.setText(str(binding or ""))
        self.hotkey_status.setText(f"Captured binding: {binding}")
        self.btn_hotkey_record.setEnabled(True)
        self.btn_hotkey_apply.setEnabled(True)
        self.btn_hotkey_clear.setEnabled(True)
        self.btn_hotkey_reset_one.setEnabled(True)

    def _on_binding_capture_failed(self, message):
        self._capture_in_progress = False
        self.hotkey_status.setText(str(message or "Binding capture failed."))
        self.btn_hotkey_record.setEnabled(bool(self._selected_entry()))

    def _apply_current_binding(self):
        if self.hotkeys is None:
            return
        entry = self._selected_entry()
        if not entry:
            return
        action = str(entry.get("action", "") or "")
        binding = self.hotkey_binding_edit.text().strip()
        result = self.hotkeys.set_binding(action, binding)
        self.hotkey_status.setText(f"Updated {entry.get('label', action)} to {result or 'Unbound'}.")
        self.refresh_state()

    def _clear_current_binding(self):
        if self.hotkeys is None:
            return
        entry = self._selected_entry()
        if not entry:
            return
        self.hotkey_binding_edit.clear()
        self._apply_current_binding()

    def _reset_selected_to_default(self):
        if self.hotkeys is None:
            return
        entry = self._selected_entry()
        if not entry:
            return
        default_binding = str(entry.get("default_binding", "") or "")
        self.hotkey_binding_edit.setText(default_binding)
        self._apply_current_binding()

    def _reset_all_defaults(self):
        if self.hotkeys is None:
            return
        self.hotkeys.reset_defaults()
        self.hotkey_status.setText("All hotkeys reset to defaults.")
        self.refresh_state()
