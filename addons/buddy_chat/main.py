from __future__ import annotations

from collections.abc import Mapping

from core.addons import BaseAddon
from addons.buddy_chat.native_controller import BuddyChatController


_CAPABILITIES = frozenset(
    {
        "chat_context.collect",
        "chat.user_text_command",
        "buddy_chat.contextual_reply",
        "buddy_chat.assistant_reply",
        "tts.voice_segments",
        "tts.voice_segments.requires_full_text",
        "tts.voice_warmup_paths",
        "buddy_chat.status",
        "runtime.buddy.native_snapshot",
        "runtime.buddy.native_update",
        "runtime.buddy.native_action",
    }
)


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self.controller = BuddyChatController(context)
        context.services.register(
            "buddy.chat",
            self,
            metadata={"kind": "chat", "addon_id": "nc.buddy_chat"},
        )
        context.logger.info("[BuddyChat] Native Buddy Chat service initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip()
        if name not in _CAPABILITIES:
            return None
        request = dict(payload or {})
        if name == "tts.voice_segments":
            source = request.get("source_meta")
            request_id = str(source.get("remote_capture_id") or "") if isinstance(source, Mapping) else ""
            if request_id:
                try:
                    peer = self.context.services.get("main_chat.remote")
                    policy = getattr(peer, "phone_native_speech_policy", None)
                    result = policy(request_id) if callable(policy) else None
                except Exception:
                    result = None
                if isinstance(result, dict) and result.get("suppress_original") is True:
                    return {"segments": [], "suppress_original": True}
        controller = self.controller
        handlers = {
            "chat_context.collect": lambda: controller.collect_chat_context(request),
            "chat.user_text_command": lambda: controller.handle_user_text_command(request),
            "buddy_chat.contextual_reply": lambda: controller.contextual_reply(request),
            "buddy_chat.assistant_reply": lambda: controller.record_assistant_reply(request),
            "tts.voice_segments": lambda: controller.voice_segments(request),
            "tts.voice_segments.requires_full_text": lambda: controller.voice_segments_requires_full_text(request),
            "tts.voice_warmup_paths": controller.voice_warmup_paths,
            "buddy_chat.status": self.status_snapshot,
            "runtime.buddy.native_snapshot": controller.native_snapshot,
            "runtime.buddy.native_update": lambda: controller.native_update_setting(
                str(request.get("key") or ""), request.get("value")
            ),
            "runtime.buddy.native_action": lambda: controller.native_action(
                str(request.get("action") or ""), dict(request.get("payload") or {})
            ),
        }
        return handlers[name]()

    def status_snapshot(self):
        return {**self.controller.status_snapshot(), "phone_native_audio_handoff": True}

    def invoke_capability_threadsafe(self, capability, payload=None):
        return self.invoke_capability(capability, payload)

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
            self.context.services.unregister("buddy.chat")
        except Exception:
            pass
        controller = getattr(self, "controller", None)
        self.controller = None
        if controller is not None:
            controller.shutdown()
