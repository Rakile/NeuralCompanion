import glob
import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from core import avatar_hand_state, chat_providers
from ui.panels.input_dialog import QtInputDialog


DEFAULT_MAX_RESPONSE_TOKENS = 600


from ui.runtime.engine_access import engine_module as _engine


def _runtime_config():
    return _engine().RUNTIME_CONFIG


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


class BackendPresetBodyRuntimeMixin:
    """Preset and body-config list/save/load/delete behavior."""
    def _on_runtime_section_toggled(self):
        self._sync_host_settings_tabs_height()
        self.save_session()

    def _build_preset_payload(self, ensure_pocket_tts_path=False):
        runtime_config = _runtime_config()
        engine = _engine()
        chat_provider_generation_settings = dict(runtime_config.get("chat_provider_generation_settings", {}) or {})
        payload = {
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(runtime_config.get("chat_provider_settings", {}) or {}),
            "model_name": self.model_combo.currentText(),
            "voice_file": self._current_voice_file_value(),
            "input_mode": "push_to_talk" if self.input_mode_combo.currentText() == "Push-to-Talk" else "voice_activation",
            "input_message_role": self._input_role_value_from_label(self.input_role_combo.currentText()),
            "stream_mode": self.stream_mode_combo.currentText() == "On",
            "tts_backend": self._current_tts_backend_value(),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(runtime_config.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(runtime_config.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(runtime_config.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(runtime_config.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(runtime_config.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(runtime_config.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(runtime_config.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(runtime_config.get("sensory_pingpong_source_prompts", {}) or {}),
            "sensory_provider_metadata_overrides": self._current_sensory_provider_metadata_override_map() if hasattr(self, "_current_sensory_provider_metadata_override_map") else dict(runtime_config.get("sensory_provider_metadata_overrides", {}) or {}),
            "allow_proactive_replies": self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else True,
            "require_first_user_before_proactive": self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False,
            "listen_idle_window_seconds": float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0,
            "proactive_delay_seconds": float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0,
            "chat_context_window_messages": int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20,
            "stored_chat_history_limit": int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0,
            "chat_context_overflow_policy": self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window",
            "emotional_instructions": self.emotional_text.toPlainText().strip(),
            "system_prompt": self.system_prompt_text.toPlainText().strip(),
            "temperature": self.brain_sliders["temperature"].value(),
            "top_p": self.brain_sliders["top_p"].value(),
            "top_k": self.brain_sliders["top_k"].value(),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value(),
            "min_p": self.brain_sliders["min_p"].value(),
            "limit_response_length": self.limit_response_checkbox.isChecked(),
            "max_response_tokens": int(self.max_response_tokens_spin.value()),
        }
        if chat_provider_generation_settings:
            payload["chat_provider_generation_settings"] = chat_provider_generation_settings
        if self._addon_manager is not None:
            try:
                payload.update(self._addon_manager.export_preset_state())
            except Exception:
                pass
        return payload

    def _preset_payload_signature(self, payload):
        return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def _refresh_preset_dirty_state(self):
        if not hasattr(self, "btn_preset_save") or not hasattr(self, "btn_preset_save_as"):
            return
        if not bool(getattr(self, "_preset_dirty_tracking_ready", False)):
            return
        if bool(getattr(self, "_restoring_session", False)):
            return
        current_signature = self._preset_payload_signature(self._build_preset_payload())
        if self._preset_reference_signature:
            dirty = current_signature != self._preset_reference_signature
        else:
            dirty = False
            self._preset_reference_signature = current_signature
            self._preset_reference_name = str(self.preset_combo.currentText() or "")
        if dirty != self._preset_dirty_state:
            self._preset_dirty_state = dirty
            style = "border: 2px solid #d84a4a; border-radius: 10px;" if dirty else ""
            self.btn_preset_save.setStyleSheet(style)
            self.btn_preset_save_as.setStyleSheet(style)

    def _update_preset_reference_from_selection(self, preset_name=None):
        name = str(preset_name or self.preset_combo.currentText() or "").strip()
        if name in {"", "Select Preset...", "No Presets"}:
            self._preset_reference_name = ""
            self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
        else:
            path = Path("presets") / f"{name}.json"
            self._preset_reference_name = name
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self._preset_reference_signature = self._preset_payload_signature(data)
                except Exception:
                    self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
            else:
                self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
        self._preset_dirty_tracking_ready = True
        self._refresh_preset_dirty_state()

    def _update_preset_reference_from_current_state(self, preset_name=None):
        name = str(preset_name or self.preset_combo.currentText() or "").strip()
        if name in {"", "Select Preset...", "No Presets"}:
            self._preset_reference_name = ""
        else:
            self._preset_reference_name = name
        self._preset_reference_signature = self._preset_payload_signature(self._build_preset_payload())
        self._preset_dirty_tracking_ready = True
        self._refresh_preset_dirty_state()

    def _queue_preset_clean_after_model_refresh(self, preset_name, provider_id="", model_name=""):
        self._pending_preset_clean_name = str(preset_name or "").strip()
        self._pending_preset_clean_provider = chat_providers.normalize_provider_id(
            provider_id or self._current_chat_provider_value(),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        self._pending_preset_clean_model = str(model_name or "").strip()

    def _finalize_pending_preset_clean_if_ready(self, *, force=False):
        name = str(getattr(self, "_pending_preset_clean_name", "") or "").strip()
        if not name:
            return False
        provider_id = str(getattr(self, "_pending_preset_clean_provider", "") or "").strip()
        model_name = str(getattr(self, "_pending_preset_clean_model", "") or "").strip()
        if provider_id and self._current_chat_provider_value() != provider_id:
            return False
        if model_name and hasattr(self, "model_combo"):
            current_model = str(self.model_combo.currentText() or "").strip()
            if current_model != model_name and not force:
                return False
        self._pending_preset_clean_name = ""
        self._pending_preset_clean_provider = ""
        self._pending_preset_clean_model = ""
        self._update_preset_reference_from_current_state(name)
        return True

    def _finalize_session_restore_dirty_state(self):
        self._restoring_session = False
        self._update_preset_reference_from_selection(self.preset_combo.currentText() if hasattr(self, "preset_combo") else "")
        self._refresh_preset_dirty_state()

    def on_preset_selection_changed(self, text):
        selected = str(text or "").strip()
        if selected in {"", "Select Preset...", "No Presets"}:
            _update_runtime_config("active_preset_name", "")
        else:
            _update_runtime_config("active_preset_name", selected)
        self._update_preset_reference_from_selection(selected)

    def refresh_preset_list(self):
        current = str(self.preset_combo.currentText() or "").strip() if hasattr(self, "preset_combo") else ""
        presets = [Path(path).stem for path in glob.glob("presets/*.json")]
        self.preset_combo.clear()
        self.preset_combo.addItems(presets or ["No Presets"])
        if current and current in presets:
            self.preset_combo.setCurrentText(current)

    def refresh_body_list(self):
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        bodies = [Path(path).stem for path in glob.glob("body_configs/*.json")]
        body_combo.clear()
        body_combo.addItems(bodies or ["No Configs"])

    def load_preset(self):
        name = self.preset_combo.currentText()
        if not name or name in {"No Presets", "Select Preset..."}:
            return
        path = Path("presets") / f"{name}.json"
        if not path.exists():
            return
        scroll_state = (
            self._capture_vertical_scroll_state(self.system_shaping_scroll)
            if hasattr(self, "system_shaping_scroll")
            else None
        )
        _update_runtime_config("active_preset_name", name)
        data = json.loads(path.read_text(encoding="utf-8"))
        preset_model_name = str(data.get("model_name") or "").strip()
        preset_provider_name = chat_providers.normalize_provider_id(
            data.get("chat_provider", self._current_chat_provider_value()),
            fallback=chat_providers.DEFAULT_PROVIDER_ID,
        )
        self._queue_preset_clean_after_model_refresh(name, preset_provider_name, preset_model_name)
        if preset_model_name:
            self._pending_restored_model_name = preset_model_name
            _update_runtime_config("model_name", preset_model_name)
        if "chat_provider" in data and hasattr(self, "chat_provider_combo"):
            self._set_chat_provider_selection(data["chat_provider"])
            self.on_chat_provider_changed(self.chat_provider_combo.currentText())
        if "chat_provider_settings" in data:
            _update_runtime_config("chat_provider_settings", data.get("chat_provider_settings", {}))
            self._refresh_chat_provider_card()
        _update_runtime_config("chat_provider_generation_settings", data.get("chat_provider_generation_settings", {}))
        self._refresh_chat_provider_generation_card()
        if preset_model_name:
            self._apply_saved_model_name(preset_model_name)
        if "voice_file" in data:
            voice_file = str(data.get("voice_file") or "").strip()
            if voice_file and voice_file != "No .wav found" and self.voice_combo.findText(voice_file) >= 0:
                index = self.voice_combo.findText(voice_file)
                self.voice_combo.setCurrentIndex(index)
            else:
                _update_runtime_config("voice_path", "")
        if "input_mode" in data:
            mode_text = "Push-to-Talk" if str(data["input_mode"]).lower() == "push_to_talk" else "Voice Activation"
            self.input_mode_combo.setCurrentText(mode_text)
        if "input_message_role" in data:
            role_text = self._input_role_label_from_value(data["input_message_role"])
            self.input_role_combo.setCurrentText(role_text)
        if "stream_mode" in data:
            self.stream_mode_combo.setCurrentText("On" if bool(data["stream_mode"]) else "Off")
        if "sensory_pingpong_enabled" in data and hasattr(self, "sensory_pingpong_checkbox"):
            pingpong_enabled = bool(data["sensory_pingpong_enabled"])
            self.sensory_pingpong_checkbox.setChecked(pingpong_enabled)
            self.on_sensory_pingpong_enabled_changed(pingpong_enabled)
        if "sensory_allow_hidden_proactive_speech" in data and hasattr(self, "sensory_allow_hidden_proactive_checkbox"):
            proactive_enabled = bool(data["sensory_allow_hidden_proactive_speech"])
            self.sensory_allow_hidden_proactive_checkbox.setChecked(proactive_enabled)
            self.on_sensory_allow_hidden_proactive_changed(proactive_enabled)
        if "sensory_allow_hidden_visual_generation" in data and hasattr(self, "sensory_allow_hidden_visual_checkbox"):
            visual_enabled = bool(data["sensory_allow_hidden_visual_generation"])
            self.sensory_allow_hidden_visual_checkbox.setChecked(visual_enabled)
            self.on_sensory_allow_hidden_visual_changed(visual_enabled)
        if "sensory_pingpong_history_depth" in data and hasattr(self, "sensory_pingpong_history_spin"):
            pingpong_depth = max(0, int(data["sensory_pingpong_history_depth"] or 0))
            self.sensory_pingpong_history_spin.setValue(pingpong_depth)
            self.on_sensory_pingpong_history_depth_changed(pingpong_depth)
        if "sensory_pingpong_prompt" in data and hasattr(self, "sensory_pingpong_prompt_text"):
            prompt_text = str(data["sensory_pingpong_prompt"] or getattr(_engine(), "DEFAULT_SENSORY_PINGPONG_PROMPT", "")).strip() or getattr(_engine(), "DEFAULT_SENSORY_PINGPONG_PROMPT", "")
            self.sensory_pingpong_prompt_text.setPlainText(prompt_text)
            _update_runtime_config("sensory_pingpong_prompt", prompt_text)
        if "sensory_pingpong_source_prompts" in data:
            prompt_map = self._normalize_sensory_pingpong_source_prompt_map(data.get("sensory_pingpong_source_prompts", {})) if hasattr(self, "_normalize_sensory_pingpong_source_prompt_map") else dict(data.get("sensory_pingpong_source_prompts", {}) or {})
            _update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
            self._refresh_sensory_feedback_source_tabs()
        if "sensory_provider_metadata_overrides" in data:
            metadata_map = self._normalize_sensory_provider_metadata_override_map(data.get("sensory_provider_metadata_overrides", {})) if hasattr(self, "_normalize_sensory_provider_metadata_override_map") else dict(data.get("sensory_provider_metadata_overrides", {}) or {})
            _update_runtime_config("sensory_provider_metadata_overrides", metadata_map)
            self._refresh_sensory_feedback_source_tabs()
        if "sensory_feedback_source" in data and hasattr(self, "sensory_feedback_source_combo"):
            source_value = str(data["sensory_feedback_source"] or "off")
            self.refresh_sensory_feedback_source_options(selected_value=source_value)
            self.on_sensory_feedback_source_changed(source_value)
        if "sensory_feedback_interval_seconds" in data and hasattr(self, "sensory_feedback_interval_spin"):
            interval_seconds = max(2.0, float(data["sensory_feedback_interval_seconds"] or 7.0))
            self.sensory_feedback_interval_spin.setValue(interval_seconds)
            self.on_sensory_feedback_interval_changed(interval_seconds)
        if "tts_backend" in data and hasattr(self, "tts_backend_combo"):
            backend_value = str(data["tts_backend"]).strip().lower()
            combo = self.tts_backend_combo
            combo.blockSignals(True)
            try:
                self._populate_tts_backend_combo(selected_value=backend_value)
                index = combo.findData(backend_value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            finally:
                combo.blockSignals(False)
        if "allow_proactive_replies" in data and hasattr(self, "allow_proactive_checkbox"):
            self.allow_proactive_checkbox.setChecked(bool(data["allow_proactive_replies"]))
            self.on_allow_proactive_replies_changed(bool(data["allow_proactive_replies"]))
        if "require_first_user_before_proactive" in data and hasattr(self, "require_first_user_checkbox"):
            self.require_first_user_checkbox.setChecked(bool(data["require_first_user_before_proactive"]))
            self.on_require_first_user_before_proactive_changed(bool(data["require_first_user_before_proactive"]))
        if "listen_idle_window_seconds" in data and hasattr(self, "listen_idle_window_spin"):
            listen_seconds = max(0.5, float(data["listen_idle_window_seconds"] or 5.0))
            self.listen_idle_window_spin.setValue(listen_seconds)
            self.on_listen_idle_window_changed(listen_seconds)
        if "proactive_delay_seconds" in data and hasattr(self, "proactive_delay_spin"):
            proactive_seconds = max(0.5, float(data["proactive_delay_seconds"] or 10.0))
            self.proactive_delay_spin.setValue(proactive_seconds)
            self.on_proactive_delay_changed(proactive_seconds)
        if "chat_context_window_messages" in data and hasattr(self, "chat_context_window_spin"):
            context_messages = max(4, int(data["chat_context_window_messages"] or 20))
            self.chat_context_window_spin.setValue(context_messages)
            self.on_chat_context_window_changed(context_messages)
        if "stored_chat_history_limit" in data and hasattr(self, "stored_chat_history_limit_spin"):
            stored_limit = max(0, int(data["stored_chat_history_limit"] or 0))
            self.stored_chat_history_limit_spin.setValue(stored_limit)
            self.on_stored_chat_history_limit_changed(stored_limit)
        if "chat_context_overflow_policy" in data and hasattr(self, "chat_overflow_policy_combo"):
            policy_text = self._chat_overflow_policy_label_from_value(data["chat_context_overflow_policy"])
            self.chat_overflow_policy_combo.setCurrentText(policy_text)
            self.on_chat_overflow_policy_changed(policy_text)
        self.emotional_text.setPlainText(data.get("emotional_instructions", ""))
        self.system_prompt_text.setPlainText(data.get("system_prompt", ""))
        for key, slider in self.brain_sliders.items():
            if key in data:
                slider.set_value(data[key])
                self.update_brain_value(key, data[key], key == "top_k")
        if "limit_response_length" in data:
            self.limit_response_checkbox.setChecked(bool(data["limit_response_length"]))
            self.on_limit_response_length_changed(bool(data["limit_response_length"]))
        if "max_response_tokens" in data:
            tokens = max(32, int(data["max_response_tokens"] or DEFAULT_MAX_RESPONSE_TOKENS))
            self.max_response_tokens_spin.setValue(tokens)
            self.on_max_response_tokens_changed(tokens)
        self._refresh_chat_provider_generation_card()
        previous_restoring_preset = bool(getattr(self, "_restoring_preset", False))
        self._restoring_preset = True
        try:
            if self._addon_manager is not None:
                try:
                    self._addon_manager.import_preset_state(data)
                except Exception:
                    pass
            self._refresh_sensory_feedback_source_tabs()
            self._refresh_addon_group_tabs()
            self._refresh_tts_runtime_card(activate_tab=False)
        finally:
            self._restoring_preset = previous_restoring_preset
        print(f"[QtGUI] Loading preset: {name}...")
        self.emit_tutorial_event("preset_loaded", {"name": name})
        self._finalize_pending_preset_clean_if_ready()
        self.save_session()
        self._restore_system_shaping_scroll_state(scroll_state)
        QtCore.QTimer.singleShot(0, lambda state=scroll_state: self._restore_system_shaping_scroll_state(state))
        QtCore.QTimer.singleShot(150, lambda state=scroll_state: self._restore_system_shaping_scroll_state(state))

    def save_preset_dialog(self):
        name = QtInputDialog.get_text("Save Preset", "Enter Preset Name:", self)
        if name:
            self.save_preset(name)

    def save_current_preset(self):
        name = self.preset_combo.currentText()
        if not name or name in {"No Presets", "Select Preset..."}:
            self.save_preset_dialog()
            return
        self.save_preset(name)

    def save_preset(self, name):
        data = self._build_preset_payload(ensure_pocket_tts_path=True)
        path = Path("presets") / f"{name}.json"
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        self.refresh_preset_list()
        index = self.preset_combo.findText(name)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        self._update_preset_reference_from_selection(name)
        print(f"[QtGUI] Saved preset: {path}")
        self.save_session()

    def delete_current_preset(self):
        name = self.preset_combo.currentText()
        if not name or name in {"No Presets", "Select Preset..."}:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Preset", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        path = Path("presets") / f"{name}.json"
        if path.exists():
            path.unlink()
        self.refresh_preset_list()
        print(f"[QtGUI] Deleted preset: {path}")

    def save_body_dialog(self):
        name = QtInputDialog.get_text("Save Body Config", "Enter Body Config Name:", self)
        if name:
            self.save_body_config(name)

    def save_current_body(self):
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        name = body_combo.currentText()
        if not name or name == "No Configs":
            self.save_body_dialog()
            return
        self.save_body_config(name)

    def save_body_config(self, name):
        data = {
            "profile": _engine().AVATAR_PROFILE,
            "hands": avatar_hand_state.HAND_CALIBRATION,
        }
        path = Path("body_configs") / f"{name}.json"
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        self.refresh_body_list()
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is not None:
            index = body_combo.findText(name)
            if index >= 0:
                body_combo.setCurrentIndex(index)
        print(f"[QtGUI] Saved Full Body & Hands: {path}")
        self.save_session()

    def load_body_config_from_combo(self):
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        name = body_combo.currentText()
        if not name or name == "No Configs":
            return
        path = Path("body_configs") / f"{name}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        if "profile" in data:
            _engine().AVATAR_PROFILE.update(data["profile"])
            if "hands" in data:
                avatar_hand_state.HAND_CALIBRATION.update(data["hands"])
        else:
            _engine().AVATAR_PROFILE.update(data)
        emotion_combo = self._live_widget_attr("emotion_combo")
        if emotion_combo is not None:
            self.on_emotion_change(emotion_combo.currentText())
        print(f"[QtGUI] Loading Config: {name}...")
        self.save_session()

    def delete_current_body(self):
        body_combo = self._live_widget_attr("body_combo")
        if body_combo is None:
            return
        name = body_combo.currentText()
        if not name or name in {"No Configs", "Default"}:
            return
        if QtWidgets.QMessageBox.question(self, "Delete Body Config", f"Delete '{name}'?") != QtWidgets.QMessageBox.Yes:
            return
        path = Path("body_configs") / f"{name}.json"
        if path.exists():
            path.unlink()
        self.refresh_body_list()
        print(f"[QtGUI] Deleted body config: {path}")

