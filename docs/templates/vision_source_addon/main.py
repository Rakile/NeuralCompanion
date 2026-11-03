"""Headless Vision source template for the native-QML NeuralCompanion shell."""

from __future__ import annotations

import time

from core.addons.base import BaseAddon


PROVIDER_ID = "my_source"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.enabled = True
        self.latest_text = ""
        self._sensory_service = context.get_service("qt.sensory")
        if self._sensory_service is not None:
            self._sensory_service.register_provider(
                provider_id=PROVIDER_ID,
                label="My Source",
                instruction="Optional hidden sensory context from My Source.",
                order=150,
                capture_handler=self._capture_sensory_snapshot,
                metadata={"kind": "text"},
            )

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if name == "my_source.snapshot":
            return self.export_session_state()
        if name == "my_source.update":
            key = str(request.get("key") or "").strip()
            if key == "enabled":
                self.enabled = bool(request.get("value"))
            elif key == "latest_text":
                self.latest_text = str(request.get("value") or "").strip()
            else:
                raise KeyError(key)
            return self.export_session_state()
        return None

    def shutdown(self):
        if self._sensory_service is not None:
            self._sensory_service.unregister_provider(PROVIDER_ID)

    def export_session_state(self):
        return {
            "my_source_enabled": bool(self.enabled),
            "my_source_latest_text": str(self.latest_text or ""),
        }

    export_preset_state = export_session_state

    def import_session_state(self, session):
        payload = dict(session or {})
        self.enabled = bool(payload.get("my_source_enabled", self.enabled))
        self.latest_text = str(payload.get("my_source_latest_text", self.latest_text) or "")

    import_preset_state = import_session_state

    def _capture_sensory_snapshot(self, capture_context=None):
        del capture_context
        text = str(self.latest_text or "").strip()
        if not self.enabled or not text:
            return None
        return {"captured_at": time.time(), "source": PROVIDER_ID, "content_text": text}
