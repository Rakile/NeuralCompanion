"""Headless Vision supervisor template for typed native-QML adapters."""

from __future__ import annotations

from core.addons.base import BaseAddon


CONTRIBUTOR_ID = "nc.my_vision_supervisor.behavior"
SOURCE_ID = "screen"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.enabled = True
        self.trigger = "The screen clearly shows something important."
        self.action = "Offer one short, in-character observation."
        self._sensory_service = context.get_service("qt.sensory")
        self._register_prompt_contributor()

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if name == "my_vision_supervisor.snapshot":
            return self.export_session_state()
        if name == "my_vision_supervisor.update":
            key = str(request.get("key") or "").strip()
            if key == "enabled":
                self.enabled = bool(request.get("value"))
            elif key == "trigger":
                self.trigger = str(request.get("value") or "").strip()
            elif key == "action":
                self.action = str(request.get("value") or "").strip()
            else:
                raise KeyError(key)
            self._register_prompt_contributor()
            return self.export_session_state()
        return None

    def shutdown(self):
        self._unregister_prompt_contributor()

    def export_session_state(self):
        return {
            "my_vision_supervisor_enabled": bool(self.enabled),
            "my_vision_supervisor_trigger": str(self.trigger or ""),
            "my_vision_supervisor_action": str(self.action or ""),
        }

    export_preset_state = export_session_state

    def import_session_state(self, session):
        payload = dict(session or {})
        self.enabled = bool(payload.get("my_vision_supervisor_enabled", self.enabled))
        self.trigger = str(payload.get("my_vision_supervisor_trigger", self.trigger) or "")
        self.action = str(payload.get("my_vision_supervisor_action", self.action) or "")
        self._register_prompt_contributor()

    import_preset_state = import_session_state

    def _render_prompt(self):
        return (
            f"This behavior applies only to {SOURCE_ID} input.\n"
            f"Trigger: {self.trigger}\nAction: {self.action}\n"
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
