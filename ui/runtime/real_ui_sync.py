from PySide6 import QtCore, QtGui, QtWidgets


def configure_real_ui_sync_dependencies(namespace):
    """Inject qt_app-owned globals used by the extracted real-UI sync mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealSyncMixin:
    """Frontend/backend mirroring and polling sync helpers for the runtime-backed main.ui bridge."""

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

    def _combo_items_snapshot(self, combo):
            if combo is None or not hasattr(combo, "count"):
                return []
            items = []
            for index in range(combo.count()):
                try:
                    text = str(combo.itemText(index) or "")
                    data = combo.itemData(index) if hasattr(combo, "itemData") else None
                    items.append((text, data))
                except Exception:
                    continue
            return items

    def _copy_combo_state(self, source, target):
            if source is None or target is None or not hasattr(source, "count") or not hasattr(target, "clear"):
                return False
            if self._combo_popup_is_open(target):
                return False
            items = self._combo_items_snapshot(source)
            existing_items = self._combo_items_snapshot(target)
            selected_data = None
            selected_text = ""
            try:
                if hasattr(source, "currentData"):
                    selected_data = source.currentData()
            except Exception:
                selected_data = None
            try:
                selected_text = str(source.currentText() or "").strip()
            except Exception:
                selected_text = ""
            target.blockSignals(True)
            try:
                if existing_items != items:
                    target.clear()
                    for text, data in items:
                        if hasattr(target, "addItem"):
                            target.addItem(text, data)
                applied = False
                if selected_data is not None and hasattr(target, "findData"):
                    try:
                        index = target.findData(selected_data)
                    except Exception:
                        index = -1
                    if index >= 0 and target.currentIndex() != index:
                        target.setCurrentIndex(index)
                    if index >= 0:
                        applied = True
                if not applied and selected_text:
                    try:
                        index = target.findText(selected_text)
                    except Exception:
                        index = -1
                    if index >= 0 and target.currentIndex() != index:
                        target.setCurrentIndex(index)
                    if index >= 0:
                        applied = True
                if not applied and target.count():
                    fallback_index = min(max(source.currentIndex(), 0), target.count() - 1)
                    if target.currentIndex() != fallback_index:
                        target.setCurrentIndex(fallback_index)
            finally:
                target.blockSignals(False)
            return True

    def _copy_text_state(self, source, target):
            if source is None or target is None:
                return False
            if hasattr(source, "toPlainText") and hasattr(target, "setPlainText"):
                text = str(source.toPlainText() or "")
                return self._set_text_widget_text(target, text)
            if hasattr(source, "text") and hasattr(target, "setText"):
                text = str(source.text() or "")
                return self._set_text_widget_text(target, text)
            return False

    def _set_text_widget_text(self, target, text):
            if target is None:
                return False
            value = str(text or "")
            try:
                if hasattr(target, "toPlainText"):
                    current = str(target.toPlainText() or "")
                    if current == value:
                        return True
                    was_blocked = bool(target.blockSignals(True)) if hasattr(target, "blockSignals") else False
                    try:
                        target.setPlainText(value)
                    finally:
                        if hasattr(target, "blockSignals"):
                            target.blockSignals(was_blocked)
                    return True
                if hasattr(target, "text") and hasattr(target, "setText"):
                    current = str(target.text() or "")
                    if current == value:
                        return True
                    was_blocked = bool(target.blockSignals(True)) if hasattr(target, "blockSignals") else False
                    try:
                        target.setText(value)
                    finally:
                        if hasattr(target, "blockSignals"):
                            target.blockSignals(was_blocked)
                    return True
            except Exception:
                return False
            return False

    def _copy_runtime_plain_text_state(self, object_name, config_key):
            front = self._ui_object(object_name)
            back = self._backend_widget(object_name)
            if front is None or back is None:
                return False
            if self._widget_or_child_has_focus(front):
                return False
            text = ""
            try:
                if hasattr(back, "toPlainText"):
                    text = str(back.toPlainText() or "")
            except Exception:
                text = ""
            try:
                runtime_text = str((RUNTIME_CONFIG or {}).get(config_key, "") or "")
            except Exception:
                runtime_text = ""
            designer_placeholders = {
                "emotional_text": "Technical rules / expressive tags",
                "system_prompt_text": "System prompt",
                "sensory_pingpong_prompt_text": "Hidden PING/PONG prompt",
            }
            if text == designer_placeholders.get(str(object_name), "") and runtime_text:
                text = ""
            if not text and runtime_text:
                text = runtime_text
                self._set_text_widget_text(back, text)
            return self._set_text_widget_text(front, text)

    def _copy_checkbox_state(self, source, target):
            if source is None or target is None or not hasattr(source, "isChecked") or not hasattr(target, "setChecked"):
                return False
            try:
                target.blockSignals(True)
                target.setChecked(bool(source.isChecked()))
                return True
            except Exception:
                return False
            finally:
                try:
                    target.blockSignals(False)
                except Exception:
                    pass

    def _copy_spin_state(self, source, target):
            if source is None or target is None or not hasattr(source, "value") or not hasattr(target, "setValue"):
                return False
            try:
                target.blockSignals(True)
                target.setValue(source.value())
                return True
            except Exception:
                return False
            finally:
                try:
                    target.blockSignals(False)
                except Exception:
                    pass

    def _set_readonly_text_if_changed(self, target, text):
            if target is None:
                return False
            value = str(text or "")
            current = ""
            try:
                if hasattr(target, "toPlainText"):
                    current = str(target.toPlainText() or "")
                elif hasattr(target, "text"):
                    current = str(target.text() or "")
            except Exception:
                current = ""
            if current == value:
                return False
            if hasattr(target, "setPlainText") and value.startswith(current):
                suffix = value[len(current):]
                if suffix:
                    try:
                        active_cursor = target.textCursor() if hasattr(target, "textCursor") else None
                        if hasattr(target, "blockSignals"):
                            target.blockSignals(True)
                        cursor = QtGui.QTextCursor(target.document())
                        cursor.movePosition(QtGui.QTextCursor.End)
                        cursor.insertText(suffix)
                        if active_cursor is not None and hasattr(target, "setTextCursor"):
                            target.setTextCursor(active_cursor)
                        return True
                    finally:
                        try:
                            target.blockSignals(False)
                        except Exception:
                            pass
            if hasattr(target, "setPlainText"):
                try:
                    if hasattr(target, "blockSignals"):
                        target.blockSignals(True)
                    target.setPlainText(value)
                    return True
                finally:
                    try:
                        target.blockSignals(False)
                    except Exception:
                        pass
            if hasattr(target, "setText"):
                target.setText(value)
                return True
            return False

    def _sync_backend_to_ui(self, *, force=False, lightweight=False):
            if lightweight and not force:
                # Keep MuseTalk preview rendering smooth in the Designer front-end:
                # status/diode mirroring is cheap, while full button/field mirroring
                # can steal UI-thread time from the 16 ms preview frame timer.
                self._mirror_runtime_status_widgets()
                self._mirror_pipeline_telemetry_widgets()
                return
            for object_name in self._combo_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                if self._combo_popup_is_open(front):
                    continue
                if force or not getattr(front, "hasFocus", lambda: False)():
                    self._copy_combo_state(back, front)
            for object_name in self._checkbox_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                self._copy_checkbox_state(back, front)
            for object_name in self._spin_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                self._copy_spin_state(back, front)
            for object_name in self._line_edit_sync_names():
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                if force or not getattr(front, "hasFocus", lambda: False)():
                    self._copy_text_state(back, front)
            self._mirror_runtime_text_views()
            self._mirror_pipeline_telemetry_widgets()
            self._mirror_runtime_status_widgets()
            self._mirror_runtime_button_state()
            self._mirror_runtime_selection_widgets()
            self._mirror_persona_runtime_widgets(force=force)
            self._copy_runtime_plain_text_state("sensory_pingpong_prompt_text", "sensory_pingpong_prompt")
            self._mirror_body_pose_runtime_widgets(force=force)
            self._mirror_vam_runtime_widgets(force=force)
            self._mirror_chunking_runtime_widgets(force=force)
            self._mirror_provider_runtime_labels()
            self._refresh_frontend_theme_controls()

    def _mirror_pipeline_telemetry_widgets(self):
            ready_bar = getattr(self, "_frontend_render_ready_bar", None)
            preview_bar = getattr(self, "_frontend_preview_playback_bar", None)
            hint = getattr(self, "_frontend_pipeline_telemetry_hint", None)
            if ready_bar is None and preview_bar is None and hint is None:
                return
            telemetry_widget = getattr(self.backend, "pipeline_telemetry_widget", None)
            if telemetry_widget is None:
                return
            try:
                raw_snapshot = shared_state.get_musetalk_pipeline_snapshot()
                preview_state = getattr(shared_state, "current_musetalk_frame_data", {}) or {}
                snapshot = self.backend._build_pipeline_visual_snapshot(raw_snapshot)
                telemetry_widget.update_snapshot(snapshot, preview_state)
            except Exception:
                return
            chunks = list((getattr(getattr(telemetry_widget, "ready_bar", None), "_snapshot", {}) or {}).get("chunks", []) or [])
            chunk_total = max(1, len(chunks))
            try:
                ready_progress = float(telemetry_widget.ready_bar._ready_progress())
            except Exception:
                ready_progress = 0.0
            try:
                preview_progress = float(telemetry_widget.preview_bar._preview_progress())
            except Exception:
                preview_progress = 0.0
            ready_value = int(round(max(0.0, min(ready_progress / float(chunk_total), 1.0)) * 1000.0))
            preview_value = int(round(max(0.0, min(preview_progress / float(chunk_total), 1.0)) * 1000.0))
            for bar, value, label, progress in (
                (ready_bar, ready_value, "Render Ready", ready_progress),
                (preview_bar, preview_value, "Preview / Playback", preview_progress),
            ):
                if bar is None:
                    continue
                try:
                    bar.setRange(0, 1000)
                    bar.setValue(value)
                    bar.setFormat(f"{label}: {progress:.2f}/{len(chunks)}")
                    bar.setVisible(True)
                except Exception:
                    pass
            if hint is not None and hasattr(hint, "setText"):
                try:
                    hint.setText(str(getattr(telemetry_widget, "summary_label").text() or "Telemetry appears during MuseTalk and VaM replies."))
                except Exception:
                    pass

    def _mirror_chunking_runtime_widgets(self, *, force=False):
            for key, spec in UI_SHELL_CHUNKING_SPECS.items():
                slider = self._ui_object(str(spec.get("widget") or ""))
                if slider is None or not hasattr(slider, "setValue"):
                    continue
                backend_slider = getattr(self.backend, "chunking_sliders", {}).get(str(key))
                if backend_slider is not None and hasattr(backend_slider, "value"):
                    try:
                        value = backend_slider.value()
                    except Exception:
                        value = RUNTIME_CONFIG.get(str(key), spec.get("default", 0))
                else:
                    value = RUNTIME_CONFIG.get(str(key), spec.get("default", 0))
                try:
                    is_int = bool(spec.get("is_int", True))
                    value = int(round(float(value))) if is_int else round(float(value), 2)
                    slider_value = int(round(float(value) * float(spec.get("scale", 1) or 1)))
                except Exception:
                    value = int(spec.get("default", 0) or 0)
                    slider_value = int(round(value * float(spec.get("scale", 1) or 1)))
                if force or not getattr(slider, "isSliderDown", lambda: False)():
                    was_blocked = False
                    try:
                        was_blocked = bool(slider.blockSignals(True))
                        slider.setValue(slider_value)
                    except Exception:
                        pass
                    finally:
                        try:
                            slider.blockSignals(was_blocked)
                        except Exception:
                            pass
                _ui_shell_update_chunking_label(self.window, str(key), value)
            self._mirror_chunking_profile_combo(force=force)

    def _mirror_chunking_profile_combo(self, *, force=False):
            front = self._ui_object("chunking_profile_combo")
            back = self._backend_widget("chunking_profile_combo")
            if front is None or back is None:
                return
            if self._combo_popup_is_open(front):
                return
            if force or not getattr(front, "hasFocus", lambda: False)():
                self._copy_combo_state(back, front)

    def _mirror_persona_runtime_widgets(self, *, force=False):
            for object_name in ("voice_combo",):
                front = self._ui_object(object_name)
                back = self._backend_widget(object_name)
                if front is None or back is None:
                    continue
                if not self._combo_popup_is_open(front):
                    self._copy_combo_state(back, front)
            self._copy_runtime_plain_text_state("emotional_text", "emotional_instructions")
            self._copy_runtime_plain_text_state("system_prompt_text", "system_prompt")

    def _mirror_body_pose_runtime_widgets(self, *, force=False):
            pose_sliders = getattr(self.backend, "pose_sliders", {})
            body_state = getattr(engine, "CURRENT_BODY_STATE", {}) or {}
            for key, spec in UI_SHELL_BODY_POSE_SPECS.items():
                slider = self._ui_object(str(spec.get("widget") or ""))
                if slider is None or not hasattr(slider, "setValue"):
                    continue
                backend_slider = pose_sliders.get(str(key)) if isinstance(pose_sliders, dict) else None
                if backend_slider is not None and hasattr(backend_slider, "value"):
                    try:
                        value = backend_slider.value()
                    except Exception:
                        value = body_state.get(str(key), spec.get("default", 0.0))
                else:
                    value = body_state.get(str(key), spec.get("default", 0.0))
                raw_value = _ui_shell_body_value_to_slider_raw(str(key), value)
                if force or not getattr(slider, "isSliderDown", lambda: False)():
                    was_blocked = False
                    try:
                        was_blocked = bool(slider.blockSignals(True))
                        slider.setValue(raw_value)
                    except Exception:
                        pass
                    finally:
                        try:
                            slider.blockSignals(was_blocked)
                        except Exception:
                            pass
                _ui_shell_update_body_label(self.window, str(key), value)

    def _mirror_vam_runtime_widgets(self, *, force=False):
            bridge_root_front = self._ui_object("vam_bridge_root_edit")
            bridge_root_back = self._backend_widget("vam_bridge_root_edit")
            if bridge_root_front is not None and hasattr(bridge_root_front, "setReadOnly"):
                try:
                    bridge_root_front.setReadOnly(True)
                except Exception:
                    pass
            if bridge_root_front is not None and bridge_root_back is not None:
                if force or not getattr(bridge_root_front, "hasFocus", lambda: False)():
                    self._copy_text_state(bridge_root_back, bridge_root_front)

            def line_text(object_name, default=""):
                widget = self._ui_object(object_name)
                if widget is not None and hasattr(widget, "text"):
                    try:
                        return str(widget.text() or "").strip()
                    except Exception:
                        pass
                widget = self._backend_widget(object_name)
                if widget is not None and hasattr(widget, "text"):
                    try:
                        return str(widget.text() or "").strip()
                    except Exception:
                        pass
                return str(default or "").strip()

            def checked_text(object_name):
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "isChecked"):
                    widget = self._backend_widget(object_name)
                try:
                    return "on" if bool(widget.isChecked()) else "off"
                except Exception:
                    return "off"

            def spin_value(object_name, default):
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "value"):
                    widget = self._backend_widget(object_name)
                try:
                    return int(widget.value())
                except Exception:
                    return int(default)

            def set_label(object_name, value):
                label = self._ui_object(object_name)
                if label is not None and hasattr(label, "setText"):
                    try:
                        label.setText(str(value))
                    except Exception:
                        pass

            vam_root = line_text("vam_root_edit", RUNTIME_CONFIG.get("vam_root", ""))
            bridge_root = line_text("vam_bridge_root_edit", RUNTIME_CONFIG.get("vam_bridge_root", ""))
            target_atom = line_text("vam_target_atom_uid_edit", RUNTIME_CONFIG.get("vam_target_atom_uid", "Person")) or "Person"
            target_storable = line_text("vam_target_storable_id_edit", RUNTIME_CONFIG.get("vam_target_storable_id", ""))
            vmc_host = line_text("vam_vmc_host_edit", RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1")) or "127.0.0.1"
            vmc_port = spin_value("vam_vmc_port_spin", RUNTIME_CONFIG.get("vam_vmc_port", 39539))

            set_label("vam_summary_label", f"VaM target: {target_atom}" + (f" / {target_storable}" if target_storable else ""))
            set_label("vam_runtime_label", f"VMC {checked_text('vam_vmc_enabled_checkbox')} | File bridge {checked_text('vam_bridge_enabled_checkbox')} | Head audio {checked_text('vam_play_audio_in_vam_checkbox')}")
            set_label("vam_bridge_status_label", f"Bridge root: {bridge_root or '(derived when VaM root is set)'}")
            set_label("vam_bridge_detail_label", f"VaM root: {vam_root or '(not set)'} | VMC: {vmc_host}:{vmc_port} | Timeline auto-resume {checked_text('vam_timeline_auto_resume_checkbox')}")

    def _mirror_runtime_text_views(self):
            backend_console = self._backend_widget("console_edit")
            frontend_console = self._ui_object("console_edit")
            if backend_console is not None and frontend_console is not None and hasattr(backend_console, "toPlainText"):
                if hasattr(frontend_console, "setReadOnly"):
                    try:
                        frontend_console.setReadOnly(True)
                    except Exception:
                        pass
                preserve_scroll = None
                console_auto_scroll = bool(getattr(self.backend, "console_auto_scroll", True))
                if not console_auto_scroll:
                    preserve_scroll = self._capture_text_scroll_state(frontend_console)
                changed = self._set_readonly_text_if_changed(frontend_console, backend_console.toPlainText())
                if changed and console_auto_scroll:
                    self._schedule_text_scroll_to_bottom(frontend_console)
                elif changed and preserve_scroll is not None:
                    self._restore_text_scroll_state(frontend_console, preserve_scroll)
                    QtCore.QTimer.singleShot(0, lambda w=frontend_console, state=preserve_scroll: self._restore_text_scroll_state(w, state))
            backend_chat = self._backend_widget("chat_edit")
            frontend_chat = self._ui_object("chat_edit")
            if backend_chat is not None and frontend_chat is not None and hasattr(backend_chat, "toPlainText"):
                if hasattr(frontend_chat, "setReadOnly") and not bool(getattr(self.backend, "chat_edit_mode", False)):
                    try:
                        frontend_chat.setReadOnly(True)
                    except Exception:
                        pass
                if not bool(getattr(self.backend, "chat_edit_mode", False)):
                    preserve_scroll = None
                    chat_auto_scroll = bool(getattr(self.backend, "chat_auto_scroll", True))
                    if not chat_auto_scroll:
                        preserve_scroll = self._capture_text_scroll_state(frontend_chat)
                    changed = self._set_readonly_text_if_changed(frontend_chat, backend_chat.toPlainText())
                    if changed and chat_auto_scroll:
                        self._schedule_text_scroll_to_bottom(frontend_chat)
                    elif changed and preserve_scroll is not None:
                        self._restore_text_scroll_state(frontend_chat, preserve_scroll)
                        QtCore.QTimer.singleShot(0, lambda w=frontend_chat, state=preserve_scroll: self._restore_text_scroll_state(w, state))

    def _mirror_runtime_status_widgets(self):
            for object_name in ("console_status", "chat_status", "mic_status_label"):
                backend_widget = self._backend_widget(object_name)
                frontend_widget = self._ui_object(object_name)
                if backend_widget is None or frontend_widget is None or not hasattr(backend_widget, "text") or not hasattr(frontend_widget, "setText"):
                    continue
                try:
                    frontend_widget.setText(str(backend_widget.text() or ""))
                except Exception:
                    continue
                if hasattr(frontend_widget, "setStyleSheet") and hasattr(backend_widget, "styleSheet"):
                    try:
                        frontend_widget.setStyleSheet(str(backend_widget.styleSheet() or ""))
                    except Exception:
                        pass
            for object_name in ("listen_diode", "mic_diode"):
                backend_widget = self._backend_widget(object_name)
                frontend_widget = self._ui_object(object_name)
                if backend_widget is None or frontend_widget is None or not hasattr(frontend_widget, "setStyleSheet"):
                    continue
                try:
                    frontend_widget.setStyleSheet(str(backend_widget.styleSheet() or ""))
                except Exception:
                    pass
                frontend_widget.setVisible(True)
                try:
                    frontend_widget.setEnabled(bool(backend_widget.isEnabled()))
                except Exception:
                    pass
                try:
                    frontend_widget.setFixedSize(16, 16)
                except Exception:
                    pass
                try:
                    if hasattr(frontend_widget, "setFrameShape"):
                        frontend_widget.setFrameShape(QtWidgets.QFrame.NoFrame)
                except Exception:
                    pass
            self._mirror_console_chat_pause_frame()

    def _mirror_console_chat_pause_frame(self):
            paused = bool(getattr(self.backend, "_chat_runtime_border_paused", False))
            if getattr(self, "_frontend_console_chat_pause_frame", None) == paused:
                return
            self._frontend_console_chat_pause_frame = paused
            for object_name in ("system_console_tab", "chat_runtime_tab"):
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "setStyleSheet"):
                    continue
                base_attr = "_nc_real_ui_base_stylesheet"
                if not hasattr(widget, base_attr):
                    try:
                        setattr(widget, base_attr, str(widget.styleSheet() or ""))
                    except Exception:
                        setattr(widget, base_attr, "")
                if paused:
                    widget.setStyleSheet(
                        f"QWidget#{object_name} {{ border: 2px solid #d84a4a; border-radius: 10px; }}"
                    )
                else:
                    widget.setStyleSheet(str(getattr(widget, base_attr, "") or ""))

    def _mirror_runtime_button_state(self):
            for object_name in (
                "btn_start_engine",
                "btn_stop_engine",
                "btn_reset_chat",
                "btn_regenerate",
                "btn_retry",
                "btn_pause",
                "btn_skip",
                "btn_skip_user",
                "console_autoscroll_button",
                "chat_autoscroll_button",
                "btn_push_to_talk",
                "btn_model_refresh",
                "btn_musetalk_avatar_pack_refresh",
                "btn_preset_refresh",
                "btn_preset_load",
                "btn_preset_save",
                "btn_preset_save_as",
                "btn_preset_delete",
                "btn_dry_run_start",
                "btn_dry_run_stop",
                "btn_dry_run_apply",
                "btn_body_load",
                "btn_body_save",
                "btn_body_save_as",
                "btn_body_delete",
                "btn_hand_doctor",
                "btn_musetalk_preview",
                "btn_musetalk_avatar_focus",
                "btn_start_vam_desktop",
                "btn_start_vam_vr",
                "btn_vam_hide_interface",
            ):
                backend_widget = self._backend_widget(object_name)
                frontend_widget = self._ui_object(object_name)
                if backend_widget is None or frontend_widget is None:
                    continue
                if hasattr(frontend_widget, "setEnabled") and hasattr(backend_widget, "isEnabled"):
                    try:
                        frontend_widget.setEnabled(bool(backend_widget.isEnabled()))
                    except Exception:
                        pass
                if hasattr(frontend_widget, "setText") and hasattr(backend_widget, "text"):
                    try:
                        frontend_widget.setText(str(backend_widget.text() or ""))
                    except Exception:
                        pass
            self._mirror_chat_edit_state()
            self._mirror_dry_run_widgets()
            self._mirror_audio_story_duplicate_widgets()
            self._mirror_provider_model_widgets()

    def _mirror_chat_edit_state(self):
            frontend_chat = self._ui_object("chat_edit")
            if frontend_chat is not None and hasattr(frontend_chat, "setReadOnly"):
                try:
                    frontend_chat.setReadOnly(not bool(getattr(self.backend, "chat_edit_mode", False)))
                except Exception:
                    pass
            edit_button = self._ui_object("chat_edit_mode_button")
            if edit_button is not None and hasattr(edit_button, "setVisible"):
                try:
                    edit_button.setVisible(not bool(getattr(self.backend, "chat_edit_mode", False)))
                except Exception:
                    pass
            apply_button = self._ui_object("chat_apply_edit_button")
            if apply_button is not None and hasattr(apply_button, "setVisible"):
                try:
                    apply_button.setVisible(bool(getattr(self.backend, "chat_edit_mode", False)))
                except Exception:
                    pass
            cancel_button = self._ui_object("chat_cancel_edit_button")
            if cancel_button is not None and hasattr(cancel_button, "setVisible"):
                try:
                    cancel_button.setVisible(bool(getattr(self.backend, "chat_edit_mode", False)))
                except Exception:
                    pass

    def _mirror_dry_run_widgets(self):
            backend_status = self._backend_widget("dry_run_status_label")
            frontend_status = self._ui_object("dry_run_status_label")
            if backend_status is not None and frontend_status is not None and hasattr(backend_status, "text") and hasattr(frontend_status, "setText"):
                try:
                    frontend_status.setText(str(backend_status.text() or ""))
                except Exception:
                    pass
            backend_summary = self._backend_widget("dry_run_summary")
            frontend_summary = self._ui_object("dry_run_summary")
            if backend_summary is not None and frontend_summary is not None:
                self._copy_text_state(backend_summary, frontend_summary)

    def _mirror_provider_model_widgets(self):
            backend_budget = self._backend_widget("model_budget_label")
            frontend_budget = self._ui_object("model_budget_label")
            if backend_budget is not None and frontend_budget is not None and hasattr(backend_budget, "text") and hasattr(frontend_budget, "setText"):
                try:
                    frontend_budget.setText(str(backend_budget.text() or ""))
                except Exception:
                    pass
            backend_vision = self._backend_widget("model_requires_vision_checkbox")
            frontend_vision = self._ui_object("model_requires_vision_checkbox")
            if backend_vision is not None and frontend_vision is not None:
                self._copy_checkbox_state(backend_vision, frontend_vision)
            for object_name in ("btn_preset_save", "btn_preset_save_as"):
                backend_button = self._backend_widget(object_name)
                frontend_button = self._ui_object(object_name)
                if backend_button is None or frontend_button is None:
                    continue
                if hasattr(frontend_button, "setStyleSheet") and hasattr(backend_button, "styleSheet"):
                    try:
                        frontend_button.setStyleSheet(str(backend_button.styleSheet() or ""))
                    except Exception:
                        pass

    def _mirror_runtime_selection_widgets(self):
            for object_name in (
                "limit_response_checkbox",
                "max_response_tokens_spin",
                "engine_combo",
                "input_mode_combo",
                "input_role_combo",
                "stream_mode_combo",
                "tts_backend_combo",
                "musetalk_vram_combo",
                "musetalk_avatar_pack_combo",
                "visual_reply_mode_combo",
                "visual_reply_provider_combo",
                "visual_reply_size_combo",
                "sensory_feedback_source_combo",
                "chat_font_size_combo",
                "voice_combo",
                "body_combo",
                "emotion_combo",
                "live_sync_checkbox",
                "vam_vmc_enabled_checkbox",
                "vam_bridge_enabled_checkbox",
                "vam_play_audio_in_vam_checkbox",
                "vam_timeline_auto_resume_checkbox",
                "vam_vmc_port_spin",
                "chunking_profile_combo",
                "performance_profile_combo",
                "dry_run_auto_replies_checkbox",
                "dry_run_target_spin",
                "musetalk_loop_fade_spin",
                "visual_reply_model_edit",
                "vam_root_edit",
                "vam_bridge_root_edit",
                "vam_target_atom_uid_edit",
                "vam_target_storable_id_edit",
                "vam_vmc_host_edit",
            ):
                backend_widget = self._backend_widget(object_name)
                frontend_widget = self._ui_object(object_name)
                if backend_widget is None or frontend_widget is None:
                    continue
                if hasattr(frontend_widget, "setEnabled") and hasattr(backend_widget, "isEnabled"):
                    try:
                        frontend_widget.setEnabled(bool(backend_widget.isEnabled()))
                    except Exception:
                        pass

    def _mirror_audio_story_duplicate_widgets(self):
            controller = self._audio_story_controller()
            if controller is None:
                return
            frontend_path = self._ui_object("audio_file_path_edit")
            backend_path = getattr(controller, "audio_story_path_edit", None)
            if frontend_path is not None and backend_path is not None:
                self._copy_text_state(backend_path, frontend_path)
                if hasattr(frontend_path, "setReadOnly"):
                    try:
                        frontend_path.setReadOnly(True)
                    except Exception:
                        pass
            frontend_combo = self._ui_object("audio_story_playback_combo")
            backend_combo = getattr(controller, "audio_story_playback_mode_combo", None)
            if frontend_combo is not None and backend_combo is not None:
                self._copy_combo_state(backend_combo, frontend_combo)
                if hasattr(frontend_combo, "setEnabled") and hasattr(backend_combo, "isEnabled"):
                    try:
                        frontend_combo.setEnabled(bool(backend_combo.isEnabled()))
                    except Exception:
                        pass
            frontend_transcribe_slider = self._ui_object("transcribe_seconds_slider")
            backend_transcribe_slider = getattr(controller, "audio_story_transcribe_seconds_slider", None)
            if frontend_transcribe_slider is not None and backend_transcribe_slider is not None:
                if hasattr(frontend_transcribe_slider, "setRange") and hasattr(backend_transcribe_slider, "minimum") and hasattr(backend_transcribe_slider, "maximum"):
                    try:
                        frontend_transcribe_slider.setRange(int(backend_transcribe_slider.minimum()), int(backend_transcribe_slider.maximum()))
                    except Exception:
                        pass
                if not (hasattr(frontend_transcribe_slider, "isSliderDown") and frontend_transcribe_slider.isSliderDown()):
                    self._copy_spin_state(backend_transcribe_slider, frontend_transcribe_slider)
                if hasattr(frontend_transcribe_slider, "setEnabled") and hasattr(backend_transcribe_slider, "isEnabled"):
                    try:
                        frontend_transcribe_slider.setEnabled(bool(backend_transcribe_slider.isEnabled()))
                    except Exception:
                        pass
            button_pairs = (
                ("import_audio_button", "audio_story_import_button"),
                ("transcribe_audio_button", "audio_story_transcribe_button"),
                ("audio_story_play_button", "audio_story_play_button"),
                ("audio_story_pause_button", "audio_story_pause_button"),
                ("audio_story_stop_button", "audio_story_stop_button"),
            )
            for frontend_name, backend_name in button_pairs:
                frontend_widget = self._ui_object(frontend_name)
                backend_widget = getattr(controller, backend_name, None)
                if frontend_widget is None or backend_widget is None:
                    continue
                if hasattr(frontend_widget, "setEnabled") and hasattr(backend_widget, "isEnabled"):
                    try:
                        frontend_widget.setEnabled(bool(backend_widget.isEnabled()))
                    except Exception:
                        pass
                if hasattr(frontend_widget, "setText") and hasattr(backend_widget, "text"):
                    try:
                        frontend_widget.setText(str(backend_widget.text() or ""))
                    except Exception:
                        pass
            frontend_seek = self._ui_object("audio_story_seek_slider")
            backend_seek = getattr(controller, "audio_story_position_slider", None)
            if frontend_seek is not None and backend_seek is not None:
                if hasattr(frontend_seek, "setRange") and hasattr(backend_seek, "minimum") and hasattr(backend_seek, "maximum"):
                    try:
                        frontend_seek.setRange(int(backend_seek.minimum()), int(backend_seek.maximum()))
                    except Exception:
                        pass
                if not (hasattr(frontend_seek, "isSliderDown") and frontend_seek.isSliderDown()):
                    self._copy_spin_state(backend_seek, frontend_seek)
                if hasattr(frontend_seek, "setEnabled") and hasattr(backend_seek, "isEnabled"):
                    try:
                        frontend_seek.setEnabled(bool(backend_seek.isEnabled()))
                    except Exception:
                        pass
            frontend_position = self._ui_object("audio_story_position_label")
            backend_time = getattr(controller, "audio_story_time_label", None)
            backend_status = getattr(controller, "audio_story_status_label", None)
            if frontend_position is not None and backend_time is not None and hasattr(backend_time, "text") and hasattr(frontend_position, "setText"):
                try:
                    frontend_position.setText(str(backend_time.text() or ""))
                except Exception:
                    pass
            if frontend_position is not None and backend_status is not None and hasattr(backend_status, "text") and hasattr(frontend_position, "setToolTip"):
                try:
                    frontend_position.setToolTip(str(backend_status.text() or ""))
                except Exception:
                    pass

    def _mirror_provider_runtime_labels(self):
            settings_label = self._ui_object("provider_settings_label")
            generation_label = self._ui_object("provider_generation_label")
            fields_placeholder = self._ui_object("chat_provider_fields_placeholder")
            generation_placeholder = self._ui_object("chat_provider_generation_fields_placeholder")
            runtime_box = self._ui_object("chat_runtime_box")
            tts_runtime_box = self._ui_object("tts_runtime_box")
            backend_settings_section = getattr(self.backend, "chat_provider_settings_section", None)
            backend_generation_section = getattr(self.backend, "chat_provider_generation_section", None)
            backend_runtime_section = getattr(self.backend, "chat_runtime_section", None)
            backend_tts_runtime_section = getattr(self.backend, "tts_runtime_section", None)
            backend_hint_label = getattr(self.backend, "chat_provider_hint_label", None)
            if settings_label is not None and backend_settings_section is not None and hasattr(backend_settings_section, "toggle_button"):
                try:
                    full_text = str(backend_settings_section.toggle_button.text() or "Provider Settings")
                    base_title, summary = _split_collapsible_section_text(full_text, "Provider Settings")
                    settings_label.setText(base_title or "Provider Settings")
                    settings_label.setToolTip(full_text)
                    if summary and fields_placeholder is not None and hasattr(fields_placeholder, "setToolTip"):
                        fields_placeholder.setToolTip(summary)
                except Exception:
                    pass
            if generation_label is not None and backend_generation_section is not None and hasattr(backend_generation_section, "toggle_button"):
                try:
                    full_text = str(backend_generation_section.toggle_button.text() or "Generation Settings")
                    base_title, summary = _split_collapsible_section_text(full_text, "Generation Settings")
                    generation_label.setText(base_title or "Generation Settings")
                    generation_label.setToolTip(full_text)
                    if summary and generation_placeholder is not None and hasattr(generation_placeholder, "setToolTip"):
                        generation_placeholder.setToolTip(summary)
                except Exception:
                    pass
            if runtime_box is not None and hasattr(runtime_box, "setTitle") and backend_runtime_section is not None and hasattr(backend_runtime_section, "toggle_button"):
                try:
                    self._set_frontend_collapsible_group_summary(
                        runtime_box,
                        str(backend_runtime_section.toggle_button.text() or "Chat Runtime"),
                        "Chat Runtime",
                    )
                except Exception:
                    pass
            if tts_runtime_box is not None and hasattr(tts_runtime_box, "setTitle") and backend_tts_runtime_section is not None and hasattr(backend_tts_runtime_section, "toggle_button"):
                try:
                    self._set_frontend_collapsible_group_summary(
                        tts_runtime_box,
                        str(backend_tts_runtime_section.toggle_button.text() or "TTS Runtime"),
                        "TTS Runtime",
                    )
                except Exception:
                    pass
            if fields_placeholder is not None and backend_hint_label is not None and hasattr(backend_hint_label, "text"):
                try:
                    fields_placeholder.setText(str(backend_hint_label.text() or ""))
                except Exception:
                    pass
            if generation_placeholder is not None and hasattr(generation_placeholder, "setText"):
                try:
                    generation_placeholder.setText("Live runtime generation fields are mounted above.")
                except Exception:
                    pass

    def _scroll_text_to_bottom(self, widget):
            if widget is None or not hasattr(widget, "verticalScrollBar"):
                return
            try:
                if hasattr(widget, "moveCursor"):
                    widget.moveCursor(QtGui.QTextCursor.End)
                if hasattr(widget, "ensureCursorVisible"):
                    widget.ensureCursorVisible()
                scrollbar = widget.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
            except Exception:
                pass

    def _schedule_text_scroll_to_bottom(self, widget):
            self._scroll_text_to_bottom(widget)
            for delay_ms in (0, 50, 150):
                QtCore.QTimer.singleShot(delay_ms, lambda w=widget: self._scroll_text_to_bottom(w))

    def _capture_text_scroll_state(self, widget):
            if widget is None or not hasattr(widget, "verticalScrollBar"):
                return None
            try:
                scrollbar = widget.verticalScrollBar()
                maximum = max(1, int(scrollbar.maximum()))
                value = int(scrollbar.value())
                return {"value": value, "ratio": float(value) / float(maximum)}
            except Exception:
                return None

    def _restore_text_scroll_state(self, widget, state):
            if widget is None or not state or not hasattr(widget, "verticalScrollBar"):
                return
            try:
                scrollbar = widget.verticalScrollBar()
                maximum = int(scrollbar.maximum())
                value = int(state.get("value", 0) or 0)
                ratio = float(state.get("ratio", 0.0) or 0.0)
                target = min(max(value, 0), maximum)
                if maximum > 0 and target == 0 and ratio > 0.0:
                    target = int(round(maximum * ratio))
                scrollbar.setValue(min(max(target, 0), maximum))
            except Exception:
                pass
