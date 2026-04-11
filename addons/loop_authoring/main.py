from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_loop_authoring_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Loop Authoring controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LoopAuthoringController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_tab(
            id="loop_authoring_tab",
            title="Loop Authoring",
            area="musetalk",
            order=200,
            tooltip="First-party Loop Authoring tab provided through the addon framework.",
            factory=self._build_tab,
        )
        context.events.subscribe("app.resources_refreshed", self._on_app_resources_refreshed)
        context.logger.info("Loop Authoring addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_tab(self, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Loop Authoring controller is unavailable.")
        return controller.build_tab()

    def _on_app_resources_refreshed(self, payload):
        controller = self._peek_controller()
        if controller is None:
            return
        controller._refresh_loop_authoring_recommendation()
        if hasattr(controller, "loop_author_prompt_edit") and not controller.loop_author_prompt_edit.toPlainText().strip():
            controller.apply_loop_authoring_template()

    def export_session_state(self):
        controller = self._peek_controller()
        if controller is None:
            return {}
        return controller.export_session_state() or {}

    def export_preset_state(self):
        return self.export_session_state()

    def import_session_state(self, session):
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.import_session_state(session)

    def import_preset_state(self, preset):
        return self.import_session_state(preset)
