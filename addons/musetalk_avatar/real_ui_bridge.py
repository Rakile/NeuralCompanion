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


def vram_key_from_label(label):
    text = str(label or "").strip()
    for key, value in VRAM_MODE_LABELS.items():
        if text == value:
            return key
    return "quality"


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
    }


def update_runtime_config_from_widgets(backend, runtime_config=None):
    from engine import update_runtime_config

    for key, value in collect_runtime_config(backend, runtime_config).items():
        update_runtime_config(key, value)


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
    callback = getattr(bridge.backend, "on_musetalk_vram_mode_change", None)
    widget = bridge._ui_object("musetalk_vram_combo")
    if callable(callback) and widget is not None and hasattr(widget, "currentText"):
        callback(str(widget.currentText() or ""))
    bridge._refresh_musetalk_visual_runtime_frontend()


def sync_avatar_pack(bridge):
    bridge._sync_single_combo_to_backend("musetalk_avatar_pack_combo")
    callback = getattr(bridge.backend, "on_musetalk_avatar_pack_change", None)
    widget = bridge._ui_object("musetalk_avatar_pack_combo")
    if callable(callback) and widget is not None and hasattr(widget, "currentText"):
        callback(str(widget.currentText() or ""))
    bridge._refresh_musetalk_visual_runtime_frontend()


def refresh_avatar_packs(bridge):
    try:
        callback = getattr(bridge.backend, "refresh_musetalk_avatar_pack_list", None)
        if callable(callback):
            callback()
    finally:
        if QtCore is not None:
            QtCore.QTimer.singleShot(0, lambda: bridge._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: bridge._sync_backend_to_ui(force=True))


def sync_loop_fade(bridge):
    bridge._sync_single_spin_to_backend("musetalk_loop_fade_spin")
    callback = getattr(bridge.backend, "on_musetalk_loop_fade_changed", None)
    widget = bridge._ui_object("musetalk_loop_fade_spin")
    if callable(callback) and widget is not None and hasattr(widget, "value"):
        callback(int(widget.value()))
    bridge._refresh_profile_utility_runtime_frontend()


def sync_frame_cache(bridge):
    bridge._sync_single_checkbox_to_backend("musetalk_use_frame_cache_checkbox")
    callback = getattr(bridge.backend, "on_musetalk_use_frame_cache_changed", None)
    widget = bridge._ui_object("musetalk_use_frame_cache_checkbox")
    if callable(callback) and widget is not None and hasattr(widget, "isChecked"):
        callback(bool(widget.isChecked()))
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
