import importlib.util
from pathlib import Path

from core.addons import BaseAddon


def _load_controller_class():
    controller_path = Path(__file__).with_name("controller.py")
    module_name = "nc_addon_hotkeys_controller"
    spec = importlib.util.spec_from_file_location(module_name, controller_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Hotkeys controller from {controller_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HotkeysController


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_manifest_designer_tab(
            id="hotkeys_tab",
            binder=self._bind_designer_tab,
        )
        context.logger.info("Hotkeys addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _build_tab(self, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Hotkeys controller is unavailable.")
        return controller.build_tab()

    def _bind_designer_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Hotkeys controller is unavailable.")
        return controller.bind_designer_tab(widget)
