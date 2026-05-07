try:
    from PySide6 import QtCore
except Exception:  # pragma: no cover - shell smoke may inspect without Qt available.
    QtCore = None


VRAM_MODE_LABELS = {
    "quality": "Quality",
    "balanced": "Balanced",
    "low_vram": "Low VRAM",
    "very_low_vram": "Very Low VRAM",
}
VRAM_MODE_OVERHEAD_GIB = {
    "Quality": 5.8,
    "Balanced": 4.0,
    "Low VRAM": 2.3,
    "Very Low VRAM": 1.5,
}
DEFAULT_LOOP_FADE_MS = 180


def vram_key_from_label(label):
    text = str(label or "").strip()
    for key, value in VRAM_MODE_LABELS.items():
        if text == value:
            return key
    return "quality"


def vram_label_from_key(value):
    return VRAM_MODE_LABELS.get(str(value or "").strip().lower(), "Quality")


def estimated_runtime_overhead_gib(backend):
    label = backend._live_combo_text("musetalk_vram_combo", "Very Low VRAM").strip() or "Very Low VRAM"
    return float(VRAM_MODE_OVERHEAD_GIB.get(label, 6.5))


def collect_runtime_config(backend, runtime_config=None):
    """Collect MuseTalk-owned runtime config from the current backend widgets."""
    runtime = dict(runtime_config or {})
    return {
        "musetalk_avatar_pack_id": str(
            backend._live_combo_data("musetalk_avatar_pack_combo", runtime.get("musetalk_avatar_pack_id", "")) or ""
        ),
        "musetalk_vram_mode": vram_key_from_label(backend._live_combo_text("musetalk_vram_combo", "")),
        "musetalk_use_frame_cache": backend._live_checked(
            "musetalk_use_frame_cache_checkbox",
            runtime.get("musetalk_use_frame_cache", True),
        ),
        "musetalk_loop_fade_ms": int(
            backend._live_value(
                "musetalk_loop_fade_spin",
                runtime.get("musetalk_loop_fade_ms", DEFAULT_LOOP_FADE_MS) or DEFAULT_LOOP_FADE_MS,
            )
        ),
    }


def build_status_snapshot(backend, runtime_config=None):
    settings = collect_runtime_config(backend, runtime_config)
    vram_key = str(settings.get("musetalk_vram_mode") or "quality")
    return {
        "musetalk_vram_mode": vram_label_from_key(vram_key),
        "musetalk_avatar_pack": backend._live_combo_text("musetalk_avatar_pack_combo", ""),
        "musetalk_loop_fade_ms": int(settings.get("musetalk_loop_fade_ms", DEFAULT_LOOP_FADE_MS) or DEFAULT_LOOP_FADE_MS),
        "musetalk_use_frame_cache": bool(settings.get("musetalk_use_frame_cache", True)),
        "musetalk_vram_mode_key": vram_key,
        "preview_visible": bool(hasattr(backend, "preview_dock") and backend.preview_dock.isVisible()),
    }


def build_tutorial_state(backend):
    """Expose MuseTalk-owned fields for tutorial condition checks."""
    return {
        "musetalk_vram_mode": backend._live_combo_text("musetalk_vram_combo", ""),
        "musetalk_avatar_pack": backend._live_combo_text("musetalk_avatar_pack_combo", ""),
    }


def apply_safe_tutorial_defaults(backend):
    """Apply MuseTalk-owned safe defaults used by first-run tutorials."""
    widget = backend._live_widget_attr("musetalk_vram_combo")
    if widget is not None:
        widget.setCurrentText("Very Low VRAM")


def refresh_resource_widgets(backend, runtime_config=None):
    """Refresh MuseTalk-owned widgets from runtime/session config."""
    runtime = dict(runtime_config or {})
    vram_mode = str(runtime.get("musetalk_vram_mode", "quality") or "quality").lower()
    widget = backend._live_widget_attr("musetalk_vram_combo")
    if widget is not None:
        widget.setCurrentText(vram_label_from_key(vram_mode))


def update_runtime_config_from_widgets(backend, runtime_config=None):
    from engine import update_runtime_config

    for key, value in collect_runtime_config(backend, runtime_config).items():
        update_runtime_config(key, value)


