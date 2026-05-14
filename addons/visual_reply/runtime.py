import time
from pathlib import Path

from PySide6 import QtWidgets

from addons.visual_reply import state as visual_reply_state
from addons.visual_reply.providers import (
    default_model_for_provider,
    known_default_models,
    model_override_for_provider,
    normalize_model_for_provider,
    provider_label_from_value,
    provider_setting_from_config,
    updated_provider_settings,
    provider_value_from_label,
)
from core.addons.qt_host_services import QtRuntimeConfigService
from ui.panels.input_dialog import QtInputDialog


def _runtime_config_service(backend):
    return QtRuntimeConfigService(backend)


def _runtime_config(backend):
    return _runtime_config_service(backend).snapshot()


def _update_runtime_config(backend, key, value):
    key = str(key)
    service = _runtime_config_service(backend)
    snapshot = service.snapshot()
    if key in snapshot:
        return service.update(key, value)
    if key.startswith("visual_reply_"):
        engine = service._engine()
        config = getattr(engine, "RUNTIME_CONFIG", None)
        if isinstance(config, dict):
            config[key] = value
    return None


def visual_reply_mode_label_from_value(value):
    return "Off" if str(value or "auto").strip().lower() == "off" else "Auto"


def visual_reply_mode_value_from_label(label):
    return "off" if str(label or "").strip().lower() == "off" else "auto"


def visual_reply_provider_label_from_value(value):
    return provider_label_from_value(value)


def visual_reply_provider_value_from_label(label):
    return provider_value_from_label(label)


def normalize_visual_reply_size(value):
    size = str(value or "1024x1024").strip().lower()
    if size in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
        return size
    return "1024x1024"


def visual_reply_size_label_from_value(value):
    size = normalize_visual_reply_size(value)
    return "Auto" if size == "auto" else size


def visual_reply_size_for_provider(backend, provider):
    provider = str(provider or "openai").strip().lower()
    config = _runtime_config(backend)
    provider_size = str(provider_setting_from_config(config, provider, "size", "") or "").strip()
    if provider_size:
        return normalize_visual_reply_size(provider_size)
    active_provider = str(config.get("visual_reply_provider", "openai") or "openai").strip().lower()
    if active_provider == provider:
        return normalize_visual_reply_size(config.get("visual_reply_size", "1024x1024"))
    return "1024x1024"


def visual_reply_default_model_for_provider(provider):
    return default_model_for_provider(provider)


def visual_reply_known_default_models():
    return known_default_models()


def visual_reply_model_override_for_provider(provider, model):
    return model_override_for_provider(provider, model)


def visual_reply_normalize_model_for_provider(provider, model):
    return normalize_model_for_provider(provider, model)


def visual_reply_model_for_provider(backend, provider):
    provider = str(provider or "openai").strip().lower()
    config = _runtime_config(backend)
    default_model = visual_reply_default_model_for_provider(provider)
    provider_model = str(provider_setting_from_config(config, provider, "model", "") or "").strip()
    if provider_model:
        return visual_reply_normalize_model_for_provider(provider, provider_model)
    active_provider = str(config.get("visual_reply_provider", "openai") or "openai").strip().lower()
    if active_provider == provider:
        return visual_reply_normalize_model_for_provider(provider, config.get("visual_reply_model", default_model))
    return default_model


def visual_reply_api_key_for_provider(backend, provider):
    return str(provider_setting_from_config(_runtime_config(backend), provider, "api_key", "") or "").strip()


def _update_visual_reply_provider_setting(backend, provider, role, value):
    settings = updated_provider_settings(_runtime_config(backend), provider, role, value)
    return _update_runtime_config(backend, "visual_reply_provider_settings", settings)


def sync_visual_reply_api_key_field(backend, provider=None):
    widget = getattr(backend, "visual_reply_api_key_edit", None)
    if widget is None or not hasattr(widget, "setText"):
        return
    if provider is None:
        provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    label = visual_reply_provider_label_from_value(provider)
    previous = False
    try:
        previous = bool(widget.blockSignals(True))
        widget.setText(visual_reply_api_key_for_provider(backend, provider))
        if hasattr(widget, "setPlaceholderText"):
            widget.setPlaceholderText(f"{label} API key (optional; env vars still work)")
        if hasattr(widget, "setToolTip"):
            widget.setToolTip(f"Optional {label} API key saved in the local session for Visual Reply image generation.")
    finally:
        try:
            widget.blockSignals(previous)
        except Exception:
            pass


