from __future__ import annotations

import shiboken6


CHATTERBOX_TOOLTIPS = {
    "chatterbox_seed": "Seed for reproducible Chatterbox speech. Use 0 to pick a random seed each time.",
    "chatterbox_temperature": "Speech sampling randomness. Lower values are steadier; higher values can sound more varied.",
    "chatterbox_top_p": "Nucleus sampling limit for speech tokens. Lower values narrow the candidate pool.",
    "chatterbox_top_k": "Limits speech sampling to the top K candidates. Higher values allow more variation.",
    "chatterbox_repeat_penalty": "Penalty for repeated speech tokens. Higher values can reduce looping or stutters.",
    "chatterbox_min_p": "Minimum probability filter for speech token sampling. Higher values can make output more focused.",
    "chatterbox_normalize_loudness": "Normalize generated speech loudness toward -27 LUFS for steadier playback volume.",
}


class ChatterboxTTSController:
    STATE_KEY = "chatterbox_tts_settings"

    def __init__(self, context=None):
        self.context = context
        self.shell = context.get_service("qt.shell") if context is not None else None
        self._shell_preview = bool(
            context.get_service("qt.shell_preview") or context.get_service("qt.chatterbox_tts_shell_preview")
        ) if context is not None else False
        self._shell_state = self._initial_shell_state()
        self._widget = None
        self._build_pending = False
        self._seed_spin = None
        self._temperature_spin = None
        self._top_p_spin = None
        self._top_k_spin = None
        self._repeat_penalty_spin = None
        self._min_p_spin = None
        self._normalize_loudness_checkbox = None

    def _runtime_config_service(self):
        return self.context.get_service("qt.runtime_config") if self.context is not None else None

    def _initial_shell_state(self):
        if not self._shell_preview:
            return {}
        session_getter = self.context.get_service("qt.shell_session_snapshot") if self.context is not None else None
        session = {}
        if callable(session_getter):
            try:
                session = dict(session_getter() or {})
            except Exception:
                session = {}
        return {
            "tts_seed": int(session.get("tts_seed", 0) or 0),
            "tts_temperature": float(session.get("tts_temperature", 0.8) or 0.8),
            "tts_top_p": float(session.get("tts_top_p", 0.9) or 0.9),
            "tts_top_k": int(session.get("tts_top_k", 40) or 40),
            "tts_repeat_penalty": float(session.get("tts_repeat_penalty", 1.2) or 1.2),
            "tts_min_p": float(session.get("tts_min_p", 0.0) or 0.0),
            "tts_normalize_loudness": bool(session.get("tts_normalize_loudness", False)),
        }

    def _notify_settings_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def _current_state(self):
        if self._shell_preview:
            return dict(self._shell_state)
        runtime_config = self._runtime_config_service()
        getter = runtime_config.get if runtime_config is not None else (lambda _key, default=None: default)
        return {
            "tts_seed": int(getter("tts_seed", 0) or 0),
            "tts_temperature": float(getter("tts_temperature", 0.8) or 0.8),
            "tts_top_p": float(getter("tts_top_p", 0.9) or 0.9),
            "tts_top_k": int(getter("tts_top_k", 40) or 40),
            "tts_repeat_penalty": float(getter("tts_repeat_penalty", 1.2) or 1.2),
            "tts_min_p": float(getter("tts_min_p", 0.0) or 0.0),
            "tts_normalize_loudness": bool(getter("tts_normalize_loudness", False)),
        }

    def _set_runtime(self, key: str, value):
        if self._shell_preview:
            self._shell_state[str(key)] = value
            self._notify_settings_changed()
            return
        runtime_config = self._runtime_config_service()
        if runtime_config is not None:
            runtime_config.update(key, value)
        self._notify_settings_changed()

    def _sync_widgets_from_runtime(self):
        state = self._current_state()
        widgets = (
            ("_seed_spin", state["tts_seed"]),
            ("_temperature_spin", state["tts_temperature"]),
            ("_top_p_spin", state["tts_top_p"]),
            ("_top_k_spin", state["tts_top_k"]),
            ("_repeat_penalty_spin", state["tts_repeat_penalty"]),
            ("_min_p_spin", state["tts_min_p"]),
        )
        for attr, value in widgets:
            widget = getattr(self, attr, None)
            if not self._widget_alive(widget):
                continue
            widget.blockSignals(True)
            try:
                widget.setValue(value)
            except Exception:
                pass
            widget.blockSignals(False)
        checkbox = self._normalize_loudness_checkbox
        if self._widget_alive(checkbox):
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(state["tts_normalize_loudness"]))
            checkbox.blockSignals(False)

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

    def _set_tooltip_pair(self, widget, label_name, tooltip):
        tooltip = str(tooltip or "").strip()
        if not tooltip:
            return
        if self._widget_alive(widget) and hasattr(widget, "setToolTip"):
            widget.setToolTip(tooltip)
        label = self._ui_child(self._widget, label_name)
        if self._widget_alive(label) and hasattr(label, "setToolTip"):
            label.setToolTip(tooltip)

    def bind_designer_tab(self, widget):
        from PySide6 import QtWidgets

        if widget is None:
            raise RuntimeError("Chatterbox Designer UI did not provide a widget.")
        self._seed_spin = self._ui_child(widget, "chatterbox_seed_spin", QtWidgets.QSpinBox)
        self._temperature_spin = self._ui_child(widget, "chatterbox_temperature_spin", QtWidgets.QDoubleSpinBox)
        self._top_p_spin = self._ui_child(widget, "chatterbox_top_p_spin", QtWidgets.QDoubleSpinBox)
        self._top_k_spin = self._ui_child(widget, "chatterbox_top_k_spin", QtWidgets.QSpinBox)
        self._repeat_penalty_spin = self._ui_child(widget, "chatterbox_repeat_penalty_spin", QtWidgets.QDoubleSpinBox)
        self._min_p_spin = self._ui_child(widget, "chatterbox_min_p_spin", QtWidgets.QDoubleSpinBox)
        self._normalize_loudness_checkbox = self._ui_child(widget, "chatterbox_normalize_loudness_checkbox", QtWidgets.QCheckBox)
        info = self._ui_child(widget, "chatterbox_info_label", QtWidgets.QLabel)

        required = (
            self._seed_spin,
            self._temperature_spin,
            self._top_p_spin,
            self._top_k_spin,
            self._repeat_penalty_spin,
            self._min_p_spin,
            self._normalize_loudness_checkbox,
            info,
        )
        if any(item is None for item in required):
            raise RuntimeError("Chatterbox Designer UI is missing one or more required controls.")

        self._widget = widget

        self._seed_spin.setRange(0, 2 ** 31 - 1)
        self._set_tooltip_pair(self._seed_spin, "chatterbox_seed_label", CHATTERBOX_TOOLTIPS["chatterbox_seed"])
        self._seed_spin.valueChanged.connect(lambda value: self._set_runtime("tts_seed", max(0, int(value or 0))))

        self._temperature_spin.setRange(0.05, 2.0)
        self._temperature_spin.setSingleStep(0.05)
        self._temperature_spin.setDecimals(2)
        self._set_tooltip_pair(self._temperature_spin, "chatterbox_temperature_label", CHATTERBOX_TOOLTIPS["chatterbox_temperature"])
        self._temperature_spin.valueChanged.connect(lambda value: self._set_runtime("tts_temperature", max(0.05, float(value or 0.8))))

        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.01)
        self._top_p_spin.setDecimals(2)
        self._set_tooltip_pair(self._top_p_spin, "chatterbox_top_p_label", CHATTERBOX_TOOLTIPS["chatterbox_top_p"])
        self._top_p_spin.valueChanged.connect(lambda value: self._set_runtime("tts_top_p", max(0.0, min(1.0, float(value or 0.9)))))

        self._top_k_spin.setRange(0, 1000)
        self._top_k_spin.setSingleStep(1)
        self._set_tooltip_pair(self._top_k_spin, "chatterbox_top_k_label", CHATTERBOX_TOOLTIPS["chatterbox_top_k"])
        self._top_k_spin.valueChanged.connect(lambda value: self._set_runtime("tts_top_k", max(0, int(value or 0))))

        self._repeat_penalty_spin.setRange(1.0, 2.0)
        self._repeat_penalty_spin.setSingleStep(0.01)
        self._repeat_penalty_spin.setDecimals(2)
        self._set_tooltip_pair(self._repeat_penalty_spin, "chatterbox_repeat_penalty_label", CHATTERBOX_TOOLTIPS["chatterbox_repeat_penalty"])
        self._repeat_penalty_spin.valueChanged.connect(lambda value: self._set_runtime("tts_repeat_penalty", max(1.0, float(value or 1.2))))

        self._min_p_spin.setRange(0.0, 1.0)
        self._min_p_spin.setSingleStep(0.01)
        self._min_p_spin.setDecimals(2)
        self._set_tooltip_pair(self._min_p_spin, "chatterbox_min_p_label", CHATTERBOX_TOOLTIPS["chatterbox_min_p"])
        self._min_p_spin.valueChanged.connect(lambda value: self._set_runtime("tts_min_p", max(0.0, min(1.0, float(value or 0.0)))))

        self._normalize_loudness_checkbox.setToolTip(CHATTERBOX_TOOLTIPS["chatterbox_normalize_loudness"])
        self._normalize_loudness_checkbox.toggled.connect(lambda checked: self._set_runtime("tts_normalize_loudness", bool(checked)))

        info_text = "Shell preview: Chatterbox settings are local only. No model, backend, or audio path is started."
        if not self._shell_preview:
            info_text = "Chatterbox sampling controls for local speech generation."
        info.setText(info_text)

        self._sync_widgets_from_runtime()
        return self._widget

    def export_session_state(self):
        return self._current_state()

    def export_preset_state(self):
        return self._current_state()

    def import_session_state(self, session):
        if self._shell_preview:
            payload = dict(session or {})
            mapping = {
                "tts_seed": lambda v: max(0, int(v or 0)),
                "tts_temperature": lambda v: max(0.05, float(v or 0.8)),
                "tts_top_p": lambda v: max(0.0, min(1.0, float(v or 0.9))),
                "tts_top_k": lambda v: max(0, int(v or 0)),
                "tts_repeat_penalty": lambda v: max(1.0, float(v or 1.2)),
                "tts_min_p": lambda v: max(0.0, min(1.0, float(v or 0.0))),
                "tts_normalize_loudness": lambda v: bool(v),
            }
            changed = False
            for key, converter in mapping.items():
                if key not in payload:
                    continue
                try:
                    self._shell_state[key] = converter(payload.get(key))
                    changed = True
                except Exception:
                    pass
            if changed:
                self._sync_widgets_from_runtime()
                self._notify_settings_changed()
            return None
        payload = dict(session or {})
        changed = False
        mapping = {
            "tts_seed": lambda v: max(0, int(v or 0)),
            "tts_temperature": lambda v: max(0.05, float(v or 0.8)),
            "tts_top_p": lambda v: max(0.0, min(1.0, float(v or 0.9))),
            "tts_top_k": lambda v: max(0, int(v or 0)),
            "tts_repeat_penalty": lambda v: max(1.0, float(v or 1.2)),
            "tts_min_p": lambda v: max(0.0, min(1.0, float(v or 0.0))),
            "tts_normalize_loudness": lambda v: bool(v),
        }
        for key, converter in mapping.items():
            if key not in payload:
                continue
            try:
                self._set_runtime(key, converter(payload.get(key)))
                changed = True
            except Exception:
                pass
        if changed:
            self._sync_widgets_from_runtime()
            self._notify_settings_changed()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        return None
