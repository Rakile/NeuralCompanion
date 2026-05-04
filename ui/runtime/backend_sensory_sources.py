from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import NoWheelTabWidget


def _engine():
    import engine

    return engine


def _sensory():
    from core import sensory

    return sensory


class BackendSensorySourcesMixin:
    """Manage backend hidden-sensory source selection and source prompt tabs."""

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
        if not sources:
            summary = "Hidden sensory feedback is disabled. No addon or built-in sensory provider will attach hidden context to LLM requests."
        else:
            labels = []
            descriptions = []
            for source in sources:
                provider = _sensory().get_provider(source)
                labels.append(str(getattr(provider, "label", source) or source))
                description = str(getattr(provider, "description", "") or "").strip() if provider is not None else ""
                if description:
                    descriptions.append(description)
            summary = (
                f"NC will refresh hidden sensory input from {', '.join(repr(label) for label in labels)} when building an LLM request if the last capture is older than about "
                f"{interval:.1f}s. Each selected source may contribute its own image or text payload as ambient context, not as a user request."
            )
            if descriptions:
                summary += " " + " ".join(descriptions)
            if pingpong_enabled:
                summary += (
                    f" Hidden PING/PONG is enabled, so while NC is idle it may send background sensory PINGs and retain up to "
                    f"{pingpong_depth} meaningful hidden PONG event(s)."
                )
                summary += (
                    f" Auto-speech from hidden PONGs is {'enabled' if hidden_proactive else 'disabled'}. "
                    f"Automatic visual replies are {'enabled' if hidden_visual else 'disabled'} for both hidden PONGs and assistant [visualize: ...] tags."
                )
            else:
                summary += " Hidden PING/PONG is off, so sensory updates are only attached during normal visible requests."
        self.sensory_feedback_hint.setText(summary)

    def on_sensory_feedback_source_changed(self, choice):
        selected = self._parse_sensory_feedback_source_values(choice)
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
                checkbox = QtWidgets.QCheckBox(label)
                checkbox.setChecked(provider_id in selected_set)
                checkbox.toggled.connect(self._on_sensory_feedback_source_checkbox_toggled)
                layout.addWidget(checkbox)
                self._sensory_feedback_source_checkboxes[provider_id] = checkbox
            layout.addStretch(1)
        self._sync_sensory_feedback_source_summary(requested)
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
            labels.append(str(getattr(provider, "label", provider_id) or provider_id))
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
        self._refresh_sensory_feedback_hint()
        self._refresh_sensory_feedback_source_tabs()
        self.emit_tutorial_event("ui_changed", {"field": "sensory_feedback_source", "value": config_value})
        self.save_session()

    def _normalize_sensory_pingpong_source_prompt_map(self, payload=None):
        raw = payload if payload is not None else _engine().RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {})
        if not isinstance(raw, dict):
            return {}
        result = {}
        for key, value in list(raw.items()):
            provider_id = str(key or "").strip().lower()
            if not provider_id:
                continue
            result[provider_id] = str(value or "").strip()
        return result

    def _current_sensory_pingpong_source_prompt_map(self):
        editors = getattr(self, "_sensory_source_prompt_editors", {}) or {}
        current_map = self._normalize_sensory_pingpong_source_prompt_map()
        for provider_id, editor in editors.items():
            current_map[str(provider_id or "").strip().lower()] = str(editor.toPlainText() or "").strip()
        return current_map

    def _provider_sensory_pingpong_prompt_default(self, provider_id):
        provider = _sensory().get_provider(str(provider_id or "").strip().lower())
        metadata = dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}
        return str(metadata.get("pingpong_prompt") or "").strip()

    def _provider_uses_source_prompt_fragment(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        return metadata.get("prompt_fragment_enabled", True) is not False

    def _provider_sensory_metadata(self, provider_id):
        provider = _sensory().get_provider(str(provider_id or "").strip().lower())
        return dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}

    def _provider_declared_ping_payload(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("ping_payload", [])
        payload_lines = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    field_name = str(item.get("field") or "").strip()
                    description = str(item.get("description") or "").strip()
                    text = field_name
                    if field_name and description:
                        text = f"{field_name}: {description}"
                    elif description:
                        text = description
                else:
                    text = str(item or "").strip()
                if text and text not in payload_lines:
                    payload_lines.append(text)
        return payload_lines

    def _provider_declared_pong_influences(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("pong_influences", metadata.get("pong_outputs", []))
        outputs = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    field_name = str(item.get("field") or "").strip()
                    description = str(item.get("description") or "").strip()
                    text = field_name
                    if field_name and description:
                        text = f"{field_name}: {description}"
                    elif description:
                        text = description
                else:
                    text = str(item or "").strip()
                if text and text not in outputs:
                    outputs.append(text)
        return outputs

    def _provider_prompt_contributors(self, provider_id):
        provider_key = str(provider_id or "").strip().lower()
        items = []
        for contributor in _sensory().list_prompt_contributors(provider_key):
            if hasattr(contributor, "to_summary"):
                items.append(contributor.to_summary())
            elif isinstance(contributor, dict):
                items.append(dict(contributor))
        return items

    def _provider_declared_tag_subscriptions(self, provider_id):
        metadata = self._provider_sensory_metadata(provider_id)
        raw = metadata.get("tag_subscriptions", [])
        tags = []
        if isinstance(raw, (list, tuple, set)):
            for item in list(raw):
                if isinstance(item, dict):
                    tag_name = str(item.get("tag") or "").strip()
                    action = str(item.get("action") or "").strip()
                    text = tag_name
                    if tag_name and action:
                        text = f"{tag_name}: {action}"
                    elif action:
                        text = action
                else:
                    text = str(item or "").strip()
                if text and text not in tags:
                    tags.append(text)
        return tags

    def _on_sensory_source_prompt_changed(self, provider_id):
        prompt_map = self._current_sensory_pingpong_source_prompt_map()
        _engine().update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
        self.emit_tutorial_event("ui_changed", {"field": f"sensory_pingpong_source_prompt:{provider_id}", "value": "edited"})
        self.save_session()

    def _reset_sensory_source_prompt_to_default(self, provider_id):
        editors = getattr(self, "_sensory_source_prompt_editors", {}) or {}
        editor = editors.get(str(provider_id or "").strip().lower())
        if editor is None:
            return
        default_prompt = self._provider_sensory_pingpong_prompt_default(provider_id)
        editor.setPlainText(default_prompt)
        self._on_sensory_source_prompt_changed(provider_id)

    def _vision_source_tab_contributions(self, provider_id):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return []
        provider_key = str(provider_id or "").strip().lower()
        items = []
        for contribution in manager.get_tab_contributions(area="vision_source"):
            parent_tab_id = str(getattr(contribution, "parent_tab_id", "") or "").strip().lower()
            if parent_tab_id == provider_key:
                items.append(contribution)
        return items

    def _build_sensory_source_foundation_widget(
        self,
        provider_key,
        label,
        *,
        prompt_text="",
        description="",
        declared_ping_payload=None,
        declared_outputs=None,
        declared_tags=None,
        contributors=None,
        include_behavior_contributors=False,
    ):
        declared_ping_payload = list(declared_ping_payload or [])
        declared_outputs = list(declared_outputs or [])
        declared_tags = list(declared_tags or [])
        contributors = list(contributors or [])

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        editor = None
        if self._provider_uses_source_prompt_fragment(provider_key):
            prompt_header = QtWidgets.QLabel(f"Source guidance for {label}")
            prompt_header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(prompt_header)
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addStretch(1)
            reset_button = QtWidgets.QPushButton("Use Recommended")
            reset_button.clicked.connect(lambda _=False, pid=provider_key: self._reset_sensory_source_prompt_to_default(pid))
            row.addWidget(reset_button, 0)
            layout.addLayout(row)
            editor = QtWidgets.QPlainTextEdit()
            editor.setMinimumHeight(0)
            editor.setPlaceholderText(f"Prompt fragment for {label}")
            editor.setPlainText(str(prompt_text or "").strip())
            editor.textChanged.connect(lambda pid=provider_key: self._on_sensory_source_prompt_changed(pid))
            layout.addWidget(editor)
            hint = QtWidgets.QLabel("This fragment is appended after the core hidden PING/PONG prompt whenever this source is enabled.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(hint)

        info_items_added = False

        def add_info_header(text):
            nonlocal info_items_added
            header = QtWidgets.QLabel(text)
            header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(header)
            info_items_added = True

        def add_info_label(text):
            nonlocal info_items_added
            label_widget = QtWidgets.QLabel(text)
            label_widget.setWordWrap(True)
            label_widget.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(label_widget)
            info_items_added = True

        if description or declared_ping_payload or declared_outputs or declared_tags or (contributors and include_behavior_contributors):
            about_header = QtWidgets.QLabel(f"About {label}")
            about_header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(about_header)
            if description:
                add_info_label(description)

        if declared_ping_payload:
            add_info_header("Declared PING payload")
            add_info_label("\n".join([f"- {item}" for item in declared_ping_payload]))

        if declared_outputs:
            add_info_header("May influence PONG")
            add_info_label("\n".join([f"- {item}" for item in declared_outputs]))

        if contributors and include_behavior_contributors:
            add_info_header("Active behavior contributors")
            contributor_lines = []
            for item in contributors:
                label_text = str(item.get("label") or item.get("id") or "Behavior")
                contributor_prompt_text = str(item.get("prompt") or "").strip()
                if contributor_prompt_text:
                    contributor_lines.append(f"- {label_text}: {contributor_prompt_text}")
                else:
                    contributor_lines.append(f"- {label_text}")
            add_info_label("\n".join(contributor_lines))

        if declared_tags:
            add_info_header("Declared tag subscriptions")
            add_info_label("\n".join([f"- {item}" for item in declared_tags]))

        if not info_items_added and editor is None:
            empty = QtWidgets.QLabel(f"No additional source guidance is declared for {label}.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            layout.addWidget(empty)

        layout.addStretch(1)
        return widget, editor

    def _on_vision_source_child_checkbox_toggled(self, provider_id, contribution_id, checked):
        contribution_id = str(contribution_id or "").strip()
        contribution = next((item for item in self._vision_source_tab_contributions(provider_id) if str(getattr(item, "id", "") or "") == contribution_id), None)
        if contribution is None:
            return
        self._set_addon_contribution_enabled(contribution, bool(checked))
        self._refresh_sensory_feedback_source_tabs(selected_provider_id=str(provider_id or "").strip().lower())
        self.save_session()

    def _build_sensory_source_prompt_tab(self, provider_id, label):
        provider_key = str(provider_id or "").strip().lower()
        prompt_map = self._normalize_sensory_pingpong_source_prompt_map()
        prompt_text = str(prompt_map.get(provider_key) or self._provider_sensory_pingpong_prompt_default(provider_key) or "").strip()
        provider = _sensory().get_provider(provider_key)
        description = str(getattr(provider, "description", "") or "").strip() if provider is not None else ""
        declared_ping_payload = self._provider_declared_ping_payload(provider_key)
        declared_outputs = self._provider_declared_pong_influences(provider_key)
        declared_tags = self._provider_declared_tag_subscriptions(provider_key)
        addon_contributions = self._vision_source_tab_contributions(provider_key)
        contributors = self._provider_prompt_contributors(provider_key)
        has_custom_source_tab = any(str(getattr(item, "title", "") or "").strip().lower() == "source" for item in addon_contributions)
        use_nested_source_tab = bool(
            (not has_custom_source_tab) and addon_contributions and (
                self._provider_uses_source_prompt_fragment(provider_key)
                or description
                or declared_ping_payload
                or declared_outputs
                or declared_tags
            )
        )

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        widget = QtWidgets.QWidget()
        scroll.setWidget(widget)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        editor = None

        if addon_contributions:
            checkable_children = [
                item for item in addon_contributions
                if bool(dict(getattr(item, "metadata", {}) or {}).get("checkable", False))
            ]
            static_tabs = [item for item in addon_contributions if item not in checkable_children]
            if checkable_children:
                include_row = QtWidgets.QHBoxLayout()
                include_row.setContentsMargins(0, 0, 0, 0)
                include_row.setSpacing(8)
                for item in checkable_children:
                    checkbox = QtWidgets.QCheckBox(item.title)
                    checkbox.setChecked(bool(self._addon_contribution_enabled(item)))
                    checkbox.toggled.connect(lambda checked, pid=provider_key, cid=item.id: self._on_vision_source_child_checkbox_toggled(pid, cid, checked))
                    include_row.addWidget(checkbox)
                include_row.addStretch(1)
                layout.addLayout(include_row)
            nested_tabs = NoWheelTabWidget()
            nested_tabs.setObjectName(f"vision_source_tabs_{provider_key}")
            nested_tabs.setMinimumSize(0, 0)
            nested_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            nested_tabs.currentChanged.connect(lambda _index, tabs=nested_tabs: self._sync_tab_widget_height(tabs))
            if use_nested_source_tab:
                source_widget, editor = self._build_sensory_source_foundation_widget(
                    provider_key,
                    label,
                    prompt_text=prompt_text,
                    description=description,
                    declared_ping_payload=declared_ping_payload,
                    declared_outputs=declared_outputs,
                    declared_tags=declared_tags,
                    contributors=contributors,
                    include_behavior_contributors=False,
                )
                tab_index = nested_tabs.addTab(source_widget, "Source")
                nested_tabs.setTabToolTip(tab_index, f"Source guidance and declared payload for {label}.")
            for item in static_tabs:
                try:
                    child_widget = item.factory(None)
                    if child_widget is None:
                        continue
                    tab_index = nested_tabs.addTab(child_widget, item.title)
                    if item.tooltip:
                        nested_tabs.setTabToolTip(tab_index, item.tooltip)
                except Exception as exc:
                    print(f"⚠️ [Addons] Failed to mount Vision source tab '{item.id}': {exc}")
            for item in checkable_children:
                if not self._addon_contribution_enabled(item):
                    continue
                try:
                    child_widget = item.factory(None)
                    if child_widget is None:
                        continue
                    tab_index = nested_tabs.addTab(child_widget, item.title)
                    if item.tooltip:
                        nested_tabs.setTabToolTip(tab_index, item.tooltip)
                except Exception as exc:
                    print(f"⚠️ [Addons] Failed to mount Vision child tab '{item.id}': {exc}")
            if nested_tabs.count() > 0:
                layout.addWidget(nested_tabs, 0, QtCore.Qt.AlignTop)
                self._sync_tab_widget_height(nested_tabs)

        if not use_nested_source_tab:
            foundation_widget, foundation_editor = self._build_sensory_source_foundation_widget(
                provider_key,
                label,
                prompt_text=prompt_text,
                description=description,
                declared_ping_payload=declared_ping_payload,
                declared_outputs=declared_outputs,
                declared_tags=declared_tags,
                contributors=contributors,
                include_behavior_contributors=not addon_contributions,
            )
            layout.addWidget(foundation_widget)
            if foundation_editor is not None:
                editor = foundation_editor

        if editor is not None:
            self._sensory_source_prompt_editors[provider_key] = editor
        self._sensory_source_prompt_tabs[provider_key] = scroll
        return scroll

    def _refresh_sensory_feedback_source_tabs(self, selected_provider_id=None):
        tabs = getattr(self, "sensory_feedback_tabs", None)
        if tabs is None:
            return
        target_provider_id = str(selected_provider_id or "").strip().lower()
        if not target_provider_id and tabs.count() > 1:
            current_widget = tabs.currentWidget()
            for provider_id, widget in dict(getattr(self, "_sensory_source_prompt_tabs", {}) or {}).items():
                if widget is current_widget:
                    target_provider_id = str(provider_id or "").strip().lower()
                    break
        while tabs.count() > 1:
            widget = tabs.widget(1)
            tabs.removeTab(1)
            if widget is not None:
                widget.deleteLater()
        self._sensory_source_prompt_editors = {}
        self._sensory_source_prompt_tabs = {}
        for provider_id in self._selected_sensory_feedback_sources():
            provider = _sensory().get_provider(provider_id)
            label = str(getattr(provider, "label", provider_id) or provider_id)
            widget = self._build_sensory_source_prompt_tab(provider_id, label)
            tabs.addTab(widget, label)
            self._sensory_source_prompt_tabs[str(provider_id or "").strip().lower()] = widget
        if target_provider_id:
            target_widget = self._sensory_source_prompt_tabs.get(target_provider_id)
            if target_widget is not None:
                for index in range(1, tabs.count()):
                    if tabs.widget(index) is target_widget:
                        tabs.setCurrentIndex(index)
                        break
        self._sync_tab_widget_height(getattr(self, "sensory_feedback_tabs", None))
        self._sync_host_settings_tabs_height()
