"""Shell-preview service facades used by the Designer UI."""

import json
from collections import OrderedDict
from pathlib import Path


def configure_shell_service_dependencies(namespace):
    """Inject qt_app helper functions/constants used by these boundary services."""
    globals().update(dict(namespace or {}))

class _UiShellRuntimeStatusService:
    """Read-only shell runtime status facade for Designer-bound UI code."""

    def __init__(self, window):
        self._window = window
        self._running = False
        self._session_overrides = {}

    def set_running(self, running):
        self._running = bool(running)

    def set_session_overrides(self, **values):
        for key, value in values.items():
            if value is None:
                self._session_overrides.pop(str(key), None)
            else:
                self._session_overrides[str(key)] = value

    def snapshot(self):
        binding_summary = _ui_shell_binding_summary(self._window)
        session = dict(_read_ui_shell_session_snapshot() or {})
        session.update(dict(self._session_overrides or {}))
        return build_runtime_status_snapshot(
            session,
            running=self._running,
            engine_connected=False,
            shell_mode=True,
            lifecycle_state="shell_running_preview" if self._running else "shell_preview",
            source="ui_shell",
            metadata={
                "bindings_checked": int(binding_summary.get("checked", 0) or 0),
                "bindings_bound": int(binding_summary.get("bound", 0) or 0),
                "binding_issues": bool(binding_summary.get("missing") or binding_summary.get("mismatched")),
            },
        )

    def status_line(self):
        return self.snapshot().status_line()


class _UiShellModelRefreshService:
    """Shell-safe model refresh facade.

    The Designer shell can bind refresh controls through the same host-service
    name as the real app, but this implementation never calls provider handlers.
    """

    def __init__(self, window):
        self._window = window
        self._last_requested_provider = ""

    def snapshot(self, provider_id=None):
        session = dict(_read_ui_shell_session_snapshot() or {})
        provider = str(provider_id or session.get("chat_provider", "") or "").strip().lower()
        model_name = str(session.get("model_name", "") or "").strip()
        models = [model_name] if model_name else []
        return {
            "provider": provider,
            "selected_model": model_name,
            "models": models,
            "in_flight": False,
            "refresh_available": False,
            "deferred": True,
            "last_requested_provider": self._last_requested_provider,
            "message": "Live model refresh is deferred in shell preview.",
            "source": "ui_shell",
        }

    def refresh(self, provider_id=None, *, quiet=True, wait_for_reachable=False):
        self._last_requested_provider = str(provider_id or "").strip().lower()
        return self.snapshot(provider_id)


class _UiShellEngineLifecycleService:
    """Shell-local lifecycle facade that never starts runtime systems."""

    def __init__(self, window):
        self._window = window
        self._running = False

    def snapshot(self):
        status = _ui_shell_runtime_status_service(self._window)
        return {
            "running": bool(self._running),
            "shell_mode": True,
            "engine_connected": False,
            "runtime_status": status.snapshot().to_dict(),
            "message": "Engine lifecycle is shell-local only.",
            "source": "ui_shell",
        }

    def start_engine(self, *, offline_replay_only=False):
        self._running = True
        _ui_shell_runtime_status_service(self._window).set_running(True)
        return self.snapshot()

    def stop_engine(self):
        self._running = False
        _ui_shell_runtime_status_service(self._window).set_running(False)
        return self.snapshot()

    def reset_chat_memory(self):
        return {
            "running": bool(self._running),
            "shell_mode": True,
            "engine_connected": False,
            "message": "Shell-local chat reset only.",
            "source": "ui_shell",
        }

    def start(self, **kwargs):
        return self.start_engine(**kwargs)

    def stop(self):
        return self.stop_engine()

    def reset(self):
        return self.reset_chat_memory()


