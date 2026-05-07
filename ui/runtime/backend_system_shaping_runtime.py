from PySide6 import QtCore, QtWidgets

from addons.musetalk_avatar import real_ui_bridge as musetalk_real_ui_bridge
from ui.runtime.shell_session_config import _ui_shell_combo_select_label, _ui_shell_combo_set_items
from ui.runtime.shell_status_layout import _ui_shell_audio_device_labels
from ui.shell_specs import UI_SHELL_DEFAULT_CHUNKING_VALUES
from ui.widgets.basic import CollapsibleSection, ContextTokenStepper, DecimalStepper, NoWheelComboBox, NoWheelSpinBox, NoWheelTabWidget


QT_MUSETALK_LOOP_FADE_MS = 180
DEFAULT_LOCAL_VAM_ROOT = ""


def _engine():
    import engine

    return engine


def _update_runtime_config(key, value):
    from engine import update_runtime_config

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
        mode = "push_to_talk" if choice == "Push-to-Talk" else "voice_activation"
        _update_runtime_config("input_mode", mode)
        self._refresh_hotkey_labels()
        self._update_push_to_talk_button()
        self.save_session()

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
        _update_runtime_config("stream_mode", enabled)
        current_backend = self._current_tts_backend_value()
        if current_backend in {"chatterbox", "pockettts"}:
            desired_backend = "pockettts" if enabled else "chatterbox"
            if current_backend != desired_backend and hasattr(self, "tts_backend_combo"):
                self.tts_backend_combo.setCurrentIndex(max(self.tts_backend_combo.findData(desired_backend), 0))
        self._advisor_context_manual_override = False
        self.emit_tutorial_event("ui_changed", {"field": "stream_mode", "value": choice})
        self.save_session()

    def on_musetalk_vram_mode_change(self, choice):
        musetalk_real_ui_bridge.apply_vram_mode_change(self, choice)

    def on_musetalk_loop_fade_changed(self, value):
        musetalk_real_ui_bridge.apply_loop_fade_change(self, value)

    def on_musetalk_use_frame_cache_changed(self, checked):
        musetalk_real_ui_bridge.apply_frame_cache_change(self, checked)

    def refresh_musetalk_avatar_pack_list(self, selected_pack_id=None):
        musetalk_real_ui_bridge.refresh_avatar_pack_list(self, selected_pack_id=selected_pack_id)

    def on_musetalk_avatar_pack_change(self, _choice):
        musetalk_real_ui_bridge.apply_avatar_pack_change(self, _choice)
