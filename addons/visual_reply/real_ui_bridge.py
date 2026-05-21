from pathlib import Path

from addons.visual_reply.controller import AddonVisualReplyPanel as QtVisualReplyPanel
from addons.visual_reply import state as visual_reply_state
from addons.visual_reply.runtime import (
    on_visual_reply_api_key_changed,
    on_visual_reply_auto_show_changed,
    on_visual_reply_comfyui_cleanup_changed,
    on_visual_reply_mode_changed,
    on_visual_reply_model_changed,
    on_visual_reply_provider_changed,
    on_visual_reply_size_changed,
    normalize_visual_reply_size,
    refresh_visual_reply_hint,
    sync_visual_reply_api_key_field,
    sync_visual_reply_comfyui_cleanup_field,
    sync_visual_reply_model_field,
    sync_visual_reply_size_field,
    visual_reply_model_for_provider,
    visual_reply_size_for_provider,
    visual_reply_mode_label_from_value,
    visual_reply_mode_value_from_label,
    visual_reply_default_model_for_provider,
    visual_reply_comfyui_cleanup_label_from_value,
    visual_reply_provider_label_from_value,
    visual_reply_provider_value_from_label,
    visual_reply_size_label_from_value,
)
from addons.visual_reply.providers import provider_labels, provider_setting_from_config, provider_settings_from_config
from core.addons.qt_host_services import AddonCapabilityBridgeService, QtRuntimeConfigService

try:
    import shiboken6
except Exception:  # pragma: no cover
    shiboken6 = None

try:
    from PySide6 import QtCore, QtWidgets
except Exception:  # pragma: no cover - shell smoke may inspect without Qt available.
    QtCore = None
    QtWidgets = None


APP_ROOT = Path(__file__).resolve().parents[2]


def _qt_widget_alive(widget):
    if widget is None:
        return False
    if shiboken6 is None:
        return True
    try:
        return bool(shiboken6.isValid(widget))
    except Exception:
        return False


def _legacy_runtime_widgets_alive(backend) -> bool:
    for name in (
        "visual_reply_mode_combo",
        "visual_reply_provider_combo",
        "visual_reply_size_combo",
        "visual_reply_model_edit",
        "visual_reply_api_key_edit",
        "visual_reply_comfyui_cleanup_combo",
        "visual_reply_auto_show_checkbox",
    ):
        if not _qt_widget_alive(getattr(backend, name, None)):
            return False
    return True


