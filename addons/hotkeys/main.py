import importlib.util
from pathlib import Path

from core.addons import BaseAddon
from addons.hotkeys import actions


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
        runtime_config = context.get_service("qt.runtime_config")
        registrar = getattr(runtime_config, "engine_attr", lambda *_args, **_kwargs: None)("register_ui_hotkey_actions", None)
        if callable(registrar):
            registrar(actions.UI_ACTION_HOTKEYS, actions.UI_ACTION_LABELS)
        controller_cls = _load_controller_class()
        self.controller = controller_cls(context)
        context.ui.register_manifest_designer_tab(
            id="hotkeys_tab",
            binder=self._bind_designer_tab,
        )
        context.logger.info("Hotkeys addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _bind_designer_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Hotkeys controller is unavailable.")
        return controller.bind_designer_tab(widget)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip().lower()
        payload = dict(payload or {})
        if capability.startswith("runtime.backend."):
            from addons.hotkeys.runtime import BackendHotkeyMixin

            backend = payload.get("backend")
            method_name = capability[len("runtime.backend.") :]
            method = getattr(BackendHotkeyMixin, method_name, None)
            if backend is not None and callable(method):
                return method(backend, *list(payload.get("args") or []), **dict(payload.get("kwargs") or {}))
        if capability == "shell.create_hotkey_service":
            from addons.hotkeys.shell_service import _UiShellHotkeyService

            return _UiShellHotkeyService()
        return None
