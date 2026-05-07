"""Session persistence helpers for the runtime-backed main window."""

import base64
import json
import os
from collections import OrderedDict
from pathlib import Path

from PySide6 import QtCore, QtWidgets

import engine
from engine import RUNTIME_CONFIG, update_runtime_config
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES, UI_SHELL_MUSE_VRAM_MODE_LABELS

SESSION_PATH = Path("qt_session.json")
QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_CHUNKING_VALUES = UI_SHELL_DEFAULT_CHUNKING_VALUES
DEFAULT_MAX_RESPONSE_TOKENS = 600
MUSE_VRAM_MODE_LABELS = OrderedDict(UI_SHELL_MUSE_VRAM_MODE_LABELS)


class MainWindowSessionMixin:
    def save_session(self):
        if bool(getattr(self, "_session_read_only", False)):
            return
        if bool(getattr(self, "_suspend_session_save", False)):
            return
        preserved_main_ui_real_layout = None
        try:
            if SESSION_PATH.exists():
                previous_session = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
                if isinstance(previous_session, dict):
                    preserved_main_ui_real_layout = previous_session.get("main_ui_real_layout")
        except Exception:
            preserved_main_ui_real_layout = None
        session = {
            "first_run": bool(self.first_run),
            "ui_theme_preset": self.current_app_theme_preset(),
            "avatar_mode": self._current_avatar_mode_value(),
            "audio_input_device": self.audio_input_device_combo.currentText() if hasattr(self, "audio_input_device_combo") else str(RUNTIME_CONFIG.get("audio_input_device", "Default Input") or "Default Input"),
            "audio_output_device": self.audio_output_device_combo.currentText() if hasattr(self, "audio_output_device_combo") else str(RUNTIME_CONFIG.get("audio_output_device", "Default Output") or "Default Output"),
            "voice_file": self._current_voice_file_value() if hasattr(self, "voice_combo") else "",
            "input_mode": self.input_mode_combo.currentText(),
            "input_message_role": self.input_role_combo.currentText(),
            "push_to_talk_hotkey": engine.get_push_to_talk_hotkey(),
            "manual_action_hotkeys": dict(engine.get_manual_action_hotkeys()),
            "ui_action_hotkeys": dict(engine.get_ui_action_hotkeys()),
            "stream_mode": self.stream_mode_combo.currentText(),
            "tts_backend": self._current_tts_backend_value(),
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "chat_provider_generation_settings": dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {}),
            "chat_font_size": int(self.chat_font_size_combo.currentData() or 12) if hasattr(self, "chat_font_size_combo") else 12,
            "chat_runtime_expanded": self.chat_runtime_section.isExpanded() if hasattr(self, "chat_runtime_section") else True,
            "tts_runtime_expanded": self.tts_runtime_section.isExpanded() if hasattr(self, "tts_runtime_section") else True,
            "model_name": self.model_combo.currentText() if hasattr(self, "model_combo") else str(RUNTIME_CONFIG.get("model_name", "") or ""),
            "model_requires_vision": self.model_requires_vision_checkbox.isChecked() if hasattr(self, "model_requires_vision_checkbox") else False,
            "model_supports_images": self._current_model_supports_images_value(self.model_combo.currentText()) if hasattr(self, "model_combo") else RUNTIME_CONFIG.get("model_supports_images", None),
            "allow_proactive_replies": self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else True,
            "require_first_user_before_proactive": self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False,
            "listen_idle_window_seconds": float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0,
            "proactive_delay_seconds": float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0,
            "chat_context_window_messages": int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20,
            "stored_chat_history_limit": int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0,
            "chat_context_overflow_policy": self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window",
            "limit_response_length": self.limit_response_checkbox.isChecked() if hasattr(self, "limit_response_checkbox") else False,
            "max_response_tokens": int(self.max_response_tokens_spin.value()) if hasattr(self, "max_response_tokens_spin") else DEFAULT_MAX_RESPONSE_TOKENS,
            "musetalk_vram_mode": next(
                (key for key, label in MUSE_VRAM_MODE_LABELS.items() if label == self._live_combo_text("musetalk_vram_combo", "")),
                "quality",
            ),
            "musetalk_loop_fade_ms": int(self._live_value("musetalk_loop_fade_spin", RUNTIME_CONFIG.get("musetalk_loop_fade_ms", QT_MUSETALK_LOOP_FADE_MS))),
            "musetalk_use_frame_cache": bool(self._live_checked("musetalk_use_frame_cache_checkbox", RUNTIME_CONFIG.get("musetalk_use_frame_cache", True))),
            "musetalk_avatar_pack_id": str(self._live_combo_data("musetalk_avatar_pack_combo", RUNTIME_CONFIG.get("musetalk_avatar_pack_id", "")) or ""),
            "vam_vmc_enabled": self._live_checked("vam_vmc_enabled_checkbox", RUNTIME_CONFIG.get("vam_vmc_enabled", True)),
            "vam_vmc_host": self._live_text("vam_vmc_host_edit", RUNTIME_CONFIG.get("vam_vmc_host", "127.0.0.1")).strip() or "127.0.0.1",
            "vam_vmc_port": int(self._live_value("vam_vmc_port_spin", RUNTIME_CONFIG.get("vam_vmc_port", 39539) or 39539)),
            "vam_bridge_enabled": self._live_checked("vam_bridge_enabled_checkbox", RUNTIME_CONFIG.get("vam_bridge_enabled", True)),
            "vam_root": self._current_vam_root_value() if self._live_widget_attr("vam_root_edit") is not None else str(RUNTIME_CONFIG.get("vam_root", getattr(engine, "DEFAULT_VAM_ROOT", "")) or getattr(engine, "DEFAULT_VAM_ROOT", "")),
            "vam_bridge_root": self._current_vam_bridge_root_value() if self._live_widget_attr("vam_bridge_root_edit") is not None else str(RUNTIME_CONFIG.get("vam_bridge_root", getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")) or getattr(engine, "DEFAULT_VAM_BRIDGE_ROOT", "")),
            "vam_play_audio_in_vam": self._live_checked("vam_play_audio_in_vam_checkbox", RUNTIME_CONFIG.get("vam_play_audio_in_vam", False)),
            "vam_target_atom_uid": self._live_text("vam_target_atom_uid_edit", RUNTIME_CONFIG.get("vam_target_atom_uid", "Person")).strip() or "Person",
            "vam_target_storable_id": self._live_text("vam_target_storable_id_edit", RUNTIME_CONFIG.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge")).strip() or "plugin#0_NeuralCompanionBridge",
            "vam_timeline_auto_resume": self._live_checked("vam_timeline_auto_resume_checkbox", RUNTIME_CONFIG.get("vam_timeline_auto_resume", True)),
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
            "performance_profile": self.performance_profile_combo.currentData() if hasattr(self, "performance_profile_combo") else "",
            "emotional_instructions": self.emotional_text.toPlainText().strip() if hasattr(self, "emotional_text") else str(RUNTIME_CONFIG.get("emotional_instructions", "") or ""),
            "system_prompt": self.system_prompt_text.toPlainText().strip() if hasattr(self, "system_prompt_text") else str(RUNTIME_CONFIG.get("system_prompt", "") or ""),
            "temperature": self.brain_sliders["temperature"].value() if "temperature" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("temperature", 1.22) or 1.22),
            "top_p": self.brain_sliders["top_p"].value() if "top_p" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("top_p", 0.9) or 0.9),
            "top_k": int(self.brain_sliders["top_k"].value()) if "top_k" in getattr(self, "brain_sliders", {}) else int(RUNTIME_CONFIG.get("top_k", 40) or 40),
            "repeat_penalty": self.brain_sliders["repeat_penalty"].value() if "repeat_penalty" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("repeat_penalty", 1.15) or 1.15),
            "min_p": self.brain_sliders["min_p"].value() if "min_p" in getattr(self, "brain_sliders", {}) else float(RUNTIME_CONFIG.get("min_p", 0.05) or 0.05),
            "chunking": {key: slider.value() for key, slider in self.chunking_sliders.items()},
            "dry_run_target_samples": self.dry_run_target_spin.value(),
            "dry_run_auto_replies": self.dry_run_auto_replies_checkbox.isChecked(),
            "last_preset": self.preset_combo.currentText(),
            "last_body": self._live_combo_text("body_combo", RUNTIME_CONFIG.get("last_body", "")),
            "live_sync": self._live_checked("live_sync_checkbox", RUNTIME_CONFIG.get("live_sync", False)),
            "geometry": [self.x(), self.y(), self.width(), self.height()],
            "main_splitter_sizes": self.main_splitter.sizes() if hasattr(self, "main_splitter") else [400, 980],
            "pinned_floating_docks": sorted(getattr(self, "_pinned_floating_dock_names", set()) or []),
            "always_on_top_floating_docks": sorted(getattr(self, "_always_on_top_floating_dock_names", set()) or []),
            "preview_visible": bool(hasattr(self, "preview_dock") and self.preview_dock.isVisible()),
            "visual_reply_visible": bool(
                self._visual_reply_addon_enabled()
                and hasattr(self, "visual_reply_dock")
                and self.visual_reply_dock.isVisible()
            ),
            "performance_guidance_visible": bool(hasattr(self, "guidance_box") and self.guidance_box.isVisible()),
            "window_state": base64.b64encode(self.saveState().data()).decode("ascii"),
            "right_dock_state": (
                base64.b64encode(self.right_dock_host.saveState().data()).decode("ascii")
                if hasattr(self, "right_dock_host")
                else ""
            ),
        }
        if isinstance(preserved_main_ui_real_layout, dict):
            session["main_ui_real_layout"] = preserved_main_ui_real_layout
        if self._addon_manager is not None:
            session.update(self._addon_manager.export_session_state())
        SESSION_PATH.write_text(json.dumps(session, indent=4), encoding="utf-8")

    def _ensure_window_on_screen(self):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        client = self.geometry()
        width = min(max(client.width(), 200), max(available.width(), 200))
        height = min(max(client.height(), 200), max(available.height(), 200))
        x = frame.x()
        y = frame.y()
        if x < available.left():
            x = available.left()
        if y < available.top():
            y = available.top()
        if x + width > available.right() + 1:
            x = max(available.left(), available.right() - width + 1)
        if y + height > available.bottom() + 1:
            y = max(available.top(), available.bottom() - height + 1)
        self.setGeometry(x, y, width, height)
        self.move(x, y)

    def restore_session(self):
        if not SESSION_PATH.exists():
            return
        try:
            session = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[QtGUI] Session Restore Failed: {exc}")
            return
        previous_suspend = bool(getattr(self, "_suspend_session_save", False))
        self._suspend_session_save = True
        self._restoring_session = True
        try:
            self.first_run = bool(session.get("first_run", True))
            ui_theme_preset = session.get("ui_theme_preset")
            if ui_theme_preset is not None:
                self.apply_app_theme_preset(ui_theme_preset, save_session=False)
            geometry = session.get("geometry")
            if geometry and len(geometry) == 4:
                self.setGeometry(*geometry)
                self._ensure_window_on_screen()
            preset = session.get("last_preset")
            if preset:
                index = self.preset_combo.findText(preset)
                if index >= 0:
                    self.preset_combo.setCurrentIndex(index)
                    update_runtime_config("active_preset_name", preset)

            engine_choice = session.get("avatar_mode")
            if isinstance(engine_choice, str) and engine_choice.strip().lower() == "lam":
                engine_choice = "MuseTalk"
            if engine_choice:
                index = self.engine_combo.findData(str(engine_choice).strip().lower())
                if index < 0:
                    index = self.engine_combo.findText(engine_choice)
                if index >= 0:
                    self.engine_combo.setCurrentIndex(index)
            vam_play_audio = self._live_widget_attr("vam_play_audio_in_vam_checkbox")
            if str(engine_choice or "").strip().lower() == "vam" and vam_play_audio is not None:
                vam_play_audio.setChecked(True)
                self.on_vam_play_audio_in_vam_changed(True)
            audio_input_device = session.get("audio_input_device")
            if audio_input_device is not None:
                audio_input_device = self._resolve_audio_device_label(audio_input_device, direction="input")
                update_runtime_config("audio_input_device", str(audio_input_device or "Default Input") or "Default Input")
                if hasattr(self, "audio_input_device_combo"):
                    self.audio_input_device_combo.blockSignals(True)
                    index = self.audio_input_device_combo.findText(str(audio_input_device))
                    if index >= 0:
                        self.audio_input_device_combo.setCurrentIndex(index)
                    self.audio_input_device_combo.blockSignals(False)
            audio_output_device = session.get("audio_output_device")
            if audio_output_device is not None:
                audio_output_device = self._resolve_audio_device_label(audio_output_device, direction="output")
                update_runtime_config("audio_output_device", str(audio_output_device or "Default Output") or "Default Output")
                if hasattr(self, "audio_output_device_combo"):
                    self.audio_output_device_combo.blockSignals(True)
                    index = self.audio_output_device_combo.findText(str(audio_output_device))
                    if index >= 0:
                        self.audio_output_device_combo.setCurrentIndex(index)
                    self.audio_output_device_combo.blockSignals(False)
            input_mode = session.get("input_mode")
            if input_mode:
                index = self.input_mode_combo.findText(input_mode)
                if index >= 0:
                    self.input_mode_combo.setCurrentIndex(index)
            voice_file = str(session.get("voice_file", "") or "").strip()
            if voice_file and voice_file != "No .wav found" and hasattr(self, "voice_combo"):
                index = self.voice_combo.findText(voice_file)
                if index >= 0:
                    self.voice_combo.blockSignals(True)
                    try:
                        self.voice_combo.setCurrentIndex(index)
                    finally:
                        self.voice_combo.blockSignals(False)
                    update_runtime_config("voice_path", os.path.join("voices", voice_file))
                else:
                    update_runtime_config("voice_path", "")
            push_to_talk_hotkey = session.get("push_to_talk_hotkey")
            if push_to_talk_hotkey is not None:
                engine.set_push_to_talk_hotkey(push_to_talk_hotkey)
            manual_action_hotkeys = session.get("manual_action_hotkeys")
            if manual_action_hotkeys is not None:
                update_runtime_config("manual_action_hotkeys", manual_action_hotkeys)
            ui_action_hotkeys = session.get("ui_action_hotkeys")
            if ui_action_hotkeys is not None:
                update_runtime_config("ui_action_hotkeys", ui_action_hotkeys)
            input_role = session.get("input_message_role")
            if input_role:
                index = self.input_role_combo.findText(input_role)
                if index >= 0:
                    self.input_role_combo.setCurrentIndex(index)
            stream_mode = session.get("stream_mode")
            if stream_mode is not None:
                if isinstance(stream_mode, str):
                    index = self.stream_mode_combo.findText(stream_mode)
                    if index >= 0:
                        self.stream_mode_combo.setCurrentIndex(index)
                else:
                    self.stream_mode_combo.setCurrentText("On" if bool(stream_mode) else "Off")
            tts_backend = session.get("tts_backend")
            if tts_backend:
                desired_backend = str(tts_backend or "").strip().lower()
                self._populate_tts_backend_combo(selected_value=desired_backend)
                index = self.tts_backend_combo.findData(desired_backend)
                if index >= 0:
                    self.tts_backend_combo.setCurrentIndex(index)
                self.on_tts_backend_change(self.tts_backend_combo.currentText())
            vam_vmc_enabled = session.get("vam_vmc_enabled")
            widget = self._live_widget_attr("vam_vmc_enabled_checkbox")
            if vam_vmc_enabled is not None and widget is not None:
                widget.setChecked(bool(vam_vmc_enabled))
                self.on_vam_vmc_enabled_changed(bool(vam_vmc_enabled))
            vam_bridge_enabled = session.get("vam_bridge_enabled")
            widget = self._live_widget_attr("vam_bridge_enabled_checkbox")
            if vam_bridge_enabled is not None and widget is not None:
                widget.setChecked(bool(vam_bridge_enabled))
                self.on_vam_bridge_enabled_changed(bool(vam_bridge_enabled))
            vam_play_audio_in_vam = session.get("vam_play_audio_in_vam")
            widget = self._live_widget_attr("vam_play_audio_in_vam_checkbox")
            if vam_play_audio_in_vam is not None and widget is not None:
                widget.setChecked(bool(vam_play_audio_in_vam))
                self.on_vam_play_audio_in_vam_changed(bool(vam_play_audio_in_vam))
            vam_timeline_auto_resume = session.get("vam_timeline_auto_resume")
            widget = self._live_widget_attr("vam_timeline_auto_resume_checkbox")
            if vam_timeline_auto_resume is not None and widget is not None:
                widget.setChecked(bool(vam_timeline_auto_resume))
                self.on_vam_timeline_auto_resume_changed(bool(vam_timeline_auto_resume))
            vam_vmc_host = session.get("vam_vmc_host")
            widget = self._live_widget_attr("vam_vmc_host_edit")
            if vam_vmc_host and widget is not None:
                widget.setText(str(vam_vmc_host))
                self.on_vam_vmc_host_changed()
            vam_vmc_port = session.get("vam_vmc_port")
            widget = self._live_widget_attr("vam_vmc_port_spin")
            if vam_vmc_port is not None and widget is not None:
                widget.setValue(int(vam_vmc_port))
                self.on_vam_vmc_port_changed(int(vam_vmc_port))
            vam_root = session.get("vam_root") or session.get("vam_bridge_root")
            widget = self._live_widget_attr("vam_root_edit")
            if vam_root and widget is not None:
                widget.setText(engine.normalize_vam_root(vam_root))
                self.on_vam_root_changed()
            vam_target_atom_uid = session.get("vam_target_atom_uid")
            widget = self._live_widget_attr("vam_target_atom_uid_edit")
            if vam_target_atom_uid and widget is not None:
                widget.setText(str(vam_target_atom_uid))
                self.on_vam_target_atom_uid_changed()
            vam_target_storable_id = session.get("vam_target_storable_id")
            widget = self._live_widget_attr("vam_target_storable_id_edit")
            if vam_target_storable_id and widget is not None:
                widget.setText(str(vam_target_storable_id))
                self.on_vam_target_storable_id_changed()
            chat_provider = session.get("chat_provider")
            if chat_provider is not None and hasattr(self, "chat_provider_combo"):
                normalized_provider = self._set_chat_provider_selection(chat_provider)
                update_runtime_config("chat_provider", normalized_provider)
            chat_provider_settings = session.get("chat_provider_settings")
            if chat_provider_settings is not None:
                update_runtime_config("chat_provider_settings", chat_provider_settings)
                self._refresh_chat_provider_card()
            chat_provider_generation_settings = session.get("chat_provider_generation_settings")
            if chat_provider_generation_settings is None:
                preset_name = str(session.get("last_preset") or "").strip()
                preset_path = Path("presets") / f"{preset_name}.json" if preset_name else None
                if preset_path is not None and preset_path.exists():
                    try:
                        preset_data = json.loads(preset_path.read_text(encoding="utf-8"))
                        chat_provider_generation_settings = preset_data.get("chat_provider_generation_settings")
                    except Exception:
                        chat_provider_generation_settings = None
            if chat_provider_generation_settings is not None:
                update_runtime_config("chat_provider_generation_settings", chat_provider_generation_settings)
                self._refresh_chat_provider_generation_card()
            chat_font_size = session.get("chat_font_size")
            if chat_font_size is not None and hasattr(self, "chat_font_size_combo"):
                size = max(8, min(20, int(chat_font_size)))
                index = self.chat_font_size_combo.findData(size)
                if index >= 0:
                    self.chat_font_size_combo.setCurrentIndex(index)
                self._apply_chat_font_size(size, update_combo=False)
            if "chat_runtime_expanded" in session and hasattr(self, "chat_runtime_section"):
                self.chat_runtime_section.setExpanded(bool(session.get("chat_runtime_expanded", True)))
            if "tts_runtime_expanded" in session and hasattr(self, "tts_runtime_section"):
                self.tts_runtime_section.setExpanded(bool(session.get("tts_runtime_expanded", True)))
            saved_model_name = str(session.get("model_name") or "").strip()
            if saved_model_name:
                self._pending_restored_model_name = saved_model_name
                update_runtime_config("model_name", saved_model_name)
            self.request_model_list_refresh(quiet=True, wait_for_reachable=False)
            model_requires_vision = session.get("model_requires_vision")
            if model_requires_vision is not None and hasattr(self, "model_requires_vision_checkbox"):
                self.model_requires_vision_checkbox.setChecked(bool(model_requires_vision))
                update_runtime_config("model_requires_vision", bool(model_requires_vision))
            if "model_supports_images" in session:
                update_runtime_config("model_supports_images", session.get("model_supports_images"))
            allow_proactive_replies = session.get("allow_proactive_replies")
            if allow_proactive_replies is not None and hasattr(self, "allow_proactive_checkbox"):
                self.allow_proactive_checkbox.setChecked(bool(allow_proactive_replies))
                self.on_allow_proactive_replies_changed(bool(allow_proactive_replies))
            require_first_user_before_proactive = session.get("require_first_user_before_proactive")
            if require_first_user_before_proactive is not None and hasattr(self, "require_first_user_checkbox"):
                self.require_first_user_checkbox.setChecked(bool(require_first_user_before_proactive))
                self.on_require_first_user_before_proactive_changed(bool(require_first_user_before_proactive))
            listen_idle_window_seconds = session.get("listen_idle_window_seconds")
            if listen_idle_window_seconds is not None and hasattr(self, "listen_idle_window_spin"):
                listen_seconds = max(0.5, float(listen_idle_window_seconds))
                self.listen_idle_window_spin.setValue(listen_seconds)
                self.on_listen_idle_window_changed(listen_seconds)
            proactive_delay_seconds = session.get("proactive_delay_seconds")
            if proactive_delay_seconds is not None and hasattr(self, "proactive_delay_spin"):
                proactive_seconds = max(0.5, float(proactive_delay_seconds))
                self.proactive_delay_spin.setValue(proactive_seconds)
                self.on_proactive_delay_changed(proactive_seconds)
            chat_context_window_messages = session.get("chat_context_window_messages")
            if chat_context_window_messages is not None and hasattr(self, "chat_context_window_spin"):
                context_messages = max(4, int(chat_context_window_messages))
                self.chat_context_window_spin.setValue(context_messages)
                self.on_chat_context_window_changed(context_messages)
            stored_chat_history_limit = session.get("stored_chat_history_limit")
            if stored_chat_history_limit is not None and hasattr(self, "stored_chat_history_limit_spin"):
                stored_limit = max(0, int(stored_chat_history_limit))
                self.stored_chat_history_limit_spin.setValue(stored_limit)
                self.on_stored_chat_history_limit_changed(stored_limit)
            chat_context_overflow_policy = session.get("chat_context_overflow_policy")
            if chat_context_overflow_policy is not None and hasattr(self, "chat_overflow_policy_combo"):
                policy_text = self._chat_overflow_policy_label_from_value(chat_context_overflow_policy)
                self.chat_overflow_policy_combo.setCurrentText(policy_text)
                self.on_chat_overflow_policy_changed(policy_text)
            limit_response_length = session.get("limit_response_length")
            if limit_response_length is not None:
                self.limit_response_checkbox.setChecked(bool(limit_response_length))
                self.on_limit_response_length_changed(bool(limit_response_length))
            max_response_tokens = session.get("max_response_tokens")
            if max_response_tokens is not None:
                tokens = max(32, int(max_response_tokens))
                self.max_response_tokens_spin.setValue(tokens)
                self.on_max_response_tokens_changed(tokens)
            self.refresh_performance_profile_list()
            performance_profile = session.get("performance_profile")
            if performance_profile and hasattr(self, "performance_profile_combo"):
                for index in range(self.performance_profile_combo.count()):
                    if self.performance_profile_combo.itemData(index) == performance_profile:
                        self.performance_profile_combo.setCurrentIndex(index)
                        break
            musetalk_vram_mode = session.get("musetalk_vram_mode")
            if musetalk_vram_mode:
                label = MUSE_VRAM_MODE_LABELS.get(str(musetalk_vram_mode).strip().lower(), None)
                widget = self._live_widget_attr("musetalk_vram_combo")
                if label and widget is not None:
                    index = widget.findText(label)
                    if index >= 0:
                        widget.setCurrentIndex(index)
            musetalk_loop_fade_ms = session.get("musetalk_loop_fade_ms")
            widget = self._live_widget_attr("musetalk_loop_fade_spin")
            if musetalk_loop_fade_ms is not None and widget is not None:
                fade_ms = max(0, int(musetalk_loop_fade_ms))
                widget.setValue(fade_ms)
                self.on_musetalk_loop_fade_changed(fade_ms)
            musetalk_use_frame_cache = session.get("musetalk_use_frame_cache")
            widget = self._live_widget_attr("musetalk_use_frame_cache_checkbox")
            if musetalk_use_frame_cache is not None and widget is not None:
                widget.setChecked(bool(musetalk_use_frame_cache))
                self.on_musetalk_use_frame_cache_changed(bool(musetalk_use_frame_cache))
            sensory_feedback_source = session.get("sensory_feedback_source")
            if sensory_feedback_source is not None and hasattr(self, "sensory_feedback_source_combo"):
                source_value = str(sensory_feedback_source or "off")
                self.refresh_sensory_feedback_source_options(selected_value=source_value)
                self.on_sensory_feedback_source_changed(source_value)
            sensory_feedback_interval_seconds = session.get("sensory_feedback_interval_seconds")
            if sensory_feedback_interval_seconds is not None and hasattr(self, "sensory_feedback_interval_spin"):
                interval_seconds = max(2.0, float(sensory_feedback_interval_seconds))
                self.sensory_feedback_interval_spin.setValue(interval_seconds)
                self.on_sensory_feedback_interval_changed(interval_seconds)
            sensory_pingpong_enabled = session.get("sensory_pingpong_enabled")
            if sensory_pingpong_enabled is not None and hasattr(self, "sensory_pingpong_checkbox"):
                pingpong_enabled = bool(sensory_pingpong_enabled)
                self.sensory_pingpong_checkbox.setChecked(pingpong_enabled)
                self.on_sensory_pingpong_enabled_changed(pingpong_enabled)
            sensory_allow_hidden_proactive_speech = session.get("sensory_allow_hidden_proactive_speech")
            if sensory_allow_hidden_proactive_speech is not None and hasattr(self, "sensory_allow_hidden_proactive_checkbox"):
                proactive_enabled = bool(sensory_allow_hidden_proactive_speech)
                self.sensory_allow_hidden_proactive_checkbox.setChecked(proactive_enabled)
                self.on_sensory_allow_hidden_proactive_changed(proactive_enabled)
            sensory_allow_hidden_visual_generation = session.get("sensory_allow_hidden_visual_generation")
            if sensory_allow_hidden_visual_generation is not None and hasattr(self, "sensory_allow_hidden_visual_checkbox"):
                visual_enabled = bool(sensory_allow_hidden_visual_generation)
                self.sensory_allow_hidden_visual_checkbox.setChecked(visual_enabled)
                self.on_sensory_allow_hidden_visual_changed(visual_enabled)
            sensory_pingpong_history_depth = session.get("sensory_pingpong_history_depth")
            if sensory_pingpong_history_depth is not None and hasattr(self, "sensory_pingpong_history_spin"):
                pingpong_depth = max(0, int(sensory_pingpong_history_depth))
                self.sensory_pingpong_history_spin.setValue(pingpong_depth)
                self.on_sensory_pingpong_history_depth_changed(pingpong_depth)
            sensory_pingpong_prompt = session.get("sensory_pingpong_prompt")
            if sensory_pingpong_prompt is not None and hasattr(self, "sensory_pingpong_prompt_text"):
                prompt_text = str(sensory_pingpong_prompt or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")).strip() or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")
                self.sensory_pingpong_prompt_text.setPlainText(prompt_text)
                update_runtime_config("sensory_pingpong_prompt", prompt_text)
            sensory_pingpong_source_prompts = session.get("sensory_pingpong_source_prompts")
            if sensory_pingpong_source_prompts is not None:
                prompt_map = self._normalize_sensory_pingpong_source_prompt_map(sensory_pingpong_source_prompts) if hasattr(self, "_normalize_sensory_pingpong_source_prompt_map") else dict(sensory_pingpong_source_prompts or {})
                update_runtime_config("sensory_pingpong_source_prompts", prompt_map)
                self._refresh_sensory_feedback_source_tabs()
            saved_model_name = session.get("model_name")
            if saved_model_name:
                QtCore.QTimer.singleShot(400, lambda wanted=str(saved_model_name or ""): self._apply_saved_model_name(wanted))
            musetalk_avatar_pack_id = session.get("musetalk_avatar_pack_id")
            if musetalk_avatar_pack_id == "__standalone__":
                musetalk_avatar_pack_id = None
            widget = self._live_widget_attr("musetalk_avatar_pack_combo")
            if musetalk_avatar_pack_id is not None and widget is not None:
                self.refresh_musetalk_avatar_pack_list(selected_pack_id=musetalk_avatar_pack_id)
                widget = self._live_widget_attr("musetalk_avatar_pack_combo")
                if widget is not None:
                    for index in range(widget.count()):
                        if str(widget.itemData(index) or "") == str(musetalk_avatar_pack_id or ""):
                            widget.setCurrentIndex(index)
                            break
                    self.on_musetalk_avatar_pack_change(widget.currentText())
            emotional_instructions = session.get("emotional_instructions")
            if emotional_instructions is not None and hasattr(self, "emotional_text"):
                self.emotional_text.setPlainText(str(emotional_instructions or ""))
                update_runtime_config("emotional_instructions", self.emotional_text.toPlainText().strip())
            system_prompt = session.get("system_prompt")
            if system_prompt is not None and hasattr(self, "system_prompt_text"):
                self.system_prompt_text.setPlainText(str(system_prompt or ""))
                update_runtime_config("system_prompt", self.system_prompt_text.toPlainText().strip())
            for key in ("temperature", "top_p", "top_k", "repeat_penalty", "min_p"):
                if key in session and key in getattr(self, "brain_sliders", {}):
                    self.brain_sliders[key].set_value(session[key])
                    self.update_brain_value(key, session[key], key == "top_k")
            chunking = session.get("chunking")
            if isinstance(chunking, dict):
                for key, value in chunking.items():
                    if key in self.chunking_sliders:
                        self.chunking_sliders[key].set_value(value)
                        update_runtime_config(key, value)
            dry_run_target = session.get("dry_run_target_samples")
            if dry_run_target is not None:
                self.dry_run_target_spin.setValue(max(0, min(12, int(dry_run_target))))
            dry_run_auto_replies = session.get("dry_run_auto_replies")
            if dry_run_auto_replies is not None:
                self.dry_run_auto_replies_checkbox.setChecked(bool(dry_run_auto_replies))
            body = session.get("last_body")
            body_combo = self._live_widget_attr("body_combo")
            if body and body_combo is not None:
                index = body_combo.findText(body)
                if index >= 0:
                    body_combo.setCurrentIndex(index)
                    self.load_body_config_from_combo()
            if self._addon_manager is not None:
                self._addon_manager.import_session_state(session)
                self._refresh_addon_group_tabs()
            live_sync_checkbox = self._live_widget_attr("live_sync_checkbox")
            if live_sync_checkbox is not None:
                live_sync_checkbox.setChecked(bool(session.get("live_sync", False)))
            splitter_sizes = session.get("main_splitter_sizes")
            if isinstance(splitter_sizes, list) and len(splitter_sizes) == 2 and hasattr(self, "main_splitter"):
                try:
                    self.main_splitter.setSizes([max(220, int(splitter_sizes[0])), max(320, int(splitter_sizes[1]))])
                except Exception:
                    pass
            window_state = session.get("window_state")
            if window_state:
                try:
                    self.restoreState(QtCore.QByteArray.fromBase64(window_state.encode("ascii")))
                except Exception:
                    pass
            right_dock_state = session.get("right_dock_state")
            if right_dock_state and hasattr(self, "right_dock_host"):
                try:
                    self.right_dock_host.restoreState(QtCore.QByteArray.fromBase64(right_dock_state.encode("ascii")))
                except Exception:
                    pass
            self._pinned_floating_dock_names = {
                str(item or "").strip()
                for item in list(session.get("pinned_floating_docks", []) or [])
                if str(item or "").strip()
            }
            self._always_on_top_floating_dock_names = {
                str(item or "").strip()
                for item in list(session.get("always_on_top_floating_docks", []) or [])
                if str(item or "").strip()
            }
            self._apply_legacy_dock_title_widgets()
            suppress_aux_docks = bool(getattr(self, "_suppress_restored_aux_docks", False))
            if bool(session.get("preview_visible", False)) and not suppress_aux_docks:
                self.preview_dock.show()
            else:
                self.preview_dock.hide()
            if (
                bool(session.get("visual_reply_visible", False))
                and not suppress_aux_docks
                and self._visual_reply_addon_enabled()
            ):
                self.visual_reply_dock.show()
            else:
                self.visual_reply_dock.hide()
            performance_guidance_visible = bool(session.get("performance_guidance_visible", False))
            if hasattr(self, "performance_guidance_toggle"):
                self.performance_guidance_toggle.setChecked(performance_guidance_visible)
                self._toggle_performance_guidance(performance_guidance_visible)
            self._refresh_hotkey_shortcuts()
            self._refresh_hotkey_labels()
            self._apply_disabled_addon_surfaces()
            self._update_restart_sensitive_controls()
            self.refresh_dry_run_status()
            QtCore.QTimer.singleShot(0, self._ensure_window_on_screen)
        finally:
            self._suspend_session_save = previous_suspend
        self.save_session()
        QtCore.QTimer.singleShot(700, self._finalize_session_restore_dirty_state)

