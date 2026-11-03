from __future__ import annotations

from core.addons import BaseAddon
from addons.musetalk_preprocess.native_service import (
    MuseTalkPreprocessHeadlessService,
)


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = MuseTalkPreprocessHeadlessService(context)
        context.services.register('musetalk_creator_resources', self.controller,
                                  metadata={'kind': 'runtime_resource'})
        context.events.subscribe("app.resources_refreshed", self._on_resources_refreshed)

    def _on_resources_refreshed(self, _payload):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.action("refresh_avatars")

    def invoke_capability(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("MuseTalk Preprocess native service is unavailable.")
        name = str(capability or "").strip()
        data = dict(payload or {})
        if name == "runtime.musetalk_preprocess.creator_activity":
            return controller.creator_activity_snapshot()
        if name == "runtime.musetalk_preprocess.begin_chat_handoff":
            return controller.begin_chat_handoff()
        if name == "runtime.musetalk_preprocess.prepare_shutdown":
            try:
                controller.prepare_shutdown()
                return {"ok": True}
            except Exception as error:
                return {"ok": False, "error": str(error) or type(error).__name__}
        if name == "runtime.musetalk_preprocess.end_chat_handoff":
            controller.end_chat_handoff(str(data.get("ticket") or ""))
            return {"ok": True}
        if name == "runtime.musetalk_preprocess.native_snapshot":
            return controller.snapshot()
        if name == "runtime.musetalk_preprocess.native_update":
            return controller.update(str(data.get("key") or ""), data.get("value"))
        if name == "runtime.musetalk_preprocess.native_action":
            try:
                return controller.action(
                    str(data.get("action") or ""), data.get("payload")
                )
            except Exception as error:  # noqa: BLE001 - preserve addon action errors across the host boundary.
                return {"ok": False, "error": str(error) or type(error).__name__}
        if name == "avatar_preprocess.set_source_path":
            return controller.action("set_source_path", data.get("path"))
        return None

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        return controller.export_session_state() if controller is not None else {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.import_session_state(session)

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            cleanup_ok = controller.shutdown()
            if cleanup_ok:
                self.controller = None
