from __future__ import annotations

from core.addons.base import BaseAddon
from core.stt_runtime import NoSTTService


class Addon(BaseAddon):
    SERVICE_NAME = "none"

    def initialize(self, context):
        super().initialize(context)
        self.service = NoSTTService()
        context.services.register(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "stt",
                "backend_id": self.SERVICE_NAME,
                "label": "None",
                "provider": "disabled",
                "default_model_size": "tiny.en",
                "default_language": "en",
                "language_mode": "disabled",
            },
        )
        context.logger.info("No STT addon initialized.")

    def shutdown(self):
        if getattr(self, "service", None) is not None:
            self.service.close()
        return None
