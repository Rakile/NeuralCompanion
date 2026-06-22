from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import NoWheelTabWidget


from ui.runtime.engine_access import engine_module as _engine


def _sensory():
    from core import sensory

    return sensory


COMPANION_ORB_PROVIDER_ID = "companion_orb_target"

SENSORY_SOURCE_UI_COPY = {
    "screen": {
        "label": "Screen",
        "checkbox": "Screen",
        "tab_label": "Screen",
        "kind": "Visual",
        "tooltip": "Uses the current screen or configured screen region as background visual context.",
        "description": "Current screen or configured capture region.",
    },
    "webcam": {
        "label": "Webcam",
        "checkbox": "Webcam",
        "tab_label": "Webcam",
        "kind": "Visual",
        "tooltip": "Uses the latest webcam frame as background visual context.",
        "description": "Camera image from the selected webcam.",
    },
    COMPANION_ORB_PROVIDER_ID: {
        "label": "Orb Target",
        "checkbox": "Orb target",
        "tab_label": "Orb",
        "kind": "Region",
        "tooltip": "Uses the Companion Orb selected target. If the target is missing, it reports that instead of silently using full-screen capture.",
        "description": "Selected window, region, or full-screen context map from Companion Orb.",
    },
    "clipboard": {
        "label": "Clipboard",
        "checkbox": "Clipboard",
        "tab_label": "Clipboard",
        "kind": "Visual",
        "tooltip": "Uses the latest copied image when Clipboard Source has one available.",
        "description": "Most recent image copied to the clipboard.",
    },
    "heart_rate": {
        "label": "Heart Rate",
        "checkbox": "Heart rate",
        "tab_label": "Heart Rate",
        "kind": "Body",
        "tooltip": "Uses heart-rate metadata as background text context.",
        "description": "Pulse, BPM, and state metadata.",
    },
    "spotify_sense": {
        "label": "Spotify",
        "checkbox": "Spotify",
        "tab_label": "Spotify",
        "kind": "Music",
        "tooltip": "Uses current Spotify track metadata as music context. It does not analyze raw audio.",
        "description": "Current song, artist, playback state, and freshness metadata.",
    },
}