class _UiShellRuntimeControlService:
    """Shell-safe runtime controls facade for Operational View buttons."""

    SUPPORTED_ACTIONS = (
        "regenerate_response",
        "retry_user_input",
        "pause_speech",
        "skip_speech",
        "skip_user_reply",
    )

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def snapshot(self):
        return {
            "actions": list(self.SUPPORTED_ACTIONS),
            "last_action": self._last_action,
            "shell_mode": True,
            "runtime_connected": False,
            "message": "Runtime control actions are shell-local only.",
            "source": "ui_shell",
        }

    def trigger(self, action: str):
        action_key = str(action or "").strip()
        if action_key in self.SUPPORTED_ACTIONS:
            self._last_action = action_key
            return {**self.snapshot(), "accepted": True, "action": action_key}
        return {**self.snapshot(), "accepted": False, "action": action_key}


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
            "allow_proactive_replies": self._checked("allow_proactive_checkbox", session.get("allow_proactive_replies", True)),
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


class _UiShellInputActionService:
    """Shell-safe input/runtime-adjacent control facade."""

    AUDIO_STORY_PLAYBACK_MODES = ("Play Imported Audio", "Use TTS Narration")
    AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS = 8
    AUDIO_STORY_PREVIEW_TOTAL_SECONDS = 60

    def __init__(self, window):
        self._window = window
        self._last_action = ""
        self._push_to_talk_held = False
        self._audio_story_playback_state = "stopped"
        self._audio_story_seek_percent = 0

    def _audio_story_path(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        return _ui_shell_line_edit_value(self._window, "audio_file_path_edit", str(session.get("audio_story_mode_audio_path", "") or ""))

    def _audio_story_playback_mode(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        stored = str(session.get("audio_story_mode_playback_mode", "Play Imported Audio") or "Play Imported Audio")
        return _ui_shell_combo_text_value(self._window, "audio_story_playback_combo", stored) or "Play Imported Audio"

    def _audio_story_transcribe_seconds(self) -> int:
        session = dict(_read_ui_shell_session_snapshot() or {})
        slider = _ui_shell_find_object(self._window, "transcribe_seconds_slider")
        if slider is not None and hasattr(slider, "value"):
            try:
                return max(1, int(slider.value()))
            except Exception:
                pass
        return max(1, int(session.get("audio_story_mode_transcribe_seconds", self.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS) or self.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS))

    def _push_to_talk_enabled(self) -> bool:
        session = dict(_read_ui_shell_session_snapshot() or {})
        input_mode = _ui_shell_combo_text_value(self._window, "input_mode_combo", str(session.get("input_mode", "Voice Activation") or "Voice Activation"))
        dry_run_state = str(_ui_shell_dry_run_service(self._window).snapshot().get("state") or "idle").strip().lower()
        return input_mode == "Push-to-Talk" and dry_run_state != "armed"

    def _push_to_talk_hotkey(self) -> str:
        session = dict(_read_ui_shell_session_snapshot() or {})
        return str(session.get("push_to_talk_hotkey", "Right Ctrl") or "Right Ctrl").strip() or "Right Ctrl"

    def _position_text(self, seek_percent: int) -> str:
        total_seconds = int(self.AUDIO_STORY_PREVIEW_TOTAL_SECONDS)
        current_seconds = int(round(total_seconds * max(0, min(100, int(seek_percent or 0))) / 100.0))
        return f"{_ui_shell_format_clock_seconds(current_seconds)} / {_ui_shell_format_clock_seconds(total_seconds)}"

    def snapshot(self):
        push_enabled = self._push_to_talk_enabled()
        if not push_enabled:
            self._push_to_talk_held = False
        audio_path = self._audio_story_path()
        has_audio = bool(audio_path)
        playback_state = str(self._audio_story_playback_state or "stopped").strip().lower()
        if playback_state not in {"playing", "paused", "stopped"}:
            playback_state = "stopped"
        if not has_audio:
            playback_state = "stopped"
            self._audio_story_seek_percent = 0
        seek_widget = _ui_shell_find_object(self._window, "audio_story_seek_slider")
        if seek_widget is not None and hasattr(seek_widget, "value"):
            try:
                self._audio_story_seek_percent = max(0, min(100, int(seek_widget.value())))
            except Exception:
                self._audio_story_seek_percent = 0
        seek_percent = 0 if not has_audio else max(0, min(100, int(self._audio_story_seek_percent or 0)))
        return {
            "last_action": self._last_action,
            "push_to_talk_enabled": push_enabled,
            "push_to_talk_held": bool(self._push_to_talk_held and push_enabled),
            "push_to_talk_hotkey": self._push_to_talk_hotkey(),
            "audio_story_audio_path": audio_path,
            "audio_story_has_audio": has_audio,
            "audio_story_playback_mode": self._audio_story_playback_mode(),
            "audio_story_transcribe_seconds": self._audio_story_transcribe_seconds(),
            "audio_story_playback_state": playback_state,
            "audio_story_seek_percent": seek_percent,
            "audio_story_position_text": self._position_text(seek_percent),
            "shell_mode": True,
            "message": "Input/runtime-adjacent actions are shell-local previews only.",
            "source": "ui_shell",
        }

    def set_push_to_talk_hold(self, held: bool):
        self._last_action = "push_to_talk_press" if held else "push_to_talk_release"
        if held and not self._push_to_talk_enabled():
            self._push_to_talk_held = False
            payload = self.snapshot()
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Push-to-Talk preview is available only when Input Mode is Push-to-Talk and Dry Run preview is idle.",
            })
            return payload
        self._push_to_talk_held = bool(held) and self._push_to_talk_enabled()
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Push-to-Talk hold preview toggled locally only. No microphone capture started." if held else "Push-to-Talk released in shell preview. No microphone capture was active.",
        })
        return payload

    def set_audio_file_path(self, path: str):
        value = str(path or "").strip()
        self._last_action = "set_audio_file_path"
        if not value:
            self._audio_story_playback_state = "stopped"
            self._audio_story_seek_percent = 0
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "audio_story_audio_path": value,
            "message": "Audio Story preview path updated locally only." if value else "Audio Story preview path cleared.",
        })
        return payload

    def request_audio_import(self):
        self._last_action = "request_audio_import"
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Audio import dialog is deferred in shell preview. Paste a local audio path into the field to preview this surface.",
        })
        return payload

    def request_audio_transcription(self):
        self._last_action = "request_audio_transcription"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Transcription preview needs an audio path first. No Whisper/STT runtime was started.",
            })
            return payload
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Audio transcription remains deferred in shell preview. No Whisper/STT runtime was started.",
        })
        return payload

    def play_audio_story(self):
        self._last_action = "play_audio_story"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story playback preview needs an audio path first.",
            })
            return payload
        self._audio_story_playback_state = "playing"
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview started locally only. No media player or TTS narration was started.",
        })
        return payload

    def pause_audio_story(self):
        self._last_action = "pause_audio_story"
        payload = self.snapshot()
        if payload.get("audio_story_playback_state") != "playing":
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story pause preview is only available while the shell preview is marked as playing.",
            })
            return payload
        self._audio_story_playback_state = "paused"
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview paused locally only.",
        })
        return payload

    def stop_audio_story(self):
        self._last_action = "stop_audio_story"
        self._audio_story_playback_state = "stopped"
        self._audio_story_seek_percent = 0
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": "Audio Story playback preview stopped locally only. No audio runtime was active.",
        })
        return payload

    def seek_audio_story(self, position_percent: int):
        self._last_action = "seek_audio_story"
        payload = self.snapshot()
        if not payload.get("audio_story_has_audio"):
            payload.update({
                "accepted": False,
                "deferred": True,
                "message": "Audio Story seek preview needs an audio path first.",
            })
            return payload
        self._audio_story_seek_percent = max(0, min(100, int(position_percent or 0)))
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "deferred": True,
            "message": f"Audio Story seek preview moved to {payload.get('audio_story_seek_percent', 0)}%.",
        })
        return payload


