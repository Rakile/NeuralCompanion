"""Grouped shell-preview services extracted from shell_services.py."""

import json
from collections import OrderedDict
from pathlib import Path


def configure_shell_services_settings_dependencies(namespace):
    globals().update(dict(namespace or {}))


class _UiShellChatContextService:
    """Shell-safe chat context facade.

    File/session operations are intentionally not performed in the Designer shell.
    """

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def snapshot(self):
        return {
            "last_action": self._last_action,
            "shell_mode": True,
            "file_operations_available": False,
            "message": "Chat context file operations are deferred in shell preview.",
            "source": "ui_shell",
        }

    def save_chat_context(self):
        self._last_action = "save_chat_context"
        return self.snapshot()

    def save_chat_context_as(self):
        self._last_action = "save_chat_context_as"
        return self.snapshot()

    def load_chat_context(self):
        self._last_action = "load_chat_context"
        return self.snapshot()

    def quick_save_chat_context(self):
        self._last_action = "quick_save_chat_context"
        return self.snapshot()

    def quick_load_chat_context(self):
        self._last_action = "quick_load_chat_context"
        return self.snapshot()

    def reset_chat_memory(self):
        self._last_action = "reset_chat_memory"
        return self.snapshot()


class _UiShellInputSettingsService:
    """Shell-safe input/session settings facade for future `main.ui` runtime wiring."""

    def __init__(self, window):
        self._window = window

    def _combo(self, name: str):
        return _ui_shell_find_object(self._window, str(name))

    def _spin(self, name: str):
        return _ui_shell_find_object(self._window, str(name))

    def _checkbox(self, name: str):
        return _ui_shell_find_object(self._window, str(name))

    def _combo_text(self, name: str, default: str = "") -> str:
        widget = self._combo(name)
        if widget is not None and hasattr(widget, "currentText"):
            try:
                text = str(widget.currentText() or "").strip()
                if text:
                    return text
            except Exception:
                pass
        return str(default or "").strip()

    def _combo_items(self, name: str) -> list[str]:
        widget = self._combo(name)
        if widget is None or not hasattr(widget, "count"):
            return []
        items = []
        try:
            for index in range(widget.count()):
                text = str(widget.itemText(index) or "").strip()
                if text:
                    items.append(text)
        except Exception:
            return []
        return items

    def _spin_value(self, name: str, default):
        widget = self._spin(name)
        if widget is not None and hasattr(widget, "value"):
            try:
                return widget.value()
            except Exception:
                pass
        return default

    def _checked(self, name: str, default: bool = False) -> bool:
        widget = self._checkbox(name)
        if widget is not None and hasattr(widget, "isChecked"):
            try:
                return bool(widget.isChecked())
            except Exception:
                pass
        return bool(default)

    def _set_combo_text(self, name: str, value) -> None:
        widget = self._combo(name)
        if widget is None:
            return
        _ui_shell_combo_select_label(widget, value)

    def _set_spin_value(self, name: str, value) -> None:
        widget = self._spin(name)
        if widget is None:
            return
        if isinstance(value, float):
            _ui_shell_set_double_value(widget, value)
        else:
            _ui_shell_set_spin_value(widget, value)

    def _set_checked(self, name: str, value) -> None:
        widget = self._checkbox(name)
        if widget is None:
            return
        _ui_shell_set_checked(widget, value)

    def snapshot(self):
        session = dict(_read_ui_shell_session_snapshot() or {})
        audio_devices = _ui_shell_audio_device_labels()
        return {
            "audio_input_device": self._combo_text("audio_input_device_combo", session.get("audio_input_device", "Default Input")),
            "audio_output_device": self._combo_text("audio_output_device_combo", session.get("audio_output_device", "Default Output")),
            "audio_input_options": list(audio_devices.get("inputs") or ["Default Input"]),
            "audio_output_options": list(audio_devices.get("outputs") or ["Default Output"]),
            "input_mode": self._combo_text("input_mode_combo", session.get("input_mode", "Voice Activation")),
            "input_role": self._combo_text("input_role_combo", session.get("input_message_role", "User Message")),
            "stream_mode": self._combo_text("stream_mode_combo", session.get("stream_mode", "Off")),
            "allow_proactive_replies": self._checked("allow_proactive_checkbox", session.get("allow_proactive_replies", False)),
            "require_first_user_before_proactive": self._checked("require_first_user_checkbox", session.get("require_first_user_before_proactive", False)),
            "listen_idle_window_seconds": float(self._spin_value("listen_idle_window_spin", session.get("listen_idle_window_seconds", 5.0))),
            "proactive_delay_seconds": float(self._spin_value("proactive_delay_spin", session.get("proactive_delay_seconds", 10.0))),
            "chat_context_window_messages": int(self._spin_value("chat_context_window_spin", session.get("chat_context_window_messages", 20))),
            "stored_chat_history_limit": int(self._spin_value("stored_chat_history_limit_spin", session.get("stored_chat_history_limit", 0))),
            "chat_context_overflow_policy": self._combo_text("chat_overflow_policy_combo", "Rolling Window"),
            "limit_response_length": self._checked("limit_response_checkbox", session.get("limit_response_length", False)),
            "max_response_tokens": int(self._spin_value("max_response_tokens_spin", session.get("max_response_tokens", 600))),
            "shell_mode": True,
            "message": "Input/session settings are shell-local only.",
            "source": "ui_shell",
        }

    def apply(self, updates: dict | None = None, **kwargs):
        payload = dict(updates or {})
        payload.update(kwargs)
        if "audio_input_device" in payload:
            self._set_combo_text("audio_input_device_combo", payload.get("audio_input_device"))
        if "audio_output_device" in payload:
            self._set_combo_text("audio_output_device_combo", payload.get("audio_output_device"))
        if "input_mode" in payload:
            self._set_combo_text("input_mode_combo", payload.get("input_mode"))
        if "input_role" in payload:
            value = payload.get("input_role")
            self._set_combo_text("input_role_combo", value)
        if "stream_mode" in payload:
            value = payload.get("stream_mode")
            label = value if isinstance(value, str) else ("On" if bool(value) else "Off")
            self._set_combo_text("stream_mode_combo", label)
        if "allow_proactive_replies" in payload:
            self._set_checked("allow_proactive_checkbox", payload.get("allow_proactive_replies"))
        if "require_first_user_before_proactive" in payload:
            self._set_checked("require_first_user_checkbox", payload.get("require_first_user_before_proactive"))
        if "listen_idle_window_seconds" in payload:
            self._set_spin_value("listen_idle_window_spin", float(payload.get("listen_idle_window_seconds") or 5.0))
        if "proactive_delay_seconds" in payload:
            self._set_spin_value("proactive_delay_spin", float(payload.get("proactive_delay_seconds") or 10.0))
        if "chat_context_window_messages" in payload:
            self._set_spin_value("chat_context_window_spin", int(payload.get("chat_context_window_messages") or 20))
        if "stored_chat_history_limit" in payload:
            self._set_spin_value("stored_chat_history_limit_spin", int(payload.get("stored_chat_history_limit") or 0))
        if "chat_context_overflow_policy" in payload:
            self._set_combo_text("chat_overflow_policy_combo", payload.get("chat_context_overflow_policy"))
        if "limit_response_length" in payload:
            self._set_checked("limit_response_checkbox", payload.get("limit_response_length"))
        if "max_response_tokens" in payload:
            self._set_spin_value("max_response_tokens_spin", int(payload.get("max_response_tokens") or 600))
        return self.snapshot()


