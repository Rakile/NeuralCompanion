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
        context.ui.register_manifest_designer_tab(
            id="chat_session_player_tab",
            binder=self._bind_designer_tab,
        )
        context.logger.info("Chat Session Player addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _bind_designer_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Chat Session Player controller is unavailable.")
        return controller.bind_designer_tab(widget)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip().lower()
        payload = dict(payload or {})
        if capability == "real_ui.add_replay_context_menu_action":
            from addons.chat_session_player import real_ui_bridge

            return real_ui_bridge.add_replay_context_menu_action(
                payload.get("bridge"),
                payload.get("menu"),
                payload.get("chat_edit"),
                payload.get("point"),
            )
        if capability == "backend.add_replay_context_menu_action":
            from addons.chat_session_player import real_ui_bridge

            return real_ui_bridge.add_replay_context_menu_action_for_backend(
                payload.get("backend"),
                payload.get("menu"),
                payload.get("chat_edit"),
                payload.get("point"),
            )
        return None
