"""Widget-free Chatterbox Multilingual TTS provider addon."""

from __future__ import annotations

from addons.chatterbox_multilingual_tts.process_service import ChatterboxMultilingualProcessService
from core.addons.base import BaseAddon


_DEFAULTS = {
    "chatterbox_multilingual_language": "en",
    "chatterbox_multilingual_seed": 0,
    "chatterbox_multilingual_temperature": 0.8,
    "chatterbox_multilingual_top_p": 1.0,
    "chatterbox_multilingual_exaggeration": 0.5,
    "chatterbox_multilingual_cfg_weight": 0.5,
    "chatterbox_multilingual_min_p": 0.05,
    "chatterbox_multilingual_repeat_penalty": 2.0,
    "chatterbox_multilingual_prewarm_on_start": True,
    "chatterbox_multilingual_use_cloned_voice": True,
    "chatterbox_multilingual_apply_watermark": False,
}


def _snapshot(runtime_config) -> dict:
    runtime = dict(runtime_config or {})
    result = dict(_DEFAULTS)
    result.update({key: runtime[key] for key in result if key in runtime})
    result["chatterbox_multilingual_seed"] = max(0, int(result["chatterbox_multilingual_seed"] or 0))
    result["chatterbox_multilingual_temperature"] = max(0.05, float(result["chatterbox_multilingual_temperature"] or 0.8))
    for key in ("chatterbox_multilingual_top_p", "chatterbox_multilingual_exaggeration",
                "chatterbox_multilingual_cfg_weight", "chatterbox_multilingual_min_p"):
        result[key] = float(_DEFAULTS[key] if result[key] is None or result[key] == "" else result[key])
    result["chatterbox_multilingual_top_p"] = min(1.0, max(0.0, result["chatterbox_multilingual_top_p"]))
    result["chatterbox_multilingual_repeat_penalty"] = max(1.0, float(result["chatterbox_multilingual_repeat_penalty"] or 2.0))
    return result


class Addon(BaseAddon):
    SERVICE_NAME = "chatterbox_multilingual"

    def initialize(self, context):
        super().initialize(context)
        self._runtime_config = context.capabilities.runtime_config
        self.service = ChatterboxMultilingualProcessService(context)
        context.capabilities.speech_providers.register_provider(
            self.SERVICE_NAME,
            self.service,
            metadata={
                "kind": "tts",
                "backend_id": self.SERVICE_NAME,
                "label": "Chatterbox Multilingual",
                "provider": "local",
                "supports_streaming": False,
                "preferred_for_streaming": False,
                "preferred_for_non_streaming": False,
                "supports_voice_reference": True,
                "supported_speech_tags": [
                    "clear throat", "sigh", "shush", "groan", "sniff", "gasp", "chuckle", "laugh",
                ],
                "runtime_overhead_gib": 5.8,
            },
        )
        context.logger.info("Chatterbox Multilingual TTS native provider initialized.")

    def invoke_capability(self, capability, payload=None):
        name, request = str(capability or "").strip(), dict(payload or {})
        values = _snapshot(request.get("runtime_config"))
        if name == "runtime.estimate_overhead_gib":
            return 5.8
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
