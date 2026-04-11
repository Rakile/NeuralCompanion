import importlib.util
from pathlib import Path

from core.addons.base import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_visual_reply_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Visual Reply controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.VisualReplyController


class Addon(BaseAddon):
    HOST_TAB_ID = "visuals_host"

    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        self.controller.install_panel()
        context.ui.register_tab(
            id=self.HOST_TAB_ID,
            title="Visuals",
            area="host_settings",
            order=120,
            tooltip="Visual reply runtime settings and future visual addons.",
            metadata={"nested_title": "Core"},
            factory=self._build_core_tab,
        )
        context.logger.info("Visual Reply addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_core_tab(self, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Visual Reply controller is unavailable.")
        return controller.build_core_tab()
