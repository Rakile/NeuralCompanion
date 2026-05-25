from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import NoWheelTabWidget


from ui.runtime.engine_access import engine_module as _engine


def _sensory():
    from core import sensory

    return sensory

class BackendSensoryTabsMixin:
    def _screen_source_auto_attach_enabled(self):
        try:
            return bool(_engine().RUNTIME_CONFIG.get("screen_source_auto_attach_next_user_turn", False))
        except Exception:
            return False

    def _set_screen_source_auto_attach_enabled(self, checked):
        try:
            _engine().update_runtime_config("screen_source_auto_attach_next_user_turn", bool(checked))
        except Exception:
            return
        try:
            self.save_session()
        except Exception:
            pass

    def _add_screen_source_controls(self, layout):
        checkbox = QtWidgets.QCheckBox("Attach screen capture to each user message")
        checkbox.setToolTip(
            "When enabled, each user message captures the current screen with the Screen Capture settings and sends it as that turn's image attachment. "
            "Manual or clipboard image attachments take priority."
        )
        checkbox.setChecked(self._screen_source_auto_attach_enabled())
        checkbox.toggled.connect(self._set_screen_source_auto_attach_enabled)
        layout.addWidget(checkbox)
        if not hasattr(self, "_screen_source_auto_attach_checkboxes"):
            self._screen_source_auto_attach_checkboxes = []
        self._screen_source_auto_attach_checkboxes.append(checkbox)

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
        effective_payload = self._provider_sensory_effective_payload(provider_key) if hasattr(self, "_provider_sensory_effective_payload") else {}
        effective_metadata = dict(effective_payload.get("metadata") or {})

        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        editor = None
        if provider_key == "screen":
            self._add_screen_source_controls(layout)

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

        metadata_header_row = QtWidgets.QHBoxLayout()
        metadata_header_row.setContentsMargins(0, 6, 0, 0)
        metadata_header = QtWidgets.QLabel("Source metadata")
        metadata_header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
        metadata_header_row.addWidget(metadata_header)
        metadata_header_row.addStretch(1)
        metadata_reset_button = QtWidgets.QPushButton("Use Recommended")
        metadata_reset_button.clicked.connect(lambda _=False, pid=provider_key: self._reset_sensory_source_metadata_to_default(pid))
        metadata_header_row.addWidget(metadata_reset_button, 0)
        layout.addLayout(metadata_header_row)

        metadata_form = QtWidgets.QFormLayout()
        metadata_form.setContentsMargins(0, 0, 0, 0)
        metadata_form.setSpacing(6)

        def add_text_editor(field_key, label_text, value, *, height=64, placeholder=""):
            editor_widget = QtWidgets.QPlainTextEdit()
            editor_widget.setMinimumHeight(height)
            editor_widget.setPlaceholderText(placeholder)
            editor_widget.setPlainText(str(value or ""))
            editor_widget.textChanged.connect(lambda pid=provider_key: self._on_sensory_source_metadata_changed(pid))
            metadata_form.addRow(label_text, editor_widget)
            return editor_widget

        def add_json_editor(field_key, label_text, value, *, height=92):
            editor_widget = QtWidgets.QPlainTextEdit()
            editor_widget.setMinimumHeight(height)
            editor_widget.setPlaceholderText("Editable JSON list")
            formatter = getattr(self, "_format_sensory_metadata_json", None)
            text = formatter(value) if callable(formatter) else str(value or [])
            editor_widget.setPlainText(text)
            editor_widget.textChanged.connect(lambda pid=provider_key: self._on_sensory_source_metadata_changed(pid))
            metadata_form.addRow(label_text, editor_widget)
            return editor_widget

        metadata_editors = {
            "instruction": add_text_editor(
                "instruction",
                "Runtime instruction",
                effective_payload.get("instruction", ""),
                height=76,
                placeholder=f"Runtime instruction for {label}",
            ),
            "description": add_text_editor(
                "description",
                "Description",
                effective_payload.get("description", ""),
                height=58,
                placeholder=f"User-facing description for {label}",
            ),
            "ping_payload": add_json_editor("ping_payload", "PING payload", effective_metadata.get("ping_payload", declared_ping_payload)),
            "pong_influences": add_json_editor("pong_influences", "PONG influence", effective_metadata.get("pong_influences", declared_outputs)),
            "tag_subscriptions": add_json_editor("tag_subscriptions", "Tag subscriptions", effective_metadata.get("tag_subscriptions", declared_tags), height=72),
        }
        layout.addLayout(metadata_form)
        if not hasattr(self, "_sensory_source_metadata_editors"):
            self._sensory_source_metadata_editors = {}
        self._sensory_source_metadata_editors[provider_key] = metadata_editors

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

        if description or (contributors and include_behavior_contributors):
            about_header = QtWidgets.QLabel(f"About {label}")
            about_header.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
            layout.addWidget(about_header)
            if description:
                add_info_label(description)

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

        if not info_items_added and editor is None:
            empty = QtWidgets.QLabel(f"Metadata for {label} is editable above.")
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
        self._sensory_source_metadata_editors = {}
        self._sensory_source_prompt_tabs = {}
        self._screen_source_auto_attach_checkboxes = []
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
