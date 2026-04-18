from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_audio_story_mode_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Audio Story Mode controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.AudioStoryModeController


class Addon(BaseAddon):
    TAB_ID = "audio_story_mode_runtime"

    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_tab(
            id=self.TAB_ID,
            title="Audio Story Mode",
            area="operational_view",
            order=120,
            tooltip="Import story audio, transcribe it locally, and sync visual replies to playback.",
            factory=self._build_tab,
        )
        context.logger.info("Audio Story Mode addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_tab(self, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Audio Story Mode controller is unavailable.")
        return controller.build_tab()

    def export_session_state(self):
        controller = self._peek_controller()
        if controller is None:
            return {}
        return controller.export_session_state() or {}

    def import_session_state(self, session):
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.import_session_state(session)

    def invoke_capability(self, capability, payload=None):
        controller = self._peek_controller()
        if controller is None:
            return None
        capability_name = str(capability or "").strip().lower()
        if capability_name == "audio_story_mode.load_current_image":
            return controller.load_current_story_image(payload or {})
        if capability_name == "audio_story_mode.refresh_master_style_anchor":
            return controller.refresh_master_style_anchor(payload or {})
        return None

    def shutdown(self):
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.shutdown()
