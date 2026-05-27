from __future__ import annotations

from core.addons.base import BaseAddon


class Addon(BaseAddon):
    TAB_ID = "multi_persona_roleplay_tab"
    VOICE_SERVICE_NAME = "nc.multi_persona_roleplay.voice_router"

    def initialize(self, context):
        super().initialize(context)
        from addons.multi_persona_roleplay.controller import MultiPersonaRoleplayController

        self.controller = MultiPersonaRoleplayController(context)
        context.services.register(
            self.VOICE_SERVICE_NAME,
            self.controller.voice_router,
            metadata={
                "kind": "tts_voice_router",
                "addon_id": "nc.multi_persona_roleplay",
                "label": "Multi Persona Roleplay Voice Router",
            },
        )
        context.ui.register_manifest_designer_tab(
            id=self.TAB_ID,
            binder=self._bind_designer_tab,
        )
        context.logger.info("Multi Persona Roleplay addon initialized.")

    def _bind_designer_tab(self, widget, context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Multi Persona Roleplay controller is unavailable.")
        return controller.bind_designer_tab(widget)

    def invoke_capability(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        return controller.invoke_capability_threadsafe(str(capability or ""), dict(payload or {}))

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        if controller is None:
            return {}
        return controller.export_session_state()

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            return controller.import_session_state(session)
        return None

    def export_preset_state(self):
        return {}

    def import_preset_state(self, preset):
        return None

    def shutdown(self):
        context = getattr(self, "context", None)
        if context is not None:
            try:
                context.services.unregister(self.VOICE_SERVICE_NAME)
            except Exception:
                pass
        controller = getattr(self, "controller", None)
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                pass
        self.controller = None
        return None
