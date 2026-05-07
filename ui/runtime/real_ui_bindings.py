from PySide6 import QtCore, QtWidgets

from addons.audio_story_mode import real_ui_bridge as audio_story_real_ui_bridge


def configure_real_ui_binding_dependencies(namespace):
    """Inject qt_app-owned constants used by the extracted real-UI binding mixin."""
    globals().update(dict(namespace or {}))


class MainUiRealBindingMixin:
    """Signal wiring helpers for connecting main.ui controls to backend/runtime callbacks."""

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
                "btn_load_chat_session": self._chat_context_service.load_chat_context,
                "btn_reset_chat_session": self._chat_context_service.reset_chat_memory,
            }
            for object_name, handler in bindings.items():
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "clicked"):
                    continue
                widget.clicked.connect(handler)

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

    def _show_frontend_chat_context_menu(self, point):
            chat_edit = self._ui_object("chat_edit")
            if chat_edit is None:
                return
            try:
                menu = chat_edit.createStandardContextMenu()
            except Exception:
                menu = QtWidgets.QMenu(chat_edit)
            if not bool(getattr(self.backend, "chat_edit_mode", False)):
                replay_index = None
                try:
                    cursor = chat_edit.cursorForPosition(point)
                    position = cursor.position()
                    replay_index = self.backend._assistant_replay_index_for_chat_position(position)
                except Exception:
                    replay_index = None
                if replay_index is not None:
                    try:
                        menu.addSeparator()
                        replay_action = menu.addAction(f"Start Playing From This Message (#{replay_index})")
                        replay_action.triggered.connect(
                            lambda _checked=False, idx=replay_index: self.backend.trigger_replay_from_assistant_index(idx)
                        )
                    except Exception:
                        pass
            try:
                menu.exec(chat_edit.viewport().mapToGlobal(point))
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
            combo_bindings = (
                ("audio_input_device_combo", self._on_frontend_audio_input_device_changed),
                ("audio_output_device_combo", self._on_frontend_audio_output_device_changed),
                ("engine_combo", self._on_frontend_engine_changed),
                ("input_mode_combo", self._on_frontend_input_mode_changed),
                ("input_role_combo", self._on_frontend_input_role_changed),
                ("stream_mode_combo", self._on_frontend_stream_mode_changed),
                ("tts_backend_combo", self._on_frontend_tts_backend_changed),
            )
            for object_name, handler in combo_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "currentIndexChanged"):
                    continue
                widget.currentIndexChanged.connect(handler)
            refresh_avatar_packs = self._ui_object("btn_musetalk_avatar_pack_refresh")
            if refresh_avatar_packs is not None and hasattr(refresh_avatar_packs, "clicked"):
                refresh_avatar_packs.clicked.connect(self._refresh_musetalk_avatar_packs_from_ui_real)

    def _bind_musetalk_visual_runtime_controls(self):
            combo_bindings = (
                ("musetalk_vram_combo", self._on_frontend_musetalk_vram_changed),
                ("musetalk_avatar_pack_combo", self._on_frontend_musetalk_avatar_pack_changed),
                ("visual_reply_mode_combo", self._on_frontend_visual_reply_mode_changed),
                ("visual_reply_provider_combo", self._on_frontend_visual_reply_provider_changed),
                ("visual_reply_size_combo", self._on_frontend_visual_reply_size_changed),
                ("sensory_feedback_source_combo", self._on_frontend_sensory_feedback_source_changed),
                ("chat_font_size_combo", self._on_frontend_chat_font_size_changed),
            )
            for object_name, handler in combo_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "currentIndexChanged"):
                    continue
                widget.currentIndexChanged.connect(handler)

    def _bind_avatar_body_vam_runtime_controls(self):
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
            checkbox_bindings = (
                ("live_sync_checkbox", self._on_frontend_live_sync_changed),
                ("vam_vmc_enabled_checkbox", self._on_frontend_vam_vmc_enabled_changed),
                ("vam_bridge_enabled_checkbox", self._on_frontend_vam_bridge_enabled_changed),
                ("vam_play_audio_in_vam_checkbox", self._on_frontend_vam_play_audio_changed),
                ("vam_timeline_auto_resume_checkbox", self._on_frontend_vam_timeline_auto_resume_changed),
            )
            for object_name, handler in checkbox_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "toggled"):
                    continue
                widget.toggled.connect(handler)
            vam_vmc_port_spin = self._ui_object("vam_vmc_port_spin")
            if vam_vmc_port_spin is not None and hasattr(vam_vmc_port_spin, "valueChanged"):
                vam_vmc_port_spin.valueChanged.connect(self._on_frontend_vam_vmc_port_changed)
            for key, spec in UI_SHELL_BODY_POSE_SPECS.items():
                slider = self._ui_object(str(spec.get("widget") or ""))
                if slider is None or not hasattr(slider, "valueChanged"):
                    continue
                try:
                    minimum = _ui_shell_body_value_to_slider_raw(key, spec.get("minimum", 0.0))
                    maximum = _ui_shell_body_value_to_slider_raw(key, spec.get("maximum", 0.0))
                    slider.setRange(minimum, maximum)
                    if hasattr(slider, "setSingleStep"):
                        scale = int(spec.get("scale", 1) or 1)
                        slider.setSingleStep(max(1, scale // 10 if scale > 1 else 1))
                    if hasattr(slider, "setToolTip"):
                        slider.setToolTip("Runtime-backed VSeeFace body setting. Save a body preset to persist edited pose values.")
                except Exception:
                    pass
                slider.valueChanged.connect(lambda value, pose_key=key: self._on_frontend_body_pose_slider_changed(pose_key, value))
            edit_bindings = (
                ("vam_root_edit", self._on_frontend_vam_root_changed),
                ("vam_target_atom_uid_edit", self._on_frontend_vam_target_atom_uid_changed),
                ("vam_target_storable_id_edit", self._on_frontend_vam_target_storable_id_changed),
                ("vam_vmc_host_edit", self._on_frontend_vam_vmc_host_changed),
            )
            for object_name, handler in edit_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "editingFinished"):
                    continue
                widget.editingFinished.connect(handler)
            button_bindings = {
                "btn_body_load": self._load_body_config_from_ui_real,
                "btn_body_save": self._save_current_body_from_ui_real,
                "btn_body_save_as": self._save_body_dialog_from_ui_real,
                "btn_body_delete": self._delete_current_body_from_ui_real,
                "btn_hand_doctor": self._open_hand_debugger_from_ui_real,
                "btn_vseeface_hide_interface": self._enter_vseeface_focus_from_ui_real,
                "btn_start_vam_desktop": self._start_vam_desktop_from_ui_real,
                "btn_start_vam_vr": self._start_vam_vr_from_ui_real,
                "btn_vam_hide_interface": self._enter_vam_focus_from_ui_real,
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
                ("musetalk_loop_fade_spin", self._on_frontend_musetalk_loop_fade_changed),
            )
            for object_name, handler in spin_bindings:
                widget = self._ui_object(object_name)
                if widget is None or not hasattr(widget, "valueChanged"):
                    continue
                widget.valueChanged.connect(handler)
            visual_reply_model_edit = self._ui_object("visual_reply_model_edit")
            if visual_reply_model_edit is not None and hasattr(visual_reply_model_edit, "editingFinished"):
                visual_reply_model_edit.editingFinished.connect(self._on_frontend_visual_reply_model_changed)

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
                    slider.setToolTip("Runtime-backed chunking setting. Changes are saved to the current session.")
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
            system_prompt_text = self._ui_object("system_prompt_text")
            if system_prompt_text is not None and hasattr(system_prompt_text, "textChanged"):
                system_prompt_text.textChanged.connect(self._on_frontend_system_prompt_changed)
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

    def _bind_audio_story_duplicate_controls(self):
            audio_story_real_ui_bridge.bind_duplicate_controls(self)

    def _bind_musetalk_preview_controls(self):
            preview_button = self._ui_object("btn_musetalk_preview")
            if preview_button is not None and hasattr(preview_button, "clicked"):
                preview_button.clicked.connect(self._show_frontend_musetalk_preview)
            focus_button = self._ui_object("btn_musetalk_avatar_focus")
            if focus_button is not None and hasattr(focus_button, "clicked"):
                focus_button.clicked.connect(self._toggle_frontend_musetalk_avatar_focus)

    def _bind_visual_reply_controls(self):
            show_button = self._ui_object("btn_visual_reply")
            if show_button is not None and hasattr(show_button, "clicked"):
                show_button.clicked.connect(self._show_frontend_visual_reply_dock)

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
