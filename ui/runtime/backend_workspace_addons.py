import sys

from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import LabeledSlider, NoWheelComboBox, NoWheelSpinBox


DEFAULT_MAX_RESPONSE_TOKENS = 600

ADDON_PURPOSE_GROUPS = (
    ("core", "Core", "Chat providers, memory, hotkeys, and base runtime support."),
    ("voice", "Voice", "Speech-to-text, text-to-speech, and voice runtime addons."),
    ("visual", "Visual", "Images, avatars, vision sources, overlays, and visual feedback."),
    ("story", "Story", "Story mode, replay, soundtrack, and narrative tools."),
    ("phone", "Phone", "LAN pairing, phone remote, and mobile companion features."),
    ("experimental", "Experimental", "Newer or heavier visual systems that may need extra testing."),
)


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
            "Manage addons by what they do. Launch Groups are parent switches for the next Neural Companion start; individual addon switches let you turn one feature on or off without hunting through technical categories."
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

    def _on_addon_requirements_install_requested(self, addon_id):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return
        record = manager.get_addon_record(str(addon_id or ""))
        if record is None:
            return
        requirements_path = record.root_dir / "requirements.txt"
        if not requirements_path.exists():
            return
        try:
            requirements_preview = requirements_path.read_text(encoding="utf-8").strip()
        except Exception:
            requirements_preview = str(requirements_path)
        if len(requirements_preview) > 1200:
            requirements_preview = requirements_preview[:1200].rstrip() + "\n..."
        message = (
            f"Addon '{record.manifest.name}' needs to install/update Python libraries from:\n\n"
            f"{requirements_path}\n\n"
            f"Requirements:\n{requirements_preview or '(empty requirements file)'}\n\n"
            "Install these addon requirements into the active Neural Companion Python environment now?"
        )
        choice = QtWidgets.QMessageBox.question(
            self,
            "Install Addon Requirements",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if choice != QtWidgets.QMessageBox.Yes:
            return
        try:
            from core.dependency_repair import addon_requirements_status, install_args_for_requirements

            status = addon_requirements_status(
                addon_id=record.manifest.id,
                label=record.manifest.name,
                requirements_path=requirements_path,
            )
            requirements_hash = str(status.get("requirements_hash") or "")
            install_args = install_args_for_requirements(requirements_path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Install Addon Requirements", f"Could not prepare addon requirements install: {exc}")
            return
        process = QtCore.QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(install_args)
        process.finished.connect(
            lambda exit_code, exit_status, addon_id=record.manifest.id, req_hash=requirements_hash, req_path=str(requirements_path), proc=process: self._on_addon_requirements_install_finished(
                addon_id,
                req_hash,
                req_path,
                proc,
                exit_code,
                exit_status,
            )
        )
        process.errorOccurred.connect(
            lambda error, addon_id=record.manifest.id, req_hash=requirements_hash, req_path=str(requirements_path): self._on_addon_requirements_install_error(
                addon_id,
                req_hash,
                req_path,
                error,
            )
        )
        self._addon_requirements_install_process = process
        self.btn_addons_refresh.setEnabled(False)
        process.start()

    def _on_addon_requirements_install_error(self, addon_id, requirements_hash, requirements_path, error):
        try:
            from core.dependency_repair import record_install_result

            record_install_result(
                target_id=str(addon_id or ""),
                kind="addon",
                requirements_hash=str(requirements_hash or ""),
                requirements_path=str(requirements_path or ""),
                success=False,
                error=str(error),
            )
        except Exception:
            pass
        self._addon_requirements_install_process = None
        if hasattr(self, "btn_addons_refresh"):
            self.btn_addons_refresh.setEnabled(True)
        self._refresh_addons_management_ui()

    def _on_addon_requirements_install_finished(self, addon_id, requirements_hash, requirements_path, process, exit_code, _exit_status):
        details = ""
        try:
            details = bytes(process.readAllStandardError()).decode(errors="replace").strip()
        except Exception:
            details = ""
        success = int(exit_code) == 0
        try:
            from core.dependency_repair import record_install_result

            record_install_result(
                target_id=str(addon_id or ""),
                kind="addon",
                requirements_hash=str(requirements_hash or ""),
                requirements_path=str(requirements_path or ""),
                success=success,
                error=details,
            )
        except Exception:
            pass
        self._addon_requirements_install_process = None
        if hasattr(self, "btn_addons_refresh"):
            self.btn_addons_refresh.setEnabled(True)
        self._refresh_addons_management_ui()
        if not success:
            QtWidgets.QMessageBox.warning(
                self,
                "Install Addon Requirements",
                f"Addon requirements install failed for '{addon_id}'.\n\n{details or 'No details were reported.'}",
            )

    def _addon_purpose_for_row(self, addon):
        addon_id = str(addon.get("id") or "").strip().lower()
        name = str(addon.get("name") or "").strip().lower()
        category_id = str(addon.get("_category_id") or "").strip().lower()
        haystack = f"{addon_id} {name} {category_id}"
        if any(token in haystack for token in ("main_chat_remote", "phone", "remote")):
            return "phone"
        if any(token in haystack for token in ("neural_face", "ai_presence", "scenic")):
            return "experimental"
        if any(
            token in haystack
            for token in (
                "multi_persona",
                "roleplay",
                "audio_story",
                "story",
                "chat_session_player",
                "conversation replay",
                "spotify",
                "soundtrack",
            )
        ):
            return "story"
        if any(token in haystack for token in ("tts", "stt", "whisper", "chatterbox", "pockettts", "gemini tts", "voice")):
            return "voice"
        if any(
            token in haystack
            for token in (
                "visual",
                "vision",
                "avatar",
                "musetalk",
                "vam",
                "vseeface",
                "screen",
                "webcam",
                "clipboard",
                "heart_rate",
                "orb",
                "presence",
            )
        ):
            return "visual"
        return "core"

    def _addons_by_purpose(self, snapshot):
        grouped = {key: [] for key, _label, _hint in ADDON_PURPOSE_GROUPS}
        category_rows = []
        for category in list(snapshot or []):
            category_id = str(category.get("id") or "").strip()
            category_label = str(category.get("label") or category_id or "Addons").strip()
            category_enabled = bool(category.get("enabled", True))
            category_rows.append(
                {
                    "id": category_id,
                    "label": category_label,
                    "enabled": category_enabled,
                }
            )
            for addon in list(category.get("addons", []) or []):
                row = dict(addon or {})
                row["_category_id"] = category_id
                row["_category_label"] = category_label
                row["_category_enabled"] = category_enabled
                purpose = self._addon_purpose_for_row(row)
                grouped.setdefault(purpose, []).append(row)
        for rows in grouped.values():
            rows.sort(key=lambda item: str(item.get("name") or item.get("id") or "").lower())
        return category_rows, grouped

    def _add_addon_category_switches(self, layout, categories):
        category_box = QtWidgets.QGroupBox("Launch Groups")
        category_layout = QtWidgets.QVBoxLayout(category_box)
        category_layout.setContentsMargins(12, 12, 12, 12)
        category_layout.setSpacing(8)

        hint = QtWidgets.QLabel("These parent switches apply on the next launch and affect every addon in that launch group.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        category_layout.addWidget(hint)

        grid_widget = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for index, category in enumerate(list(categories or [])):
            checkbox = QtWidgets.QCheckBox(str(category.get("label") or category.get("id") or "Addons"))
            checkbox.setChecked(bool(category.get("enabled", True)))
            checkbox.toggled.connect(
                lambda checked, category_id=str(category.get("id") or ""): self._on_addon_category_toggled(category_id, checked)
            )
            grid.addWidget(checkbox, index // 3, index % 3)
        category_layout.addWidget(grid_widget)
        layout.addWidget(category_box)

    def _add_addon_row(self, layout, addon):
        category_enabled = bool(addon.get("_category_enabled", True))
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
        category_label = str(addon.get("_category_label") or "Addons")
        if not category_enabled:
            status_bits.append(f"inactive: {category_label} launch group is off")
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

        meta_bits = [category_label, str(addon.get("id") or "").strip()]
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

        dependency_status = addon.get("dependency_status")
        if isinstance(dependency_status, dict):
            dependency_row = QtWidgets.QHBoxLayout()
            dependency_message = str(dependency_status.get("message") or "").strip()
            dependency_label = QtWidgets.QLabel(dependency_message or "Addon requirements status unavailable.")
            dependency_label.setWordWrap(True)
            dependency_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            dependency_row.addWidget(dependency_label, 1)
            if bool(dependency_status.get("needs_install", False)) and bool(dependency_status.get("installable", False)):
                install_button = QtWidgets.QPushButton("Install requirements")
                install_button.setToolTip("Install only this addon's requirements.txt into the active NC Python environment.")
                install_button.clicked.connect(
                    lambda _checked=False, addon_id=str(addon.get("id") or ""): self._on_addon_requirements_install_requested(addon_id)
                )
                dependency_row.addWidget(install_button)
            row_layout.addLayout(dependency_row)

        layout.addWidget(row_frame)

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
        category_rows, grouped = self._addons_by_purpose(snapshot)
        self._add_addon_category_switches(layout, category_rows)
        for purpose_id, label, hint_text in ADDON_PURPOSE_GROUPS:
            purpose_box = QtWidgets.QGroupBox(label)
            purpose_layout = QtWidgets.QVBoxLayout(purpose_box)
            purpose_layout.setContentsMargins(12, 12, 12, 12)
            purpose_layout.setSpacing(8)

            hint = QtWidgets.QLabel(hint_text)
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
            purpose_layout.addWidget(hint)

            rows = list(grouped.get(purpose_id, []) or [])
            if rows:
                for addon in rows:
                    self._add_addon_row(purpose_layout, addon)
            else:
                empty = QtWidgets.QLabel("No addons in this group right now.")
                empty.setWordWrap(True)
                empty.setStyleSheet("color: #6f8599; font-size: 11px;")
                purpose_layout.addWidget(empty)
            layout.addWidget(purpose_box)
        layout.addStretch(1)
