from __future__ import annotations

from core.addons.base import BaseAddon


PROVIDER_ID = "none"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._avatar_service = context.get_service("qt.avatar_providers")
        if self._avatar_service is None:
            context.logger.warning("No Avatar addon could not find qt.avatar_providers service.")
            return None

        self._avatar_service.register_provider(
            provider_id=PROVIDER_ID,
            label="None",
            description="Audio-only mode with no external avatar engine.",
            order=900,
            factory=self._create_adapter,
            metadata={"kind": "avatar", "audio_only": True},
        )
        context.logger.info("No Avatar provider addon initialized.")
        return None

    def shutdown(self):
        avatar_service = getattr(self, "_avatar_service", None)
        if avatar_service is not None:
            try:
                avatar_service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        return None

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        if capability == "runtime.estimate_overhead_gib":
            return 0.0
        return None

    def _create_adapter(self):
        return None
