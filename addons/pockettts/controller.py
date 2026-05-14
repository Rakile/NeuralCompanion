from __future__ import annotations

import shiboken6
from pathlib import Path

from core.tts_session_schema import with_flat_tts_runtime_settings

class PocketTTSController:
    STATE_KEY = "pocket_tts_settings"

    def __init__(self, context=None):
        self.context = context
        self.dialogs = context.get_service("qt.dialogs") if context is not None else None
        self.shell = context.get_service("qt.shell") if context is not None else None
        self._shell_preview = bool(
            context.get_service("qt.shell_preview") or context.get_service("qt.pockettts_shell_preview")
        ) if context is not None else False
        self._shell_python = self._initial_shell_python()
        self._shell_generation_state = self._initial_shell_generation_state()
        self._widget = None
        self._advanced_group = None
        self._advanced_toggle = None
        self._python_edit = None
        self._bundled_label = None
        self._temperature_spin = None
        self._lsd_steps_spin = None
        self._eos_threshold_spin = None
        self._max_tokens_spin = None
        self._frames_after_eos_spin = None

    def _runtime_config_service(self):
        return self.context.get_service("qt.runtime_config") if self.context is not None else None

    def _default_python(self) -> str:
        service = self._runtime_config_service()
        if service is None or not hasattr(service, "engine_attr"):
            return ""
        return str(service.engine_attr("DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()

    def _initial_shell_python(self) -> str:
        if not self._shell_preview:
            return ""
        session_getter = self.context.get_service("qt.shell_session_snapshot") if self.context is not None else None
        if callable(session_getter):
            try:
                session = with_flat_tts_runtime_settings(session_getter() or {})
                return str(session.get("pocket_tts_python", "") or "").strip()
            except Exception:
                return ""
        return ""

    def _initial_shell_generation_state(self):
        if not self._shell_preview:
            return {}
        session_getter = self.context.get_service("qt.shell_session_snapshot") if self.context is not None else None
        session = {}
        if callable(session_getter):
            try:
                session = with_flat_tts_runtime_settings(session_getter() or {})
            except Exception:
                session = {}
        return {
            "pocket_tts_temperature": max(0.05, float(session.get("pocket_tts_temperature", 0.7) or 0.7)),
            "pocket_tts_lsd_decode_steps": max(1, int(session.get("pocket_tts_lsd_decode_steps", 1) or 1)),
            "pocket_tts_eos_threshold": float(session.get("pocket_tts_eos_threshold", -4.0) or -4.0),
            "pocket_tts_max_tokens": max(1, int(session.get("pocket_tts_max_tokens", 50) or 50)),
            "pocket_tts_frames_after_eos": max(0, int(session.get("pocket_tts_frames_after_eos", 0) or 0)),
        }

    def _notify_settings_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def _current_python(self) -> str:
        if self._shell_preview:
            return str(self._shell_python or "").strip()
        service = self._runtime_config_service()
        if service is None:
            return ""
        return str(service.get("pocket_tts_python", "") or "").strip()

    def _current_generation_state(self):
        if self._shell_preview:
            getter = self._shell_generation_state.get
        else:
            service = self._runtime_config_service()
            getter = service.get if service is not None else (lambda _key, default=None: default)
        return {
            "pocket_tts_temperature": max(0.05, float(getter("pocket_tts_temperature", 0.7) or 0.7)),
            "pocket_tts_lsd_decode_steps": max(1, int(getter("pocket_tts_lsd_decode_steps", 1) or 1)),
            "pocket_tts_eos_threshold": float(getter("pocket_tts_eos_threshold", -4.0) or -4.0),
            "pocket_tts_max_tokens": max(1, int(getter("pocket_tts_max_tokens", 50) or 50)),
            "pocket_tts_frames_after_eos": max(0, int(getter("pocket_tts_frames_after_eos", 0) or 0)),
        }

    def _set_runtime(self, key: str, value):
        if self._shell_preview:
            self._shell_generation_state[str(key)] = value
            self._notify_settings_changed()
            return
        service = self._runtime_config_service()
        if service is not None:
            service.update(str(key), value)
        self._notify_settings_changed()

    def _set_python(self, value: str):
        if self._shell_preview:
            self._shell_python = str(value or "").strip()
            self._notify_settings_changed()
            return
        service = self._runtime_config_service()
        if service is not None:
            service.update("pocket_tts_python", str(value or "").strip())
        self._notify_settings_changed()

    def _ensure_default_python(self):
        if self._shell_preview:
            return self._current_python()
        current = self._current_python()
        if current:
            return current
        fallback = self._default_python()
        if fallback and Path(fallback).exists():
            if self._python_edit is not None:
                self._python_edit.setText(fallback)
            self._set_python(fallback)
            return fallback
        return ""

    def _sync_widgets_from_runtime(self):
        if self._widget_alive(self._python_edit):
            self._python_edit.blockSignals(True)
            self._python_edit.setText(self._current_python())
            self._python_edit.blockSignals(False)
        state = self._current_generation_state()
        for attr, key in (
            ("_temperature_spin", "pocket_tts_temperature"),
            ("_lsd_steps_spin", "pocket_tts_lsd_decode_steps"),
            ("_eos_threshold_spin", "pocket_tts_eos_threshold"),
            ("_max_tokens_spin", "pocket_tts_max_tokens"),
            ("_frames_after_eos_spin", "pocket_tts_frames_after_eos"),
        ):
            widget = getattr(self, attr, None)
            if not self._widget_alive(widget):
                continue
            widget.blockSignals(True)
            try:
                widget.setValue(state[key])
            except Exception:
                pass
            widget.blockSignals(False)
        if self._widget_alive(self._advanced_toggle) and self._widget_alive(self._advanced_group):
            self._advanced_group.setVisible(bool(self._advanced_toggle.isChecked()))

    def _widget_alive(self, widget):
        if widget is None:
            return False
        try:
            return bool(shiboken6.isValid(widget))
        except Exception:
            return False

    def _toggle_advanced(self, checked):
        if self._advanced_group is not None:
            self._advanced_group.setVisible(bool(checked))
        if self._advanced_toggle is not None:
            self._advanced_toggle.setText(
                "Hide Advanced PocketTTS Override" if checked else "Show Advanced PocketTTS Override"
            )

    def _browse_python(self):
        if self._python_edit is None:
            return
        if self._shell_preview:
            return
        from PySide6 import QtWidgets

        if self.dialogs is not None:
            path, _ = self.dialogs.open_file(
                "Select PocketTTS Python",
                self._current_python() or "",
                "Python (*.exe);;All Files (*.*)",
            )
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                None,
                "Select PocketTTS Python",
                self._current_python() or "",
                "Python (*.exe);;All Files (*.*)",
            )
        if not path:
            return
        self._python_edit.setText(path)
        self._set_python(path)

    def _reset_to_default(self):
        if self._shell_preview:
            if self._widget_alive(self._python_edit):
                self._python_edit.setText("")
            self._set_python("")
            self._toggle_advanced(self._advanced_toggle.isChecked() if self._widget_alive(self._advanced_toggle) else False)
            return
        fallback = self._default_python()
        if fallback and Path(fallback).exists() and self._widget_alive(self._python_edit):
            self._python_edit.setText(fallback)
            self._set_python(fallback)
        self._toggle_advanced(self._advanced_toggle.isChecked() if self._widget_alive(self._advanced_toggle) else False)

    def _ui_child(self, root, name, cls=None):
        if root is None:
            return None
        try:
            from PySide6 import QtCore

            return root.findChild(cls or QtCore.QObject, name)
        except Exception:
            return None

    def bind_designer_tab(self, widget):
        from PySide6 import QtWidgets

        if widget is None:
            raise RuntimeError("PocketTTS Designer UI did not provide a widget.")
        self._advanced_group = self._ui_child(widget, "pockettts_advanced_group", QtWidgets.QGroupBox)
        self._advanced_toggle = self._ui_child(widget, "btn_pockettts_advanced_toggle", QtWidgets.QPushButton)
        self._python_edit = self._ui_child(widget, "pockettts_python_edit", QtWidgets.QLineEdit)
        self._bundled_label = self._ui_child(widget, "pockettts_bundled_label", QtWidgets.QLabel)
        self._temperature_spin = self._ui_child(widget, "pockettts_temperature_spin", QtWidgets.QDoubleSpinBox)
        self._lsd_steps_spin = self._ui_child(widget, "pockettts_lsd_steps_spin", QtWidgets.QSpinBox)
        self._eos_threshold_spin = self._ui_child(widget, "pockettts_eos_threshold_spin", QtWidgets.QDoubleSpinBox)
        self._max_tokens_spin = self._ui_child(widget, "pockettts_max_tokens_spin", QtWidgets.QSpinBox)
        self._frames_after_eos_spin = self._ui_child(widget, "pockettts_frames_after_eos_spin", QtWidgets.QSpinBox)
        browse = self._ui_child(widget, "btn_pockettts_browse", QtWidgets.QPushButton)
        bundled_button = self._ui_child(widget, "btn_pockettts_use_bundled", QtWidgets.QPushButton)
        note = self._ui_child(widget, "pockettts_note_label", QtWidgets.QLabel)

        required = (
            self._advanced_group,
            self._python_edit,
            self._bundled_label,
            self._temperature_spin,
            self._lsd_steps_spin,
            self._eos_threshold_spin,
            self._max_tokens_spin,
            self._frames_after_eos_spin,
            browse,
            bundled_button,
            note,
        )
        if any(item is None for item in required):
            raise RuntimeError("PocketTTS Designer UI is missing one or more required controls.")

        bundled_text = "Shell preview: bundled interpreter lookup is disabled."
        if not self._shell_preview:
            bundled_text = self._default_python() or "Bundled PocketTTS interpreter not found."
        self._bundled_label.setText(f"Bundled interpreter: {bundled_text}")
        self._python_edit.setPlaceholderText("Optional override path to PocketTTS python.exe")
        self._python_edit.editingFinished.connect(lambda: self._set_python(self._python_edit.text()))

        self._temperature_spin.setRange(0.05, 2.0)
        self._temperature_spin.setSingleStep(0.05)
        self._temperature_spin.setDecimals(2)
        self._temperature_spin.valueChanged.connect(lambda value: self._set_runtime("pocket_tts_temperature", max(0.05, float(value or 0.7))))

        self._lsd_steps_spin.setRange(1, 8)
        self._lsd_steps_spin.setSingleStep(1)
        self._lsd_steps_spin.valueChanged.connect(lambda value: self._set_runtime("pocket_tts_lsd_decode_steps", max(1, int(value or 1))))

        self._eos_threshold_spin.setRange(-12.0, 0.0)
        self._eos_threshold_spin.setSingleStep(0.25)
        self._eos_threshold_spin.setDecimals(2)
        self._eos_threshold_spin.valueChanged.connect(lambda value: self._set_runtime("pocket_tts_eos_threshold", float(value if value is not None else -4.0)))

        self._max_tokens_spin.setRange(10, 200)
        self._max_tokens_spin.setSingleStep(5)
        self._max_tokens_spin.valueChanged.connect(lambda value: self._set_runtime("pocket_tts_max_tokens", max(1, int(value or 50))))

        self._frames_after_eos_spin.setRange(0, 10)
        self._frames_after_eos_spin.setSingleStep(1)
        self._frames_after_eos_spin.valueChanged.connect(lambda value: self._set_runtime("pocket_tts_frames_after_eos", max(0, int(value or 0))))

        browse.clicked.connect(self._browse_python)
        bundled_button.clicked.connect(self._reset_to_default)
        if self._widget_alive(self._advanced_toggle):
            self._advanced_toggle.setCheckable(True)
            self._advanced_toggle.toggled.connect(self._toggle_advanced)
        if self._shell_preview:
            browse.setEnabled(False)
            browse.setToolTip("Disabled in shell preview; no file dialogs or runtime config writes are connected.")
        self._advanced_group.setVisible(True)

        note_text = "Shell preview: PocketTTS settings are local only. No subprocess, backend, or audio path is started."
        if not self._shell_preview:
            note_text = "PocketTTS uses the bundled interpreter or the override path configured here."
        note.setText(note_text)

        self._widget = widget
        if not self._current_python():
            self._ensure_default_python()
        self._sync_widgets_from_runtime()
        return self._widget

    def export_session_state(self):
        return {
            "pocket_tts_python": self._current_python(),
            **self._current_generation_state(),
        }

    def export_preset_state(self):
        return {
            "pocket_tts_python": self._current_python(),
            **self._current_generation_state(),
        }

    def import_session_state(self, session):
        payload = with_flat_tts_runtime_settings(session or {})
        if "pocket_tts_python" in payload:
            self._set_python(str(payload.get("pocket_tts_python") or "").strip())
        elif not self._shell_preview and not self._current_python():
            self._ensure_default_python()
        mapping = {
            "pocket_tts_temperature": lambda v: max(0.05, float(v or 0.7)),
            "pocket_tts_lsd_decode_steps": lambda v: max(1, int(v or 1)),
            "pocket_tts_eos_threshold": lambda v: float(v if v is not None else -4.0),
            "pocket_tts_max_tokens": lambda v: max(1, int(v or 50)),
            "pocket_tts_frames_after_eos": lambda v: max(0, int(v or 0)),
        }
        for key, converter in mapping.items():
            if key not in payload:
                continue
            try:
                self._set_runtime(key, converter(payload.get(key)))
            except Exception:
                pass
        self._sync_widgets_from_runtime()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        return None
