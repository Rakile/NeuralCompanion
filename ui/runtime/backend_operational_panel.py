from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import NoWheelComboBox, NoWheelTabWidget
from ui.widgets.telemetry import PipelineTelemetryWidget


class BackendOperationalPanelMixin:
    """Build the backend operational panel used by the runtime bridge."""

    def _build_right_panel(self):
        panel = self._wrap_panel()
        panel.setMinimumSize(0, 0)
        panel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        outer_layout = QtWidgets.QVBoxLayout(panel)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setMinimumSize(0, 0)
        scroll.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        outer_layout.addWidget(scroll)

        content = QtWidgets.QWidget()
        content.setMinimumSize(0, 0)
        scroll.setWidget(content)

        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        layout.addWidget(self._make_header("Operational View", "Conversation + Telemetry"))

        self.pipeline_telemetry_box = QtWidgets.QGroupBox("Buffer Race")
        self.pipeline_telemetry_box.setMinimumSize(0, 0)
        self.pipeline_telemetry_box.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        telemetry_layout = QtWidgets.QVBoxLayout(self.pipeline_telemetry_box)
        telemetry_layout.setContentsMargins(10, 12, 10, 10)
        telemetry_layout.setSpacing(8)
        self.pipeline_telemetry_widget = PipelineTelemetryWidget()
        telemetry_layout.addWidget(self.pipeline_telemetry_widget)
        layout.addWidget(self.pipeline_telemetry_box)

        mic_row = getattr(self, "mic_status_row_widget", None)
        if mic_row is not None:
            layout.addWidget(mic_row, 0)

        self.right_tabs = NoWheelTabWidget()
        self.right_tabs.setObjectName("right_tabs")
        self.right_tabs.setMinimumSize(0, 0)
        self.right_tabs.setMinimumHeight(230)
        self.right_tabs.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.right_tabs.currentChanged.connect(self._on_right_tab_changed)
        layout.addWidget(self.right_tabs, 1)

        system_tab = QtWidgets.QWidget()
        system_tab.setObjectName("system_console_tab")
        system_tab.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        system_layout = QtWidgets.QVBoxLayout(system_tab)
        console_header = QtWidgets.QHBoxLayout()
        self.console_status = QtWidgets.QLabel("0 lines | autoscroll on")
        console_header.addWidget(self.console_status)
        console_header.addStretch(1)
        self.console_autoscroll_button = QtWidgets.QPushButton("Autoscroll: On")
        self.console_autoscroll_button.clicked.connect(self.toggle_console_autoscroll)
        console_header.addWidget(self.console_autoscroll_button)
        self.console_clear_button = QtWidgets.QPushButton("Clear")
        self.console_clear_button.clicked.connect(self.clear_console)
        console_header.addWidget(self.console_clear_button)
        self.console_edit = QtWidgets.QPlainTextEdit()
        self.console_edit.setObjectName("console_edit")
        self.console_edit.setReadOnly(True)
        self.console_edit.setMinimumSize(0, 0)
        self.console_edit.setMinimumHeight(90)
        system_layout.addLayout(console_header)
        system_layout.addWidget(self.console_edit, 1)
        self.system_console_tab = system_tab
        self.right_tabs.addTab(system_tab, "System Console")

        chat_tab = QtWidgets.QWidget()
        chat_tab.setObjectName("chat_runtime_tab")
        chat_tab.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        chat_layout = QtWidgets.QVBoxLayout(chat_tab)
        chat_header = QtWidgets.QHBoxLayout()
        self.chat_status = QtWidgets.QLabel("autoscroll on | context 0/20")
        chat_header.addWidget(self.chat_status)
        chat_header.addStretch(1)
        chat_font_label = QtWidgets.QLabel("Font Size")
        chat_header.addWidget(chat_font_label)
        self.chat_font_size_combo = NoWheelComboBox()
        self.chat_font_size_combo.setObjectName("chat_font_size_combo")
        self.chat_font_size_combo.setMinimumWidth(74)
        for size in self._chat_font_size_choices():
            self.chat_font_size_combo.addItem(str(size), size)
        self.chat_font_size_combo.blockSignals(True)
        try:
            default_index = self.chat_font_size_combo.findData(12)
            if default_index >= 0:
                self.chat_font_size_combo.setCurrentIndex(default_index)
        finally:
            self.chat_font_size_combo.blockSignals(False)
        self.chat_font_size_combo.currentIndexChanged.connect(self.on_chat_font_size_changed)
        chat_header.addWidget(self.chat_font_size_combo)
        self.chat_quick_save_button = QtWidgets.QPushButton("Quick Save")
        self.chat_quick_save_button.clicked.connect(self.quick_save_chat_context)
        chat_header.addWidget(self.chat_quick_save_button)
        self.chat_quick_load_button = QtWidgets.QPushButton("Quick Load")
        self.chat_quick_load_button.clicked.connect(self.quick_load_chat_context)
        chat_header.addWidget(self.chat_quick_load_button)
        self.chat_edit_mode_button = QtWidgets.QPushButton("Edit Mode")
        self.chat_edit_mode_button.clicked.connect(self.enter_chat_edit_mode)
        chat_header.addWidget(self.chat_edit_mode_button)
        self.chat_apply_edit_button = QtWidgets.QPushButton("Apply Edit")
        self.chat_apply_edit_button.clicked.connect(self.apply_chat_edit_mode)
        self.chat_apply_edit_button.setVisible(False)
        chat_header.addWidget(self.chat_apply_edit_button)
        self.chat_cancel_edit_button = QtWidgets.QPushButton("Cancel Edit")
        self.chat_cancel_edit_button.clicked.connect(self.cancel_chat_edit_mode)
        self.chat_cancel_edit_button.setVisible(False)
        chat_header.addWidget(self.chat_cancel_edit_button)
        self.chat_autoscroll_button = QtWidgets.QPushButton("Autoscroll: On")
        self.chat_autoscroll_button.clicked.connect(self.toggle_chat_autoscroll)
        chat_header.addWidget(self.chat_autoscroll_button)
        self.chat_clear_button = QtWidgets.QPushButton("Clear")
        self.chat_clear_button.clicked.connect(self.clear_chat)
        chat_header.addWidget(self.chat_clear_button)
        self.chat_edit = QtWidgets.QTextEdit()
        self.chat_edit.setObjectName("chat_edit")
        self.chat_edit.setReadOnly(True)
        self.chat_edit.setMinimumSize(0, 0)
        self.chat_edit.setMinimumHeight(90)
        self._apply_chat_font_size(12, update_combo=False)
        self.chat_edit.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.chat_edit.customContextMenuRequested.connect(self._show_chat_context_menu)
        chat_layout.addLayout(chat_header)
        chat_layout.addWidget(self.chat_edit, 1)
        chat_input_row = QtWidgets.QHBoxLayout()
        chat_input_row.setSpacing(8)
        self.chat_message_input = QtWidgets.QLineEdit()
        self.chat_message_input.setObjectName("chat_message_input")
        self.chat_message_input.setPlaceholderText("Type a message...")
        self.chat_message_input.returnPressed.connect(self.send_typed_chat_message)
        chat_input_row.addWidget(self.chat_message_input, 1)
        self.chat_send_button = QtWidgets.QPushButton("Send")
        self.chat_send_button.setObjectName("chat_send_button")
        self.chat_send_button.clicked.connect(self.send_typed_chat_message)
        chat_input_row.addWidget(self.chat_send_button)
        chat_layout.addLayout(chat_input_row)
        self.chat_tab = chat_tab
        self.right_tabs.addTab(chat_tab, "Chat")

        controls = QtWidgets.QGridLayout()
        self.btn_regenerate = self._make_action_button("Regenerate", lambda: self.trigger_control_action("regenerate_response"))
        self.btn_retry = self._make_action_button("Retry Input", lambda: self.trigger_control_action("retry_user_input"))
        self.btn_pause = self._make_action_button("Pause / Resume", lambda: self.trigger_control_action("pause_speech"))
        self.btn_skip = self._make_action_button("Skip Speech", lambda: self.trigger_control_action("skip_speech"))
        self.btn_skip_user = self._make_action_button("Skip User Reply", lambda: self.trigger_control_action("skip_user_reply"))
        self._control_action_buttons = {
            "regenerate_response": self.btn_regenerate,
            "retry_user_input": self.btn_retry,
            "pause_speech": self.btn_pause,
            "skip_speech": self.btn_skip,
            "skip_user_reply": self.btn_skip_user,
        }
        for index, button in enumerate([self.btn_regenerate, self.btn_retry, self.btn_pause, self.btn_skip, self.btn_skip_user]):
            controls.addWidget(button, 0, index)
        layout.addLayout(controls)

        self.btn_start = QtWidgets.QPushButton("INITIALIZE SYSTEM")
        self.btn_start.setObjectName("btn_start_engine")
        self.btn_start.clicked.connect(self.start_engine)
        self.btn_start.setStyleSheet("background: #1d6e52; border: 1px solid #2cc985; font-size: 13px; min-height: 44px;")
        self.btn_stop = QtWidgets.QPushButton("TERMINATE")
        self.btn_stop.setObjectName("btn_stop_engine")
        self.btn_stop.clicked.connect(self.stop_engine)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background: #6f2222; border: 1px solid #c92c2c; min-height: 42px;")
        self.btn_reset = QtWidgets.QPushButton("RESET CHAT MEMORY")
        self.btn_reset.setObjectName("btn_reset_chat")
        self.btn_reset.clicked.connect(self.reset_chat_session)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        layout.addWidget(self.btn_reset)

        self._qt_hotkey_shortcuts = {}
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()

        return panel

    def _make_action_button(self, text, handler):
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(handler)
        button.setEnabled(False)
        button.setMinimumHeight(50)
        return button
