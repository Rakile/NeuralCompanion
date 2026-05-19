from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import shiboken6

from core.pocket_tts_voices import (
    POCKET_TTS_BUILTIN_VOICE_CHOICES,
    normalize_pocket_tts_builtin_voice,
)
from core.tts_session_schema import with_flat_tts_runtime_settings


POCKET_TTS_MULTILINGUAL_LANGUAGES = (
    ("English", "en"),
    ("French", "fr"),
    ("German", "de"),
    ("Spanish", "es"),
    ("Portuguese", "pt"),
    ("Italian", "it"),
)
DEFAULT_POCKET_TTS_MULTILINGUAL_LANGUAGE = "en"

SETTING_DEFAULTS = {
    "pocket_tts_multilingual_temperature": 0.7,
    "pocket_tts_multilingual_lsd_decode_steps": 1,
    "pocket_tts_multilingual_eos_threshold": -4.0,
    "pocket_tts_multilingual_frames_after_eos": 0,
    "pocket_tts_multilingual_builtin_voice": "auto",
    "pocket_tts_multilingual_use_cloned_voice": True,
    "pocket_tts_multilingual_prewarm_on_start": True,
}


def _normalize_language(value):
    text = str(value or "").strip().lower()
    for label, code in POCKET_TTS_MULTILINGUAL_LANGUAGES:
        if text in {label.lower(), code.lower()}:
            return code
    return DEFAULT_POCKET_TTS_MULTILINGUAL_LANGUAGE


