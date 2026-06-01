from PySide6 import QtCore, QtWidgets


def configure_real_ui_binding_dependencies(namespace):
    """Inject qt_app-owned constants used by the extracted real-UI binding mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealBindingMixin:
    """Signal wiring helpers for connecting main.ui controls to backend/runtime callbacks."""

    def _invoke_backend_addon_capability(self, addon_id, capability, payload=None, default=None):
            callback = getattr(self.backend, "_invoke_addon_capability", None)
            if not callable(callback):
                return default
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(addon_id, capability, payload, default=default)

    def _invoke_backend_service_capability(self, service_id, capability, payload=None, default=None, **metadata_match):
            callback = getattr(self.backend, "_invoke_addon_service_capability", None)
            if not callable(callback):
                return default
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(service_id, capability, payload, default=default, **metadata_match)

    def _invoke_all_backend_addon_capabilities(self, capability, payload=None):
            callback = getattr(self.backend, "_invoke_all_addon_capabilities", None)
            if not callable(callback):
                return []
            payload = dict(payload or {})
            payload.setdefault("bridge", self)
            return callback(capability, payload)

    def _visual_reply_addon_id(self):
            callback = getattr(self.backend, "_addon_id_for_ui_role", None)
            if callable(callback):
                return callback("visual_reply", fallback="")
            return ""

    def _bind_basic_runtime_mirrors(self):
            bindings = {
                "console_autoscroll_button": getattr(self.backend, "toggle_console_autoscroll", None),
                "console_clear_button": getattr(self.backend, "clear_console", None),
                "chat_autoscroll_button": getattr(self.backend, "toggle_chat_autoscroll", None),
                "chat_clear_button": getattr(self.backend, "clear_chat", None),
            }
            for object_name, handler in bindings.items():
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "clicked") or not callable(handler):
                    continue
                widget.clicked.connect(lambda _checked=False, callback=handler: self._invoke_runtime_callback(callback))

    def _bind_lifecycle_controls(self):
            start_button = self._ui_object("btn_start_engine")
            if start_button is not None and hasattr(start_button, "clicked"):
                start_button.clicked.connect(self._start_engine_from_ui_real)
            stop_button = self._ui_object("btn_stop_engine")
            if stop_button is not None and hasattr(stop_button, "clicked"):
                stop_button.clicked.connect(self._engine_lifecycle_service.stop_engine)
            reset_button = self._ui_object("btn_reset_chat")
            if reset_button is not None and hasattr(reset_button, "clicked"):
                reset_button.clicked.connect(self._engine_lifecycle_service.reset_chat_memory)

    def _bind_runtime_action_controls(self):
            button_actions = {
                "btn_regenerate": "regenerate_response",
                "btn_retry": "retry_user_input",
                "btn_pause": "pause_speech",
                "btn_skip": "skip_speech",
                "btn_skip_user": "skip_user_reply",
            }
            for object_name, action_name in button_actions.items():
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "clicked"):
                    continue
                widget.clicked.connect(lambda _checked=False, action=action_name: self._runtime_control_service.trigger(action))

    def _bind_chat_context_controls(self):
            bindings = {
                "chat_quick_save_button": self._chat_context_service.quick_save_chat_context,
                "chat_quick_load_button": self._chat_context_service.quick_load_chat_context,
                "btn_save_chat_session": self._chat_context_service.save_chat_context,
                "btn_save_chat_session_as": getattr(self._chat_context_service, "save_chat_context_as", None),
                "btn_load_chat_session": self._chat_context_service.load_chat_context,
                "btn_reset_chat_session": self._chat_context_service.reset_chat_memory,
                "btn_review_long_term_memory": getattr(self.backend, "review_long_term_memory", None),
                "btn_batch_update_long_term_memory": getattr(self.backend, "batch_update_long_term_memory_now", None),
                "btn_forget_long_term_memory": getattr(self.backend, "forget_long_term_memory", None),
            }
            for object_name, handler in bindings.items():
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "clicked") or not callable(handler):
                    continue
                widget.clicked.connect(lambda _checked=False, callback=handler: self._invoke_runtime_callback(callback))

    def _bind_tutorial_runtime_controls(self):
            # Tutorial overlays need the visible main.ui window for targeting, while
            # runtime state and tutorial events still live on the backend window.
            try:
                self.window.tutorial_event_bus = getattr(self.backend, "tutorial_event_bus", None)
                self.window.get_tutorial_runtime_state = getattr(self.backend, "get_tutorial_runtime_state")
                self.window.apply_safe_tutorial_defaults = self._apply_safe_tutorial_defaults_from_ui_real
                self.window.load_performance_profile_by_id = self._load_performance_profile_by_id_from_ui_real
                self.window.load_preset = self._load_preset_from_tutorial_ui_real
                preset_combo = self._ui_object("preset_combo")
                if preset_combo is not None:
                    self.window.preset_combo = preset_combo
            except Exception:
                pass

            tutorials_list = self._ui_object("tutorials_list")
            if tutorials_list is not None and hasattr(tutorials_list, "currentRowChanged"):
                tutorials_list.currentRowChanged.connect(self._on_frontend_tutorial_selection_changed)
            refresh_button = self._ui_object("btn_tutorial_refresh")
            if refresh_button is not None and hasattr(refresh_button, "clicked"):
                refresh_button.clicked.connect(lambda _checked=False: self._refresh_tutorials_from_ui_real())
            start_button = self._ui_object("btn_tutorial_start")
            if start_button is not None and hasattr(start_button, "clicked"):
                start_button.clicked.connect(lambda _checked=False: self._start_selected_tutorial_from_ui_real())
            description = self._ui_object("tutorial_description")
            if description is not None and hasattr(description, "setReadOnly"):
                try:
                    description.setReadOnly(True)
                except Exception:
                    pass
            self._refresh_tutorials_from_ui_real()

    def _bind_model_refresh_control(self):
            refresh_button = self._ui_object("btn_model_refresh")
            if refresh_button is not None and hasattr(refresh_button, "clicked"):
                refresh_button.clicked.connect(self._request_model_refresh_from_ui_real)

    def _bind_push_to_talk_control(self):
            button = self._ui_object("btn_push_to_talk")
            if button is None:
                return
            if hasattr(button, "pressed"):
                button.pressed.connect(lambda: self._input_action_service.set_push_to_talk_hold(True))
            if hasattr(button, "released"):
                button.released.connect(lambda: self._input_action_service.set_push_to_talk_hold(False))

    def _bind_chat_edit_controls(self):
            chat_edit = self._ui_object("chat_edit")
            if chat_edit is not None and hasattr(chat_edit, "customContextMenuRequested"):
                chat_edit.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                chat_edit.customContextMenuRequested.connect(self._show_frontend_chat_context_menu)
            edit_button = self._ui_object("chat_edit_mode_button")
            if edit_button is not None and hasattr(edit_button, "clicked"):
                edit_button.clicked.connect(self._enter_chat_edit_mode_from_ui_real)
            apply_button = self._ui_object("chat_apply_edit_button")
            if apply_button is not None and hasattr(apply_button, "clicked"):
                apply_button.clicked.connect(self._apply_chat_edit_mode_from_ui_real)
            cancel_button = self._ui_object("chat_cancel_edit_button")
            if cancel_button is not None and hasattr(cancel_button, "clicked"):
                cancel_button.clicked.connect(self._cancel_chat_edit_mode_from_ui_real)
            send_button = self._ui_object("chat_send_button")
            if send_button is not None and hasattr(send_button, "clicked"):
                send_button.clicked.connect(lambda _checked=False: self._send_frontend_typed_chat_message())
            message_input = self._ui_object("chat_message_input")
            if message_input is not None and hasattr(message_input, "returnPressed"):
                message_input.returnPressed.connect(self._send_frontend_typed_chat_message)

    def _show_frontend_chat_context_menu(self, point):
            chat_edit = self._ui_object("chat_edit")
            if chat_edit is None:
                return
            try:
                menu = chat_edit.createStandardContextMenu()
            except Exception:
                menu = QtWidgets.QMenu(chat_edit)
            replay_addon_id = ""
            callback = getattr(self.backend, "_addon_id_for_ui_role", None)
            if callable(callback):
                replay_addon_id = callback("chat_replay", fallback="")
            self._invoke_backend_addon_capability(
                replay_addon_id,
                "real_ui.add_replay_context_menu_action",
                {"menu": menu, "chat_edit": chat_edit, "point": point},
            )
            try:
                menu.exec(chat_edit.viewport().mapToGlobal(point))
            except Exception:
                pass

    def _bind_performance_guidance_controls(self):
            toggle = self._ui_object("performance_guidance_toggle")
            if toggle is not None and hasattr(toggle, "toggled"):
                toggle.toggled.connect(self._toggle_frontend_performance_guidance)
                self._toggle_frontend_performance_guidance(bool(toggle.isChecked()))

    def _toggle_frontend_performance_guidance(self, checked):
            visible = bool(checked)
            for object_name in (
                "stream_hint_label",
                "musetalk_vram_hint",
                "context_check_label",
                "model_context_input",
                "context_tokens_label",
                "model_budget_label",
            ):
                widget = self._ui_object(object_name)
                if widget is not None and hasattr(widget, "setVisible"):
                    widget.setVisible(visible)
            toggle = self._ui_object("performance_guidance_toggle")
            if toggle is not None and hasattr(toggle, "setText"):
                toggle.setText("Hide Performance Guidance" if visible else "Show Performance Guidance")
            backend_toggle = getattr(self.backend, "performance_guidance_toggle", None)
            if backend_toggle is not None and hasattr(backend_toggle, "setChecked"):
                try:
                    backend_toggle.setChecked(visible)
                except Exception:
                    pass
            if hasattr(self.backend, "_toggle_performance_guidance"):
                try:
                    self.backend._toggle_performance_guidance(visible)
                except Exception:
                    pass

    def _bind_dry_run_controls(self):
            bindings = {
                "btn_dry_run_start": getattr(self.backend, "start_dry_run_session", None),
                "btn_dry_run_stop": getattr(self.backend, "stop_dry_run_session", None),
                "btn_dry_run_apply": getattr(self.backend, "apply_dry_run_recommendation", None),
            }
            for object_name, handler in bindings.items():
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "clicked") or not callable(handler):
                    continue
                widget.clicked.connect(lambda _checked=False, callback=handler: self._invoke_runtime_callback(callback))

    def _bind_response_length_runtime_controls(self):
            limit_response_checkbox = self._ui_object("limit_response_checkbox")
            if limit_response_checkbox is not None and hasattr(limit_response_checkbox, "toggled"):
                limit_response_checkbox.toggled.connect(self._on_frontend_limit_response_length_changed)
            max_response_tokens_spin = self._ui_object("max_response_tokens_spin")
            if max_response_tokens_spin is not None and hasattr(max_response_tokens_spin, "valueChanged"):
                max_response_tokens_spin.valueChanged.connect(self._on_frontend_max_response_tokens_changed)

    def _bind_host_input_runtime_controls(self):
            show_all_audio_inputs = self._ui_object("show_all_audio_inputs_checkbox")
            if show_all_audio_inputs is not None and hasattr(show_all_audio_inputs, "toggled"):
                show_all_audio_inputs.toggled.connect(self._on_frontend_show_all_audio_inputs_changed)
            combo_bindings = (
                ("audio_input_device_combo", self._on_frontend_audio_input_device_changed),
                ("audio_output_device_combo", self._on_frontend_audio_output_device_changed),
                ("engine_combo", self._on_frontend_engine_changed),
                ("input_mode_combo", self._on_frontend_input_mode_changed),
                ("input_role_combo", self._on_frontend_input_role_changed),
                ("stream_mode_combo", self._on_frontend_stream_mode_changed),
                ("stt_backend_combo", self._on_frontend_stt_backend_changed),
                ("stt_model_combo", self._on_frontend_stt_model_changed),
                ("stt_language_combo", self._on_frontend_stt_language_changed),
                ("tts_backend_combo", self._on_frontend_tts_backend_changed),
            )
            for object_name, handler in combo_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "currentIndexChanged"):
                    continue
                widget.currentIndexChanged.connect(handler)

    def _bind_addon_owned_runtime_controls(self):
            common_payload = {
                "pose_specs": UI_SHELL_BODY_POSE_SPECS,
                "value_to_raw": _ui_shell_body_value_to_slider_raw,
                "raw_to_value": _ui_shell_body_slider_raw_to_value,
                "update_label": _ui_shell_update_body_label,
            }
            for capability in (
                "real_ui.bind_runtime_controls",
                "real_ui.bind_preview_controls",
                "real_ui.bind_duplicate_controls",
                "real_ui.bind_show_button",
            ):
                self._invoke_all_backend_addon_capabilities(capability, common_payload)

    def _bind_musetalk_visual_runtime_controls(self):
            combo_bindings = (
                ("sensory_feedback_source_combo", self._on_frontend_sensory_feedback_source_changed),
                ("chat_font_size_combo", self._on_frontend_chat_font_size_changed),
            )
            for object_name, handler in combo_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "currentIndexChanged"):
                    continue
                widget.currentIndexChanged.connect(handler)

    def _bind_avatar_body_vam_runtime_controls(self):
            tooltips = {
                "voice_combo": "Voice reference used by the selected TTS backend when voice cloning is available.",
                "use_wav_file_checkbox": "Use the selected .wav file as the TTS voice reference. Disable to use the backend's built-in/default voice.",
                "btn_voice_refresh": "Refresh voice reference files from the voices folder.",
                "body_combo": "Saved VSeeFace body pose preset. Use Load to apply it to the visible sliders.",
                "emotion_combo": "Preview/edit the body-pose values associated with this emotion.",
                "live_sync_checkbox": "When enabled, body slider changes are sent live to the avatar runtime.",
                "btn_body_load": "Load the selected body preset into the body pose sliders.",
                "btn_body_save": "Save the current body pose sliders into the selected body preset.",
                "btn_body_save_as": "Save the current body pose sliders as a new body preset.",
                "btn_body_delete": "Delete the selected body preset.",
                "btn_hand_doctor": "Open the hand debugging/calibration helper for avatar hand pose tuning.",
            }
            for object_name, tooltip in tooltips.items():
                widget = self._ui_object(object_name)
                if widget is not None and hasattr(widget, "setToolTip"):
                    widget.setToolTip(tooltip)
            combo_bindings = (
                ("voice_combo", self._on_frontend_voice_changed),
                ("body_combo", self._on_frontend_body_selection_changed),
                ("emotion_combo", self._on_frontend_emotion_changed),
            )
            for object_name, handler in combo_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "currentIndexChanged"):
                    continue
                widget.currentIndexChanged.connect(handler)
            button = self._ui_object("btn_voice_refresh")
            if button is not None and hasattr(button, "clicked"):
                button.clicked.connect(lambda _checked=False: self._refresh_frontend_voice_list())
            checkbox_bindings = (
                ("use_wav_file_checkbox", self._on_frontend_use_wav_file_changed),
                ("live_sync_checkbox", self._on_frontend_live_sync_changed),
            )
            for object_name, handler in checkbox_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "toggled"):
                    continue
                widget.toggled.connect(handler)
            button_bindings = {
                "btn_body_load": self._load_body_config_from_ui_real,
                "btn_body_save": self._save_current_body_from_ui_real,
                "btn_body_save_as": self._save_body_dialog_from_ui_real,
                "btn_body_delete": self._delete_current_body_from_ui_real,
                "btn_hand_doctor": self._open_hand_debugger_from_ui_real,
            }
            for object_name, handler in button_bindings.items():
                button = self._ui_object(object_name)
                if button is None or not hasattr(button, "clicked"):
                    continue
                button.clicked.connect(lambda _checked=False, callback=handler: self._invoke_runtime_callback(callback))

    def _bind_profile_utility_runtime_controls(self):
            combo_bindings = (
                ("chunking_profile_combo", self._on_frontend_chunking_profile_changed),
                ("performance_profile_combo", self._on_frontend_performance_profile_changed),
            )
            for object_name, handler in combo_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "currentIndexChanged"):
                    continue
                widget.currentIndexChanged.connect(handler)
            dry_run_auto_replies_checkbox = self._ui_object("dry_run_auto_replies_checkbox")
            if dry_run_auto_replies_checkbox is not None and hasattr(dry_run_auto_replies_checkbox, "toggled"):
                dry_run_auto_replies_checkbox.toggled.connect(self._on_frontend_dry_run_auto_replies_changed)
            spin_bindings = (
                ("dry_run_target_spin", self._on_frontend_dry_run_target_changed),
            )
            for object_name, handler in spin_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "valueChanged"):
                    continue
                widget.valueChanged.connect(handler)
    def _bind_chunking_runtime_controls(self):
            for key, spec in UI_SHELL_CHUNKING_SPECS.items():
                slider = self._ui_object(str(spec.get("widget") or ""))
                if slider is None or not hasattr(slider, "valueChanged"):
                    continue
                try:
                    scale = float(spec.get("scale", 1) or 1)
                    slider.setRange(
                        int(round(float(spec.get("minimum", 0) or 0) * scale)),
                        int(round(float(spec.get("maximum", 100) or 100) * scale)),
                    )
                    slider.setToolTip(
                        str(spec.get("tooltip") or "").strip()
                        or "Runtime-backed chunking setting. Changes are saved to the current session."
                    )
                except Exception:
                    pass
                slider.valueChanged.connect(lambda value, chunk_key=key: self._on_frontend_chunking_value_changed(chunk_key, value))

            button_bindings = {
                "btn_reset_chunking_defaults": self._reset_chunking_from_ui_real,
                "btn_chunking_profile_refresh": self._refresh_chunking_profiles_from_ui_real,
                "btn_chunking_profile_load": self._load_chunking_profile_from_ui_real,
                "btn_chunking_profile_save": self._save_chunking_profile_from_ui_real,
                "btn_chunking_profile_delete": self._delete_chunking_profile_from_ui_real,
            }
            for object_name, handler in button_bindings.items():
                button = self._ui_object(object_name)
                if button is None or not hasattr(button, "clicked"):
                    continue
                button.clicked.connect(lambda _checked=False, callback=handler: self._invoke_runtime_callback(callback))

    def _bind_chat_session_runtime_controls(self):
            allow_proactive_checkbox = self._ui_object("allow_proactive_checkbox")
            if allow_proactive_checkbox is not None and hasattr(allow_proactive_checkbox, "toggled"):
                allow_proactive_checkbox.toggled.connect(self._on_frontend_allow_proactive_changed)
            require_first_user_checkbox = self._ui_object("require_first_user_checkbox")
            if require_first_user_checkbox is not None and hasattr(require_first_user_checkbox, "toggled"):
                require_first_user_checkbox.toggled.connect(self._on_frontend_require_first_user_changed)
            listen_idle_window_spin = self._ui_object("listen_idle_window_spin")
            if listen_idle_window_spin is not None and hasattr(listen_idle_window_spin, "valueChanged"):
                listen_idle_window_spin.valueChanged.connect(self._on_frontend_listen_idle_window_changed)
            proactive_delay_spin = self._ui_object("proactive_delay_spin")
            if proactive_delay_spin is not None and hasattr(proactive_delay_spin, "valueChanged"):
                proactive_delay_spin.valueChanged.connect(self._on_frontend_proactive_delay_changed)
            chat_context_window_spin = self._ui_object("chat_context_window_spin")
            if chat_context_window_spin is not None and hasattr(chat_context_window_spin, "valueChanged"):
                chat_context_window_spin.valueChanged.connect(self._on_frontend_chat_context_window_changed)
            stored_chat_history_limit_spin = self._ui_object("stored_chat_history_limit_spin")
            if stored_chat_history_limit_spin is not None and hasattr(stored_chat_history_limit_spin, "valueChanged"):
                stored_chat_history_limit_spin.valueChanged.connect(self._on_frontend_stored_chat_history_limit_changed)
            chat_overflow_policy_combo = self._ui_object("chat_overflow_policy_combo")
            if chat_overflow_policy_combo is not None and hasattr(chat_overflow_policy_combo, "currentTextChanged"):
                chat_overflow_policy_combo.currentTextChanged.connect(self._on_frontend_chat_overflow_policy_changed)
            long_term_memory_enabled_checkbox = self._ui_object("long_term_memory_enabled_checkbox")
            if long_term_memory_enabled_checkbox is not None and hasattr(long_term_memory_enabled_checkbox, "toggled"):
                long_term_memory_enabled_checkbox.toggled.connect(self._on_frontend_long_term_memory_enabled_changed)
            long_term_memory_update_on_save_checkbox = self._ui_object("long_term_memory_update_on_save_checkbox")
            if long_term_memory_update_on_save_checkbox is not None and hasattr(long_term_memory_update_on_save_checkbox, "toggled"):
                long_term_memory_update_on_save_checkbox.toggled.connect(self._on_frontend_long_term_memory_update_on_save_changed)
            long_term_memory_inject_checkbox = self._ui_object("long_term_memory_inject_checkbox")
            if long_term_memory_inject_checkbox is not None and hasattr(long_term_memory_inject_checkbox, "toggled"):
                long_term_memory_inject_checkbox.toggled.connect(self._on_frontend_long_term_memory_inject_changed)
            long_term_memory_max_chars_spin = self._ui_object("long_term_memory_max_chars_spin")
            if long_term_memory_max_chars_spin is not None and hasattr(long_term_memory_max_chars_spin, "valueChanged"):
                long_term_memory_max_chars_spin.valueChanged.connect(self._on_frontend_long_term_memory_max_chars_changed)
            system_prompt_text = self._ui_object("system_prompt_text")
            if system_prompt_text is not None and hasattr(system_prompt_text, "textChanged"):
                system_prompt_text.textChanged.connect(self._on_frontend_system_prompt_changed)
                if hasattr(system_prompt_text, "customContextMenuRequested"):
                    system_prompt_text.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
                    system_prompt_text.customContextMenuRequested.connect(self._show_frontend_system_prompt_context_menu)
            emotional_text = self._ui_object("emotional_text")
            if emotional_text is not None and hasattr(emotional_text, "textChanged"):
                emotional_text.textChanged.connect(self._on_frontend_emotional_text_changed)

    def _bind_sensory_runtime_controls(self):
            interval_spin = self._ui_object("sensory_feedback_interval_spin")
            if interval_spin is not None and hasattr(interval_spin, "valueChanged"):
                interval_spin.valueChanged.connect(self._on_frontend_sensory_interval_changed)
            pingpong_checkbox = self._ui_object("sensory_pingpong_checkbox")
            if pingpong_checkbox is not None and hasattr(pingpong_checkbox, "toggled"):
                pingpong_checkbox.toggled.connect(self._on_frontend_sensory_pingpong_toggled)
            hidden_proactive_checkbox = self._ui_object("sensory_allow_hidden_proactive_checkbox")
            if hidden_proactive_checkbox is not None and hasattr(hidden_proactive_checkbox, "toggled"):
                hidden_proactive_checkbox.toggled.connect(self._on_frontend_sensory_hidden_proactive_toggled)
            hidden_visual_checkbox = self._ui_object("sensory_allow_hidden_visual_checkbox")
            if hidden_visual_checkbox is not None and hasattr(hidden_visual_checkbox, "toggled"):
                hidden_visual_checkbox.toggled.connect(self._on_frontend_sensory_hidden_visual_toggled)
            history_spin = self._ui_object("sensory_pingpong_history_spin")
            if history_spin is not None and hasattr(history_spin, "valueChanged"):
                history_spin.valueChanged.connect(self._on_frontend_sensory_history_changed)
            prompt_text = self._ui_object("sensory_pingpong_prompt_text")
            if prompt_text is not None and hasattr(prompt_text, "textChanged"):
                prompt_text.textChanged.connect(self._on_frontend_sensory_prompt_changed)
            prompt_reset = self._ui_object("btn_sensory_pingpong_prompt_reset")
            if prompt_reset is not None and hasattr(prompt_reset, "clicked"):
                prompt_reset.clicked.connect(self._reset_frontend_sensory_prompt_to_default)

    def _bind_provider_model_workflow_controls(self):
            provider_combo = self._ui_object("chat_provider_combo")
            if provider_combo is not None and hasattr(provider_combo, "currentIndexChanged"):
                provider_combo.currentIndexChanged.connect(self._on_frontend_chat_provider_changed)
            model_combo = self._ui_object("model_combo")
            if model_combo is not None and hasattr(model_combo, "currentIndexChanged"):
                model_combo.currentIndexChanged.connect(self._on_frontend_model_selection_changed)
            vision_checkbox = self._ui_object("model_requires_vision_checkbox")
            if vision_checkbox is not None and hasattr(vision_checkbox, "toggled"):
                vision_checkbox.toggled.connect(self._on_frontend_model_requires_vision_changed)
            preset_combo = self._ui_object("preset_combo")
            if preset_combo is not None and hasattr(preset_combo, "currentIndexChanged"):
                preset_combo.currentIndexChanged.connect(self._on_frontend_preset_selection_changed)
            preset_bindings = {
                "btn_preset_refresh": getattr(self.backend, "refresh_preset_list", None),
                "btn_preset_load": getattr(self.backend, "load_preset", None),
                "btn_preset_save": getattr(self.backend, "save_current_preset", None),
                "btn_preset_save_as": getattr(self.backend, "save_preset_dialog", None),
                "btn_preset_delete": getattr(self.backend, "delete_current_preset", None),
            }
            for object_name, handler in preset_bindings.items():
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "clicked") or not callable(handler):
                    continue
                widget.clicked.connect(lambda _checked=False, callback=handler: self._invoke_provider_model_callback(callback))
