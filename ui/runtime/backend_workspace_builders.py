from PySide6 import QtCore, QtWidgets

from addons.musetalk_avatar import real_ui_bridge as musetalk_real_ui_bridge
from ui.widgets.basic import LabeledSlider, NoWheelComboBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    # Imported lazily because qt_app imports this mixin before it imports engine.
    import engine

    return engine.RUNTIME_CONFIG

class BackendWorkspaceBuilderMixin:
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
                musetalk_real_ui_bridge.chunking_slider_specs(runtime_config),
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
