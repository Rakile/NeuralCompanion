from __future__ import annotations

from pathlib import Path

from core.addons.base import BaseAddon


def _load_service_class():
    import importlib.util

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

        self._service_entry = context.services.register(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "tts",
                "backend_id": self.SERVICE_NAME,
                "label": "Gemini TTS Preview",
                "provider": "gemini",
                "supports_streaming": False,
                "preferred_for_streaming": False,
                "preferred_for_non_streaming": False,
                "supports_voice_reference": False,
                "supported_speech_tags": [],
                "runtime_overhead_gib": 0.1,
            },
        )

        context.logger.info("Gemini TTS Preview native provider initialized.")

    def export_session_state(self):
        if getattr(self, "service", None) is None:
            return {}
        return self.service.export_session_state() or {}

    def export_preset_state(self):
        return {}

    def import_session_state(self, session):
        service = getattr(self, "service", None)
        if service is None:
            return None
        service.import_session_state(session)
        return None

    def import_preset_state(self, preset):
        return None

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        request = dict(payload or {})
        if capability == "runtime.estimate_overhead_gib":
            return 0.1
        if capability == "runtime.gemini_tts.snapshot":
            return self.service.snapshot()
        if capability == "runtime.gemini_tts.update":
            return self.service.update_settings(**dict(request.get("changes") or {}))
        if capability == "runtime.gemini_tts.models":
            return self.service.list_models(quiet=bool(request.get("quiet", False)))
        if capability == "runtime.gemini_tts.check_connection":
            return self.service.check_connection()
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
        return None