class _UiShellPerformanceProfileService:
    """Shell-safe performance-profile facade backed by local JSON files only."""

    def __init__(self, window):
        self._window = window

    def snapshot(self):
        selected_chunking = _ui_shell_profile_selected_name(self._window, "chunking")
        selected_performance = _ui_shell_profile_selected_name(self._window, "dry_run")
        profiles = _ui_shell_list_performance_profiles()
        return {
            "profiles": profiles,
            "profile_names": [str(item.get("name") or "") for item in profiles if str(item.get("name") or "").strip()],
            "selected_chunking_profile": selected_chunking,
            "selected_performance_profile": selected_performance,
            "current_chunking": _ui_shell_current_chunking_values(self._window),
            "shell_mode": True,
            "load_available": bool(profiles),
            "refresh_available": True,
            "reset_available": True,
            "save_available": False,
            "delete_available": False,
            "message": "Performance profile refresh/load is shell-local only. Save/delete remains deferred.",
            "source": "ui_shell",
        }

    def refresh_profiles(self, preferred_name: str = ""):
        _ui_shell_refresh_performance_profile_combos(self._window, preferred_name=preferred_name)
        return self.snapshot()

    def load_profile(self, name: str = "", *, source: str = "dry_run"):
        result = _ui_shell_load_profile_preview(self._window, name=name, source=source)
        payload = self.snapshot()
        payload.update(result)
        return payload

    def reset_chunking_defaults(self):
        result = _ui_shell_reset_chunking_defaults(self._window)
        payload = self.snapshot()
        payload.update(result)
        return payload

    def save_profile(self, *args, **kwargs):
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "action": "save_profile",
            "message": "Saving performance profiles is deferred in shell preview.",
        })
        return payload

    def delete_profile(self, *args, **kwargs):
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "action": "delete_profile",
            "message": "Deleting performance profiles is deferred in shell preview.",
        })
        return payload


