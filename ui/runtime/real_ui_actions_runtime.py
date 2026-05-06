"""RealUiActionsRuntimeMixin extracted from real_ui_actions.py."""

from PySide6 import QtCore


def configure_real_ui_actions_runtime_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiActionsRuntimeMixin:
    def _invoke_runtime_callback(self, callback):
            try:
                callback()
            finally:
                QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
                QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _invoke_audio_story_controller(self, method_name):
            controller = self._audio_story_controller()
            if controller is None:
                return
            callback = getattr(controller, str(method_name or ""), None)
            if not callable(callback):
                return
            try:
                callback()
            finally:
                QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
                QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
                QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))

    def _invoke_provider_model_callback(self, callback):
            try:
                callback()
            finally:
                QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
                QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
                QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))

    def _prime_frontend_audio_device_controls(self):
            session = dict(_read_ui_shell_session_snapshot() or {})
            audio_devices = _ui_shell_audio_device_labels()
            combo_specs = (
                ("audio_input_device_combo", list(audio_devices.get("inputs") or ["Default Input"]), str(RUNTIME_CONFIG.get("audio_input_device", session.get("audio_input_device", "Default Input")) or "Default Input")),
                ("audio_output_device_combo", list(audio_devices.get("outputs") or ["Default Output"]), str(RUNTIME_CONFIG.get("audio_output_device", session.get("audio_output_device", "Default Output")) or "Default Output")),
            )
            for object_name, options, selected in combo_specs:
                widget = self._ui_object(object_name)
                if widget is None:
                    continue
                _ui_shell_combo_set_items(widget, options or [selected])
                _ui_shell_combo_select_label(widget, selected)

    def _redirect_backend_audio_device_controls(self):
            # The original UI did not expose these controls, so the hidden
            # backend can otherwise keep stale default-only combo boxes. Make
            # the visible real-UI choices the canonical widgets read by
            # qt_app.start_engine() and save_session().
            for object_name in ("audio_input_device_combo", "audio_output_device_combo"):
                widget = self._ui_object(object_name)
                if widget is not None:
                    setattr(self.backend, object_name, widget)

    def _refresh_response_length_runtime_frontend(self):
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _refresh_host_input_runtime_frontend(self):
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))

    def _refresh_musetalk_visual_runtime_frontend(self):
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))

    def _refresh_avatar_body_vam_runtime_frontend(self):
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))

    def _refresh_profile_utility_runtime_frontend(self):
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))

    def _refresh_musetalk_preview_frontend(self):
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _commit_frontend_audio_device_selection(self, object_name, config_key, default_label):
            widget = self._ui_object(object_name)
            if widget is None or not hasattr(widget, "currentText"):
                return
            choice = str(widget.currentText() or "").strip() or str(default_label or "").strip()
            backend_widget = self._backend_widget(object_name)
            if backend_widget is not None and hasattr(backend_widget, "findText") and hasattr(backend_widget, "setCurrentIndex"):
                index = backend_widget.findText(choice)
                if index < 0 and hasattr(backend_widget, "addItem"):
                    backend_widget.addItem(choice)
                    index = backend_widget.findText(choice)
                if index >= 0:
                    backend_widget.setCurrentIndex(index)
            update_runtime_config(str(config_key), choice)
            self.backend.save_session()
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_limit_response_length_changed(self, _checked):
            self._sync_single_checkbox_to_backend("limit_response_checkbox")
            self._refresh_response_length_runtime_frontend()

    def _on_frontend_max_response_tokens_changed(self, _value):
            self._sync_single_spin_to_backend("max_response_tokens_spin")
            self._refresh_response_length_runtime_frontend()

    def _on_frontend_audio_input_device_changed(self, _index=None):
            self._commit_frontend_audio_device_selection("audio_input_device_combo", "audio_input_device", "Default Input")

    def _on_frontend_audio_output_device_changed(self, _index=None):
            self._commit_frontend_audio_device_selection("audio_output_device_combo", "audio_output_device", "Default Output")

    def _on_frontend_engine_changed(self, _index=None):
            self._sync_single_combo_to_backend("engine_combo")
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_input_mode_changed(self, _index=None):
            self._sync_single_combo_to_backend("input_mode_combo")
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_input_role_changed(self, _index=None):
            self._sync_single_combo_to_backend("input_role_combo")
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_stream_mode_changed(self, _index=None):
            self._sync_single_combo_to_backend("stream_mode_combo")
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_tts_backend_changed(self, _index=None):
            self._sync_single_combo_to_backend("tts_backend_combo")
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_musetalk_vram_changed(self, _index=None):
            self._sync_single_combo_to_backend("musetalk_vram_combo")
            self._refresh_musetalk_visual_runtime_frontend()

    def _on_frontend_musetalk_avatar_pack_changed(self, _index=None):
            self._sync_single_combo_to_backend("musetalk_avatar_pack_combo")
            self._refresh_musetalk_visual_runtime_frontend()

    def _refresh_musetalk_avatar_packs_from_ui_real(self):
            try:
                self.backend.refresh_musetalk_avatar_pack_list()
            finally:
                QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
                QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
