import subprocess
from pathlib import Path

from PySide6 import QtWidgets

from core.addons.qt_host_services import QtRuntimeConfigService


DEFAULT_LOCAL_VAM_ROOT = ""
DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER = "VaM (Desktop Mode).bat"
DEFAULT_LOCAL_VAM_VR_LAUNCHER = "VaM (OpenVR).bat"


def _runtime_config_service(backend):
    return QtRuntimeConfigService(backend)


def _runtime_config(backend):
    return _runtime_config_service(backend).snapshot()


def _update_runtime_config(backend, key, value):
    return _runtime_config_service(backend).update(key, value)


def _engine_attr(backend, name: str, default=None):
    return _runtime_config_service(backend).engine_attr(name, default)


class BackendVamRuntimeMixin:
    """Host-facing VaM bridge settings and launcher helpers."""

    def on_vam_vmc_enabled_changed(self, enabled):
        _update_runtime_config(self, "vam_vmc_enabled", bool(enabled))
        self.save_session()

    def on_vam_bridge_enabled_changed(self, enabled):
        _update_runtime_config(self, "vam_bridge_enabled", bool(enabled))
        self.save_session()

    def on_vam_play_audio_in_vam_changed(self, enabled):
        _update_runtime_config(self, "vam_play_audio_in_vam", bool(enabled))
        self.save_session()

    def on_vam_timeline_auto_resume_changed(self, enabled):
        _update_runtime_config(self, "vam_timeline_auto_resume", bool(enabled))
        self.save_session()

    def on_vam_vmc_host_changed(self):
        _update_runtime_config(self, "vam_vmc_host", self._live_text("vam_vmc_host_edit", _runtime_config(self).get("vam_vmc_host", "127.0.0.1")).strip() or "127.0.0.1")
        self.save_session()

    def on_vam_vmc_port_changed(self, value):
        _update_runtime_config(self, "vam_vmc_port", int(value))
        self.save_session()

    def _current_vam_root_value(self):
        normalize_vam_root = _engine_attr(self, "normalize_vam_root", lambda value: str(value or "").strip())
        default_vam_root = _engine_attr(self, "DEFAULT_VAM_ROOT", "")
        raw = self._live_text(
            "vam_root_edit",
            _runtime_config(self).get("vam_root", default_vam_root) or default_vam_root,
        ).strip()
        return normalize_vam_root(raw)

    def _current_vam_bridge_root_value(self):
        derive_vam_bridge_root = _engine_attr(self, "derive_vam_bridge_root", lambda value: str(value or "").strip())
        return derive_vam_bridge_root(self._current_vam_root_value())

    def _refresh_vam_path_widgets(self):
        root_edit = self._live_widget_attr("vam_root_edit")
        if root_edit is not None:
            root_edit.setText(self._current_vam_root_value())
        bridge_edit = self._live_widget_attr("vam_bridge_root_edit")
        if bridge_edit is not None:
            bridge_edit.setText(self._current_vam_bridge_root_value())

    def _ensure_vam_root_for_launch(self):
        current_root = self._current_vam_root_value()
        if str(current_root or "").strip():
            return current_root
        normalize_vam_root = _engine_attr(self, "normalize_vam_root", lambda value: str(value or "").strip())
        fallback_root = normalize_vam_root(DEFAULT_LOCAL_VAM_ROOT)
        root_edit = self._live_widget_attr("vam_root_edit")
        if root_edit is not None:
            root_edit.setText(fallback_root)
        self.on_vam_root_changed()
        return fallback_root

    def on_vam_root_changed(self):
        derive_vam_bridge_root = _engine_attr(self, "derive_vam_bridge_root", lambda value: str(value or "").strip())
        normalized_root = self._current_vam_root_value()
        derived_bridge_root = derive_vam_bridge_root(normalized_root)
        root_edit = self._live_widget_attr("vam_root_edit")
        if root_edit is not None:
            root_edit.setText(normalized_root)
        bridge_edit = self._live_widget_attr("vam_bridge_root_edit")
        if bridge_edit is not None:
            bridge_edit.setText(derived_bridge_root)
        _update_runtime_config(self, "vam_root", normalized_root)
        _update_runtime_config(self, "vam_bridge_root", derived_bridge_root)
        self.save_session()

    def on_vam_bridge_root_changed(self):
        self.on_vam_root_changed()

    def _launch_vam_target(self, launch_name, title):
        vam_root = self._ensure_vam_root_for_launch()
        target_path = Path(vam_root) / str(launch_name or "").strip()
        if not target_path.exists():
            QtWidgets.QMessageBox.warning(
                self,
                title,
                f"Could not find {launch_name} at:\n{target_path}",
            )
            return
        try:
            if target_path.suffix.lower() == ".bat":
                subprocess.Popen(["cmd", "/c", str(target_path)], cwd=str(target_path.parent))
            else:
                subprocess.Popen([str(target_path)], cwd=str(target_path.parent))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                title,
                f"Failed to launch {launch_name}.\n\n{exc}",
            )

    def on_start_vam_desktop_clicked(self):
        self._launch_vam_target(DEFAULT_LOCAL_VAM_DESKTOP_LAUNCHER, "Start VaM Desktop")

    def on_start_vam_vr_clicked(self):
        self._launch_vam_target(DEFAULT_LOCAL_VAM_VR_LAUNCHER, "Start VaM VR")

    def on_vam_target_atom_uid_changed(self):
        _update_runtime_config(self, "vam_target_atom_uid", self._live_text("vam_target_atom_uid_edit", _runtime_config(self).get("vam_target_atom_uid", "Person")).strip() or "Person")
        self.save_session()

    def on_vam_target_storable_id_changed(self):
        _update_runtime_config(self, "vam_target_storable_id", self._live_text("vam_target_storable_id_edit", _runtime_config(self).get("vam_target_storable_id", "")).strip())
        self.save_session()
