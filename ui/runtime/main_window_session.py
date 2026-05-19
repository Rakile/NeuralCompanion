"""Session persistence helpers for the runtime-backed main window."""

import base64
import json
import os
from collections import OrderedDict
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from addons.visual_reply.session_schema import group_visual_reply_session, with_flat_visual_reply_settings
from core.chat_runtime_session_schema import group_chat_runtime_session, with_flat_chat_runtime_settings
from core.chunking_session_schema import group_chunking_session, with_flat_chunking_settings
from core.dry_run_session_schema import group_dry_run_session, with_flat_dry_run_settings
from core.musetalk_session_schema import group_musetalk_session, with_flat_musetalk_settings
from core.persona_session_schema import group_persona_session, with_flat_persona_settings
from core.runtime_controls_session_schema import group_runtime_controls_session, with_flat_runtime_controls_settings
from core.sensory_session_schema import group_sensory_session, with_flat_sensory_settings
from core.tts_session_schema import group_tts_runtime_session, with_flat_tts_runtime_settings
from core.ui_session_schema import group_ui_session, with_flat_ui_settings
from core.vam_session_schema import group_vam_session, with_flat_vam_settings
from ui.runtime import engine_access as engine
from ui.runtime.engine_access import RUNTIME_CONFIG, update_runtime_config
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES, UI_SHELL_MUSE_VRAM_MODE_LABELS

SESSION_PATH = Path("qt_session.json")
QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_CHUNKING_VALUES = UI_SHELL_DEFAULT_CHUNKING_VALUES
DEFAULT_MAX_RESPONSE_TOKENS = 600
MUSE_VRAM_MODE_LABELS = OrderedDict(UI_SHELL_MUSE_VRAM_MODE_LABELS)


