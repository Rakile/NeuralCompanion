try:
    from PySide6 import QtCore, QtWidgets
except Exception:  # pragma: no cover - shell smoke may inspect without Qt available.
    QtCore = None
    QtWidgets = None

from core.addons.qt_host_services import QtRuntimeConfigService
from addons.musetalk_avatar.text_policy import normalize_vram_mode


VRAM_MODE_LABELS = {
    "quality": "Quality",
    "balanced": "Balanced",
    "low": "Low VRAM",
    "very_low": "Very Low VRAM",
}
VRAM_MODE_OVERHEAD_GIB = {
    "Quality": 5.8,
    "Balanced": 4.0,
    "Low VRAM": 2.3,
    "Very Low VRAM": 1.5,
}
VRAM_MODE_TOOLTIP = (
    "MuseTalk-only memory profile. Quality uses larger render batches and keeps MuseTalk's Whisper encoder on GPU; "
    "Balanced lowers batch size and enables VAE slicing; Low and Very Low use smaller batches and move MuseTalk's "
    "internal Whisper encoder to CPU. Main STT Whisper still uses GPU when available."
)
LOOP_FADE_TOOLTIP = (
    "MuseTalk preview crossfade duration when switching avatar/emotion frames. 0 disables the fade; "
    "higher values smooth changes but can delay visible updates."
)
FRAME_CACHE_TOOLTIP = (
    "Use/create MuseTalk NumPy frame caches for faster avatar startup. Disable to save disk space and always read PNG frames."
)
AVATAR_PACK_TOOLTIP = "Prepared MuseTalk avatar pack and variant used for rendering visual speech."
AVATAR_PACK_REFRESH_TOOLTIP = "Rescan installed MuseTalk avatar packs under avatar_packs/."
UA_COMPANION_ORB_TOOLTIP = (
    "Send MuseTalk preview frames as grayscale masks to the Ua Companion Orb Unreal overlay. "
    "When enabled, the local MuseTalk preview is suppressed."
)
DEFAULT_LOOP_FADE_MS = 180
PERFORMANCE_PROFILE_APPLY_KEYS = {
    "musetalk_vram_mode",
    "musetalk_chunk_target_chars",
    "musetalk_chunk_max_chars",
    "musetalk_quickstart_1_target_chars",
    "musetalk_quickstart_1_max_chars",
    "musetalk_quickstart_2_target_chars",
    "musetalk_quickstart_2_max_chars",
}
PERFORMANCE_SUMMARY_SETTING_KEYS = [
    "musetalk_chunk_target_chars",
    "musetalk_chunk_max_chars",
    "musetalk_quickstart_1_target_chars",
    "musetalk_quickstart_1_max_chars",
    "musetalk_quickstart_2_target_chars",
    "musetalk_quickstart_2_max_chars",
]


def vram_key_from_label(label):
    text = str(label or "").strip()
    for key, value in VRAM_MODE_LABELS.items():
        if text == value:
            return key
    return "quality"


def vram_label_from_key(value):
    return VRAM_MODE_LABELS.get(normalize_vram_mode(value), "Quality")


def estimated_runtime_overhead_gib(backend):
    label = backend._live_combo_text("musetalk_vram_combo", "Very Low VRAM").strip() or "Very Low VRAM"
    return float(VRAM_MODE_OVERHEAD_GIB.get(label, 6.5))


def performance_profile_apply_keys():
    return set(PERFORMANCE_PROFILE_APPLY_KEYS)


def performance_summary_setting_keys():
    return list(PERFORMANCE_SUMMARY_SETTING_KEYS)


def performance_profile_label_fragment(item):
    return str(item.get("musetalk_vram_mode") or "").replace("_", " ").title()


def performance_candidate_log_fragment(settings):
    return (
        f"muse_target={settings.get('musetalk_chunk_target_chars')} "
        f"muse_max={settings.get('musetalk_chunk_max_chars')} "
        f"qs1={settings.get('musetalk_quickstart_1_target_chars')}/{settings.get('musetalk_quickstart_1_max_chars')} "
        f"qs2={settings.get('musetalk_quickstart_2_target_chars')}/{settings.get('musetalk_quickstart_2_max_chars')}"
    )