class _UiShellChatReplayService:
    """Shell-safe replay facade for Chat Player and related addons."""

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def snapshot_chat_session(self):
        return {
            "conversation_history": [],
            "shell_mode": True,
            "message": "Chat replay is not connected in shell preview.",
        }

    def replayable_assistant_entries(self):
        return []

    def replayable_assistant_messages(self):
        return []

    def is_engine_running(self) -> bool:
        return False

    def is_offline_replay_only(self) -> bool:
        return False

    def trigger_control_action(self, action: str) -> None:
        self._last_action = str(action or "").strip()

    def replay_latest_reply(self) -> None:
        self._last_action = "replay_latest_reply"

    def replay_chat_session(self) -> None:
        self._last_action = "replay_chat_session"

    def replay_chat_session_from_index(self, start_index: int) -> None:
        self._last_action = f"replay_chat_session_from_index:{int(start_index or 0)}"

    def load_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).load_chat_context()

    def quick_load_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).quick_load_chat_context()

    def save_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).save_chat_context()

    def quick_save_chat_context(self) -> None:
        _ui_shell_chat_context_service(self._window).quick_save_chat_context()


class _UiShellTutorialService:
    """Shell-safe tutorial browser facade backed only by tutorial JSON files."""

    def __init__(self, window):
        self._window = window
        self._started_tutorial_id = ""

    def _tutorials_dir(self):
        return Path(__file__).resolve().parent / "tutorials"

    def list_tutorials(self):
        items = []
        try:
            for path in sorted(self._tutorials_dir().glob("*.json"), key=lambda item: item.stem.lower()):
                payload = self.load_tutorial(path.stem)
                if not payload:
                    continue
                items.append({
                    "id": str(payload.get("id") or path.stem),
                    "title": str(payload.get("title") or path.stem),
                    "description": str(payload.get("description") or ""),
                    "step_count": len(list(payload.get("steps") or [])),
                })
        except Exception:
            pass
        return items

    def load_tutorial(self, tutorial_id: str):
        key = str(tutorial_id or "").strip()
        if not key:
            return {}
        path = self._tutorials_dir() / f"{key}.json"
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def start_tutorial(self, tutorial_id: str):
        self._started_tutorial_id = str(tutorial_id or "").strip()
        return {
            "started": bool(self._started_tutorial_id),
            "tutorial_id": self._started_tutorial_id,
            "shell_mode": True,
            "message": "Tutorial start is shell-local; no overlay was created.",
            "source": "ui_shell",
        }

    def snapshot(self):
        return {
            "tutorials": self.list_tutorials(),
            "started_tutorial_id": self._started_tutorial_id,
            "shell_mode": True,
            "source": "ui_shell",
        }


