try:
    from PySide6 import QtWidgets
except Exception:  # pragma: no cover - shell smoke may inspect without Qt available.
    QtWidgets = None

from core.addons.qt_host_services import QtRuntimeConfigService


DEFAULT_LOCAL_VAM_ROOT = ""


def _runtime_config_service(backend):
    return QtRuntimeConfigService(backend)


def _engine_attr(backend, name: str, default=None):
    return _runtime_config_service(backend).engine_attr(name, default)


def _update_runtime_config(backend, key, value):
    return _runtime_config_service(backend).update(key, value)


def collect_runtime_config(backend, runtime_config=None, *, avatar_mode=""):
    """Collect VaM-owned runtime config from the current backend widgets."""
    runtime = dict(runtime_config or {})
    mode = str(avatar_mode or "").strip().lower()
    return {
        "vam_vmc_enabled": backend._live_checked("vam_vmc_enabled_checkbox", runtime.get("vam_vmc_enabled", True)),
        "vam_vmc_host": backend._live_text("vam_vmc_host_edit", runtime.get("vam_vmc_host", "127.0.0.1")).strip() or "127.0.0.1",
        "vam_vmc_port": int(backend._live_value("vam_vmc_port_spin", runtime.get("vam_vmc_port", 39539) or 39539)),
        "vam_bridge_enabled": backend._live_checked("vam_bridge_enabled_checkbox", runtime.get("vam_bridge_enabled", True)),
        "vam_root": backend._current_vam_root_value(),
        "vam_bridge_root": backend._current_vam_bridge_root_value(),
        "vam_play_audio_in_vam": True if mode == "vam" else backend._live_checked(
            "vam_play_audio_in_vam_checkbox",
            runtime.get("vam_play_audio_in_vam", False),
        ),
        "vam_target_atom_uid": backend._live_text("vam_target_atom_uid_edit", runtime.get("vam_target_atom_uid", "Person")).strip() or "Person",
        "vam_target_storable_id": backend._live_text(
            "vam_target_storable_id_edit",
            runtime.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge"),
        ).strip(),
        "vam_timeline_auto_resume": backend._live_checked(
            "vam_timeline_auto_resume_checkbox",
            runtime.get("vam_timeline_auto_resume", True),
        ),
    }


def estimated_runtime_overhead_gib():
    return 1.0


