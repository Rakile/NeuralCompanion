from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import LabeledSlider, NoWheelComboBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    # Imported lazily because qt_app imports this mixin before it imports engine.
    import engine

    return engine.RUNTIME_CONFIG


class BackendWorkspaceTabsMixin:
    """Build legacy/backend workspace utility tabs used by both UI frontends."""

    def _current_ui_focus_path(self):
        path = []
        top_title = ""
        if hasattr(self, "tabs"):
            top_index = self.tabs.currentIndex()
            if top_index >= 0:
                top_title = str(self.tabs.tabText(top_index) or "").strip()
                if top_title:
                    path.append(top_title)
        if top_title.lower() == "musetalk" and hasattr(self, "musetalk_tabs"):
            nested_index = self.musetalk_tabs.currentIndex()
            if nested_index >= 0:
                nested_title = str(self.musetalk_tabs.tabText(nested_index) or "").strip()
                if nested_title:
                    path.append(nested_title)
        return path

    def _emit_tab_focus_changed_event(self, *, scope, container, previous_title, current_title):
        current_path = self._current_ui_focus_path()
        payload = {
            "scope": str(scope or ""),
            "container": str(container or ""),
            "previous_tab_title": str(previous_title or ""),
            "current_tab_title": str(current_title or ""),
            "current_path": current_path,
        }
        self._publish_addon_event("ui.tab_focus_changed", payload)

    def _on_left_tab_changed(self, index):
        if not hasattr(self, "tabs"):
            return
        current_title = str(self.tabs.tabText(index) or "").strip()
        previous_title = getattr(self, "_last_left_tab_title", "")
        self._last_left_tab_title = current_title
        self._emit_tab_focus_changed_event(
            scope="top_level",
            container="left_tabs",
            previous_title=previous_title,
            current_title=current_title,
        )

    def _on_musetalk_tab_changed(self, index):
        if not hasattr(self, "musetalk_tabs"):
            return
        current_title = str(self.musetalk_tabs.tabText(index) or "").strip()
        previous_title = getattr(self, "_last_musetalk_tab_title", "")
        self._last_musetalk_tab_title = current_title
        self._emit_tab_focus_changed_event(
            scope="nested",
            container="musetalk_tabs",
            previous_title=previous_title,
            current_title=current_title,
        )

    def _sync_tab_widget_height(self, tabs):
        if tabs is None:
            return
        try:
            tabs.setMinimumHeight(0)
            tabs.setMaximumHeight(16777215)
            tabs.adjustSize()
            tabs.updateGeometry()
            parent = tabs.parentWidget()
            if parent is not None:
                parent.updateGeometry()
        except Exception:
            pass

    def _sync_host_settings_tabs_height(self):
        self._sync_tab_widget_height(getattr(self, "host_settings_tabs", None))

    def _build_persona_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("persona_tab")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMinimumSize(0, 0)

        widget = QtWidgets.QWidget()
        widget.setMinimumSize(0, 0)
        scroll.setWidget(widget)

        layout = QtWidgets.QVBoxLayout(widget)

        self.voice_combo = NoWheelComboBox()
        self.voice_combo.setObjectName("voice_combo")
        self.voice_combo.currentTextChanged.connect(self.on_voice_changed)
        layout.addWidget(QtWidgets.QLabel("Voice Clone"))
        layout.addWidget(self.voice_combo)

        self.emotional_text = QtWidgets.QPlainTextEdit()
        self.emotional_text.setObjectName("emotional_text")
        self.emotional_text.setPlaceholderText("Technical rules / expressive tags")
        self.emotional_text.setMinimumHeight(0)
        self.emotional_text.setMinimumSize(0, 90)
        self.system_prompt_text = QtWidgets.QPlainTextEdit()
        self.system_prompt_text.setObjectName("system_prompt_text")
        self.system_prompt_text.setPlaceholderText("System prompt")
        self.system_prompt_text.setMinimumHeight(0)
        self.system_prompt_text.setMinimumSize(0, 90)

        text_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        text_splitter.setChildrenCollapsible(False)
        text_splitter.setMinimumHeight(230)

        technical_group = QtWidgets.QGroupBox("Technical Rules (Tags)")
        technical_layout = QtWidgets.QVBoxLayout(technical_group)
        technical_layout.setContentsMargins(8, 10, 8, 8)
        technical_layout.addWidget(self.emotional_text)

        prompt_group = QtWidgets.QGroupBox("System Prompt")
        prompt_layout = QtWidgets.QVBoxLayout(prompt_group)
        prompt_layout.setContentsMargins(8, 10, 8, 8)
        prompt_layout.addWidget(self.system_prompt_text)

        text_splitter.addWidget(technical_group)
        text_splitter.addWidget(prompt_group)
        text_splitter.setStretchFactor(0, 1)
        text_splitter.setStretchFactor(1, 1)
        layout.addWidget(text_splitter, 1)

        apply_button = QtWidgets.QPushButton("Apply Changes")
        apply_button.setObjectName("btn_apply_text_config")
        apply_button.clicked.connect(self.apply_text_config)
        layout.addWidget(apply_button)
        return scroll

    def _build_brain_tab(self):
        runtime_config = _runtime_config()
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("brain_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        for label, key, minimum, maximum, default, is_int in [
            ("Temperature", "temperature", 0.1, 2.0, 1.22, False),
            ("Top P", "top_p", 0.1, 1.0, 0.9, False),
            ("Top K", "top_k", 0, 100, 40, True),
            ("Repeat Penalty", "repeat_penalty", 1.0, 2.0, 1.15, False),
            ("Min P", "min_p", 0.0, 0.5, 0.05, False),
        ]:
            slider = LabeledSlider(label, minimum, maximum, default, is_int=is_int)
            slider.value_changed.connect(lambda value, k=key, integer=is_int: self.update_brain_value(k, value, integer))
            self.brain_sliders[key] = slider
            layout.addWidget(slider)

        response_group = QtWidgets.QGroupBox("Response Length")
        response_layout = QtWidgets.QFormLayout(response_group)
        response_layout.setContentsMargins(10, 10, 10, 10)
        response_layout.setSpacing(8)

        self.limit_response_checkbox = QtWidgets.QCheckBox("Limit Response Length")
        self.limit_response_checkbox.setObjectName("limit_response_checkbox")
        self.limit_response_checkbox.setChecked(bool(runtime_config.get("limit_response_length", False)))
        self.limit_response_checkbox.toggled.connect(self.on_limit_response_length_changed)
        response_layout.addRow(self.limit_response_checkbox)

        self.max_response_tokens_spin = NoWheelSpinBox()
        self.max_response_tokens_spin.setObjectName("max_response_tokens_spin")
        self.max_response_tokens_spin.setRange(32, 8192)
        self.max_response_tokens_spin.setSingleStep(32)
        self.max_response_tokens_spin.setValue(int(runtime_config.get("max_response_tokens", DEFAULT_MAX_RESPONSE_TOKENS) or DEFAULT_MAX_RESPONSE_TOKENS))
        self.max_response_tokens_spin.valueChanged.connect(self.on_max_response_tokens_changed)
        response_layout.addRow("Maximum response length (tokens)", self.max_response_tokens_spin)

        self.max_response_tokens_spin.setEnabled(self.limit_response_checkbox.isChecked())
        layout.addWidget(response_group)
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_chunking_tab(self):
        runtime_config = _runtime_config()
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("chunking_tab")
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)

        hint = QtWidgets.QLabel(
            "Global pipeline tuning. These values affect chunking behavior system-wide and are not saved with personas."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(hint)

        groups = [
            (
                "Standard",
                [
                    ("Target Chars", "chunk_target_chars", 40, 220, int(runtime_config.get("chunk_target_chars", 100) or 100), True),
                    ("Max Chars", "chunk_max_chars", 60, 320, int(runtime_config.get("chunk_max_chars", 200) or 200), True),
                ],
            ),
            (
                "MuseTalk Non-Stream",
                [
                    ("Target Chars", "musetalk_chunk_target_chars", 60, 220, int(runtime_config.get("musetalk_chunk_target_chars", 110) or 110), True),
                    ("Max Chars", "musetalk_chunk_max_chars", 80, 320, int(runtime_config.get("musetalk_chunk_max_chars", 220) or 220), True),
                    ("Quickstart 1 Target", "musetalk_quickstart_1_target_chars", 60, 260, int(runtime_config.get("musetalk_quickstart_1_target_chars", 170) or 170), True),
                    ("Quickstart 1 Max", "musetalk_quickstart_1_max_chars", 80, 360, int(runtime_config.get("musetalk_quickstart_1_max_chars", 320) or 320), True),
                    ("Quickstart 2 Target", "musetalk_quickstart_2_target_chars", 60, 240, int(runtime_config.get("musetalk_quickstart_2_target_chars", 130) or 130), True),
                    ("Quickstart 2 Max", "musetalk_quickstart_2_max_chars", 80, 320, int(runtime_config.get("musetalk_quickstart_2_max_chars", 240) or 240), True),
                ],
            ),
            (
                "Streaming",
                [
                    ("Target Chars", "stream_chunk_target_chars", 40, 220, int(runtime_config.get("stream_chunk_target_chars", 85) or 85), True),
                    ("Max Chars", "stream_chunk_max_chars", 60, 320, int(runtime_config.get("stream_chunk_max_chars", 170) or 170), True),
                    ("First Chunk Min", "stream_first_chunk_min_chars", 10, 80, int(runtime_config.get("stream_first_chunk_min_chars", 28) or 28), True),
                    ("First Flush (s)", "stream_force_flush_seconds", 0.2, 2.5, float(runtime_config.get("stream_force_flush_seconds", 0.9) or 0.9), False),
                    ("Later Flush (s)", "stream_force_flush_later_seconds", 0.3, 4.0, float(runtime_config.get("stream_force_flush_later_seconds", 1.4) or 1.4), False),
                ],
            ),
        ]

        for title, items in groups:
            box = QtWidgets.QGroupBox(title)
            box_layout = QtWidgets.QVBoxLayout(box)
            for label, key, minimum, maximum, default, is_int in items:
                slider = LabeledSlider(label, minimum, maximum, default, is_int=is_int)
                slider.value_changed.connect(lambda value, k=key, integer=is_int: self.update_chunking_value(k, value, integer))
                self.chunking_sliders[key] = slider
                box_layout.addWidget(slider)
            layout.addWidget(box)

        reset_row = QtWidgets.QHBoxLayout()
        reset_row.addStretch(1)
        reset_button = QtWidgets.QPushButton("Reset Chunking Defaults")
        reset_button.clicked.connect(self.reset_chunking_defaults)
        reset_row.addWidget(reset_button)
        layout.addLayout(reset_row)

        profile_box = QtWidgets.QGroupBox("Performance Profiles")
        profile_layout = QtWidgets.QVBoxLayout(profile_box)
        profile_row = QtWidgets.QHBoxLayout()
        self.chunking_profile_combo = NoWheelComboBox()
        self.chunking_profile_combo.setObjectName("chunking_profile_combo")
        self.chunking_profile_combo.addItem("No Saved Profiles")
        profile_row.addWidget(self.chunking_profile_combo, 1)
        self.btn_chunking_profile_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_chunking_profile_refresh.setObjectName("btn_chunking_profile_refresh")
        self.btn_chunking_profile_refresh.clicked.connect(self.refresh_performance_profile_list)
        profile_row.addWidget(self.btn_chunking_profile_refresh)
        profile_layout.addLayout(profile_row)

        profile_buttons = QtWidgets.QHBoxLayout()
        self.btn_chunking_profile_load = QtWidgets.QPushButton("Load Profile")
        self.btn_chunking_profile_load.setObjectName("btn_chunking_profile_load")
        self.btn_chunking_profile_load.clicked.connect(self.load_selected_chunking_profile)
        self.btn_chunking_profile_save = QtWidgets.QPushButton("Save Current As")
        self.btn_chunking_profile_save.setObjectName("btn_chunking_profile_save")
        self.btn_chunking_profile_save.clicked.connect(self.save_current_chunking_profile)
        self.btn_chunking_profile_delete = QtWidgets.QPushButton("Delete")
        self.btn_chunking_profile_delete.setObjectName("btn_chunking_profile_delete")
        self.btn_chunking_profile_delete.clicked.connect(self.delete_selected_chunking_profile)
        profile_buttons.addWidget(self.btn_chunking_profile_load)
        profile_buttons.addWidget(self.btn_chunking_profile_save)
        profile_buttons.addWidget(self.btn_chunking_profile_delete)
        profile_layout.addLayout(profile_buttons)
        layout.addWidget(profile_box)

        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _build_dry_run_tab(self):
        widget = QtWidgets.QWidget()
        widget.setObjectName("dry_run_tab")
        layout = QtWidgets.QVBoxLayout(widget)

        intro = QtWidgets.QLabel(
            "Dry Run profiles your current hardware and recommends safer startup/chunking values without changing the live pipeline while it measures."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        self.dry_run_target_spin = QtWidgets.QSpinBox()
        self.dry_run_target_spin.setObjectName("dry_run_target_spin")
        self.dry_run_target_spin.setRange(0, 12)
        self.dry_run_target_spin.setSpecialValueText("Auto")
        self.dry_run_target_spin.setValue(0)
        self.dry_run_target_spin.valueChanged.connect(lambda _: self.save_session())
        form.addRow("Target Reply Samples", self.dry_run_target_spin)
        self.dry_run_auto_replies_checkbox = QtWidgets.QCheckBox("Auto-generate follow-up replies")
        self.dry_run_auto_replies_checkbox.setObjectName("dry_run_auto_replies_checkbox")
        self.dry_run_auto_replies_checkbox.setChecked(True)
        self.dry_run_auto_replies_checkbox.toggled.connect(lambda _: self.save_session())
        form.addRow("Hands-Free", self.dry_run_auto_replies_checkbox)
        layout.addLayout(form)

        controls = QtWidgets.QHBoxLayout()
        self.btn_dry_run_start = QtWidgets.QPushButton("Arm Dry Run")
        self.btn_dry_run_start.setObjectName("btn_dry_run_start")
        self.btn_dry_run_start.clicked.connect(self.start_dry_run_session)
        self.btn_dry_run_stop = QtWidgets.QPushButton("Stop Dry Run")
        self.btn_dry_run_stop.setObjectName("btn_dry_run_stop")
        self.btn_dry_run_stop.clicked.connect(self.stop_dry_run_session)
        self.btn_dry_run_apply = QtWidgets.QPushButton("Apply Recommendation")
        self.btn_dry_run_apply.setObjectName("btn_dry_run_apply")
        self.btn_dry_run_apply.clicked.connect(self.apply_dry_run_recommendation)
        controls.addWidget(self.btn_dry_run_start)
        controls.addWidget(self.btn_dry_run_stop)
        controls.addWidget(self.btn_dry_run_apply)
        layout.addLayout(controls)

        self.dry_run_status_label = QtWidgets.QLabel("Dry Run idle.")
        self.dry_run_status_label.setStyleSheet("color: #d8dee9; font-weight: 600;")
        layout.addWidget(self.dry_run_status_label)

        self.dry_run_summary = QtWidgets.QPlainTextEdit()
        self.dry_run_summary.setReadOnly(True)
        self.dry_run_summary.setPlaceholderText("Recommendations and measured startup metrics will appear here.")
        layout.addWidget(self.dry_run_summary, 1)

        profile_box = QtWidgets.QGroupBox("Performance Profiles")
        profile_layout = QtWidgets.QVBoxLayout(profile_box)
        profile_row = QtWidgets.QHBoxLayout()
        self.performance_profile_combo = NoWheelComboBox()
        self.performance_profile_combo.setObjectName("performance_profile_combo")
        self.performance_profile_combo.addItem("No Saved Profiles")
        profile_row.addWidget(self.performance_profile_combo, 1)
        self.btn_profile_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_profile_refresh.setObjectName("btn_profile_refresh")
        self.btn_profile_refresh.clicked.connect(self.refresh_performance_profile_list)
        profile_row.addWidget(self.btn_profile_refresh)
        profile_layout.addLayout(profile_row)

        profile_buttons = QtWidgets.QHBoxLayout()
        self.btn_profile_load = QtWidgets.QPushButton("Load Profile")
        self.btn_profile_load.setObjectName("btn_profile_load")
        self.btn_profile_load.clicked.connect(self.load_selected_performance_profile)
        self.btn_profile_save = QtWidgets.QPushButton("Save Latest As")
        self.btn_profile_save.setObjectName("btn_profile_save_latest")
        self.btn_profile_save.clicked.connect(self.save_latest_performance_profile)
        self.btn_profile_delete = QtWidgets.QPushButton("Delete")
        self.btn_profile_delete.setObjectName("btn_profile_delete")
        self.btn_profile_delete.clicked.connect(self.delete_selected_performance_profile)
        profile_buttons.addWidget(self.btn_profile_load)
        profile_buttons.addWidget(self.btn_profile_save)
        profile_buttons.addWidget(self.btn_profile_delete)
        profile_layout.addLayout(profile_buttons)
        layout.addWidget(profile_box)
        return widget

    def _build_tutorials_tab(self):
        widget = QtWidgets.QWidget()
        widget.setObjectName("tutorials_tab")
        layout = QtWidgets.QVBoxLayout(widget)

        intro = QtWidgets.QLabel(
            "Tutorials are loaded from JSON files, so new walkthroughs can be added over time without hardcoding them into the application."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(intro)

        self.tutorials_list = QtWidgets.QListWidget()
        self.tutorials_list.setObjectName("tutorials_list")
        self.tutorials_list.currentRowChanged.connect(self.on_tutorial_selection_changed)
        layout.addWidget(self.tutorials_list, 1)

        self.tutorial_description = QtWidgets.QPlainTextEdit()
        self.tutorial_description.setObjectName("tutorial_description")
        self.tutorial_description.setReadOnly(True)
        self.tutorial_description.setPlaceholderText("Select a tutorial to see its description.")
        layout.addWidget(self.tutorial_description, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.btn_tutorial_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_tutorial_refresh.setObjectName("btn_tutorial_refresh")
        self.btn_tutorial_refresh.clicked.connect(self.refresh_tutorial_list)
        self.btn_tutorial_start = QtWidgets.QPushButton("Start Tutorial")
        self.btn_tutorial_start.setObjectName("btn_tutorial_start")
        self.btn_tutorial_start.clicked.connect(self.start_selected_tutorial)
        buttons.addWidget(self.btn_tutorial_refresh)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_tutorial_start)
        layout.addLayout(buttons)
        return widget

    def _build_addons_tab(self):
        widget = QtWidgets.QWidget()
        widget.setObjectName("addons_tab")
        layout = QtWidgets.QVBoxLayout(widget)

        intro = QtWidgets.QLabel(
            "Manage addon loading here. Category toggles act like parent switches: if a parent category is off, all child addons under it are effectively off too. Changes here are global and apply on next launch."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8;")
        layout.addWidget(intro)

        controls = QtWidgets.QHBoxLayout()
        self.btn_addons_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_addons_refresh.setObjectName("btn_addons_refresh")
        self.btn_addons_refresh.clicked.connect(self._refresh_addons_management_ui)
        controls.addWidget(self.btn_addons_refresh)
        self.addons_restart_badge = QtWidgets.QLabel("Restart required")
        self.addons_restart_badge.setObjectName("addons_restart_badge")
        self.addons_restart_badge.setVisible(False)
        self.addons_restart_badge.setStyleSheet(
            "color: #ffb4b4; background: rgba(216, 74, 74, 0.16); border: 1px solid #d84a4a; border-radius: 10px; padding: 4px 10px; font-weight: 700;"
        )
        controls.addWidget(self.addons_restart_badge)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.addons_restart_note = QtWidgets.QLabel(
            "These toggles are saved in the session, not in presets. Already loaded addons keep running until you restart Neural Companion."
        )
        self.addons_restart_note.setWordWrap(True)
        self.addons_restart_note.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(self.addons_restart_note)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        layout.addWidget(scroll, 1)

        content = QtWidgets.QWidget()
        scroll.setWidget(content)
        self.addons_management_layout = QtWidgets.QVBoxLayout(content)
        self.addons_management_layout.setContentsMargins(0, 0, 0, 0)
        self.addons_management_layout.setSpacing(10)
        self._refresh_addons_management_ui()
        return widget

    def _on_addon_category_toggled(self, category_id, checked):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return
        manager.set_category_enabled(str(category_id or ""), bool(checked))
        self._refresh_addons_management_ui()
        self.save_session()

    def _on_addon_global_toggled(self, addon_id, checked):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return
        manager.set_addon_enabled(str(addon_id or ""), bool(checked))
        self._refresh_addons_management_ui()
        self.save_session()

    def _refresh_addons_management_ui(self):
        layout = getattr(self, "addons_management_layout", None)
        manager = getattr(self, "_addon_manager", None)
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        snapshot = manager.get_addon_registry_snapshot() if manager is not None else []
        if hasattr(self, "addons_restart_badge"):
            pending = bool(manager.has_pending_restart_changes()) if manager is not None else False
            self.addons_restart_badge.setVisible(pending)
            if pending and manager is not None:
                summary = manager.get_pending_restart_changes_summary()
                addon_changes = int(summary.get("addon_changes", 0) or 0)
                category_changes = int(summary.get("category_changes", 0) or 0)
                parts = []
                if addon_changes:
                    parts.append(f"{addon_changes} addon{'s' if addon_changes != 1 else ''}")
                if category_changes:
                    parts.append(f"{category_changes} categor{'y' if category_changes == 1 else 'ies'}")
                suffix = ", ".join(parts) if parts else "changes"
                self.addons_restart_badge.setText(f"Restart required: {suffix}")
        if not snapshot:
            empty = QtWidgets.QLabel("No addons discovered yet.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #8ea3b8;")
            layout.addWidget(empty)
            layout.addStretch(1)
            return
        for category in snapshot:
            category_box = QtWidgets.QGroupBox(str(category.get("label") or "Addons"))
            category_layout = QtWidgets.QVBoxLayout(category_box)
            category_layout.setContentsMargins(12, 12, 12, 12)
            category_layout.setSpacing(8)

            header_row = QtWidgets.QHBoxLayout()
            enabled_checkbox = QtWidgets.QCheckBox("Enabled")
            enabled_checkbox.setChecked(bool(category.get("enabled", True)))
            enabled_checkbox.toggled.connect(
                lambda checked, category_id=str(category.get("id") or ""): self._on_addon_category_toggled(category_id, checked)
            )
            header_row.addWidget(enabled_checkbox)
            header_row.addStretch(1)
            category_layout.addLayout(header_row)

            category_hint = QtWidgets.QLabel(
                "Turning this parent category off disables all child addons under it on next launch."
            )
            category_hint.setWordWrap(True)
            category_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            category_layout.addWidget(category_hint)

            category_enabled = bool(category.get("enabled", True))
            for addon in list(category.get("addons", []) or []):
                row_frame = QtWidgets.QFrame()
                row_frame.setObjectName("Panel")
                row_layout = QtWidgets.QVBoxLayout(row_frame)
                row_layout.setContentsMargins(10, 10, 10, 10)
                row_layout.setSpacing(4)

                top_row = QtWidgets.QHBoxLayout()
                addon_checkbox = QtWidgets.QCheckBox(str(addon.get("name") or addon.get("id") or "Addon"))
                addon_checkbox.setChecked(bool(addon.get("enabled", True)))
                addon_checkbox.setEnabled(category_enabled)
                addon_checkbox.toggled.connect(
                    lambda checked, addon_id=str(addon.get("id") or ""): self._on_addon_global_toggled(addon_id, checked)
                )
                top_row.addWidget(addon_checkbox)

                status_bits = []
                if not category_enabled:
                    status_bits.append("inactive: parent category disabled")
                elif not bool(addon.get("effective_enabled", True)):
                    status_bits.append("inactive on next launch")
                else:
                    status_bits.append("active on next launch")
                record_state = str(addon.get("state") or "").strip()
                if record_state:
                    status_bits.append(f"current state: {record_state}")
                status = QtWidgets.QLabel(" | ".join(status_bits))
                status.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                top_row.addStretch(1)
                top_row.addWidget(status, 0, QtCore.Qt.AlignRight)
                row_layout.addLayout(top_row)

                meta_bits = [str(addon.get("id") or "").strip()]
                version = str(addon.get("version") or "").strip()
                if version:
                    meta_bits.append(f"v{version}")
                permissions = list(addon.get("permissions", []) or [])
                if permissions:
                    meta_bits.append(", ".join(permissions))
                meta = QtWidgets.QLabel(" | ".join([bit for bit in meta_bits if bit]))
                meta.setWordWrap(True)
                meta.setStyleSheet("color: #6f8599; font-size: 11px;")
                row_layout.addWidget(meta)

                description = str(addon.get("description") or "").strip()
                if description:
                    description_label = QtWidgets.QLabel(description)
                    description_label.setWordWrap(True)
                    description_label.setStyleSheet("color: #9fb3c8; font-size: 11px;")
                    row_layout.addWidget(description_label)

                category_layout.addWidget(row_frame)
            layout.addWidget(category_box)
        layout.addStretch(1)
