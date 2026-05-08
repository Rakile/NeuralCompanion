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
        context.ui.register_manifest_designer_tab(
            id=self.HOST_TAB_ID,
            binder=self._bind_core_tab,
        )
        context.logger.info("Visual Reply addon initialized.")

    def _peek_controller(self):
        return getattr(self, "controller", None)

    def _bind_core_tab(self, widget, context):
        controller = self._peek_controller()
        if controller is None:
            raise RuntimeError("Visual Reply controller is unavailable.")
        return controller.bind_core_tab(widget)

    def _visual_reply_service(self):
        context = getattr(self, "context", None)
        if context is None:
            return None
        try:
            return context.get_service("qt.visual_reply")
        except Exception:
            return None

    def export_session_state(self):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "export_session_state"):
            return service.export_session_state() or {}
        return {}

    def export_preset_state(self):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "export_preset_state"):
            return service.export_preset_state() or {}
        return self.export_session_state()

    def import_session_state(self, session):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "import_session_state"):
            return service.import_session_state(session)
        return None

    def import_preset_state(self, preset):
        service = self._visual_reply_service()
        if service is not None and hasattr(service, "import_preset_state"):
            return service.import_preset_state(preset)
        return self.import_session_state(preset)

    def invoke_capability(self, capability, payload=None):
        capability = str(capability or "").strip()
        payload = dict(payload or {})
        if capability == "runtime.apply_settings":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.apply_runtime_settings(backend, payload.get("settings") or {})
            return None
        if capability == "runtime.status_snapshot":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_status_snapshot(backend, payload.get("runtime_config") or {})
            return None
        if capability == "legacy.build_utility_button":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_legacy_utility_button(backend)
            return None
        if capability == "legacy.build_settings_tab":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_legacy_settings_tab(backend)
            return None
        if capability == "legacy.build_runtime_widgets":
            from addons.visual_reply import real_ui_bridge

            backend = payload.get("backend")
            if backend is not None:
                return real_ui_bridge.build_legacy_runtime_widgets(backend, payload.get("runtime_config") or {})
            return None
        if capability == "real_ui.bind_runtime_controls":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.bind_runtime_controls(bridge)
            return None
        if capability == "real_ui.build_dock":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.build_dock(
                    bridge,
                    theme_provider=payload.get("theme_provider"),
                    runtime_config=payload.get("runtime_config") or {},
                    shared_state_module=payload.get("shared_state_module"),
                    storage_dir=payload.get("storage_dir"),
                )
            return None
        if capability == "real_ui.bind_show_button":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.bind_show_button(bridge)
            return None
        if capability == "real_ui.show_dock":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.show_dock(bridge)
            return None
        if capability == "real_ui.redirect_runtime_surface":
            from addons.visual_reply import real_ui_bridge

            bridge = payload.get("bridge")
            if bridge is not None:
                return real_ui_bridge.redirect_runtime_surface(bridge)
            return None
        if capability.startswith("runtime.backend."):
            from addons.visual_reply.runtime import BackendVisualReplyRuntimeMixin

            backend = payload.get("backend")
            method_name = capability[len("runtime.backend.") :]
            method = getattr(BackendVisualReplyRuntimeMixin, method_name, None)
            if backend is not None and callable(method):
                return method(backend, *list(payload.get("args") or []), **dict(payload.get("kwargs") or {}))
            return None
        if capability == "shell.create_visual_reply_service":
            from addons.visual_reply.shell_service import _UiShellVisualReplyService

            return _UiShellVisualReplyService(payload.get("window"))
        if capability != "visual_reply.build_runtime_panel":
            return None
        controller = self._peek_controller()
        if controller is None:
            return None
        return controller.build_runtime_panel(capability_bridge=payload.get("capability_bridge"))
