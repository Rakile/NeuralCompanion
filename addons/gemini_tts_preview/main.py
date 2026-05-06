from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons.base import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_gemini_tts_preview_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Gemini TTS Preview controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GeminiTTSPreviewController


def _load_service_class():
    service_path = Path(__file__).with_name("service.py")
    module_name = "nc_addon_gemini_tts_preview_service"
    spec = importlib.util.spec_from_file_location(module_name, service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Gemini TTS Preview service from {service_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GeminiTTSPreviewService


class Addon(BaseAddon):
    TAB_ID = "gemini_tts_preview_tab"
    SERVICE_NAME = "gemini_tts_preview"

    def initialize(self, context):
        super().initialize(context)
        service_cls = _load_service_class()
        self.service = service_cls(context)
        self.controller = None

        self._service_entry = context.services.register(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "tts",
                "backend_id": self.SERVICE_NAME,
                "label": "Gemini TTS Preview",
                "provider": "gemini",
                "supports_streaming": False,
            },
        )

        context.ui.register_manifest_designer_tab(
            id=self.TAB_ID,
            binder=self._bind_designer_tab,
        )
        context.logger.info("Gemini TTS Preview addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _bind_designer_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            controller_cls = _load_controller_class()
            controller = controller_cls(context, self.service)
            self.controller = controller
        return controller.bind_designer_tab(widget)

    def export_session_state(self):
        if getattr(self, "service", None) is None:
            return {}
        return self.service.export_session_state() or {}

    def export_preset_state(self):
        if getattr(self, "service", None) is None:
            return {}
        return self.service.export_preset_state() or {}

    def import_session_state(self, session):
        service = getattr(self, "service", None)
        if service is None:
            return None
        service.import_session_state(session)
        controller = self._peek_controller()
        if controller is not None:
            return controller.import_session_state(session)
        return None

    def import_preset_state(self, preset):
        service = getattr(self, "service", None)
        if service is None:
            return None
        service.import_preset_state(preset)
        controller = self._peek_controller()
        if controller is not None:
            return controller.import_preset_state(preset)
        return None

    def shutdown(self):
        service = getattr(self, "service", None)
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
        if getattr(self, "_service_entry", None) is not None:
            try:
                self.context.services.unregister(self.SERVICE_NAME)
            except Exception:
                pass
        controller = self._peek_controller()
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                pass
        return None
