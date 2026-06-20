"""RealUiSyncMirrorMixin extracted from real_ui_sync.py."""

from PySide6 import QtCore, QtGui, QtWidgets


def configure_real_ui_sync_mirrors_dependencies(namespace):
    globals().update(dict(namespace or {}))


class RealUiSyncMirrorMixin:
    def _invoke_mirror_addon_capability(self, addon_id, capability, payload=None, default=None):
            callback = getattr(self.backend, "_invoke_addon_capability", None)
            if not callable(callback):
                return default
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(addon_id, capability, payload, default=default)

    def _invoke_all_mirror_addon_capabilities(self, capability, payload=None):
            callback = getattr(self.backend, "_invoke_all_addon_capabilities", None)
            if not callable(callback):
                return []
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(capability, payload)

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
                raw_snapshot = self.backend._invoke_addon_service_capability(
                    "avatar_provider_registry",
                    "runtime.pipeline_snapshot",
                    {},
                    default={},
                    provider_id="musetalk",
                )
                preview_state = self.backend._invoke_addon_service_capability(
                    "avatar_provider_registry",
                    "runtime.preview.current_state",
                    {},
                    default={},
                    provider_id="musetalk",
                )
                snapshot = self.backend._build_pipeline_visual_snapshot(raw_snapshot)
                telemetry_widget.update_snapshot(snapshot, dict(preview_state or {}))
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
            sync_use_wav = getattr(self.backend, "_sync_use_wav_file_checkbox", None)
            if callable(sync_use_wav):
                sync_use_wav()
            front = self._ui_object("use_wav_file_checkbox")
            back = self._backend_widget("use_wav_file_checkbox")
            if front is not None and back is not None:
                self._copy_checkbox_state(back, front)
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

    def _mirror_addon_runtime_widgets(self, *, force=False):
            self._invoke_all_mirror_addon_capabilities(
                "real_ui.mirror_runtime_widgets",
                {"force": bool(force)},
            )

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
                    border_style = f"QWidget#{object_name} {{ border: 2px solid #d84a4a; border-radius: 10px; }}"
                    if str(widget.styleSheet() or "") != border_style:
                        widget.setStyleSheet(border_style)
                else:
                    base_style = str(getattr(widget, base_attr, "") or "")
                    if str(widget.styleSheet() or "") != base_style:
                        widget.setStyleSheet(base_style)
            self._frontend_console_chat_pause_frame = paused

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
                self._copy_widget_tooltip(backend_widget, frontend_widget)
            self._mirror_chat_edit_state()
            self._mirror_dry_run_widgets()
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
            core_names = (
                "limit_response_checkbox",
                "max_response_tokens_spin",
                "engine_combo",
                "input_mode_combo",
                "input_role_combo",
                "stream_mode_combo",
                "stt_backend_combo",
                "stt_model_combo",
                "stt_language_combo",
                "tts_backend_combo",
                "sensory_feedback_source_combo",
                "chat_font_size_combo",
                "voice_combo",
                "use_wav_file_checkbox",
                "body_combo",
                "emotion_combo",
                "live_sync_checkbox",
                "chunking_profile_combo",
                "performance_profile_combo",
                "dry_run_auto_replies_checkbox",
                "dry_run_target_spin",
            )
            addon_names = set()
            addon_names.update(self._addon_sync_widget_names("combo"))
            addon_names.update(self._addon_sync_widget_names("checkbox"))
            addon_names.update(self._addon_sync_widget_names("spin"))
            addon_names.update(self._addon_sync_widget_names("line_edit"))
            for object_name in tuple(core_names) + tuple(sorted(addon_names)):
                backend_widget = self._backend_widget(object_name)
                frontend_widget = self._ui_object(object_name)
                if backend_widget is None or frontend_widget is None:
                    continue
                if backend_widget is frontend_widget:
                    continue
                if hasattr(frontend_widget, "setEnabled") and hasattr(backend_widget, "isEnabled"):
                    try:
                        frontend_widget.setEnabled(bool(backend_widget.isEnabled()))
                    except Exception:
                        pass

    def _visual_reply_runtime_summary_text(self, backend_text):
            fallback = "Visual Reply Runtime"
            try:
                _title, summary = _split_collapsible_section_text(str(backend_text or fallback), fallback)
                if summary:
                    return str(backend_text or fallback)
            except Exception:
                pass

            def widget_for(name):
                widget = self._ui_object(name)
                if widget is not None:
                    return widget
                try:
                    return self._backend_widget(name)
                except Exception:
                    return None

            def combo_text(name, default=""):
                widget = widget_for(name)
                if widget is not None and hasattr(widget, "currentText"):
                    try:
                        text = str(widget.currentText() or "").strip()
                        if text:
                            return text
                    except Exception:
                        pass
                return str(default or "").strip()

            def line_text(name, default=""):
                widget = widget_for(name)
                if widget is not None and hasattr(widget, "text"):
                    try:
                        text = str(widget.text() or "").strip()
                        if text:
                            return text
                    except Exception:
                        pass
                return str(default or "").strip()

            mode = combo_text("visual_reply_mode_combo", "Auto")
            if mode.lower() == "off":
                return f"{fallback} - Off"
            provider = combo_text("visual_reply_provider_combo", "OpenAI")
            model = line_text("visual_reply_model_edit", "")
            if provider and model:
                return f"{fallback} - {provider} / {model}"
            if provider:
                return f"{fallback} - {provider}"
            return str(backend_text or fallback)

    def _mirror_provider_runtime_labels(self):
            settings_label = self._ui_object("provider_settings_label")
            generation_label = self._ui_object("provider_generation_label")
            fields_placeholder = self._ui_object("chat_provider_fields_placeholder")
            generation_placeholder = self._ui_object("chat_provider_generation_fields_placeholder")
            runtime_box = self._ui_object("chat_runtime_box")
            stt_runtime_box = self._ui_object("stt_runtime_box")
            tts_runtime_box = self._ui_object("tts_runtime_box")
            visual_reply_runtime_box = self._ui_object("visual_reply_runtime_box")
            backend_settings_section = getattr(self.backend, "chat_provider_settings_section", None)
            backend_generation_section = getattr(self.backend, "chat_provider_generation_section", None)
            backend_runtime_section = getattr(self.backend, "chat_runtime_section", None)
            backend_stt_runtime_section = getattr(self.backend, "stt_runtime_section", None)
            backend_tts_runtime_section = getattr(self.backend, "tts_runtime_section", None)
            backend_visual_reply_runtime_section = getattr(self.backend, "visual_reply_runtime_section", None)
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
                        str(backend_runtime_section.toggle_button.text() or "LLM Runtime"),
                        "LLM Runtime",
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
            if stt_runtime_box is not None and hasattr(stt_runtime_box, "setTitle") and backend_stt_runtime_section is not None and hasattr(backend_stt_runtime_section, "toggle_button"):
                try:
                    self._set_frontend_collapsible_group_summary(
                        stt_runtime_box,
                        str(backend_stt_runtime_section.toggle_button.text() or "STT Runtime"),
                        "STT Runtime",
                    )
                except Exception:
                    pass
            if visual_reply_runtime_box is not None and hasattr(visual_reply_runtime_box, "setTitle") and backend_visual_reply_runtime_section is not None and hasattr(backend_visual_reply_runtime_section, "toggle_button"):
                try:
                    self._set_frontend_collapsible_group_summary(
                        visual_reply_runtime_box,
                        self._visual_reply_runtime_summary_text(
                            str(backend_visual_reply_runtime_section.toggle_button.text() or "Visual Reply Runtime")
                        ),
                        "Visual Reply Runtime",
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
