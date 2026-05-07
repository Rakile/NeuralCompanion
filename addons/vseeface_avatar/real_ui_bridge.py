def update_body_pose_slider(bridge, key, raw_value, *, raw_to_value, update_label):
    value = raw_to_value(key, raw_value)
    backend_slider = getattr(bridge.backend, "pose_sliders", {}).get(str(key))
    if backend_slider is not None and hasattr(backend_slider, "set_value"):
        try:
            backend_slider.set_value(value)
        except Exception:
            pass
    callback = getattr(bridge.backend, "update_pose_value", None)
    if callable(callback):
        callback(str(key), value)
    update_label(bridge.window, str(key), value)


def enter_focus(bridge):
    bridge._sync_frontend_to_backend()
    callback = getattr(bridge.backend, "enter_external_avatar_focus", None)
    if callable(callback):
        callback("VSeeFace")


def bind_runtime_controls(bridge, pose_specs, *, value_to_raw, raw_to_value, update_label):
    """Wire VSeeFace-owned body pose and focus controls from main.ui."""
    for key, spec in dict(pose_specs or {}).items():
        slider = bridge._ui_object(str(spec.get("widget") or ""))
        if slider is None or not hasattr(slider, "valueChanged"):
            continue
        try:
            minimum = value_to_raw(key, spec.get("minimum", 0.0))
            maximum = value_to_raw(key, spec.get("maximum", 0.0))
            slider.setRange(minimum, maximum)
            if hasattr(slider, "setSingleStep"):
                scale = int(spec.get("scale", 1) or 1)
                slider.setSingleStep(max(1, scale // 10 if scale > 1 else 1))
            if hasattr(slider, "setToolTip"):
                slider.setToolTip("Runtime-backed VSeeFace body setting. Save a body preset to persist edited pose values.")
        except Exception:
            pass
        slider.valueChanged.connect(
            lambda value, pose_key=key: update_body_pose_slider(
                bridge,
                pose_key,
                value,
                raw_to_value=raw_to_value,
                update_label=update_label,
            )
        )

    focus_button = bridge._ui_object("btn_vseeface_hide_interface")
    if focus_button is not None and hasattr(focus_button, "clicked"):
        focus_button.clicked.connect(lambda _checked=False: bridge._invoke_runtime_callback(lambda: enter_focus(bridge)))
