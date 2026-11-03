from core.addons import BaseAddon
from addons.chat_session_player.native_controller import NativeChatSessionPlayer


class Addon(BaseAddon):
    """Conversation replay runtime with a typed, widget-free QML contract."""

    def initialize(self, context):
        super().initialize(context)
        self._controller = NativeChatSessionPlayer(context.capabilities)

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        request = dict(payload or {})
        if name == "runtime.chat_replay.snapshot":
            return self._controller.snapshot()
        if name == "runtime.chat_replay.select":
            return self._controller.select(request.get("replay_index"))
        if name == "runtime.chat_replay.set_voice":
            return self._controller.set_role_voice(request.get("role"), request.get("path"))
        if name == "runtime.chat_replay.action":
            return self._controller.action(request.get("action"))
        return None

    def export_session_state(self):
        return self._controller.export_session_state()

    def import_session_state(self, session):
        return self._controller.import_session_state(session)

    def shutdown(self):
        self._controller = None
