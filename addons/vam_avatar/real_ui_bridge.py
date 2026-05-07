def sync_checkbox_action(bridge, object_name, callback_name):
    bridge._sync_single_checkbox_to_backend(object_name)
    callback = getattr(bridge.backend, callback_name, None)
    widget = bridge._ui_object(object_name)
    if callable(callback) and widget is not None and hasattr(widget, "isChecked"):
        callback(bool(widget.isChecked()))
    bridge._refresh_avatar_body_vam_runtime_frontend()


def sync_spin_action(bridge, object_name, callback_name):
    bridge._sync_single_spin_to_backend(object_name)
    callback = getattr(bridge.backend, callback_name, None)
    widget = bridge._ui_object(object_name)
    if callable(callback) and widget is not None and hasattr(widget, "value"):
        callback(int(widget.value()))
    bridge._refresh_avatar_body_vam_runtime_frontend()


def sync_line_action(bridge, object_name, callback_name):
    bridge._sync_single_line_edit_to_backend(object_name)
    callback = getattr(bridge.backend, callback_name, None)
    if callable(callback):
        callback()
    bridge._refresh_avatar_body_vam_runtime_frontend()


def start_desktop(bridge):
    bridge._sync_frontend_to_backend()
    callback = getattr(bridge.backend, "on_start_vam_desktop_clicked", None)
    if callable(callback):
        callback()


def start_vr(bridge):
    bridge._sync_frontend_to_backend()
    callback = getattr(bridge.backend, "on_start_vam_vr_clicked", None)
    if callable(callback):
        callback()


def enter_focus(bridge):
    bridge._sync_frontend_to_backend()
    callback = getattr(bridge.backend, "enter_external_avatar_focus", None)
    if callable(callback):
        callback("VaM")


def bind_runtime_controls(bridge):
    """Wire VaM-owned controls from main.ui to VaM backend callbacks."""
    checkbox_bindings = (
        ("vam_vmc_enabled_checkbox", "on_vam_vmc_enabled_changed"),
        ("vam_bridge_enabled_checkbox", "on_vam_bridge_enabled_changed"),
        ("vam_play_audio_in_vam_checkbox", "on_vam_play_audio_in_vam_changed"),
        ("vam_timeline_auto_resume_checkbox", "on_vam_timeline_auto_resume_changed"),
    )
    for object_name, callback_name in checkbox_bindings:
        widget = bridge._ui_object(object_name)
        if widget is None or not hasattr(widget, "toggled"):
            continue
        widget.toggled.connect(
            lambda _checked=False, name=object_name, cb=callback_name: sync_checkbox_action(bridge, name, cb)
        )

    port_spin = bridge._ui_object("vam_vmc_port_spin")
    if port_spin is not None and hasattr(port_spin, "valueChanged"):
        port_spin.valueChanged.connect(
            lambda _value=0: sync_spin_action(bridge, "vam_vmc_port_spin", "on_vam_vmc_port_changed")
        )

    edit_bindings = (
        ("vam_root_edit", "on_vam_root_changed"),
        ("vam_target_atom_uid_edit", "on_vam_target_atom_uid_changed"),
        ("vam_target_storable_id_edit", "on_vam_target_storable_id_changed"),
        ("vam_vmc_host_edit", "on_vam_vmc_host_changed"),
    )
    for object_name, callback_name in edit_bindings:
        widget = bridge._ui_object(object_name)
        if widget is None or not hasattr(widget, "editingFinished"):
            continue
        widget.editingFinished.connect(
            lambda name=object_name, cb=callback_name: sync_line_action(bridge, name, cb)
        )

    button_bindings = {
        "btn_start_vam_desktop": start_desktop,
        "btn_start_vam_vr": start_vr,
        "btn_vam_hide_interface": enter_focus,
    }
    for object_name, callback in button_bindings.items():
        button = bridge._ui_object(object_name)
        if button is None or not hasattr(button, "clicked"):
            continue
        button.clicked.connect(lambda _checked=False, cb=callback: bridge._invoke_runtime_callback(lambda: cb(bridge)))
