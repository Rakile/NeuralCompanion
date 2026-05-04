def _runtime_config():
    import engine

    return getattr(engine, "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from engine import update_runtime_config

    return update_runtime_config(key, value)


class BackendVisualReplyRuntimeMixin:
    """Visual Reply runtime settings and hint text."""

    def _visual_reply_mode_label_from_value(self, value):
        return "Off" if str(value or "auto").strip().lower() == "off" else "Auto"

    def _visual_reply_mode_value_from_label(self, label):
        return "off" if str(label or "").strip().lower() == "off" else "auto"

    def _visual_reply_provider_label_from_value(self, value):
        return "xAI / Grok" if str(value or "openai").strip().lower() == "xai" else "OpenAI"

    def _visual_reply_provider_value_from_label(self, label):
        return "xai" if "grok" in str(label or "").strip().lower() or "xai" in str(label or "").strip().lower() else "openai"

    def _normalize_visual_reply_size(self, value):
        size = str(value or "1024x1024").strip().lower()
        if size in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            return size
        return "1024x1024"

    def _visual_reply_size_label_from_value(self, value):
        size = self._normalize_visual_reply_size(value)
        return "Auto" if size == "auto" else size

    def _refresh_visual_reply_hint(self):
        hint = self._live_widget_attr("visual_reply_hint")
        if hint is None:
            return
        mode = self._visual_reply_mode_value_from_label(self._live_combo_text("visual_reply_mode_combo", "Auto"))
        provider = self._visual_reply_provider_value_from_label(self._live_combo_text("visual_reply_provider_combo", "OpenAI"))
        size = self._normalize_visual_reply_size(self._live_combo_text("visual_reply_size_combo", "1024x1024"))
        model = self._live_text("visual_reply_model_edit", _runtime_config().get("visual_reply_model", "gpt-image-1")).strip() or "gpt-image-1"
        auto_show = self._live_checked("visual_reply_auto_show_checkbox", True)
        if mode == "off":
            summary = "Visual replies are disabled. NC will not ask the LLM for [visualize: ...] tags or generate images automatically."
        else:
            dock_text = "The dock will auto-show when a request starts or finishes." if auto_show else "The dock stays where it is; use Show Visual Reply if you want to watch generation live."
            provider_text = "xAI / Grok" if provider == "xai" else "OpenAI"
            summary = (
                f"Visual replies are enabled. Automatic image generation still follows the NC auto-visual toggle; when allowed, NC may append one [visualize: ...] tag when an image would help. "
                f"Current backend request: {provider_text}, {size}, model '{model}'. {dock_text}"
            )
        hint.setText(summary)

    def on_visual_reply_mode_changed(self, choice):
        mode = self._visual_reply_mode_value_from_label(choice)
        _update_runtime_config("visual_reply_mode", mode)
        _update_runtime_config("visual_replies_enabled", mode != "off")
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_mode", "value": mode})
        self.save_session()

    def on_visual_reply_provider_changed(self, choice):
        provider = self._visual_reply_provider_value_from_label(choice)
        _update_runtime_config("visual_reply_provider", provider)
        current_model = str(self.visual_reply_model_edit.text() if hasattr(self, "visual_reply_model_edit") else "").strip()
        if provider == "xai":
            if not current_model or current_model == "gpt-image-1":
                self.visual_reply_model_edit.setText("grok-imagine-image")
                _update_runtime_config("visual_reply_model", "grok-imagine-image")
        else:
            if not current_model or current_model == "grok-imagine-image":
                self.visual_reply_model_edit.setText("gpt-image-1")
                _update_runtime_config("visual_reply_model", "gpt-image-1")
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_provider", "value": provider})
        self.save_session()

    def on_visual_reply_size_changed(self, choice):
        size = self._normalize_visual_reply_size(choice)
        if hasattr(self, "visual_reply_size_combo"):
            label = self._visual_reply_size_label_from_value(size)
            if self.visual_reply_size_combo.currentText() != label:
                self.visual_reply_size_combo.setCurrentText(label)
        _update_runtime_config("visual_reply_size", size)
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_size", "value": size})
        self.save_session()

    def on_visual_reply_model_changed(self):
        model_name = str(self.visual_reply_model_edit.text() if hasattr(self, "visual_reply_model_edit") else "").strip() or "gpt-image-1"
        if hasattr(self, "visual_reply_model_edit") and self.visual_reply_model_edit.text().strip() != model_name:
            self.visual_reply_model_edit.setText(model_name)
        _update_runtime_config("visual_reply_model", model_name)
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_model", "value": model_name})
        self.save_session()

    def on_visual_reply_auto_show_changed(self, checked):
        enabled = bool(checked)
        _update_runtime_config("visual_reply_auto_show_dock", enabled)
        self._refresh_visual_reply_hint()
        self.emit_tutorial_event("ui_changed", {"field": "visual_reply_auto_show_dock", "value": enabled})
        self.save_session()