def chunking_slider_specs(runtime_config=None):
    runtime = dict(runtime_config or {})
    return [
        ("Target Chars", "musetalk_chunk_target_chars", 60, 220, int(runtime.get("musetalk_chunk_target_chars", 110) or 110), True),
        ("Max Chars", "musetalk_chunk_max_chars", 80, 320, int(runtime.get("musetalk_chunk_max_chars", 220) or 220), True),
        (
            "Quickstart 1 Target",
            "musetalk_quickstart_1_target_chars",
            60,
            260,
            int(runtime.get("musetalk_quickstart_1_target_chars", 170) or 170),
            True,
        ),
        (
            "Quickstart 1 Max",
            "musetalk_quickstart_1_max_chars",
            80,
            360,
            int(runtime.get("musetalk_quickstart_1_max_chars", 320) or 320),
            True,
        ),
        (
            "Quickstart 2 Target",
            "musetalk_quickstart_2_target_chars",
            60,
            240,
            int(runtime.get("musetalk_quickstart_2_target_chars", 130) or 130),
            True,
        ),
        (
            "Quickstart 2 Max",
            "musetalk_quickstart_2_max_chars",
            80,
            320,
            int(runtime.get("musetalk_quickstart_2_max_chars", 240) or 240),
            True,
        ),
    ]


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
        "ua_companion_orb_send_musetalk_face_mask": backend._live_checked(
            "ua_companion_orb_send_musetalk_face_mask_checkbox",
            runtime.get("ua_companion_orb_send_musetalk_face_mask", False),
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


def apply_runtime_settings(backend, settings):
    """Apply MuseTalk-owned settings from dry-run/profile payloads."""
    payload = dict(settings or {})
    widget = backend._live_widget_attr("musetalk_vram_combo")
    if "musetalk_vram_mode" in payload and widget is not None:
        widget.setCurrentText(vram_label_from_key(payload["musetalk_vram_mode"]))
    widget = backend._live_widget_attr("musetalk_loop_fade_spin")
    if "musetalk_loop_fade_ms" in payload and widget is not None:
        fade_ms = max(0, int(payload["musetalk_loop_fade_ms"] or 0))
        widget.setValue(fade_ms)
        apply_loop_fade_change(backend, fade_ms)
    widget = backend._live_widget_attr("musetalk_use_frame_cache_checkbox")
    if "musetalk_use_frame_cache" in payload and widget is not None:
        enabled = bool(payload["musetalk_use_frame_cache"])
        widget.setChecked(enabled)
        apply_frame_cache_change(backend, enabled)
    widget = backend._live_widget_attr("ua_companion_orb_send_musetalk_face_mask_checkbox")
    if "ua_companion_orb_send_musetalk_face_mask" in payload and widget is not None:
        enabled = bool(payload["ua_companion_orb_send_musetalk_face_mask"])
        widget.setChecked(enabled)
        apply_ua_companion_orb_send_change(backend, enabled)


def add_performance_override(backend, override, runtime_config=None):
    """Add MuseTalk-owned performance-profile fields to a host override payload."""
    settings = collect_runtime_config(backend, runtime_config)
    override.update(
        {
            "musetalk_avatar_pack_id": str(settings.get("musetalk_avatar_pack_id") or ""),
            "musetalk_vram_mode": str(settings.get("musetalk_vram_mode") or "quality"),
        }
    )
    return override


def refresh_resource_widgets(backend, runtime_config=None):
    """Refresh MuseTalk-owned widgets from runtime/session config."""
    runtime = dict(runtime_config or {})
    vram_mode = str(runtime.get("musetalk_vram_mode", "quality") or "quality").lower()
    widget = backend._live_widget_attr("musetalk_vram_combo")
    if widget is not None:
        widget.setCurrentText(vram_label_from_key(vram_mode))
    widget = backend._live_widget_attr("ua_companion_orb_send_musetalk_face_mask_checkbox")
    if widget is not None:
        widget.setChecked(bool(runtime.get("ua_companion_orb_send_musetalk_face_mask", False)))


def update_runtime_config_from_widgets(backend, runtime_config=None):
    for key, value in collect_runtime_config(backend, runtime_config).items():
        _update_runtime_config(backend, key, value)


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


def _runtime_config_service(backend):
    return QtRuntimeConfigService(backend)


def _update_runtime_config(backend, key, value):
    return _runtime_config_service(backend).update(key, value)


def _engine_attr(backend, name: str, default=None):
    return _runtime_config_service(backend).engine_attr(name, default)


def apply_vram_mode_change(backend, choice):
    mode = normalize_vram_mode(vram_key_from_label(choice))
    _update_runtime_config(backend, "musetalk_vram_mode", mode)
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
    _update_runtime_config(backend, "musetalk_loop_fade_ms", fade_ms)
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "musetalk_loop_fade_ms", "value": fade_ms})
    if hasattr(backend, "save_session"):
        backend.save_session()


