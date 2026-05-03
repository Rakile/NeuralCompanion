from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_chat_session_player_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Chat Session Player controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ChatSessionPlayerController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_designer_tab(
            id="chat_session_player_tab",
            title="Chat Player",
            ui_path="ui/chat_session_player.ui",
            binder=self._bind_designer_tab,
            fallback_factory=self._build_tab,
            area="top_level",
            order=920,
            tooltip="Standalone chat session replay and context loading tools.",
            icon_path="ui/icons/chat_player.png",
        )
        context.logger.info("Chat Session Player addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_tab(self, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Chat Session Player controller is unavailable.")
        return controller.build_tab()

    def _bind_designer_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Chat Session Player controller is unavailable.")
        return controller.bind_designer_tab(widget)