class _UiShellDialogService:
    """Shell-only dialog service: report intent without opening native dialogs."""

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def _log(self, message):
        _ui_shell_append_console(self._window, f"[UI Shell] {message}")

    def open_file(self, title: str, start_dir: str = "", file_filter: str = ""):
        self._last_action = "open_file"
        self._log(f"File dialog deferred: {title or 'Open File'}")
        return "", str(file_filter or "")

    def save_file(self, title: str, start_path: str = "", file_filter: str = ""):
        self._last_action = "save_file"
        self._log(f"Save dialog deferred: {title or 'Save File'}")
        return "", str(file_filter or "")

    def open_directory(self, title: str, start_dir: str = ""):
        self._last_action = "open_directory"
        self._log(f"Directory dialog deferred: {title or 'Open Directory'}")
        return ""

    def warning(self, title: str, message: str) -> None:
        self._last_action = "warning"
        self._log(f"Warning deferred: {title or 'Warning'} - {message or ''}")

    def information(self, title: str, message: str) -> None:
        self._last_action = "information"
        self._log(f"Info deferred: {title or 'Information'} - {message or ''}")

    def snapshot(self):
        return {
            "last_action": self._last_action,
            "shell_mode": True,
            "native_dialogs_available": False,
            "source": "ui_shell",
        }


