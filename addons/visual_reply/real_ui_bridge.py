from pathlib import Path

from addons.visual_reply.controller import AddonVisualReplyPanel as QtVisualReplyPanel
from addons.visual_reply import state as visual_reply_state
from core.addons.qt_host_services import AddonCapabilityBridgeService

try:
    from PySide6 import QtCore, QtWidgets
except Exception:  # pragma: no cover - shell smoke may inspect without Qt available.
    QtCore = None
    QtWidgets = None


APP_ROOT = Path(__file__).resolve().parents[2]


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


def build_legacy_runtime_widgets(backend, runtime_config=None):
    """Build Visual Reply-owned controls used by the backend shell."""
    if QtWidgets is None:
        return
    from ui.widgets.basic import NoWheelComboBox

    runtime = dict(runtime_config or {})
    backend.visual_reply_mode_combo = NoWheelComboBox()
    backend.visual_reply_mode_combo.setObjectName("visual_reply_mode_combo")
    backend.visual_reply_mode_combo.addItems(["Off", "Auto"])
    backend.visual_reply_mode_combo.setCurrentText(
        "Off" if str(runtime.get("visual_reply_mode", "auto") or "auto").strip().lower() == "off" else "Auto"
    )
    backend.visual_reply_mode_combo.currentTextChanged.connect(backend.on_visual_reply_mode_changed)

    backend.visual_reply_provider_combo = NoWheelComboBox()
    backend.visual_reply_provider_combo.setObjectName("visual_reply_provider_combo")
    backend.visual_reply_provider_combo.addItems(["OpenAI", "xAI / Grok"])
    current_provider = str(runtime.get("visual_reply_provider", "openai") or "openai").strip().lower()
    backend.visual_reply_provider_combo.setCurrentText("xAI / Grok" if current_provider == "xai" else "OpenAI")
    backend.visual_reply_provider_combo.currentTextChanged.connect(backend.on_visual_reply_provider_changed)

    backend.visual_reply_size_combo = NoWheelComboBox()
    backend.visual_reply_size_combo.setObjectName("visual_reply_size_combo")
    backend.visual_reply_size_combo.addItems(["Auto", "1024x1024", "1024x1536", "1536x1024"])
    current_size = str(runtime.get("visual_reply_size", "1024x1024") or "1024x1024").strip().lower()
    if current_size not in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
        current_size = "1024x1024"
    backend.visual_reply_size_combo.setCurrentText("Auto" if current_size == "auto" else current_size)
    backend.visual_reply_size_combo.currentTextChanged.connect(backend.on_visual_reply_size_changed)

    backend.visual_reply_model_edit = QtWidgets.QLineEdit()
    backend.visual_reply_model_edit.setObjectName("visual_reply_model_edit")
    backend.visual_reply_model_edit.setText(str(runtime.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"))
    backend.visual_reply_model_edit.editingFinished.connect(backend.on_visual_reply_model_changed)

    backend.visual_reply_auto_show_checkbox = QtWidgets.QCheckBox("Auto-show Visual Reply dock")
    backend.visual_reply_auto_show_checkbox.setObjectName("visual_reply_auto_show_checkbox")
    backend.visual_reply_auto_show_checkbox.setChecked(bool(runtime.get("visual_reply_auto_show_dock", True)))
    backend.visual_reply_auto_show_checkbox.toggled.connect(backend.on_visual_reply_auto_show_changed)


def build_legacy_settings_tab(backend):
    """Build the Visual Reply settings tab owned by the Visual Reply addon."""
    if QtCore is None or QtWidgets is None:
        return None
    tab = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(tab)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(10)

    visual_box = QtWidgets.QGroupBox("Visual Replies")
    visual_layout = QtWidgets.QVBoxLayout(visual_box)
    visual_layout.setContentsMargins(12, 14, 12, 12)
    visual_layout.setSpacing(8)

    visual_form = QtWidgets.QFormLayout()
    visual_form.setLabelAlignment(QtCore.Qt.AlignLeft)
    visual_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldsStayAtSizeHint)
    visual_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
    visual_form.addRow("Mode", backend.visual_reply_mode_combo)
    visual_form.addRow("Provider", backend.visual_reply_provider_combo)
    visual_form.addRow("Image Size", backend.visual_reply_size_combo)
    visual_form.addRow("Image Model", backend.visual_reply_model_edit)
    visual_layout.addLayout(visual_form)
    visual_layout.addWidget(backend.visual_reply_auto_show_checkbox)

    backend.visual_reply_hint = QtWidgets.QLabel()
    backend.visual_reply_hint.setObjectName("visual_reply_hint")
    backend.visual_reply_hint.setWordWrap(True)
    backend.visual_reply_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
    visual_layout.addWidget(backend.visual_reply_hint)
    backend._refresh_visual_reply_hint()

    layout.addWidget(visual_box)
    layout.addStretch(1)
    return tab


def build_legacy_utility_button(backend):
    """Build the Visual Reply utility button used by the backend shell."""
    if QtWidgets is None:
        return None
    backend.btn_visual_reply = QtWidgets.QPushButton("Show Visual Reply")
    backend.btn_visual_reply.setObjectName("btn_visual_reply")
    backend.btn_visual_reply.clicked.connect(backend.show_visual_reply_dock)
    return backend.btn_visual_reply


def build_dock(
    backend,
    *,
    theme_provider=None,
    runtime_config=None,
    shared_state_module=None,
    storage_dir=None,
):
    """Create the Visual Reply dock owned by the Visual Reply addon."""
    if QtCore is None or QtWidgets is None:
        return None
    dock = QtWidgets.QDockWidget("Visual Reply", backend)
    dock.setObjectName("VisualReplyDock")
    dock.setAllowedAreas(
        QtCore.Qt.RightDockWidgetArea
        | QtCore.Qt.BottomDockWidgetArea
        | QtCore.Qt.LeftDockWidgetArea
    )
    panel = QtVisualReplyPanel(
        theme_provider=theme_provider,
        runtime_config=runtime_config,
        shared_state_module=shared_state_module or visual_reply_state,
        storage_dir=storage_dir or (APP_ROOT / "runtime" / "visual_replies"),
    )
    panel.loadRequested.connect(backend.prompt_visual_reply_image)
    panel.captionRequested.connect(backend.prompt_visual_reply_caption)
    panel.clearRequested.connect(lambda: backend.clear_visual_reply(auto_show=False))
    dock.setWidget(panel)
    backend.visual_reply_dock = dock
    backend.visual_reply_panel = panel
    backend._register_workspace_dock(dock)
    backend.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
    dock.hide()
    if hasattr(backend, "preview_dock"):
        try:
            backend.tabifyDockWidget(backend.preview_dock, dock)
        except Exception:
            pass
    if hasattr(backend, "workspace_menu"):
        backend.workspace_menu.insertAction(backend.workspace_menu.actions()[-2], dock.toggleViewAction())
    return dock


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


def redirect_runtime_surface(bridge):
    """Mount the live Visual Reply panel into main.ui and claim backend routing."""
    frontend_dock = bridge._ui_object("VisualReplyDock")
    if frontend_dock is None or not hasattr(frontend_dock, "setWidget"):
        return False
    addon_enabled = True
    checker = getattr(bridge, "_visual_reply_addon_enabled", None)
    if callable(checker):
        addon_enabled = bool(checker())
    backend_dock = getattr(bridge.backend, "visual_reply_dock", None)
    if backend_dock is not None and backend_dock is not frontend_dock:
        # The hidden backend may restore its own saved dock before the real UI
        # redirect runs. Hide it before replacing the backend surface pointer.
        try:
            backend_dock.hide()
        except Exception:
            pass
    if not addon_enabled:
        enforcer = getattr(bridge, "_enforce_disabled_frontend_workspace_docks", None)
        if callable(enforcer):
            enforcer()
        else:
            try:
                frontend_dock.hide()
            except Exception:
                pass
        setattr(bridge.window, "show_visual_reply_dock", lambda *args, **kwargs: None)
        bridge._visual_reply_runtime_redirected = False
        return False
    old_widget = None
    try:
        old_widget = frontend_dock.widget()
    except Exception:
        old_widget = None
    if old_widget is not None and hasattr(old_widget, "setObjectName"):
        try:
            old_widget.setObjectName("visual_reply_panel_legacy")
        except Exception:
            pass
        for legacy_name in (
            "visual_reply_status",
            "visual_reply_storage_label",
            "visual_reply_previous_button",
            "visual_reply_load_button",
            "visual_reply_next_button",
            "visual_reply_load_current_story_button",
            "visual_reply_use_current_style_button",
            "visual_reply_caption_button",
            "visual_reply_delete_button",
            "visual_reply_clear_button",
            "visual_reply_delete_all_button",
            "visual_reply_frame",
            "visual_reply_image_label",
        ):
            try:
                child = old_widget.findChild(QtCore.QObject, legacy_name)
            except Exception:
                child = None
            if child is not None and hasattr(child, "setObjectName"):
                try:
                    child.setObjectName(f"{legacy_name}_legacy")
                except Exception:
                    pass
    panel = build_runtime_panel(bridge)
    connect_runtime_panel(bridge, panel)
    try:
        frontend_dock.setWidget(panel)
        bridge.backend.visual_reply_dock = frontend_dock
        bridge.backend.visual_reply_panel = panel
        bridge._frontend_visual_reply_panel = panel
        setattr(bridge.window, "show_visual_reply_dock", bridge._show_frontend_visual_reply_dock)
        bridge._visual_reply_runtime_redirected = True
    except Exception as exc:
        print(f"[UI Real] Visual Reply runtime surface redirect failed: {exc}")
        return False
    if old_widget is not None and old_widget is not panel:
        try:
            old_widget.deleteLater()
        except Exception:
            pass
    return True


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
