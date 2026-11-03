"""Widget-free Chatterbox TTS provider addon."""

from core.addons.base import BaseAddon
from addons.chatterbox_tts.process_service import ChatterboxProcessService


_DEFAULTS = {
    "tts_seed": 0,
    "tts_temperature": 0.8,
    "tts_top_p": 0.9,
    "tts_top_k": 40,
    "tts_repeat_penalty": 1.2,
    "tts_min_p": 0.0,  # Legacy session compatibility; Turbo does not use Min P.
    "tts_normalize_loudness": False,
    "tts_prewarm_on_start": True,
    "tts_use_cloned_voice": True,
    "tts_apply_watermark": False,
}


def _snapshot(runtime_config) -> dict:
    runtime = dict(runtime_config or {})
    result = dict(_DEFAULTS)
    result.update({key: runtime[key] for key in result if key in runtime})
    result["tts_seed"] = max(0, int(result["tts_seed"] or 0))
    result["tts_temperature"] = max(0.05, float(result["tts_temperature"] or 0.8))
    top_p = result["tts_top_p"]
    result["tts_top_p"] = min(1.0, max(0.0, float(0.9 if top_p in (None, "") else top_p)))
    top_k = result["tts_top_k"]
    result["tts_top_k"] = max(0, int(40 if top_k in (None, "") else top_k))
    result["tts_repeat_penalty"] = max(0.0, float(result["tts_repeat_penalty"] or 1.2))
    result["tts_min_p"] = min(1.0, max(0.0, float(result["tts_min_p"] or 0.0)))
    return result


class Addon(BaseAddon):
    SERVICE_NAME = "chatterbox"

    def initialize(self, context):
        super().initialize(context)
        self._runtime_config = context.capabilities.runtime_config
        self.service = ChatterboxProcessService(context)
        context.capabilities.speech_providers.register_provider(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "tts",
                "backend_id": self.SERVICE_NAME,
                "label": "Chatterbox",
                "provider": "local",
                "supports_streaming": False,
                "preferred_for_streaming": False,
                "preferred_for_non_streaming": True,
                "supports_voice_reference": True,
                "supported_speech_tags": [
                    "clear throat",
                    "sigh",
                    "shush",
                    "groan",
                    "sniff",
                    "gasp",
                    "chuckle",
                    "laugh",
                ],
                "runtime_overhead_gib": 5.2,
            },
        )
        context.logger.info("Chatterbox TTS native provider initialized.")

    def invoke_capability(self, capability, payload=None):
        name, request = str(capability or "").strip(), dict(payload or {})
        values = _snapshot(request.get("runtime_config"))
        if name == "runtime.estimate_overhead_gib":
            return 5.2
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
        return None

    def import_preset_state(self, payload):
        del payload
        return None

    def shutdown(self):
        service = getattr(self, "service", None)
        self.service = None
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
        return None