class MainWindowSessionMixin:
    def _addon_session_surface_specs(self):
        manager = getattr(self, "_addon_manager", None)
        if manager is None:
            return []
        try:
            return [
                dict(spec)
                for spec in list(manager.get_ui_disabled_surface_specs() or [])
                if str((spec or {}).get("session_visible_key") or "").strip()
            ]
        except Exception:
            return []

    def _save_addon_session_surface_visibility(self, session):
        for spec in self._addon_session_surface_specs():
            key = str(spec.get("session_visible_key") or "").strip()
            dock_name = str(spec.get("dock_name") or "").strip()
            if not key or not dock_name:
                continue
            dock = getattr(self, dock_name, None)
            enabled = True
            addon_id = str(spec.get("addon_id") or "").strip()
            checker = getattr(self, "_addon_surface_runtime_available", None) or getattr(self, "_addon_effectively_enabled", None)
            if callable(checker) and addon_id:
                try:
                    enabled = bool(checker(addon_id))
                except Exception:
                    enabled = True
            try:
                session[key] = bool(enabled and dock is not None and dock.isVisible())
            except Exception:
                session[key] = False

    def _restore_addon_session_surface_visibility(self, session, *, suppress_aux_docks=False):
        for spec in self._addon_session_surface_specs():
            key = str(spec.get("session_visible_key") or "").strip()
            dock_name = str(spec.get("dock_name") or "").strip()
            if not key or not dock_name:
                continue
            dock = getattr(self, dock_name, None)
            if dock is None:
                continue
            addon_id = str(spec.get("addon_id") or "").strip()
            enabled = True
            checker = getattr(self, "_addon_surface_runtime_available", None) or getattr(self, "_addon_effectively_enabled", None)
            if callable(checker) and addon_id:
                try:
                    enabled = bool(checker(addon_id))
                except Exception:
                    enabled = True
            try:
                if bool(session.get(key, False)) and not suppress_aux_docks and enabled:
                    dock.show()
                else:
                    dock.hide()
            except Exception:
                pass

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
                    previous_session = with_flat_ui_settings(previous_session)
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
            "hotkeys": dict(engine.get_hotkey_settings()),
            "stream_mode": self.stream_mode_combo.currentText(),
            "stt_backend": self._current_stt_backend_value() if hasattr(self, "stt_backend_combo") else str(RUNTIME_CONFIG.get("stt_backend", "none") or "none"),
            "stt_model_size": self._current_stt_model_value() if hasattr(self, "stt_model_combo") else str(RUNTIME_CONFIG.get("stt_model_size", "tiny.en") or "tiny.en"),
            "stt_language": self._current_stt_language_value() if hasattr(self, "stt_language_combo") else str(RUNTIME_CONFIG.get("stt_language", "en") or "en"),
            "tts_backend": self._current_tts_backend_value(),
            "chat_provider": self._current_chat_provider_value(),
            "chat_provider_settings": dict(RUNTIME_CONFIG.get("chat_provider_settings", {}) or {}),
            "chat_provider_generation_settings": dict(RUNTIME_CONFIG.get("chat_provider_generation_settings", {}) or {}),
            "chat_font_size": int(self.chat_font_size_combo.currentData() or 12) if hasattr(self, "chat_font_size_combo") else 12,
            "chat_runtime_expanded": self.chat_runtime_section.isExpanded() if hasattr(self, "chat_runtime_section") else True,
            "stt_runtime_expanded": self.stt_runtime_section.isExpanded() if hasattr(self, "stt_runtime_section") else True,
            "tts_runtime_expanded": self.tts_runtime_section.isExpanded() if hasattr(self, "tts_runtime_section") else True,
            "model_name": self.model_combo.currentText() if hasattr(self, "model_combo") else str(RUNTIME_CONFIG.get("model_name", "") or ""),
            "model_requires_vision": self.model_requires_vision_checkbox.isChecked() if hasattr(self, "model_requires_vision_checkbox") else False,
            "model_supports_images": self._current_model_supports_images_value(self.model_combo.currentText()) if hasattr(self, "model_combo") else RUNTIME_CONFIG.get("model_supports_images", None),
            "allow_proactive_replies": self.allow_proactive_checkbox.isChecked() if hasattr(self, "allow_proactive_checkbox") else False,
            "require_first_user_before_proactive": self.require_first_user_checkbox.isChecked() if hasattr(self, "require_first_user_checkbox") else False,
            "listen_idle_window_seconds": float(self.listen_idle_window_spin.value()) if hasattr(self, "listen_idle_window_spin") else 5.0,
            "proactive_delay_seconds": float(self.proactive_delay_spin.value()) if hasattr(self, "proactive_delay_spin") else 10.0,
            "chat_context_window_messages": int(self.chat_context_window_spin.value()) if hasattr(self, "chat_context_window_spin") else 20,
            "stored_chat_history_limit": int(self.stored_chat_history_limit_spin.value()) if hasattr(self, "stored_chat_history_limit_spin") else 0,
            "chat_context_overflow_policy": self._chat_overflow_policy_value_from_label(self.chat_overflow_policy_combo.currentText()) if hasattr(self, "chat_overflow_policy_combo") else "rolling_window",
            "limit_response_length": self.limit_response_checkbox.isChecked() if hasattr(self, "limit_response_checkbox") else False,
            "max_response_tokens": int(self.max_response_tokens_spin.value()) if hasattr(self, "max_response_tokens_spin") else DEFAULT_MAX_RESPONSE_TOKENS,
            "sensory_feedback_source": self._sensory_feedback_source_value_from_label(self.sensory_feedback_source_combo.currentText()) if hasattr(self, "sensory_feedback_source_combo") else str(RUNTIME_CONFIG.get("sensory_feedback_source", "off") or "off"),
            "sensory_feedback_interval_seconds": float(self.sensory_feedback_interval_spin.value()) if hasattr(self, "sensory_feedback_interval_spin") else float(RUNTIME_CONFIG.get("sensory_feedback_interval_seconds", 7.0) or 7.0),
            "sensory_pingpong_enabled": bool(self.sensory_pingpong_checkbox.isChecked()) if hasattr(self, "sensory_pingpong_checkbox") else bool(RUNTIME_CONFIG.get("sensory_pingpong_enabled", False)),
            "sensory_allow_hidden_proactive_speech": bool(self.sensory_allow_hidden_proactive_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_proactive_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_proactive_speech", False)),
            "sensory_allow_hidden_visual_generation": bool(self.sensory_allow_hidden_visual_checkbox.isChecked()) if hasattr(self, "sensory_allow_hidden_visual_checkbox") else bool(RUNTIME_CONFIG.get("sensory_allow_hidden_visual_generation", False)),
            "sensory_pingpong_history_depth": int(self.sensory_pingpong_history_spin.value()) if hasattr(self, "sensory_pingpong_history_spin") else int(RUNTIME_CONFIG.get("sensory_pingpong_history_depth", 3) or 3),
            "sensory_pingpong_prompt": self.sensory_pingpong_prompt_text.toPlainText().strip() if hasattr(self, "sensory_pingpong_prompt_text") else str(RUNTIME_CONFIG.get("sensory_pingpong_prompt", getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")) or getattr(engine, "DEFAULT_SENSORY_PINGPONG_PROMPT", "")),
            "sensory_pingpong_source_prompts": self._current_sensory_pingpong_source_prompt_map() if hasattr(self, "_current_sensory_pingpong_source_prompt_map") else dict(RUNTIME_CONFIG.get("sensory_pingpong_source_prompts", {}) or {}),
            "sensory_provider_metadata_overrides": self._current_sensory_provider_metadata_override_map() if hasattr(self, "_current_sensory_provider_metadata_override_map") else dict(RUNTIME_CONFIG.get("sensory_provider_metadata_overrides", {}) or {}),
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
            "performance_guidance_visible": bool(hasattr(self, "guidance_box") and self.guidance_box.isVisible()),
            "window_state": base64.b64encode(self.saveState().data()).decode("ascii"),
            "right_dock_state": (
                base64.b64encode(self.right_dock_host.saveState().data()).decode("ascii")
                if hasattr(self, "right_dock_host")
                else ""
            ),
        }
        self._save_addon_session_surface_visibility(session)
        if isinstance(preserved_main_ui_real_layout, dict):
            session["main_ui_real_layout"] = preserved_main_ui_real_layout
        if self._addon_manager is not None:
            session.update(self._addon_manager.export_session_state())
        active_chat_provider = str(session.get("chat_provider") or "").strip().lower()
        if active_chat_provider:
            provider_settings = dict(session.get("chat_provider_settings", {}) or {})
            active_provider_settings = dict(provider_settings.get(active_chat_provider, {}) or {})
            active_provider_settings["model_name"] = session.get("model_name", "")
            active_provider_settings["model_requires_vision"] = bool(session.get("model_requires_vision", False))
            active_provider_settings["model_supports_images"] = bool(session.get("model_supports_images", False))
            active_provider_settings["model_supports_reasoning"] = bool(RUNTIME_CONFIG.get("model_supports_reasoning", False))
            active_provider_settings["model_supports_reasoning_toggle"] = bool(RUNTIME_CONFIG.get("model_supports_reasoning_toggle", False))
            provider_settings[active_chat_provider] = active_provider_settings
            session["chat_provider_settings"] = provider_settings
        session = group_persona_session(session)
        session = group_runtime_controls_session(session)
        session = group_dry_run_session(session)
        session = group_chunking_session(session)
        session = group_chat_runtime_session(session)
        session = group_sensory_session(session)
        session = group_musetalk_session(session)
        session = group_tts_runtime_session(session)
        session = group_visual_reply_session(session)
        session = group_vam_session(session)
        session = group_ui_session(session)
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
        session = with_flat_chat_runtime_settings(
            with_flat_sensory_settings(
                with_flat_musetalk_settings(
                    with_flat_tts_runtime_settings(
                        with_flat_visual_reply_settings(
                            with_flat_persona_settings(
                                with_flat_runtime_controls_settings(
                                    with_flat_dry_run_settings(
                                        with_flat_chunking_settings(
                                            with_flat_ui_settings(with_flat_vam_settings(session))
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )
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
                mode_text = self._input_mode_label_from_value(input_mode)
                index = self.input_mode_combo.findText(mode_text)
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
            hotkeys = session.get("hotkeys")
            if hotkeys is not None:
                engine.set_hotkey_settings(hotkeys)
            else:
                legacy_hotkeys = {}
                push_to_talk_hotkey = session.get("push_to_talk_hotkey")
                if push_to_talk_hotkey is not None:
                    legacy_hotkeys["push_to_talk"] = push_to_talk_hotkey
                manual_action_hotkeys = session.get("manual_action_hotkeys")
                if manual_action_hotkeys is not None:
                    legacy_hotkeys["manual_actions"] = manual_action_hotkeys
                ui_action_hotkeys = session.get("ui_action_hotkeys")
                if ui_action_hotkeys is not None:
                    legacy_hotkeys["ui_actions"] = ui_action_hotkeys
                if legacy_hotkeys:
                    engine.set_hotkey_settings(legacy_hotkeys)
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
            stt_backend = session.get("stt_backend")
            if stt_backend is not None and hasattr(self, "stt_backend_combo"):
                self._populate_stt_backend_combo(selected_value=stt_backend)
                index = self.stt_backend_combo.findData(str(stt_backend or "").strip().lower())
                if index >= 0:
                    self.stt_backend_combo.setCurrentIndex(index)
                self.on_stt_backend_change(self.stt_backend_combo.currentText())
            stt_model_size = session.get("stt_model_size")
            if stt_model_size is not None and hasattr(self, "stt_model_combo"):
                self._populate_stt_model_combo(selected_value=stt_model_size)
                index = self.stt_model_combo.findData(str(stt_model_size or "").strip())
                if index >= 0:
                    self.stt_model_combo.setCurrentIndex(index)
                self.on_stt_model_change(self.stt_model_combo.currentText())
            stt_language = session.get("stt_language")
            if stt_language is not None and hasattr(self, "stt_language_combo"):
                self._populate_stt_language_combo(selected_value=stt_language)
                self.on_stt_language_change(self.stt_language_combo.currentText())
            tts_backend = session.get("tts_backend")
            if tts_backend:
                desired_backend = str(tts_backend or "").strip().lower()
                self._populate_tts_backend_combo(selected_value=desired_backend)
                index = self.tts_backend_combo.findData(desired_backend)
                if index >= 0:
                    self.tts_backend_combo.setCurrentIndex(index)
                self.on_tts_backend_change(self.tts_backend_combo.currentText())
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
            if "stt_runtime_expanded" in session and hasattr(self, "stt_runtime_section"):
                self.stt_runtime_section.setExpanded(bool(session.get("stt_runtime_expanded", True)))
            if "tts_runtime_expanded" in session and hasattr(self, "tts_runtime_section"):
                self.tts_runtime_section.setExpanded(bool(session.get("tts_runtime_expanded", True)))
            saved_model_name = str(session.get("model_name") or "").strip()
            if saved_model_name:
                self._pending_restored_model_name = saved_model_name
                update_runtime_config("model_name", saved_model_name)
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
            sensory_provider_metadata_overrides = session.get("sensory_provider_metadata_overrides")
            if sensory_provider_metadata_overrides is not None:
                metadata_map = self._normalize_sensory_provider_metadata_override_map(sensory_provider_metadata_overrides) if hasattr(self, "_normalize_sensory_provider_metadata_override_map") else dict(sensory_provider_metadata_overrides or {})
                update_runtime_config("sensory_provider_metadata_overrides", metadata_map)
                self._refresh_sensory_feedback_source_tabs()
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
            preview_dock = getattr(self, "preview_dock", None)
            if preview_dock is not None:
                if bool(session.get("preview_visible", False)) and not suppress_aux_docks:
                    preview_dock.show()
                else:
                    preview_dock.hide()
            self._restore_addon_session_surface_visibility(session, suppress_aux_docks=suppress_aux_docks)
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
