"""Host shims for MuseTalk focus/preview runtime actions."""


class BackendMuseTalkPreviewRuntimeMixin:
    def _invoke_musetalk_focus_runtime(self, method_name, *args, default=None, **kwargs):
        callback = getattr(self, "_invoke_addon_service_capability", None)
        if not callable(callback):
            return default
        return callback(
            "avatar_provider_registry",
            f"runtime.backend.{method_name}",
            {"backend": self, "args": list(args), "kwargs": dict(kwargs)},
            default=default,
            provider_id="musetalk",
        )

    def open_hand_debugger(self):
        return self._invoke_musetalk_focus_runtime("open_hand_debugger")

    def show_musetalk_preview(self):
        return self._invoke_musetalk_focus_runtime("show_musetalk_preview")

    def enter_musetalk_avatar_focus(self):
        return self._invoke_musetalk_focus_runtime("enter_musetalk_avatar_focus")

    def exit_musetalk_avatar_focus(self, *, raise_main=False):
        return self._invoke_musetalk_focus_runtime("exit_musetalk_avatar_focus", raise_main=raise_main)

    def toggle_musetalk_avatar_focus(self):
        return self._invoke_musetalk_focus_runtime("toggle_musetalk_avatar_focus")

    def show_main_interface_from_musetalk_focus(self):
        return self._invoke_musetalk_focus_runtime("show_main_interface_from_musetalk_focus")

    def stop_musetalk_preview(self):
        return self._invoke_musetalk_focus_runtime("stop_musetalk_preview")
