"""Visual Reply service-extension template for the native-QML shell.

Presentation belongs in a typed native adapter. This template demonstrates a
finite capability surface and intentionally constructs no presentation object.
"""

from __future__ import annotations

from core.addons.base import BaseAddon


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._visual_service = context.get_service("qt.visual_reply")

    def invoke_capability(self, capability, payload=None):
        del payload
        if str(capability or "").strip().lower() != "my_visual_reply.snapshot":
            return None
        snapshot = {}
        if self._visual_service is not None:
            snapshot = dict(self._visual_service.settings_snapshot() or {})
        return {"available": self._visual_service is not None, "settings": snapshot}
