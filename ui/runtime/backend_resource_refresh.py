import glob
import os


from ui.runtime.engine_access import engine_module as _engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class BackendResourceRefreshMixin:
    """Refresh backend UI resources from current runtime/config state."""

    def refresh_voice_list(self, preferred_voice=None):
        if not hasattr(self, "voice_combo"):
            return []
        voices = sorted(
            [os.path.basename(path) for path in glob.glob("voices/*.wav")],
            key=lambda name: name.lower(),
        )
        current_voice = str(preferred_voice or "").strip()
        if not current_voice and hasattr(self, "_current_voice_file_value"):
            current_voice = str(self._current_voice_file_value() or "").strip()
        if not current_voice:
            runtime_config = _runtime_config()
            current_voice = os.path.basename(str(runtime_config.get("voice_path", "") or runtime_config.get("voice_file", "") or "").strip())

        selected_voice = current_voice if current_voice in voices else (voices[0] if voices else "")
        previous = False
        try:
            previous = bool(self.voice_combo.blockSignals(True))
            self.voice_combo.clear()
            self.voice_combo.addItems(voices or ["No .wav found"])
            if selected_voice:
                index = self.voice_combo.findText(selected_voice)
                if index >= 0:
                    self.voice_combo.setCurrentIndex(index)
        finally:
            try:
                self.voice_combo.blockSignals(previous)
            except Exception:
                pass

        if selected_voice:
            _update_runtime_config("voice_path", os.path.join("voices", selected_voice))
        else:
            _update_runtime_config("voice_path", "")
        if hasattr(self, "_refresh_tts_runtime_summary"):
            self._refresh_tts_runtime_summary()
        return voices

    def refresh_resources(self):
        engine = _engine()
        runtime_config = _runtime_config()
        self.refresh_model_list_quietly(quiet=False)

        self.refresh_voice_list(runtime_config.get("voice_file", ""))

        self.refresh_preset_list()
        self.refresh_body_list()
        self._populate_chat_provider_combo(runtime_config.get("chat_provider", "lmstudio"))
        self._refresh_chat_provider_card()

        self.emotional_text.setPlainText(runtime_config.get("emotional_instructions", ""))
        self.system_prompt_text.setPlainText(runtime_config.get("system_prompt", ""))
        if hasattr(self, "sensory_pingpong_prompt_text"):
            default_prompt = getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")
            self.sensory_pingpong_prompt_text.setPlainText(str(runtime_config.get("sensory_pingpong_prompt", default_prompt) or default_prompt))
        self._invoke_addon_service_capability(
            "tts_backend_service",
            "runtime.refresh_resource_widgets",
            {"backend": self, "runtime_config": runtime_config},
            default=None,
            backend_id=str(runtime_config.get("tts_backend", "chatterbox") or "chatterbox").lower(),
        )
        input_mode = str(runtime_config.get("input_mode", "voice_activation") or "voice_activation").lower()
        self.input_mode_combo.setCurrentText("Push-to-Talk" if input_mode == "push_to_talk" else "Voice Activation")
        input_role = str(runtime_config.get("input_message_role", "user") or "user").lower()
        self.input_role_combo.setCurrentText(self._input_role_label_from_value(input_role))
        if hasattr(self, "chat_context_window_spin"):
            self.chat_context_window_spin.setValue(max(4, int(runtime_config.get("chat_context_window_messages", 20) or 20)))
        if hasattr(self, "chat_overflow_policy_combo"):
            self.chat_overflow_policy_combo.setCurrentText(self._chat_overflow_policy_label_from_value(runtime_config.get("chat_context_overflow_policy", "rolling_window")))
        self.stream_mode_combo.setCurrentText("On" if bool(runtime_config.get("stream_mode", False)) else "Off")
        tts_backend = str(runtime_config.get("tts_backend", "chatterbox") or "chatterbox").lower()
        self._populate_tts_backend_combo(selected_value=tts_backend)
        self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "runtime.refresh_resource_widgets",
            {"backend": self, "runtime_config": runtime_config},
            default=None,
            provider_id=str(runtime_config.get("avatar_mode", "vseeface") or "vseeface").lower(),
        )
        for key, slider in self.brain_sliders.items():
            slider.set_value(runtime_config.get(key, slider.value()))
        for key, slider in self.chunking_sliders.items():
            slider.set_value(runtime_config.get(key, slider.value()))
        self._refresh_hotkey_shortcuts()
        self._refresh_hotkey_labels()
        emotion_combo = self._live_widget_attr("emotion_combo")
        if emotion_combo is not None:
            self.on_emotion_change(emotion_combo.currentText())
        self.refresh_performance_profile_list()
        self.refresh_tutorial_list()
        self._update_restart_sensitive_controls()
        self.refresh_dry_run_status()
        self.update_model_budget_hint()
        self._publish_addon_event("app.resources_refreshed", {"source": "refresh_resources"})
