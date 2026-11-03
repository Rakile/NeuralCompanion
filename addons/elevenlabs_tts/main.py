from __future__ import annotations

from pathlib import Path

from core.addons.base import BaseAddon


def _load_service_class():
    import importlib.util

    service_path = Path(__file__).with_name("service.py")
    module_name = "nc_addon_elevenlabs_tts_service"
    spec = importlib.util.spec_from_file_location(module_name, service_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load ElevenLabs TTS service from {service_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ElevenLabsTTSService


class Addon(BaseAddon):
    TAB_ID = "elevenlabs_tts_tab"
    SERVICE_NAME = "elevenlabs_tts"

    def initialize(self, context) -> None:
        super().initialize(context)
        service_cls = _load_service_class()
        self.service = service_cls(context)
        self._service_entry = context.services.register(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "tts",
                "backend_id": self.SERVICE_NAME,
                "label": "ElevenLabs TTS",
                "provider": "elevenlabs",
                "supports_streaming": False,
                "preferred_for_streaming": False,
                "preferred_for_non_streaming": False,
                "supports_voice_reference": False,
                "supported_speech_tags": [],
                "runtime_overhead_gib": 0.05,
            },
        )
        context.logger.info("ElevenLabs TTS native provider initialized.")

    def export_session_state(self):
        service = getattr(self, "service", None)
        return service.export_session_state() if service is not None else {}

    def export_preset_state(self):
        service = getattr(self, "service", None)
        return service.export_preset_state() if service is not None else {}

    def import_session_state(self, session) -> None:
        service = getattr(self, "service", None)
        if service is not None:
            service.import_session_state(session)

    def import_preset_state(self, preset) -> None:
        service = getattr(self, "service", None)
        if service is not None:
            service.import_preset_state(preset)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        request = dict(payload or {})
        if capability == "runtime.estimate_overhead_gib":
            return 0.05
        if capability == "runtime.elevenlabs_tts.snapshot":
            return self.service.snapshot()
        if capability == "runtime.elevenlabs_tts.update":
            return self.service.update_settings(**dict(request.get("changes") or {}))
        if capability == "runtime.elevenlabs_tts.voices":
            return self.service.list_voices(quiet=bool(request.get("quiet", False)))
        if capability == "runtime.elevenlabs_tts.models":
            return self.service.list_models(quiet=bool(request.get("quiet", False)))
        if capability == "runtime.elevenlabs_tts.check_connection":
            return self.service.check_connection()
        return None

    def shutdown(self) -> None:
        service = getattr(self, "service", None)
        if service is not None:
            try:
                service.close()
            except RuntimeError as exc:
                self.context.logger.warning(f"ElevenLabs TTS close failed: {exc}")
        if getattr(self, "_service_entry", None) is not None:
            try:
                self.context.services.unregister(self.SERVICE_NAME)
            except (KeyError, RuntimeError) as exc:
                self.context.logger.warning(
                    f"ElevenLabs TTS service unregister failed: {exc}"
                )
