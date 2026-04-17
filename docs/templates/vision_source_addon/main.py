from __future__ import annotations

import time

from PySide6 import QtWidgets

from core.addons.base import BaseAddon


PROVIDER_ID = "my_source"


class Addon(BaseAddon):
    TAB_ID = "my_source_tab"

    def initialize(self, context):
        super().initialize(context)
        self.enabled = True
        self.latest_text = ""
        self._sensory_service = context.get_service("qt.sensory")
        if self._sensory_service is not None:
            self._sensory_service.register_provider(
                provider_id=PROVIDER_ID,
                label="My Source",
                instruction="Optional hidden sensory context from My Source.",
                order=150,
                capture_handler=self._capture_sensory_snapshot,
                metadata={"kind": "text"},
            )
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Source",
            area="vision_source",
            parent_tab_id=PROVIDER_ID,
            order=100,
            tooltip="My Source controls.",
            factory=self._build_tab,
        )
        return None

    def shutdown(self):
        if getattr(self, "_sensory_service", None) is not None:
            self._sensory_service.unregister_provider(PROVIDER_ID)
        return None

    def export_session_state(self):
        return {
            "my_source_enabled": bool(self.enabled),
            "my_source_latest_text": str(self.latest_text or ""),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = dict(session or {})
        if "my_source_enabled" in payload:
            self.enabled = bool(payload["my_source_enabled"])
        if "my_source_latest_text" in payload:
            self.latest_text = str(payload["my_source_latest_text"] or "")
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def _build_tab(self, _context):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        checkbox = QtWidgets.QCheckBox("Enable source")
        checkbox.setChecked(bool(self.enabled))
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText("Example hidden sensory text")
        edit.setText(str(self.latest_text or ""))
        checkbox.toggled.connect(self._set_enabled)
        edit.editingFinished.connect(lambda: self._set_latest_text(edit.text()))
        layout.addWidget(checkbox)
        layout.addWidget(edit)
        layout.addStretch(1)
        return widget

    def _set_enabled(self, checked):
        self.enabled = bool(checked)
        self._notify_settings_changed()

    def _set_latest_text(self, text):
        self.latest_text = str(text or "").strip()
        self._notify_settings_changed()

    def _notify_settings_changed(self):
        shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
        if shell is not None:
            shell.notify_settings_changed()

    def _capture_sensory_snapshot(self, capture_context=None):
        if not self.enabled or not str(self.latest_text or "").strip():
            return None
        return {
            "captured_at": time.time(),
            "source": PROVIDER_ID,
            "content_text": str(self.latest_text or "").strip(),
        }
