"""RealUiActionsAvatarMixin extracted from real_ui_actions.py."""

from PySide6 import QtCore


def configure_real_ui_actions_avatar_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsAvatarMixin:
    def _on_frontend_voice_changed(self, _index=None):
            self._sync_single_combo_to_backend("voice_combo")
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_body_selection_changed(self, _index=None):
            self._sync_single_combo_to_backend("body_combo")
            callback = getattr(self.backend, "load_body_config_from_combo", None)
            if callable(callback):
                callback()
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_emotion_changed(self, _index=None):
            self._sync_single_combo_to_backend("emotion_combo")
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_live_sync_changed(self, _checked):
            self._sync_single_checkbox_to_backend("live_sync_checkbox")
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_body_pose_slider_changed(self, key, raw_value):
            value = _ui_shell_body_slider_raw_to_value(key, raw_value)
            backend_slider = getattr(self.backend, "pose_sliders", {}).get(str(key))
            if backend_slider is not None and hasattr(backend_slider, "set_value"):
                try:
                    backend_slider.set_value(value)
                except Exception:
                    pass
            callback = getattr(self.backend, "update_pose_value", None)
            if callable(callback):
                callback(str(key), value)
            _ui_shell_update_body_label(self.window, str(key), value)

    def _on_frontend_vam_vmc_enabled_changed(self, _checked):
            self._sync_single_checkbox_to_backend("vam_vmc_enabled_checkbox")
            callback = getattr(self.backend, "on_vam_vmc_enabled_changed", None)
            widget = self._ui_object("vam_vmc_enabled_checkbox")
            if callable(callback) and widget is not None and hasattr(widget, "isChecked"):
                callback(bool(widget.isChecked()))
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_bridge_enabled_changed(self, _checked):
            self._sync_single_checkbox_to_backend("vam_bridge_enabled_checkbox")
            callback = getattr(self.backend, "on_vam_bridge_enabled_changed", None)
            widget = self._ui_object("vam_bridge_enabled_checkbox")
            if callable(callback) and widget is not None and hasattr(widget, "isChecked"):
                callback(bool(widget.isChecked()))
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_play_audio_changed(self, _checked):
            self._sync_single_checkbox_to_backend("vam_play_audio_in_vam_checkbox")
            callback = getattr(self.backend, "on_vam_play_audio_in_vam_changed", None)
            widget = self._ui_object("vam_play_audio_in_vam_checkbox")
            if callable(callback) and widget is not None and hasattr(widget, "isChecked"):
                callback(bool(widget.isChecked()))
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_timeline_auto_resume_changed(self, _checked):
            self._sync_single_checkbox_to_backend("vam_timeline_auto_resume_checkbox")
            callback = getattr(self.backend, "on_vam_timeline_auto_resume_changed", None)
            widget = self._ui_object("vam_timeline_auto_resume_checkbox")
            if callable(callback) and widget is not None and hasattr(widget, "isChecked"):
                callback(bool(widget.isChecked()))
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_vmc_port_changed(self, _value):
            self._sync_single_spin_to_backend("vam_vmc_port_spin")
            callback = getattr(self.backend, "on_vam_vmc_port_changed", None)
            widget = self._ui_object("vam_vmc_port_spin")
            if callable(callback) and widget is not None and hasattr(widget, "value"):
                callback(int(widget.value()))
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_root_changed(self):
            self._sync_single_line_edit_to_backend("vam_root_edit")
            callback = getattr(self.backend, "on_vam_root_changed", None)
            if callable(callback):
                callback()
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_target_atom_uid_changed(self):
            self._sync_single_line_edit_to_backend("vam_target_atom_uid_edit")
            callback = getattr(self.backend, "on_vam_target_atom_uid_changed", None)
            if callable(callback):
                callback()
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_target_storable_id_changed(self):
            self._sync_single_line_edit_to_backend("vam_target_storable_id_edit")
            callback = getattr(self.backend, "on_vam_target_storable_id_changed", None)
            if callable(callback):
                callback()
            self._refresh_avatar_body_vam_runtime_frontend()

    def _on_frontend_vam_vmc_host_changed(self):
            self._sync_single_line_edit_to_backend("vam_vmc_host_edit")
            callback = getattr(self.backend, "on_vam_vmc_host_changed", None)
            if callable(callback):
                callback()
            self._refresh_avatar_body_vam_runtime_frontend()

    def _load_body_config_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "load_body_config_from_combo", None)
            if callable(callback):
                callback()

    def _save_current_body_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "save_current_body", None)
            if callable(callback):
                callback()

    def _save_body_dialog_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "save_body_dialog", None)
            if callable(callback):
                callback()

    def _delete_current_body_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "delete_current_body", None)
            if callable(callback):
                callback()

    def _open_hand_debugger_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "open_hand_debugger", None)
            if callable(callback):
                callback()

    def _enter_vseeface_focus_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "enter_external_avatar_focus", None)
            if callable(callback):
                callback("VSeeFace")

    def _start_vam_desktop_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "on_start_vam_desktop_clicked", None)
            if callable(callback):
                callback()

    def _start_vam_vr_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "on_start_vam_vr_clicked", None)
            if callable(callback):
                callback()

    def _enter_vam_focus_from_ui_real(self):
            self._sync_frontend_to_backend()
            callback = getattr(self.backend, "enter_external_avatar_focus", None)
            if callable(callback):
                callback("VaM")
