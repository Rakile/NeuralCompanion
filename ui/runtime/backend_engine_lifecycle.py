import threading
import traceback

from PySide6 import QtCore


from ui.runtime.engine_access import engine_module as _engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class BackendEngineLifecycleMixin:
    """Engine start/stop lifecycle and config handoff from the Qt backend window."""

    def _collect_avatar_provider_runtime_config(self, avatar_mode, runtime_config):
        payload = {
            "backend": self,
            "runtime_config": dict(runtime_config or {}),
            "avatar_mode": str(avatar_mode or ""),
        }
        result = self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "runtime.collect_config",
            payload,
            default={},
            provider_id=str(avatar_mode or ""),
        )
        return dict(result or {})

    def _collect_tts_backend_runtime_config(self, tts_backend, runtime_config):
        payload = {
            "backend": self,
            "runtime_config": dict(runtime_config or {}),
            "tts_backend": str(tts_backend or ""),
        }
        result = self._invoke_addon_service_capability(
            "tts_backend_service",
            "runtime.collect_config",
            payload,
            default={},
            backend_id=str(tts_backend or ""),
        )
        return dict(result or {})

    def _update_avatar_provider_runtime_config_from_widgets(self, avatar_mode, runtime_config):
        self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "runtime.update_config_from_widgets",
            {
                "backend": self,
                "runtime_config": dict(runtime_config or {}),
                "avatar_mode": str(avatar_mode or ""),
            },
            default=None,
            provider_id=str(avatar_mode or ""),
        )

    def _update_tts_backend_runtime_config_from_widgets(self, tts_backend, runtime_config):
        self._invoke_addon_service_capability(
            "tts_backend_service",
            "runtime.update_config_from_widgets",
            {
                "backend": self,
                "runtime_config": dict(runtime_config or {}),
                "tts_backend": str(tts_backend or ""),
            },
            default=None,
            backend_id=str(tts_backend or ""),
        )

    def apply_text_config(self):
        runtime_config = _runtime_config()
        avatar_mode = self._current_avatar_mode_value() if hasattr(self, "engine_combo") else str(runtime_config.get("avatar_mode", "vseeface") or "vseeface").strip().lower()
        mode = self._input_mode_value_from_label(self.input_mode_combo.currentText())
        role = self._input_role_value_from_label(self.input_role_combo.currentText())
        stream_mode = self.stream_mode_combo.currentText() == "On"
        tts_backend = self._current_tts_backend_value()
        _update_runtime_config("input_mode", mode)
        if mode == "text_only":
            set_stt_none = getattr(self, "_set_stt_backend_none_for_text_only", None)
            if callable(set_stt_none):
                set_stt_none()
            else:
                _update_runtime_config("stt_backend", "none")
        else:
            _update_runtime_config("stt_backend", self._current_stt_backend_value())
        if hasattr(self, "_current_stt_model_value"):
            _update_runtime_config("stt_model_size", self._current_stt_model_value())
        if hasattr(self, "_current_stt_language_value"):
            _update_runtime_config("stt_language", self._current_stt_language_value())
        _update_runtime_config("input_message_role", role)
        _update_runtime_config("stream_mode", stream_mode)
        _update_runtime_config("tts_backend", tts_backend)
        self._update_avatar_provider_runtime_config_from_widgets(avatar_mode, runtime_config)
        _update_runtime_config("allow_proactive_replies", self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else False)
        _update_runtime_config("require_first_user_before_proactive", self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False)
        _update_runtime_config("listen_idle_window_seconds", round(float(self.listen_idle_window_spin.value()), 1) if hasattr(self, "listen_idle_window_spin") else 5.0)
        _update_runtime_config("proactive_delay_seconds", round(float(self.proactive_delay_spin.value()), 1) if hasattr(self, "proactive_delay_spin") else 10.0)
        _update_runtime_config("chat_context_window_messages", max(4, int(self.chat_context_window_spin.value())) if hasattr(self, "chat_context_window_spin") else 20)
        _update_runtime_config("stored_chat_history_limit", max(0, int(self.stored_chat_history_limit_spin.value())) if hasattr(self, "stored_chat_history_limit_spin") else 0)
        _update_runtime_config("chat_context_overflow_policy", self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window")
        self._update_tts_backend_runtime_config_from_widgets(tts_backend, runtime_config)
        _update_runtime_config("emotional_instructions", self.emotional_text.toPlainText().strip())
        _update_runtime_config("system_prompt", self.system_prompt_text.toPlainText().strip())
        print("[QtGUI] Text Config Updated.")

    def start_engine(self, offline_replay_only=False):
        engine = _engine()
        runtime_config = _runtime_config()
        if self.thread and self.thread.is_alive():
            return
        self._engine_stop_in_progress = False
        self._publish_addon_event("runtime.heavy_task_starting", {"source": "engine_start"})
        mode = self._current_avatar_mode_value()
        _update_runtime_config("avatar_mode", mode)
        self.apply_text_config()
        input_mode = self._input_mode_value_from_label(self.input_mode_combo.currentText())
        config = {
            "active_preset_name": str(runtime_config.get("active_preset_name", "") or ""),
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(runtime_config.get("chat_provider_settings", {}) or {}),
            "chat_provider_generation_settings": dict(runtime_config.get("chat_provider_generation_settings", {}) or {}),
            "model_name": self.model_combo.currentText(),
            "system_prompt": self.system_prompt_text.toPlainText().strip(),
            "temperature": self.brain_sliders["temperature"].value(),
            "top_p": self.brain_sliders["top_p"].value(),
            "top_k": int(self.brain_sliders["top_k"].value()),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value(),
            "min_p": self.brain_sliders["min_p"].value(),
            "limit_response_length": self.limit_response_checkbox.isChecked(),
            "max_response_tokens": int(self.max_response_tokens_spin.value()),
            "avatar_mode": mode,
            "input_mode": input_mode,
            "input_message_role": self._input_role_value_from_label(self.input_role_combo.currentText()),
            "stream_mode": self.stream_mode_combo.currentText() == "On",
            "stt_backend": (
                "none"
                if input_mode == "text_only"
                else (
                    self._current_stt_backend_value()
                    if hasattr(self, "_current_stt_backend_value")
                    else str(runtime_config.get("stt_backend", "none") or "none")
                )
            ),
            "stt_model_size": self._current_stt_model_value() if hasattr(self, "_current_stt_model_value") else str(runtime_config.get("stt_model_size", "tiny.en") or "tiny.en"),
            "stt_language": self._current_stt_language_value() if hasattr(self, "_current_stt_language_value") else str(runtime_config.get("stt_language", "en") or "en"),
            "audio_input_device": self.audio_input_device_combo.currentText() if hasattr(self, "audio_input_device_combo") else str(runtime_config.get("audio_input_device", "Default Input") or "Default Input"),
            "audio_output_device": self.audio_output_device_combo.currentText() if hasattr(self, "audio_output_device_combo") else str(runtime_config.get("audio_output_device", "Default Output") or "Default Output"),
            "offline_replay_only": bool(offline_replay_only),
            "tts_backend": self._current_tts_backend_value(),
            **self._collect_avatar_provider_runtime_config(mode, runtime_config),
            **self._collect_tts_backend_runtime_config(self._current_tts_backend_value(), runtime_config),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(runtime_config.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(runtime_config.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(runtime_config.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(runtime_config.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(runtime_config.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(runtime_config.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(runtime_config.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(runtime_config.get("sensory_pingpong_source_prompts", {}) or {}),
            "sensory_provider_metadata_overrides": self._current_sensory_provider_metadata_override_map() if hasattr(self, "_current_sensory_provider_metadata_override_map") else dict(runtime_config.get("sensory_provider_metadata_overrides", {}) or {}),
        }
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        if mode == "musetalk":
            self.show_musetalk_preview()
        self.thread = threading.Thread(target=self._run_engine_thread, args=(config,), daemon=True)
        self.thread.start()
        self.emit_tutorial_event("engine_start_requested", {"avatar_mode": mode, "tts_backend": config.get("tts_backend", "")})
        self._update_restart_sensitive_controls()
        self._update_control_action_buttons()
        self._update_push_to_talk_button()

    def _run_engine_thread(self, config):
        try:
            _engine().run_companion(config)
        except Exception as exc:
            print(f"CRITICAL ERROR: {exc}")
            traceback.print_exc()
        finally:
            if not self._closing:
                try:
                    QtCore.QMetaObject.invokeMethod(self, "reset_ui", QtCore.Qt.QueuedConnection)
                except RuntimeError:
                    pass

    @QtCore.Slot()
    def reset_ui(self):
        if self._closing:
            return
        self._engine_stop_in_progress = False
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.emit_tutorial_event("engine_stopped", self.get_tutorial_runtime_state())
        self._update_restart_sensitive_controls()
        self._update_control_action_buttons()
        self._update_push_to_talk_button()
        print("[QtGUI] System Halted.")

    def stop_engine(self):
        if bool(getattr(self, "_engine_stop_in_progress", False)):
            return
        self._engine_stop_in_progress = True
        engine = _engine()
        try:
            print("[QtGUI] Stopping...")
            engine.stop_flag.set()
            if hasattr(engine, "stop_playback"):
                engine.stop_playback.set()
            engine_thread = getattr(self, "thread", None)
            if not (engine_thread and engine_thread.is_alive()):
                engine.shutdown_avatar_engine()
            self.btn_stop.setEnabled(False)
            self.emit_tutorial_event("engine_stop_requested", self.get_tutorial_runtime_state())
            self._update_restart_sensitive_controls()
            self._update_control_action_buttons()
            self._update_push_to_talk_button()
        finally:
            engine_thread = getattr(self, "thread", None)
            if not (engine_thread and engine_thread.is_alive()):
                self._engine_stop_in_progress = False
