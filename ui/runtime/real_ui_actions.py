from PySide6 import QtCore


def configure_real_ui_actions_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI action mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealActionsMixin:
    """Frontend callback handlers that forward Designer UI changes to the hidden backend."""

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

    def _on_frontend_visual_reply_mode_changed(self, _index=None):
            self._sync_single_combo_to_backend("visual_reply_mode_combo")
            self._refresh_musetalk_visual_runtime_frontend()

    def _on_frontend_visual_reply_provider_changed(self, _index=None):
            self._sync_single_combo_to_backend("visual_reply_provider_combo")
            self._refresh_musetalk_visual_runtime_frontend()

    def _on_frontend_visual_reply_size_changed(self, _index=None):
            self._sync_single_combo_to_backend("visual_reply_size_combo")
            self._refresh_musetalk_visual_runtime_frontend()

    def _on_frontend_sensory_feedback_source_changed(self, _index=None):
            self._sync_single_combo_to_backend("sensory_feedback_source_combo")
            self._refresh_musetalk_visual_runtime_frontend()

    def _on_frontend_chat_font_size_changed(self, _index=None):
            self._sync_single_combo_to_backend("chat_font_size_combo")
            self._refresh_musetalk_visual_runtime_frontend()

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

    def _on_frontend_chunking_profile_changed(self, _index=None):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_chunking_value_changed(self, key, value):
            spec = _ui_shell_chunking_slider_spec(key)
            normalized_value = value
            try:
                is_int = bool(spec.get("is_int", True))
                scale = float(spec.get("scale", 1) or 1)
                normalized_value = float(value) / scale
                normalized_value = int(round(normalized_value)) if is_int else round(normalized_value, 2)
                callback = getattr(self.backend, "update_chunking_value", None)
                if callable(callback):
                    callback(str(key), normalized_value, is_int)
                else:
                    update_runtime_config(str(key), normalized_value)
                    self.backend.save_session()
            finally:
                backend_slider = getattr(self.backend, "chunking_sliders", {}).get(str(key))
                if backend_slider is not None and hasattr(backend_slider, "set_value"):
                    try:
                        backend_slider.set_value(normalized_value)
                    except Exception:
                        pass
                _ui_shell_update_chunking_label(self.window, str(key), normalized_value)
                self._refresh_profile_utility_runtime_frontend()

    def _reset_chunking_from_ui_real(self):
            self.backend.reset_chunking_defaults()
            self._mirror_chunking_runtime_widgets(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _refresh_chunking_profiles_from_ui_real(self):
            self.backend.refresh_performance_profile_list()
            self._mirror_chunking_profile_combo(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _load_chunking_profile_from_ui_real(self):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self.backend.load_selected_chunking_profile()
            self._mirror_chunking_runtime_widgets(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _save_chunking_profile_from_ui_real(self):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self.backend.save_current_chunking_profile()
            self._mirror_chunking_profile_combo(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _delete_chunking_profile_from_ui_real(self):
            self._sync_single_combo_to_backend("chunking_profile_combo")
            self.backend.delete_selected_chunking_profile()
            self._mirror_chunking_profile_combo(force=True)
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_performance_profile_changed(self, _index=None):
            self._sync_single_combo_to_backend("performance_profile_combo")
            self.backend.save_session()
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_dry_run_auto_replies_changed(self, _checked):
            self._sync_single_checkbox_to_backend("dry_run_auto_replies_checkbox")
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_dry_run_target_changed(self, _value):
            self._sync_single_spin_to_backend("dry_run_target_spin")
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_musetalk_loop_fade_changed(self, _value):
            self._sync_single_spin_to_backend("musetalk_loop_fade_spin")
            self._refresh_profile_utility_runtime_frontend()

    def _on_frontend_visual_reply_model_changed(self):
            self._sync_single_line_edit_to_backend("visual_reply_model_edit")
            callback = getattr(self.backend, "on_visual_reply_model_changed", None)
            if callable(callback):
                callback()
            self._refresh_profile_utility_runtime_frontend()

    def _refresh_chat_session_runtime_frontend(self):
            try:
                self.backend._refresh_chat_session_hint()
            except Exception:
                pass
            try:
                self.backend._update_chat_status(self.backend._console_redirect.chat_line_count, int(self.backend.chat_auto_scroll))
            except Exception:
                pass
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_allow_proactive_changed(self, checked):
            try:
                self.backend.on_allow_proactive_replies_changed(bool(checked))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_require_first_user_changed(self, checked):
            try:
                self.backend.on_require_first_user_before_proactive_changed(bool(checked))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_listen_idle_window_changed(self, value):
            try:
                self.backend.on_listen_idle_window_changed(value)
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_proactive_delay_changed(self, value):
            try:
                self.backend.on_proactive_delay_changed(value)
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_chat_context_window_changed(self, value):
            try:
                self.backend.on_chat_context_window_changed(int(value))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_stored_chat_history_limit_changed(self, value):
            try:
                self.backend.on_stored_chat_history_limit_changed(int(value))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_chat_overflow_policy_changed(self, choice):
            try:
                self.backend.on_chat_overflow_policy_changed(str(choice or ""))
            finally:
                self._refresh_chat_session_runtime_frontend()

    def _on_frontend_system_prompt_changed(self):
            try:
                self._frontend_system_prompt_commit_timer.start(250)
            except Exception:
                self._commit_frontend_system_prompt_to_runtime()

    def _commit_frontend_system_prompt_to_runtime(self):
            system_prompt_text = self._ui_object("system_prompt_text")
            if system_prompt_text is None or not hasattr(system_prompt_text, "toPlainText"):
                return
            try:
                update_runtime_config("system_prompt", str(system_prompt_text.toPlainText() or "").strip())
                self._sync_plain_text_to_backend("system_prompt_text")
                self.backend.save_session()
            finally:
                QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_emotional_text_changed(self):
            emotional_text = self._ui_object("emotional_text")
            if emotional_text is None or not hasattr(emotional_text, "toPlainText"):
                return
            try:
                update_runtime_config("emotional_instructions", str(emotional_text.toPlainText() or "").strip())
                self._sync_plain_text_to_backend("emotional_text")
            except Exception:
                pass

    def _refresh_sensory_runtime_frontend(self):
            try:
                self.backend._refresh_sensory_feedback_hint()
            except Exception:
                pass
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_sensory_interval_changed(self, value):
            try:
                self.backend.on_sensory_feedback_interval_changed(value)
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_pingpong_toggled(self, checked):
            try:
                self.backend.on_sensory_pingpong_enabled_changed(bool(checked))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_hidden_proactive_toggled(self, checked):
            try:
                self.backend.on_sensory_allow_hidden_proactive_changed(bool(checked))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_hidden_visual_toggled(self, checked):
            try:
                self.backend.on_sensory_allow_hidden_visual_changed(bool(checked))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_history_changed(self, value):
            try:
                self.backend.on_sensory_pingpong_history_depth_changed(int(value))
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_sensory_prompt_changed(self):
            try:
                self.backend.on_sensory_pingpong_prompt_changed()
            finally:
                self._refresh_sensory_runtime_frontend()

    def _reset_frontend_sensory_prompt_to_default(self):
            try:
                self.backend.reset_sensory_pingpong_prompt_to_default()
            finally:
                self._refresh_sensory_runtime_frontend()

    def _on_frontend_chat_provider_changed(self, _index=None):
            frontend_combo = self._ui_object("chat_provider_combo")
            backend_combo = self._backend_widget("chat_provider_combo")
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(1200, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_model_selection_changed(self, _index=None):
            frontend_combo = self._ui_object("model_combo")
            backend_combo = self._backend_widget("model_combo")
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_model_requires_vision_changed(self, checked):
            backend_checkbox = self._backend_widget("model_requires_vision_checkbox")
            if backend_checkbox is None or not hasattr(backend_checkbox, "setChecked"):
                return
            try:
                backend_checkbox.setChecked(bool(checked))
            except Exception:
                return
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))
            QtCore.QTimer.singleShot(300, lambda: self._sync_backend_to_ui(force=True))

    def _on_frontend_preset_selection_changed(self, _index=None):
            frontend_combo = self._ui_object("preset_combo")
            backend_combo = self._backend_widget("preset_combo")
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            self._refresh_backend_preset_dirty_state()
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _enter_chat_edit_mode_from_ui_real(self):
            self._sync_backend_to_ui(force=True)
            try:
                self.backend.enter_chat_edit_mode()
            finally:
                self._sync_backend_to_ui(force=True)

    def _cancel_chat_edit_mode_from_ui_real(self):
            try:
                self.backend.cancel_chat_edit_mode()
            finally:
                self._sync_backend_to_ui(force=True)

    def _apply_chat_edit_mode_from_ui_real(self):
            frontend_chat = self._ui_object("chat_edit")
            backend_chat = self._backend_widget("chat_edit")
            if frontend_chat is not None and backend_chat is not None and hasattr(frontend_chat, "toPlainText") and hasattr(backend_chat, "setPlainText"):
                try:
                    backend_chat.setPlainText(str(frontend_chat.toPlainText() or ""))
                except Exception:
                    pass
            try:
                self.backend.apply_chat_edit_mode()
            finally:
                self._sync_backend_to_ui(force=True)

    def _sync_audio_story_frontend_combo_to_controller(self):
            controller = self._audio_story_controller()
            frontend_combo = self._ui_object("audio_story_playback_combo")
            backend_combo = getattr(controller, "audio_story_playback_mode_combo", None) if controller is not None else None
            if frontend_combo is None or backend_combo is None:
                return
            self._sync_combo_like_widget(frontend_combo, backend_combo)
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _sync_audio_story_frontend_slider_to_controller(self, value):
            controller = self._audio_story_controller()
            backend_slider = getattr(controller, "audio_story_transcribe_seconds_slider", None) if controller is not None else None
            if backend_slider is None or not hasattr(backend_slider, "setValue"):
                return
            try:
                backend_slider.setValue(int(value))
            except Exception:
                return
            QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _apply_audio_story_seek_from_frontend(self):
            controller = self._audio_story_controller()
            frontend_slider = self._ui_object("audio_story_seek_slider")
            backend_slider = getattr(controller, "audio_story_position_slider", None) if controller is not None else None
            if frontend_slider is None or backend_slider is None or not hasattr(frontend_slider, "value") or not hasattr(backend_slider, "setValue"):
                return
            try:
                backend_slider.setValue(int(frontend_slider.value()))
            except Exception:
                return
            callback = getattr(controller, "_on_slider_released", None)
            if callable(callback):
                try:
                    callback()
                finally:
                    QtCore.QTimer.singleShot(0, lambda: self._sync_backend_to_ui(force=True))

    def _set_frontend_musetalk_focus_button_text(self, text):
            focus_button = self._ui_object("btn_musetalk_avatar_focus")
            if focus_button is not None and hasattr(focus_button, "setText"):
                try:
                    focus_button.setText(str(text or "Avatar Focus"))
                except Exception:
                    pass

    def _show_frontend_musetalk_preview(self):
            if self.backend._current_avatar_mode_value() != "musetalk":
                return
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if bool(getattr(self.backend, "_musetalk_avatar_focus_active", False)):
                stage_window = self.backend._ensure_musetalk_stage_window()
                self.backend._attach_musetalk_preview_to_host("stage")
                stage_window.show()
                stage_window.raise_()
                stage_window.activateWindow()
            else:
                self.backend._attach_musetalk_preview_to_host("dock")
                preview_dock = self._ui_object("PreviewDock")
                if preview_dock is not None:
                    preview_dock.show()
                    preview_dock.raise_()
            if panel is not None:
                panel.show()
                if hasattr(panel, "set_focus_mode"):
                    panel.set_focus_mode(bool(getattr(self.backend, "_musetalk_avatar_focus_active", False)))
            self._refresh_musetalk_preview_frontend()

    def _enter_frontend_musetalk_avatar_focus(self):
            if self.backend._current_avatar_mode_value() != "musetalk":
                return
            self.backend._musetalk_avatar_focus_active = True
            self.backend._musetalk_main_window_was_maximized = bool(self.window.isMaximized())
            self.backend._musetalk_main_window_was_fullscreen = bool(self.window.isFullScreen())
            self._set_frontend_musetalk_focus_button_text("Exit Avatar Focus")
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if panel is not None and hasattr(panel, "set_focus_mode"):
                panel.set_focus_mode(True)
            self.backend._attach_musetalk_preview_to_host("stage")
            preview_dock = self._ui_object("PreviewDock")
            if preview_dock is not None:
                preview_dock.hide()
            stage_window = self.backend._ensure_musetalk_stage_window()
            self.backend._sync_musetalk_stage_window_geometry_from_preview()
            stage_window.show()
            stage_window.raise_()
            stage_window.activateWindow()
            self.window.hide()
            self._refresh_musetalk_preview_frontend()

    def _exit_frontend_musetalk_avatar_focus(self, *, raise_main=False):
            was_active = bool(getattr(self.backend, "_musetalk_avatar_focus_active", False))
            self.backend._musetalk_avatar_focus_active = False
            self._set_frontend_musetalk_focus_button_text("Avatar Focus")
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if panel is not None and hasattr(panel, "set_focus_mode"):
                panel.set_focus_mode(False)
            self.backend._attach_musetalk_preview_to_host("dock")
            stage_window = getattr(self.backend, "_musetalk_stage_window", None)
            if stage_window is not None:
                try:
                    stage_window.allow_internal_close(True)
                    stage_window.hide()
                    stage_window.allow_internal_close(False)
                except Exception:
                    pass
            preview_dock = self._ui_object("PreviewDock")
            if preview_dock is not None:
                preview_dock.show()
            visual_reply_dock = self._ui_object("VisualReplyDock")
            if preview_dock is not None and visual_reply_dock is not None:
                try:
                    self.window.tabifyDockWidget(preview_dock, visual_reply_dock)
                except Exception:
                    pass
            if raise_main or was_active or not self.window.isVisible():
                if bool(getattr(self.backend, "_musetalk_main_window_was_fullscreen", False)):
                    self.window.showFullScreen()
                elif bool(getattr(self.backend, "_musetalk_main_window_was_maximized", False)):
                    self.window.showMaximized()
                else:
                    self.window.showNormal()
                self.window.raise_()
                self.window.activateWindow()
            self._refresh_musetalk_preview_frontend()

    def _toggle_frontend_musetalk_avatar_focus(self):
            if bool(getattr(self.backend, "_musetalk_avatar_focus_active", False)):
                self._exit_frontend_musetalk_avatar_focus(raise_main=True)
            else:
                self._enter_frontend_musetalk_avatar_focus()

    def _show_frontend_main_interface_from_musetalk_focus(self):
            self._exit_frontend_musetalk_avatar_focus(raise_main=True)

    def _stop_frontend_musetalk_preview(self):
            self._exit_frontend_musetalk_avatar_focus(raise_main=False)
            preview_dock = self._ui_object("PreviewDock")
            if preview_dock is not None:
                preview_dock.hide()
            stage_window = getattr(self.backend, "_musetalk_stage_window", None)
            if stage_window is not None:
                try:
                    stage_window.allow_internal_close(True)
                    stage_window.hide()
                    stage_window.allow_internal_close(False)
                except Exception:
                    pass
            panel = getattr(self.backend, "embedded_musetalk_preview", None)
            if panel is not None and hasattr(panel, "reset_preview"):
                panel.reset_preview()
            self._refresh_musetalk_preview_frontend()

    def _show_frontend_visual_reply_dock(self):
            dock = self._ui_object("VisualReplyDock")
            if dock is None:
                return
            try:
                dock.show()
                dock.raise_()
            except Exception:
                pass
