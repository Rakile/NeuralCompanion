"""Audio Story Mode addon entry point for the native QML application."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from core.addons import BaseAddon


_CAPABILITIES = frozenset(
    {
        "audio_story_mode.load_current_image",
        "audio_story_mode.refresh_master_style_anchor",
        "runtime.audio_story.native_snapshot",
        "runtime.audio_story.native_update_control",
        "runtime.audio_story.native_control_action",
    }
)


def _load_controller_class():
    controller_path = Path(__file__).with_name("native_controller.py")
    module_name = "nc_addon_audio_story_mode_native_controller"
    module = sys.modules.get(module_name)
    if module is not None:
        return module.AudioStoryModeController
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"Could not load Audio Story Mode controller from {controller_path}"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if sys.modules.get(module_name) is module:
            sys.modules.pop(module_name, None)
        raise
    return module.AudioStoryModeController


class _ControllerStoryActions:
    def __init__(self, controller) -> None:
        self._controller = controller

    def load_current_image(self):
        return self._controller.load_current_story_image(
            {"source": "visual_reply"}
        )

    def refresh_master_style_anchor(self):
        return self._controller.refresh_master_style_anchor(
            {"source": "visual_reply"}
        )


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self._controller = controller_cls(context)
        self._story_actions_binding = None
        story_actions = getattr(context.capabilities, "story", None)
        if story_actions is not None:
            try:
                binding = _ControllerStoryActions(self._controller)
                story_actions.bind_story_actions(binding)
                self._story_actions_binding = binding
            except AttributeError:
                pass
        context.logger.info(
            "Audio Story Mode native controller initialized without a Designer tab."
        )

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        if name not in _CAPABILITIES:
            return None
        request = dict(payload or {})
        if name == "runtime.audio_story.native_snapshot":
            return self._controller.native_snapshot()
        if name == "runtime.audio_story.native_update_control":
            return self._controller.native_update_control(
                request.get("control_id"), request.get("value")
            )
        if name == "runtime.audio_story.native_control_action":
            return self._controller.native_control_action(
                request.get("control_id"), request.get("payload")
            )
        source = str(request.get("source") or "visual_reply")
        if name == "audio_story_mode.load_current_image":
            return self._controller.load_current_story_image({"source": source})
        return self._controller.refresh_master_style_anchor({"source": source})

    def export_session_state(self):
        return self._controller.export_session_state() or {}

    def import_session_state(self, payload):
        return self._controller.import_session_state(payload)

    def shutdown(self):
        story_actions = getattr(self.context.capabilities, "story", None)
        binding = getattr(self, "_story_actions_binding", None)
        if story_actions is not None and binding is not None:
            try:
                story_actions.unbind_story_actions(binding)
            except AttributeError:
                pass
        self._story_actions_binding = None
        controller = getattr(self, "_controller", None)
        self._controller = None
        return None if controller is None else controller.shutdown()
