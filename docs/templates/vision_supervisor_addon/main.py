from __future__ import annotations

from PySide6 import QtWidgets

from core.addons.base import BaseAddon


CONTRIBUTOR_ID = "nc.my_vision_supervisor.behavior"
SOURCE_ID = "screen"


class Addon(BaseAddon):
    TAB_ID = "my_vision_supervisor_tab"

    def initialize(self, context):
        super().initialize(context)
        self.enabled = True
        self.trigger = "The screen clearly shows something important."
        self.action = "Offer one short, in-character observation."
        self._sensory_service = context.get_service("qt.sensory")
        self._register_prompt_contributor()
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Supervisor",
            area="vision_source",
            parent_tab_id=SOURCE_ID,
            order=230,
            tooltip="Template supervisor rules.",
            metadata={"checkable": True},
            factory=self._build_tab,
        )
        return None

    def shutdown(self):
        self._unregister_prompt_contributor()
        return None

    def invoke_capability(self, capability, payload=None):
        if str(capability or "") != "ui.tab_enabled":
            return None
        request = dict(payload or {})
        if str(request.get("tab_id") or "") not in {"", self.TAB_ID}:
            return None
        if str(request.get("action") or "get").lower() == "set":
            self.enabled = bool(request.get("enabled", True))
            self._publish_state()
        return {"enabled": bool(self.enabled)}

    def export_session_state(self):
        return {
            "my_vision_supervisor_enabled": bool(self.enabled),
            "my_vision_supervisor_trigger": str(self.trigger or ""),
            "my_vision_supervisor_action": str(self.action or ""),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        payload = dict(session or {})
        if "my_vision_supervisor_enabled" in payload:
            self.enabled = bool(payload["my_vision_supervisor_enabled"])
        if "my_vision_supervisor_trigger" in payload:
            self.trigger = str(payload["my_vision_supervisor_trigger"] or "")
        if "my_vision_supervisor_action" in payload:
            self.action = str(payload["my_vision_supervisor_action"] or "")
        self._register_prompt_contributor()
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def _render_prompt(self):
        return (
            f"This behavior applies only to {SOURCE_ID} input.\n"
            f"Trigger: {self.trigger}\n"
            f"Action: {self.action}\n"
            "If the trigger is not clearly present, set should_speak=false."
        )

    def _register_prompt_contributor(self):
        if self._sensory_service is None:
            return
        if not self.enabled:
            self._unregister_prompt_contributor()
            return
        self._sensory_service.register_prompt_contributor(
            contributor_id=CONTRIBUTOR_ID,
            source_id=SOURCE_ID,
            label="My Vision Supervisor",
            prompt=self._render_prompt(),
            order=230,
            metadata={"type": "behavior_rule"},
        )

    def _unregister_prompt_contributor(self):
        if self._sensory_service is not None:
            self._sensory_service.unregister_prompt_contributor(CONTRIBUTOR_ID)

    def _build_tab(self, _context):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(widget)
        enabled = QtWidgets.QCheckBox("Enabled")
        enabled.setChecked(bool(self.enabled))
        trigger = QtWidgets.QPlainTextEdit(str(self.trigger or ""))
        action = QtWidgets.QPlainTextEdit(str(self.action or ""))
        layout.addRow("", enabled)
        layout.addRow("Trigger", trigger)
        layout.addRow("Action", action)
        enabled.toggled.connect(self._set_enabled)
        trigger.textChanged.connect(lambda: self._set_trigger(trigger.toPlainText()))
        action.textChanged.connect(lambda: self._set_action(action.toPlainText()))
        return widget

    def _set_enabled(self, checked):
        self.enabled = bool(checked)
        self._publish_state()

    def _set_trigger(self, text):
        self.trigger = str(text or "").strip()
        self._publish_state()

    def _set_action(self, text):
        self.action = str(text or "").strip()
        self._publish_state()

    def _publish_state(self):
        self._register_prompt_contributor()
        shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
        if shell is not None:
            shell.notify_settings_changed()
