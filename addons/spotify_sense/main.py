from __future__ import annotations

from core.addons import BaseAddon


class Addon(BaseAddon):
    TAB_ID = "spotify_sense_tab"

    def initialize(self, context):
        super().initialize(context)
        from addons.spotify_sense.controller import SpotifySenseController

        self.controller = SpotifySenseController(context)
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Spotify Sense",
            factory=self._build_tab,
            area="top_level",
            order=126,
            tooltip="Connect Spotify, control playback safely, and expose optional music awareness tools.",
            icon_path="../../ui_icons/side_tabs/chat_player.png",
            metadata={"runtime_role": "spotify_sense"},
        )
        context.services.register(
            "spotify.sense",
            self.controller,
            metadata={"kind": "music", "provider": "spotify", "safe_defaults": True},
        )
        context.logger.info("[SpotifySense] Spotify Sense addon initialized.")

    def _build_tab(self, _context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Spotify Sense controller is unavailable.")
        return controller.build_tab()

    def invoke_capability(self, capability, payload=None):
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        return controller.invoke_capability(capability, dict(payload or {}))

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        if controller is None:
            return {}
        return controller.export_session_state() or {}

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        if controller is not None:
            return controller.import_session_state(session)
        return None

    def shutdown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            try:
                controller.shutdown()
            except Exception:
                pass
        self.controller = None
        return None
