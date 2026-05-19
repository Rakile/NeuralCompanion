from __future__ import annotations

import subprocess
import sys
import threading

import shiboken6

from core.tts_session_schema import with_flat_tts_runtime_settings


CHATTERBOX_MULTILINGUAL_SOURCE_URL = "https://github.com/resemble-ai/chatterbox/archive/refs/heads/master.zip"

CHATTERBOX_MULTILINGUAL_LANGUAGES = (
    ("English", "en"),
    ("Arabic", "ar"),
    ("Chinese", "zh"),
    ("Danish", "da"),
    ("Dutch", "nl"),
    ("Finnish", "fi"),
    ("German", "de"),
    ("Greek", "el"),
    ("French", "fr"),
    ("Hebrew", "he"),
    ("Hindi", "hi"),
    ("Italian", "it"),
    ("Japanese", "ja"),
    ("Korean", "ko"),
    ("Malay", "ms"),
    ("Norwegian", "no"),
    ("Polish", "pl"),
    ("Portuguese", "pt"),
    ("Russian", "ru"),
    ("Spanish", "es"),
    ("Swedish", "sv"),
    ("Swahili", "sw"),
    ("Turkish", "tr"),
)
DEFAULT_CHATTERBOX_MULTILINGUAL_LANGUAGE = "en"
DEFAULT_CHATTERBOX_MULTILINGUAL_TOP_P = 1.0
DEFAULT_CHATTERBOX_MULTILINGUAL_REPEAT_PENALTY = 2.0

SETTING_DEFAULTS = {
    "chatterbox_multilingual_seed": 0,
    "chatterbox_multilingual_temperature": 0.8,
    "chatterbox_multilingual_top_p": DEFAULT_CHATTERBOX_MULTILINGUAL_TOP_P,
    "chatterbox_multilingual_top_k": 40,
    "chatterbox_multilingual_repeat_penalty": DEFAULT_CHATTERBOX_MULTILINGUAL_REPEAT_PENALTY,
    "chatterbox_multilingual_normalize_loudness": False,
    "chatterbox_multilingual_prewarm_on_start": True,
    "chatterbox_multilingual_use_cloned_voice": True,
    "chatterbox_multilingual_apply_watermark": True,
}


def _normalize_language(value):
    text = str(value or "").strip().lower()
    for label, code in CHATTERBOX_MULTILINGUAL_LANGUAGES:
        if text in {label.lower(), code.lower()}:
            return code
    return DEFAULT_CHATTERBOX_MULTILINGUAL_LANGUAGE