class _UiShellSensoryService:
    """Shell-only sensory registry: accept metadata without capturing input."""

    def __init__(self):
        self._providers = OrderedDict()
        self._contributors = OrderedDict()

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        instruction: str = "",
        description: str = "",
        order: int = 1000,
        capture_handler=None,
        metadata: dict | None = None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Sensory provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "instruction": str(instruction or "").strip(),
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_capture_handler": callable(capture_handler),
            "shell_mode": True,
        }
        self._providers[provider_id] = summary
        return dict(summary)

    def unregister_provider(self, provider_id: str) -> bool:
        return self._providers.pop(str(provider_id or "").strip(), None) is not None

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(self._providers.values(), key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]

    def register_prompt_contributor(
        self,
        *,
        contributor_id: str,
        source_id: str,
        label: str,
        prompt: str = "",
        order: int = 1000,
        metadata: dict | None = None,
    ):
        contributor_id = str(contributor_id or "").strip()
        if not contributor_id:
            raise RuntimeError("Sensory prompt contributor id is required.")
        summary = {
            "id": contributor_id,
            "source_id": str(source_id or "").strip(),
            "label": str(label or contributor_id).strip() or contributor_id,
            "prompt": str(prompt or ""),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "shell_mode": True,
        }
        self._contributors[contributor_id] = summary
        return dict(summary)

    def unregister_prompt_contributor(self, contributor_id: str) -> bool:
        return self._contributors.pop(str(contributor_id or "").strip(), None) is not None

    def list_prompt_contributors(self, source_id: str | None = None):
        source = str(source_id or "").strip()
        rows = list(self._contributors.values())
        if source:
            rows = [row for row in rows if str(row.get("source_id") or "").strip() == source]
        return [
            dict(item)
            for item in sorted(rows, key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]


class _UiShellAvatarProviderService:
    """Shell-only avatar provider registry: keep factories inert."""

    def __init__(self):
        self._providers = OrderedDict()

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        factory,
        description: str = "",
        order: int = 1000,
        metadata: dict | None = None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Avatar provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_factory": callable(factory),
            "shell_mode": True,
        }
        self._providers[provider_id] = summary
        return dict(summary)

    def unregister_provider(self, provider_id: str) -> bool:
        return self._providers.pop(str(provider_id or "").strip(), None) is not None

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(self._providers.values(), key=lambda row: (int(row.get("order", 1000)), str(row.get("label") or row.get("id") or "")))
        ]



class _UiShellChatProviderRegistry:
    """Shell-only provider registry: accept addon metadata without invoking handlers."""

    def __init__(self):
        self._providers = OrderedDict()
        self._registrations = {}

    def register_provider(
        self,
        *,
        provider_id,
        label,
        description="",
        order=1000,
        client_factory=None,
        model_list_handler=None,
        completion_handler=None,
        stream_handler=None,
        connection_check_handler=None,
        api_key_getter=None,
        base_url_getter=None,
        metadata=None,
    ):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            raise RuntimeError("Chat provider id is required.")
        summary = {
            "id": provider_id,
            "label": str(label or provider_id).strip() or provider_id,
            "description": str(description or "").strip(),
            "order": int(order or 1000),
            "metadata": dict(metadata or {}),
            "has_model_list_handler": callable(model_list_handler),
            "has_completion_handler": callable(completion_handler),
            "has_stream_handler": callable(stream_handler),
            "has_connection_check_handler": callable(connection_check_handler),
            "has_api_key_getter": callable(api_key_getter),
            "has_base_url_getter": callable(base_url_getter),
        }
        self._providers[provider_id] = summary
        self._registrations[provider_id] = {
            "client_factory": client_factory,
            "model_list_handler": model_list_handler,
            "completion_handler": completion_handler,
            "stream_handler": stream_handler,
            "connection_check_handler": connection_check_handler,
            "api_key_getter": api_key_getter,
            "base_url_getter": base_url_getter,
        }
        return dict(summary)

    def unregister_provider(self, provider_id):
        provider_id = str(provider_id or "").strip()
        existed = provider_id in self._providers
        self._providers.pop(provider_id, None)
        self._registrations.pop(provider_id, None)
        return existed

    def list_providers(self):
        return [
            dict(item)
            for item in sorted(
                self._providers.values(),
                key=lambda provider: (int(provider.get("order", 1000)), str(provider.get("label", ""))),
            )
        ]

    def provider_ids(self):
        return set(self._providers.keys())

    def get_provider_settings(self, provider_id=None):
        if provider_id:
            return {}
        return {provider_id: {} for provider_id in self._providers}

    def get_provider_setting(self, provider_id, field_id):
        return ""


