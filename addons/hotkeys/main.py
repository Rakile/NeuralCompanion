"""Widget-free Hotkeys addon entry point."""

from core.addons.base import BaseAddon
from addons.hotkeys import actions


class Addon(BaseAddon):
    def initialize(self, context):
        super().initialize(context)
        self._hotkeys = context.capabilities.hotkeys
        if self._hotkeys is None:
            raise RuntimeError("Hotkey host capability is unavailable.")
        self._hotkeys.register_actions(
            actions.UI_ACTION_HOTKEYS,
            actions.UI_ACTION_LABELS,
        )
        context.logger.info("Hotkeys native service initialized.")

    def invoke_capability(self, capability, payload=None):
        name = str(capability or "").strip().lower()
        args = list(dict(payload or {}).get("args") or [])
        service = self._hotkeys
        if name == "shell.create_hotkey_service":
            from addons.hotkeys.shell_service import _UiShellHotkeyService

            return _UiShellHotkeyService()
        if name == "runtime.backend._build_ui_hotkey_timer":
            return service.build_ui_hotkey_timer()
        if name == "runtime.backend._hotkey_button_titles":
            return service.button_titles()
        if name == "runtime.backend._supported_ui_hotkey_actions":
            return service.supported_actions()
        if name == "runtime.backend._dispatch_hotkey_action" and args:
            return service.dispatch_action(args[0])
        if name == "runtime.backend._refresh_hotkey_shortcuts":
            return service.refresh_shortcuts()
        if name == "runtime.backend._poll_exact_ui_hotkeys":
            return service.poll_exact()
        if name == "runtime.backend._refresh_hotkey_labels":
            return service.refresh_labels()
        if name == "runtime.backend.hotkey_catalog":
            return service.list_bindings()
        if name == "runtime.backend.set_hotkey_binding" and len(args) >= 2:
            return service.set_binding(args[0], args[1])
        if name == "runtime.backend.reset_hotkey_bindings":
            return service.reset_defaults()
        return None

    def shutdown(self):
        self._hotkeys = None
        return None