def sync_visual_reply_model_field(backend, provider=None):
    widget = getattr(backend, "visual_reply_model_edit", None)
    if widget is None or not hasattr(widget, "setText"):
        return
    if provider is None:
        provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    model_name = visual_reply_model_for_provider(backend, provider)
    previous = False
    try:
        previous = bool(widget.blockSignals(True))
        widget.setText(model_name)
    finally:
        try:
            widget.blockSignals(previous)
        except Exception:
            pass


def sync_visual_reply_size_field(backend, provider=None):
    widget = getattr(backend, "visual_reply_size_combo", None)
    if widget is None or not hasattr(widget, "setCurrentText"):
        return
    if provider is None:
        provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    size = visual_reply_size_for_provider(backend, provider)
    previous = False
    try:
        previous = bool(widget.blockSignals(True))
        widget.setCurrentText(visual_reply_size_label_from_value(size))
    finally:
        try:
            widget.blockSignals(previous)
        except Exception:
            pass


def on_visual_reply_api_key_changed(backend):
    provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    api_key = str(backend.visual_reply_api_key_edit.text() if hasattr(backend, "visual_reply_api_key_edit") else "").strip()
    _update_visual_reply_provider_setting(backend, provider, "api_key", api_key)
    refresh_hint = getattr(backend, "_refresh_visual_reply_hint", None)
    if callable(refresh_hint):
        refresh_hint()
    save_session = getattr(backend, "save_session", None)
    if callable(save_session):
        save_session()


def refresh_visual_reply_hint(backend):
    hint = backend._live_widget_attr("visual_reply_hint")
    if hint is None:
        return
    mode = visual_reply_mode_value_from_label(backend._live_combo_text("visual_reply_mode_combo", "Auto"))
    provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    size = normalize_visual_reply_size(backend._live_combo_text("visual_reply_size_combo", visual_reply_size_for_provider(backend, provider)))
    default_model = visual_reply_default_model_for_provider(provider)
    model = backend._live_text("visual_reply_model_edit", visual_reply_model_for_provider(backend, provider)).strip() or default_model
    auto_show = backend._live_checked("visual_reply_auto_show_checkbox", True)
    if mode == "off":
        title = "Visual Reply Runtime - Off"
        summary = "Visual replies are disabled. NC will not ask the LLM for [visualize: ...] tags or generate images automatically."
    else:
        dock_text = "The dock will auto-show when a request starts or finishes." if auto_show else "The dock stays where it is; use Show Visual Reply if you want to watch generation live."
        provider_text = visual_reply_provider_label_from_value(provider)
        title = f"Visual Reply Runtime - {provider_text} / {model}"
        key_text = "A local API key is set for this provider." if visual_reply_api_key_for_provider(backend, provider) else "API key can come from this field or the provider environment variable."
        summary = (
            f"Visual replies are enabled. Automatic image generation still follows the NC auto-visual toggle; when allowed, NC may append one [visualize: ...] tag when an image would help. "
            f"Current backend request: {provider_text}, {size}, model '{model}'. {key_text} {dock_text}"
        )
    hint.setText(summary)
    runtime_box = backend._live_widget_attr("visual_reply_runtime_box")
    if runtime_box is not None and hasattr(runtime_box, "setTitle"):
        try:
            runtime_box.setTitle(title)
            runtime_box.setToolTip(summary)
        except Exception:
            pass


def on_visual_reply_mode_changed(backend, choice):
    mode = visual_reply_mode_value_from_label(choice)
    _update_runtime_config(backend, "visual_reply_mode", mode)
    _update_runtime_config(backend, "visual_replies_enabled", mode != "off")
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_mode", "value": mode})
    backend.save_session()


