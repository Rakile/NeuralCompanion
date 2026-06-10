from __future__ import annotations

from core.addons import BaseAddon


class Addon(BaseAddon):
    TAB_ID = "ai_presence_mode_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.ai_presence_mode.controller import AIPresenceModeController

        self.controller = AIPresenceModeController(context)
        context.ui.register_tab(
            id=self.TAB_ID,
            title="AI Presence",
            factory=self._build_tab,
            area="top_level",
            order=124,
            tooltip="Configure AI Presence fullscreen, floating window, visual styles, transparency, and audio sync.",
            icon_path="../../ui_icons/side_tabs/visuals.png",
            metadata={"runtime_role": "ai_presence"},
        )
        context.logger.info("[AIPresence] AI Presence Mode addon initialized.")

    def _build_tab(self, _context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("AI Presence Mode controller is unavailable.")
        return controller.build_tab()

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        return controller.export_session_state() if controller is not None else {}

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.import_session_state(session)
        orb = getattr(self, "orb_controller", None)
        if orb is not None:
            return orb.import_session_state(session)
        return None

    def invoke_capability(self, capability, payload=None):
        capability_name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if capability_name == "ai_presence.set_mood":
            mood = str(request.get("mood") or request.get("value") or "neutral").strip() or "neutral"
            try:
                from visual_presence import runtime as visual_presence_runtime

                visual_presence_runtime.set_presence_mood(mood)
            except Exception as exc:
                return {"ok": False, "error": f"AI Presence mood could not be set: {exc}"}
            return {"ok": True, "mood": mood}
        if capability_name == "ai_presence.reset_floating_position":
            try:
                from visual_presence import runtime as visual_presence_runtime

                visual_presence_runtime.reset_ai_presence_floating_position()
            except Exception as exc:
                return {"ok": False, "error": f"AI Presence floating position could not be reset: {exc}"}
            return {"ok": True, "centered": True}
        return None

    def shutdown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                pass
        self.controller = None
        return None
