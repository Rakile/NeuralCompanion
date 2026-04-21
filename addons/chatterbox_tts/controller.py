from __future__ import annotations

import shiboken6

class ChatterboxTTSController:
    STATE_KEY = "chatterbox_tts_settings"

    def __init__(self, context=None):
        self.context = context
        self.shell = context.get_service("qt.shell") if context is not None else None
        self._widget = None
        self._build_pending = False
        self._seed_spin = None
        self._temperature_spin = None
        self._top_p_spin = None
        self._top_k_spin = None
        self._repeat_penalty_spin = None
        self._min_p_spin = None
        self._normalize_loudness_checkbox = None

    def _engine(self):
        import engine

        return engine

    def _notify_settings_changed(self):
        notifier = getattr(self.shell, "notify_settings_changed", None) if self.shell is not None else None
        if callable(notifier):
            notifier()

    def _current_state(self):
        engine = self._engine()
        return {
            "tts_seed": int(engine.RUNTIME_CONFIG.get("tts_seed", 0) or 0),
            "tts_temperature": float(engine.RUNTIME_CONFIG.get("tts_temperature", 0.8) or 0.8),
            "tts_top_p": float(engine.RUNTIME_CONFIG.get("tts_top_p", 0.9) or 0.9),
            "tts_top_k": int(engine.RUNTIME_CONFIG.get("tts_top_k", 40) or 40),
            "tts_repeat_penalty": float(engine.RUNTIME_CONFIG.get("tts_repeat_penalty", 1.2) or 1.2),
            "tts_min_p": float(engine.RUNTIME_CONFIG.get("tts_min_p", 0.0) or 0.0),
            "tts_normalize_loudness": bool(engine.RUNTIME_CONFIG.get("tts_normalize_loudness", False)),
        }

    def _set_runtime(self, key: str, value):
        engine = self._engine()
        engine.update_runtime_config(key, value)
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

    def build_tab(self):
        if self._widget is not None:
            return self._widget
        from PySide6 import QtCore, QtWidgets

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        card = QtWidgets.QGroupBox("Chatterbox Runtime")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(8)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        form.setSpacing(8)

        self._seed_spin = QtWidgets.QSpinBox()
        self._seed_spin.setRange(0, 2 ** 31 - 1)
        self._seed_spin.valueChanged.connect(lambda value: self._set_runtime("tts_seed", max(0, int(value or 0))))
        form.addRow("Random seed (0 = random)", self._seed_spin)

        self._temperature_spin = QtWidgets.QDoubleSpinBox()
        self._temperature_spin.setRange(0.05, 2.0)
        self._temperature_spin.setSingleStep(0.05)
        self._temperature_spin.setDecimals(2)
        self._temperature_spin.valueChanged.connect(lambda value: self._set_runtime("tts_temperature", max(0.05, float(value or 0.8))))
        form.addRow("Temperature", self._temperature_spin)

        self._top_p_spin = QtWidgets.QDoubleSpinBox()
        self._top_p_spin.setRange(0.0, 1.0)
        self._top_p_spin.setSingleStep(0.01)
        self._top_p_spin.setDecimals(2)
        self._top_p_spin.valueChanged.connect(lambda value: self._set_runtime("tts_top_p", max(0.0, min(1.0, float(value or 0.9)))))
        form.addRow("Top P", self._top_p_spin)

        self._top_k_spin = QtWidgets.QSpinBox()
        self._top_k_spin.setRange(0, 1000)
        self._top_k_spin.setSingleStep(1)
        self._top_k_spin.valueChanged.connect(lambda value: self._set_runtime("tts_top_k", max(0, int(value or 0))))
        form.addRow("Top K", self._top_k_spin)

        self._repeat_penalty_spin = QtWidgets.QDoubleSpinBox()
        self._repeat_penalty_spin.setRange(1.0, 2.0)
        self._repeat_penalty_spin.setSingleStep(0.01)
        self._repeat_penalty_spin.setDecimals(2)
        self._repeat_penalty_spin.valueChanged.connect(lambda value: self._set_runtime("tts_repeat_penalty", max(1.0, float(value or 1.2))))
        form.addRow("Repetition Penalty", self._repeat_penalty_spin)

        self._min_p_spin = QtWidgets.QDoubleSpinBox()
        self._min_p_spin.setRange(0.0, 1.0)
        self._min_p_spin.setSingleStep(0.01)
        self._min_p_spin.setDecimals(2)
        self._min_p_spin.valueChanged.connect(lambda value: self._set_runtime("tts_min_p", max(0.0, min(1.0, float(value or 0.0)))))
        form.addRow("Min P", self._min_p_spin)

        self._normalize_loudness_checkbox = QtWidgets.QCheckBox("Normalize Loudness (-27 LUFS)")
        self._normalize_loudness_checkbox.toggled.connect(lambda checked: self._set_runtime("tts_normalize_loudness", bool(checked)))
        form.addRow("", self._normalize_loudness_checkbox)

        card_layout.addLayout(form)
        info = QtWidgets.QLabel("Chatterbox sampling controls for local speech generation.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        card_layout.addWidget(info)

        layout.addWidget(card)
        layout.addStretch(1)
        self._widget = widget
        self._sync_widgets_from_runtime()
        return self._widget

    def export_session_state(self):
        return self._current_state()

    def export_preset_state(self):
        return self._current_state()

    def import_session_state(self, session):
        engine = self._engine()
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
                engine.update_runtime_config(key, converter(payload.get(key)))
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
