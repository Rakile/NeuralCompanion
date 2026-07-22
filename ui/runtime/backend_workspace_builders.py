from PySide6 import QtCore, QtWidgets

from ui.runtime.system_prompt_library import (
    QUICK_PROMPT_LIMIT,
    add_prompt_to_quick,
    all_prompt_records,
    find_prompt,
    is_prompt_quick,
    prompt_record_for_text,
    quick_prompt_records,
    remove_prompt_from_quick,
    save_prompt_as,
)
from ui.shell_specs import UI_SHELL_CHUNKING_SPECS
from ui.widgets.basic import LabeledSlider, NoWheelComboBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    # Imported lazily because qt_app imports this mixin before it imports engine.
    from ui.runtime import engine_access as engine

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
        self.voice_combo.setToolTip("Voice reference used by the selected TTS backend when voice cloning is available.")
        self.voice_combo.currentTextChanged.connect(self.on_voice_changed)
        self.btn_voice_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_voice_refresh.setObjectName("btn_voice_refresh")
        self.btn_voice_refresh.setToolTip("Refresh voice reference files from the voices folder.")
        self.btn_voice_refresh.clicked.connect(lambda _checked=False: self.refresh_voice_list())
        self.use_wav_file_checkbox = QtWidgets.QCheckBox("Use wav file")
        self.use_wav_file_checkbox.setObjectName("use_wav_file_checkbox")
        self.use_wav_file_checkbox.setFixedSize(136, 32)
        self.use_wav_file_checkbox.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.use_wav_file_checkbox.setChecked(True)
        self.use_wav_file_checkbox.setToolTip("Use the selected .wav file as the TTS voice reference. Disable to use the backend's built-in/default voice.")
        self.use_wav_file_checkbox.toggled.connect(self.on_use_wav_file_changed)
        self.use_wav_file_checkbox.setStyleSheet(
            "QCheckBox#use_wav_file_checkbox {"
            " color: #eadff2;"
            " font-weight: 700;"
            " background: #171223;"
            " border: 1px solid #8f4db8;"
            " border-radius: 8px;"
            " padding: 5px 10px;"
            " spacing: 7px;"
            "}"
            "QCheckBox#use_wav_file_checkbox:hover { background: #241a35; }"
            "QCheckBox#use_wav_file_checkbox::indicator {"
            " width: 20px;"
            " height: 20px;"
            " image: url(ui/assets/checkbox_round_inactive.svg);"
            " background: transparent;"
            " border: 0px;"
            "}"
            "QCheckBox#use_wav_file_checkbox::indicator:checked {"
            " width: 20px;"
            " height: 20px;"
            " image: url(ui/assets/checkbox_round_active.svg);"
            " background: transparent;"
            " border: 0px;"
            "}"
        )
        voice_row = QtWidgets.QHBoxLayout()
        voice_row.addWidget(self.voice_combo, 1)
        voice_row.addWidget(self.use_wav_file_checkbox, 0)
        voice_row.addWidget(self.btn_voice_refresh, 0)
        layout.addWidget(QtWidgets.QLabel("Voice Clone"))
        layout.addLayout(voice_row)

        self.identity_relay_persona_row = QtWidgets.QWidget()
        self.identity_relay_persona_row.setObjectName("identity_relay_persona_row")
        identity_relay_layout = QtWidgets.QHBoxLayout(self.identity_relay_persona_row)
        identity_relay_layout.setContentsMargins(0, 0, 0, 0)
        self.identity_relay_ref_label = QtWidgets.QLabel("Connected Identity")
        self.identity_relay_ref_label.setObjectName("identity_relay_ref_label")
        identity_relay_layout.addWidget(self.identity_relay_ref_label)
        self.identity_relay_ref_combo = NoWheelComboBox()
        self.identity_relay_ref_combo.setObjectName("identity_relay_ref_combo")
        identity_relay_layout.addWidget(self.identity_relay_ref_combo, 1)
        self.identity_relay_connection_status_label = QtWidgets.QLabel()
        self.identity_relay_connection_status_label.setObjectName("identity_relay_connection_status_label")
        self.identity_relay_connection_status_label.setWordWrap(True)
        identity_relay_layout.addWidget(self.identity_relay_connection_status_label, 1)
        self.identity_relay_review_button = QtWidgets.QPushButton("Review")
        self.identity_relay_review_button.setObjectName("identity_relay_review_button")
        self.identity_relay_review_button.setToolTip("Review the connected identity classification and use decisions.")
        self.identity_relay_review_button.setVisible(False)
        identity_relay_layout.addWidget(self.identity_relay_review_button)
        self.identity_relay_persona_row.setVisible(False)
        layout.addWidget(self.identity_relay_persona_row)

        self.emotional_text = QtWidgets.QPlainTextEdit()
        self.emotional_text.setObjectName("emotional_text")
        self.emotional_text.setPlaceholderText("Technical rules / expressive tags")
        self.emotional_text.setToolTip("Persona-facing technical rules, such as valid emotion and sound tags. Saved with presets.")
        self.emotional_text.setMinimumHeight(0)
        self.emotional_text.setMinimumSize(0, 90)
        self.system_prompt_text = QtWidgets.QPlainTextEdit()
        self.system_prompt_text.setObjectName("system_prompt_text")
        self.system_prompt_text.setPlaceholderText("System prompt")
        self.system_prompt_text.setToolTip("The main system prompt sent to the chat provider. Right-click to refine it with the current provider.")
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
        self._install_system_prompt_library_controls(prompt_group, self.system_prompt_text)
        prompt_layout.addWidget(self.system_prompt_text)

        text_splitter.addWidget(technical_group)
        text_splitter.addWidget(prompt_group)
        text_splitter.setStretchFactor(0, 1)
        text_splitter.setStretchFactor(1, 1)
        layout.addWidget(text_splitter, 1)

        apply_button = QtWidgets.QPushButton("Apply Changes")
        apply_button.setObjectName("btn_apply_text_config")
        apply_button.setToolTip("Apply persona text changes to the current runtime/session settings.")
        apply_button.clicked.connect(self.apply_text_config)
        layout.addWidget(apply_button)
        return scroll

    def _install_system_prompt_library_controls(self, prompt_group, text_widget):
        if prompt_group is None or text_widget is None:
            return None
        try:
            existing = prompt_group.findChild(QtWidgets.QWidget, "system_prompt_library_panel")
        except Exception:
            existing = None
        if existing is not None:
            return existing

        panel = QtWidgets.QWidget(prompt_group)
        panel.setObjectName("system_prompt_library_panel")
        panel_layout = QtWidgets.QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 4)
        panel_layout.setSpacing(6)

        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(6)
        self.system_prompt_library_combo = NoWheelComboBox()
        self.system_prompt_library_combo.setObjectName("system_prompt_library_combo")
        self.system_prompt_library_combo.setToolTip("Load a built-in or custom saved system prompt into the editor below.")
        self.system_prompt_library_combo.currentIndexChanged.connect(self._on_system_prompt_library_selected)
        top_row.addWidget(self.system_prompt_library_combo, 1)

        self.btn_system_prompt_save_as = QtWidgets.QPushButton("Save As")
        self.btn_system_prompt_save_as.setObjectName("btn_system_prompt_save_as")
        self.btn_system_prompt_save_as.setToolTip("Save the current system prompt as a custom prompt. The name is generated automatically.")
        self.btn_system_prompt_save_as.clicked.connect(lambda _checked=False: self._on_system_prompt_save_as_clicked())
        top_row.addWidget(self.btn_system_prompt_save_as, 0)

        self.btn_system_prompt_add_quick = QtWidgets.QPushButton("Add Quick")
        self.btn_system_prompt_add_quick.setObjectName("btn_system_prompt_add_quick")
        self.btn_system_prompt_add_quick.setToolTip("Add the selected saved prompt to the six quick-select slots.")
        self.btn_system_prompt_add_quick.clicked.connect(lambda _checked=False: self._on_system_prompt_add_quick_clicked())
        top_row.addWidget(self.btn_system_prompt_add_quick, 0)

        self.btn_system_prompt_remove_quick = QtWidgets.QPushButton("Remove Quick")
        self.btn_system_prompt_remove_quick.setObjectName("btn_system_prompt_remove_quick")
        self.btn_system_prompt_remove_quick.setToolTip("Remove the selected saved prompt from quick select.")
        self.btn_system_prompt_remove_quick.clicked.connect(lambda _checked=False: self._on_system_prompt_remove_quick_clicked())
        top_row.addWidget(self.btn_system_prompt_remove_quick, 0)

        self.system_prompt_refine_nsfw_checkbox = QtWidgets.QCheckBox("NSFW refine")
        self.system_prompt_refine_nsfw_checkbox.setObjectName("system_prompt_refine_nsfw_checkbox")
        self.system_prompt_refine_nsfw_checkbox.setToolTip(
            "When refining, preserve mature/adult-theme intent with guardrails. Off keeps refinement SFW/non-explicit."
        )
        top_row.addWidget(self.system_prompt_refine_nsfw_checkbox, 0)
        panel_layout.addLayout(top_row)

        quick_row = QtWidgets.QHBoxLayout()
        quick_row.setSpacing(6)
        quick_label = QtWidgets.QLabel("Quick")
        quick_label.setToolTip("Explicit quick-select prompts. Use Add Quick or Remove Quick to manage these slots.")
        quick_row.addWidget(quick_label, 0)
        self.system_prompt_quick_checkboxes = []
        for index in range(QUICK_PROMPT_LIMIT):
            checkbox = QtWidgets.QCheckBox(str(index + 1))
            checkbox.setObjectName(f"system_prompt_quick_{index + 1}_checkbox")
            checkbox.setToolTip("Quick prompt shortcut. Use Add Quick to fill these slots.")
            checkbox.toggled.connect(lambda checked, slot=index: self._on_system_prompt_quick_toggled(slot, checked))
            self.system_prompt_quick_checkboxes.append(checkbox)
            quick_row.addWidget(checkbox, 0)
        quick_row.addStretch(1)
        panel_layout.addLayout(quick_row)

        self.system_prompt_library_status_label = QtWidgets.QLabel("")
        self.system_prompt_library_status_label.setObjectName("system_prompt_library_status_label")
        self.system_prompt_library_status_label.setWordWrap(True)
        self.system_prompt_library_status_label.setToolTip("Shows saved prompt library actions and validation messages.")
        panel_layout.addWidget(self.system_prompt_library_status_label)

        layout = prompt_group.layout()
        if layout is not None and hasattr(layout, "insertWidget"):
            layout.insertWidget(0, panel)
        self._refresh_system_prompt_library_controls()
        return panel

    def _system_prompt_text_value(self) -> str:
        widget = getattr(self, "system_prompt_text", None)
        if widget is None or not hasattr(widget, "toPlainText"):
            return ""
        return str(widget.toPlainText() or "")

    def _set_system_prompt_text_value(self, prompt: str):
        widget = getattr(self, "system_prompt_text", None)
        if widget is None or not hasattr(widget, "setPlainText"):
            return
        text = str(prompt or "")
        current = str(widget.toPlainText() or "") if hasattr(widget, "toPlainText") else ""
        if current != text:
            widget.setPlainText(text)
        try:
            from ui.runtime.engine_access import update_runtime_config

            update_runtime_config("system_prompt", text.strip())
        except Exception:
            pass

    def _set_system_prompt_library_status(self, message: str):
        label = getattr(self, "system_prompt_library_status_label", None)
        if label is not None and hasattr(label, "setText"):
            label.setText(str(message or ""))

    def _selected_system_prompt_library_id(self) -> str:
        combo = getattr(self, "system_prompt_library_combo", None)
        if combo is not None and hasattr(combo, "currentData"):
            prompt_id = str(combo.currentData() or "").strip()
            if prompt_id:
                return prompt_id
        record = prompt_record_for_text(self._system_prompt_text_value())
        return str(record.get("id") or "").strip() if record else ""

    def _selected_system_prompt_library_record(self):
        prompt_id = self._selected_system_prompt_library_id()
        return find_prompt(prompt_id) if prompt_id else None

    def _refresh_system_prompt_quick_buttons(self):
        prompt_id = self._selected_system_prompt_library_id()
        has_prompt = bool(prompt_id and find_prompt(prompt_id))
        quick = bool(has_prompt and is_prompt_quick(prompt_id))
        add_button = getattr(self, "btn_system_prompt_add_quick", None)
        remove_button = getattr(self, "btn_system_prompt_remove_quick", None)
        if add_button is not None and hasattr(add_button, "setEnabled"):
            add_button.setEnabled(has_prompt and not quick and len(quick_prompt_records()) < QUICK_PROMPT_LIMIT)
        if remove_button is not None and hasattr(remove_button, "setEnabled"):
            remove_button.setEnabled(has_prompt and quick)

    def _refresh_system_prompt_library_controls(self, selected_id: str = ""):
        combo = getattr(self, "system_prompt_library_combo", None)
        if combo is not None and hasattr(combo, "clear"):
            previous = bool(combo.blockSignals(True)) if hasattr(combo, "blockSignals") else False
            try:
                combo.clear()
                combo.addItem("Load system prompt...", "")
                for record in all_prompt_records():
                    addon = str(record.get("addon") or "").strip()
                    name = str(record.get("name") or "Prompt").strip()
                    label = f"{name} ({addon})" if addon and addon not in name else name
                    combo.addItem(label, str(record.get("id") or ""))
                if selected_id:
                    for index in range(combo.count()):
                        if str(combo.itemData(index) or "") == str(selected_id):
                            combo.setCurrentIndex(index)
                            break
                    else:
                        combo.setCurrentIndex(0)
                else:
                    combo.setCurrentIndex(0)
            finally:
                if hasattr(combo, "blockSignals"):
                    combo.blockSignals(previous)

        quick_records = quick_prompt_records()
        checkboxes = list(getattr(self, "system_prompt_quick_checkboxes", []) or [])
        for index, checkbox in enumerate(checkboxes):
            previous = bool(checkbox.blockSignals(True)) if hasattr(checkbox, "blockSignals") else False
            try:
                if index < len(quick_records):
                    record = quick_records[index]
                    checkbox.setText(f"{index + 1}. {record.get('name', 'Prompt')}")
                    checkbox.setProperty("prompt_id", str(record.get("id") or ""))
                    checkbox.setEnabled(True)
                    checkbox.setChecked(False)
                    checkbox.setToolTip(f"Load custom prompt: {record.get('name', 'Prompt')}")
                else:
                    checkbox.setText(f"{index + 1}. Empty")
                    checkbox.setProperty("prompt_id", "")
                    checkbox.setEnabled(False)
                    checkbox.setChecked(False)
                    checkbox.setToolTip("Empty quick prompt shortcut. Select a saved prompt and press Add Quick to fill it.")
            finally:
                if hasattr(checkbox, "blockSignals"):
                    checkbox.blockSignals(previous)
        self._refresh_system_prompt_quick_buttons()

    def _load_system_prompt_record(self, record):
        if not isinstance(record, dict):
            return
        prompt = str(record.get("prompt") or "").strip()
        if not prompt:
            return
        self._set_system_prompt_text_value(prompt)
        prompt_id = str(record.get("id") or "")
        checkboxes = list(getattr(self, "system_prompt_quick_checkboxes", []) or [])
        for checkbox in checkboxes:
            previous = bool(checkbox.blockSignals(True)) if hasattr(checkbox, "blockSignals") else False
            try:
                checkbox.setChecked(str(checkbox.property("prompt_id") or "") == prompt_id)
            finally:
                if hasattr(checkbox, "blockSignals"):
                    checkbox.blockSignals(previous)
        self._set_system_prompt_library_status(f"Loaded: {record.get('name', 'System prompt')}")
        self._refresh_system_prompt_quick_buttons()

    def _on_system_prompt_library_selected(self, index: int):
        combo = getattr(self, "system_prompt_library_combo", None)
        if combo is None or not hasattr(combo, "itemData"):
            return
        prompt_id = str(combo.itemData(index) or "").strip()
        if not prompt_id:
            return
        record = find_prompt(prompt_id)
        if record:
            self._load_system_prompt_record(record)
        self._refresh_system_prompt_quick_buttons()

    def _on_system_prompt_quick_toggled(self, slot: int, checked: bool):
        if not checked:
            return
        checkboxes = list(getattr(self, "system_prompt_quick_checkboxes", []) or [])
        if slot < 0 or slot >= len(checkboxes):
            return
        checkbox = checkboxes[slot]
        prompt_id = str(checkbox.property("prompt_id") or "").strip()
        if not prompt_id:
            return
        for index, other in enumerate(checkboxes):
            if index == slot:
                continue
            previous = bool(other.blockSignals(True)) if hasattr(other, "blockSignals") else False
            try:
                other.setChecked(False)
            finally:
                if hasattr(other, "blockSignals"):
                    other.blockSignals(previous)
        record = find_prompt(prompt_id)
        if record:
            self._load_system_prompt_record(record)
            combo = getattr(self, "system_prompt_library_combo", None)
            if combo is not None and hasattr(combo, "count"):
                previous = bool(combo.blockSignals(True)) if hasattr(combo, "blockSignals") else False
                try:
                    for index in range(combo.count()):
                        if str(combo.itemData(index) or "") == prompt_id:
                            combo.setCurrentIndex(index)
                            break
                finally:
                    if hasattr(combo, "blockSignals"):
                        combo.blockSignals(previous)

    def _on_system_prompt_save_as_clicked(self):
        prompt = self._system_prompt_text_value().strip()
        if not prompt:
            self._set_system_prompt_library_status("Nothing to save: the system prompt is empty.")
            return
        try:
            record = save_prompt_as(prompt)
        except Exception as exc:
            self._set_system_prompt_library_status(f"Save failed: {exc}")
            return
        self._refresh_system_prompt_library_controls(str(record.get("id") or ""))
        self._set_system_prompt_library_status(
            f"Saved custom prompt: {record.get('name', 'System prompt')}. Use Add Quick if you want it in quick select."
        )

    def _on_system_prompt_add_quick_clicked(self):
        record = self._selected_system_prompt_library_record()
        if not record:
            self._set_system_prompt_library_status("Choose a saved prompt before adding it to quick select.")
            return
        prompt_id = str(record.get("id") or "")
        try:
            add_prompt_to_quick(prompt_id)
        except Exception as exc:
            self._set_system_prompt_library_status(f"Add Quick failed: {exc}")
            return
        self._refresh_system_prompt_library_controls(prompt_id)
        self._set_system_prompt_library_status(f"Added to quick select: {record.get('name', 'System prompt')}")

    def _on_system_prompt_remove_quick_clicked(self):
        record = self._selected_system_prompt_library_record()
        if not record:
            self._set_system_prompt_library_status("Choose a saved prompt before removing it from quick select.")
            return
        prompt_id = str(record.get("id") or "")
        remove_prompt_from_quick(prompt_id)
        self._refresh_system_prompt_library_controls(prompt_id)
        self._set_system_prompt_library_status(f"Removed from quick select: {record.get('name', 'System prompt')}")

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

        musetalk_chunking_specs = self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "ui.chunking_slider_specs",
            {"backend": self, "runtime_config": runtime_config},
            default=[],
            provider_id="musetalk",
        )
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
                list(musetalk_chunking_specs or []),
            ),
            (
                "Streaming",
                [
                    ("Target Chars", "stream_chunk_target_chars", 40, 220, int(runtime_config.get("stream_chunk_target_chars", 80) or 80), True),
                    ("Max Chars", "stream_chunk_max_chars", 60, 320, int(runtime_config.get("stream_chunk_max_chars", 185) or 185), True),
                    ("First Chunk Min", "stream_first_chunk_min_chars", 10, 80, int(runtime_config.get("stream_first_chunk_min_chars", 40) or 40), True),
                    ("First Flush (s)", "stream_force_flush_seconds", 0.2, 2.5, float(runtime_config.get("stream_force_flush_seconds", 0.30) or 0.30), False),
                    ("Later Flush (s)", "stream_force_flush_later_seconds", 0.3, 4.0, float(runtime_config.get("stream_force_flush_later_seconds", 0.70) or 0.70), False),
                ],
            ),
        ]

        for title, items in groups:
            box = QtWidgets.QGroupBox(title)
            box_layout = QtWidgets.QVBoxLayout(box)
            for label, key, minimum, maximum, default, is_int in items:
                slider = LabeledSlider(label, minimum, maximum, default, is_int=is_int)
                spec = UI_SHELL_CHUNKING_SPECS.get(str(key), {})
                tooltip = str(spec.get("tooltip") or "").strip()
                if tooltip:
                    slider.setToolTip(tooltip)
                slider.value_changed.connect(lambda value, k=key, integer=is_int: self.update_chunking_value(k, value, integer))
                self.chunking_sliders[key] = slider
                box_layout.addWidget(slider)
            layout.addWidget(box)

        reset_row = QtWidgets.QHBoxLayout()
        reset_row.addStretch(1)
        reset_button = QtWidgets.QPushButton("Reset Chunking Defaults")
        reset_button.setToolTip("Restore the built-in chunking defaults for this session.")
        reset_button.clicked.connect(self.reset_chunking_defaults)
        reset_row.addWidget(reset_button)
        layout.addLayout(reset_row)

        profile_box = QtWidgets.QGroupBox("Performance Profiles")
        profile_layout = QtWidgets.QVBoxLayout(profile_box)
        profile_row = QtWidgets.QHBoxLayout()
        self.chunking_profile_combo = NoWheelComboBox()
        self.chunking_profile_combo.setObjectName("chunking_profile_combo")
        self.chunking_profile_combo.addItem("No Saved Profiles")
        self.chunking_profile_combo.setToolTip("Saved performance/chunking profiles measured by Dry Run or saved manually.")
        profile_row.addWidget(self.chunking_profile_combo, 1)
        self.btn_chunking_profile_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_chunking_profile_refresh.setObjectName("btn_chunking_profile_refresh")
        self.btn_chunking_profile_refresh.setToolTip("Refresh the list of saved performance profiles.")
        self.btn_chunking_profile_refresh.clicked.connect(self.refresh_performance_profile_list)
        profile_row.addWidget(self.btn_chunking_profile_refresh)
        profile_layout.addLayout(profile_row)

        profile_buttons = QtWidgets.QHBoxLayout()
        self.btn_chunking_profile_load = QtWidgets.QPushButton("Load Profile")
        self.btn_chunking_profile_load.setObjectName("btn_chunking_profile_load")
        self.btn_chunking_profile_load.setToolTip("Apply the selected profile's chunking and performance settings.")
        self.btn_chunking_profile_load.clicked.connect(self.load_selected_chunking_profile)
        self.btn_chunking_profile_save = QtWidgets.QPushButton("Save Current As")
        self.btn_chunking_profile_save.setObjectName("btn_chunking_profile_save")
        self.btn_chunking_profile_save.setToolTip("Save the current chunking values as a reusable profile.")
        self.btn_chunking_profile_save.clicked.connect(self.save_current_chunking_profile)
        self.btn_chunking_profile_delete = QtWidgets.QPushButton("Delete")
        self.btn_chunking_profile_delete.setObjectName("btn_chunking_profile_delete")
        self.btn_chunking_profile_delete.setToolTip("Delete the selected saved profile.")
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
