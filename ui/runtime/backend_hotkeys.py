"""Host shims for the Hotkeys addon runtime."""


class BackendHotkeyMixin:
    def _invoke_hotkeys_runtime(self, method_name, *args, default=None, **kwargs):
        callback = getattr(self, "_invoke_addon_capability", None)
        if not callable(callback):
            return default
        return callback(
            "nc.hotkeys",
            f"runtime.backend.{method_name}",
            {"backend": self, "args": list(args), "kwargs": dict(kwargs)},
            default=default,
        )

    def _build_ui_hotkey_timer(self):
        return self._invoke_hotkeys_runtime("_build_ui_hotkey_timer")

    def _hotkey_button_titles(self):
        return self._invoke_hotkeys_runtime("_hotkey_button_titles", default={})

    def _supported_ui_hotkey_actions(self):
        return self._invoke_hotkeys_runtime("_supported_ui_hotkey_actions", default={})

    def _dispatch_hotkey_action(self, action):
        return self._invoke_hotkeys_runtime("_dispatch_hotkey_action", action)

    def _refresh_hotkey_shortcuts(self):
        return self._invoke_hotkeys_runtime("_refresh_hotkey_shortcuts")

    def _poll_exact_ui_hotkeys(self):
        return self._invoke_hotkeys_runtime("_poll_exact_ui_hotkeys")

    def _refresh_hotkey_labels(self):
        return self._invoke_hotkeys_runtime("_refresh_hotkey_labels")

    def hotkey_catalog(self):
        return self._invoke_hotkeys_runtime("hotkey_catalog", default=[])

    def set_hotkey_binding(self, action, binding):
        return self._invoke_hotkeys_runtime("set_hotkey_binding", action, binding)

    def reset_hotkey_bindings(self):
        return self._invoke_hotkeys_runtime("reset_hotkey_bindings", default={})
