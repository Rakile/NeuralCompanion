from __future__ import annotations

from core.addons.base import BaseAddon
from core.stt_runtime import LocalWhisperSTTService


class Addon(BaseAddon):
    SERVICE_NAME = "whisper_multilingual"

    def initialize(self, context):
        super().initialize(context)
        self.service = LocalWhisperSTTService(
            context,
            backend_id=self.SERVICE_NAME,
            default_model_size="tiny",
            default_language=None,
            force_language=None,
        )
        context.services.register(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "stt",
                "backend_id": self.SERVICE_NAME,
                "label": "Whisper Multilingual",
                "provider": "local",
                "engine": "faster-whisper",
                "default_model_size": "tiny",
                "default_language": "",
                "language_mode": "multilingual",
            },
        )
        context.logger.info("Whisper Multilingual STT addon initialized.")

    def shutdown(self):
        if getattr(self, "service", None) is not None:
            self.service.close()
        return None
