"""Widget-free Scenic avatar provider."""

from core.addons.base import BaseAddon
from core.avatar_runtime_context import ScenicAdapterInputs

from addons.scenic_avatar import pack_runtime
from addons.scenic_avatar.adapter import ScenicAdapter


PROVIDER_ID = "scenic"


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._active_adapter = None
        self._runtime_config = context.capabilities.runtime_config
        self._host_operations = context.capabilities.scenic_avatar_host
        self._avatar_service = context.capabilities.avatar
        if self._avatar_service is None:
            context.logger.warning("Scenic avatar provider registry is unavailable.")
            return
        self._avatar_service.register_provider(
            provider_id=PROVIDER_ID,
            label="Scenic",
            description="Simple tag-to-image avatar packs.",
            order=250,
            factory=self._create_adapter,
            construction_input_type=ScenicAdapterInputs,
            metadata={
                "kind": "avatar",
                "static_images": True,
                "runtime_context": False,
                "native_qml": True,
            },
        )
        context.logger.info("Scenic avatar native provider initialized.")

    def _create_adapter(self, construction_input):
        self._active_adapter = ScenicAdapter(construction_input)
        return self._active_adapter

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        runtime_config = dict(request.get("runtime_config") or {})
        if name == "runtime.preview.current_state":
            adapter = getattr(self, "_active_adapter", None)
            return adapter.preview_snapshot() if adapter is not None else {}
        if name == "runtime.create_adapter":
            return self._create_adapter(request.get("construction_input"))
        if name == "runtime.available_pack_emotion_names":
            return pack_runtime.available_pack_emotion_names(
                runtime_config,
                default_names=list(request.get("default_names") or []),
            )
        if name == "runtime.collect_config":
            return self._host_operations.collect_runtime_config(runtime_config)
        if name == "runtime.refresh_resources":
            return self._host_operations.refresh_resource_widgets(runtime_config)
        if name == "runtime.discover_packs":
            return pack_runtime.pack_catalog()
        return None

    def export_session_state(self):
        if self._runtime_config is None:
            return {}
        return {
            "scenic_pack_id": str(self._runtime_config.get("scenic_pack_id", "") or "")
        }

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, payload):
        if self._runtime_config is None:
            return
        state = dict(payload or {})
        if "scenic_pack_id" in state:
            self._runtime_config.update("scenic_pack_id", str(state["scenic_pack_id"] or ""))

    def import_preset_state(self, payload):
        self.import_session_state(payload)

    def shutdown(self):
        adapter = getattr(self, "_active_adapter", None)
        if adapter is not None:
            adapter.stop()
        self._active_adapter = None
        service = getattr(self, "_avatar_service", None)
        if service is not None:
            try:
                service.unregister_provider(PROVIDER_ID)
            except Exception:
                pass
        self._avatar_service = None