def _provider_from_runtime_config(runtime) -> str:
    runtime = dict(runtime or {})
    provider = str(runtime.get("visual_reply_provider", "openai") or "openai").strip().lower()
    if provider == "openai":
        openai_model = str(
            provider_setting_from_config(runtime, "openai", "model", "")
            or runtime.get("visual_reply_model", "")
            or ""
        ).strip().lower()
        comfy_workflow = str(provider_setting_from_config(runtime, "comfyui", "model", "") or "").strip()
        if comfy_workflow and openai_model.endswith(".json"):
            return "comfyui"
    return provider


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
        "Off" if str(runtime.get("visual_reply_mode", "off") or "off").strip().lower() == "off" else "Auto"
    )
    backend.visual_reply_mode_combo.currentTextChanged.connect(lambda choice: on_visual_reply_mode_changed(backend, choice))

    backend.visual_reply_provider_combo = NoWheelComboBox()
    backend.visual_reply_provider_combo.setObjectName("visual_reply_provider_combo")
    backend.visual_reply_provider_combo.addItems(provider_labels())
    current_provider = _provider_from_runtime_config(runtime)
    backend._visual_reply_active_provider = current_provider
    backend.visual_reply_provider_combo.setCurrentText(visual_reply_provider_label_from_value(current_provider))
    backend.visual_reply_provider_combo.currentTextChanged.connect(lambda choice: on_visual_reply_provider_changed(backend, choice))

    backend.visual_reply_size_combo = NoWheelComboBox()
    backend.visual_reply_size_combo.setObjectName("visual_reply_size_combo")
    backend.visual_reply_size_combo.addItems(["Auto", "1024x1024", "1024x1536", "1536x1024"])
    current_size = str(provider_setting_from_config(runtime, current_provider, "size", runtime.get("visual_reply_size", "1024x1024")) or "1024x1024").strip().lower()
    if current_size not in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
        current_size = "1024x1024"
    backend.visual_reply_size_combo.setCurrentText("Auto" if current_size == "auto" else current_size)
    backend.visual_reply_size_combo.currentTextChanged.connect(lambda choice: on_visual_reply_size_changed(backend, choice))

    backend.visual_reply_model_edit = QtWidgets.QLineEdit()
    backend.visual_reply_model_edit.setObjectName("visual_reply_model_edit")
    default_model = visual_reply_default_model_for_provider(current_provider)
    current_model = str(provider_setting_from_config(runtime, current_provider, "model", runtime.get("visual_reply_model", default_model)) or default_model).strip()
    backend.visual_reply_model_edit.setText(current_model)
    backend.visual_reply_model_edit.editingFinished.connect(lambda: on_visual_reply_model_changed(backend))

    backend.visual_reply_api_key_edit = QtWidgets.QLineEdit()
    backend.visual_reply_api_key_edit.setObjectName("visual_reply_api_key_edit")
    backend.visual_reply_api_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
    backend.visual_reply_api_key_edit.editingFinished.connect(lambda: on_visual_reply_api_key_changed(backend))
    sync_visual_reply_api_key_field(backend, current_provider)

    backend.visual_reply_comfyui_cleanup_combo = NoWheelComboBox()
    backend.visual_reply_comfyui_cleanup_combo.setObjectName("visual_reply_comfyui_cleanup_combo")
    backend.visual_reply_comfyui_cleanup_combo.addItems(["Keep cache", "Free memory", "Unload models + free memory"])
    current_cleanup = str(provider_setting_from_config(runtime, "comfyui", "cleanup_mode", "keep_cache") or "keep_cache")
    backend.visual_reply_comfyui_cleanup_combo.setCurrentText(visual_reply_comfyui_cleanup_label_from_value(current_cleanup))
    backend.visual_reply_comfyui_cleanup_combo.currentTextChanged.connect(lambda choice: on_visual_reply_comfyui_cleanup_changed(backend, choice))

    backend.visual_reply_auto_show_checkbox = QtWidgets.QCheckBox("Auto-show Visual Reply dock")
    backend.visual_reply_auto_show_checkbox.setObjectName("visual_reply_auto_show_checkbox")
    backend.visual_reply_auto_show_checkbox.setChecked(bool(runtime.get("visual_reply_auto_show_dock", True)))
    backend.visual_reply_auto_show_checkbox.toggled.connect(lambda checked: on_visual_reply_auto_show_changed(backend, checked))


