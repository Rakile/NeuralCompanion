from __future__ import annotations

from core.addons.base import BaseAddon


PROVIDER_ID = "musetalk"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._musetalk_ui_service = context.get_service("qt.musetalk_ui")
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
                "real_ui_bridge_module": "addons.musetalk_avatar.real_ui_bridge",
            },
        )
        context.ui.register_manifest_designer_tab(
            id="musetalk_avatar_tab",
        )
        context.logger.info("MuseTalk avatar provider addon initialized.")
        return None

    def export_session_state(self):
        service = getattr(self, "_musetalk_ui_service", None)
        if service is not None and hasattr(service, "export_avatar_runtime_settings"):
            return service.export_avatar_runtime_settings() or {}
        return {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        service = getattr(self, "_musetalk_ui_service", None)
        if service is not None and hasattr(service, "import_avatar_runtime_settings"):
            return service.import_avatar_runtime_settings(session)
        return None

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        payload = dict(payload or {})
        backend = payload.get("backend")
        runtime_config = payload.get("runtime_config")
        from addons.musetalk_avatar import real_ui_bridge

        if capability == "runtime.estimate_overhead_gib" and backend is not None:
            return real_ui_bridge.estimated_runtime_overhead_gib(backend)
        if capability == "runtime.collect_config" and backend is not None:
            return real_ui_bridge.collect_runtime_config(backend, runtime_config)
        if capability == "runtime.update_config_from_widgets" and backend is not None:
            return real_ui_bridge.update_runtime_config_from_widgets(backend, runtime_config)
        if capability == "runtime.status_snapshot" and backend is not None:
            return real_ui_bridge.build_status_snapshot(backend, runtime_config)
        if capability == "runtime.restart_sensitive_widgets" and backend is not None:
            return real_ui_bridge.restart_sensitive_widgets(backend)
        if capability == "runtime.refresh_resource_widgets" and backend is not None:
            return real_ui_bridge.refresh_resource_widgets(backend, runtime_config)
        if capability == "runtime.apply_settings" and backend is not None:
            return real_ui_bridge.apply_runtime_settings(backend, payload.get("settings") or {})
        if capability == "dry_run.performance_apply_keys":
            return real_ui_bridge.performance_profile_apply_keys()
        if capability == "dry_run.performance_summary_keys":
            return real_ui_bridge.performance_summary_setting_keys()
        if capability == "dry_run.performance_label_fragment":
            return real_ui_bridge.performance_profile_label_fragment(payload.get("item") or {})
        if capability == "dry_run.performance_log_fragment":
            return real_ui_bridge.performance_candidate_log_fragment(payload.get("settings") or {})
        if capability == "dry_run.add_performance_override" and backend is not None:
            override = dict(payload.get("override") or {})
            return real_ui_bridge.add_performance_override(backend, override, runtime_config)
        if capability == "tutorial.runtime_state" and backend is not None:
            return real_ui_bridge.build_tutorial_state(backend)
        if capability == "tutorial.apply_safe_defaults" and backend is not None:
            return real_ui_bridge.apply_safe_tutorial_defaults(backend)
        if capability == "ui.apply_vram_mode_change" and backend is not None:
            return real_ui_bridge.apply_vram_mode_change(backend, payload.get("choice"))
        if capability == "ui.apply_loop_fade_change" and backend is not None:
            return real_ui_bridge.apply_loop_fade_change(backend, payload.get("value"))
        if capability == "ui.apply_frame_cache_change" and backend is not None:
            return real_ui_bridge.apply_frame_cache_change(backend, payload.get("checked"))
        if capability == "ui.refresh_avatar_pack_list" and backend is not None:
            return real_ui_bridge.refresh_avatar_pack_list(backend, selected_pack_id=payload.get("selected_pack_id"))
        if capability == "ui.apply_avatar_pack_change" and backend is not None:
            return real_ui_bridge.apply_avatar_pack_change(backend, payload.get("choice"))
        if capability == "ui.chunking_slider_specs":
            return real_ui_bridge.chunking_slider_specs(runtime_config)
        if capability == "legacy.build_utility_buttons" and backend is not None:
            return real_ui_bridge.build_legacy_utility_buttons(backend)
        if capability == "legacy.build_runtime_widgets" and backend is not None:
            return real_ui_bridge.build_legacy_runtime_widgets(backend, runtime_config)
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
            try:
                import engine

                runtime_context = engine._build_avatar_runtime_context()
            except Exception:
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
