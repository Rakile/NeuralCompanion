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
                "runtime_context": True,
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

    def _create_adapter(self, runtime_context=None):
        from addons.musetalk_avatar.adapter import MuseTalkAdapter

        if runtime_context is None:
            # Backward-compatible fallback for older hosts that do not pass the
            # avatar runtime context yet.
            return MuseTalkAdapter()
        return MuseTalkAdapter(
            runtime_config=runtime_context.runtime_config,
            invalidate_available_emotion_names_fn=runtime_context.get("invalidate_available_emotion_names_fn"),
            shared_state_module=runtime_context.get("shared_state_module"),
            log_memory_checkpoint_fn=runtime_context.get("log_memory_checkpoint_fn"),
            stop_flag_event=runtime_context.get("stop_flag_event"),
            stop_playback_event=runtime_context.get("stop_playback_event"),
            dry_run_module=runtime_context.get("dry_run_module"),
        )
