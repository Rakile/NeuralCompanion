"""RealUiActionsAvatarMixin extracted from real_ui_actions.py."""

from PySide6 import QtCore

from addons.vam_avatar import real_ui_bridge as vam_real_ui_bridge


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
            vam_real_ui_bridge.sync_checkbox_action(self, "vam_vmc_enabled_checkbox", "on_vam_vmc_enabled_changed")

    def _on_frontend_vam_bridge_enabled_changed(self, _checked):
            vam_real_ui_bridge.sync_checkbox_action(self, "vam_bridge_enabled_checkbox", "on_vam_bridge_enabled_changed")

    def _on_frontend_vam_play_audio_changed(self, _checked):
            vam_real_ui_bridge.sync_checkbox_action(self, "vam_play_audio_in_vam_checkbox", "on_vam_play_audio_in_vam_changed")

    def _on_frontend_vam_timeline_auto_resume_changed(self, _checked):
            vam_real_ui_bridge.sync_checkbox_action(self, "vam_timeline_auto_resume_checkbox", "on_vam_timeline_auto_resume_changed")

    def _on_frontend_vam_vmc_port_changed(self, _value):
            vam_real_ui_bridge.sync_spin_action(self, "vam_vmc_port_spin", "on_vam_vmc_port_changed")

    def _on_frontend_vam_root_changed(self):
            vam_real_ui_bridge.sync_line_action(self, "vam_root_edit", "on_vam_root_changed")

    def _on_frontend_vam_target_atom_uid_changed(self):
            vam_real_ui_bridge.sync_line_action(self, "vam_target_atom_uid_edit", "on_vam_target_atom_uid_changed")

    def _on_frontend_vam_target_storable_id_changed(self):
            vam_real_ui_bridge.sync_line_action(self, "vam_target_storable_id_edit", "on_vam_target_storable_id_changed")

    def _on_frontend_vam_vmc_host_changed(self):
            vam_real_ui_bridge.sync_line_action(self, "vam_vmc_host_edit", "on_vam_vmc_host_changed")

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
            vam_real_ui_bridge.start_desktop(self)

    def _start_vam_vr_from_ui_real(self):
            vam_real_ui_bridge.start_vr(self)

    def _enter_vam_focus_from_ui_real(self):
            vam_real_ui_bridge.enter_focus(self)