class PocketTTSMultilingualController:
    def __init__(self, context=None):
        self.context = context
        self.shell = context.get_service("qt.shell") if context is not None else None
        self._shell_preview = bool(context.get_service("qt.shell_preview")) if context is not None else False
        self._shell_language = self._initial_shell_language()
        self._shell_python = self._initial_shell_python()
        self._shell_state = self._initial_shell_state()
        self._widget = None
        self._language_combo = None
        self._python_edit = None
        self._bundled_label = None
        self._temperature_spin = None
        self._lsd_steps_spin = None
        self._eos_threshold_spin = None
        self._frames_after_eos_spin = None
        self._builtin_voice_combo = None
        self._use_cloned_voice_checkbox = None
        self._prewarm_checkbox = None
        self._install_button = None
        self._install_status_label = None

    def _runtime_config_service(self):
        return self.context.get_service("qt.runtime_config") if self.context is not None else None

    def _default_python(self) -> str:
        service = self._runtime_config_service()
        if service is None or not hasattr(service, "engine_attr"):
            return ""
        return str(service.engine_attr("DEFAULT_POCKET_TTS_PYTHON", "") or "").strip()

    def _initial_shell_language(self):
        if not self._shell_preview:
            return DEFAULT_POCKET_TTS_MULTILINGUAL_LANGUAGE
        session_getter = self.context.get_service("qt.shell_session_snapshot") if self.context is not None else None
        if callable(session_getter):
            try:
                session = with_flat_tts_runtime_settings(session_getter() or {})
                return _normalize_language(session.get("pocket_tts_multilingual_language"))
            except Exception:
                pass
        return DEFAULT_POCKET_TTS_MULTILINGUAL_LANGUAGE

    def _initial_shell_python(self):
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

    def _initial_shell_state(self):
        if not self._shell_preview:
            return dict(SETTING_DEFAULTS)
        session_getter = self.context.get_service("qt.shell_session_snapshot") if self.context is not None else None
        session = {}
        if callable(session_getter):
            try:
                session = with_flat_tts_runtime_settings(session_getter() or {})
            except Exception:
                session = {}
        return self._coerce_state(session)

    def _coerce_state(self, source):
        getter = dict(source or {}).get
        return {
            "pocket_tts_multilingual_temperature": max(
                0.05, float(getter("pocket_tts_multilingual_temperature", 0.7) or 0.7)
            ),
            "pocket_tts_multilingual_lsd_decode_steps": max(
                1, int(getter("pocket_tts_multilingual_lsd_decode_steps", 1) or 1)
            ),
            "pocket_tts_multilingual_eos_threshold": float(
                getter("pocket_tts_multilingual_eos_threshold", -4.0) or -4.0
            ),
            "pocket_tts_multilingual_frames_after_eos": max(
                0, int(getter("pocket_tts_multilingual_frames_after_eos", 0) or 0)
            ),
            "pocket_tts_multilingual_builtin_voice": normalize_pocket_tts_builtin_voice(
                getter("pocket_tts_multilingual_builtin_voice", "auto")
            ),
            "pocket_tts_multilingual_use_cloned_voice": bool(
                getter("pocket_tts_multilingual_use_cloned_voice", True)
            ),
            "pocket_tts_multilingual_prewarm_on_start": bool(
                getter("pocket_tts_multilingual_prewarm_on_start", True)
            ),
        }

    def _notify_settings_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def _current_language(self):
        if self._shell_preview:
            return _normalize_language(self._shell_language)
        service = self._runtime_config_service()
        if service is None:
            return DEFAULT_POCKET_TTS_MULTILINGUAL_LANGUAGE
        return _normalize_language(
            service.get("pocket_tts_multilingual_language", DEFAULT_POCKET_TTS_MULTILINGUAL_LANGUAGE)
        )

    def _current_python(self):
        if self._shell_preview:
            return str(self._shell_python or "").strip()
        service = self._runtime_config_service()
        if service is None:
            return ""
        return str(service.get("pocket_tts_python", "") or "").strip()

    def _current_state(self):
        if self._shell_preview:
            return self._coerce_state(self._shell_state)
        service = self._runtime_config_service()
        if service is None:
            return dict(SETTING_DEFAULTS)
        return self._coerce_state({key: service.get(key, default) for key, default in SETTING_DEFAULTS.items()})

    def _set_language(self, value):
        language = _normalize_language(value)
        if self._shell_preview:
            self._shell_language = language
            self._notify_settings_changed()
            return
        service = self._runtime_config_service()
        if service is not None:
            service.update("pocket_tts_multilingual_language", language)
        self._notify_settings_changed()

    def _set_python(self, value):
        value = str(value or "").strip()
        if self._shell_preview:
            self._shell_python = value
            self._notify_settings_changed()
            return
        service = self._runtime_config_service()
        if service is not None:
            service.update("pocket_tts_python", value)
        self._notify_settings_changed()

    def _set_runtime(self, key: str, value):
        if self._shell_preview:
            self._shell_state[str(key)] = value
            self._notify_settings_changed()
            return
        service = self._runtime_config_service()
        if service is not None:
            service.update(str(key), value)
        self._notify_settings_changed()

    def _ensure_default_python(self):
        current = self._current_python()
        if current:
            return current
        fallback = self._default_python()
        if fallback and Path(fallback).exists():
            if self._widget_alive(self._python_edit):
                self._python_edit.setText(fallback)
            self._set_python(fallback)
            return fallback
        return ""

    def _widget_alive(self, widget):
        if widget is None:
            return False
        try:
            return bool(shiboken6.isValid(widget))
        except Exception:
            return False

    def _ui_child(self, root, name, cls=None):
        if root is None:
            return None
        try:
            from PySide6 import QtCore

            return root.findChild(cls or QtCore.QObject, name)
        except Exception:
            return None

    def _set_install_status(self, text):
        if self._widget_alive(self._install_status_label):
            self._install_status_label.setText(str(text or ""))

    def _install_or_update_runtime(self):
        if self._shell_preview:
            self._set_install_status("Install is disabled in shell preview.")
            return
        python_exe = self._ensure_default_python()
        if not python_exe:
            self._set_install_status("No PocketTTS Python runtime found. Set the Python path first.")
            return
        if self._widget_alive(self._install_button):
            self._install_button.setEnabled(False)
        self._set_install_status("Installing/updating PocketTTS multilingual runtime...")

        def worker():
            message = ""
            command = [
                python_exe,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "https://github.com/kyutai-labs/pocket-tts/archive/refs/heads/main.zip",
            ]
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
                lines = (completed.stdout or completed.stderr or "").strip().splitlines()
                tail = lines[-1] if lines else ""
                if completed.returncode == 0:
                    message = "PocketTTS multilingual runtime updated. Restart NC before using it."
                else:
                    message = f"PocketTTS multilingual update failed with exit code {completed.returncode}."
                if tail:
                    message += f" Last output: {tail[:180]}"
            except Exception as exc:
                message = f"PocketTTS multilingual update failed: {exc}"
            print(f"[PocketTTSMultilingual] {message}")
            try:
                from PySide6 import QtCore

                QtCore.QTimer.singleShot(0, lambda: self._set_install_status(message))
                QtCore.QTimer.singleShot(
                    0,
                    lambda: self._install_button.setEnabled(True) if self._widget_alive(self._install_button) else None,
                )
            except Exception:
                self._set_install_status(message)
                if self._widget_alive(self._install_button):
                    self._install_button.setEnabled(True)

        threading.Thread(target=worker, name="nc-pockettts-multilingual-install", daemon=True).start()

    def _sync_widgets_from_runtime(self):
        if self._widget_alive(self._language_combo):
            self._language_combo.blockSignals(True)
            index = self._language_combo.findData(self._current_language())
            if index < 0:
                index = self._language_combo.findData(DEFAULT_POCKET_TTS_MULTILINGUAL_LANGUAGE)
            if index >= 0:
                self._language_combo.setCurrentIndex(index)
            self._language_combo.blockSignals(False)
        if self._widget_alive(self._python_edit):
            self._python_edit.blockSignals(True)
            self._python_edit.setText(self._current_python())
            self._python_edit.blockSignals(False)
        state = self._current_state()
        if self._widget_alive(self._builtin_voice_combo):
            self._builtin_voice_combo.blockSignals(True)
            index = self._builtin_voice_combo.findData(state["pocket_tts_multilingual_builtin_voice"])
            if index < 0:
                index = self._builtin_voice_combo.findData("auto")
            if index >= 0:
                self._builtin_voice_combo.setCurrentIndex(index)
            self._builtin_voice_combo.blockSignals(False)
        for attr, key in (
            ("_temperature_spin", "pocket_tts_multilingual_temperature"),
            ("_lsd_steps_spin", "pocket_tts_multilingual_lsd_decode_steps"),
            ("_eos_threshold_spin", "pocket_tts_multilingual_eos_threshold"),
            ("_frames_after_eos_spin", "pocket_tts_multilingual_frames_after_eos"),
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
        for widget, key in (
            (self._use_cloned_voice_checkbox, "pocket_tts_multilingual_use_cloned_voice"),
            (self._prewarm_checkbox, "pocket_tts_multilingual_prewarm_on_start"),
        ):
            if self._widget_alive(widget):
                widget.blockSignals(True)
                widget.setChecked(bool(state[key]))
                widget.blockSignals(False)

    def bind_designer_tab(self, widget):
        from PySide6 import QtWidgets

        if widget is None:
            raise RuntimeError("PocketTTS Multilingual Designer UI did not provide a widget.")
        self._language_combo = self._ui_child(widget, "pockettts_multilingual_language_combo", QtWidgets.QComboBox)
        self._python_edit = self._ui_child(widget, "pockettts_multilingual_python_edit", QtWidgets.QLineEdit)
        self._bundled_label = self._ui_child(widget, "pockettts_multilingual_bundled_label", QtWidgets.QLabel)
        self._temperature_spin = self._ui_child(widget, "pockettts_multilingual_temperature_spin", QtWidgets.QDoubleSpinBox)
        self._lsd_steps_spin = self._ui_child(widget, "pockettts_multilingual_lsd_steps_spin", QtWidgets.QSpinBox)
        self._eos_threshold_spin = self._ui_child(widget, "pockettts_multilingual_eos_threshold_spin", QtWidgets.QDoubleSpinBox)
        self._frames_after_eos_spin = self._ui_child(widget, "pockettts_multilingual_frames_after_eos_spin", QtWidgets.QSpinBox)
        self._builtin_voice_combo = self._ui_child(widget, "pockettts_multilingual_builtin_voice_combo", QtWidgets.QComboBox)
        self._use_cloned_voice_checkbox = self._ui_child(widget, "pockettts_multilingual_use_cloned_voice_checkbox", QtWidgets.QCheckBox)
        self._prewarm_checkbox = self._ui_child(widget, "pockettts_multilingual_prewarm_checkbox", QtWidgets.QCheckBox)
        self._install_button = self._ui_child(widget, "btn_pockettts_multilingual_install", QtWidgets.QPushButton)
        self._install_status_label = self._ui_child(widget, "pockettts_multilingual_install_status_label", QtWidgets.QLabel)
        note = self._ui_child(widget, "pockettts_multilingual_note_label", QtWidgets.QLabel)
        required = (
            self._language_combo,
            self._python_edit,
            self._bundled_label,
            self._temperature_spin,
            self._lsd_steps_spin,
            self._eos_threshold_spin,
            self._frames_after_eos_spin,
            self._builtin_voice_combo,
            self._use_cloned_voice_checkbox,
            self._prewarm_checkbox,
            self._install_button,
            self._install_status_label,
            note,
        )
        if any(item is None for item in required):
            raise RuntimeError("PocketTTS Multilingual Designer UI is missing one or more required controls.")

        self._language_combo.blockSignals(True)
        self._language_combo.clear()
        for label, code in POCKET_TTS_MULTILINGUAL_LANGUAGES:
            self._language_combo.addItem(label, code)
        self._language_combo.blockSignals(False)
        self._language_combo.currentIndexChanged.connect(
            lambda _index: self._set_language(self._language_combo.currentData() or self._language_combo.currentText())
        )
        self._language_combo.setToolTip("Language model passed to the PocketTTS multilingual runtime.")
        bundled_text = self._default_python() or "Bundled PocketTTS interpreter not found."
        if self._shell_preview:
            bundled_text = "Shell preview: bundled interpreter lookup is disabled."
        self._bundled_label.setText(f"Bundled interpreter: {bundled_text}")
        self._python_edit.setPlaceholderText("PocketTTS python.exe path")
        self._python_edit.editingFinished.connect(lambda: self._set_python(self._python_edit.text()))

        self._temperature_spin.setRange(0.05, 2.0)
        self._temperature_spin.setSingleStep(0.05)
        self._temperature_spin.setDecimals(2)
        self._temperature_spin.valueChanged.connect(
            lambda value: self._set_runtime("pocket_tts_multilingual_temperature", max(0.05, float(value or 0.7)))
        )
        self._lsd_steps_spin.setRange(1, 8)
        self._lsd_steps_spin.valueChanged.connect(
            lambda value: self._set_runtime("pocket_tts_multilingual_lsd_decode_steps", max(1, int(value or 1)))
        )
        self._eos_threshold_spin.setRange(-12.0, 0.0)
        self._eos_threshold_spin.setSingleStep(0.25)
        self._eos_threshold_spin.setDecimals(2)
        self._eos_threshold_spin.valueChanged.connect(
            lambda value: self._set_runtime(
                "pocket_tts_multilingual_eos_threshold", float(value if value is not None else -4.0)
            )
        )
        self._frames_after_eos_spin.setRange(0, 10)
        self._frames_after_eos_spin.valueChanged.connect(
            lambda value: self._set_runtime("pocket_tts_multilingual_frames_after_eos", max(0, int(value or 0)))
        )
        self._builtin_voice_combo.blockSignals(True)
        self._builtin_voice_combo.clear()
        for label, value in POCKET_TTS_BUILTIN_VOICE_CHOICES:
            self._builtin_voice_combo.addItem(label, value)
        self._builtin_voice_combo.blockSignals(False)
        self._builtin_voice_combo.setToolTip(
            "Built-in PocketTTS voice to use when cloned voice reference is disabled."
        )
        self._builtin_voice_combo.currentIndexChanged.connect(
            lambda _index: self._set_runtime(
                "pocket_tts_multilingual_builtin_voice",
                normalize_pocket_tts_builtin_voice(self._builtin_voice_combo.currentData()),
            )
        )
        self._use_cloned_voice_checkbox.setToolTip(
            "Use the configured avatar voice file as a PocketTTS voice prompt. Disable to use the built-in/default voice for the selected language."
        )
        self._use_cloned_voice_checkbox.toggled.connect(
            lambda checked: self._set_runtime("pocket_tts_multilingual_use_cloned_voice", bool(checked))
        )
        self._prewarm_checkbox.toggled.connect(
            lambda checked: self._set_runtime("pocket_tts_multilingual_prewarm_on_start", bool(checked))
        )
        self._install_button.clicked.connect(lambda _checked=False: self._install_or_update_runtime())
        note.setText(
            "Requires kyutai-labs/pocket-tts main with multilingual model loading. Use Install / Update if missing, then restart NC."
        )
        note.setWordWrap(True)
        self._widget = widget
        if not self._current_python():
            self._ensure_default_python()
        self._sync_widgets_from_runtime()
        return self._widget

    def export_session_state(self):
        return {
            "pocket_tts_multilingual_language": self._current_language(),
            "pocket_tts_python": self._current_python(),
            **self._current_state(),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = with_flat_tts_runtime_settings(session or {})
        if "pocket_tts_multilingual_language" in payload:
            self._set_language(payload.get("pocket_tts_multilingual_language"))
        if "pocket_tts_python" in payload:
            self._set_python(payload.get("pocket_tts_python"))
        for key, value in self._coerce_state(payload).items():
            if key in payload:
                self._set_runtime(key, value)
        self._sync_widgets_from_runtime()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        return None
