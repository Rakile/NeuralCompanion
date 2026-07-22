from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_identity_artifacts_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Identity Artifacts controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    previous_module = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        controller_class = module.IdentityArtifactsController
    except Exception:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module
        raise
    return controller_class


class Addon(BaseAddon):
    TAB_ID = "identity_artifacts_tab"

    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_manifest_tab(
            id=self.TAB_ID,
            factory=self._create_tab,
        )
        context.logger.info("Identity Artifacts addon initialized.")

    def _create_tab(self, context):
        controller = getattr(self, "controller", None)
        if controller is None:
            raise RuntimeError("Identity Artifacts controller is unavailable.")
        return controller.create_tab()

    def export_session_state(self):
        controller = getattr(self, "controller", None)
        return controller.export_session_state() if controller is not None else {"identity_relay_ref": ""}

    def import_session_state(self, session):
        controller = getattr(self, "controller", None)
        return controller.import_session_state(session) if controller is not None else None

    def export_preset_state(self):
        controller = getattr(self, "controller", None)
        return controller.export_preset_state() if controller is not None else {"identity_relay_ref": ""}

    def import_preset_state(self, preset):
        controller = getattr(self, "controller", None)
        return controller.import_preset_state(preset) if controller is not None else None

    def shutdown(self):
        controller = getattr(self, "controller", None)
        if controller is not None:
            controller.shutdown()
        self.controller = None
        return super().shutdown()

    def invoke_capability(self, capability, payload=None):
        request = dict(payload or {})
        controller = getattr(self, "controller", None)
        if controller is None:
            return None
        explicit_v2 = request.get("schema_version") == 2
        handlers = {
            "identity_relay.capture_mode": lambda: (
                controller.capture_mode() if explicit_v2 else None
            ),
            "identity_relay.capture_turn": lambda: (
                controller.capture_turn(request)
                if explicit_v2
                else controller.capture_turn_snapshot()
            ),
            "identity_relay.prepare_turn": lambda: (
                controller.prepare_turn(request) if explicit_v2 else None
            ),
            "identity_relay.render_judge_request": lambda: (
                controller.render_judge_request(request) if explicit_v2 else None
            ),
            "identity_relay.finalize_turn": lambda: (
                controller.finalize_turn(request) if explicit_v2 else None
            ),
            "identity_relay.restore_persisted_snapshot": lambda: (
                controller.restore_persisted_snapshot(request) if explicit_v2 else None
            ),
            "identity_relay.chat_session.export": lambda: (
                controller.export_chat_session_state_v2()
                if explicit_v2
                else controller.export_chat_session_state()
            ),
            "identity_relay.chat_session.import": lambda: controller.import_chat_session_state(request),
            "identity_relay.chat_session.reset": lambda: controller.reset_chat_session_state(),
            "chat_context.collect": lambda: controller.collect_chat_context(request),
            "real_ui.sync_widget_names": lambda: controller.real_ui_sync_widget_names(request),
            "real_ui.bind_runtime_controls": lambda: controller.bind_runtime_controls(request),
            "real_ui.mirror_runtime_widgets": lambda: controller.mirror_runtime_widgets(request),
        }
        handler = handlers.get(str(capability or "").strip())
        return handler() if handler else None
