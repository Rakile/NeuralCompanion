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
            addon_combo_names = self._addon_sync_widget_names("combo")
            for object_name in self._combo_sync_names():
                if object_name in {
                    "audio_input_device_combo",
                    "audio_output_device_combo",
                    "engine_combo",
                    "input_mode_combo",
                    "input_role_combo",
                    "stream_mode_combo",
                    "stt_backend_combo",
                    "stt_model_combo",
                    "stt_language_combo",
                    "tts_backend_combo",
                    "chat_provider_combo",
                    "model_combo",
                    "preset_combo",
                    "sensory_feedback_source_combo",
                    "chat_font_size_combo",
                    "spellcheck_language_combo",
                    "voice_combo",
                    "body_combo",
                    "emotion_combo",
                    "chat_overflow_policy_combo",
                    "chunking_profile_combo",
                    "performance_profile_combo",
                } | addon_combo_names:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "currentIndexChanged"):
                    front.currentIndexChanged.connect(lambda _index, name=object_name: self._sync_single_combo_to_backend(name))
            addon_checkbox_names = self._addon_sync_widget_names("checkbox")
            for object_name in self._checkbox_sync_names():
                if object_name in {
                    "limit_response_checkbox",
                    "show_all_audio_inputs_checkbox",
                    "model_requires_vision_checkbox",
                    "allow_proactive_checkbox",
                    "require_first_user_checkbox",
                    "long_term_memory_enabled_checkbox",
                    "long_term_memory_update_on_save_checkbox",
                    "long_term_memory_inject_checkbox",
                    "long_term_memory_retrieval_enabled_checkbox",
                    "long_term_memory_auto_archive_enabled_checkbox",
                    "long_term_memory_embedding_enabled_checkbox",
                    "spellcheck_enabled_checkbox",
                    "sensory_pingpong_checkbox",
                    "sensory_allow_hidden_proactive_checkbox",
                    "sensory_allow_hidden_visual_checkbox",
                    "use_wav_file_checkbox",
                    "live_sync_checkbox",
                    "dry_run_auto_replies_checkbox",
                } | addon_checkbox_names:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "toggled"):
                    front.toggled.connect(lambda _checked, name=object_name: self._sync_single_checkbox_to_backend(name))
            addon_spin_names = self._addon_sync_widget_names("spin")
            for object_name in self._spin_sync_names():
                if object_name in {
                    "max_response_tokens_spin",
                    "chat_context_window_spin",
                    "stored_chat_history_limit_spin",
                    "listen_idle_window_spin",
                    "proactive_delay_spin",
                    "continuity_memory_auto_turns_spin",
                    "long_term_memory_max_chars_spin",
                    "long_term_memory_retrieval_max_items_spin",
                    "long_term_memory_recall_image_limit_spin",
                    "long_term_memory_archive_batch_turns_spin",
                    "long_term_memory_embedding_context_length_spin",
                    "sensory_feedback_interval_spin",
                    "sensory_pingpong_history_spin",
                    "dry_run_target_spin",
                } | addon_spin_names:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "valueChanged"):
                    front.valueChanged.connect(lambda _value, name=object_name: self._sync_single_spin_to_backend(name))
            addon_line_edit_names = self._addon_sync_widget_names("line_edit")
            for object_name in self._line_edit_sync_names():
                if object_name in addon_line_edit_names:
                    continue
                front = self._ui_object(object_name)
                if front is not None and hasattr(front, "editingFinished"):
                    front.editingFinished.connect(lambda name=object_name: self._sync_single_line_edit_to_backend(name))

    def _addon_sync_widget_names(self, kind=None):
        cache = getattr(self, "_addon_sync_widget_name_cache", None)
        if cache is None:
            cache = {}
            self._addon_sync_widget_name_cache = cache
        callback = getattr(self.backend, "_invoke_all_addon_capabilities", None)
        if not callable(callback):
            return set()
        wanted_kind = str(kind or "").strip()
        if wanted_kind in cache:
            return set(cache.get(wanted_kind) or set())
        try:
            results = callback(
                "real_ui.sync_widget_names",
                {"bridge": self, "kind": wanted_kind},
            )
        except Exception:
            return set()
        names = set()
        for result in list(results or []):
            if isinstance(result, dict):
                values = result.get(wanted_kind) if wanted_kind else result.values()
                if wanted_kind:
                    iterable = values if isinstance(values, (list, tuple, set)) else [values]
                else:
                    iterable = []
                    for value in values:
                        iterable.extend(value if isinstance(value, (list, tuple, set)) else [value])
            elif isinstance(result, (list, tuple, set)):
                iterable = result
            else:
                iterable = [result]
            for name in iterable:
                text = str(name or "").strip()
                if text:
                    names.add(text)
        cache[wanted_kind] = set(names)
        return names

    def _combo_sync_names(self):
            return tuple(
                list((
                "audio_input_device_combo",
                "audio_output_device_combo",
                "engine_combo",
                "input_mode_combo",
                "input_role_combo",
                "stream_mode_combo",
                "stt_backend_combo",
                "stt_model_combo",
                "stt_language_combo",
                "tts_backend_combo",
                "preset_combo",
                "chat_provider_combo",
                "model_combo",
                "long_term_memory_embedding_model_edit",
                "spellcheck_language_combo",
                "model_requires_vision_checkbox",
                "sensory_feedback_source_combo",
                "chat_font_size_combo",
                "voice_combo",
                "body_combo",
                "emotion_combo",
                "chat_overflow_policy_combo",
                "chunking_profile_combo",
                "performance_profile_combo",
                ))
                + sorted(self._addon_sync_widget_names("combo"))
            )

    def _checkbox_sync_names(self):
            return tuple(
                list((
                "limit_response_checkbox",
                "show_all_audio_inputs_checkbox",
                "allow_proactive_checkbox",
                "require_first_user_checkbox",
                "long_term_memory_enabled_checkbox",
                "long_term_memory_update_on_save_checkbox",
                "long_term_memory_inject_checkbox",
                "long_term_memory_retrieval_enabled_checkbox",
                "long_term_memory_auto_archive_enabled_checkbox",
                "long_term_memory_embedding_enabled_checkbox",
                "spellcheck_enabled_checkbox",
                "sensory_pingpong_checkbox",
                "sensory_allow_hidden_proactive_checkbox",
                "sensory_allow_hidden_visual_checkbox",
                "use_wav_file_checkbox",
                "live_sync_checkbox",
                "dry_run_auto_replies_checkbox",
                ))
                + sorted(self._addon_sync_widget_names("checkbox"))
            )

    def _spin_sync_names(self):
            return tuple(
                list((
                "max_response_tokens_spin",
                "chat_context_window_spin",
                "stored_chat_history_limit_spin",
                "listen_idle_window_spin",
                "proactive_delay_spin",
                "continuity_memory_auto_turns_spin",
                "long_term_memory_max_chars_spin",
                "long_term_memory_retrieval_max_items_spin",
                "long_term_memory_recall_image_limit_spin",
                "long_term_memory_archive_batch_turns_spin",
                "long_term_memory_embedding_context_length_spin",
                "sensory_feedback_interval_spin",
                "sensory_pingpong_history_spin",
                "dry_run_target_spin",
                ))
                + sorted(self._addon_sync_widget_names("spin"))
            )

    def _line_edit_sync_names(self):
            return tuple(
                list((
                "long_term_memory_embedding_base_url_edit",
                ))
                + sorted(self._addon_sync_widget_names("line_edit"))
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
            if front is None or back is None:
                return False
            try:
                if hasattr(front, "currentText"):
                    text = str(front.currentText() or "")
                elif hasattr(front, "text"):
                    text = str(front.text() or "")
                else:
                    return False
                if hasattr(back, "setCurrentText"):
                    back.setCurrentText(text)
                elif hasattr(back, "setText"):
                    back.setText(text)
                else:
                    return False
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
