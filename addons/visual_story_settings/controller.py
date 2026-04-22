from __future__ import annotations

import shiboken6
from PySide6 import QtCore, QtWidgets


class VisualStorySettingsController:
    def __init__(self, context):
        self.context = context
        self.shell = context.get_service("qt.shell") if context is not None else None
        self.visual_reply_service = context.get_service("qt.visual_reply") if context is not None else None
        self.tab_widget = None
        self.story_mode_button = None
        self.max_images_spin = None
        self.continuity_slider = None
        self.continuity_value_label = None
        self.theme_buttons = {}
        self.theme_edits = {}
        self.master_prompt_edit = None
        self.safe_checkbox = None
        self.no_speech_bubbles_checkbox = None
        self.hint_label = None

    def _engine(self):
        import engine

        return engine

    def _visual_config_service(self):
        service = self.visual_reply_service
        if service is not None and hasattr(service, "get_runtime_config") and hasattr(service, "update_runtime_config"):
            return service
        return None

    def _runtime_config_get(self, key, default=None):
        service = self._visual_config_service()
        if service is not None:
            return service.get_runtime_config(str(key), default)
        return self._engine().RUNTIME_CONFIG.get(str(key), default)

    def _runtime_config_set(self, key, value):
        service = self._visual_config_service()
        if service is not None:
            service.update_runtime_config(str(key), value)
            return
        self._engine().update_runtime_config(str(key), value)

    def build_tab(self):
        if self.tab_widget is not None:
            return self.tab_widget

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)

        container = QtWidgets.QWidget()
        scroll.setWidget(container)

        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        box = QtWidgets.QGroupBox("Story Visual Replies")
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.setContentsMargins(12, 14, 12, 12)
        box_layout.setSpacing(10)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
        form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

        self.story_mode_button = QtWidgets.QPushButton("Story Mode")
        self.story_mode_button.setCheckable(True)
        self.story_mode_button.setToolTip("Generate visual replies for spoken story chunks, up to the max picture limit.")
        self.story_mode_button.setStyleSheet(
            "QPushButton { padding: 6px 12px; }"
            "QPushButton:checked { background: #4d8dff; color: white; border: 1px solid #6a95ff; }"
        )
        self.story_mode_button.toggled.connect(self._on_story_mode_changed)
        form.addRow("Story Mode", self.story_mode_button)

        self.max_images_spin = QtWidgets.QSpinBox()
        self.max_images_spin.setRange(1, 20)
        self.max_images_spin.setToolTip("Maximum number of images to request during one story-mode reply.")
        self.max_images_spin.valueChanged.connect(self._on_max_images_changed)
        form.addRow("Max Pictures", self.max_images_spin)

        continuity_row = QtWidgets.QHBoxLayout()
        self.continuity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.continuity_slider.setRange(0, 100)
        self.continuity_slider.valueChanged.connect(self._on_continuity_changed)
        continuity_row.addWidget(self.continuity_slider, 1)
        self.continuity_value_label = QtWidgets.QLabel("80%")
        self.continuity_value_label.setMinimumWidth(52)
        self.continuity_value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        continuity_row.addWidget(self.continuity_value_label)
        continuity_widget = QtWidgets.QWidget()
        continuity_widget.setLayout(continuity_row)
        form.addRow("Continuity", continuity_widget)

        box_layout.addLayout(form)

        theme_widget = QtWidgets.QWidget()
        theme_layout = QtWidgets.QGridLayout(theme_widget)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.setHorizontalSpacing(10)
        theme_layout.setVerticalSpacing(6)
        button_style = (
            "QPushButton { padding: 6px 10px; }"
            "QPushButton:checked { background: #4d8dff; color: white; border: 1px solid #6a95ff; }"
        )
        for index, preset in enumerate(self._theme_presets()):
            theme_id = str(preset.get("id") or "").strip().lower()
            if not theme_id:
                continue
            column = index % 3
            row = (index // 3) * 2
            button = QtWidgets.QPushButton(str(preset.get("label") or theme_id.title()))
            button.setCheckable(True)
            button.setStyleSheet(button_style)
            button.toggled.connect(lambda checked, theme_id=theme_id: self._on_theme_toggled(theme_id, checked))
            edit = QtWidgets.QLineEdit()
            edit.setClearButtonEnabled(True)
            edit.editingFinished.connect(lambda theme_id=theme_id, edit=edit: self._on_theme_prompt_changed(theme_id, edit.text()))
            theme_layout.addWidget(button, row, column)
            theme_layout.addWidget(edit, row + 1, column)
            theme_layout.setColumnStretch(column, 1)
            self.theme_buttons[theme_id] = button
            self.theme_edits[theme_id] = edit
        box_layout.addWidget(QtWidgets.QLabel("Styles"))
        box_layout.addWidget(theme_widget)

        guard_row = QtWidgets.QHBoxLayout()
        guard_row.setContentsMargins(0, 0, 0, 0)
        guard_row.setSpacing(8)
        self.safe_checkbox = QtWidgets.QCheckBox("Safe")
        self.safe_checkbox.toggled.connect(self._on_safe_changed)
        self.no_speech_bubbles_checkbox = QtWidgets.QCheckBox("No Speech Bubbles")
        self.no_speech_bubbles_checkbox.toggled.connect(self._on_no_speech_bubbles_changed)
        guard_row.addWidget(self.safe_checkbox)
        guard_row.addWidget(self.no_speech_bubbles_checkbox)
        guard_row.addStretch(1)
        box_layout.addLayout(guard_row)

        self.master_prompt_edit = QtWidgets.QPlainTextEdit()
        self.master_prompt_edit.setPlaceholderText("Optional master style anchor...")
        self.master_prompt_edit.setMinimumHeight(72)
        self.master_prompt_edit.setMaximumHeight(120)
        self.master_prompt_edit.textChanged.connect(self._on_master_prompt_changed)
        box_layout.addWidget(QtWidgets.QLabel("Master Style Anchor"))
        box_layout.addWidget(self.master_prompt_edit)

        self.hint_label = QtWidgets.QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        box_layout.addWidget(self.hint_label)

        layout.addWidget(box)
        layout.addStretch(1)

        self.tab_widget = scroll
        self._sync_widgets_from_runtime()
        self._refresh_hint()
        return scroll

    def export_session_state(self):
        return {
            "visual_reply_story_mode": bool(self._runtime_config_get("visual_reply_story_mode", False)),
            "visual_reply_story_max_images": self._max_images(),
            "visual_reply_story_continuity_strength": self._continuity_strength(),
            "visual_reply_story_theme_prompts": self._current_theme_prompts(),
            "visual_reply_story_theme_enabled": self._current_theme_enabled(),
            "visual_reply_master_style_prompt": self._master_prompt(),
            "visual_reply_master_prompt_safe": bool(self._runtime_config_get("visual_reply_master_prompt_safe", False)),
            "visual_reply_master_prompt_no_speech_bubbles": bool(self._runtime_config_get("visual_reply_master_prompt_no_speech_bubbles", False)),
        }

    def _widget_alive(self, widget):
        if widget is None:
            return False
        try:
            return bool(shiboken6.isValid(widget))
        except Exception:
            return False

    def import_session_state(self, session):
        payload = dict(session or {})
        for key in (
            "visual_reply_story_mode",
            "visual_reply_story_max_images",
            "visual_reply_story_continuity_strength",
            "visual_reply_story_theme_prompts",
            "visual_reply_story_theme_enabled",
            "visual_reply_master_style_prompt",
            "visual_reply_master_prompt_safe",
            "visual_reply_master_prompt_no_speech_bubbles",
        ):
            if key in payload:
                self._set_runtime_config(key, payload.get(key), notify=False)
        self._sync_widgets_from_runtime()
        self._refresh_hint()

    def _theme_presets(self):
        service = self._visual_config_service()
        if service is not None and hasattr(service, "story_theme_presets"):
            return list(service.story_theme_presets() or ())
        return list(getattr(self._engine(), "VISUAL_REPLY_STORY_THEME_PRESETS", ()) or ())

    def _default_theme_prompts(self):
        prompts = {}
        for preset in self._theme_presets():
            theme_id = str(preset.get("id") or "").strip().lower()
            if theme_id:
                prompts[theme_id] = str(preset.get("prompt") or "").strip()
        return prompts

    def _theme_labels(self):
        labels = {}
        for preset in self._theme_presets():
            theme_id = str(preset.get("id") or "").strip().lower()
            if theme_id:
                labels[theme_id] = str(preset.get("label") or theme_id.title()).strip()
        return labels

    def _normalize_theme_prompts(self, payload=None):
        raw = payload if payload is not None else self._runtime_config_get("visual_reply_story_theme_prompts", {})
        if not isinstance(raw, dict):
            raw = {}
        defaults = self._default_theme_prompts()
        prompts = {}
        for theme_id, default_prompt in defaults.items():
            prompt = str(raw.get(theme_id, default_prompt) or "").strip()
            prompts[theme_id] = prompt or default_prompt
        return prompts

    def _normalize_theme_enabled(self, payload=None):
        raw = payload if payload is not None else self._runtime_config_get("visual_reply_story_theme_enabled", [])
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            raw = []
        labels = self._theme_labels()
        enabled = []
        seen = set()
        for value in raw:
            theme_id = str(value or "").strip().lower()
            if not theme_id or theme_id not in labels or theme_id in seen:
                continue
            enabled.append(theme_id)
            seen.add(theme_id)
        return enabled

    def _current_theme_prompts(self):
        prompts = self._normalize_theme_prompts()
        for theme_id, edit in dict(self.theme_edits or {}).items():
            if theme_id in prompts and self._widget_alive(edit):
                prompts[theme_id] = str(edit.text() or "").strip() or prompts[theme_id]
        return prompts

    def _current_theme_enabled(self):
        if not self.theme_buttons:
            return self._normalize_theme_enabled()
        enabled = []
        for preset in self._theme_presets():
            theme_id = str(preset.get("id") or "").strip().lower()
            button = self.theme_buttons.get(theme_id)
            if self._widget_alive(button) and button.isChecked():
                enabled.append(theme_id)
        return enabled

    def _continuity_strength(self):
        if self._widget_alive(self.continuity_slider):
            return max(0.0, min(1.0, float(self.continuity_slider.value()) / 100.0))
        try:
            value = float(self._runtime_config_get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            value = 0.8
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _max_images(self):
        if self._widget_alive(self.max_images_spin):
            return max(1, int(self.max_images_spin.value()))
        try:
            return max(1, int(self._runtime_config_get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            return 3

    def _master_prompt(self):
        if self._widget_alive(self.master_prompt_edit):
            return str(self.master_prompt_edit.toPlainText() or "").strip()
        return str(self._runtime_config_get("visual_reply_master_style_prompt", "") or "").strip()

    def _set_runtime_config(self, key, value, *, notify=True):
        self._runtime_config_set(str(key), value)
        if notify:
            self._refresh_hint()
            if self.visual_reply_service is not None:
                try:
                    self.visual_reply_service.refresh_hint()
                except Exception:
                    pass
            if self.shell is not None:
                try:
                    self.shell.notify_settings_changed()
                except Exception:
                    pass

    def _sync_widgets_from_runtime(self):
        if self.story_mode_button is None:
            return
        self.story_mode_button.blockSignals(True)
        self.story_mode_button.setChecked(bool(self._runtime_config_get("visual_reply_story_mode", False)))
        self.story_mode_button.blockSignals(False)

        self.max_images_spin.blockSignals(True)
        self.max_images_spin.setValue(self._max_images())
        self.max_images_spin.blockSignals(False)

        percent = int(round(self._continuity_strength() * 100.0))
        self.continuity_slider.blockSignals(True)
        self.continuity_slider.setValue(percent)
        self.continuity_slider.blockSignals(False)
        self.continuity_value_label.setText(f"{percent}%")

        prompts = self._normalize_theme_prompts()
        enabled = set(self._normalize_theme_enabled())
        for theme_id, button in dict(self.theme_buttons or {}).items():
            button.blockSignals(True)
            button.setChecked(theme_id in enabled)
            button.blockSignals(False)
        for theme_id, edit in dict(self.theme_edits or {}).items():
            edit.blockSignals(True)
            edit.setText(prompts.get(theme_id, ""))
            edit.blockSignals(False)

        self.master_prompt_edit.blockSignals(True)
        self.master_prompt_edit.setPlainText(str(self._runtime_config_get("visual_reply_master_style_prompt", "") or "").strip())
        self.master_prompt_edit.blockSignals(False)

        self.safe_checkbox.blockSignals(True)
        self.safe_checkbox.setChecked(bool(self._runtime_config_get("visual_reply_master_prompt_safe", False)))
        self.safe_checkbox.blockSignals(False)

        self.no_speech_bubbles_checkbox.blockSignals(True)
        self.no_speech_bubbles_checkbox.setChecked(bool(self._runtime_config_get("visual_reply_master_prompt_no_speech_bubbles", False)))
        self.no_speech_bubbles_checkbox.blockSignals(False)

    def _refresh_hint(self):
        if self.hint_label is None:
            return
        story_mode = bool(self._runtime_config_get("visual_reply_story_mode", False))
        max_images = self._max_images()
        continuity_percent = int(round(self._continuity_strength() * 100.0))
        labels = self._theme_labels()
        active_labels = [labels.get(theme_id, theme_id.title()) for theme_id in self._normalize_theme_enabled()]
        guard_parts = []
        if bool(self._runtime_config_get("visual_reply_master_prompt_safe", False)):
            guard_parts.append("Safe")
        if bool(self._runtime_config_get("visual_reply_master_prompt_no_speech_bubbles", False)):
            guard_parts.append("No Speech Bubbles")
        parts = [
            f"Story Mode is {'on' if story_mode else 'off'}; when enabled, NC can request one image per spoken chunk, up to {max_images} picture(s), with continuity at {continuity_percent}%."
        ]
        if active_labels:
            parts.append(f"Active story styles: {', '.join(active_labels)}.")
        if self._master_prompt():
            parts.append("Master style anchor is active.")
        if guard_parts:
            parts.append(f"Master prompt guards: {', '.join(guard_parts)}.")
        self.hint_label.setText(" ".join(parts))

    def _on_story_mode_changed(self, checked):
        self._set_runtime_config("visual_reply_story_mode", bool(checked))

    def _on_max_images_changed(self, value):
        self._set_runtime_config("visual_reply_story_max_images", max(1, int(value or 1)))

    def _on_continuity_changed(self, value):
        strength = max(0.0, min(1.0, float(value or 0) / 100.0))
        if self.continuity_value_label is not None:
            self.continuity_value_label.setText(f"{int(round(strength * 100.0))}%")
        self._set_runtime_config("visual_reply_story_continuity_strength", strength)

    def _on_theme_toggled(self, _theme_id, _checked):
        self._set_runtime_config("visual_reply_story_theme_enabled", self._current_theme_enabled())
        self._set_runtime_config("visual_reply_story_theme_prompts", self._current_theme_prompts())

    def _on_theme_prompt_changed(self, _theme_id, _text):
        self._set_runtime_config("visual_reply_story_theme_prompts", self._current_theme_prompts())

    def _on_master_prompt_changed(self):
        self._set_runtime_config("visual_reply_master_style_prompt", self._master_prompt())

    def _on_safe_changed(self, checked):
        self._set_runtime_config("visual_reply_master_prompt_safe", bool(checked))

    def _on_no_speech_bubbles_changed(self, checked):
        self._set_runtime_config("visual_reply_master_prompt_no_speech_bubbles", bool(checked))
