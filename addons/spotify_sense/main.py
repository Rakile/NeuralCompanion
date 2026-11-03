from __future__ import annotations

from core.addons.base import BaseAddon
from addons.spotify_sense.native_controller import SpotifySenseController


class Addon(BaseAddon):
    """Spotify runtime and sensory service for the native QML surface."""

    def initialize(self, context):
        super().initialize(context)
        self.controller = SpotifySenseController(context)
        context.capabilities.music.register_controller(
            self.controller,
            metadata={"kind": "music", "provider": "spotify", "safe_defaults": True},
        )
        context.logger.info("[SpotifySense] Native Spotify Sense service initialized.")

    def _run(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        return controller.invoke_capability(capability, dict(payload or {}))

    def invoke_capability(self, capability, payload=None):
        return self._run(capability, payload)

    def story_hook(self, payload):
        return self._run("spotify.story_hook", payload)

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        return controller.export_session_state() if controller is not None else {}

    def import_session_state(self, payload):
        controller = getattr(self, "controller", None)
        if controller is not None:
            return controller.import_session_state(payload)
        return None

    def shutdown(self):
        controller = getattr(self, "controller", None)
        self.controller = None
        if controller is not None:
            controller.shutdown()