def set_provider_controls_enabled(backend, enabled):
    for object_name in ("btn_musetalk_preview", "btn_musetalk_avatar_focus"):
        widget = backend._live_widget_attr(object_name)
        if widget is not None and hasattr(widget, "setEnabled"):
            widget.setEnabled(bool(enabled))


def restart_sensitive_widgets(backend):
    """Return MuseTalk-owned controls that should lock while the engine is running."""
    return [
        widget
        for widget in (backend._live_widget_attr("musetalk_vram_combo"),)
        if widget is not None
    ]


def _engine():
    import engine

    return engine


def _update_runtime_config(key, value):
    from engine import update_runtime_config

    return update_runtime_config(key, value)


def apply_vram_mode_change(backend, choice):
    mode = vram_key_from_label(choice)
    _update_runtime_config("musetalk_vram_mode", mode)
    if hasattr(backend, "_advisor_context_manual_override"):
        backend._advisor_context_manual_override = False
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "musetalk_vram_mode", "value": choice})
    if hasattr(backend, "update_model_budget_hint"):
        backend.update_model_budget_hint()
    if hasattr(backend, "save_session"):
        backend.save_session()


def apply_loop_fade_change(backend, value):
    fade_ms = max(0, int(value or 0))
    _update_runtime_config("musetalk_loop_fade_ms", fade_ms)
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "musetalk_loop_fade_ms", "value": fade_ms})
    if hasattr(backend, "save_session"):
        backend.save_session()


def apply_frame_cache_change(backend, checked):
    enabled = bool(checked)
    _update_runtime_config("musetalk_use_frame_cache", enabled)
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "musetalk_use_frame_cache", "value": enabled})
    if hasattr(backend, "save_session"):
        backend.save_session()


def refresh_avatar_pack_list(backend, selected_pack_id=None):
    combo = backend._live_widget_attr("musetalk_avatar_pack_combo")
    if combo is None:
        return
    engine = _engine()
    config = engine.RUNTIME_CONFIG
    requested = str(selected_pack_id or combo.currentData() or config.get("musetalk_avatar_pack_id", "") or "").strip()
    catalog = list(engine.get_musetalk_avatar_pack_catalog() or [])
    combo.blockSignals(True)
    combo.clear()
    for item in catalog:
        pack_id = str(item.get("id") or "").strip()
        if not pack_id:
            continue
        display_name = str(item.get("display_name") or pack_id).strip()
        default_avatar_id = str(item.get("default_avatar_id") or "default_avatar").strip()
        source = str(item.get("source") or "manifest").strip()
        combo.addItem(f"{display_name} | {default_avatar_id} [{source}]", pack_id)
    if combo.count() <= 0:
        combo.addItem("No avatar packs found", "")
    target_index = -1
    for index in range(combo.count()):
        if str(combo.itemData(index) or "") == requested:
            target_index = index
            break
    combo.setCurrentIndex(target_index if target_index >= 0 else 0)
    combo.blockSignals(False)


def apply_avatar_pack_change(backend, _choice=None):
    pack_id = str(backend._live_combo_data("musetalk_avatar_pack_combo", "") or "").strip()
    if not pack_id:
        return
    selected_pack_id = _engine().apply_musetalk_avatar_pack_selection(pack_id)
    _update_runtime_config("musetalk_avatar_pack_id", selected_pack_id)
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "musetalk_avatar_pack_id", "value": selected_pack_id})
    if hasattr(backend, "save_session"):
        backend.save_session()


def set_focus_button_text(bridge, text):
    focus_button = bridge._ui_object("btn_musetalk_avatar_focus")
    if focus_button is not None and hasattr(focus_button, "setText"):
        try:
            focus_button.setText(str(text or "Avatar Focus"))
        except Exception:
            pass


