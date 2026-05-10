from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import LabeledSlider, NoWheelComboBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600


def _runtime_config():
    # Imported lazily because qt_app imports this mixin before it imports engine.
    from ui.runtime import engine_access as engine

    return engine.RUNTIME_CONFIG

class BackendWorkspaceAddonsMixin:
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
