from __future__ import annotations

from core.addons.base import BaseAddon
from addons.vam_avatar import config as vam_config


PROVIDER_ID = "vam"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._persona_service = context.get_service("qt.persona_avatar")
        self._avatar_service = context.get_service("qt.avatar_providers")
        if self._avatar_service is None:
            context.logger.warning("VaM avatar addon could not find qt.avatar_providers service.")
            return None

        self._avatar_service.register_provider(
            provider_id=PROVIDER_ID,
            label="VaM",
            description="Virt-A-Mate VMC/file bridge avatar provider.",
            order=300,
            factory=self._create_adapter,
            metadata={
                "kind": "avatar",
                "transport": "vam_bridge",
                "runtime_context": True,
            },
        )
        context.ui.register_manifest_designer_tab(
            id="vam_avatar_tab",
        )
        context.logger.info("VaM avatar provider addon initialized.")
        return None

    def export_session_state(self):
        service = getattr(self, "_persona_service", None)
        if service is not None and hasattr(service, "export_vam_settings"):
            return service.export_vam_settings() or {}
        return {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        service = getattr(self, "_persona_service", None)
        if service is not None and hasattr(service, "import_vam_settings"):
            return service.import_vam_settings(session)
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def shutdown(self):
        avatar_service = getattr(self, "_avatar_service", None)
        if avatar_service is not None:
            try:
                avatar_service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        return None

    def _create_adapter(self, runtime_context=None):
        if runtime_context is None:
            # Backward-compatible fallback for older hosts that do not pass the
            # avatar runtime context yet. The engine helper provides the
            # required VaM path and runtime hooks without engine-owned wrappers.
            import engine

            runtime_context = engine._build_avatar_runtime_context()
        from addons.vam_avatar.adapter import VaMAdapter

        return VaMAdapter(
            runtime_config=runtime_context.runtime_config,
            normalize_vam_root=runtime_context.get("normalize_vam_root", vam_config.normalize_root),
            derive_vam_bridge_root=runtime_context.get("derive_vam_bridge_root", vam_config.derive_bridge_root),
            default_vam_root=runtime_context.get("default_vam_root", vam_config.DEFAULT_ROOT),
            default_emotion_preset_map=runtime_context.get("default_vam_emotion_preset_map", vam_config.DEFAULT_EMOTION_PRESET_MAP),
            default_timeline_clip_map=runtime_context.get("default_vam_timeline_clip_map", vam_config.DEFAULT_TIMELINE_CLIP_MAP),
            audio_segment_cls=runtime_context.get("audio_segment_cls"),
            avatar_profile=runtime_context.get("avatar_profile", {}),
            current_body_state=runtime_context.get("current_body_state", {}),
            edit_emotion_getter=runtime_context.get("edit_emotion_getter", lambda: "neutral"),
            force_edit_mode_getter=runtime_context.get("force_edit_mode_getter", lambda: False),
            hand_debug=runtime_context.get("hand_debug", {"active": False}),
            hand_calibration=runtime_context.get("hand_calibration", {}),
        )
