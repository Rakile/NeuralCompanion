from __future__ import annotations

from core.addons import BaseAddon


class Addon(BaseAddon):
    TAB_ID = "neural_face_presence_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.ai_presence_mode.controller import NeuralFacePresenceController

        self.controller = NeuralFacePresenceController(context)
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Neural Face",
            factory=self._build_tab,
            area="top_level",
            order=125,
            tooltip="Configure Neural Face Presence topology, lip sync, blink, gaze, glow, and face animation.",
            icon_path="../../ui_icons/side_tabs/persona.png",
            metadata={"runtime_role": "neural_face_presence"},
        )
        context.logger.info("[NeuralFacePresence] Neural Face Presence addon initialized.")

    def _build_tab(self, _context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Neural Face Presence controller is unavailable.")
        return controller.build_tab()

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        return controller.export_session_state() if controller is not None else {}

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            return controller.import_session_state(session)
        return None

    def invoke_capability(self, capability, payload=None):
        capability_name = str(capability or "").strip().lower()
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        if capability_name == "neural_face.show_fullscreen":
            controller._show_neural_face_fullscreen()
            return {"ok": True, "mode": "fullscreen"}
        if capability_name == "neural_face.show_floating":
            controller._show_neural_face_floating()
            return {"ok": True, "mode": "floating"}
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
