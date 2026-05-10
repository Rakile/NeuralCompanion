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
        if capability == "runtime.create_adapter":
            return self._create_adapter(runtime_context=payload.get("runtime_context"))
        if capability == "real_ui.sync_widget_names":
            return {
                "combo": ["musetalk_vram_combo", "musetalk_avatar_pack_combo"],
                "checkbox": ["musetalk_use_frame_cache_checkbox"],
                "spin": ["musetalk_loop_fade_spin"],
            }
        if capability == "runtime.discover_avatar_packs":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.discover_packs(**dict(payload.get("kwargs") or {}))
        if capability == "runtime.get_avatar_pack":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.get_pack(**dict(payload.get("kwargs") or {}))
        if capability == "runtime.normalize_enabled_pack_emotions":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.normalize_enabled_pack_emotions(payload.get("value"))
        if capability == "runtime.enabled_pack_emotions":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.enabled_pack_emotions(
                payload.get("runtime_config") or {},
                payload.get("pack_id"),
            )
        if capability == "runtime.vram_mode":
            from addons.musetalk_avatar import text_policy

            return text_policy.vram_mode(
                payload.get("runtime_config") or {},
                default=str(payload.get("default") or "quality"),
            )
        if capability == "runtime.chunk_limits_for_index":
            from addons.musetalk_avatar import text_policy

            return text_policy.chunk_limits_for_index(
                int(payload.get("chunk_index", 0) or 0),
                payload.get("runtime_config") or {},
                payload.get("defaults") or {},
            )
        if capability == "runtime.preview.stream_frames":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state
            from core import runtime_files

            return preview_runtime.stream_musetalk_preview_frames(
                payload.get("playback_state") or {},
                payload.get("stop_event"),
                runtime_config=payload.get("runtime_config") or {},
                list_png_frames=runtime_files.list_png_frames,
                musetalk_state_module=musetalk_state,
            )
        if capability == "runtime.preview.stream_delegated_audio_progress":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state

            return preview_runtime.stream_delegated_audio_progress(
                payload.get("playback_state") or {},
                payload.get("stop_event"),
                musetalk_state_module=musetalk_state,
            )
        if capability == "runtime.preview.prime_frame":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state
            from core import runtime_files

            return preview_runtime.prime_musetalk_preview_frame(
                payload.get("playback_state") or {},
                runtime_config=payload.get("runtime_config") or {},
                list_png_frames=runtime_files.list_png_frames,
                musetalk_state_module=musetalk_state,
            )
        if capability == "runtime.preview.estimate_displayed_frames":
            from addons.musetalk_avatar import preview_runtime

            return preview_runtime.estimate_displayed_musetalk_frames(
                payload.get("state") or {},
                payload.get("now"),
                runtime_config=payload.get("runtime_config") or {},
            )
        if capability == "runtime.preview.current_source_index":
            from addons.musetalk_avatar import preview_runtime, state as musetalk_state

            return preview_runtime.get_current_musetalk_source_index(
                payload.get("state"),
                runtime_config=payload.get("runtime_config") or {},
                musetalk_state_module=musetalk_state,
                advance_to_next_frame=bool(payload.get("advance_to_next_frame", False)),
                now=payload.get("now"),
            )
        if capability == "runtime.preview.current_state":
            from addons.musetalk_avatar import state as musetalk_state

            return dict(getattr(musetalk_state, "current_musetalk_frame_data", {}) or {})
        if capability == "runtime.preview.set_state":
            from addons.musetalk_avatar import state as musetalk_state

            musetalk_state.set_current_musetalk_frame_data(dict(payload.get("state") or {}))
            return True
        if capability == "runtime.pipeline_snapshot":
            from addons.musetalk_avatar import state as musetalk_state

            return musetalk_state.get_musetalk_pipeline_snapshot()
        if capability == "runtime.preview.append_log":
            from addons.musetalk_avatar import state as musetalk_state

            musetalk_state.append_musetalk_preview_log(str(payload.get("message") or ""))
            return True
        if capability == "runtime.available_pack_emotion_names":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.available_pack_emotion_names(
                payload.get("runtime_config") or {},
                default_names=set(payload.get("default_names") or []),
                avatar_profile=payload.get("avatar_profile") or {},
                legacy_map=payload.get("legacy_map") or {},
                legacy_transitions=payload.get("legacy_transitions") or {},
                avatars_dir=payload.get("avatars_dir"),
            )
        if capability == "runtime.pack_catalog":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.pack_catalog(
                payload.get("runtime_config") or {},
                legacy_map=payload.get("legacy_map") or {},
                legacy_transitions=payload.get("legacy_transitions") or {},
            )
        if capability == "runtime.select_pack":
            from addons.musetalk_avatar import pack_runtime

            return pack_runtime.select_pack(
                payload.get("runtime_config") or {},
                payload.get("requested_pack_id"),
                legacy_map=payload.get("legacy_map") or {},
                legacy_transitions=payload.get("legacy_transitions") or {},
            )
        if capability == "ui.preview_panel_exports":
            from addons.musetalk_avatar import preview_panel

            return {
                "QT_MUSETALK_LOOP_FADE_MS": preview_panel.QT_MUSETALK_LOOP_FADE_MS,
                "QT_PREVIEW_AHEAD_PRELOAD": preview_panel.QT_PREVIEW_AHEAD_PRELOAD,
                "QT_PREVIEW_CACHE_LIMIT": preview_panel.QT_PREVIEW_CACHE_LIMIT,
                "QT_PREVIEW_INITIAL_PRELOAD": preview_panel.QT_PREVIEW_INITIAL_PRELOAD,
                "QtMuseTalkPreviewPanel": preview_panel.QtMuseTalkPreviewPanel,
            }
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
        bridge = payload.get("bridge")
        if bridge is not None:
            if capability == "real_ui.build_preview_dock":
                return real_ui_bridge.build_preview_dock(
                    bridge,
                    theme_provider=payload.get("theme_provider"),
                    runtime_config=payload.get("runtime_config") or {},
                )
            if capability == "real_ui.ensure_stage_window":
                return real_ui_bridge.ensure_stage_window(bridge)
            if capability == "real_ui.attach_preview_to_host":
                return real_ui_bridge.attach_preview_to_host(bridge, payload.get("host"))
            if capability == "real_ui.sync_stage_window_geometry_from_preview":
                return real_ui_bridge.sync_stage_window_geometry_from_preview(bridge)
            if capability == "real_ui.set_provider_controls_enabled":
                return real_ui_bridge.set_provider_controls_enabled(bridge, bool(payload.get("enabled", False)))
            if capability == "real_ui.bind_runtime_controls":
                return real_ui_bridge.bind_runtime_controls(bridge)
            if capability == "real_ui.bind_preview_controls":
                return real_ui_bridge.bind_preview_controls(bridge)
            if capability == "real_ui.redirect_preview_runtime_surface":
                return real_ui_bridge.redirect_preview_runtime_surface(bridge)
            if capability == "real_ui.set_focus_button_text":
                return real_ui_bridge.set_focus_button_text(bridge, payload.get("text"))
            if capability == "real_ui.show_preview":
                return real_ui_bridge.show_preview(bridge)
            if capability == "real_ui.enter_avatar_focus":
                return real_ui_bridge.enter_avatar_focus(bridge)
            if capability == "real_ui.exit_avatar_focus":
                return real_ui_bridge.exit_avatar_focus(bridge, raise_main=bool(payload.get("raise_main", False)))
            if capability == "real_ui.toggle_avatar_focus":
                return real_ui_bridge.toggle_avatar_focus(bridge)
            if capability == "real_ui.show_main_interface_from_focus":
                return real_ui_bridge.show_main_interface_from_focus(bridge)
            if capability == "real_ui.stop_preview":
                return real_ui_bridge.stop_preview(bridge)
        if capability.startswith("runtime.backend."):
            from addons.musetalk_avatar.focus_runtime import BackendMuseTalkPreviewRuntimeMixin

            backend = payload.get("backend")
            method_name = capability[len("runtime.backend.") :]
            method = getattr(BackendMuseTalkPreviewRuntimeMixin, method_name, None)
            if backend is not None and callable(method):
                return method(backend, *list(payload.get("args") or []), **dict(payload.get("kwargs") or {}))
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
            from core.avatar_runtime import AvatarRuntimeContext

            runtime_context = AvatarRuntimeContext(runtime_config={})
        return MuseTalkAdapter(
            runtime_config=runtime_context.runtime_config,
            invalidate_available_emotion_names_fn=runtime_context.get("invalidate_available_emotion_names_fn"),
            musetalk_state_module=runtime_context.get("avatar_preview_state_module", runtime_context.get("musetalk_state_module")),
            log_memory_checkpoint_fn=runtime_context.get("log_memory_checkpoint_fn"),
            stop_flag_event=runtime_context.get("stop_flag_event"),
            stop_playback_event=runtime_context.get("stop_playback_event"),
            dry_run_module=runtime_context.get("dry_run_module"),
        )
