from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons.base import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_pockettts_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load PocketTTS controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PocketTTSController


def _load_service_class():
    service_path = Path(__file__).with_name("service.py")
    module_name = "nc_addon_pockettts_service"
    spec = importlib.util.spec_from_file_location(module_name, service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load PocketTTS service from {service_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PocketTTSService


class Addon(BaseAddon):
    SERVICE_NAME = "pockettts"
    TAB_ID = "pockettts_tab"

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
                "label": "PocketTTS",
                "provider": "local",
                "supports_streaming": True,
                "preferred_for_streaming": True,
                "preferred_for_non_streaming": False,
                "supports_voice_reference": True,
            },
        )
        context.ui.register_manifest_designer_tab(
            id=self.TAB_ID,
            binder=self._bind_designer_tab,
        )
        context.logger.info("PocketTTS addon initialized.")

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
        controller = self._peek_controller()
        if controller is None:
            return {}
        return controller.export_preset_state() or {}

    def import_session_state(self, session):
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.import_session_state(session)

    def import_preset_state(self, preset):
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.import_preset_state(preset)

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