def apply_frame_cache_change(backend, checked):
    enabled = bool(checked)
    _update_runtime_config(backend, "musetalk_use_frame_cache", enabled)
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "musetalk_use_frame_cache", "value": enabled})
    if hasattr(backend, "save_session"):
        backend.save_session()


def apply_ua_companion_orb_send_change(backend, checked):
    enabled = bool(checked)
    _update_runtime_config(backend, "ua_companion_orb_send_musetalk_face_mask", enabled)
    preview = getattr(backend, "embedded_musetalk_preview", None)
    if preview is not None and hasattr(preview, "reset_preview"):
        preview.reset_preview()
        if enabled and hasattr(preview, "preview_label"):
            preview.preview_label.setText("MuseTalk routed to Ua Companion Orb")
    if enabled:
        for dock_name in ("preview_dock", "_musetalk_stage_window"):
            dock = getattr(backend, dock_name, None)
            if dock is not None and hasattr(dock, "hide"):
                dock.hide()
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "ua_companion_orb_send_musetalk_face_mask", "value": enabled})
    if hasattr(backend, "save_session"):
        backend.save_session()


def refresh_avatar_pack_list(backend, selected_pack_id=None):
    combo = backend._live_widget_attr("musetalk_avatar_pack_combo")
    if combo is None:
        return
    config = _runtime_config_service(backend).snapshot()
    requested = str(selected_pack_id or combo.currentData() or config.get("musetalk_avatar_pack_id", "") or "").strip()
    catalog_getter = _engine_attr(backend, "get_musetalk_avatar_pack_catalog", lambda: [])
    catalog = list(catalog_getter() or [])
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
    selector = _engine_attr(backend, "apply_musetalk_avatar_pack_selection", lambda value: value)
    selected_pack_id = selector(pack_id)
    _update_runtime_config(backend, "musetalk_avatar_pack_id", selected_pack_id)
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "musetalk_avatar_pack_id", "value": selected_pack_id})
    if hasattr(backend, "save_session"):
        backend.save_session()


def build_preview_dock(backend, *, theme_provider=None, runtime_config=None):
    """Create the MuseTalk preview dock owned by the MuseTalk addon."""
    if QtCore is None or QtWidgets is None:
        return None
    from addons.musetalk_avatar.preview_panel import QtMuseTalkPreviewPanel

    dock = QtWidgets.QDockWidget("MuseTalk Preview", backend)
    dock.setObjectName("MuseTalkPreviewDock")
    dock.setAllowedAreas(
        QtCore.Qt.RightDockWidgetArea
        | QtCore.Qt.BottomDockWidgetArea
        | QtCore.Qt.LeftDockWidgetArea
    )
    container = QtWidgets.QWidget()
    container.setMinimumWidth(0)
    container.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    panel = QtMuseTalkPreviewPanel(
        theme_provider=theme_provider,
        runtime_config=runtime_config,
    )
    panel.focusModeRequested.connect(backend.toggle_musetalk_avatar_focus)
    panel.showInterfaceRequested.connect(backend.show_main_interface_from_musetalk_focus)
    layout.addWidget(panel)
    dock.setWidget(container)

    backend.preview_dock = dock
    backend.preview_dock_container = container
    backend.preview_dock_layout = layout
    backend.embedded_musetalk_preview = panel
    backend._register_workspace_dock(dock)
    backend.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.hide()
    backend._ensure_musetalk_stage_window()
    if hasattr(backend, "workspace_menu"):
        backend.workspace_menu.insertAction(backend.workspace_menu.actions()[-2], dock.toggleViewAction())
    return dock