def build_legacy_runtime_widgets(backend, runtime_config=None):
    """Build VaM-owned controls used by the backend shell."""
    if QtWidgets is None:
        return
    from ui.widgets.basic import NoWheelSpinBox

    runtime = dict(runtime_config or {})
    normalize_vam_root = _engine_attr(backend, "normalize_vam_root", lambda value: str(value or "").strip())
    derive_vam_bridge_root = _engine_attr(backend, "derive_vam_bridge_root", lambda value: str(value or "").strip())
    default_vam_root = _engine_attr(backend, "DEFAULT_VAM_ROOT", "")

    backend.vam_vmc_enabled_checkbox = QtWidgets.QCheckBox("Relay motion to VaM over VMC")
    backend.vam_vmc_enabled_checkbox.setObjectName("vam_vmc_enabled_checkbox")
    backend.vam_vmc_enabled_checkbox.setChecked(bool(runtime.get("vam_vmc_enabled", True)))
    backend.vam_vmc_enabled_checkbox.toggled.connect(backend.on_vam_vmc_enabled_changed)

    backend.vam_bridge_enabled_checkbox = QtWidgets.QCheckBox("Enable VaM file bridge")
    backend.vam_bridge_enabled_checkbox.setObjectName("vam_bridge_enabled_checkbox")
    backend.vam_bridge_enabled_checkbox.setChecked(bool(runtime.get("vam_bridge_enabled", True)))
    backend.vam_bridge_enabled_checkbox.toggled.connect(backend.on_vam_bridge_enabled_changed)

    backend.vam_play_audio_in_vam_checkbox = QtWidgets.QCheckBox("Play speech audio through VaM head audio")
    backend.vam_play_audio_in_vam_checkbox.setObjectName("vam_play_audio_in_vam_checkbox")
    backend.vam_play_audio_in_vam_checkbox.setChecked(bool(runtime.get("vam_play_audio_in_vam", True)))
    backend.vam_play_audio_in_vam_checkbox.toggled.connect(backend.on_vam_play_audio_in_vam_changed)

    backend.vam_timeline_auto_resume_checkbox = QtWidgets.QCheckBox("Allow VaM Timeline auto-resume hooks")
    backend.vam_timeline_auto_resume_checkbox.setObjectName("vam_timeline_auto_resume_checkbox")
    backend.vam_timeline_auto_resume_checkbox.setChecked(bool(runtime.get("vam_timeline_auto_resume", True)))
    backend.vam_timeline_auto_resume_checkbox.toggled.connect(backend.on_vam_timeline_auto_resume_changed)

    backend.vam_vmc_host_edit = QtWidgets.QLineEdit()
    backend.vam_vmc_host_edit.setObjectName("vam_vmc_host_edit")
    backend.vam_vmc_host_edit.setText(str(runtime.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"))
    backend.vam_vmc_host_edit.editingFinished.connect(backend.on_vam_vmc_host_changed)

    backend.vam_vmc_port_spin = NoWheelSpinBox()
    backend.vam_vmc_port_spin.setObjectName("vam_vmc_port_spin")
    backend.vam_vmc_port_spin.setRange(1, 65535)
    backend.vam_vmc_port_spin.setSingleStep(1)
    backend.vam_vmc_port_spin.setValue(int(runtime.get("vam_vmc_port", 39539) or 39539))
    backend.vam_vmc_port_spin.valueChanged.connect(backend.on_vam_vmc_port_changed)

    backend.vam_root_edit = QtWidgets.QLineEdit()
    backend.vam_root_edit.setObjectName("vam_root_edit")
    backend.vam_root_edit.setText(
        normalize_vam_root(
            runtime.get("vam_root", default_vam_root)
            or default_vam_root
        )
    )
    if not backend.vam_root_edit.text().strip():
        backend.vam_root_edit.setText(normalize_vam_root(DEFAULT_LOCAL_VAM_ROOT))
    backend.vam_root_edit.setToolTip("Path to the VaM installation root. NC derives the bridge folder from this.")
    backend.vam_root_edit.editingFinished.connect(backend.on_vam_root_changed)

    backend.vam_bridge_root_edit = QtWidgets.QLineEdit()
    backend.vam_bridge_root_edit.setObjectName("vam_bridge_root_edit")
    backend.vam_bridge_root_edit.setReadOnly(True)
    backend.vam_bridge_root_edit.setText(derive_vam_bridge_root(backend.vam_root_edit.text().strip()))
    backend.vam_bridge_root_edit.setToolTip(
        "Derived from the VaM Root. The plugin's default Bridge Root already matches this location inside VaM."
    )

    backend.vam_target_atom_uid_edit = QtWidgets.QLineEdit()
    backend.vam_target_atom_uid_edit.setObjectName("vam_target_atom_uid_edit")
    backend.vam_target_atom_uid_edit.setText(str(runtime.get("vam_target_atom_uid", "Person") or "Person"))
    backend.vam_target_atom_uid_edit.editingFinished.connect(backend.on_vam_target_atom_uid_changed)

    backend.vam_target_storable_id_edit = QtWidgets.QLineEdit()
    backend.vam_target_storable_id_edit.setObjectName("vam_target_storable_id_edit")
    backend.vam_target_storable_id_edit.setText(
        str(runtime.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge")
    )
    backend.vam_target_storable_id_edit.editingFinished.connect(backend.on_vam_target_storable_id_changed)


def update_runtime_config_from_widgets(backend, runtime_config=None, *, avatar_mode=""):
    for key, value in collect_runtime_config(backend, runtime_config, avatar_mode=avatar_mode).items():
        _update_runtime_config(backend, key, value)


def apply_provider_selected_defaults(backend, active):
    if not active:
        return

    widget = backend._live_widget_attr("vam_play_audio_in_vam_checkbox")
    if widget is not None and hasattr(widget, "isChecked") and hasattr(widget, "setChecked") and not widget.isChecked():
        widget.setChecked(True)
        _update_runtime_config(backend, "vam_play_audio_in_vam", True)


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


def mirror_runtime_widgets(bridge, *, force=False):
    """Mirror VaM-owned labels and derived fields into the real main.ui surface."""
    runtime_config = _runtime_config_service(bridge.backend).snapshot()
    bridge_root_front = bridge._ui_object("vam_bridge_root_edit")
    bridge_root_back = bridge._backend_widget("vam_bridge_root_edit")
    if bridge_root_front is not None and hasattr(bridge_root_front, "setReadOnly"):
        try:
            bridge_root_front.setReadOnly(True)
        except Exception:
            pass
    if bridge_root_front is not None and bridge_root_back is not None:
        if force or not getattr(bridge_root_front, "hasFocus", lambda: False)():
            bridge._copy_text_state(bridge_root_back, bridge_root_front)

    def line_text(object_name, default=""):
        widget = bridge._ui_object(object_name)
        if widget is not None and hasattr(widget, "text"):
            try:
                return str(widget.text() or "").strip()
            except Exception:
                pass
        widget = bridge._backend_widget(object_name)
        if widget is not None and hasattr(widget, "text"):
            try:
                return str(widget.text() or "").strip()
            except Exception:
                pass
        return str(default or "").strip()

    def checked_text(object_name):
        widget = bridge._ui_object(object_name)
        if widget is None or not hasattr(widget, "isChecked"):
            widget = bridge._backend_widget(object_name)
        try:
            return "on" if bool(widget.isChecked()) else "off"
        except Exception:
            return "off"

    def spin_value(object_name, default):
        widget = bridge._ui_object(object_name)
        if widget is None or not hasattr(widget, "value"):
            widget = bridge._backend_widget(object_name)
        try:
            return int(widget.value())
        except Exception:
            return int(default)

    def set_label(object_name, value):
        label = bridge._ui_object(object_name)
        if label is not None and hasattr(label, "setText"):
            try:
                label.setText(str(value))
            except Exception:
                pass

    vam_root = line_text("vam_root_edit", runtime_config.get("vam_root", ""))
    bridge_root = line_text("vam_bridge_root_edit", runtime_config.get("vam_bridge_root", ""))
    target_atom = line_text("vam_target_atom_uid_edit", runtime_config.get("vam_target_atom_uid", "Person")) or "Person"
    target_storable = line_text("vam_target_storable_id_edit", runtime_config.get("vam_target_storable_id", ""))
    vmc_host = line_text("vam_vmc_host_edit", runtime_config.get("vam_vmc_host", "127.0.0.1")) or "127.0.0.1"
    vmc_port = spin_value("vam_vmc_port_spin", runtime_config.get("vam_vmc_port", 39539))

    set_label("vam_summary_label", f"VaM target: {target_atom}" + (f" / {target_storable}" if target_storable else ""))
    set_label(
        "vam_runtime_label",
        f"VMC {checked_text('vam_vmc_enabled_checkbox')} | "
        f"File bridge {checked_text('vam_bridge_enabled_checkbox')} | "
        f"Head audio {checked_text('vam_play_audio_in_vam_checkbox')}",
    )
    set_label("vam_bridge_status_label", f"Bridge root: {bridge_root or '(derived when VaM root is set)'}")
    set_label(
        "vam_bridge_detail_label",
        f"VaM root: {vam_root or '(not set)'} | VMC: {vmc_host}:{vmc_port} | "
        f"Timeline auto-resume {checked_text('vam_timeline_auto_resume_checkbox')}",
    )
