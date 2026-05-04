import glob
import os


def _engine():
    import engine

    return engine


def _runtime_config():
    return getattr(_engine(), "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from engine import update_runtime_config

    return update_runtime_config(key, value)


def _musetalk_vram_mode_labels():
    from qt_app import MUSE_VRAM_MODE_LABELS

    return MUSE_VRAM_MODE_LABELS


class BackendResourceRefreshMixin:
    """Refresh backend UI resources from current runtime/config state."""

    def refresh_resources(self):
        engine = _engine()
        runtime_config = _runtime_config()
        self.refresh_model_list_quietly(quiet=False)

        voices = [os.path.basename(path) for path in glob.glob("voices/*.wav")]
        self.voice_combo.clear()
        self.voice_combo.addItems(voices or ["No .wav found"])
        if voices:
            self.voice_combo.setCurrentIndex(0)
            _update_runtime_config("voice_path", os.path.join("voices", voices[0]))
        else:
            _update_runtime_config("voice_path", "")

        self.refresh_preset_list()
        self.refresh_body_list()
        self._populate_chat_provider_combo(runtime_config.get("chat_provider", "lmstudio"))
        self._refresh_chat_provider_card()

        self.emotional_text.setPlainText(runtime_config.get("emotional_instructions", ""))
        self.system_prompt_text.setPlainText(runtime_config.get("system_prompt", ""))
        if hasattr(self, "sensory_pingpong_prompt_text"):
            default_prompt = getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")
            self.sensory_pingpong_prompt_text.setPlainText(str(runtime_config.get("sensory_pingpong_prompt", default_prompt) or default_prompt))
        if hasattr(self, "pocket_tts_python_edit"):
            self.pocket_tts_python_edit.setText(str(runtime_config.get("pocket_tts_python", "") or ""))
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
        vram_mode = str(runtime_config.get("musetalk_vram_mode", "quality") or "quality").lower()
        musetalk_vram_combo = self._live_widget_attr("musetalk_vram_combo")
        if musetalk_vram_combo is not None:
            musetalk_vram_combo.setCurrentText(_musetalk_vram_mode_labels().get(vram_mode, "Quality"))
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
