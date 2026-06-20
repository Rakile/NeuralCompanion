from PySide6 import QtCore, QtGui, QtWidgets

from ui.widgets.basic import NoWheelTabWidget


from ui.runtime.engine_access import engine_module as _engine


def _sensory():
    from core import sensory

    return sensory

class BackendSensoryTabsMixin:
    def _apply_vision_tab_button_style(self, tabs):
        if tabs is None:
            return
        try:
            tabs.setUsesScrollButtons(True)
            tabs.setElideMode(QtCore.Qt.ElideNone)
            tabs.setIconSize(QtCore.QSize(16, 16))
            tab_bar = tabs.tabBar()
            if tab_bar is not None:
                tab_bar.setExpanding(False)
                tab_bar.setUsesScrollButtons(True)
                tab_bar.setElideMode(QtCore.Qt.ElideNone)
                tab_bar.setIconSize(QtCore.QSize(16, 16))
                tab_bar.setFixedHeight(34)
                tab_bar.setStyleSheet(
                    "QTabBar {"
                    "  background: transparent;"
                    "  min-height: 34px;"
                    "  max-height: 34px;"
                    "  qproperty-drawBase: 0;"
                    "}"
                    "QTabBar::tab {"
                    "  background: #17212c;"
                    "  border: 1px solid #273342;"
                    "  min-width: 112px;"
                    "  max-width: 190px;"
                    "  min-height: 30px;"
                    "  max-height: 30px;"
                    "  height: 30px;"
                    "  padding: 4px 12px;"
                    "  margin-top: 0px;"
                    "  margin-right: 3px;"
                    "  margin-bottom: -1px;"
                    "  border-top-left-radius: 7px;"
                    "  border-top-right-radius: 7px;"
                    "  border-bottom-left-radius: 0px;"
                    "  border-bottom-right-radius: 0px;"
                    "}"
                    "QTabBar::tab:!selected {"
                    "  margin-top: 0px;"
                    "}"
                    "QTabBar::tab:selected {"
                    "  background: #0f141b;"
                    "  border-color: #273342;"
                    "  border-bottom-color: #0f141b;"
                    "  padding: 4px 12px;"
                    "  margin-bottom: -1px;"
                    "}"
                    "QTabBar::tab:hover {"
                    "  background: #223247;"
                    "}"
                )
        except Exception:
            pass

    def _sensory_source_icon(self, provider_id):
        style = QtWidgets.QApplication.style()
        provider_key = str(provider_id or "").strip().lower()
        icon_map = {
            "screen": QtWidgets.QStyle.SP_ComputerIcon,
            "webcam": QtWidgets.QStyle.SP_DesktopIcon,
            "clipboard": QtWidgets.QStyle.SP_FileDialogContentsView,
            "heart_rate": QtWidgets.QStyle.SP_DialogApplyButton,
            "spotify_sense": QtWidgets.QStyle.SP_MediaPlay,
            "companion_orb_target": QtWidgets.QStyle.SP_DialogHelpButton,
        }
        standard_icon = icon_map.get(provider_key, QtWidgets.QStyle.SP_FileIcon)
        return style.standardIcon(standard_icon) if style is not None else QtGui.QIcon()

    def _source_section_card(self, title, *, icon=None, description="", object_name=""):
        card = QtWidgets.QGroupBox(str(title or "").strip())
        if object_name:
            card.setObjectName(str(object_name or "").strip())
        card.setStyleSheet(self._vision_section_group_stylesheet())
        card.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(10, 10, 10, 10)
        card_layout.setSpacing(8)
        if description:
            intro_row = QtWidgets.QHBoxLayout()
            intro_row.setContentsMargins(0, 0, 0, 0)
            intro_row.setSpacing(8)
            if icon is not None and not icon.isNull():
                icon_label = QtWidgets.QLabel()
                icon_label.setPixmap(icon.pixmap(20, 20))
                intro_row.addWidget(icon_label, 0, QtCore.Qt.AlignTop)
            description_label = QtWidgets.QLabel(str(description or ""))
            description_label.setObjectName("sensory_source_section_description")
            description_label.setWordWrap(True)
            description_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
            intro_row.addWidget(description_label, 1)
            card_layout.addLayout(intro_row)
        return card, card_layout

    def _vision_section_group_stylesheet(self):
        return (
            "QGroupBox {"
            "  color: #dbeafe;"
            "  font-weight: 700;"
            "  border: 1px solid rgba(96, 165, 250, 0.32);"
            "  border-radius: 7px;"
            "  margin-top: 10px;"
            "  padding-top: 10px;"
            "}"
            "QGroupBox::title {"
            "  subcontrol-origin: margin;"
            "  left: 10px;"
            "  padding: 0 4px;"
            "}"
        )

    def _vision_panel_frame_stylesheet(self, object_name):
        safe_name = str(object_name or "vision_contribution_panel").strip() or "vision_contribution_panel"
        return (
            f"QFrame#{safe_name} {{"
            "  background: rgba(10, 18, 30, 0.74);"
            "  border: 1px solid rgba(96, 165, 250, 0.32);"
            "  border-radius: 7px;"
            "}"
        )

    def _normalize_vision_source_contribution_widget(self, widget):
        if widget is None:
            return
        try:
            widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
        except Exception:
            pass
        root_layout = widget.layout() if hasattr(widget, "layout") else None
        if root_layout is not None:
            try:
                root_layout.setContentsMargins(8, 8, 8, 8)
                root_layout.setSpacing(8)
            except Exception:
                pass
        for group in widget.findChildren(QtWidgets.QGroupBox):
            title = str(group.title() or "").strip()
            if title == "Advanced Reaction Prompt Template":
                group.setTitle("Advanced Prompt Rules")
            group.setStyleSheet(self._vision_section_group_stylesheet())
            try:
                group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
                group_layout = group.layout()
                if group_layout is not None:
                    group_layout.setContentsMargins(10, 10, 10, 10)
                    group_layout.setSpacing(8)
            except Exception:
                pass
        for frame in widget.findChildren(QtWidgets.QFrame):
            try:
                if frame.metaObject().className() != "QFrame" or frame.layout() is None:
                    continue
                if not str(frame.objectName() or "").strip():
                    frame.setObjectName("vision_contribution_panel")
                frame.setStyleSheet(self._vision_panel_frame_stylesheet(frame.objectName()))
                frame.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Maximum)
                frame_layout = frame.layout()
                if frame_layout is not None:
                    frame_layout.setContentsMargins(10, 10, 10, 10)
                    frame_layout.setSpacing(8)
            except Exception:
                continue
        for label in widget.findChildren(QtWidgets.QLabel):
            try:
                text = str(label.text() or "").strip()
                if text == "Addon Contract":
                    label.setText("How this source connects")
                elif text == "Prompt Preview":
                    label.setText("Review Prompt Preview")
            except Exception:
                continue

    def _source_help_label(self, text):
        label = QtWidgets.QLabel(str(text or "").strip())
        label.setWordWrap(True)
        label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        return label

    def _vision_source_contribution_tab_title(self, provider_id, contribution):
        raw_title = str(getattr(contribution, "title", "") or "").strip()
        title_key = raw_title.lower()
        provider_key = str(provider_id or "").strip().lower()
        if title_key == "source":
            return "Source Setup"
        if title_key == "supervisor":
            return "Reactions"
        if title_key == "threshold rules":
            return "Pulse Rules" if provider_key == "heart_rate" else "Reactions"
        return raw_title or "Settings"

    def _vision_source_contribution_icon(self, provider_id, contribution):
        raw_title = str(getattr(contribution, "title", "") or "").strip().lower()
        if raw_title in {"supervisor", "threshold rules"}:
            style = QtWidgets.QApplication.style()
            return style.standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation) if style is not None else QtGui.QIcon()
        return self._sensory_source_icon(provider_id)

    def _provider_hides_vision_source_tab(self, provider_id):
        provider = _sensory().get_provider(str(provider_id or "").strip().lower())
        metadata = dict(getattr(provider, "metadata", {}) or {}) if provider is not None else {}
        return bool(metadata.get("hide_vision_source_tab", False) or metadata.get("hide_source_tab", False))

    def _update_sensory_feedback_tab_bar_visibility(self):
        tabs = getattr(self, "sensory_feedback_tabs", None)
        if tabs is None or not hasattr(tabs, "tabBar"):
            return
        try:
            tab_bar = tabs.tabBar()
        except Exception:
            tab_bar = None
        if tab_bar is None:
            return
        self._apply_vision_tab_button_style(tabs)
        try:
            tab_bar.setVisible(int(tabs.count()) > 1)
        except Exception:
            pass

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
        source_icon = self._sensory_source_icon(provider_key)
        overview_description = self._sensory_source_short_description(provider_key, description) if hasattr(self, "_sensory_source_short_description") else description
        overview_card, overview_layout = self._source_section_card(
            "Source Overview",
            icon=source_icon,
            object_name="vision_source_overview_group",
            description=overview_description
            or "This source can add background context when selected in Background Awareness.",
        )
        overview_layout.addWidget(
            self._source_help_label(
                "Use this page to see what the source provides, how background review should read it, and which optional reaction add-ons are attached."
            )
        )
        if provider_key == "screen":
            self._add_screen_source_controls(overview_layout)
        layout.addWidget(overview_card)

        if self._provider_uses_source_prompt_fragment(provider_key):
            prompt_card, prompt_layout = self._source_section_card(
                "How NC reads this source",
                icon=source_icon,
                object_name="vision_source_guidance_group",
                description=(
                    "These instructions are merged into the background review prompt only when this source is selected. "
                    "Use them to keep reactions focused on visible evidence and useful context."
                ),
            )
            row = QtWidgets.QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            row.addStretch(1)
            reset_button = QtWidgets.QPushButton("Restore recommended prompt")
            reset_button.clicked.connect(lambda _=False, pid=provider_key: self._reset_sensory_source_prompt_to_default(pid))
            row.addWidget(reset_button, 0)
            prompt_layout.addLayout(row)
            editor = QtWidgets.QPlainTextEdit()
            editor.setMinimumHeight(0)
            editor.setPlaceholderText(f"Background review guidance for {label}")
            editor.setPlainText(str(prompt_text or "").strip())
            editor.textChanged.connect(lambda pid=provider_key: self._on_sensory_source_prompt_changed(pid))
            prompt_layout.addWidget(editor)
            prompt_layout.addWidget(
                self._source_help_label("This guidance is appended to the source-aware background review contract.")
            )
            layout.addWidget(prompt_card)

        metadata_card, metadata_layout = self._source_section_card(
            "Advanced Source Details",
            icon=source_icon,
            object_name="vision_source_advanced_details_group",
            description=(
                "Advanced source details for what gets sent into review and what the review is allowed to produce. "
                "Most users can leave these recommended values alone."
            ),
        )
        metadata_header_row = QtWidgets.QHBoxLayout()
        metadata_header_row.setContentsMargins(0, 0, 0, 0)
        metadata_header_row.addStretch(1)
        metadata_reset_button = QtWidgets.QPushButton("Restore recommended prompt")
        metadata_reset_button.clicked.connect(lambda _=False, pid=provider_key: self._reset_sensory_source_metadata_to_default(pid))
        metadata_header_row.addWidget(metadata_reset_button, 0)
        metadata_layout.addLayout(metadata_header_row)

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
                "How NC reads it",
                effective_payload.get("instruction", ""),
                height=76,
                placeholder=f"How NC should use {label}",
            ),
            "description": add_text_editor(
                "description",
                "What this source provides",
                effective_payload.get("description", ""),
                height=58,
                placeholder=f"Plain-language description for {label}",
            ),
            "ping_payload": add_json_editor("ping_payload", "What gets reviewed", effective_metadata.get("ping_payload", declared_ping_payload)),
            "pong_influences": add_json_editor("pong_influences", "What review can do", effective_metadata.get("pong_influences", declared_outputs)),
            "tag_subscriptions": add_json_editor("tag_subscriptions", "Matching tags", effective_metadata.get("tag_subscriptions", declared_tags), height=72),
        }
        metadata_layout.addLayout(metadata_form)
        layout.addWidget(metadata_card)
        if not hasattr(self, "_sensory_source_metadata_editors"):
            self._sensory_source_metadata_editors = {}
        self._sensory_source_metadata_editors[provider_key] = metadata_editors

        if contributors and include_behavior_contributors:
            contributor_lines = []
            for item in contributors:
                label_text = str(item.get("label") or item.get("id") or "Behavior")
                contributor_prompt_text = str(item.get("prompt") or "").strip()
                if contributor_prompt_text:
                    contributor_lines.append(f"- {label_text}: {contributor_prompt_text}")
                else:
                    contributor_lines.append(f"- {label_text}")
            reactions_card, reactions_layout = self._source_section_card(
                "Reactions",
                icon=source_icon,
                object_name="vision_source_reactions_group",
                description=(
                    "These enabled add-ons contribute behavior rules for this source. They can suggest spoken comments, Visual Reply beats, or tags when the review output allows it."
                ),
            )
            reactions_layout.addWidget(self._source_help_label("\n".join(contributor_lines)))
            layout.addWidget(reactions_card)
        elif editor is None:
            layout.addWidget(self._source_help_label(f"{label} uses the recommended source contract unless you edit the advanced fields above."))

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
        source_icon = self._sensory_source_icon(provider_key)
        source_kind = self._sensory_source_kind(provider_key) if hasattr(self, "_sensory_source_kind") else "Source"
        intro_card, _intro_layout = self._source_section_card(
            "Source Overview",
            icon=source_icon,
            object_name="vision_source_overview_group",
            description=(
                f"{label} is a {source_kind.lower()} source. Use these tabs to decide what it captures, "
                "how background review should interpret it, and which optional reaction rules are active."
            ),
        )
        layout.addWidget(intro_card)

        if addon_contributions:
            checkable_children = [
                item for item in addon_contributions
                if bool(dict(getattr(item, "metadata", {}) or {}).get("checkable", False))
            ]
            static_tabs = [item for item in addon_contributions if item not in checkable_children]
            if checkable_children:
                add_on_card, add_on_layout = self._source_section_card(
                    "Optional Reactions",
                    icon=source_icon,
                    object_name=f"vision_source_{provider_key}_optional_reactions_group",
                    description="Turn source-specific reaction add-ons on or off. Disabled add-ons keep their settings but do not contribute rules to background review.",
                )
                for item in checkable_children:
                    checkbox = QtWidgets.QCheckBox(self._vision_source_contribution_tab_title(provider_key, item))
                    checkbox.setToolTip(str(getattr(item, "tooltip", "") or "Optional source behavior add-on."))
                    checkbox.setChecked(bool(self._addon_contribution_enabled(item)))
                    checkbox.toggled.connect(lambda checked, pid=provider_key, cid=item.id: self._on_vision_source_child_checkbox_toggled(pid, cid, checked))
                    add_on_layout.addWidget(checkbox)
                layout.addWidget(add_on_card)
            nested_tabs = NoWheelTabWidget()
            nested_tabs.setObjectName(f"vision_source_tabs_{provider_key}")
            nested_tabs.setMinimumSize(0, 0)
            nested_tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            self._apply_vision_tab_button_style(nested_tabs)
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
                tab_index = nested_tabs.addTab(source_widget, self._sensory_source_icon(provider_key), "Source Setup")
                nested_tabs.setTabToolTip(tab_index, f"Source guidance and declared capture data for {label}.")
            for item in static_tabs:
                try:
                    child_widget = item.factory(None)
                    if child_widget is None:
                        continue
                    self._normalize_vision_source_contribution_widget(child_widget)
                    tab_title = self._vision_source_contribution_tab_title(provider_key, item)
                    tab_index = nested_tabs.addTab(child_widget, self._vision_source_contribution_icon(provider_key, item), tab_title)
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
                    self._normalize_vision_source_contribution_widget(child_widget)
                    tab_title = self._vision_source_contribution_tab_title(provider_key, item)
                    tab_index = nested_tabs.addTab(child_widget, self._vision_source_contribution_icon(provider_key, item), tab_title)
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
            if self._provider_hides_vision_source_tab(provider_id):
                continue
            provider = _sensory().get_provider(provider_id)
            provider_label = str(getattr(provider, "label", provider_id) or provider_id)
            label_getter = getattr(self, "_sensory_source_display_label", None)
            label = label_getter(provider_id, provider_label) if callable(label_getter) else provider_label
            widget = self._build_sensory_source_prompt_tab(provider_id, label)
            tab_label_getter = getattr(self, "_sensory_source_tab_label", None)
            tab_label = tab_label_getter(provider_id, label) if callable(tab_label_getter) else label
            tab_index = tabs.addTab(widget, self._sensory_source_icon(provider_id), tab_label)
            tabs.setTabToolTip(tab_index, label)
            self._sensory_source_prompt_tabs[str(provider_id or "").strip().lower()] = widget
        if target_provider_id:
            target_widget = self._sensory_source_prompt_tabs.get(target_provider_id)
            if target_widget is not None:
                for index in range(1, tabs.count()):
                    if tabs.widget(index) is target_widget:
                        tabs.setCurrentIndex(index)
                        break
        self._update_sensory_feedback_tab_bar_visibility()
        self._sync_tab_widget_height(getattr(self, "sensory_feedback_tabs", None))
        self._sync_host_settings_tabs_height()
