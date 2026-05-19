from PySide6 import QtCore, QtWidgets

from ui.runtime.shell_session_config import _ui_shell_combo_select_label, _ui_shell_combo_set_items
from ui.runtime.shell_status_layout import _ui_shell_audio_device_labels
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES
from ui.widgets.basic import CollapsibleSection, ContextTokenStepper, DecimalStepper, NoWheelComboBox, NoWheelSpinBox, NoWheelTabWidget


QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_LOCAL_VAM_ROOT = ""


from ui.runtime.engine_access import engine_module as _engine


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


def _default_chat_provider_id():
    from core import chat_providers

    return chat_providers.DEFAULT_PROVIDER_ID


class BackendSystemShapingPanelMixin:
    """Build the backend System Shaping and Workspace panels."""

class BackendSystemShapingRuntimeMixin:
    def update_pose_value(self, key, value):
        engine = _engine()
        value = round(float(value), 2)
        target = engine.EDIT_EMOTION if engine.FORCE_EDIT_MODE else "neutral"
        if target in engine.AVATAR_PROFILE:
            engine.AVATAR_PROFILE[target][key] = value
        engine.CURRENT_BODY_STATE[key] = value

    def update_brain_value(self, key, value, is_int):
        _update_runtime_config(key, int(value) if is_int else round(float(value), 2))

    def on_limit_response_length_changed(self, checked):
        checked = bool(checked)
        _update_runtime_config("limit_response_length", checked)
        if hasattr(self, "max_response_tokens_spin"):
            self.max_response_tokens_spin.setEnabled(checked)
        self.save_session()

    def on_max_response_tokens_changed(self, value):
        _update_runtime_config("max_response_tokens", int(value))
        self.save_session()

    def update_chunking_value(self, key, value, is_int):
        _update_runtime_config(key, int(value) if is_int else round(float(value), 2))
        self.save_session()

    def reset_chunking_defaults(self):
        for key, value in UI_SHELL_DEFAULT_CHUNKING_VALUES.items():
            if key in self.chunking_sliders:
                self.chunking_sliders[key].set_value(value)
            _update_runtime_config(key, value)
        self.save_session()
        print("[QtGUI] Chunking settings reset to defaults.")

    def on_input_mode_change(self, choice):
        mode = self._input_mode_value_from_label(choice)
        _update_runtime_config("input_mode", mode)
        if mode == "text_only":
            self._set_stt_backend_none_for_text_only()
        else:
            restore_stt = getattr(self, "_restore_stt_backend_for_voice_input", None)
            if callable(restore_stt):
                restore_stt()
        self._refresh_hotkey_labels()
        self._update_push_to_talk_button()
        self.save_session()

    def _input_mode_value_from_label(self, label):
        text = str(label or "").strip().lower().replace("_", " ")
        if text in {"text only", "text-only"}:
            return "text_only"
        if text in {"push to talk", "push-to-talk"}:
            return "push_to_talk"
        return "voice_activation"

    def _input_mode_label_from_value(self, value):
        mode = str(value or "voice_activation").strip().lower().replace("-", "_")
        if mode in {"text_only", "text only"}:
            return "Text Only"
        if mode in {"push_to_talk", "push to talk"}:
            return "Push-to-Talk"
        return "Voice Activation"

    def _set_stt_backend_none_for_text_only(self):
        _update_runtime_config("stt_backend", "none")
        combo = getattr(self, "stt_backend_combo", None)
        if combo is not None and hasattr(combo, "findData"):
            try:
                index = combo.findData("none")
            except Exception:
                index = -1
            if index >= 0 and hasattr(combo, "setCurrentIndex"):
                blocked = combo.blockSignals(True)
                try:
                    combo.setCurrentIndex(index)
                finally:
                    combo.blockSignals(blocked)
        refresh = getattr(self, "_refresh_stt_runtime_summary", None)
        if callable(refresh):
            refresh()
        reload_stt = getattr(self, "_reload_stt_runtime_if_available", None)
        if callable(reload_stt):
            reload_stt()

    def on_input_role_change(self, choice):
        role = self._input_role_value_from_label(choice)
        _update_runtime_config("input_message_role", role)
        self.save_session()

    def _input_role_value_from_label(self, label):
        text = str(label or "").strip().lower()
        if text == "system message":
            return "system"
        if text == "assistant message":
            return "assistant"
        return "user"

    def _input_role_label_from_value(self, value):
        role = str(value or "user").strip().lower()
        if role == "system":
            return "System Message"
        if role == "assistant":
            return "Assistant Message"
        return "User Message"

    def on_stream_mode_change(self, choice):
        enabled = choice == "On"
        if bool(getattr(self, "thread", None) and self.thread.is_alive()):
            current_enabled = bool(getattr(_engine(), "RUNTIME_CONFIG", {}).get("stream_mode", False))
            expected_label = "On" if current_enabled else "Off"
            if str(choice or "") != expected_label and hasattr(self, "stream_mode_combo"):
                previous_blocked = self.stream_mode_combo.blockSignals(True)
                try:
                    self.stream_mode_combo.setCurrentText(expected_label)
                finally:
                    self.stream_mode_combo.blockSignals(previous_blocked)
            return
        _update_runtime_config("stream_mode", enabled)
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "stream_mode", "value": choice})
        self.save_session()

    def on_musetalk_vram_mode_change(self, choice):
        self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "ui.apply_vram_mode_change",
            {"backend": self, "choice": choice},
            default=None,
            provider_id="musetalk",
        )

    def on_musetalk_loop_fade_changed(self, value):
        self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "ui.apply_loop_fade_change",
            {"backend": self, "value": value},
            default=None,
            provider_id="musetalk",
        )

    def on_musetalk_use_frame_cache_changed(self, checked):
        self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "ui.apply_frame_cache_change",
            {"backend": self, "checked": checked},
            default=None,
            provider_id="musetalk",
        )

    def refresh_musetalk_avatar_pack_list(self, selected_pack_id=None):
        self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "ui.refresh_avatar_pack_list",
            {"backend": self, "selected_pack_id": selected_pack_id},
            default=None,
            provider_id="musetalk",
        )

    def on_musetalk_avatar_pack_change(self, _choice):
        self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "ui.apply_avatar_pack_change",
            {"backend": self, "choice": _choice},
            default=None,
            provider_id="musetalk",
        )
