"""Widget-free PocketTTS Multilingual provider addon."""

from __future__ import annotations

from addons.pockettts_multilingual_tts.service import PocketTTSMultilingualService
from core.addons.base import BaseAddon
from core.pocket_tts_voices import normalize_pocket_tts_builtin_voice


_DEFAULTS = {
    "pocket_tts_multilingual_language": "en",
    "pocket_tts_python": "",
    "pocket_tts_multilingual_temperature": 0.7,
    "pocket_tts_multilingual_lsd_decode_steps": 1,
    "pocket_tts_multilingual_eos_threshold": -4.0,
    "pocket_tts_multilingual_frames_after_eos": 0,
    "pocket_tts_multilingual_builtin_voice": "auto",
    "pocket_tts_multilingual_use_cloned_voice": True,
    "pocket_tts_multilingual_prewarm_on_start": True,
}


def _snapshot(runtime_config) -> dict:
    runtime = dict(runtime_config or {})
    result = dict(_DEFAULTS)
    result.update({key: runtime[key] for key in result if key in runtime})
    language = str(result["pocket_tts_multilingual_language"] or "en").strip().lower()
    result["pocket_tts_multilingual_language"] = language if language in {"en", "fr", "de", "es", "pt", "it"} else "en"
    result["pocket_tts_python"] = str(result["pocket_tts_python"] or "").strip()
    result["pocket_tts_multilingual_temperature"] = max(0.05, float(result["pocket_tts_multilingual_temperature"] or 0.7))
    result["pocket_tts_multilingual_lsd_decode_steps"] = max(1, int(result["pocket_tts_multilingual_lsd_decode_steps"] or 1))
    result["pocket_tts_multilingual_eos_threshold"] = float(result["pocket_tts_multilingual_eos_threshold"] or -4.0)
    result["pocket_tts_multilingual_frames_after_eos"] = max(0, int(result["pocket_tts_multilingual_frames_after_eos"] or 0))
    result["pocket_tts_multilingual_builtin_voice"] = normalize_pocket_tts_builtin_voice(result["pocket_tts_multilingual_builtin_voice"])
    return result


class Addon(BaseAddon):
    SERVICE_NAME = "pockettts_multilingual"

    def initialize(self, context):
        super().initialize(context)
        self._runtime_config = context.capabilities.runtime_config
        self.service = PocketTTSMultilingualService(context)
        context.capabilities.speech_providers.register_provider(
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
                "supported_speech_tags": [],
                "runtime_overhead_gib": 2.0,
            },
        )
        context.logger.info("PocketTTS Multilingual native provider initialized.")

    def invoke_capability(self, capability, payload=None):
        name, request = str(capability or "").strip(), dict(payload or {})
        values = _snapshot(request.get("runtime_config"))
        if name == "runtime.estimate_overhead_gib":
            return 2.0
        if name in {"runtime.collect_config", "runtime.status_snapshot", "runtime.refresh_resource_widgets"}:
            return values
        if name == "runtime.update_config_from_widgets":
            service = getattr(self, "_runtime_config", None)
            if service is not None:
                for key, value in values.items():
                    service.update(key, value)
            return values
        if name == "runtime.restart_sensitive_widgets":
            return []
        return None

    def export_session_state(self):
        return {}

    def export_preset_state(self):
        return {}

    def import_session_state(self, payload):
        del payload

    def import_preset_state(self, payload):
        del payload

    def shutdown(self):
        service = getattr(self, "service", None)
        self.service = None
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