class ChatterboxMultilingualTTSController:
    def __init__(self, context=None):
        self.context = context
        self.shell = context.get_service("qt.shell") if context is not None else None
        self._shell_preview = bool(context.get_service("qt.shell_preview")) if context is not None else False
        self._shell_language = self._initial_shell_language()
        self._shell_state = self._initial_shell_state()
        self._widget = None
        self._language_combo = None
        self._seed_spin = None
        self._temperature_spin = None
        self._top_p_spin = None
        self._top_k_spin = None
        self._repeat_penalty_spin = None
        self._normalize_loudness_checkbox = None
        self._prewarm_checkbox = None
        self._use_cloned_voice_checkbox = None
        self._apply_watermark_checkbox = None
        self._install_button = None
        self._install_status_label = None

    def _runtime_config_service(self):
        return self.context.get_service("qt.runtime_config") if self.context is not None else None

    def _initial_shell_language(self):
        if not self._shell_preview:
            return DEFAULT_CHATTERBOX_MULTILINGUAL_LANGUAGE
        session_getter = self.context.get_service("qt.shell_session_snapshot") if self.context is not None else None
        if callable(session_getter):
            try:
                session = with_flat_tts_runtime_settings(session_getter() or {})
                return _normalize_language(session.get("chatterbox_multilingual_language"))
            except Exception:
                pass
        return DEFAULT_CHATTERBOX_MULTILINGUAL_LANGUAGE

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
            "chatterbox_multilingual_seed": max(0, int(getter("chatterbox_multilingual_seed", 0) or 0)),
            "chatterbox_multilingual_temperature": max(
                0.05, float(getter("chatterbox_multilingual_temperature", 0.8) or 0.8)
            ),
            "chatterbox_multilingual_top_p": max(
                0.0,
                min(
                    1.0,
                    float(
                        getter(
                            "chatterbox_multilingual_top_p",
                            DEFAULT_CHATTERBOX_MULTILINGUAL_TOP_P,
                        )
                        or DEFAULT_CHATTERBOX_MULTILINGUAL_TOP_P
                    ),
                ),
            ),
            "chatterbox_multilingual_top_k": max(0, int(getter("chatterbox_multilingual_top_k", 40) or 40)),
            "chatterbox_multilingual_repeat_penalty": max(
                1.0,
                float(
                    getter(
                        "chatterbox_multilingual_repeat_penalty",
                        DEFAULT_CHATTERBOX_MULTILINGUAL_REPEAT_PENALTY,
                    )
                    or DEFAULT_CHATTERBOX_MULTILINGUAL_REPEAT_PENALTY
                ),
            ),
            "chatterbox_multilingual_normalize_loudness": bool(
                getter("chatterbox_multilingual_normalize_loudness", False)
            ),
            "chatterbox_multilingual_prewarm_on_start": bool(
                getter("chatterbox_multilingual_prewarm_on_start", True)
            ),
            "chatterbox_multilingual_use_cloned_voice": bool(
                getter("chatterbox_multilingual_use_cloned_voice", True)
            ),
            "chatterbox_multilingual_apply_watermark": bool(
                getter("chatterbox_multilingual_apply_watermark", True)
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
            return DEFAULT_CHATTERBOX_MULTILINGUAL_LANGUAGE
        return _normalize_language(service.get("chatterbox_multilingual_language", DEFAULT_CHATTERBOX_MULTILINGUAL_LANGUAGE))

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
            service.update("chatterbox_multilingual_language", language)
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
        if self._widget_alive(self._install_button):
            self._install_button.setEnabled(False)
        self._set_install_status("Installing/updating Chatterbox Multilingual runtime...")

        def worker():
            message = ""
            command = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--force-reinstall",
                "--no-deps",
                CHATTERBOX_MULTILINGUAL_SOURCE_URL,
            ]
            try:
                completed = subprocess.run(command, capture_output=True, text=True, timeout=900)
                lines = (completed.stdout or completed.stderr or "").strip().splitlines()
                tail = lines[-1] if lines else ""
                if completed.returncode == 0:
                    message = "Chatterbox Multilingual runtime updated from GitHub. Restart NC before using it."
                else:
                    message = f"Chatterbox Multilingual update failed with exit code {completed.returncode}."
                if tail:
                    message += f" Last output: {tail[:180]}"
            except Exception as exc:
                message = f"Chatterbox Multilingual update failed: {exc}"
            print(f"[ChatterboxMultilingual] {message}")
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

        threading.Thread(target=worker, name="nc-chatterbox-multilingual-install", daemon=True).start()

    def _sync_widgets_from_runtime(self):
        if self._widget_alive(self._language_combo):
            self._language_combo.blockSignals(True)
            index = self._language_combo.findData(self._current_language())
            if index < 0:
                index = self._language_combo.findData(DEFAULT_CHATTERBOX_MULTILINGUAL_LANGUAGE)
            if index >= 0:
                self._language_combo.setCurrentIndex(index)
            self._language_combo.blockSignals(False)
        state = self._current_state()
        for attr, key in (
            ("_seed_spin", "chatterbox_multilingual_seed"),
            ("_temperature_spin", "chatterbox_multilingual_temperature"),
            ("_top_p_spin", "chatterbox_multilingual_top_p"),
            ("_top_k_spin", "chatterbox_multilingual_top_k"),
            ("_repeat_penalty_spin", "chatterbox_multilingual_repeat_penalty"),
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
        for attr, key in (
            ("_normalize_loudness_checkbox", "chatterbox_multilingual_normalize_loudness"),
            ("_prewarm_checkbox", "chatterbox_multilingual_prewarm_on_start"),
            ("_use_cloned_voice_checkbox", "chatterbox_multilingual_use_cloned_voice"),
            ("_apply_watermark_checkbox", "chatterbox_multilingual_apply_watermark"),
        ):
            checkbox = getattr(self, attr, None)
            if self._widget_alive(checkbox):
                checkbox.blockSignals(True)
                checkbox.setChecked(bool(state[key]))
                checkbox.blockSignals(False)

    def bind_designer_tab(self, widget):
        from PySide6 import QtWidgets

        if widget is None:
            raise RuntimeError("Chatterbox Multilingual Designer UI did not provide a widget.")
        self._language_combo = self._ui_child(widget, "chatterbox_multilingual_language_combo", QtWidgets.QComboBox)
        self._seed_spin = self._ui_child(widget, "chatterbox_multilingual_seed_spin", QtWidgets.QSpinBox)
        self._temperature_spin = self._ui_child(widget, "chatterbox_multilingual_temperature_spin", QtWidgets.QDoubleSpinBox)
        self._top_p_spin = self._ui_child(widget, "chatterbox_multilingual_top_p_spin", QtWidgets.QDoubleSpinBox)
        self._top_k_spin = self._ui_child(widget, "chatterbox_multilingual_top_k_spin", QtWidgets.QSpinBox)
        self._repeat_penalty_spin = self._ui_child(widget, "chatterbox_multilingual_repeat_penalty_spin", QtWidgets.QDoubleSpinBox)
        self._normalize_loudness_checkbox = self._ui_child(widget, "chatterbox_multilingual_normalize_loudness_checkbox", QtWidgets.QCheckBox)
        self._prewarm_checkbox = self._ui_child(widget, "chatterbox_multilingual_prewarm_checkbox", QtWidgets.QCheckBox)
        self._use_cloned_voice_checkbox = self._ui_child(widget, "chatterbox_multilingual_use_cloned_voice_checkbox", QtWidgets.QCheckBox)
        self._apply_watermark_checkbox = self._ui_child(widget, "chatterbox_multilingual_apply_watermark_checkbox", QtWidgets.QCheckBox)
        self._install_button = self._ui_child(widget, "btn_chatterbox_multilingual_install", QtWidgets.QPushButton)
        self._install_status_label = self._ui_child(widget, "chatterbox_multilingual_install_status_label", QtWidgets.QLabel)
        note = self._ui_child(widget, "chatterbox_multilingual_note_label", QtWidgets.QLabel)
        required = (
            self._language_combo,
            self._seed_spin,
            self._temperature_spin,
            self._top_p_spin,
            self._top_k_spin,
            self._repeat_penalty_spin,
            self._normalize_loudness_checkbox,
            self._prewarm_checkbox,
            self._use_cloned_voice_checkbox,
            self._apply_watermark_checkbox,
            self._install_button,
            self._install_status_label,
            note,
        )
        if any(item is None for item in required):
            raise RuntimeError("Chatterbox Multilingual Designer UI is missing one or more required controls.")

        self._language_combo.blockSignals(True)
        self._language_combo.clear()
        for label, code in CHATTERBOX_MULTILINGUAL_LANGUAGES:
            self._language_combo.addItem(label, code)
        self._language_combo.blockSignals(False)
        self._language_combo.currentIndexChanged.connect(
            lambda _index: self._set_language(self._language_combo.currentData() or self._language_combo.currentText())
        )
        self._language_combo.setToolTip("Language ID passed to Chatterbox Multilingual generation.")

        self._seed_spin.setRange(0, 2 ** 31 - 1)
        self._seed_spin.valueChanged.connect(
            lambda value: self._set_runtime("chatterbox_multilingual_seed", max(0, int(value or 0)))
        )
        self._temperature_spin.setRange(0.05, 2.0)
        self._temperature_spin.setSingleStep(0.05)
        self._temperature_spin.setDecimals(2)
        self._temperature_spin.valueChanged.connect(
            lambda value: self._set_runtime("chatterbox_multilingual_temperature", max(0.05, float(value or 0.8)))
        )
        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.01)
        self._top_p_spin.setDecimals(2)
        self._top_p_spin.valueChanged.connect(
            lambda value: self._set_runtime(
                "chatterbox_multilingual_top_p",
                max(0.0, min(1.0, float(value or DEFAULT_CHATTERBOX_MULTILINGUAL_TOP_P))),
            )
        )
        self._top_k_spin.setRange(0, 1000)
        self._top_k_spin.valueChanged.connect(
            lambda value: self._set_runtime("chatterbox_multilingual_top_k", max(0, int(value or 0)))
        )
        self._repeat_penalty_spin.setRange(1.0, 2.0)
        self._repeat_penalty_spin.setSingleStep(0.01)
        self._repeat_penalty_spin.setDecimals(2)
        self._repeat_penalty_spin.valueChanged.connect(
            lambda value: self._set_runtime(
                "chatterbox_multilingual_repeat_penalty",
                max(1.0, float(value or DEFAULT_CHATTERBOX_MULTILINGUAL_REPEAT_PENALTY)),
            )
        )
        self._normalize_loudness_checkbox.toggled.connect(
            lambda checked: self._set_runtime("chatterbox_multilingual_normalize_loudness", bool(checked))
        )
        self._prewarm_checkbox.toggled.connect(
            lambda checked: self._set_runtime("chatterbox_multilingual_prewarm_on_start", bool(checked))
        )
        self._use_cloned_voice_checkbox.toggled.connect(
            lambda checked: self._set_runtime("chatterbox_multilingual_use_cloned_voice", bool(checked))
        )
        self._apply_watermark_checkbox.toggled.connect(
            lambda checked: self._set_runtime("chatterbox_multilingual_apply_watermark", bool(checked))
        )
        self._use_cloned_voice_checkbox.setToolTip(
            "When enabled, Chatterbox Multilingual conditions on the configured voice WAV. "
            "Disable it to use the model's built-in voice."
        )
        self._apply_watermark_checkbox.setToolTip(
            "Apply Chatterbox/Perth implicit watermarking to generated speech. "
            "Disable only if you want to avoid that extra processing."
        )
        self._install_button.clicked.connect(lambda _checked=False: self._install_or_update_runtime())
        note.setText(
            "Uses Chatterbox Multilingual from the official GitHub package. "
            "Use Install / Update if this runtime is missing, then restart NC."
        )
        note.setWordWrap(True)
        self._widget = widget
        self._sync_widgets_from_runtime()
        return self._widget

    def export_session_state(self):
        return {
            "chatterbox_multilingual_language": self._current_language(),
            **self._current_state(),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = with_flat_tts_runtime_settings(session or {})
        if "chatterbox_multilingual_language" in payload:
            self._set_language(payload.get("chatterbox_multilingual_language"))
        for key, value in self._coerce_state(payload).items():
            if key in payload:
                self._set_runtime(key, value)
        self._sync_widgets_from_runtime()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        return None
