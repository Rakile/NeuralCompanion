from __future__ import annotations

from core.addons import BaseAddon


class Addon(BaseAddon):
    TAB_ID = "buddy_chat_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.buddy_chat.controller import BuddyChatController

        self.controller = BuddyChatController(context)
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Buddy Chat",
            factory=self._build_tab,
            area="top_level",
            order=127,
            tooltip="Let one or more buddy personas speak naturally in the main chat.",
            icon_path="../../ui_icons/side_tabs/budy_chat.png",
            metadata={"runtime_role": "buddy_chat"},
        )
        context.services.register(
            "buddy.chat",
            self.controller,
            metadata={"kind": "chat", "addon_id": "nc.buddy_chat"},
        )
        context.logger.info("[BuddyChat] Buddy Chat addon initialized.")

    def _build_tab(self, _context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Buddy Chat controller is unavailable.")
        return controller.build_tab()

    def invoke_capability(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        return controller.invoke_capability_threadsafe(str(capability or ""), dict(payload or {}))

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        return controller.export_session_state() if controller is not None else {}

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            return controller.import_session_state(dict(session or {}))
        return None

    def shutdown(self):
        context = getattr(self, "context", None)
        if context is not None:
            try:
                context.services.unregister("buddy.chat")
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
