from __future__ import annotations

from core.addons.base import BaseAddon
from addons.vam_avatar import config as vam_config


PROVIDER_ID = "vam"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._vam_service = context.get_service("qt.vam_avatar") or context.get_service("qt.persona_avatar")
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
                "real_ui_bridge_module": "addons.vam_avatar.real_ui_bridge",
            },
        )
        context.ui.register_manifest_designer_tab(
            id="vam_avatar_tab",
        )
        context.logger.info("VaM avatar provider addon initialized.")
        return None

    def export_session_state(self):
        service = getattr(self, "_vam_service", None)
        if service is not None and hasattr(service, "export_vam_settings"):
            return service.export_vam_settings() or {}
        return {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        service = getattr(self, "_vam_service", None)
        if service is not None and hasattr(service, "import_vam_settings"):
            return service.import_vam_settings(session)
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
                "checkbox": [
                    "vam_vmc_enabled_checkbox",
                    "vam_bridge_enabled_checkbox",
                    "vam_play_audio_in_vam_checkbox",
                    "vam_timeline_auto_resume_checkbox",
                ],
                "spin": ["vam_vmc_port_spin"],
                "line_edit": [
                    "vam_root_edit",
                    "vam_bridge_root_edit",
                    "vam_target_atom_uid_edit",
                    "vam_target_storable_id_edit",
                    "vam_vmc_host_edit",
                ],
            }
        if capability == "runtime.vam_config":
            return {
                "detect_default_root": vam_config.detect_default_root,
                "derive_bridge_root": vam_config.derive_bridge_root,
                "derive_plugin_dir": vam_config.derive_plugin_dir,
                "normalize_root": vam_config.normalize_root,
                "normalize_bridge_root": vam_config.normalize_bridge_root,
                "default_root": vam_config.DEFAULT_ROOT,
                "legacy_bridge_roots": vam_config.LEGACY_BRIDGE_ROOTS,
                "default_bridge_root": vam_config.DEFAULT_BRIDGE_ROOT,
                "default_emotion_preset_map": vam_config.DEFAULT_EMOTION_PRESET_MAP,
                "default_timeline_clip_map": vam_config.DEFAULT_TIMELINE_CLIP_MAP,
            }
        from addons.vam_avatar import real_ui_bridge

        if capability == "runtime.estimate_overhead_gib":
            return real_ui_bridge.estimated_runtime_overhead_gib()
        if capability == "runtime.collect_config" and backend is not None:
            return real_ui_bridge.collect_runtime_config(
                backend,
                runtime_config,
                avatar_mode=str(payload.get("avatar_mode") or ""),
            )
        if capability == "runtime.update_config_from_widgets" and backend is not None:
            return real_ui_bridge.update_runtime_config_from_widgets(
                backend,
                runtime_config,
                avatar_mode=str(payload.get("avatar_mode") or ""),
            )
        if capability == "legacy.build_runtime_widgets" and backend is not None:
            return real_ui_bridge.build_legacy_runtime_widgets(backend, runtime_config)
        if capability == "real_ui.bind_runtime_controls":
            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.bind_runtime_controls(bridge)
        if capability == "real_ui.mirror_runtime_widgets":
            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.mirror_runtime_widgets(
                    bridge,
                    force=bool(payload.get("force", False)),
                )
        if capability == "real_ui.apply_provider_selected_defaults":
            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.apply_provider_selected_defaults(backend, bool(payload.get("active", False)))
        if capability.startswith("runtime.backend."):
            from addons.vam_avatar.runtime import BackendVamRuntimeMixin

            backend = payload.get("backend")
            method_name = capability[len("runtime.backend.") :]
            method = getattr(BackendVamRuntimeMixin, method_name, None)
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
        if runtime_context is None:
            # Backward-compatible fallback for older hosts that do not pass the
            # avatar runtime context yet.
            from core.avatar_runtime import AvatarRuntimeContext

            runtime_context = AvatarRuntimeContext(runtime_config={})
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
