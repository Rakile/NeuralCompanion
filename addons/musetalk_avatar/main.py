from __future__ import annotations

from core.addons.base import BaseAddon


PROVIDER_ID = "musetalk"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._avatar_service = context.get_service("qt.avatar_providers")
        if self._avatar_service is None:
            context.logger.warning("MuseTalk avatar addon could not find qt.avatar_providers service.")
            return None

        self._avatar_service.register_provider(
            provider_id=PROVIDER_ID,
            label="MuseTalk",
            description="MuseTalk avatar rendering and preview pipeline.",
            order=200,
            factory=self._create_adapter,
            metadata={
                "kind": "avatar",
                "transport": "musetalk_worker",
                "legacy_engine_adapter": True,
            },
        )
        context.logger.info("MuseTalk avatar provider addon initialized.")
        return None

    def shutdown(self):
        avatar_service = getattr(self, "_avatar_service", None)
        if avatar_service is not None:
            try:
                avatar_service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        return None

    def _create_adapter(self):
        # The host wrapper keeps isinstance checks stable while MuseTalk helper
        # contracts are gradually moved out of engine.py.
        import engine

        return engine.MuseTalkAdapter()
