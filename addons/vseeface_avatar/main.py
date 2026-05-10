from __future__ import annotations

from core.addons.base import BaseAddon


PROVIDER_ID = "vseeface"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._avatar_service = context.get_service("qt.avatar_providers")
        if self._avatar_service is None:
            context.logger.warning("VSeeFace avatar addon could not find qt.avatar_providers service.")
            return None

        self._avatar_service.register_provider(
            provider_id=PROVIDER_ID,
            label="VSeeFace",
            description="VSeeFace avatar control through VMC/OSC.",
            order=100,
            factory=self._create_adapter,
            metadata={
                "kind": "avatar",
                "transport": "vmc_osc",
                "runtime_context": True,
                "real_ui_bridge_module": "addons.vseeface_avatar.real_ui_bridge",
            },
        )
        context.ui.register_manifest_designer_tab(
            id="vseeface_avatar_tab",
        )
        context.logger.info("VSeeFace avatar provider addon initialized.")
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
        payload = dict(payload or {})
        if capability == "ui.hand_doctor_dialog_class":
            from addons.vseeface_avatar.hand_doctor_dialog import HandDoctorDialog

            return HandDoctorDialog
        if capability == "runtime.estimate_overhead_gib":
            from addons.vseeface_avatar import real_ui_bridge

            return real_ui_bridge.estimated_runtime_overhead_gib()
        if capability == "real_ui.bind_runtime_controls":
            from addons.vseeface_avatar import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.bind_runtime_controls(
                    bridge,
                    payload.get("pose_specs") or {},
                    value_to_raw=payload.get("value_to_raw"),
                    raw_to_value=payload.get("raw_to_value"),
                    update_label=payload.get("update_label"),
                )
        if capability == "real_ui.set_provider_controls_enabled":
            from addons.vseeface_avatar import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.set_provider_controls_enabled(backend, bool(payload.get("enabled", False)))
        if capability == "runtime.create_adapter":
            return self._create_adapter(runtime_context=payload.get("runtime_context"))
        return None

    def _create_adapter(self, runtime_context=None):
        from addons.vseeface_avatar.adapter import VSeeFaceAdapter

        if runtime_context is None:
            return VSeeFaceAdapter()

        return VSeeFaceAdapter(
            avatar_profile=runtime_context.get("avatar_profile", {}),
            current_body_state=runtime_context.get("current_body_state", {}),
            edit_emotion_getter=runtime_context.get("edit_emotion_getter", lambda: "neutral"),
            force_edit_mode_getter=runtime_context.get("force_edit_mode_getter", lambda: False),
            hand_debug=runtime_context.get("hand_debug", {"active": False}),
            hand_calibration=runtime_context.get("hand_calibration", {}),
        )
