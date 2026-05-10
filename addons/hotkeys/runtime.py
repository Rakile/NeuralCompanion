import time
from collections import OrderedDict

from PySide6 import QtCore, QtGui

from core.addons.qt_host_services import QtRuntimeConfigService


def _runtime_config_service(backend):
    return QtRuntimeConfigService(backend)


def _engine_attr(backend, name: str, default=None):
    return _runtime_config_service(backend).engine_attr(name, default)


def _engine_call(backend, name: str, default=None, *args, **kwargs):
    callback = _engine_attr(backend, name, None)
    if callable(callback):
        return callback(*args, **kwargs)
    return default


class BackendHotkeyMixin:
    """Host-facing hotkey polling, labels, and addon-facing hotkey catalog."""

    def _build_ui_hotkey_timer(self):
        self._ui_hotkey_last_triggered_at = {}
        self._ui_hotkey_poll_timer = QtCore.QTimer(self)
        self._ui_hotkey_poll_timer.setInterval(45)
        self._ui_hotkey_poll_timer.timeout.connect(self._poll_exact_ui_hotkeys)
        self._ui_hotkey_poll_timer.start()

    def _hotkey_button_titles(self):
        return {
            "regenerate_response": "Regenerate",
            "retry_user_input": "Retry Input",
            "pause_speech": "Pause / Resume",
            "skip_speech": "Skip Speech",
            "skip_user_reply": "Skip User Reply",
        }

    def _supported_ui_hotkey_actions(self):
        return OrderedDict(
            [
                ("start_engine", lambda: self.start_engine()),
                ("stop_engine", lambda: self.stop_engine()),
                ("reset_chat_session", lambda: self.reset_chat_session()),
                ("clear_console", lambda: self.clear_console()),
                ("clear_chat", lambda: self.clear_chat()),
                ("show_musetalk_preview", lambda: self.show_musetalk_preview()),
                ("toggle_musetalk_avatar_focus", lambda: self.toggle_musetalk_avatar_focus()),
                ("show_visual_reply", lambda: self.show_visual_reply_dock()),
                ("start_vam_desktop", lambda: self.on_start_vam_desktop_clicked()),
                ("start_vam_vr", lambda: self.on_start_vam_vr_clicked()),
            ]
        )

    def _dispatch_hotkey_action(self, action):
        action_key = str(action or "").strip()
        if action_key in _engine_attr(self, "DEFAULT_MANUAL_ACTION_HOTKEYS", {}):
            self.trigger_control_action(action_key)
            return
        handler = self._supported_ui_hotkey_actions().get(action_key)
        if callable(handler):
            handler()

    def _refresh_hotkey_shortcuts(self):
        shortcuts = getattr(self, "_qt_hotkey_shortcuts", None)
        if shortcuts is None:
            self._qt_hotkey_shortcuts = {}
            return
        for shortcut in shortcuts.values():
            try:
                shortcut.setEnabled(False)
                shortcut.setKey(QtGui.QKeySequence())
            except Exception:
                pass

    def _poll_exact_ui_hotkeys(self):
        if not self.isVisible() or not self.isActiveWindow():
            return
        if self._closing:
            return
        actions = self._supported_ui_hotkey_actions()
        bindings = _engine_call(self, "get_ui_action_hotkeys", {}) or {}
        now = time.time()
        debounce_seconds = 0.35
        for action, handler in actions.items():
            binding = str(bindings.get(action, "") or "").strip()
            if not binding:
                continue
            if not _engine_call(self, "is_hotkey_binding_pressed", False, binding):
                continue
            last_triggered = float(self._ui_hotkey_last_triggered_at.get(action, 0.0) or 0.0)
            if now - last_triggered < debounce_seconds:
                continue
            self._ui_hotkey_last_triggered_at[action] = now
            if callable(handler):
                handler()

    def _refresh_hotkey_labels(self):
        if hasattr(self, "input_mode_hint"):
            mode = "push_to_talk" if self.input_mode_combo.currentText() == "Push-to-Talk" else "voice_activation"
            if mode == "push_to_talk":
                binding = _engine_call(self, "get_push_to_talk_hotkey", "Right Ctrl")
                self.input_mode_hint.setText(f"Push-to-Talk hotkey: {binding} (fallback button below)")
            else:
                self.input_mode_hint.setText("Voice activation listens for speech automatically")
        button_titles = self._hotkey_button_titles()
        button_map = getattr(self, "_control_action_buttons", {}) or {}
        configured = _engine_call(self, "get_manual_action_hotkeys", {}) or {}
        labels = _engine_attr(self, "HOTKEY_ACTION_LABELS", {})
        for action, button in button_map.items():
            title = str(button_titles.get(action, labels.get(action, action)) or action)
            binding = str(configured.get(action, "") or "").strip()
            button.setText(f"{title}\n{binding}" if binding else title)

    def hotkey_catalog(self):
        labels = _engine_attr(self, "HOTKEY_ACTION_LABELS", {})
        entries = [
            {
                "action": "push_to_talk",
                "label": str(labels.get("push_to_talk", "Push-to-Talk")),
                "binding": _engine_call(self, "get_push_to_talk_hotkey", "Right Ctrl"),
                "default_binding": str(_engine_attr(self, "DEFAULT_PUSH_TO_TALK_HOTKEY", "Right Ctrl")),
                "category": "input",
                "scope": "global",
                "description": "Hold this key to talk while input mode is Push-to-Talk.",
            }
        ]
        manual_bindings = _engine_call(self, "get_manual_action_hotkeys", {}) or {}
        for action, default_binding in (_engine_attr(self, "DEFAULT_MANUAL_ACTION_HOTKEYS", {}) or {}).items():
            entries.append(
                {
                    "action": action,
                    "label": str(labels.get(action, action)),
                    "binding": str(manual_bindings.get(action, "") or ""),
                    "default_binding": str(default_binding or ""),
                    "category": "manual_controls",
                    "scope": "global_and_window",
                    "description": "Manual runtime control handled by the core hotkey spine.",
                }
            )
        ui_bindings = _engine_call(self, "get_ui_action_hotkeys", {}) or {}
        for action, default_binding in (_engine_attr(self, "DEFAULT_UI_ACTION_HOTKEYS", {}) or {}).items():
            entries.append(
                {
                    "action": action,
                    "label": str(labels.get(action, action)),
                    "binding": str(ui_bindings.get(action, "") or ""),
                    "default_binding": str(default_binding or ""),
                    "category": "ui_actions",
                    "scope": "window",
                    "description": "Qt window shortcut active while NC is focused.",
                }
            )
        return entries

    def set_hotkey_binding(self, action, binding):
        action_key = str(action or "").strip()
        normalize = _engine_attr(self, "normalize_hotkey_text", lambda value: str(value or "").strip())
        binding_text = normalize(binding)
        if action_key == "push_to_talk":
            default_binding = _engine_attr(self, "DEFAULT_PUSH_TO_TALK_HOTKEY", "Right Ctrl")
            value = _engine_call(self, "set_push_to_talk_hotkey", default_binding, binding_text or default_binding)
        elif action_key in (_engine_attr(self, "DEFAULT_MANUAL_ACTION_HOTKEYS", {}) or {}):
            value = _engine_call(self, "set_manual_action_hotkey", binding_text, action_key, binding_text)
        elif action_key in (_engine_attr(self, "DEFAULT_UI_ACTION_HOTKEYS", {}) or {}):
            value = _engine_call(self, "set_ui_action_hotkey", binding_text, action_key, binding_text)
        else:
            raise KeyError(f"Unknown hotkey action: {action_key}")
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()
        self.save_session()
        return value

    def reset_hotkey_bindings(self):
        bindings = _engine_call(self, "reset_hotkeys_to_defaults", {}) or {}
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()
        self.save_session()
        return bindings