class BackendSensoryConfigMixin:
    def _sensory_source_ui_copy(self, provider_id):
        return dict(SENSORY_SOURCE_UI_COPY.get(str(provider_id or "").strip().lower(), {}) or {})

    def _sensory_source_display_label(self, provider_id, fallback="", *, checkbox=False):
        copy = self._sensory_source_ui_copy(provider_id)
        key = "checkbox" if checkbox else "label"
        label = str(copy.get(key) or "").strip()
        return label or str(fallback or provider_id or "Source").strip() or "Source"

    def _sensory_source_tab_label(self, provider_id, fallback=""):
        copy = self._sensory_source_ui_copy(provider_id)
        label = str(copy.get("tab_label") or "").strip()
        return label or self._sensory_source_display_label(provider_id, fallback)

    def _sensory_source_kind(self, provider_id):
        copy = self._sensory_source_ui_copy(provider_id)
        return str(copy.get("kind") or "Source").strip() or "Source"

    def _format_sensory_seconds(self, value):
        seconds = max(0.0, float(value or 0.0))
        rounded = round(seconds)
        if abs(seconds - rounded) < 0.05:
            return str(int(rounded))
        return f"{seconds:.1f}".rstrip("0").rstrip(".")

    def _sensory_source_tooltip(self, provider_id, fallback=""):
        copy = self._sensory_source_ui_copy(provider_id)
        tooltip = str(copy.get("tooltip") or "").strip()
        return tooltip or str(fallback or "Adds background context when this source is selected.").strip()

    def _sensory_source_short_description(self, provider_id, fallback=""):
        copy = self._sensory_source_ui_copy(provider_id)
        description = str(copy.get("description") or "").strip()
        return description or str(fallback or "").strip()

    def _sensory_provider_summaries(self):
        return [provider.to_summary() for provider in _sensory().list_providers()]

    def _parse_sensory_feedback_source_values(self, value):
        if isinstance(value, (list, tuple, set)):
            tokens = [str(item or "").strip().lower() for item in list(value or [])]
        else:
            tokens = [part.strip().lower() for part in str(value or "off").split(",")]
        selected = []
        seen = set()
        for token in tokens:
            if not token or token == "off" or token in seen:
                continue
            if _sensory().get_provider(token) is None:
                continue
            selected.append(token)
            seen.add(token)
        return selected

    def _selected_sensory_feedback_sources(self):
        checkboxes = getattr(self, "_sensory_feedback_source_checkboxes", {}) or {}
        selected = [provider_id for provider_id, checkbox in checkboxes.items() if bool(checkbox.isChecked())]
        return self._parse_sensory_feedback_source_values(selected)

    def _sensory_feedback_config_value(self, values=None):
        selected = self._parse_sensory_feedback_source_values(values if values is not None else self._selected_sensory_feedback_sources())
        return ",".join(selected) if selected else "off"

    def _sync_sensory_feedback_source_summary(self, selected_values=None):
        if not hasattr(self, "sensory_feedback_source_combo"):
            return
        selected = self._parse_sensory_feedback_source_values(selected_values if selected_values is not None else self._selected_sensory_feedback_sources())
        summary_label = self._sensory_feedback_source_label_from_value(selected)
        summary_value = self._sensory_feedback_config_value(selected)
        combo = self.sensory_feedback_source_combo
        previous = combo.blockSignals(True)
        combo.clear()
        combo.addItem(summary_label, summary_value)
        combo.setCurrentIndex(0)
        combo.blockSignals(previous)

    def _sync_companion_orb_sensory_target_controls(self, selected_values=None):
        checkbox = getattr(self, "companion_orb_sensory_target_checkbox", None)
        if checkbox is None:
            return
        selected = set(
            self._parse_sensory_feedback_source_values(
                selected_values if selected_values is not None else _engine().RUNTIME_CONFIG.get("sensory_feedback_source", "off")
            )
        )
        enabled = bool(_engine().RUNTIME_CONFIG.get("companion_orb_sensory_target_enabled", False)) or COMPANION_ORB_PROVIDER_ID in selected
        try:
            checkbox.blockSignals(True)
            checkbox.setChecked(enabled)
        finally:
            checkbox.blockSignals(False)
        button = getattr(self, "btn_companion_orb_clear_sensory_target", None)
        if button is not None:
            button.setEnabled(enabled)

    def _refresh_sensory_feedback_hint(self):
        runtime_config = _engine().RUNTIME_CONFIG
        if not hasattr(self, "sensory_feedback_hint"):
            return
        sources = self._parse_sensory_feedback_source_values(
            self.sensory_feedback_source_combo.currentData()
            if hasattr(self, "sensory_feedback_source_combo") and self.sensory_feedback_source_combo.count()
            else runtime_config.get("sensory_feedback_source", "off")
        )
        interval = float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else 7.0
        pingpong_enabled = bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(runtime_config.get("sensory_pingpong_enabled", False))
        pingpong_depth = int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(runtime_config.get("sensory_pingpong_history_depth", 3) or 3)
        hidden_proactive = bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(runtime_config.get("sensory_allow_hidden_proactive_speech", False))
        hidden_visual = bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(runtime_config.get("sensory_allow_hidden_visual_generation", False))
        interval_label = self._format_sensory_seconds(interval)
        if not sources:
            summary = (
                "Active sources: none. Select sources if NC should add quiet background context to future LLM requests."
            )
        else:
            labels = []
            for source in sources:
                provider = _sensory().get_provider(source)
                provider_label = str(getattr(provider, "label", source) or source)
                labels.append(self._sensory_source_display_label(source, provider_label))
            review_state = "on" if pingpong_enabled else "off"
            spoken_state = "on" if hidden_proactive else "off"
            visual_state = "on" if hidden_visual else "off"
            summary = (
                f"Active sources: {', '.join(labels)}. "
                f"Review: {review_state}, every {interval_label} seconds, keeping {pingpong_depth} recent observation(s). "
                "NC treats observations as background context, not as a user message. "
                f"Allowed actions: spoken comments {spoken_state}; Visual Reply images {visual_state}."
            )
            if COMPANION_ORB_PROVIDER_ID in sources:
                target_enabled = bool(runtime_config.get("companion_orb_sensory_target_enabled", False))
                full_context = bool(runtime_config.get("companion_orb_full_screen_context_enabled", False))
                process_names = bool(runtime_config.get("companion_orb_include_process_name", True))
                if target_enabled and full_context:
                    summary += " Orb target is using the full-screen context map."
                elif target_enabled:
                    summary += " Orb target uses only the selected window or region."
                else:
                    summary += " Orb target is selected but disabled in AI Presence."
                if target_enabled and not process_names:
                    summary += " Window process names are hidden."
        self.sensory_feedback_hint.setText(summary)

    def on_sensory_feedback_source_changed(self, choice):
        selected = self._parse_sensory_feedback_source_values(choice)
        if (
            not selected
            and hasattr(self, "sensory_feedback_source_combo")
            and self.sensory_feedback_source_combo.count()
        ):
            selected = self._parse_sensory_feedback_source_values(self.sensory_feedback_source_combo.currentData())
        checkboxes = getattr(self, "_sensory_feedback_source_checkboxes", {}) or {}
        for provider_id, checkbox in checkboxes.items():
            desired = provider_id in set(selected)
            if bool(checkbox.isChecked()) == desired:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(desired)
            checkbox.blockSignals(False)
        config_value = self._sensory_feedback_config_value(selected)
        self._sync_sensory_feedback_source_summary(selected)
        _engine().update_runtime_config("sensory_feedback_source", config_value)
        orb_enabled = COMPANION_ORB_PROVIDER_ID in set(selected)
        _engine().update_runtime_config("companion_orb_sensory_target_enabled", orb_enabled)
        self._sync_companion_orb_sensory_target_controls(selected)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_feedback_source", "value": config_value})
        self.save_session()

    def on_sensory_feedback_interval_changed(self, value):
        seconds = max(2.0, float(value or 7.0))
        _engine().update_runtime_config("sensory_feedback_interval_seconds", seconds)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_feedback_interval_seconds", "value": seconds})
        self.save_session()

    def on_sensory_pingpong_enabled_changed(self, checked):
        enabled = bool(checked)
        _engine().update_runtime_config("sensory_pingpong_enabled", enabled)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_pingpong_enabled", "value": enabled})
        self.save_session()

    def on_sensory_allow_hidden_proactive_changed(self, checked):
        enabled = bool(checked)
        _engine().update_runtime_config("sensory_allow_hidden_proactive_speech", enabled)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_allow_hidden_proactive_speech", "value": enabled})
        self.save_session()

    def on_sensory_allow_hidden_visual_changed(self, checked):
        enabled = bool(checked)
        _engine().update_runtime_config("sensory_allow_hidden_visual_generation", enabled)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_allow_hidden_visual_generation", "value": enabled})
        self.save_session()

    def on_companion_orb_sensory_target_changed(self, checked):
        enabled = bool(checked)
        _engine().update_runtime_config("companion_orb_sensory_target_enabled", enabled)
        selected = self._parse_sensory_feedback_source_values(
            self.sensory_feedback_source_combo.currentData()
            if hasattr(self, "sensory_feedback_source_combo") and self.sensory_feedback_source_combo.count()
            else _engine().RUNTIME_CONFIG.get("sensory_feedback_source", "off")
        )
        selected_set = set(selected)
        if enabled:
            if _sensory().get_provider(COMPANION_ORB_PROVIDER_ID) is not None:
                selected_set.add(COMPANION_ORB_PROVIDER_ID)
        else:
            selected_set.discard(COMPANION_ORB_PROVIDER_ID)
        ordered = [provider_id for provider_id in selected if provider_id in selected_set]
        if enabled and COMPANION_ORB_PROVIDER_ID in selected_set and COMPANION_ORB_PROVIDER_ID not in ordered:
            ordered.append(COMPANION_ORB_PROVIDER_ID)
        config_value = self._sensory_feedback_config_value(ordered)
        _engine().update_runtime_config("sensory_feedback_source", config_value)
        self.refresh_sensory_feedback_source_options(selected_value=config_value)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "companion_orb_sensory_target_enabled", "value": enabled})
        self.save_session()

    def clear_companion_orb_sensory_target(self):
        callback = getattr(self, "_invoke_addon_capability", None)
        if callable(callback):
            result = callback("nc.companion_orb_overlay", "companion_orb.clear_target", {}, default=None)
            if result is None:
                callback("nc.ai_presence_mode", "companion_orb.clear_target", {}, default=None)
        _engine().update_runtime_config("companion_orb_target_info", {})
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "companion_orb_target_info", "value": "cleared"})
        self.save_session()

    def on_sensory_pingpong_history_depth_changed(self, value):
        depth = max(0, int(value or 0))
        _engine().update_runtime_config("sensory_pingpong_history_depth", depth)
        self._refresh_sensory_feedback_hint()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_pingpong_history_depth", "value": depth})
        self.save_session()

    def on_sensory_pingpong_prompt_changed(self):
        prompt_text = self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else ""
        _engine().update_runtime_config("sensory_pingpong_prompt", prompt_text or getattr(_engine(), "DEFAULT_SENSORY_PINGPONG_PROMPT", ""))

    def reset_sensory_pingpong_prompt_to_default(self):
        default_prompt = str(getattr(_engine(), "DEFAULT_SENSORY_PINGPONG_PROMPT", "") or "").strip()
        if not default_prompt or not hasattr(self, "sensory_pingpong_prompt_text"):
            return
        self.sensory_pingpong_prompt_text.setPlainText(default_prompt)
        self.on_sensory_pingpong_prompt_changed()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_pingpong_prompt_reset", "value": "recommended"})
        self.save_session()

    def refresh_sensory_feedback_source_options(self, selected_value=None):
        target_provider_id = ""
        tabs = getattr(self, "sensory_feedback_tabs", None)
        if tabs is not None and tabs.count() > 1:
            current_widget = tabs.currentWidget()
            for provider_id, widget in dict(getattr(self, "_sensory_source_prompt_tabs", {}) or {}).items():
                if widget is current_widget:
                    target_provider_id = str(provider_id or "").strip().lower()
                    break
        source_value = selected_value if selected_value is not None else _engine().RUNTIME_CONFIG.get("sensory_feedback_source", "off")
        requested = self._parse_sensory_feedback_source_values(source_value)
        if (
            bool(_engine().RUNTIME_CONFIG.get("companion_orb_sensory_target_enabled", False))
            and _sensory().get_provider(COMPANION_ORB_PROVIDER_ID) is not None
            and COMPANION_ORB_PROVIDER_ID not in requested
        ):
            requested.append(COMPANION_ORB_PROVIDER_ID)
            _engine().update_runtime_config("sensory_feedback_source", self._sensory_feedback_config_value(requested))
        entries = []
        for provider in self._sensory_provider_summaries():
            provider_id = str(provider.get("id", "") or "").strip()
            label = str(provider.get("label", provider_id) or provider_id).strip()
            if provider_id:
                entries.append((provider_id, label))
        selected_set = set(requested)
        if hasattr(self, "sensory_feedback_sources_layout"):
            layout = self.sensory_feedback_sources_layout
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self._sensory_feedback_source_checkboxes = {}
            self._sensory_source_prompt_editors = {}
            self._sensory_source_prompt_tabs = {}
            for provider_id, label in entries:
                provider = _sensory().get_provider(provider_id)
                description = str(getattr(provider, "description", "") or "").strip() if provider is not None else ""
                display_label = self._sensory_source_display_label(provider_id, label, checkbox=True)
                tooltip = self._sensory_source_tooltip(provider_id, description)
                short_description = self._sensory_source_short_description(provider_id, description)
                row = QtWidgets.QFrame()
                row.setObjectName("sensory_source_row")
                row.setFrameShape(QtWidgets.QFrame.StyledPanel)
                row.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
                row.setStyleSheet(
                    "QFrame#sensory_source_row { border: 1px solid #263344; border-radius: 6px; background: #101720; }"
                )
                row_layout = QtWidgets.QHBoxLayout(row)
                row_layout.setContentsMargins(10, 7, 10, 7)
                row_layout.setSpacing(10)
                checkbox = QtWidgets.QCheckBox(display_label)
                checkbox.setMinimumWidth(132)
                checkbox.setToolTip(tooltip)
                checkbox.setChecked(provider_id in selected_set)
                checkbox.toggled.connect(self._on_sensory_feedback_source_checkbox_toggled)
                kind_label = QtWidgets.QLabel(self._sensory_source_kind(provider_id))
                kind_label.setAlignment(QtCore.Qt.AlignCenter)
                kind_label.setMinimumWidth(58)
                kind_label.setStyleSheet(
                    "color: #bcd3e7; border: 1px solid #334458; border-radius: 5px; padding: 2px 6px; background: #142033;"
                )
                description_label = QtWidgets.QLabel(short_description or tooltip)
                description_label.setWordWrap(True)
                description_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
                description_label.setToolTip(tooltip)
                row_layout.addWidget(checkbox, 0, QtCore.Qt.AlignTop)
                row_layout.addWidget(kind_label, 0, QtCore.Qt.AlignTop)
                row_layout.addWidget(description_label, 1)
                layout.addWidget(row)
                self._sensory_feedback_source_checkboxes[provider_id] = checkbox
            layout.addStretch(1)
        self._sync_sensory_feedback_source_summary(requested)
        self._sync_companion_orb_sensory_target_controls(requested)
        self._refresh_sensory_feedback_hint()
        self._refresh_sensory_feedback_source_tabs(selected_provider_id=target_provider_id)
        self._sync_tab_widget_height(getattr(self, "sensory_feedback_tabs", None))
        self._sync_host_settings_tabs_height()

    def _sensory_feedback_source_label_from_value(self, value):
        selected = self._parse_sensory_feedback_source_values(value)
        if not selected:
            return "Off"
        labels = []
        for provider_id in selected:
            provider = _sensory().get_provider(provider_id)
            provider_label = str(getattr(provider, "label", provider_id) or provider_id)
            labels.append(self._sensory_source_display_label(provider_id, provider_label))
        if len(labels) == 1:
            return labels[0]
        if len(labels) == 2:
            return f"{labels[0]} + {labels[1]}"
        return f"{len(labels)} sources selected"

    def _sensory_feedback_source_value_from_label(self, label):
        if hasattr(self, "sensory_feedback_source_combo"):
            index = self.sensory_feedback_source_combo.findText(str(label or ""))
            if index >= 0:
                return str(self.sensory_feedback_source_combo.itemData(index) or "off")
        selected = self._parse_sensory_feedback_source_values(label)
        return ",".join(selected) if selected else "off"

    def _on_sensory_feedback_source_checkbox_toggled(self, _checked):
        selected = self._selected_sensory_feedback_sources()
        config_value = self._sensory_feedback_config_value(selected)
        self._sync_sensory_feedback_source_summary(selected)
        _engine().update_runtime_config("sensory_feedback_source", config_value)
        orb_enabled = COMPANION_ORB_PROVIDER_ID in set(selected)
        _engine().update_runtime_config("companion_orb_sensory_target_enabled", orb_enabled)
        self._sync_companion_orb_sensory_target_controls(selected)
        self._refresh_sensory_feedback_hint()
        self._refresh_sensory_feedback_source_tabs()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_feedback_source", "value": config_value})
        self.save_session()
