"""RealUiSyncFrontendMixin extracted from real_ui_sync.py."""

from PySide6 import QtCore, QtGui, QtWidgets


def configure_real_ui_sync_frontend_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiSyncFrontendMixin:
    def _widget_or_child_has_focus(self, widget):
            if widget is None:
                return False
            try:
                if bool(widget.hasFocus()):
                    return True
            except Exception:
                pass
            try:
                focused = QtWidgets.QApplication.focusWidget()
            except Exception:
                focused = None
            if focused is None:
                return False
            try:
                return focused is widget or bool(widget.isAncestorOf(focused))
            except Exception:
                return False

    def _sync_combo_like_widget(self, source, target):
            if source is None or target is None:
                return False
            source_data = None
            if hasattr(source, "currentData"):
                try:
                    source_data = source.currentData()
                except Exception:
                    source_data = None
            if source_data is not None and hasattr(target, "findData") and hasattr(target, "setCurrentIndex"):
                try:
                    index = target.findData(source_data)
                except Exception:
                    index = -1
                if index >= 0:
                    target.setCurrentIndex(index)
                    return True
            if hasattr(source, "currentText"):
                try:
                    text = str(source.currentText() or "").strip()
                except Exception:
                    text = ""
                if text and hasattr(target, "findText") and hasattr(target, "setCurrentIndex"):
                    try:
                        index = target.findText(text)
                    except Exception:
                        index = -1
                    if index >= 0:
                        target.setCurrentIndex(index)
                        return True
                if text and hasattr(target, "setCurrentText"):
                    try:
                        target.setCurrentText(text)
                        return True
                    except Exception:
                        return False
            return False

    def _bind_frontend_to_backend_sync(self):
            for object_name in self._combo_sync_names():
                if object_name in {
                    "audio_input_device_combo",
                    "audio_output_device_combo",
                    "engine_combo",
                    "input_mode_combo",
                    "input_role_combo",
                    "stream_mode_combo",
                    "tts_backend_combo",
                    "musetalk_vram_combo",
                    "musetalk_avatar_pack_combo",
                    "chat_provider_combo",
                    "model_combo",
                    "preset_combo",
                    "visual_reply_mode_combo",
                    "visual_reply_provider_combo",
                    "visual_reply_size_combo",
                    "sensory_feedback_source_combo",
                    "chat_font_size_combo",
                    "voice_combo",
                    "body_combo",
                    "emotion_combo",
                    "chat_overflow_policy_combo",
                    "chunking_profile_combo",
                    "performance_profile_combo",
                }:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "currentIndexChanged"):
                    front.currentIndexChanged.connect(lambda _index, name=object_name: self._sync_single_combo_to_backend(name))
            for object_name in self._checkbox_sync_names():
                if object_name in {
                    "limit_response_checkbox",
                    "model_requires_vision_checkbox",
                    "allow_proactive_checkbox",
                    "require_first_user_checkbox",
                    "sensory_pingpong_checkbox",
                    "sensory_allow_hidden_proactive_checkbox",
                    "sensory_allow_hidden_visual_checkbox",
                    "live_sync_checkbox",
                    "vam_vmc_enabled_checkbox",
                    "vam_bridge_enabled_checkbox",
                    "vam_play_audio_in_vam_checkbox",
                    "vam_timeline_auto_resume_checkbox",
                    "dry_run_auto_replies_checkbox",
                }:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "toggled"):
                    front.toggled.connect(lambda _checked, name=object_name: self._sync_single_checkbox_to_backend(name))
            for object_name in self._spin_sync_names():
                if object_name in {
                    "max_response_tokens_spin",
                    "chat_context_window_spin",
                    "stored_chat_history_limit_spin",
                    "listen_idle_window_spin",
                    "proactive_delay_spin",
                    "sensory_feedback_interval_spin",
                    "sensory_pingpong_history_spin",
                    "vam_vmc_port_spin",
                    "dry_run_target_spin",
                    "musetalk_loop_fade_spin",
                }:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "valueChanged"):
                    front.valueChanged.connect(lambda _value, name=object_name: self._sync_single_spin_to_backend(name))
            for object_name in self._line_edit_sync_names():
                if object_name in {
                    "vam_root_edit",
                    "vam_bridge_root_edit",
                    "vam_target_atom_uid_edit",
                    "vam_target_storable_id_edit",
                    "vam_vmc_host_edit",
                    "visual_reply_model_edit",
                }:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "editingFinished"):
                    front.editingFinished.connect(lambda name=object_name: self._sync_single_line_edit_to_backend(name))

    def _combo_sync_names(self):
            return (
                "audio_input_device_combo",
                "audio_output_device_combo",
                "engine_combo",
                "input_mode_combo",
                "input_role_combo",
                "stream_mode_combo",
                "tts_backend_combo",
                "musetalk_vram_combo",
                "musetalk_avatar_pack_combo",
                "preset_combo",
                "chat_provider_combo",
                "model_combo",
                "model_requires_vision_checkbox",
                "visual_reply_mode_combo",
                "visual_reply_provider_combo",
                "visual_reply_size_combo",
                "sensory_feedback_source_combo",
                "chat_font_size_combo",
                "voice_combo",
                "body_combo",
                "emotion_combo",
                "chat_overflow_policy_combo",
                "chunking_profile_combo",
                "performance_profile_combo",
            )

    def _checkbox_sync_names(self):
            return (
                "limit_response_checkbox",
                "allow_proactive_checkbox",
                "require_first_user_checkbox",
                "sensory_pingpong_checkbox",
                "sensory_allow_hidden_proactive_checkbox",
                "sensory_allow_hidden_visual_checkbox",
                "live_sync_checkbox",
                "musetalk_use_frame_cache_checkbox",
                "vam_vmc_enabled_checkbox",
                "vam_bridge_enabled_checkbox",
                "vam_play_audio_in_vam_checkbox",
                "vam_timeline_auto_resume_checkbox",
                "dry_run_auto_replies_checkbox",
            )

    def _spin_sync_names(self):
            return (
                "max_response_tokens_spin",
                "chat_context_window_spin",
                "stored_chat_history_limit_spin",
                "listen_idle_window_spin",
                "proactive_delay_spin",
                "musetalk_loop_fade_spin",
                "sensory_feedback_interval_spin",
                "sensory_pingpong_history_spin",
                "vam_vmc_port_spin",
                "dry_run_target_spin",
            )

    def _line_edit_sync_names(self):
            return (
                "visual_reply_model_edit",
                "vam_root_edit",
                "vam_bridge_root_edit",
                "vam_target_atom_uid_edit",
                "vam_target_storable_id_edit",
                "vam_vmc_host_edit",
            )

    def _sync_frontend_to_backend(self):
            for object_name in self._combo_sync_names():
                self._sync_single_combo_to_backend(object_name)
            for object_name in self._checkbox_sync_names():
                self._sync_single_checkbox_to_backend(object_name)
            for object_name in self._spin_sync_names():
                self._sync_single_spin_to_backend(object_name)
            for object_name in self._line_edit_sync_names():
                self._sync_single_line_edit_to_backend(object_name)
            self._sync_plain_text_to_backend("emotional_text")
            self._sync_plain_text_to_backend("system_prompt_text")
            self._sync_plain_text_to_backend("sensory_pingpong_prompt_text")

    def _sync_single_combo_to_backend(self, object_name):
            front = self._ui_object(object_name)
            back = self._backend_widget(object_name)
            if front is None or back is None or not hasattr(front, "currentText") or not hasattr(back, "setCurrentIndex"):
                return False
            front_data = None
            if hasattr(front, "currentData"):
                try:
                    front_data = front.currentData()
                except Exception:
                    front_data = None
            if front_data is not None and hasattr(back, "findData"):
                try:
                    index = back.findData(front_data)
                except Exception:
                    index = -1
                if index >= 0:
                    back.setCurrentIndex(index)
                    return True
            text = str(front.currentText() or "").strip()
            if not text:
                return False
            if hasattr(back, "findText"):
                try:
                    index = back.findText(text)
                except Exception:
                    index = -1
                if index >= 0:
                    back.setCurrentIndex(index)
                    return True
            if hasattr(back, "setCurrentText"):
                try:
                    back.setCurrentText(text)
                    return True
                except Exception:
                    return False
            return False

    def _sync_single_checkbox_to_backend(self, object_name):
            front = self._ui_object(object_name)
            back = self._backend_widget(object_name)
            if front is None or back is None or not hasattr(front, "isChecked") or not hasattr(back, "setChecked"):
                return False
            try:
                back.setChecked(bool(front.isChecked()))
                return True
            except Exception:
                return False

    def _sync_single_spin_to_backend(self, object_name):
            front = self._ui_object(object_name)
            back = self._backend_widget(object_name)
            if front is None or back is None or not hasattr(front, "value") or not hasattr(back, "setValue"):
                return False
            try:
                back.setValue(front.value())
                return True
            except Exception:
                return False

    def _sync_single_line_edit_to_backend(self, object_name):
            front = self._ui_object(object_name)
            back = self._backend_widget(object_name)
            if front is None or back is None or not hasattr(front, "text") or not hasattr(back, "setText"):
                return False
            try:
                back.setText(str(front.text() or ""))
                return True
            except Exception:
                return False

    def _sync_plain_text_to_backend(self, object_name):
            front = self._ui_object(object_name)
            back = self._backend_widget(object_name)
            if front is None or back is None or not hasattr(front, "toPlainText") or not hasattr(back, "setPlainText"):
                return False
            try:
                back.setPlainText(str(front.toPlainText() or ""))
                return True
            except Exception:
                return False

    def _refresh_backend_preset_dirty_state(self):
            callback = getattr(self.backend, "_refresh_preset_dirty_state", None)
            if callable(callback):
                try:
                    callback()
                except Exception:
                    pass

    def _combo_popup_is_open(self, combo):
            if combo is None or not hasattr(combo, "view"):
                return False
            try:
                view = combo.view()
                if view is not None and view.isVisible():
                    return True
                popup_window = view.window() if view is not None and hasattr(view, "window") else None
                return bool(popup_window is not None and popup_window.isVisible())
            except Exception:
                return False
