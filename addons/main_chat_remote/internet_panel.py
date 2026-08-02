from __future__ import annotations

import io
import json
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

try:
    import qrcode
except Exception:
    qrcode = None


class InternetRemotePanel(QtWidgets.QWidget):
    settingsSubmitted = QtCore.Signal(dict)
    enabledChanged = QtCore.Signal(bool)
    installHelperRequested = QtCore.Signal()
    stagingTestRequested = QtCore.Signal()
    productionIssueRequested = QtCore.Signal()
    refreshPublicIpRequested = QtCore.Signal()
    createEnrollmentRequested = QtCore.Signal()
    approveEnrollmentRequested = QtCore.Signal(str)
    rejectEnrollmentRequested = QtCore.Signal(str)
    revokeDeviceRequested = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("main_chat_internet_panel")
        self._snapshot: dict[str, Any] = {}

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget(scroll)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 22, 14)
        layout.setSpacing(10)

        intro = QtWidgets.QLabel(
            "Optional secure Internet access for the phone app. LAN pairing stays available and unchanged."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        connection = QtWidgets.QGroupBox("Connection")
        connection_form = QtWidgets.QFormLayout(connection)
        self.enabled_checkbox = QtWidgets.QCheckBox("Enable saved Internet Remote")
        self.enabled_checkbox.setObjectName("main_chat_internet_enabled_checkbox")
        self.enabled_checkbox.toggled.connect(self.enabledChanged)
        connection_form.addRow(self.enabled_checkbox)
        self.ddns_edit = QtWidgets.QLineEdit()
        self.ddns_edit.setObjectName("main_chat_internet_ddns_edit")
        self.ddns_edit.setPlaceholderText("nc.example.ddns.net")
        connection_form.addRow("Dynamic DNS hostname", self.ddns_edit)
        self.public_ip_edit = QtWidgets.QLineEdit()
        self.public_ip_edit.setObjectName("main_chat_internet_public_ip_edit")
        self.public_ip_edit.setPlaceholderText("Public IPv4 or IPv6 address")
        connection_form.addRow("Public IP", self.public_ip_edit)
        self.external_port_spin = QtWidgets.QSpinBox()
        self.external_port_spin.setRange(1, 65_535)
        self.external_port_spin.setValue(443)
        connection_form.addRow("Public HTTPS port", self.external_port_spin)
        self.email_edit = QtWidgets.QLineEdit()
        self.email_edit.setPlaceholderText("Certificate account email")
        connection_form.addRow("ACME email", self.email_edit)
        self.terms_checkbox = QtWidgets.QCheckBox("I accept the certificate authority terms")
        connection_form.addRow(self.terms_checkbox)
        self.confirm_ip_checkbox = QtWidgets.QCheckBox("Ask before accepting a changed public IP")
        self.confirm_ip_checkbox.setChecked(True)
        connection_form.addRow(self.confirm_ip_checkbox)

        advanced = QtWidgets.QGroupBox("Advanced local ports")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_form = QtWidgets.QFormLayout(advanced)
        self.gateway_port_spin = QtWidgets.QSpinBox()
        self.gateway_port_spin.setRange(1, 65_535)
        self.gateway_port_spin.setValue(8788)
        advanced_form.addRow("HTTPS gateway", self.gateway_port_spin)
        self.acme_port_spin = QtWidgets.QSpinBox()
        self.acme_port_spin.setRange(1, 65_535)
        self.acme_port_spin.setValue(8780)
        advanced_form.addRow("Certificate HTTP challenge", self.acme_port_spin)
        connection_form.addRow(advanced)

        connection_buttons = QtWidgets.QHBoxLayout()
        save_button = QtWidgets.QPushButton("Save Internet settings")
        save_button.clicked.connect(self._submit_settings)
        connection_buttons.addWidget(save_button)
        refresh_ip_button = QtWidgets.QPushButton("Detect public IP")
        refresh_ip_button.clicked.connect(self.refreshPublicIpRequested)
        connection_buttons.addWidget(refresh_ip_button)
        connection_buttons.addStretch(1)
        connection_form.addRow(connection_buttons)
        layout.addWidget(connection)

        certificate = QtWidgets.QGroupBox("Certificate")
        certificate_layout = QtWidgets.QVBoxLayout(certificate)
        self.certificate_status_label = QtWidgets.QLabel("Certificate has not been checked.")
        self.certificate_status_label.setWordWrap(True)
        certificate_layout.addWidget(self.certificate_status_label)
        certificate_buttons = QtWidgets.QHBoxLayout()
        install_button = QtWidgets.QPushButton("Install verified helper")
        install_button.clicked.connect(self.installHelperRequested)
        certificate_buttons.addWidget(install_button)
        staging_button = QtWidgets.QPushButton("Run staging test")
        staging_button.clicked.connect(self.stagingTestRequested)
        certificate_buttons.addWidget(staging_button)
        production_button = QtWidgets.QPushButton("Issue production certificate")
        production_button.clicked.connect(self.productionIssueRequested)
        certificate_buttons.addWidget(production_button)
        certificate_buttons.addStretch(1)
        certificate_layout.addLayout(certificate_buttons)
        layout.addWidget(certificate)

        router = QtWidgets.QGroupBox("Router setup")
        router_layout = QtWidgets.QVBoxLayout(router)
        self.router_label = QtWidgets.QLabel()
        self.router_label.setWordWrap(True)
        self.router_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        router_layout.addWidget(self.router_label)
        layout.addWidget(router)

        pairing = QtWidgets.QGroupBox("Pair an Internet phone")
        pairing_layout = QtWidgets.QVBoxLayout(pairing)
        pairing_info = QtWidgets.QLabel(
            "Create a short-lived enrollment QR. The phone waits until you explicitly approve its name below."
        )
        pairing_info.setWordWrap(True)
        pairing_layout.addWidget(pairing_info)
        create_button = QtWidgets.QPushButton("Create enrollment QR")
        create_button.clicked.connect(self.createEnrollmentRequested)
        pairing_layout.addWidget(create_button, 0, QtCore.Qt.AlignLeft)
        self.enrollment_qr = QtWidgets.QLabel("No active enrollment QR.")
        self.enrollment_qr.setFixedSize(220, 220)
        self.enrollment_qr.setAlignment(QtCore.Qt.AlignCenter)
        self.enrollment_qr.setStyleSheet("background: #ffffff; color: #172231; border: 1px solid #536579;")
        pairing_layout.addWidget(self.enrollment_qr, 0, QtCore.Qt.AlignLeft)
        self.enrollment_uri = QtWidgets.QLineEdit()
        self.enrollment_uri.setReadOnly(True)
        self.enrollment_uri.setPlaceholderText("Enrollment setup link appears here")
        pairing_layout.addWidget(self.enrollment_uri)
        self.pending_list = QtWidgets.QListWidget()
        self.pending_list.setMaximumHeight(120)
        pairing_layout.addWidget(self.pending_list)
        pending_buttons = QtWidgets.QHBoxLayout()
        approve_button = QtWidgets.QPushButton("Approve selected phone")
        approve_button.clicked.connect(self._approve_selected)
        pending_buttons.addWidget(approve_button)
        reject_button = QtWidgets.QPushButton("Reject selected phone")
        reject_button.clicked.connect(self._reject_selected)
        pending_buttons.addWidget(reject_button)
        pending_buttons.addStretch(1)
        pairing_layout.addLayout(pending_buttons)
        layout.addWidget(pairing)

        devices = QtWidgets.QGroupBox("Paired Internet devices")
        devices_layout = QtWidgets.QVBoxLayout(devices)
        self.device_list = QtWidgets.QListWidget()
        self.device_list.setMaximumHeight(140)
        devices_layout.addWidget(self.device_list)
        revoke_button = QtWidgets.QPushButton("Revoke selected device")
        revoke_button.clicked.connect(self._revoke_selected)
        devices_layout.addWidget(revoke_button, 0, QtCore.Qt.AlignLeft)
        layout.addWidget(devices)

        diagnostics = QtWidgets.QGroupBox("Status and diagnostics")
        diagnostics_layout = QtWidgets.QVBoxLayout(diagnostics)
        self.status_label = QtWidgets.QLabel("Internet Remote is disabled.")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        diagnostics_layout.addWidget(self.status_label)
        copy_button = QtWidgets.QPushButton("Copy redacted diagnostics")
        copy_button.clicked.connect(self._copy_diagnostics)
        diagnostics_layout.addWidget(copy_button, 0, QtCore.Qt.AlignLeft)
        layout.addWidget(diagnostics)
        layout.addStretch(1)

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

    def status_text(self) -> str:
        return self.status_label.text()

    def apply_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = dict(snapshot or {})
        settings = dict(self._snapshot.get("settings") or {})
        widgets = (
            self.enabled_checkbox,
            self.ddns_edit,
            self.public_ip_edit,
            self.external_port_spin,
            self.email_edit,
            self.terms_checkbox,
            self.confirm_ip_checkbox,
            self.gateway_port_spin,
            self.acme_port_spin,
        )
        blockers = [QtCore.QSignalBlocker(widget) for widget in widgets]
        self.enabled_checkbox.setChecked(bool(settings.get("enabled", False)))
        self.ddns_edit.setText(str(settings.get("ddns_hostname") or ""))
        self.public_ip_edit.setText(str(settings.get("public_ip") or ""))
        self.external_port_spin.setValue(int(settings.get("external_port") or 443))
        self.email_edit.setText(str(settings.get("account_email") or ""))
        self.terms_checkbox.setChecked(bool(settings.get("terms_accepted", False)))
        self.confirm_ip_checkbox.setChecked(bool(settings.get("confirm_ip_changes", True)))
        self.gateway_port_spin.setValue(int(settings.get("gateway_port") or 8788))
        self.acme_port_spin.setValue(int(settings.get("acme_port") or 8780))
        del blockers

        gateway = dict(self._snapshot.get("gateway") or {})
        certificate = dict(self._snapshot.get("certificate") or {})
        task = str(self._snapshot.get("task") or "")
        error = str(self._snapshot.get("last_error") or "")
        certificate_status = str(certificate.get("status") or "").replace("_", " ")
        status_parts = [
            f"Saved: {'enabled' if settings.get('enabled') else 'disabled'}",
            f"Public gateway: {'running' if gateway.get('running') else 'closed'}",
        ]
        if task:
            status_parts.append(f"Working: {task}")
        if error:
            status_parts.append(f"Error: {error}")
        elif certificate_status:
            status_parts.append(f"Certificate: {certificate_status}")
        self.status_label.setText("\n".join(status_parts))

        helper = "installed" if certificate.get("helper_installed") else "not installed"
        certificate_state = "active" if certificate.get("certificate_exists") else "not active"
        expires_at = float(certificate.get("expires_at", 0.0) or 0.0)
        expiry = QtCore.QDateTime.fromSecsSinceEpoch(int(expires_at)).toString(QtCore.Qt.ISODate) if expires_at else "unknown"
        self.certificate_status_label.setText(
            f"Verified helper: {helper}\nProduction certificate: {certificate_state}\nExpiry: {expiry}"
        )
        self.router_label.setText(
            f"Forward TCP {int(settings.get('external_port') or 443)} to this PC's TCP "
            f"{int(settings.get('gateway_port') or 8788)}. During certificate issue/renewal, also forward "
            f"public TCP 80 to this PC's TCP {int(settings.get('acme_port') or 8780)}. "
            "Keep the existing LAN backend port private; do not forward it."
        )

        setup_uri = str(self._snapshot.get("enrollment_setup_uri") or "")
        self.enrollment_uri.setText(setup_uri)
        self._set_qr(setup_uri)
        self.pending_list.clear()
        for pending in self._snapshot.get("pending_enrollments") or ():
            item_data = dict(pending or {})
            item = QtWidgets.QListWidgetItem(
                f"{item_data.get('device_name') or 'Unnamed phone'} ({item_data.get('device_id') or 'unknown id'})"
            )
            item.setData(QtCore.Qt.UserRole, str(item_data.get("enrollment_id") or ""))
            self.pending_list.addItem(item)
        self.device_list.clear()
        for device in self._snapshot.get("devices") or ():
            item_data = dict(device or {})
            revoked = " — revoked" if item_data.get("revoked") else ""
            item = QtWidgets.QListWidgetItem(
                f"{item_data.get('device_name') or 'Unnamed phone'} ({item_data.get('device_id') or 'unknown id'}){revoked}"
            )
            item.setData(QtCore.Qt.UserRole, str(item_data.get("device_id") or ""))
            self.device_list.addItem(item)

    def _submit_settings(self) -> None:
        self.settingsSubmitted.emit(
            {
                "enabled": self.enabled_checkbox.isChecked(),
                "ddns_hostname": self.ddns_edit.text(),
                "public_ip": self.public_ip_edit.text(),
                "external_port": self.external_port_spin.value(),
                "gateway_port": self.gateway_port_spin.value(),
                "acme_port": self.acme_port_spin.value(),
                "account_email": self.email_edit.text(),
                "terms_accepted": self.terms_checkbox.isChecked(),
                "confirm_ip_changes": self.confirm_ip_checkbox.isChecked(),
            }
        )

    def _selected_id(self, widget: QtWidgets.QListWidget) -> str:
        item = widget.currentItem()
        return str(item.data(QtCore.Qt.UserRole) or "") if item is not None else ""

    def _approve_selected(self) -> None:
        value = self._selected_id(self.pending_list)
        if value:
            self.approveEnrollmentRequested.emit(value)

    def _reject_selected(self) -> None:
        value = self._selected_id(self.pending_list)
        if value:
            self.rejectEnrollmentRequested.emit(value)

    def _revoke_selected(self) -> None:
        value = self._selected_id(self.device_list)
        if value:
            self.revokeDeviceRequested.emit(value)

    def _set_qr(self, setup_uri: str) -> None:
        self.enrollment_qr.setPixmap(QtGui.QPixmap())
        if not setup_uri:
            self.enrollment_qr.setText("No active enrollment QR.")
            return
        if qrcode is None:
            self.enrollment_qr.setText("QR support unavailable. Copy the setup link instead.")
            return
        try:
            image = qrcode.make(setup_uri)
            output = io.BytesIO()
            image.save(output, format="PNG")
            pixmap = QtGui.QPixmap()
            if pixmap.loadFromData(output.getvalue(), "PNG"):
                self.enrollment_qr.setPixmap(
                    pixmap.scaled(212, 212, QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
                )
                return
        except Exception:
            pass
        self.enrollment_qr.setText("QR could not be rendered. Copy the setup link instead.")

    def _copy_diagnostics(self) -> None:
        public = {
            "settings": {
                key: value
                for key, value in dict(self._snapshot.get("settings") or {}).items()
                if key not in {"account_email"}
            },
            "gateway": dict(self._snapshot.get("gateway") or {}),
            "certificate": dict(self._snapshot.get("certificate") or {}),
            "task": self._snapshot.get("task", ""),
            "last_error": self._snapshot.get("last_error", ""),
        }
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(json.dumps(public, indent=2, sort_keys=True))