def show_preview(bridge):
    if bridge.backend._current_avatar_mode_value() != "musetalk":
        return
    panel = getattr(bridge.backend, "embedded_musetalk_preview", None)
    if bool(getattr(bridge.backend, "_musetalk_avatar_focus_active", False)):
        stage_window = bridge.backend._ensure_musetalk_stage_window()
        bridge.backend._attach_musetalk_preview_to_host("stage")
        stage_window.show()
        stage_window.raise_()
        stage_window.activateWindow()
    else:
        bridge.backend._attach_musetalk_preview_to_host("dock")
        preview_dock = bridge._ui_object("PreviewDock")
        if preview_dock is not None:
            preview_dock.show()
            preview_dock.raise_()
    if panel is not None:
        panel.show()
        if hasattr(panel, "set_focus_mode"):
            panel.set_focus_mode(bool(getattr(bridge.backend, "_musetalk_avatar_focus_active", False)))
    bridge._refresh_musetalk_preview_frontend()


def enter_avatar_focus(bridge):
    if bridge.backend._current_avatar_mode_value() != "musetalk":
        return
    bridge.backend._musetalk_avatar_focus_active = True
    bridge.backend._musetalk_main_window_was_maximized = bool(bridge.window.isMaximized())
    bridge.backend._musetalk_main_window_was_fullscreen = bool(bridge.window.isFullScreen())
    set_focus_button_text(bridge, "Exit Avatar Focus")
    panel = getattr(bridge.backend, "embedded_musetalk_preview", None)
    if panel is not None and hasattr(panel, "set_focus_mode"):
        panel.set_focus_mode(True)
    bridge.backend._attach_musetalk_preview_to_host("stage")
    preview_dock = bridge._ui_object("PreviewDock")
    if preview_dock is not None:
        preview_dock.hide()
    stage_window = bridge.backend._ensure_musetalk_stage_window()
    bridge.backend._sync_musetalk_stage_window_geometry_from_preview()
    stage_window.show()
    stage_window.raise_()
    stage_window.activateWindow()
    bridge._hide_frontend_main_preserving_pinned_floating_docks()
    bridge._refresh_musetalk_preview_frontend()


def exit_avatar_focus(bridge, *, raise_main=False):
    was_active = bool(getattr(bridge.backend, "_musetalk_avatar_focus_active", False))
    bridge.backend._musetalk_avatar_focus_active = False
    set_focus_button_text(bridge, "Avatar Focus")
    panel = getattr(bridge.backend, "embedded_musetalk_preview", None)
    if panel is not None and hasattr(panel, "set_focus_mode"):
        panel.set_focus_mode(False)
    bridge.backend._attach_musetalk_preview_to_host("dock")
    stage_window = getattr(bridge.backend, "_musetalk_stage_window", None)
    if stage_window is not None:
        try:
            stage_window.allow_internal_close(True)
            stage_window.hide()
            stage_window.allow_internal_close(False)
        except Exception:
            pass
    preview_dock = bridge._ui_object("PreviewDock")
    if preview_dock is not None:
        preview_dock.show()
    visual_reply_dock = bridge._ui_object("VisualReplyDock")
    if preview_dock is not None and visual_reply_dock is not None:
        try:
            bridge.window.tabifyDockWidget(preview_dock, visual_reply_dock)
        except Exception:
            pass
    if raise_main or was_active or not bridge.window.isVisible():
        if bool(getattr(bridge.backend, "_musetalk_main_window_was_fullscreen", False)):
            bridge.window.showFullScreen()
        elif bool(getattr(bridge.backend, "_musetalk_main_window_was_maximized", False)):
            bridge.window.showMaximized()
        else:
            bridge.window.showNormal()
        bridge.window.raise_()
        bridge.window.activateWindow()
    bridge._refresh_musetalk_preview_frontend()


def toggle_avatar_focus(bridge):
    if bool(getattr(bridge.backend, "_musetalk_avatar_focus_active", False)):
        exit_avatar_focus(bridge, raise_main=True)
    else:
        enter_avatar_focus(bridge)


def show_main_interface_from_focus(bridge):
    exit_avatar_focus(bridge, raise_main=True)