class _UiShellHotkeyService:
    """Read-only shell hotkey service: expose bindings without mutating runtime state."""

    def list_bindings(self):
        try:
            from core import runtime_hotkeys as _hotkeys

            session = _read_ui_shell_session_snapshot()
            push_to_talk = _hotkeys.normalize_hotkey_text(
                session.get("push_to_talk_hotkey", _hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY)
            ) or _hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY
            manual_bindings = _hotkeys.normalize_manual_action_hotkeys(
                session.get("manual_action_hotkeys", _hotkeys.DEFAULT_MANUAL_ACTION_HOTKEYS)
            )
            ui_bindings = _hotkeys.normalize_ui_action_hotkeys(
                session.get("ui_action_hotkeys", _hotkeys.DEFAULT_UI_ACTION_HOTKEYS)
            )
            entries = [
                {
                    "action": "push_to_talk",
                    "label": str(_hotkeys.HOTKEY_ACTION_LABELS.get("push_to_talk", "Push-to-Talk")),
                    "binding": str(push_to_talk or ""),
                    "default_binding": str(_hotkeys.DEFAULT_PUSH_TO_TALK_HOTKEY),
                    "category": "input",
                    "scope": "global",
                    "description": "Read-only shell preview of the Push-to-Talk binding.",
                }
            ]
            for action, default_binding in _hotkeys.DEFAULT_MANUAL_ACTION_HOTKEYS.items():
                entries.append(
                    {
                        "action": action,
                        "label": str(_hotkeys.HOTKEY_ACTION_LABELS.get(action, action)),
                        "binding": str(manual_bindings.get(action, "") or ""),
                        "default_binding": str(default_binding or ""),
                        "category": "manual_controls",
                        "scope": "global_and_window",
                        "description": "Read-only shell preview of a manual control binding.",
                    }
                )
            for action, default_binding in _hotkeys.DEFAULT_UI_ACTION_HOTKEYS.items():
                entries.append(
                    {
                        "action": action,
                        "label": str(_hotkeys.HOTKEY_ACTION_LABELS.get(action, action)),
                        "binding": str(ui_bindings.get(action, "") or ""),
                        "default_binding": str(default_binding or ""),
                        "category": "ui_actions",
                        "scope": "window",
                        "description": "Read-only shell preview of a focused-window shortcut.",
                    }
                )
            return entries
        except Exception:
            return []

    def set_binding(self, action, binding):
        action_key = str(action or "").strip()
        for entry in self.list_bindings():
            if str(entry.get("action", "") or "") == action_key:
                return str(entry.get("binding", "") or "")
        return ""

    def reset_defaults(self):
        return self.list_bindings()


class _UiShellShellService:
    """Shell-preview service: allow addon UI refresh notifications without saving state."""

    def open_local_path(self, path):
        return False

    def notify_settings_changed(self):
        return None


