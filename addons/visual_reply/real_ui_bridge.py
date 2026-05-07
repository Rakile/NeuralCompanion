from addons.visual_reply.controller import AddonVisualReplyPanel as QtVisualReplyPanel
from core.addons.qt_host_services import AddonCapabilityBridgeService


def show_dock(bridge):
    dock = bridge._ui_object("VisualReplyDock")
    if dock is None:
        return
    try:
        dock.show()
        dock.raise_()
    except Exception:
        pass


def build_runtime_panel(bridge):
    """Build the Visual Reply runtime panel owned by the addon."""
    capability_bridge = AddonCapabilityBridgeService(lambda: getattr(bridge.backend, "_addon_manager", None))
    try:
        panel = capability_bridge.invoke(
            "visual_reply.build_runtime_panel",
            {"capability_bridge": capability_bridge},
        )
    except Exception as exc:
        print(f"[UI Real] Visual Reply panel addon capability failed, using fallback panel: {exc}")
        panel = None
    if panel is None:
        try:
            panel = QtVisualReplyPanel(capability_bridge=capability_bridge)
        except TypeError:
            panel = QtVisualReplyPanel()
    panel.setObjectName("visual_reply_panel")
    object_map = (
        ("status_label", "visual_reply_status"),
        ("storage_label", "visual_reply_storage_label"),
        ("prev_button", "visual_reply_previous_button"),
        ("load_button", "visual_reply_load_button"),
        ("next_button", "visual_reply_next_button"),
        ("load_story_button", "visual_reply_load_current_story_button"),
        ("use_style_button", "visual_reply_use_current_style_button"),
        ("caption_button", "visual_reply_caption_button"),
        ("delete_button", "visual_reply_delete_button"),
        ("clear_button", "visual_reply_clear_button"),
        ("delete_all_button", "visual_reply_delete_all_button"),
        ("image_label", "visual_reply_image_label"),
        ("caption_label", "visual_reply_caption_label"),
    )
    for attribute_name, object_name in object_map:
        widget = getattr(panel, attribute_name, None)
        if widget is not None and hasattr(widget, "setObjectName"):
            widget.setObjectName(object_name)
    return panel


def connect_runtime_panel(bridge, panel):
    """Connect addon-owned panel signals to the backend runtime callbacks."""
    try:
        load_signal = getattr(panel, "loadRequested", None)
        if load_signal is not None:
            load_signal.connect(bridge.backend.prompt_visual_reply_image)
    except Exception:
        pass
    try:
        caption_signal = getattr(panel, "captionRequested", None)
        if caption_signal is not None:
            caption_signal.connect(bridge.backend.prompt_visual_reply_caption)
    except Exception:
        pass
    try:
        clear_signal = getattr(panel, "clearRequested", None)
        if clear_signal is not None:
            clear_signal.connect(lambda: bridge.backend.clear_visual_reply(auto_show=False))
    except Exception:
        pass


def build_status_snapshot(backend, runtime_config=None):
    config = dict(runtime_config or {})
    mode = backend._visual_reply_mode_value_from_label(backend._live_combo_text("visual_reply_mode_combo", "Auto"))
    provider = backend._visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    return {
        "visual_reply_mode": mode,
        "visual_reply_provider": provider,
        "visual_reply_size": backend._normalize_visual_reply_size(
            backend._live_combo_text("visual_reply_size_combo", config.get("visual_reply_size", "1024x1024"))
        ),
        "visual_reply_model": backend._live_text(
            "visual_reply_model_edit",
            config.get("visual_reply_model", "gpt-image-1"),
        ).strip() or "gpt-image-1",
        "visual_reply_visible": bool(
            backend._visual_reply_addon_enabled()
            and hasattr(backend, "visual_reply_dock")
            and backend.visual_reply_dock.isVisible()
        ),
    }


