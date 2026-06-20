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
            show_all = bool(RUNTIME_CONFIG.get("show_all_audio_input_devices", session.get("show_all_audio_input_devices", False)))
            show_all_widget = self._ui_object("show_all_audio_inputs_checkbox")
            if show_all_widget is not None and hasattr(show_all_widget, "setChecked"):
                show_all_widget.blockSignals(True)
                try:
                    show_all_widget.setChecked(show_all)
                finally:
                    show_all_widget.blockSignals(False)
            audio_devices = _ui_shell_audio_device_labels(show_all_inputs=show_all, include_input_mode_actions=True)
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
            for object_name in ("audio_input_device_combo", "audio_output_device_combo", "show_all_audio_inputs_checkbox"):
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
            widget = self._ui_object("audio_input_device_combo")
            choice = str(widget.currentText() if widget is not None and hasattr(widget, "currentText") else "").strip()
            action = self.backend._audio_input_mode_action(choice)
            if action:
                show_all = action == "show_all"
                update_runtime_config("show_all_audio_input_devices", show_all)
                checkbox = self._ui_object("show_all_audio_inputs_checkbox")
                if checkbox is not None and hasattr(checkbox, "setChecked"):
                    checkbox.blockSignals(True)
                    try:
                        checkbox.setChecked(show_all)
                    finally:
                        checkbox.blockSignals(False)
                self._prime_frontend_audio_device_controls()
                self.backend.save_session()
                self._refresh_host_input_runtime_frontend()
                return
            self._commit_frontend_audio_device_selection("audio_input_device_combo", "audio_input_device", "Default Input")

    def _on_frontend_show_all_audio_inputs_changed(self, checked=False):
            update_runtime_config("show_all_audio_input_devices", bool(checked))
            backend_widget = self._backend_widget("show_all_audio_inputs_checkbox")
            if backend_widget is not None and hasattr(backend_widget, "setChecked"):
                backend_widget.blockSignals(True)
                try:
                    backend_widget.setChecked(bool(checked))
                finally:
                    backend_widget.blockSignals(False)
            self._prime_frontend_audio_device_controls()
            self.backend.save_session()
            self._refresh_host_input_runtime_frontend()

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

    def _on_frontend_stt_backend_changed(self, _index=None):
            if bool(getattr(self, "_runtime_provider_tab_browse_in_progress", False)):
                return
            self._sync_single_combo_to_backend("stt_backend_combo")
            if bool(getattr(self, "_runtime_provider_tab_activation_in_progress", False)):
                return
            self._refresh_host_input_runtime_frontend()
            self._schedule_frontend_runtime_layout_pass(40)

    def _frontend_combo_current_value(self, object_name):
            combo = self._ui_object(object_name)
            if combo is None:
                return ""
            try:
                data = combo.currentData() if hasattr(combo, "currentData") else None
            except Exception:
                data = None
            if data is not None:
                return str(data or "").strip()
            try:
                return str(combo.currentText() or "").strip()
            except Exception:
                return ""

    def _on_frontend_stt_model_changed(self, _index=None):
            setter = getattr(self.backend, "_set_stt_editor_runtime_values", None)
            if callable(setter):
                language = self._frontend_combo_current_value("stt_language_combo")
                setter(model_value=self._frontend_combo_current_value("stt_model_combo"), language_value=language)
            else:
                self._sync_single_combo_to_backend("stt_model_combo")
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_stt_language_changed(self, _index=None):
            setter = getattr(self.backend, "_set_stt_editor_runtime_values", None)
            if callable(setter):
                setter(
                    model_value=self._frontend_combo_current_value("stt_model_combo"),
                    language_value=self._frontend_combo_current_value("stt_language_combo"),
                )
            else:
                self._sync_single_combo_to_backend("stt_language_combo")
            self._refresh_host_input_runtime_frontend()

    def _on_frontend_tts_backend_changed(self, _index=None):
            self._sync_single_combo_to_backend("tts_backend_combo")
            if bool(getattr(self, "_runtime_provider_tab_activation_in_progress", False)):
                return
            self._refresh_host_input_runtime_frontend()
            self._schedule_frontend_runtime_layout_pass(40)
