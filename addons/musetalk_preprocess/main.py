from __future__ import annotations

import importlib.util
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_musetalk_preprocess_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load MuseTalk preprocess controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MuseTalkPreprocessController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_tab(
            id="musetalk_preprocess_tab",
            title="Preprocess",
            area="musetalk",
            order=100,
            tooltip="First-party MuseTalk preprocessing and debug tools provided through the addon framework.",
            factory=self._build_tab,
        )
        context.events.subscribe("ui.tab_focus_changed", self._on_ui_tab_focus_changed)
        context.events.subscribe("runtime.heavy_task_starting", self._on_runtime_heavy_task_starting)
        context.events.subscribe("app.resources_refreshed", self._on_app_resources_refreshed)
        context.logger.info("MuseTalk Preprocess addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_tab(self, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("MuseTalk preprocess controller is unavailable.")
        return controller.build_tab()

    def _on_ui_tab_focus_changed(self, payload):
        controller = self._peek_controller()
        if controller is None:
            return
        current_path = [str(item or "").strip().lower() for item in list(payload.get("current_path", []) or []) if str(item or "").strip()]
        if current_path[:2] == ["musetalk", "preprocess"]:
            return
        controller._stop_cached_musetalk_tool_bridge()

    def _on_runtime_heavy_task_starting(self, payload):
        controller = self._peek_controller()
        if controller is None:
            return
        controller._stop_cached_musetalk_tool_bridge()

    def _on_app_resources_refreshed(self, payload):
        controller = self._peek_controller()
        if controller is None:
            return
        controller.refresh_musetalk_avatar_list()

    def invoke_capability(self, capability, payload=None):
        controller = self._peek_controller()
        if controller is None:
            return None
        if str(capability or "").strip() == "avatar_preprocess.set_source_path":
            path = str((payload or {}).get("path") or "").strip()
            if not path or not hasattr(controller, "musetalk_source_edit"):
                return None
            resolved_path = str(Path(path).resolve())
            controller.musetalk_source_edit.setText(resolved_path)
            return {"handled": True}
        return None

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

    def shutdown(self):
        controller = self._peek_controller()
        if controller is None:
            return None
        controller._stop_cached_musetalk_tool_bridge()
        return None
