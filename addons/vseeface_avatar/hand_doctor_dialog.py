"""Hand calibration dialog used by the VSeeFace body controls."""

from PySide6 import QtCore, QtWidgets

from core.addons.qt_host_services import QtHandCalibrationService
from ui.theme_support import apply_app_slider_style


def _hand_service(owner):
    try:
        return QtHandCalibrationService(owner)
    except Exception:
        return None


class HandDoctorDialog(QtWidgets.QDialog):
    HAND_KEYS = (
        ("Fingers", ("finger_x", "finger_y", "finger_z")),
        ("Thumb", ("thumb_x", "thumb_y", "thumb_z")),
    )

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.axis_controls = {}
        self.setWindowTitle("Hand Rotation Doctor")
        self.resize(420, 540)
        self.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet(
            """
            QDialog { background: #11161d; color: #e5e9f0; }
            QLabel { color: #e5e9f0; }
            QCheckBox { color: #f2f5f9; spacing: 9px; min-height: 24px; }
            QCheckBox::indicator {
                width: 20px;
                height: 20px;
                image: url(ui/assets/checkbox_round_inactive.svg);
                background: transparent;
                border: 0px;
            }
            QCheckBox::indicator:checked {
                width: 20px;
                height: 20px;
                image: url(ui/assets/checkbox_round_active.svg);
                background: transparent;
                border: 0px;
            }
            QGroupBox {
                border: 1px solid #283342;
                border-radius: 10px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: 600;
                color: #d8dee9;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QPushButton {
                background: #223247;
                border: 1px solid #324b69;
                border-radius: 10px;
                padding: 8px 12px;
                font-weight: 600;
                color: #f2f5f9;
            }
            QPushButton:hover { background: #29405b; }
            """
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        self.debug_toggle = QtWidgets.QCheckBox("Activate Debug Override")
        hand_debug = self._hand_debug()
        self.debug_toggle.setChecked(bool(hand_debug.get("active", False)))
        self.debug_toggle.toggled.connect(self._on_toggle_debug)
        layout.addWidget(self.debug_toggle)

        preset_row = QtWidgets.QHBoxLayout()
        preset_label = QtWidgets.QLabel("Load preset to edit:")
        preset_label.setStyleSheet("font-weight: 600; color: #d8dee9;")
        preset_row.addWidget(preset_label)
        preset_row.addStretch(1)
        layout.addLayout(preset_row)

        preset_buttons = QtWidgets.QHBoxLayout()
        relaxed_button = QtWidgets.QPushButton("Edit Relaxed")
        relaxed_button.clicked.connect(lambda: self.load_values("relaxed"))
        preset_buttons.addWidget(relaxed_button)
        fist_button = QtWidgets.QPushButton("Edit Fist")
        fist_button.clicked.connect(lambda: self.load_values("fist"))
        preset_buttons.addWidget(fist_button)
        layout.addLayout(preset_buttons)

        for section_title, keys in self.HAND_KEYS:
            section = QtWidgets.QGroupBox(section_title)
            section_layout = QtWidgets.QFormLayout(section)
            section_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
            section_layout.setFormAlignment(QtCore.Qt.AlignTop)
            section_layout.setHorizontalSpacing(10)
            section_layout.setVerticalSpacing(8)
            for key in keys:
                row = self._create_axis_row(key)
                section_layout.addRow(key.replace("_", " ").title(), row)
            layout.addWidget(section)

        button_row = QtWidgets.QHBoxLayout()
        self.relaxed_save_button = QtWidgets.QPushButton("Set Relaxed")
        self.relaxed_save_button.clicked.connect(lambda: self.save_as("relaxed"))
        button_row.addWidget(self.relaxed_save_button)

        self.fist_save_button = QtWidgets.QPushButton("Set Fist")
        self.fist_save_button.clicked.connect(lambda: self.save_as("fist"))
        button_row.addWidget(self.fist_save_button)
        layout.addLayout(button_row)

        close_row = QtWidgets.QHBoxLayout()
        close_row.addStretch(1)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self.refresh_from_debug_state()

    def _create_axis_row(self, key):
        row_widget = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        slider.setRange(-1800, 1800)
        slider.setSingleStep(1)
        slider.setPageStep(100)
        apply_app_slider_style(slider)
        value_label = QtWidgets.QLabel("0.0")
        value_label.setMinimumWidth(48)
        value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        value_label.setStyleSheet("color: #9fb3c8;")

        def on_value_changed(raw_value):
            value = raw_value / 10.0
            service = self._hand_service()
            if service is not None:
                service.set_debug_axis(key, value)
            value_label.setText(f"{value:.1f}")

        slider.valueChanged.connect(on_value_changed)
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(value_label)
        self.axis_controls[key] = (slider, value_label)
        return row_widget

    def _hand_service(self):
        return _hand_service(self.owner)

    def _hand_debug(self):
        service = self._hand_service()
        return service.debug_state() if service is not None else {"active": False}

    def _on_toggle_debug(self, checked):
        service = self._hand_service()
        active = service.set_debug_active(bool(checked)) if service is not None else bool(checked)
        print(f"[QtGUI] Hand Debug Mode: {active}")

    def refresh_from_debug_state(self):
        hand_debug = self._hand_debug()
        for key, (slider, label) in self.axis_controls.items():
            value = float(hand_debug.get(key, 0.0))
            slider.blockSignals(True)
            slider.setValue(int(round(value * 10.0)))
            slider.blockSignals(False)
            label.setText(f"{value:.1f}")

    def load_values(self, target_key):
        service = self._hand_service()
        if service is None or not service.load_calibration_preset(target_key):
            print(f"[QtGUI] No calibration data for {target_key}")
            return
        print(f"[QtGUI] Loading '{target_key}' for editing...")
        self.debug_toggle.setChecked(True)
        self.refresh_from_debug_state()

    def save_as(self, target_key):
        service = self._hand_service()
        if service is None:
            print(f"[QtGUI] Could not save hand calibration for {target_key}")
            return
        service.save_calibration_preset(target_key)
        print(f"[QtGUI] Saved hand calibration for {target_key}")
        self.owner.save_current_body()
        if target_key == "relaxed":
            button = self.relaxed_save_button
            default_text = "Set Relaxed"
        else:
            button = self.fist_save_button
            default_text = "Set Fist"
        button.setText(f"{default_text} Saved!")
        QtCore.QTimer.singleShot(1800, lambda b=button, t=default_text: b.setText(t))
