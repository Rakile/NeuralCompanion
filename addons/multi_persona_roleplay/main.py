from __future__ import annotations

import time

from core.addons.base import BaseAddon
from core.tts_latency_diagnostics import runtime_diagnostic_fields
from addons.multi_persona_roleplay.native_controller import MultiPersonaRoleplayController


_CAPABILITIES = frozenset(
    {
        "roleplay.assistant_reply", "tts.generation_started", "tts.generation_finished",
        "tts.segment_started", "chat_context.collect", "tts.voice_route",
        "tts.voice_segments", "tts.audio_chunk_ready", "roleplay.play_audio_cues",
        "roleplay.audio_settings", "mprc.remote_state", "mprc.remote_send",
        "mprc.remote_choice", "mprc.remote_play", "mprc.remote_pause",
        "mprc.remote_visual", "mprc.remote_cast", "runtime.mprc.native_snapshot",
        "runtime.mprc.native_update", "runtime.mprc.native_update_control",
        "runtime.mprc.native_action",
        "chat_characters",
    }
)


class _VoiceRouterPort:
    def __init__(self, controller):
        self._controller = controller

    def effective_voice_config(self, payload=None):
        return self._controller.voice_router.effective_voice_config(payload)

    def split_text_by_persona(self, payload=None):
        return self._controller.voice_segments(payload)


class Addon(BaseAddon):
    VOICE_SERVICE_NAME = "nc.multi_persona_roleplay.voice_router"

    def initialize(self, context):
        super().initialize(context)
        recorder = context.capabilities.diagnostics
        started_at = time.perf_counter()
        error_class = ""
        if callable(recorder):
            recorder("mprc_initialize_start", **runtime_diagnostic_fields())
        try:
            self.controller = MultiPersonaRoleplayController(context)
            context.services.register(
                self.VOICE_SERVICE_NAME,
                _VoiceRouterPort(self.controller),
                metadata={
                    "kind": "tts_voice_router",
                    "addon_id": "nc.multi_persona_roleplay",
                    "label": "Multi Persona Roleplay Voice Router",
                },
            )
            context.logger.info("Multi Persona Roleplay native service initialized.")
        except Exception as exc:
            error_class = type(exc).__name__
            raise
        finally:
            if callable(recorder):
                session = getattr(getattr(self, "controller", None), "session", None)
                recorder(
                    "mprc_initialize_end",
                    duration_ms=round((time.perf_counter() - started_at) * 1000.0, 3),
                    roleplay_enabled=bool(getattr(session, "enabled", False)),
                    error_class=error_class,
                    **runtime_diagnostic_fields(),
                )

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        if name not in _CAPABILITIES:
            return None
        request = dict(payload or {})
        controller = self.controller
        handlers = {
            "chat_characters": lambda: controller.chat_characters(request),
            "roleplay.assistant_reply": lambda: controller.assistant_reply(request.get("text")),
            "tts.generation_started": lambda: controller.tts_generation_started(request),
            "tts.generation_finished": lambda: controller.tts_generation_finished(request),
            "tts.segment_started": lambda: controller.tts_segment_started(request.get("persona_id"), request.get("text")),
            "chat_context.collect": lambda: controller.collect_chat_context(request),
            "tts.voice_route": lambda: controller.voice_route(request),
            "tts.voice_segments": lambda: controller.voice_segments(request),
            "tts.audio_chunk_ready": lambda: controller.tts_audio_chunk_ready(request),
            "roleplay.play_audio_cues": lambda: controller.play_audio_cues(request.get("cue_ids") or []),
            "roleplay.audio_settings": controller.audio_settings,
            "mprc.remote_state": controller.remote_state,
            "mprc.remote_send": lambda: controller.remote_send(
                request.get("text") or request.get("message"),
                intent=request.get("intent"), speaker_id=request.get("speaker_id"),
            ),
            "mprc.remote_choice": lambda: controller.remote_choice(
                request.get("choice") or request.get("choice_id") or request.get("text")
            ),
            "mprc.remote_play": controller.remote_play_command,
            "mprc.remote_pause": controller.remote_pause_command,
            "mprc.remote_visual": controller.remote_visual,
            "mprc.remote_cast": lambda: controller.remote_cast(request),
            "runtime.mprc.native_snapshot": controller.native_snapshot,
            "runtime.mprc.native_update": lambda: controller.native_update(request.get("path"), request.get("value")),
            "runtime.mprc.native_update_control": lambda: controller.native_update_control(request.get("control_id"), request.get("value")),
            "runtime.mprc.native_action": lambda: controller.native_action(request.get("action"), request.get("payload")),
        }
        return handlers[name]()

    def remote_state(self):
        return self.controller.remote_state()

    def remote_send(self, text, *, intent="Auto", speaker_id=""):
        return self.controller.remote_send(text, intent=intent, speaker_id=speaker_id)

    def remote_choice(self, choice):
        return self.controller.remote_choice(choice)

    def remote_play(self):
        return self.controller.remote_play_command()

    def remote_pause(self):
        return self.controller.remote_pause_command()

    def remote_visual(self):
        return self.controller.remote_visual()

    def remote_cast(self, payload):
        return self.controller.remote_cast(payload)

    def export_session_state(self):
        return self.controller.export_session_state()

    def import_session_state(self, payload):
        return self.controller.import_session_state(payload)

    def export_preset_state(self):
        return {}

    def import_preset_state(self, payload):
        return None

    def begin_shutdown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.begin_shutdown()

    def shutdown(self):
        try:
            self.context.services.unregister(self.VOICE_SERVICE_NAME)
        except Exception:
            pass
        controller = getattr(self, "controller", None)
        self.controller = None
        if controller is not None:
            controller.shutdown()