class _UiShellVisualReplyService:
    """Shell-only visual reply service: render settings UI without image/runtime side effects."""

    _THEME_PRESETS = (
        {"id": "realistic", "label": "Realistic", "prompt": "realistic cinematic lighting, natural textures, grounded detail"},
        {"id": "cartoon", "label": "Cartoon", "prompt": "cartoon illustration, bold shapes, clean outlines"},
        {"id": "retro", "label": "Retro", "prompt": "retro halftone print texture, vintage color palette"},
        {"id": "cyberpunk", "label": "Cyberpunk", "prompt": "neon atmosphere, vivid contrast, futuristic detail"},
        {"id": "anime", "label": "Anime", "prompt": "anime key art, expressive characters, dynamic framing"},
        {"id": "storybook", "label": "Storybook", "prompt": "illustrated fantasy look, painterly storybook texture"},
    )

    def __init__(self, window):
        self._window = window
        self._state = self._initial_state()
        self._hint_label = None
        self._settings_widgets = {}
        self._panel = None

    def _initial_state(self):
        session = _read_ui_shell_session_snapshot()
        state = {
            "visual_reply_mode": str(session.get("visual_reply_mode", "auto") or "auto"),
            "visual_reply_provider": str(session.get("visual_reply_provider", "openai") or "openai"),
            "visual_reply_size": str(session.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "visual_reply_model": str(session.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "visual_reply_auto_show_dock": bool(session.get("visual_reply_auto_show_dock", True)),
            "visual_reply_story_mode": bool(session.get("visual_reply_story_mode", False)),
            "visual_reply_story_max_images": session.get("visual_reply_story_max_images", 3),
            "visual_reply_story_continuity_strength": session.get("visual_reply_story_continuity_strength", 0.8),
            "visual_reply_story_theme_prompts": dict(session.get("visual_reply_story_theme_prompts") or {}),
            "visual_reply_story_theme_enabled": list(session.get("visual_reply_story_theme_enabled") or []),
            "visual_reply_master_style_prompt": str(session.get("visual_reply_master_style_prompt", "") or ""),
            "visual_reply_master_prompt_safe": bool(session.get("visual_reply_master_prompt_safe", False)),
            "visual_reply_master_prompt_no_speech_bubbles": bool(session.get("visual_reply_master_prompt_no_speech_bubbles", False)),
        }
        if str(state["visual_reply_provider"]).strip().lower() not in {"openai", "xai"}:
            state["visual_reply_provider"] = "openai"
        return state

    def _theme_prompts(self):
        raw = dict(self._state.get("visual_reply_story_theme_prompts") or {})
        prompts = {}
        for theme in self._THEME_PRESETS:
            theme_id = str(theme.get("id") or "").strip().lower()
            if theme_id:
                prompts[theme_id] = str(raw.get(theme_id, theme.get("prompt", "")) or theme.get("prompt", "")).strip()
        return prompts

    def _theme_enabled(self):
        raw = self._state.get("visual_reply_story_theme_enabled", [])
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        if not isinstance(raw, (list, tuple, set)):
            raw = []
        valid = {str(theme.get("id") or "").strip().lower() for theme in self._THEME_PRESETS}
        enabled = []
        seen = set()
        for item in raw:
            theme_id = str(item or "").strip().lower()
            if theme_id in valid and theme_id not in seen:
                enabled.append(theme_id)
                seen.add(theme_id)
        return enabled

    def _story_continuity_strength(self):
        try:
            value = float(self._state.get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            value = 0.8
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def _story_max_images(self):
        try:
            return max(1, int(self._state.get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            return 3

    def story_theme_presets(self):
        return [dict(theme) for theme in self._THEME_PRESETS]

    def get_runtime_config(self, key, default=None):
        return self._state.get(str(key), default)

    def update_runtime_config(self, key, value):
        self._set_state(str(key), value)

    def settings_snapshot(self):
        prompts = self._theme_prompts()
        enabled = set(self._theme_enabled())
        return {
            "mode_value": str(self._state.get("visual_reply_mode", "auto") or "auto"),
            "provider_value": str(self._state.get("visual_reply_provider", "openai") or "openai"),
            "size_value": str(self._state.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "model_name": str(self._state.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "auto_show": bool(self._state.get("visual_reply_auto_show_dock", True)),
            "master_style_prompt": str(self._state.get("visual_reply_master_style_prompt", "") or ""),
            "master_prompt_safe": bool(self._state.get("visual_reply_master_prompt_safe", False)),
            "master_prompt_no_speech_bubbles": bool(self._state.get("visual_reply_master_prompt_no_speech_bubbles", False)),
            "story_mode": bool(self._state.get("visual_reply_story_mode", False)),
            "story_max_images": self._story_max_images(),
            "story_continuity_strength": self._story_continuity_strength(),
            "story_themes": [
                {
                    "id": str(theme.get("id") or "").strip().lower(),
                    "label": str(theme.get("label") or theme.get("id") or "").strip(),
                    "prompt": prompts.get(str(theme.get("id") or "").strip().lower(), ""),
                    "enabled": str(theme.get("id") or "").strip().lower() in enabled,
                }
                for theme in self._THEME_PRESETS
            ],
        }

    def mode_labels(self):
        return ["Off", "Auto"]

    def provider_labels(self):
        return ["OpenAI", "xAI / Grok"]

    def size_labels(self):
        return ["Auto", "1024x1024", "1024x1536", "1536x1024"]

    def mode_label_from_value(self, value):
        return "Off" if str(value or "").strip().lower() == "off" else "Auto"

    def provider_label_from_value(self, value):
        provider = str(value or "").strip().lower()
        return "xAI / Grok" if provider == "xai" else "OpenAI"

    def size_label_from_value(self, value):
        size = self.normalize_size(value)
        return "Auto" if size == "auto" else size

    def normalize_size(self, value):
        size = str(value or "1024x1024").strip().lower().replace(" ", "")
        if size in {"auto", "1024x1024", "1024x1536", "1536x1024"}:
            return size
        if size in {"1024 1024", "1024*1024"}:
            return "1024x1024"
        return "1024x1024"

    def attach_settings_widgets(self, **widgets):
        self._settings_widgets = dict(widgets or {})
        self._hint_label = widgets.get("hint_label")
        for widget in widgets.values():
            if widget is not None and hasattr(widget, "setToolTip"):
                widget.setToolTip("Shell-local Visual Reply preview. Changes are not saved and no image generation is started.")

    def _set_state(self, key, value):
        self._state[str(key)] = value
        self.refresh_hint()

    def apply_mode(self, choice):
        self._set_state("visual_reply_mode", "off" if str(choice or "").strip().lower() == "off" else "auto")

    def apply_provider(self, choice):
        label = str(choice or "").strip().lower()
        self._set_state("visual_reply_provider", "xai" if "grok" in label or "xai" in label else "openai")

    def apply_size(self, choice):
        self._set_state("visual_reply_size", self.normalize_size(choice))

    def apply_model(self):
        edit = self._settings_widgets.get("model_edit")
        text = str(edit.text() if edit is not None and hasattr(edit, "text") else "").strip()
        self._set_state("visual_reply_model", text or "gpt-image-1")

    def apply_auto_show(self, checked):
        self._set_state("visual_reply_auto_show_dock", bool(checked))

    def apply_story_mode(self, checked):
        self._set_state("visual_reply_story_mode", bool(checked))

    def apply_story_max_images(self, value):
        try:
            self._set_state("visual_reply_story_max_images", max(1, int(value or 1)))
        except Exception:
            self._set_state("visual_reply_story_max_images", 3)

    def apply_story_continuity_strength(self, value):
        try:
            strength = max(0.0, min(1.0, float(value or 0) / 100.0))
        except Exception:
            strength = 0.8
        self._set_state("visual_reply_story_continuity_strength", strength)

    def apply_story_theme_toggle(self, theme_id, checked):
        enabled = set(self._theme_enabled())
        theme_id = str(theme_id or "").strip().lower()
        if checked:
            enabled.add(theme_id)
        else:
            enabled.discard(theme_id)
        self._set_state("visual_reply_story_theme_enabled", sorted(enabled))

    def apply_story_theme_text(self, theme_id, text):
        prompts = self._theme_prompts()
        theme_id = str(theme_id or "").strip().lower()
        if theme_id:
            prompts[theme_id] = str(text or "").strip()
        self._set_state("visual_reply_story_theme_prompts", prompts)

    def refresh_hint(self):
        label = self._hint_label
        if label is None or not hasattr(label, "setText"):
            return
        snapshot = self.settings_snapshot()
        mode = str(snapshot.get("mode_value") or "auto")
        provider = self.provider_label_from_value(snapshot.get("provider_value"))
        model = str(snapshot.get("model_name") or "gpt-image-1")
        label.setText(
            "Shell-local Visual Reply settings preview. "
            f"Mode: {mode}; Provider: {provider}; Model: {model}. "
            "No image generation, dock replacement, or session save is connected."
        )

    def replace_panel(self, panel):
        self._panel = panel
        try:
            timer = getattr(panel, "poll_timer", None)
            if timer is not None and hasattr(timer, "stop"):
                timer.stop()
        except Exception:
            pass
        try:
            panel.setParent(self._window)
            panel.hide()
        except Exception:
            pass
        for name in (
            "prev_button",
            "load_button",
            "next_button",
            "load_story_button",
            "use_style_button",
            "caption_button",
            "delete_button",
            "clear_button",
            "delete_all_button",
        ):
            try:
                button = getattr(panel, name, None)
                if button is not None:
                    button.setEnabled(False)
                    button.setToolTip("Disabled in the main.ui shell preview; Visual Reply dock/image history remains Designer-owned.")
            except Exception:
                pass
        return False

    def show(self):
        return None

    def hide(self):
        return None

    def clear(self, *args, **kwargs):
        return False

    def set_loading(self, *args, **kwargs):
        return False

    def show_image(self, *args, **kwargs):
        return False


