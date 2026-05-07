def show_dock(bridge):
    dock = bridge._ui_object("VisualReplyDock")
    if dock is None:
        return
    try:
        dock.show()
        dock.raise_()
    except Exception:
        pass


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
