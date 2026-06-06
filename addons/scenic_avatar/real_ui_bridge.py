from __future__ import annotations

from PySide6 import QtWidgets

from addons.scenic_avatar import pack_runtime


SCENIC_PACK_TOOLTIP = "Portable Scenic Pack used by the Scenic avatar engine to map tags to still images."
SCENIC_PACK_REFRESH_TOOLTIP = "Rescan ScenicPacks/ for portable Scenic Pack folders."


def _runtime_config(backend):
    runtime_service = getattr(backend, "_runtime_config_service", None)
    if runtime_service is not None and hasattr(runtime_service, "snapshot"):
        return runtime_service.snapshot()
    from ui.runtime.engine_access import engine_module

    return dict(getattr(engine_module(), "RUNTIME_CONFIG", {}) or {})


def _update_runtime_config(backend, key, value):
    runtime_service = getattr(backend, "_runtime_config_service", None)
    if runtime_service is not None and hasattr(runtime_service, "update"):
        return runtime_service.update(key, value)
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


def _invalidate_emotion_names(backend):
    runtime_service = getattr(backend, "_runtime_config_service", None)
    invalidate = None
    if runtime_service is not None and hasattr(runtime_service, "engine_attr"):
        invalidate = runtime_service.engine_attr("invalidate_available_emotion_names", None)
    if not callable(invalidate):
        try:
            from ui.runtime.engine_access import engine_module

            invalidate = getattr(engine_module(), "invalidate_available_emotion_names", None)
        except Exception:
            invalidate = None
    if callable(invalidate):
        invalidate()


def _combo_data(combo, default=""):
    if combo is None:
        return default
    try:
        data = combo.currentData()
        if data is not None:
            return data
    except Exception:
        pass
    try:
        return combo.currentText()
    except Exception:
        return default


def collect_runtime_config(backend, runtime_config=None):
    runtime = dict(runtime_config or _runtime_config(backend) or {})
    combo = getattr(backend, "scenic_pack_combo", None)
    return {
        "scenic_pack_id": str(_combo_data(combo, runtime.get("scenic_pack_id", "")) or "").strip(),
    }


def update_config_from_widgets(backend, runtime_config=None):
    for key, value in collect_runtime_config(backend, runtime_config).items():
        _update_runtime_config(backend, key, value)
    _invalidate_emotion_names(backend)
    return True


def refresh_resource_widgets(backend, runtime_config=None):
    selected = str((runtime_config or _runtime_config(backend) or {}).get("scenic_pack_id", "") or "").strip()
    refresh_scenic_pack_list(backend, selected_pack_id=selected)
    return True


def build_legacy_runtime_widgets(backend, runtime_config=None):
    from ui.widgets.basic import NoWheelComboBox

    runtime = dict(runtime_config or {})
    backend.scenic_pack_combo = NoWheelComboBox()
    backend.scenic_pack_combo.setObjectName("scenic_pack_combo")
    backend.scenic_pack_combo.setToolTip(SCENIC_PACK_TOOLTIP)
    backend.scenic_pack_combo.currentTextChanged.connect(lambda _choice="": apply_scenic_pack_change(backend))

    backend.btn_scenic_pack_refresh = QtWidgets.QPushButton("Refresh")
    backend.btn_scenic_pack_refresh.setObjectName("btn_scenic_pack_refresh")
    backend.btn_scenic_pack_refresh.setToolTip(SCENIC_PACK_REFRESH_TOOLTIP)
    backend.btn_scenic_pack_refresh.clicked.connect(lambda _checked=False: refresh_scenic_pack_list(backend))

    pack_row = QtWidgets.QHBoxLayout()
    pack_row.setContentsMargins(0, 0, 0, 0)
    pack_row.setSpacing(8)
    pack_row.addWidget(backend.scenic_pack_combo, 1)
    pack_row.addWidget(backend.btn_scenic_pack_refresh, 0)
    pack_row_widget = QtWidgets.QWidget()
    pack_row_widget.setLayout(pack_row)
    backend.scenic_pack_row_widget = pack_row_widget
    refresh_scenic_pack_list(backend, selected_pack_id=runtime.get("scenic_pack_id", ""))
    return True


def refresh_scenic_pack_list(backend, selected_pack_id=None):
    combo = getattr(backend, "scenic_pack_combo", None)
    if combo is None:
        return False
    runtime = _runtime_config(backend)
    requested = str(selected_pack_id or _combo_data(combo, "") or runtime.get("scenic_pack_id", "") or "").strip()
    packs = pack_runtime.discover_packs()
    combo.blockSignals(True)
    try:
        combo.clear()
        for pack_id, pack in packs.items():
            image_count = len(pack.images)
            suffix = "image" if image_count == 1 else "images"
            combo.addItem(f"{pack.pack_name} | {image_count} {suffix}", pack_id)
        if combo.count() <= 0:
            combo.addItem("No Scenic Packs found", "")
        index = combo.findData(requested)
        if index < 0:
            index = 0
        combo.setCurrentIndex(index)
    finally:
        combo.blockSignals(False)
    return True


def apply_scenic_pack_change(backend):
    pack_id = str(_combo_data(getattr(backend, "scenic_pack_combo", None), "") or "").strip()
    _update_runtime_config(backend, "scenic_pack_id", pack_id)
    _invalidate_emotion_names(backend)
    if hasattr(backend, "emit_tutorial_event"):
        backend.emit_tutorial_event("ui_changed", {"field": "scenic_pack_id", "value": pack_id})
    if hasattr(backend, "save_session"):
        backend.save_session()
    return True


def set_provider_controls_enabled(backend, enabled):
    for name in ("scenic_pack_combo", "btn_scenic_pack_refresh", "scenic_pack_row_widget"):
        widget = getattr(backend, name, None)
        if widget is not None and hasattr(widget, "setEnabled"):
            widget.setEnabled(bool(enabled))
    return True


def sync_scenic_pack(bridge):
    bridge._sync_single_combo_to_backend("scenic_pack_combo")
    apply_scenic_pack_change(bridge.backend)


def refresh_scenic_packs(bridge):
    try:
        refresh_scenic_pack_list(bridge.backend)
    finally:
        try:
            from PySide6 import QtCore

            QtCore.QTimer.singleShot(0, lambda: bridge._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: bridge._sync_backend_to_ui(force=True))
        except Exception:
            pass


def bind_runtime_controls(bridge):
    combo = bridge._ui_object("scenic_pack_combo")
    if combo is not None and hasattr(combo, "currentIndexChanged"):
        combo.currentIndexChanged.connect(lambda _index=0: sync_scenic_pack(bridge))

    refresh_button = bridge._ui_object("btn_scenic_pack_refresh")
    if refresh_button is not None and hasattr(refresh_button, "clicked"):
        refresh_button.clicked.connect(lambda _checked=False: refresh_scenic_packs(bridge))
    return True