def on_visual_reply_provider_changed(backend, choice):
    provider = visual_reply_provider_value_from_label(choice)
    old_provider = str(
        getattr(backend, "_visual_reply_active_provider", "")
        or _runtime_config(backend).get("visual_reply_provider", "openai")
        or "openai"
    ).strip().lower()
    current_size = normalize_visual_reply_size(
        backend.visual_reply_size_combo.currentText() if hasattr(backend, "visual_reply_size_combo") else ""
    )
    _update_visual_reply_provider_setting(backend, old_provider, "size", current_size)
    current_model = str(backend.visual_reply_model_edit.text() if hasattr(backend, "visual_reply_model_edit") else "").strip()
    _update_visual_reply_provider_setting(
        backend,
        old_provider,
        "model",
        visual_reply_model_override_for_provider(old_provider, current_model),
    )
    next_size = visual_reply_size_for_provider(backend, provider)
    next_model = visual_reply_model_for_provider(backend, provider)
    _update_runtime_config(backend, "visual_reply_provider", provider)
    _update_runtime_config(backend, "visual_reply_size", next_size)
    _update_runtime_config(backend, "visual_reply_model", next_model)
    setattr(backend, "_visual_reply_active_provider", provider)
    sync_visual_reply_size_field(backend, provider)
    sync_visual_reply_model_field(backend, provider)
    sync_visual_reply_api_key_field(backend, provider)
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_provider", "value": provider})
    backend.save_session()


def on_visual_reply_size_changed(backend, choice):
    provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    size = normalize_visual_reply_size(choice)
    if hasattr(backend, "visual_reply_size_combo"):
        label = visual_reply_size_label_from_value(size)
        if backend.visual_reply_size_combo.currentText() != label:
            backend.visual_reply_size_combo.setCurrentText(label)
    _update_visual_reply_provider_setting(backend, provider, "size", size)
    _update_runtime_config(backend, "visual_reply_size", size)
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_size", "value": size})
    backend.save_session()


def on_visual_reply_model_changed(backend):
    provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    raw_model_name = str(backend.visual_reply_model_edit.text() if hasattr(backend, "visual_reply_model_edit") else "").strip()
    if raw_model_name:
        model_name = visual_reply_normalize_model_for_provider(provider, raw_model_name)
        _update_visual_reply_provider_setting(backend, provider, "model", visual_reply_model_override_for_provider(provider, model_name))
    else:
        model_name = visual_reply_default_model_for_provider(provider)
        _update_visual_reply_provider_setting(backend, provider, "model", "")
    if hasattr(backend, "visual_reply_model_edit") and backend.visual_reply_model_edit.text().strip() != model_name:
        backend.visual_reply_model_edit.setText(model_name)
    _update_runtime_config(backend, "visual_reply_model", model_name)
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_model", "value": model_name})
    backend.save_session()


def on_visual_reply_auto_show_changed(backend, checked):
    enabled = bool(checked)
    _update_runtime_config(backend, "visual_reply_auto_show_dock", enabled)
    refresh_visual_reply_hint(backend)
    backend.emit_tutorial_event("ui_changed", {"field": "visual_reply_auto_show_dock", "value": enabled})
    backend.save_session()