def build_legacy_settings_tab(backend):
    """Build the Visual Reply settings tab owned by the Visual Reply addon."""
    if QtCore is None or QtWidgets is None:
        return None
    if not _legacy_runtime_widgets_alive(backend):
        build_legacy_runtime_widgets(backend, QtRuntimeConfigService(backend).snapshot())
    tab = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(tab)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(10)

    visual_box = QtWidgets.QGroupBox("Visual Replies")
    visual_layout = QtWidgets.QVBoxLayout(visual_box)
    visual_layout.setContentsMargins(12, 14, 12, 12)
    visual_layout.setSpacing(8)

    visual_form = QtWidgets.QGridLayout()
    visual_form.setContentsMargins(0, 0, 0, 0)
    visual_form.setHorizontalSpacing(12)
    visual_form.setVerticalSpacing(8)
    visual_form.addWidget(QtWidgets.QLabel("Mode"), 0, 0, QtCore.Qt.AlignVCenter)
    visual_form.addWidget(backend.visual_reply_mode_combo, 0, 1)
    visual_form.addWidget(QtWidgets.QLabel("Provider"), 0, 2, QtCore.Qt.AlignVCenter)
    visual_form.addWidget(backend.visual_reply_provider_combo, 0, 3)
    visual_form.addWidget(QtWidgets.QLabel("Image Size"), 1, 0, QtCore.Qt.AlignVCenter)
    visual_form.addWidget(backend.visual_reply_size_combo, 1, 1)
    backend.visual_reply_model_label = QtWidgets.QLabel("Image Model")
    backend.visual_reply_model_label.setObjectName("visual_reply_model_label")
    visual_form.addWidget(backend.visual_reply_model_label, 1, 2, QtCore.Qt.AlignVCenter)
    visual_form.addWidget(backend.visual_reply_model_edit, 1, 3)
    backend.visual_reply_api_key_label = QtWidgets.QLabel("API Key")
    backend.visual_reply_api_key_label.setObjectName("visual_reply_api_key_label")
    visual_form.addWidget(backend.visual_reply_api_key_label, 2, 0, QtCore.Qt.AlignVCenter)
    visual_form.addWidget(backend.visual_reply_api_key_edit, 2, 1, 1, 3)
    backend.visual_reply_comfyui_cleanup_label = QtWidgets.QLabel("ComfyUI Cleanup")
    backend.visual_reply_comfyui_cleanup_label.setObjectName("visual_reply_comfyui_cleanup_label")
    visual_form.addWidget(backend.visual_reply_comfyui_cleanup_label, 3, 0, QtCore.Qt.AlignVCenter)
    visual_form.addWidget(backend.visual_reply_comfyui_cleanup_combo, 3, 1, 1, 3)
    visual_form.setColumnStretch(1, 1)
    visual_form.setColumnStretch(3, 1)
    visual_layout.addLayout(visual_form)
    visual_layout.addWidget(backend.visual_reply_auto_show_checkbox)

    backend.visual_reply_hint = QtWidgets.QLabel()
    backend.visual_reply_hint.setObjectName("visual_reply_hint")
    backend.visual_reply_hint.setWordWrap(True)
    backend.visual_reply_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
    visual_layout.addWidget(backend.visual_reply_hint)
    current_provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    sync_visual_reply_comfyui_cleanup_field(backend, current_provider)
    refresh_visual_reply_hint(backend)

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
    state_module=None,
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
        state_module=state_module or visual_reply_state,
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
    mode = visual_reply_mode_value_from_label(backend._live_combo_text("visual_reply_mode_combo", "Auto"))
    provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
    default_model = visual_reply_default_model_for_provider(provider)
    return {
        "visual_reply_mode": mode,
        "visual_reply_provider": provider,
        "visual_reply_size": normalize_visual_reply_size(
            backend._live_combo_text("visual_reply_size_combo", visual_reply_size_for_provider(backend, provider))
        ),
        "visual_reply_model": backend._live_text("visual_reply_model_edit", visual_reply_model_for_provider(backend, provider)).strip()
        or default_model,
        "visual_reply_visible": bool(
            backend._visual_reply_addon_enabled()
            and hasattr(backend, "visual_reply_dock")
            and backend.visual_reply_dock.isVisible()
        ),
    }


def apply_runtime_settings(backend, settings):
    """Apply Visual Reply-owned settings from dry-run/profile payloads."""
    payload = dict(settings or {})
    if "visual_reply_provider_settings" in payload:
        QtRuntimeConfigService(backend).update("visual_reply_provider_settings", provider_settings_from_config(payload))
    widget = backend._live_widget_attr("visual_reply_mode_combo")
    if "visual_reply_mode" in payload and widget is not None:
        mode_text = visual_reply_mode_label_from_value(payload["visual_reply_mode"])
        widget.setCurrentText(mode_text)
        on_visual_reply_mode_changed(backend, mode_text)
    widget = backend._live_widget_attr("visual_reply_provider_combo")
    if "visual_reply_provider" in payload and widget is not None:
        provider_text = visual_reply_provider_label_from_value(payload["visual_reply_provider"])
        widget.setCurrentText(provider_text)
        on_visual_reply_provider_changed(backend, provider_text)
    widget = backend._live_widget_attr("visual_reply_size_combo")
    if "visual_reply_size" in payload and widget is not None:
        size_text = normalize_visual_reply_size(payload["visual_reply_size"])
        widget.setCurrentText(visual_reply_size_label_from_value(size_text))
        on_visual_reply_size_changed(backend, size_text)
    widget = backend._live_widget_attr("visual_reply_model_edit")
    if "visual_reply_model" in payload and widget is not None:
        provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
        default_model = visual_reply_default_model_for_provider(provider)
        widget.setText(str(payload["visual_reply_model"] or default_model))
        on_visual_reply_model_changed(backend)
    if "visual_reply_provider_settings" in payload:
        provider = visual_reply_provider_value_from_label(backend._live_combo_text("visual_reply_provider_combo", "OpenAI"))
        sync_visual_reply_size_field(backend, provider)
        sync_visual_reply_model_field(backend, provider)
        sync_visual_reply_api_key_field(backend, provider)
        sync_visual_reply_comfyui_cleanup_field(backend, provider)
        refresh_visual_reply_hint(backend)
    widget = backend._live_widget_attr("visual_reply_auto_show_checkbox")
    if "visual_reply_auto_show_dock" in payload and widget is not None:
        auto_show = bool(payload["visual_reply_auto_show_dock"])
        widget.setChecked(auto_show)
        on_visual_reply_auto_show_changed(backend, auto_show)