class _UiShellDryRunService:
    """Shell-safe Dry Run facade that never starts profiling sessions."""

    def __init__(self, window):
        self._window = window
        self._preview_state = "idle"
        self._last_action = ""

    def snapshot(self):
        session = dict(_read_ui_shell_session_snapshot() or {})
        latest = _ui_shell_latest_performance_profile_payload()
        recommendation = dict((latest.get("recommendation") or {}).get("settings") or {})
        target_widget = _ui_shell_find_object(self._window, "dry_run_target_spin")
        auto_widget = _ui_shell_find_object(self._window, "dry_run_auto_replies_checkbox")
        target = int(target_widget.value()) if target_widget is not None and hasattr(target_widget, "value") else int(session.get("dry_run_target_samples", 0) or 0)
        auto_replies = bool(auto_widget.isChecked()) if auto_widget is not None and hasattr(auto_widget, "isChecked") else bool(session.get("dry_run_auto_replies", True))
        return {
            "state": self._preview_state,
            "last_action": self._last_action,
            "target_samples": target,
            "auto_replies": auto_replies,
            "latest_profile_name": str(latest.get("saved_name") or latest.get("display_name") or "").strip(),
            "has_recommendation": bool(recommendation),
            "recommendation_settings": recommendation,
            "summary_text": _ui_shell_dry_run_summary_text(latest, target_samples=target, auto_replies=auto_replies, preview_state=self._preview_state),
            "status_text": _ui_shell_dry_run_status_text(latest, target_samples=target, auto_replies=auto_replies, preview_state=self._preview_state),
            "shell_mode": True,
            "message": "Dry Run actions are shell-safe previews only.",
            "source": "ui_shell",
        }

    def refresh_preview(self):
        return self.snapshot()

    def start_session(self):
        self._preview_state = "armed"
        self._last_action = "start_session"
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Dry Run session start is deferred in shell preview.",
        })
        return payload

    def stop_session(self):
        self._preview_state = "idle"
        self._last_action = "stop_session"
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Dry Run session stop is deferred in shell preview.",
        })
        return payload

    def apply_recommendation(self):
        self._last_action = "apply_recommendation"
        latest = _ui_shell_latest_performance_profile_payload()
        recommendation = dict((latest.get("recommendation") or {}).get("settings") or {})
        applied = []
        deferred = []
        if recommendation:
            applied, deferred = _ui_shell_apply_profile_settings(self._window, recommendation)
            _ui_shell_refresh_host_core_status(self._window)
        payload = self.snapshot()
        payload.update({
            "accepted": bool(recommendation),
            "applied": bool(recommendation),
            "applied_keys": applied,
            "deferred_keys": deferred,
            "message": "Dry Run recommendation applied to the shell-visible subset only." if recommendation else "No saved Dry Run recommendation is available in shell preview.",
        })
        return payload


