from __future__ import annotations

from core.addons import BaseAddon


class Addon(BaseAddon):
    TAB_ID = "main_chat_remote_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.main_chat_remote.controller import MainChatRemoteController

        self.controller = MainChatRemoteController(context)
        context.ui.register_manifest_tab(
            id=self.TAB_ID,
            factory=self._build_tab,
        )
        context.services.register(
            "main_chat.remote",
            self.controller,
            metadata={"kind": "chat_remote", "transport": "local_bridge"},
        )
        context.logger.info("Main Chat Remote addon initialized.")

    def _build_tab(self, _context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Main Chat Remote controller is unavailable.")
        return controller.build_tab()

    def invoke_capability(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        return controller.invoke_capability(capability, dict(payload or {}))

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        if controller is None:
            return {}
        return controller.export_session_state() or {}

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            return controller.import_session_state(session or {})
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