def bind_show_button(bridge):
    show_button = bridge._ui_object("btn_visual_reply")
    if show_button is not None and hasattr(show_button, "clicked"):
        show_button.clicked.connect(lambda: show_dock(bridge))


def sync_combo_action(bridge, object_name, callback_name):
    bridge._sync_single_combo_to_backend(object_name)
    widget = bridge._ui_object(object_name)
    if widget is not None and hasattr(widget, "currentText"):
        choice = str(widget.currentText() or "")
        if callback_name == "on_visual_reply_mode_changed":
            on_visual_reply_mode_changed(bridge.backend, choice)
        elif callback_name == "on_visual_reply_provider_changed":
            on_visual_reply_provider_changed(bridge.backend, choice)
        elif callback_name == "on_visual_reply_size_changed":
            on_visual_reply_size_changed(bridge.backend, choice)
        elif callback_name == "on_visual_reply_comfyui_cleanup_changed":
            on_visual_reply_comfyui_cleanup_changed(bridge.backend, choice)
    bridge._refresh_musetalk_visual_runtime_frontend()


def sync_model_action(bridge):
    bridge._sync_single_line_edit_to_backend("visual_reply_model_edit")
    on_visual_reply_model_changed(bridge.backend)
    bridge._refresh_profile_utility_runtime_frontend()


def sync_api_key_action(bridge):
    bridge._sync_single_line_edit_to_backend("visual_reply_api_key_edit")
    on_visual_reply_api_key_changed(bridge.backend)
    bridge._refresh_profile_utility_runtime_frontend()


def sync_auto_show_action(bridge):
    bridge._sync_single_checkbox_to_backend("visual_reply_auto_show_checkbox")
    widget = bridge._ui_object("visual_reply_auto_show_checkbox")
    if widget is not None and hasattr(widget, "isChecked"):
        on_visual_reply_auto_show_changed(bridge.backend, bool(widget.isChecked()))
    bridge._refresh_musetalk_visual_runtime_frontend()


def bind_runtime_controls(bridge):
    """Wire Visual Reply-owned runtime controls from main.ui to Visual Reply callbacks."""
    combo_bindings = {
        "visual_reply_mode_combo": "on_visual_reply_mode_changed",
        "visual_reply_provider_combo": "on_visual_reply_provider_changed",
        "visual_reply_size_combo": "on_visual_reply_size_changed",
        "visual_reply_comfyui_cleanup_combo": "on_visual_reply_comfyui_cleanup_changed",
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
    api_key_edit = bridge._ui_object("visual_reply_api_key_edit")
    if api_key_edit is not None and hasattr(api_key_edit, "editingFinished"):
        api_key_edit.editingFinished.connect(lambda: sync_api_key_action(bridge))

    auto_show = bridge._ui_object("visual_reply_auto_show_checkbox")
    if auto_show is not None and hasattr(auto_show, "toggled"):
        auto_show.toggled.connect(lambda _checked=False: sync_auto_show_action(bridge))
