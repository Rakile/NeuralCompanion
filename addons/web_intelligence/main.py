from __future__ import annotations

from core.addons import BaseAddon

from addons.web_intelligence.service import WebIntelligenceService


class Addon(BaseAddon):
    def initialize(self, context) -> None:
        super().initialize(context)
        self.service = WebIntelligenceService(context)
        context.logger.info("Web Intelligence addon initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if name == "chat_context.collect":
            return self.service.collect_chat_context(request)
        if name == "chat.user_text_command":
            return self.service.handle_user_text_command(request)
        if name == "runtime.session.export":
            return self.export_session_state()
        if name == "runtime.session.import":
            self.import_session_state(dict(request.get("state") or {}))
            return {"accepted": True}
        if name == "runtime.web_intelligence.status":
            return self.service.status_snapshot()
        if name == "runtime.web_intelligence.configure":
            return self.service.configure(dict(request.get("settings") or {}))
        if name == "runtime.web_intelligence.action":
            return self.service.run_backend_action(
                str(request.get("action") or ""),
                dict(request.get("payload") or {}),
            )
        return None

    def export_session_state(self):
        return {"web_intelligence": self.service.export_state()}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, payload) -> None:
        state = dict(payload or {}).get("web_intelligence")
        if isinstance(state, dict):
            self.service.import_state(state)

    def import_preset_state(self, payload) -> None:
        self.import_session_state(payload)

    def shutdown(self) -> None:
        service = getattr(self, "service", None)
        self.service = None
        if service is not None:
            service.shutdown()