def build_legacy_runtime_widgets(backend, runtime_config=None):
    """Build MuseTalk-owned controls used by the legacy/backend shell."""
    if QtWidgets is None:
        return
    from ui.widgets.basic import ContextTokenStepper, NoWheelComboBox

    runtime = dict(runtime_config or {})
    backend.musetalk_vram_combo = NoWheelComboBox()
    backend.musetalk_vram_combo.setObjectName("musetalk_vram_combo")
    backend.musetalk_vram_combo.addItems(list(VRAM_MODE_LABELS.values()))
    backend.musetalk_vram_combo.setToolTip(VRAM_MODE_TOOLTIP)
    backend.musetalk_vram_combo.currentTextChanged.connect(backend.on_musetalk_vram_mode_change)

    backend.musetalk_loop_fade_spin = ContextTokenStepper()
    backend.musetalk_loop_fade_spin.setObjectName("musetalk_loop_fade_spin")
    backend.musetalk_loop_fade_spin.setRange(0, 1000)
    backend.musetalk_loop_fade_spin.setSingleStep(50)
    backend.musetalk_loop_fade_spin.setValue(
        max(0, int(runtime.get("musetalk_loop_fade_ms", DEFAULT_LOOP_FADE_MS) or DEFAULT_LOOP_FADE_MS))
    )
    backend.musetalk_loop_fade_spin.valueChanged.connect(backend.on_musetalk_loop_fade_changed)
    backend.musetalk_loop_fade_spin.setMinimumWidth(112)
    backend.musetalk_loop_fade_spin.setMaximumWidth(132)
    backend.musetalk_loop_fade_spin.setToolTip(LOOP_FADE_TOOLTIP)

    backend.musetalk_use_frame_cache_checkbox = QtWidgets.QCheckBox("Use .npy startup cache")
    backend.musetalk_use_frame_cache_checkbox.setObjectName("musetalk_use_frame_cache_checkbox")
    backend.musetalk_use_frame_cache_checkbox.setChecked(bool(runtime.get("musetalk_use_frame_cache", True)))
    backend.musetalk_use_frame_cache_checkbox.setToolTip(FRAME_CACHE_TOOLTIP)
    backend.musetalk_use_frame_cache_checkbox.toggled.connect(backend.on_musetalk_use_frame_cache_changed)

    backend.ua_companion_orb_send_musetalk_face_mask_checkbox = QtWidgets.QCheckBox("Send MuseTalk face mask to Ua Companion Orb")
    backend.ua_companion_orb_send_musetalk_face_mask_checkbox.setObjectName("ua_companion_orb_send_musetalk_face_mask_checkbox")
    backend.ua_companion_orb_send_musetalk_face_mask_checkbox.setChecked(
        bool(runtime.get("ua_companion_orb_send_musetalk_face_mask", False))
    )
    backend.ua_companion_orb_send_musetalk_face_mask_checkbox.setToolTip(UA_COMPANION_ORB_TOOLTIP)
    backend.ua_companion_orb_send_musetalk_face_mask_checkbox.toggled.connect(
        lambda checked: apply_ua_companion_orb_send_change(backend, checked)
    )

    backend.musetalk_avatar_pack_combo = NoWheelComboBox()
    backend.musetalk_avatar_pack_combo.setObjectName("musetalk_avatar_pack_combo")
    backend.musetalk_avatar_pack_combo.setToolTip(AVATAR_PACK_TOOLTIP)
    backend.musetalk_avatar_pack_combo.currentTextChanged.connect(backend.on_musetalk_avatar_pack_change)
    backend.btn_musetalk_avatar_pack_refresh = QtWidgets.QPushButton("Refresh")
    backend.btn_musetalk_avatar_pack_refresh.setObjectName("btn_musetalk_avatar_pack_refresh")
    backend.btn_musetalk_avatar_pack_refresh.setToolTip(AVATAR_PACK_REFRESH_TOOLTIP)
    backend.btn_musetalk_avatar_pack_refresh.clicked.connect(backend.refresh_musetalk_avatar_pack_list)
    pack_row = QtWidgets.QHBoxLayout()
    pack_row.setContentsMargins(0, 0, 0, 0)
    pack_row.setSpacing(8)
    pack_row.addWidget(backend.musetalk_avatar_pack_combo, 1)
    pack_row.addWidget(backend.btn_musetalk_avatar_pack_refresh, 0)
    pack_row_widget = QtWidgets.QWidget()
    pack_row_widget.setLayout(pack_row)
    backend.musetalk_avatar_pack_row_widget = pack_row_widget


