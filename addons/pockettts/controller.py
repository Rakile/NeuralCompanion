from __future__ import annotations

import shiboken6
from pathlib import Path

class PocketTTSController:
    STATE_KEY = "pocket_tts_settings"

    def __init__(self, context=None):
        self.context = context
        self.dialogs = context.get_service("qt.dialogs") if context is not None else None
        self.shell = context.get_service("qt.shell") if context is not None else None
        self._shell_preview = bool(context.get_service("qt.pockettts_shell_preview")) if context is not None else False
        self._shell_python = self._initial_shell_python()
        self._widget = None
        self._advanced_group = None
        self._advanced_toggle = None
        self._python_edit = None
        self._bundled_label = None

    def _engine(self):
        import engine

        return engine

    def _initial_shell_python(self) -> str:
        if not self._shell_preview:
            return ""
        session_getter = self.context.get_service("qt.shell_session_snapshot") if self.context is not None else None
        if callable(session_getter):
            try:
                session = dict(session_getter() or {})
                return str(session.get("pocket_tts_python", "") or "").strip()
            except Exception:
                return ""
        return ""

    def _notify_settings_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def _current_python(self) -> str:
        if self._shell_preview:
            return str(self._shell_python or "").strip()
        engine = self._engine()
        return str(engine.RUNTIME_CONFIG.get("pocket_tts_python", "") or "").strip()

    def _set_python(self, value: str):
        if self._shell_preview:
            self._shell_python = str(value or "").strip()
            self._notify_settings_changed()
            return
        engine = self._engine()
        engine.update_runtime_config("pocket_tts_python", str(value or "").strip())
        self._notify_settings_changed()

    def _ensure_default_python(self):
        if self._shell_preview:
            return self._current_python()
        engine = self._engine()
        current = self._current_python()
        if current:
            return current
        fallback = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
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
        engine = self._engine()
        fallback = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()
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
        engine = None if self._shell_preview else self._engine()
        self._advanced_group = self._ui_child(widget, "pockettts_advanced_group", QtWidgets.QGroupBox)
        self._advanced_toggle = self._ui_child(widget, "btn_pockettts_advanced_toggle", QtWidgets.QPushButton)
        self._python_edit = self._ui_child(widget, "pockettts_python_edit", QtWidgets.QLineEdit)
        self._bundled_label = self._ui_child(widget, "pockettts_bundled_label", QtWidgets.QLabel)
        browse = self._ui_child(widget, "btn_pockettts_browse", QtWidgets.QPushButton)
        bundled_button = self._ui_child(widget, "btn_pockettts_use_bundled", QtWidgets.QPushButton)
        note = self._ui_child(widget, "pockettts_note_label", QtWidgets.QLabel)

        required = (
            self._advanced_group,
            self._python_edit,
            self._bundled_label,
            browse,
            bundled_button,
            note,
        )
        if any(item is None for item in required):
            raise RuntimeError("PocketTTS Designer UI is missing one or more required controls.")

        bundled_text = "Shell preview: bundled interpreter lookup is disabled."
        if engine is not None:
            bundled_text = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip() or "Bundled PocketTTS interpreter not found."
        self._bundled_label.setText(f"Bundled interpreter: {bundled_text}")
        self._python_edit.setPlaceholderText("Optional override path to PocketTTS python.exe")
        self._python_edit.editingFinished.connect(lambda: self._set_python(self._python_edit.text()))
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

    def build_tab(self):
        if self._widget is not None:
            return self._widget
        from PySide6 import QtWidgets
        engine = None if self._shell_preview else self._engine()

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = QtWidgets.QGroupBox("PocketTTS Runtime")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(8)

        info = QtWidgets.QLabel(
            "PocketTTS is bundled with Neural Interface and is used automatically when selected."
        )
        info.setWordWrap(True)
        card_layout.addWidget(info)

        #self._advanced_toggle = QtWidgets.QPushButton("Show Advanced PocketTTS Override")
        #self._advanced_toggle.setCheckable(True)
        #self._advanced_toggle.toggled.connect(self._toggle_advanced)
        #card_layout.addWidget(self._advanced_toggle)

        self._advanced_group = QtWidgets.QGroupBox("Advanced PocketTTS Override")
        advanced_layout = QtWidgets.QVBoxLayout(self._advanced_group)
        bundled_text = "Shell preview: bundled interpreter lookup is disabled."
        if engine is not None:
            bundled_text = str(getattr(engine, "DEFAULT_POCKET_TTS_PYTHON", "") or "").strip() or "Bundled PocketTTS interpreter not found."
        self._bundled_label = QtWidgets.QLabel(f"Bundled interpreter: {bundled_text}")
        self._bundled_label.setWordWrap(True)
        advanced_layout.addWidget(self._bundled_label)

        advanced_layout.addWidget(QtWidgets.QLabel("PocketTTS Python Override"))
        row = QtWidgets.QHBoxLayout()
        self._python_edit = QtWidgets.QLineEdit()
        self._python_edit.setPlaceholderText("Optional override path to PocketTTS python.exe")
        self._python_edit.editingFinished.connect(lambda: self._set_python(self._python_edit.text()))
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse_python)
        if self._shell_preview:
            browse.setEnabled(False)
            browse.setToolTip("Disabled in shell preview; no file dialogs or runtime config writes are connected.")
        row.addWidget(self._python_edit, 1)
        row.addWidget(browse)
        advanced_layout.addLayout(row)

        bundled_button = QtWidgets.QPushButton("Use Bundled PocketTTS")
        bundled_button.clicked.connect(self._reset_to_default)
        advanced_layout.addWidget(bundled_button)
        self._advanced_group.setVisible(True)
        card_layout.addWidget(self._advanced_group)

        note_text = "Shell preview: PocketTTS settings are local only. No subprocess, backend, or audio path is started."
        if not self._shell_preview:
            note_text = "PocketTTS uses the bundled interpreter or the override path configured here."
        note = QtWidgets.QLabel(note_text)
        note.setWordWrap(True)
        note.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        card_layout.addWidget(note)

        layout.addWidget(card)
        layout.addStretch(1)
        self._widget = widget
        if not self._current_python():
            self._ensure_default_python()
        self._sync_widgets_from_runtime()
        return self._widget

    def export_session_state(self):
        return {
            "pocket_tts_python": self._current_python(),
        }

    def export_preset_state(self):
        return {
            "pocket_tts_python": self._current_python(),
        }

    def import_session_state(self, session):
        payload = dict(session or {})
        if "pocket_tts_python" in payload:
            self._set_python(str(payload.get("pocket_tts_python") or "").strip())
        elif not self._shell_preview and not self._current_python():
            self._ensure_default_python()
        self._sync_widgets_from_runtime()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        return None
