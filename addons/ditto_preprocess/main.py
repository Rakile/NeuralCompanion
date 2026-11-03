"""Preparation facade over Ditto's shared, isolated runtime service."""

from core.addons import BaseAddon


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        from addons.ditto_avatar.service import get_service
        self.controller = get_service(context)

    def invoke_capability(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Ditto preparation service is unavailable.")
        data = dict(payload or {})
        if capability == 'runtime.ditto.creator.snapshot':
            return {**controller.snapshot(), 'creator':controller.creator().snapshot()}
        if capability == 'runtime.ditto.creator.update':
            return controller.creator().update(str(data.get('key') or ''), data.get('value'))
        if capability == 'runtime.ditto.creator.action':
            try:
                return controller.creator().action(str(data.get('action') or ''), data.get('payload'))
            except Exception as error:
                return {'ok':False, 'error':str(error) or type(error).__name__}
        if capability == 'runtime.ditto.subscribe':
            return controller.changes.subscribe(data.get('callback'))
        if capability == "runtime.ditto.snapshot":
            return controller.snapshot()
        if capability == "runtime.ditto.update":
            return controller.update(str(data.get("key") or ""), data.get("value"))
        if capability == "runtime.ditto.action":
            try:
                return controller.action(str(data.get("action") or ""), data.get("payload"))
            except Exception as error:
                return {"ok": False, "error": str(error) or type(error).__name__}
        return None

    def shutdown(self):
        # The runtime addon owns the shared service lifetime. Unloading this UI
        # addon must not terminate a conversation using the same Ditto worker.
        self.controller = None
