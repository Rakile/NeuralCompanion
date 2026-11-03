from __future__ import annotations

from core.addons import BaseAddon
from addons.main_chat_remote.native_controller import MainChatRemoteController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = MainChatRemoteController(context)
        context.services.register(
            "main_chat.remote",
            self,
            metadata={"kind": "chat_remote", "transport": "local_bridge"},
        )
        context.logger.info("Main Chat Remote native service initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        request = dict(payload or {})
        controller = self.controller
        handlers = {
            "chat_context.collect": lambda: {"context": controller._story_plans.context()},
            "tts.voice_segments": lambda: controller.phone_tts_voice_segments(request),
            "tts.audio_chunk_ready": lambda: controller.handle_tts_audio_chunk(request),
            "main_chat_remote.status": controller.status_snapshot,
            "runtime.main_chat_remote.chess_mcp": lambda: controller.relay_service.chess_request(request),
            "main_chat_remote.start_bridge": self.start_bridge,
            "main_chat_remote.stop_bridge": self.stop_bridge,
            "runtime.main_chat_remote.snapshot": controller.native_snapshot,
            "runtime.main_chat_remote.presentation": lambda: controller.phone_presentation_snapshot(request),
            "runtime.main_chat_remote.set_bridge_enabled": lambda: controller.native_set_bridge_enabled(
                request.get("enabled")
            ),
            "runtime.main_chat_remote.set_pairing_code": lambda: controller.native_set_pairing_code(
                request.get("value")
            ),
            "runtime.main_chat_remote.apply_internet_settings": lambda: controller.native_apply_internet_settings(
                request.get("settings") or {}
            ),
            "runtime.main_chat_remote.action": lambda: controller.native_action(
                request.get("action"), request.get("payload") or {}
            ),
        }
        handler = handlers.get(name)
        return handler() if handler is not None else None

    def start_bridge(self):
        self.controller.start_bridge()
        return self.controller.status_snapshot()

    def stop_bridge(self):
        self.controller.stop_bridge()
        return self.controller.status_snapshot()

    def status_snapshot(self):
        return self.controller.status_snapshot()

    def phone_native_speech_policy(self, request_id: str) -> dict | None:
        """Optional peer hook; exact ownership lookup only, with no UI or I/O."""
        controller = getattr(self, "controller", None)
        return controller.phone_native_speech_policy(request_id) if controller is not None else None

    def export_session_state(self):
        return self.controller.export_session_state()

    def import_session_state(self, payload):
        return self.controller.import_session_state(payload)

    def begin_shutdown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.begin_shutdown()

    def shutdown(self):
        try:
            self.context.services.unregister("main_chat.remote")
        except Exception:
            pass
        controller = getattr(self, "controller", None)
        self.controller = None
        if controller is not None:
            controller.shutdown()