def build_legacy_utility_buttons(backend):
    """Build MuseTalk-owned utility buttons used by the legacy/backend shell."""
    if QtWidgets is None:
        return []
    backend.btn_musetalk_preview = QtWidgets.QPushButton("Show MuseTalk Preview")
    backend.btn_musetalk_preview.setObjectName("btn_musetalk_preview")
    backend.btn_musetalk_preview.clicked.connect(backend.show_musetalk_preview)
    backend.btn_musetalk_preview.setEnabled(False)
    backend.btn_musetalk_avatar_focus = QtWidgets.QPushButton("Avatar Focus")
    backend.btn_musetalk_avatar_focus.setObjectName("btn_musetalk_avatar_focus")
    backend.btn_musetalk_avatar_focus.clicked.connect(backend.toggle_musetalk_avatar_focus)
    backend.btn_musetalk_avatar_focus.setEnabled(False)
    return [backend.btn_musetalk_preview, backend.btn_musetalk_avatar_focus]


def ensure_stage_window(backend):
    """Create the standalone MuseTalk avatar-focus stage window."""
    if backend._musetalk_stage_window is None:
        from addons.musetalk_avatar.stage_window import QtMuseTalkStageWindow

        backend._musetalk_stage_window = QtMuseTalkStageWindow()
        backend._musetalk_stage_window.closeRequested.connect(backend.show_main_interface_from_musetalk_focus)
    return backend._musetalk_stage_window


def attach_preview_to_host(backend, host):
    panel = getattr(backend, "embedded_musetalk_preview", None)
    if panel is None:
        return False
    target_layout = getattr(backend, "preview_dock_layout", None)
    if host == "stage":
        stage_window = backend._ensure_musetalk_stage_window()
        stage_window.attach_preview_widget(panel)
        return True
    if target_layout is None:
        return False
    old_parent = panel.parentWidget()
    if old_parent is not None and old_parent.layout() is not None:
        old_parent.layout().removeWidget(panel)
    panel.setParent(None)
    target_layout.addWidget(panel)
    panel.show()
    return True


def sync_stage_window_geometry_from_preview(backend):
    stage_window = backend._ensure_musetalk_stage_window()
    source_rect = None
    preview_dock = getattr(backend, "preview_dock", None)
    if preview_dock is not None:
        try:
            dock_rect = preview_dock.frameGeometry()
            if dock_rect.isValid() and dock_rect.width() > 120 and dock_rect.height() > 120:
                source_rect = QtCore.QRect(dock_rect)
        except Exception:
            source_rect = None
    if source_rect is None:
        panel = getattr(backend, "embedded_musetalk_preview", None)
        if panel is not None:
            try:
                panel_size = panel.size()
                if panel_size.width() <= 32 or panel_size.height() <= 32:
                    panel_size = panel.sizeHint()
                top_left = panel.mapToGlobal(QtCore.QPoint(0, 0))
                source_rect = QtCore.QRect(top_left, panel_size)
            except Exception:
                source_rect = None
    if source_rect is None or source_rect.width() <= 32 or source_rect.height() <= 32:
        return False
    try:
        stage_window.showNormal()
    except Exception:
        pass
    stage_window.setGeometry(source_rect)
    return True


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


