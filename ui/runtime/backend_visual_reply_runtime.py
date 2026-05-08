"""Host shims for Visual Reply runtime actions.

The Visual Reply addon owns the implementation. This backend mixin keeps the
historical method names stable for signals, hotkeys, and engine callbacks while
routing behavior through addon capabilities once the addon manager is live.
"""


class BackendVisualReplyRuntimeMixin:
    def _invoke_visual_reply_runtime(self, method_name, *args, default=None, **kwargs):
        callback = getattr(self, "_invoke_addon_capability", None)
        if not callable(callback):
            return default
        addon_id_callback = getattr(self, "_addon_id_for_ui_role", None)
        addon_id = (
            addon_id_callback("visual_reply", fallback="")
            if callable(addon_id_callback)
            else ""
        )
        return callback(
            addon_id,
            f"runtime.backend.{method_name}",
            {"backend": self, "args": list(args), "kwargs": dict(kwargs)},
            default=default,
        )

    # These tiny value helpers are used while building the hidden backend before
    # addon capabilities are available, so they intentionally remain local.
    def _visual_reply_mode_label_from_value(self, value):
        return "Off" if str(value or "auto").strip().lower() == "off" else "Auto"

    def _visual_reply_mode_value_from_label(self, label):
        return "off" if str(label or "").strip().lower() == "off" else "auto"

    def _visual_reply_provider_label_from_value(self, value):
        return "xAI / Grok" if str(value or "openai").strip().lower() == "xai" else "OpenAI"

    def _visual_reply_provider_value_from_label(self, label):
        text = str(label or "").strip().lower()
        return "xai" if "grok" in text or "xai" in text else "openai"

    def _normalize_visual_reply_size(self, value):
        size = str(value or "1024x1024").strip().lower()
        if size in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            return size
        return "1024x1024"

    def _visual_reply_size_label_from_value(self, value):
        size = self._normalize_visual_reply_size(value)
        return "Auto" if size == "auto" else size

    def _refresh_visual_reply_hint(self):
        return self._invoke_visual_reply_runtime("_refresh_visual_reply_hint")

    def on_visual_reply_mode_changed(self, choice):
        return self._invoke_visual_reply_runtime("on_visual_reply_mode_changed", choice)

    def on_visual_reply_provider_changed(self, choice):
        return self._invoke_visual_reply_runtime("on_visual_reply_provider_changed", choice)

    def on_visual_reply_size_changed(self, choice):
        return self._invoke_visual_reply_runtime("on_visual_reply_size_changed", choice)

    def on_visual_reply_model_changed(self):
        return self._invoke_visual_reply_runtime("on_visual_reply_model_changed")

    def on_visual_reply_auto_show_changed(self, checked):
        return self._invoke_visual_reply_runtime("on_visual_reply_auto_show_changed", checked)

    def show_visual_reply_dock(self):
        return self._invoke_visual_reply_runtime("show_visual_reply_dock")

    def clear_visual_reply(
        self,
        status_text="Visual Reply idle",
        detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.",
        *,
        auto_show=False,
    ):
        return self._invoke_visual_reply_runtime(
            "clear_visual_reply",
            status_text,
            detail_text,
            auto_show=auto_show,
            default=False,
        )

    def set_visual_reply_loading(
        self,
        status_text="Visual Reply generating...",
        detail_text="Preparing image...",
        *,
        auto_show=True,
    ):
        return self._invoke_visual_reply_runtime(
            "set_visual_reply_loading",
            status_text,
            detail_text,
            auto_show=auto_show,
            default=False,
        )

    def show_visual_reply_image(self, image_path, caption="", status_text="Visual Reply", *, auto_show=True):
        return self._invoke_visual_reply_runtime(
            "show_visual_reply_image",
            image_path,
            caption,
            status_text,
            auto_show=auto_show,
            default=False,
        )

    def set_visual_reply_caption(self, caption=""):
        return self._invoke_visual_reply_runtime("set_visual_reply_caption", caption, default=False)

    def prompt_visual_reply_image(self):
        return self._invoke_visual_reply_runtime("prompt_visual_reply_image", default=False)

    def prompt_visual_reply_caption(self):
        return self._invoke_visual_reply_runtime("prompt_visual_reply_caption", default=False)
