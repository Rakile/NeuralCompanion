from core.addons import BaseAddon
from addons.ai_presence_mode.native_controller import AIPresenceModeController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = AIPresenceModeController(context)
        context.logger.info("[AIPresence] Native AI Presence service initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        if name not in {
            "ai_presence.set_mood",
            "ai_presence.reset_floating_position",
            "runtime.ai_presence.snapshot",
            "runtime.ai_presence.update",
            "runtime.ai_presence.action",
        }:
            return None
        request = dict(payload or {})
        if name == "ai_presence.set_mood":
            value = str(request.get("mood") or request.get("value") or "neutral").strip() or "neutral"
            try:
                from visual_presence import runtime as visual_presence_runtime

                visual_presence_runtime.set_presence_mood(value)
            except Exception as exc:
                return {"ok": False, "error": f"AI Presence mood could not be set: {exc}"}
            return {"ok": True, "mood": value}
        if name == "runtime.ai_presence.snapshot":
            return self.controller.native_snapshot()
        if name == "runtime.ai_presence.update":
            if bool(request.get("preview", False)):
                return self.controller.native_preview_setting(
                    request.get("key"), request.get("value")
                )
            return self.controller.native_update_setting(request.get("key"), request.get("value"))
        if name == "runtime.ai_presence.action":
            return self.controller.native_action(
                request.get("action"), request.get("payload")
            )
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.reset_ai_presence_floating_position()
        except Exception as exc:
            return {"ok": False, "error": f"AI Presence floating position could not be reset: {exc}"}
        return {"ok": True, "centered": True}

    def export_session_state(self):
        return self.controller.export_session_state()

    def import_session_state(self, payload):
        return self.controller.import_session_state(payload)

    def shutdown(self):
        controller = getattr(self, "controller", None)
        self.controller = None
        if controller is not None:
            controller.shutdown()