class BackendVisualReplyRuntimeMixin:
    """Host-facing Visual Reply runtime settings and image/caption controls."""

    def _visual_reply_mode_label_from_value(self, value):
        return visual_reply_mode_label_from_value(value)

    def _visual_reply_mode_value_from_label(self, label):
        return visual_reply_mode_value_from_label(label)

    def _visual_reply_provider_label_from_value(self, value):
        return visual_reply_provider_label_from_value(value)

    def _visual_reply_provider_value_from_label(self, label):
        return visual_reply_provider_value_from_label(label)

    def _normalize_visual_reply_size(self, value):
        return normalize_visual_reply_size(value)

    def _visual_reply_size_label_from_value(self, value):
        return visual_reply_size_label_from_value(value)

    def _visual_reply_default_model_for_provider(self, provider):
        return visual_reply_default_model_for_provider(provider)

    def _visual_reply_api_key_for_provider(self, provider):
        return visual_reply_api_key_for_provider(self, provider)

    def _sync_visual_reply_api_key_field(self, provider=None):
        sync_visual_reply_api_key_field(self, provider)

    def _sync_visual_reply_model_field(self, provider=None):
        sync_visual_reply_model_field(self, provider)

    def _sync_visual_reply_size_field(self, provider=None):
        sync_visual_reply_size_field(self, provider)

    def _refresh_visual_reply_hint(self):
        refresh_visual_reply_hint(self)

    def on_visual_reply_mode_changed(self, choice):
        on_visual_reply_mode_changed(self, choice)

    def on_visual_reply_provider_changed(self, choice):
        on_visual_reply_provider_changed(self, choice)

    def on_visual_reply_size_changed(self, choice):
        on_visual_reply_size_changed(self, choice)

    def on_visual_reply_model_changed(self):
        on_visual_reply_model_changed(self)

    def on_visual_reply_api_key_changed(self):
        on_visual_reply_api_key_changed(self)

    def on_visual_reply_auto_show_changed(self, checked):
        on_visual_reply_auto_show_changed(self, checked)

    def show_visual_reply_dock(self):
        if not self._visual_reply_addon_enabled():
            return
        if hasattr(self, "visual_reply_dock"):
            self.visual_reply_dock.show()
            self.visual_reply_dock.raise_()
        if hasattr(self, "visual_reply_panel"):
            self.visual_reply_panel.show()
        print("[QtGUI] Visual Reply dock shown.")

    def clear_visual_reply(self, status_text="Visual Reply idle", detail_text="No visual reply yet.\nWhen NC creates an image, it will appear here.", *, auto_show=False):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        panel.clear_visual_reply(status_text=status_text, detail_text=detail_text)
        visual_reply_state.set_current_visual_reply_data(
            {
                "status": "idle",
                "status_text": str(status_text or "Visual Reply idle"),
                "detail_text": str(detail_text or "No visual reply yet.\nWhen NC creates an image, it will appear here."),
                "image_path": "",
                "caption": "",
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        if auto_show:
            self.show_visual_reply_dock()
        return True

    def set_visual_reply_loading(self, status_text="Visual Reply generating...", detail_text="Preparing image...", *, auto_show=True):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        panel.set_loading_state(status_text=status_text, detail_text=detail_text)
        visual_reply_state.set_current_visual_reply_data(
            {
                "status": "loading",
                "status_text": str(status_text or "Visual Reply generating..."),
                "detail_text": str(detail_text or "Preparing image..."),
                "image_path": "",
                "caption": "",
                "request_id": "",
                "updated_at": time.time(),
            }
        )
        if auto_show:
            self.show_visual_reply_dock()
        return True

    def show_visual_reply_image(self, image_path, caption="", status_text="Visual Reply", *, auto_show=True):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        loaded = bool(panel.show_image(image_path, status_text=status_text, caption=caption))
        if loaded:
            resolved_caption = str(getattr(panel, "current_caption", "") or "").strip()
            visual_reply_state.set_current_visual_reply_data(
                {
                    "status": "ready",
                    "status_text": str(status_text or "Visual Reply"),
                    "detail_text": "",
                    "image_path": str(image_path or ""),
                    "caption": resolved_caption,
                    "request_id": "",
                    "updated_at": time.time(),
                }
            )
        if loaded and auto_show:
            self.show_visual_reply_dock()
        return loaded

    def set_visual_reply_caption(self, caption=""):
        panel = getattr(self, "visual_reply_panel", None)
        if panel is None:
            return False
        updated = bool(panel.set_caption(caption))
        if updated:
            visual_reply_state.update_current_visual_reply_data(caption=str(caption or ""))
        return updated

    def prompt_visual_reply_image(self):
        panel = getattr(self, "visual_reply_panel", None)
        current_image_path = str(getattr(panel, "current_image_path", "") or "").strip()
        start_dir = str(Path(current_image_path).parent) if current_image_path else str(Path.cwd())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load Visual Reply Image",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not path:
            return False
        loaded = self.show_visual_reply_image(path, status_text="Visual Reply", auto_show=True)
        if loaded:
            print(f"[QtGUI] Visual Reply image loaded: {path}")
        return loaded

    def prompt_visual_reply_caption(self):
        panel = getattr(self, "visual_reply_panel", None)
        current = panel.caption_label.text().strip() if panel is not None and hasattr(panel, "caption_label") else ""
        caption = QtInputDialog.get_text("Visual Reply Caption", "Enter Caption:", self, default_text=current)
        if caption is None:
            return False
        self.set_visual_reply_caption(caption)
        print("[QtGUI] Visual Reply caption updated.")
        return True
