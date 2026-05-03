from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons.base import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_chatterbox_tts_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Chatterbox TTS controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ChatterboxTTSController


def _load_service_class():
    service_path = Path(__file__).with_name("service.py")
    module_name = "nc_addon_chatterbox_tts_service"
    spec = importlib.util.spec_from_file_location(module_name, service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Chatterbox TTS service from {service_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ChatterboxTTSService


class Addon(BaseAddon):
    SERVICE_NAME = "chatterbox"
    TAB_ID = "chatterbox_tts_tab"

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
                "label": "Chatterbox",
                "provider": "local",
                "supports_streaming": False,
            },
        )
        context.ui.register_designer_tab(
            id=self.TAB_ID,
            title="Chatterbox",
            ui_path="ui/chatterbox_tts.ui",
            binder=self._bind_designer_tab,
            fallback_factory=self._build_tab,
            area="tts_runtime",
            order=100,
            tooltip="Local Chatterbox TTS settings.",
            metadata={"backend_id": self.SERVICE_NAME},
        )
        context.logger.info("Chatterbox TTS addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_tab(self, context):
        controller = self._peek_controller()
        if controller is None:
            controller_cls = _load_controller_class()
            controller = controller_cls(context)
            self.controller = controller
        return controller.build_tab()

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
