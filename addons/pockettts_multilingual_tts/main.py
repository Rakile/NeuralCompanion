from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons.base import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_pockettts_multilingual_tts_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load PocketTTS Multilingual controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PocketTTSMultilingualController


def _load_service_class():
    service_path = Path(__file__).with_name("service.py")
    module_name = "nc_addon_pockettts_multilingual_tts_service"
    spec = importlib.util.spec_from_file_location(module_name, service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load PocketTTS Multilingual service from {service_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PocketTTSMultilingualService


class Addon(BaseAddon):
    SERVICE_NAME = "pockettts_multilingual"
    TAB_ID = "pockettts_multilingual_tts_tab"

    def initialize(self, context):
        super().initialize(context)
        service_cls = _load_service_class()
        self.service = service_cls(context)
        self.controller = None

        context.services.register(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "tts",
                "backend_id": self.SERVICE_NAME,
                "label": "PocketTTS Multilingual",
                "provider": "local",
                "supports_streaming": True,
                "preferred_for_streaming": False,
                "preferred_for_non_streaming": False,
                "supports_voice_reference": True,
                "runtime_overhead_gib": 2.0,
                "real_ui_bridge_module": "addons.pockettts_multilingual_tts.real_ui_bridge",
            },
        )
        context.ui.register_manifest_designer_tab(id=self.TAB_ID, binder=self._bind_designer_tab)
        context.logger.info("PocketTTS Multilingual addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _bind_designer_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            controller_cls = _load_controller_class()
            controller = controller_cls(context)
            self.controller = controller
        return controller.bind_designer_tab(widget)

    def export_session_state(self):
        controller = self._peek_controller()
        if controller is None:
            return {}
        return controller.export_session_state() or {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.import_session_state(session)

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        payload = dict(payload or {})
        backend = payload.get("backend")
        runtime_config = payload.get("runtime_config")
        from addons.pockettts_multilingual_tts import real_ui_bridge

        if capability == "runtime.estimate_overhead_gib":
            return real_ui_bridge.estimated_runtime_overhead_gib()
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
        return None

    def shutdown(self):
        service = getattr(self, "service", None)
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
        controller = self._peek_controller()
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                pass
        return None
