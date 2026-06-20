from __future__ import annotations

from core.addons.base import BaseAddon


PROVIDER_ID = "scenic"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._avatar_service = context.get_service("qt.avatar_providers")
        self._controller = None
        if self._avatar_service is None:
            context.logger.warning("Scenic avatar addon could not find qt.avatar_providers service.")
        else:
            self._avatar_service.register_provider(
                provider_id=PROVIDER_ID,
                label="Scenic",
                description="Simple tag-to-image avatar packs.",
                order=250,
                factory=self._create_adapter,
                metadata={
                    "kind": "avatar",
                    "static_images": True,
                    "runtime_context": True,
                    "real_ui_bridge_module": "addons.scenic_avatar.real_ui_bridge",
                },
            )
        context.ui.register_tab(
            id="scenic_avatar_tab",
            title="Scenic",
            factory=self._create_tab,
            area="top_level",
            order=126,
            icon_path="../../ui_icons/side_tabs/scenic.png",
            tooltip="Create portable Scenic Packs that map emotion tags to still images.",
        )
        context.logger.info("Scenic avatar provider addon initialized.")
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
        if capability == "runtime.create_adapter":
            return self._create_adapter(runtime_context=payload.get("runtime_context"))
        if capability == "runtime.available_pack_emotion_names":
            from addons.scenic_avatar import pack_runtime

            return pack_runtime.available_pack_emotion_names(
                payload.get("runtime_config") or {},
                default_names=payload.get("default_names") or [],
            )
        backend = payload.get("backend")
        runtime_config = payload.get("runtime_config")
        if capability == "real_ui.sync_widget_names":
            return {
                "combo": ["scenic_pack_combo"],
            }
        if capability == "legacy.build_runtime_widgets" and backend is not None:
            from addons.scenic_avatar import real_ui_bridge

            return real_ui_bridge.build_legacy_runtime_widgets(backend, runtime_config)
        if capability == "runtime.collect_config" and backend is not None:
            from addons.scenic_avatar import real_ui_bridge

            return real_ui_bridge.collect_runtime_config(backend, runtime_config)
        if capability == "runtime.update_config_from_widgets" and backend is not None:
            from addons.scenic_avatar import real_ui_bridge

            return real_ui_bridge.update_config_from_widgets(backend, runtime_config)
        if capability == "runtime.refresh_resource_widgets" and backend is not None:
            from addons.scenic_avatar import real_ui_bridge

            return real_ui_bridge.refresh_resource_widgets(backend, runtime_config)
        if capability == "real_ui.set_provider_controls_enabled" and backend is not None:
            from addons.scenic_avatar import real_ui_bridge

            return real_ui_bridge.set_provider_controls_enabled(backend, bool(payload.get("enabled", False)))
        bridge = payload.get("bridge")
        if capability == "real_ui.bind_runtime_controls" and bridge is not None:
            from addons.scenic_avatar import real_ui_bridge

            return real_ui_bridge.bind_runtime_controls(bridge)
        return None

    def _create_adapter(self, runtime_context=None):
        from addons.scenic_avatar.adapter import ScenicAdapter

        return ScenicAdapter(runtime_context=runtime_context)

    def _create_tab(self, addon_context):
        from addons.scenic_avatar.controller import ScenicController

        controller = ScenicController(addon_context)
        self._controller = controller
        return controller.widget()