def redirect_preview_runtime_surface(bridge):
    """Mount the backend MuseTalk preview panel into the real main.ui dock."""
    frontend_dock = bridge._ui_object("PreviewDock")
    if frontend_dock is None or not hasattr(frontend_dock, "setWidget") or QtWidgets is None:
        return
    panel = getattr(bridge.backend, "embedded_musetalk_preview", None)
    if panel is None:
        return
    old_widget = None
    try:
        old_widget = frontend_dock.widget()
    except Exception:
        old_widget = None
    container = QtWidgets.QWidget()
    container.setObjectName("preview_dock_content")
    layout = QtWidgets.QVBoxLayout(container)
    layout.setObjectName("previewDockLayout")
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    try:
        old_parent = panel.parentWidget()
        if old_parent is not None and old_parent.layout() is not None:
            old_parent.layout().removeWidget(panel)
    except Exception:
        pass
    panel.setParent(None)
    layout.addWidget(panel)
    try:
        focus_signal = getattr(panel, "focusModeRequested", None)
        if focus_signal is not None:
            focus_signal.disconnect()
            focus_signal.connect(bridge._toggle_frontend_musetalk_avatar_focus)
    except Exception:
        pass
    try:
        show_interface_signal = getattr(panel, "showInterfaceRequested", None)
        if show_interface_signal is not None:
            show_interface_signal.disconnect()
            show_interface_signal.connect(bridge._show_frontend_main_interface_from_musetalk_focus)
    except Exception:
        pass
    stage_window = None
    try:
        stage_window = bridge.backend._ensure_musetalk_stage_window()
    except Exception:
        stage_window = None
    if stage_window is not None:
        try:
            stage_window.closeRequested.connect(bridge._show_frontend_main_interface_from_musetalk_focus)
        except Exception:
            pass
    try:
        frontend_dock.setWidget(container)
        bridge.backend.preview_dock = frontend_dock
        bridge.backend.preview_dock_container = container
        bridge.backend.preview_dock_layout = layout
        bridge.backend.embedded_musetalk_preview = panel
        bridge._frontend_musetalk_preview_panel = panel
        setattr(bridge.window, "show_musetalk_preview", bridge._show_frontend_musetalk_preview)
        setattr(bridge.window, "toggle_musetalk_avatar_focus", bridge._toggle_frontend_musetalk_avatar_focus)
        setattr(bridge.window, "show_main_interface_from_musetalk_focus", bridge._show_frontend_main_interface_from_musetalk_focus)
        setattr(bridge.window, "stop_musetalk_preview", bridge._stop_frontend_musetalk_preview)
        bridge._musetalk_preview_runtime_redirected = True
    except Exception as exc:
        print(f"[UI Real] MuseTalk preview runtime surface redirect failed: {exc}")
        return
    if old_widget is not None and old_widget is not container:
        try:
            old_widget.deleteLater()
        except Exception:
            pass


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


def sync_ua_companion_orb_send(bridge):
    bridge._sync_single_checkbox_to_backend("ua_companion_orb_send_musetalk_face_mask_checkbox")
    widget = bridge._ui_object("ua_companion_orb_send_musetalk_face_mask_checkbox")
    if widget is not None and hasattr(widget, "isChecked"):
        apply_ua_companion_orb_send_change(bridge.backend, bool(widget.isChecked()))
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

    ua_companion_orb_checkbox = bridge._ui_object("ua_companion_orb_send_musetalk_face_mask_checkbox")
    if ua_companion_orb_checkbox is not None and hasattr(ua_companion_orb_checkbox, "toggled"):
        ua_companion_orb_checkbox.toggled.connect(lambda _checked=False: sync_ua_companion_orb_send(bridge))
