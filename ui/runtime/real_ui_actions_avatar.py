"""RealUiActionsAvatarMixin extracted from real_ui_actions.py."""


def configure_real_ui_actions_avatar_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsAvatarMixin:
    def _refresh_frontend_voice_list(self):
            current = ""
            combo = self._ui_object("voice_combo")
            if combo is not None and hasattr(combo, "currentText"):
                current = str(combo.currentText() or "").strip()
            callback = getattr(self.backend, "refresh_voice_list", None)
            if callable(callback):
                callback(current)
            self._mirror_persona_runtime_widgets(force=True)
            self._refresh_avatar_body_vam_runtime_frontend()

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