class _UiShellPersonaAvatarService:
    """Shell-safe persona/body/VaM facade for future main.ui runtime wiring."""

    def __init__(self, window):
        self._window = window

    def snapshot(self):
        return {
            "voice_file": _ui_shell_current_voice_file(self._window),
            "voice_options": _ui_shell_voice_options(self._window),
            "emotional_instructions": _ui_shell_plain_text_value(self._window, "emotional_text"),
            "system_prompt": _ui_shell_plain_text_value(self._window, "system_prompt_text"),
            "body_presets": _ui_shell_list_body_configs(),
            "selected_body": _ui_shell_selected_body_name(self._window),
            "emotion": _ui_shell_combo_text_value(self._window, "emotion_combo", "Neutral"),
            "live_sync": _ui_shell_checkbox_value(self._window, "live_sync_checkbox", False),
            "pose_values": _ui_shell_current_body_pose_values(self._window),
            "vam_settings": _ui_shell_current_vam_settings(self._window),
            "shell_mode": True,
            "message": "Persona/body/VaM controls are shell-local previews only.",
            "source": "ui_shell",
        }

    def export_vam_settings(self):
        return dict(self.snapshot().get("vam_settings", {}) or {})

    def import_vam_settings(self, payload):
        data = dict(payload or {})
        if not data:
            return None
        root = str(data.get("vam_root") or data.get("vam_bridge_root") or UI_SHELL_DEFAULT_LOCAL_VAM_ROOT)
        normalized_root = _ui_shell_normalize_vam_root(root)
        fields = {
            "vam_root_edit": normalized_root,
            "vam_bridge_root_edit": _ui_shell_derive_vam_bridge_root(normalized_root),
            "vam_target_atom_uid_edit": str(data.get("vam_target_atom_uid", "Person") or "Person"),
            "vam_target_storable_id_edit": str(data.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge"),
            "vam_vmc_host_edit": str(data.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1"),
        }
        for name, value in fields.items():
            widget = _ui_shell_find_object(self._window, name)
            if widget is not None and hasattr(widget, "setText"):
                widget.setText(value)
        port_spin = _ui_shell_find_object(self._window, "vam_vmc_port_spin")
        if port_spin is not None:
            _ui_shell_set_spin_value(port_spin, int(data.get("vam_vmc_port", 39539) or 39539))
        for name, default in (
            ("vam_vmc_enabled_checkbox", True),
            ("vam_bridge_enabled_checkbox", True),
            ("vam_play_audio_in_vam_checkbox", False),
            ("vam_timeline_auto_resume_checkbox", True),
        ):
            widget = _ui_shell_find_object(self._window, name)
            if widget is not None:
                _ui_shell_set_checked(widget, bool(data.get(name.replace("_checkbox", ""), default)))
        return None

    def refresh_body_list(self, preferred_name: str = ""):
        _ui_shell_refresh_body_combo(self._window, preferred_name=preferred_name)
        return self.snapshot()

    def load_body(self, name: str = ""):
        result = _ui_shell_load_body_preview(self._window, name=name)
        payload = self.snapshot()
        payload.update(result)
        return payload

    def apply_persona(self):
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "applied": True,
            "message": "Persona/body/VaM preview applied locally in shell mode only.",
        })
        return payload

    def save_body(self):
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "action": "save_body",
            "message": "Body save is deferred in shell preview.",
        })
        return payload

    def delete_body(self):
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "action": "delete_body",
            "message": "Body delete is deferred in shell preview.",
        })
        return payload

    def launch_vam(self, target: str = "desktop"):
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "action": f"launch_vam:{str(target or 'desktop').strip().lower()}",
            "message": "VaM launch is deferred in shell preview.",
        })
        return payload

    def open_external_avatar_view(self, mode: str = "vseeface"):
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "action": f"external_avatar_view:{str(mode or 'vseeface').strip().lower()}",
            "message": "External avatar focus is deferred in shell preview.",
        })
        return payload