def stop_preview(bridge):
    exit_avatar_focus(bridge, raise_main=False)
    preview_dock = bridge._ui_object("PreviewDock")
    if preview_dock is not None:
        preview_dock.hide()
    stage_window = getattr(bridge.backend, "_musetalk_stage_window", None)
    if stage_window is not None:
        try:
            stage_window.allow_internal_close(True)
            stage_window.hide()
            stage_window.allow_internal_close(False)
        except Exception:
            pass
    panel = getattr(bridge.backend, "embedded_musetalk_preview", None)
    if panel is not None and hasattr(panel, "reset_preview"):
        panel.reset_preview()
    bridge._refresh_musetalk_preview_frontend()


def bind_preview_controls(bridge):
    preview_button = bridge._ui_object("btn_musetalk_preview")
    if preview_button is not None and hasattr(preview_button, "clicked"):
        preview_button.clicked.connect(lambda: show_preview(bridge))
    focus_button = bridge._ui_object("btn_musetalk_avatar_focus")
    if focus_button is not None and hasattr(focus_button, "clicked"):
        focus_button.clicked.connect(lambda: toggle_avatar_focus(bridge))


def sync_vram_mode(bridge):
    bridge._sync_single_combo_to_backend("musetalk_vram_combo")
    widget = bridge._ui_object("musetalk_vram_combo")
    if widget is not None and hasattr(widget, "currentText"):
        apply_vram_mode_change(bridge.backend, str(widget.currentText() or ""))
    bridge._refresh_musetalk_visual_runtime_frontend()


def sync_avatar_pack(bridge):
    bridge._sync_single_combo_to_backend("musetalk_avatar_pack_combo")
    widget = bridge._ui_object("musetalk_avatar_pack_combo")
    if widget is not None and hasattr(widget, "currentText"):
        apply_avatar_pack_change(bridge.backend, str(widget.currentText() or ""))
    bridge._refresh_musetalk_visual_runtime_frontend()


def refresh_avatar_packs(bridge):
    try:
        refresh_avatar_pack_list(bridge.backend)
    finally:
        if QtCore is not None:
            QtCore.QTimer.singleShot(0, lambda: bridge._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: bridge._sync_backend_to_ui(force=True))


def sync_loop_fade(bridge):
    bridge._sync_single_spin_to_backend("musetalk_loop_fade_spin")
    widget = bridge._ui_object("musetalk_loop_fade_spin")
    if widget is not None and hasattr(widget, "value"):
        apply_loop_fade_change(bridge.backend, int(widget.value()))
    bridge._refresh_profile_utility_runtime_frontend()


def sync_frame_cache(bridge):
    bridge._sync_single_checkbox_to_backend("musetalk_use_frame_cache_checkbox")
    widget = bridge._ui_object("musetalk_use_frame_cache_checkbox")
    if widget is not None and hasattr(widget, "isChecked"):
        apply_frame_cache_change(bridge.backend, bool(widget.isChecked()))
    bridge._refresh_musetalk_visual_runtime_frontend()


def bind_runtime_controls(bridge):
    """Wire MuseTalk-owned runtime controls from main.ui to MuseTalk backend callbacks."""
    combo_bindings = {
        "musetalk_vram_combo": sync_vram_mode,
        "musetalk_avatar_pack_combo": sync_avatar_pack,
    }
    for object_name, callback in combo_bindings.items():
        widget = bridge._ui_object(object_name)
        if widget is None or not hasattr(widget, "currentIndexChanged"):
            continue
        widget.currentIndexChanged.connect(lambda _index=0, cb=callback: cb(bridge))

    refresh_button = bridge._ui_object("btn_musetalk_avatar_pack_refresh")
    if refresh_button is not None and hasattr(refresh_button, "clicked"):
        refresh_button.clicked.connect(lambda _checked=False: refresh_avatar_packs(bridge))

    loop_fade_spin = bridge._ui_object("musetalk_loop_fade_spin")
    if loop_fade_spin is not None and hasattr(loop_fade_spin, "valueChanged"):
        loop_fade_spin.valueChanged.connect(lambda _value=0: sync_loop_fade(bridge))

    frame_cache_checkbox = bridge._ui_object("musetalk_use_frame_cache_checkbox")
    if frame_cache_checkbox is not None and hasattr(frame_cache_checkbox, "toggled"):
        frame_cache_checkbox.toggled.connect(lambda _checked=False: sync_frame_cache(bridge))
