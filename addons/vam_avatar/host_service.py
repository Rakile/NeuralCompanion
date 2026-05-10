from __future__ import annotations

from core.addons.qt_host_services import QtRuntimeConfigService


class QtVamAvatarService:
    _STATE_KEYS = (
        "vam_root",
        "vam_bridge_root",
        "vam_target_atom_uid",
        "vam_target_storable_id",
        "vam_vmc_host",
        "vam_vmc_port",
        "vam_vmc_enabled",
        "vam_bridge_enabled",
        "vam_play_audio_in_vam",
        "vam_timeline_auto_resume",
    )

    def __init__(self, window):
        self._window = window
        self._runtime_config = QtRuntimeConfigService(window)

    def _checkbox(self, name: str):
        return getattr(self._window, str(name), None)

    def _line_edit(self, name: str):
        return getattr(self._window, str(name), None)

    def _checked(self, name: str, default: bool = False) -> bool:
        widget = self._checkbox(name)
        if widget is not None and hasattr(widget, "isChecked"):
            try:
                return bool(widget.isChecked())
            except Exception:
                pass
        return bool(default)

    def _line_value(self, name: str, default: str = "") -> str:
        widget = self._line_edit(name)
        if widget is not None and hasattr(widget, "text"):
            try:
                return str(widget.text() or "").strip()
            except Exception:
                pass
        return str(default or "").strip()

    def snapshot(self):
        return {
            "vam_root": self._line_value("vam_root_edit"),
            "vam_bridge_root": self._line_value("vam_bridge_root_edit"),
            "vam_target_atom_uid": self._line_value("vam_target_atom_uid_edit", "Person"),
            "vam_target_storable_id": self._line_value("vam_target_storable_id_edit"),
            "vam_vmc_host": self._line_value("vam_vmc_host_edit", "127.0.0.1"),
            "vam_vmc_port": int(getattr(self._window, "vam_vmc_port_spin", None).value())
            if hasattr(getattr(self._window, "vam_vmc_port_spin", None), "value")
            else 39539,
            "vam_vmc_enabled": self._checked("vam_vmc_enabled_checkbox", True),
            "vam_bridge_enabled": self._checked("vam_bridge_enabled_checkbox", True),
            "vam_play_audio_in_vam": self._checked("vam_play_audio_in_vam_checkbox", False),
            "vam_timeline_auto_resume": self._checked("vam_timeline_auto_resume_checkbox", True),
        }

    def export_vam_settings(self):
        return dict(self.snapshot() or {})

    def _set_line_text_quietly(self, name: str, text: str):
        widget = self._line_edit(name)
        if widget is None or not hasattr(widget, "setText"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_checkbox_quietly(self, name: str, checked: bool):
        widget = self._checkbox(name)
        if widget is None or not hasattr(widget, "setChecked"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setChecked(bool(checked))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_spin_value_quietly(self, name: str, value: int):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setValue"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setValue(int(value))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def import_vam_settings(self, payload):
        data = dict(payload or {})
        if not any(key in data for key in self._STATE_KEYS):
            return None

        raw_root = data.get("vam_root") or data.get("vam_bridge_root") or self._runtime_config.engine_attr("DEFAULT_VAM_ROOT", "")
        normalize_vam_root = self._runtime_config.engine_attr("normalize_vam_root", lambda value: str(value or "").strip())
        derive_vam_bridge_root = self._runtime_config.engine_attr("derive_vam_bridge_root", lambda value: str(value or "").strip())
        normalized_root = normalize_vam_root(raw_root)
        bridge_root = derive_vam_bridge_root(normalized_root)
        state = {
            "vam_root": normalized_root,
            "vam_bridge_root": bridge_root,
            "vam_target_atom_uid": str(data.get("vam_target_atom_uid", "Person") or "Person").strip() or "Person",
            "vam_target_storable_id": str(data.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge").strip(),
            "vam_vmc_host": str(data.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1",
            "vam_vmc_port": int(data.get("vam_vmc_port", 39539) or 39539),
            "vam_vmc_enabled": bool(data.get("vam_vmc_enabled", True)),
            "vam_bridge_enabled": bool(data.get("vam_bridge_enabled", True)),
            "vam_play_audio_in_vam": bool(data.get("vam_play_audio_in_vam", False)),
            "vam_timeline_auto_resume": bool(data.get("vam_timeline_auto_resume", True)),
        }
        for key, value in state.items():
            self._runtime_config.update(key, value)

        self._set_line_text_quietly("vam_root_edit", state["vam_root"])
        self._set_line_text_quietly("vam_bridge_root_edit", state["vam_bridge_root"])
        self._set_line_text_quietly("vam_target_atom_uid_edit", state["vam_target_atom_uid"])
        self._set_line_text_quietly("vam_target_storable_id_edit", state["vam_target_storable_id"])
        self._set_line_text_quietly("vam_vmc_host_edit", state["vam_vmc_host"])
        self._set_spin_value_quietly("vam_vmc_port_spin", state["vam_vmc_port"])
        self._set_checkbox_quietly("vam_vmc_enabled_checkbox", state["vam_vmc_enabled"])
        self._set_checkbox_quietly("vam_bridge_enabled_checkbox", state["vam_bridge_enabled"])
        self._set_checkbox_quietly("vam_play_audio_in_vam_checkbox", state["vam_play_audio_in_vam"])
        self._set_checkbox_quietly("vam_timeline_auto_resume_checkbox", state["vam_timeline_auto_resume"])
        return None

    def launch_vam(self, target: str = "desktop"):
        mode = str(target or "desktop").strip().lower()
        if mode == "vr":
            launch = getattr(self._window, "on_start_vam_vr_clicked", None)
        else:
            launch = getattr(self._window, "on_start_vam_desktop_clicked", None)
        if callable(launch):
            launch()
        return self.snapshot()

    def open_external_avatar_view(self):
        handler = getattr(self._window, "enter_external_avatar_focus", None)
        if callable(handler):
            handler("VaM")
        return self.snapshot()