def apply_runtime_settings(backend, settings):
    """Apply Visual Reply-owned settings from dry-run/profile payloads."""
    payload = dict(settings or {})
    widget = backend._live_widget_attr("visual_reply_mode_combo")
    if "visual_reply_mode" in payload and widget is not None:
        mode_text = backend._visual_reply_mode_label_from_value(payload["visual_reply_mode"])
        widget.setCurrentText(mode_text)
        backend.on_visual_reply_mode_changed(mode_text)
    widget = backend._live_widget_attr("visual_reply_provider_combo")
    if "visual_reply_provider" in payload and widget is not None:
        provider_text = backend._visual_reply_provider_label_from_value(payload["visual_reply_provider"])
        widget.setCurrentText(provider_text)
        backend.on_visual_reply_provider_changed(provider_text)
    widget = backend._live_widget_attr("visual_reply_size_combo")
    if "visual_reply_size" in payload and widget is not None:
        size_text = backend._normalize_visual_reply_size(payload["visual_reply_size"])
        widget.setCurrentText(backend._visual_reply_size_label_from_value(size_text))
        backend.on_visual_reply_size_changed(size_text)
    widget = backend._live_widget_attr("visual_reply_model_edit")
    if "visual_reply_model" in payload and widget is not None:
        widget.setText(str(payload["visual_reply_model"] or "gpt-image-1"))
        backend.on_visual_reply_model_changed()
    widget = backend._live_widget_attr("visual_reply_auto_show_checkbox")
    if "visual_reply_auto_show_dock" in payload and widget is not None:
        auto_show = bool(payload["visual_reply_auto_show_dock"])
        widget.setChecked(auto_show)
        backend.on_visual_reply_auto_show_changed(auto_show)


def bind_show_button(bridge):
    show_button = bridge._ui_object("btn_visual_reply")
    if show_button is not None and hasattr(show_button, "clicked"):
        show_button.clicked.connect(lambda: show_dock(bridge))


def sync_combo_action(bridge, object_name, callback_name):
    bridge._sync_single_combo_to_backend(object_name)
    callback = getattr(bridge.backend, callback_name, None)
    widget = bridge._ui_object(object_name)
    if callable(callback) and widget is not None and hasattr(widget, "currentText"):
        callback(str(widget.currentText() or ""))
    bridge._refresh_musetalk_visual_runtime_frontend()


def sync_model_action(bridge):
    bridge._sync_single_line_edit_to_backend("visual_reply_model_edit")
    callback = getattr(bridge.backend, "on_visual_reply_model_changed", None)
    if callable(callback):
        callback()
    bridge._refresh_profile_utility_runtime_frontend()


def sync_auto_show_action(bridge):
    bridge._sync_single_checkbox_to_backend("visual_reply_auto_show_checkbox")
    callback = getattr(bridge.backend, "on_visual_reply_auto_show_changed", None)
    widget = bridge._ui_object("visual_reply_auto_show_checkbox")
    if callable(callback) and widget is not None and hasattr(widget, "isChecked"):
        callback(bool(widget.isChecked()))
    bridge._refresh_musetalk_visual_runtime_frontend()


def bind_runtime_controls(bridge):
    """Wire Visual Reply-owned runtime controls from main.ui to Visual Reply callbacks."""
    combo_bindings = {
        "visual_reply_mode_combo": "on_visual_reply_mode_changed",
        "visual_reply_provider_combo": "on_visual_reply_provider_changed",
        "visual_reply_size_combo": "on_visual_reply_size_changed",
    }
    for object_name, callback_name in combo_bindings.items():
        widget = bridge._ui_object(object_name)
        if widget is None or not hasattr(widget, "currentIndexChanged"):
            continue
        widget.currentIndexChanged.connect(
            lambda _index=0, name=object_name, cb=callback_name: sync_combo_action(bridge, name, cb)
        )

    model_edit = bridge._ui_object("visual_reply_model_edit")
    if model_edit is not None and hasattr(model_edit, "editingFinished"):
        model_edit.editingFinished.connect(lambda: sync_model_action(bridge))

    auto_show = bridge._ui_object("visual_reply_auto_show_checkbox")
    if auto_show is not None and hasattr(auto_show, "toggled"):
        auto_show.toggled.connect(lambda _checked=False: sync_auto_show_action(bridge))
