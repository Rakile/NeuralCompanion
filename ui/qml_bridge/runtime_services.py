from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any

from core import avatar_hand_state, avatar_runtime, chat_providers, runtime_hotkeys, sensory, user_image_turns
from PySide6 import QtCore, QtGui
from core.addons.runtime_config_service import (
    AddonRuntimeOperations,
    RuntimeConfigService,
    addon_runtime_operations,
)


def _runtime_running(window) -> bool:
    probe = getattr(window, "runtime_running", None)
    if callable(probe):
        return bool(probe())
    if probe is not None:
        return bool(probe)
    thread = getattr(window, "thread", None)
    return bool(thread and thread.is_alive())

class QtShellService:
    def __init__(
        self,
        window,
        *,
        toggle_main_window=None,
        initialize_system=None,
        terminate_system=None,
        runtime_state=None,
        activate_floating_workspace=None,
    ):
        self._window = window
        self._toggle_main_window = toggle_main_window
        self._initialize_system = initialize_system
        self._terminate_system = terminate_system
        self._runtime_state = runtime_state
        self._activate_floating_workspace = activate_floating_workspace

    def open_local_path(self, path) -> bool:
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(path).resolve())))

    def send_typed_chat_message(self, text=None, metadata=None) -> bool:
        sender = getattr(self._window, "send_typed_chat_message", None)
        if callable(sender):
            return bool(sender(text=text, metadata=dict(metadata or {})))
        backend = getattr(self._window, "backend", None)
        sender = getattr(backend, "send_typed_chat_message", None)
        if callable(sender):
            queued = bool(sender(text=text, metadata=dict(metadata or {})))
            sync = getattr(self._window, "_sync_backend_to_ui", None)
            if queued and callable(sync):
                try:
                    sync(force=True)
                except Exception:
                    pass
            return queued
        return False

    def notify_settings_changed(self) -> None:
        if hasattr(self._window, "_refresh_preset_dirty_state"):
            self._window._refresh_preset_dirty_state()
        if hasattr(self._window, "save_session"):
            self._window.save_session()

    def toggle_main_window(self) -> bool:
        callback = self._toggle_main_window
        if not callable(callback):
            return False
        callback()
        return True

    def initialize_system(self) -> bool:
        callback = self._initialize_system
        if not callable(callback):
            return False
        callback()
        return True

    def terminate_system(self) -> bool:
        callback = self._terminate_system
        if not callable(callback):
            return False
        callback()
        return True

    def runtime_state(self) -> dict[str, bool]:
        callback = self._runtime_state
        if not callable(callback):
            return {
                "running": False,
                "starting": False,
                "cleanup_pending": False,
                "theme_preset": "midnight",
            }
        state = dict(callback() or {})
        return {
            "running": bool(state.get("running", False)),
            "starting": bool(state.get("starting", False)),
            "cleanup_pending": bool(state.get("cleanup_pending", False)),
            "theme_preset": str(
                state.get("theme_preset", "midnight") or "midnight"
            ),
        }

    def activate_floating_workspace(
        self,
        workspace_key: str,
        close_if_floating: bool = False,
    ) -> bool:
        callback = self._activate_floating_workspace
        if not callable(callback):
            return False
        callback(
            str(workspace_key or ""),
            bool(close_if_floating),
        )
        return True














class QtUserImageTurnService:
    def __init__(self, window, chat_commands=None):
        self._window = window
        self._chat_commands = chat_commands

    def clear_pending_attachment(self) -> None:
        user_image_turns.clear_pending_attachment()

    def set_pending_attachment(self, image_path: str, *, source: str = "clipboard") -> None:
        user_image_turns.set_pending_attachment(str(image_path or ""), source=str(source or "clipboard"))

    def queue_image_turn(
        self,
        image_path: str,
        *,
        content: str | None = None,
        source: str = "clipboard",
        remote_capture_id: str = "",
        remote_request_id: str = "",
        max_output_tokens: int | None = None,
        response_guidance: str = "",
        phone_reply_control: bool = False,
        phone_shared_queue: bool = False,
    ) -> None:
        if self._chat_commands is None:
            raise RuntimeError("User image turn runtime is not configured.")
        metadata = {
            "attachment_image_path": str(image_path or ""),
            "attachment_source": str(source or "clipboard"),
            "remote_capture_id": str(remote_capture_id or ""),
            "remote_request_id": str(remote_request_id or ""),
        }
        if phone_reply_control is True and type(remote_capture_id) is str and remote_capture_id.strip():
            metadata["phone_reply_control"] = True
            if phone_shared_queue is True:
                metadata["phone_shared_queue"] = True
        if max_output_tokens is not None and not isinstance(max_output_tokens, bool):
            try:
                token_cap = int(max_output_tokens)
            except (TypeError, ValueError, OverflowError):
                token_cap = 0
            if token_cap > 0:
                metadata["normal_chat_output_token_cap"] = min(token_cap, 131_072)
        private_guidance = str(response_guidance or "").strip()
        if private_guidance:
            metadata["companion_orb_response_guidance"] = private_guidance[:1400]
        result = self._chat_commands.queue_typed(
            str(content or "").strip() or "Please respond to the image I just sent you.",
            role="user",
            metadata=metadata,
        )
        if result.accepted:
            print(f"📋 [Image Input] Queued image input for next model request: {image_path}")
            return
        failure = result.failure
        if failure is not None and failure.cause is not None:
            raise failure.cause
        raise RuntimeError(
            failure.message if failure is not None else "Could not queue image input."
        )


class QtHandCalibrationService:
    def __init__(self, window):
        self._window = window

    def debug_state(self) -> dict:
        return avatar_hand_state.hand_debug()

    def calibration(self) -> dict:
        return avatar_hand_state.hand_calibration()

    def set_debug_active(self, active: bool) -> bool:
        debug = self.debug_state()
        debug["active"] = bool(active)
        return bool(debug["active"])

    def set_debug_axis(self, key: str, value) -> float:
        normalized = str(key or "").strip()
        if normalized not in self.debug_state():
            raise KeyError(f"Unknown hand debug axis: {normalized}")
        numeric = float(value)
        self.debug_state()[normalized] = numeric
        return numeric

    def load_calibration_preset(self, preset_id: str) -> bool:
        preset = self.calibration().get(str(preset_id or "").strip())
        if not preset:
            return False
        self.debug_state().update(dict(preset))
        self.set_debug_active(True)
        return True

    def save_calibration_preset(self, preset_id: str) -> dict:
        debug = self.debug_state()
        payload = {
            "finger_x": float(debug["finger_x"]),
            "finger_y": float(debug["finger_y"]),
            "finger_z": float(debug["finger_z"]),
            "thumb_x": float(debug["thumb_x"]),
            "thumb_y": float(debug["thumb_y"]),
            "thumb_z": float(debug["thumb_z"]),
        }
        self.calibration()[str(preset_id or "").strip()] = payload
        return payload


class QtRuntimeStatusService:
    def __init__(self, window):
        self._window = window

    def snapshot(self):
        if hasattr(self._window, "build_runtime_status_snapshot"):
            return self._window.build_runtime_status_snapshot().to_dict()
        return {}

    def status_line(self) -> str:
        if hasattr(self._window, "build_runtime_status_snapshot"):
            return self._window.build_runtime_status_snapshot().status_line()
        return "runtime: unavailable"


class QtInputSettingsService:
    def __init__(self, window):
        self._runtime_config = RuntimeConfigService(window)

    def snapshot(self):
        runtime = self._runtime_config.snapshot()
        audio_input = str(runtime.get("audio_input_device", "Default Input") or "Default Input")
        audio_output = str(runtime.get("audio_output_device", "Default Output") or "Default Output")
        return {
            "audio_input_device": audio_input,
            "audio_output_device": audio_output,
            "audio_input_options": [audio_input],
            "audio_output_options": [audio_output],
            "input_mode": str(runtime.get("input_mode", "voice_activation") or "voice_activation"),
            "input_role": str(runtime.get("input_message_role", "user") or "user"),
            "stream_mode": bool(runtime.get("stream_mode", False)),
            "allow_proactive_replies": bool(runtime.get("allow_proactive_replies", True)),
            "require_first_user_before_proactive": bool(runtime.get("require_first_user_before_proactive", False)),
            "listen_idle_window_seconds": float(runtime.get("listen_idle_window_seconds", 5.0) or 5.0),
            "proactive_delay_seconds": float(runtime.get("proactive_delay_seconds", 10.0) or 10.0),
            "chat_context_window_messages": int(runtime.get("chat_context_window_messages", 20) or 20),
            "stored_chat_history_limit": int(runtime.get("stored_chat_history_limit", 0) or 0),
            "chat_context_overflow_policy": str(runtime.get("chat_context_overflow_policy", "rolling_window") or "rolling_window"),
            "limit_response_length": bool(runtime.get("limit_response_length", False)),
            "max_response_tokens": int(runtime.get("max_response_tokens", 600) or 600),
            "shell_mode": False,
            "message": "Input/session settings are available.",
            "source": "qt_app",
        }

    def apply(self, updates: dict | None = None, **kwargs):
        payload = dict(updates or {})
        payload.update(kwargs)
        aliases = {"input_role": "input_message_role"}
        for key, value in payload.items():
            if key in {"audio_input_options", "audio_output_options", "shell_mode", "message", "source"}:
                continue
            self._runtime_config.update(aliases.get(str(key), str(key)), value)
        return self.snapshot()


class QtInputActionService:
    def acquire_capture_hotkeys(self):
        """Return a release callback for a capture owner independent of chat."""
        owner = object()
        try:
            runtime_hotkeys.bind_hotkey_state_tracker(owner=owner)
        except Exception:
            runtime_hotkeys.unbind_hotkey_state_tracker(owner=owner)
            raise
        return lambda: runtime_hotkeys.unbind_hotkey_state_tracker(owner=owner)

    def __init__(self, window):
        self._window = window
        self._runtime_config = RuntimeConfigService(window)
        operations = addon_runtime_operations(window)
        self._push_to_talk_hotkey = operations.push_to_talk_hotkey
        self._set_push_to_talk_hold = operations.set_push_to_talk_hold
        self._last_action = ""
        self._push_to_talk_held = False

    def _push_to_talk_enabled(self) -> bool:
        runtime = self._runtime_config.snapshot()
        input_mode = str(runtime.get("input_mode", "voice_activation") or "voice_activation").strip().lower()
        status_builder = getattr(self._window, "build_runtime_status_snapshot", None)
        status = status_builder() if callable(status_builder) else {}
        if hasattr(status, "to_dict"):
            status = status.to_dict()
        status = dict(status or {})
        running = str(status.get("lifecycle_state", "stopped") or "stopped").lower() in {"starting", "running"}
        return running and input_mode == "push_to_talk" and not bool(runtime.get("offline_replay_only", False))

    def snapshot(self):
        try:
            push_to_talk_hotkey = str(self._push_to_talk_hotkey() or "Right Ctrl").strip() or "Right Ctrl"
        except Exception:
            push_to_talk_hotkey = "Right Ctrl"
        push_enabled = self._push_to_talk_enabled()
        if not push_enabled:
            self._push_to_talk_held = False
        capture_held = False
        runtime = self._runtime_config.snapshot()
        if str(runtime.get("input_mode", "voice_activation") or "voice_activation").strip().lower() == "push_to_talk":
            try:
                capture_held = bool(self._push_to_talk_held or runtime_hotkeys.is_hotkey_binding_pressed(push_to_talk_hotkey))
            except Exception:
                capture_held = bool(self._push_to_talk_held)
        return {
            "last_action": self._last_action,
            "push_to_talk_enabled": push_enabled,
            "push_to_talk_held": bool(self._push_to_talk_held and push_enabled),
            "push_to_talk_capture_held": capture_held,
            "push_to_talk_hotkey": push_to_talk_hotkey,
            "shell_mode": False,
            "push_to_talk_runtime_available": True,
            "message": "Input actions are available when the owning runtime exists.",
            "source": "qt_app",
        }

    def set_push_to_talk_hold(self, held: bool):
        self._last_action = "push_to_talk_press" if held else "push_to_talk_release"
        if held and not self._push_to_talk_enabled():
            self._push_to_talk_held = False
            payload = self.snapshot()
            payload.update({
                "accepted": False,
                "message": "Push-to-Talk is not currently enabled.",
            })
            return payload
        accepted = False
        try:
            self._set_push_to_talk_hold(bool(held))
            self._push_to_talk_held = bool(held)
            accepted = True
        except Exception:
            self._push_to_talk_held = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Push-to-Talk hold changed." if accepted else "Push-to-Talk runtime action was unavailable.",
        })
        return payload

class QtPerformanceProfileService:
    def __init__(self, window):
        self._window = window

    def _selected_name(self, source: str = "dry_run") -> str:
        if source == "chunking":
            combo = getattr(self._window, "chunking_profile_combo", None)
        else:
            combo = getattr(self._window, "performance_profile_combo", None)
        if combo is None or not hasattr(combo, "currentData"):
            return ""
        try:
            return str(combo.currentData() or "").strip()
        except Exception:
            return ""

    def _current_chunking(self) -> dict:
        sliders = dict(getattr(self._window, "chunking_sliders", {}) or {})
        values = {}
        for key, slider in sliders.items():
            try:
                values[str(key)] = slider.value()
            except Exception:
                continue
        return values

    def snapshot(self):
        combo = getattr(self._window, "performance_profile_combo", None)
        profiles = []
        if combo is not None and hasattr(combo, "count"):
            try:
                for index in range(combo.count()):
                    name = str(combo.itemData(index) or "").strip()
                    label = str(combo.itemText(index) or "").strip()
                    if name:
                        profiles.append({"name": name, "label": label})
            except Exception:
                profiles = []
        return {
            "profiles": profiles,
            "selected_chunking_profile": self._selected_name("chunking"),
            "selected_performance_profile": self._selected_name("dry_run"),
            "current_chunking": self._current_chunking(),
            "shell_mode": False,
            "load_available": hasattr(self._window, "load_performance_profile_by_id"),
            "refresh_available": hasattr(self._window, "refresh_performance_profile_list"),
            "reset_available": hasattr(self._window, "reset_chunking_defaults"),
            "save_available": hasattr(self._window, "save_latest_performance_profile") or hasattr(self._window, "save_current_chunking_profile"),
            "delete_available": hasattr(self._window, "delete_selected_performance_profile") or hasattr(self._window, "delete_selected_chunking_profile"),
            "message": "Performance profiles are available.",
            "source": "qt_app",
        }

    def refresh_profiles(self, preferred_name: str = ""):
        refresh = getattr(self._window, "refresh_performance_profile_list", None)
        if callable(refresh):
            refresh()
        return self.snapshot()

    def load_profile(self, name: str = "", *, source: str = "dry_run"):
        target_name = str(name or "").strip() or self._selected_name(source)
        loaded = False
        load = getattr(self._window, "load_performance_profile_by_id", None)
        if target_name and callable(load):
            loaded = bool(load(target_name))
        payload = self.snapshot()
        payload.update({
            "accepted": bool(loaded),
            "loaded": bool(loaded),
            "profile_name": target_name,
        })
        return payload

    def reset_chunking_defaults(self):
        reset = getattr(self._window, "reset_chunking_defaults", None)
        if callable(reset):
            reset()
        payload = self.snapshot()
        payload.update({
            "accepted": True,
            "action": "reset_chunking_defaults",
        })
        return payload

    def save_profile(self, *, source: str = "dry_run"):
        if source == "chunking":
            save = getattr(self._window, "save_current_chunking_profile", None)
        else:
            save = getattr(self._window, "save_latest_performance_profile", None)
        if callable(save):
            save()
        payload = self.snapshot()
        payload.update({
            "accepted": callable(save),
            "action": "save_profile",
            "source_kind": source,
        })
        return payload

    def delete_profile(self, *, source: str = "dry_run"):
        if source == "chunking":
            delete = getattr(self._window, "delete_selected_chunking_profile", None)
        else:
            delete = getattr(self._window, "delete_selected_performance_profile", None)
        if callable(delete):
            delete()
        payload = self.snapshot()
        payload.update({
            "accepted": callable(delete),
            "action": "delete_profile",
            "source_kind": source,
        })
        return payload


class QtDryRunService:
    def __init__(self, window):
        self._window = window

    def _status(self):
        try:
            import dry_run
            return dry_run.get_status() or {}
        except Exception:
            return {}

    def _latest(self):
        try:
            import dry_run
            return dry_run.get_latest_profile() or {}
        except Exception:
            return {}

    def snapshot(self):
        status = dict(self._status() or {})
        latest = dict(self._latest() or {})
        target_widget = getattr(self._window, "dry_run_target_spin", None)
        auto_widget = getattr(self._window, "dry_run_auto_replies_checkbox", None)
        target = int(target_widget.value()) if target_widget is not None and hasattr(target_widget, "value") else 0
        auto_replies = bool(auto_widget.isChecked()) if auto_widget is not None and hasattr(auto_widget, "isChecked") else True
        recommendation = dict(status.get("recommendation") or (latest.get("recommendation") or {}) or {})
        return {
            "status": status,
            "latest_profile": latest,
            "target_samples": target,
            "auto_replies": auto_replies,
            "active": bool(status.get("active")),
            "complete": bool(status.get("complete")),
            "has_recommendation": bool(recommendation.get("settings")),
            "shell_mode": False,
            "message": "Dry Run controls are available.",
            "source": "qt_app",
        }

    def refresh(self):
        refresh = getattr(self._window, "refresh_dry_run_status", None)
        if callable(refresh):
            refresh()
        return self.snapshot()

    def start_session(self):
        start = getattr(self._window, "start_dry_run_session", None)
        if callable(start):
            start()
        return self.snapshot()

    def stop_session(self):
        stop = getattr(self._window, "stop_dry_run_session", None)
        if callable(stop):
            stop()
        return self.snapshot()

    def apply_recommendation(self):
        apply = getattr(self._window, "apply_dry_run_recommendation", None)
        if callable(apply):
            apply()
        return self.snapshot()


class QtPersonaAvatarService:
    def __init__(self, window):
        self._window = window

    def _combo(self, name: str):
        return getattr(self._window, str(name), None)

    def _checkbox(self, name: str):
        return getattr(self._window, str(name), None)

    def _line_edit(self, name: str):
        return getattr(self._window, str(name), None)

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

    def _checked(self, name: str, default: bool = False) -> bool:
        widget = self._checkbox(name)
        if widget is not None and hasattr(widget, "isChecked"):
            try:
                return bool(widget.isChecked())
            except Exception:
                pass
        return bool(default)

    def _line_value(self, name: str, default: str = "") -> str:
        widget = self._line_edit(name)
        if widget is not None and hasattr(widget, "text"):
            try:
                return str(widget.text() or "").strip()
            except Exception:
                pass
        return str(default or "").strip()

    def _pose_values(self) -> dict:
        sliders = dict(getattr(self._window, "pose_sliders", {}) or {})
        values = {}
        for key, slider in sliders.items():
            try:
                values[str(key)] = slider.value()
            except Exception:
                continue
        return values

    def snapshot(self):
        emotional = getattr(self._window, "emotional_text", None)
        system_prompt = getattr(self._window, "system_prompt_text", None)
        return {
            "voice_file": self._combo_text("voice_combo"),
            "voice_options": self._combo_items("voice_combo"),
            "emotional_instructions": str(emotional.toPlainText().strip()) if emotional is not None and hasattr(emotional, "toPlainText") else "",
            "system_prompt": str(system_prompt.toPlainText().strip()) if system_prompt is not None and hasattr(system_prompt, "toPlainText") else "",
            "body_presets": self._combo_items("body_combo"),
            "selected_body": self._combo_text("body_combo"),
            "emotion": self._combo_text("emotion_combo", "Neutral"),
            "live_sync": self._checked("live_sync_checkbox", False),
            "pose_values": self._pose_values(),
            "shell_mode": False,
            "message": "Persona/body controls are available.",
            "source": "qt_app",
        }

    def refresh_body_list(self):
        refresh = getattr(self._window, "refresh_body_list", None)
        if callable(refresh):
            refresh()
        return self.snapshot()

    def load_body(self, name: str = ""):
        target = str(name or "").strip()
        combo = getattr(self._window, "body_combo", None)
        if target and combo is not None and hasattr(combo, "findText"):
            index = combo.findText(target)
            if index >= 0:
                combo.setCurrentIndex(index)
        load = getattr(self._window, "load_body_config_from_combo", None)
        if callable(load):
            load()
        return self.snapshot()

    def save_body(self, name: str = ""):
        target = str(name or "").strip()
        if target:
            save_named = getattr(self._window, "save_body_config", None)
            if callable(save_named):
                save_named(target)
        else:
            save_current = getattr(self._window, "save_current_body", None)
            if callable(save_current):
                save_current()
        return self.snapshot()

    def delete_body(self):
        delete = getattr(self._window, "delete_current_body", None)
        if callable(delete):
            delete()
        return self.snapshot()

    def apply_persona(self):
        apply = getattr(self._window, "apply_text_config", None)
        if callable(apply):
            apply()
        return self.snapshot()

    def open_external_avatar_view(self, mode: str = "vseeface"):
        handler = getattr(self._window, "enter_external_avatar_focus", None)
        if callable(handler):
            handler("VSeeFace")
        return self.snapshot()


class QtModelRefreshService:
    def __init__(self, window):
        self._window = window

    def snapshot(self, provider_id: str | None = None):
        current_provider = ""
        try:
            if hasattr(self._window, "_current_chat_provider_value"):
                current_provider = str(self._window._current_chat_provider_value() or "")
        except Exception:
            current_provider = ""
        provider = str(provider_id or current_provider or "").strip().lower()
        model_combo = getattr(self._window, "model_combo", None)
        items = []
        selected_model = ""
        if model_combo is not None:
            try:
                selected_model = str(model_combo.currentText() or "").strip()
                items = [
                    str(model_combo.itemText(index) or "").strip()
                    for index in range(model_combo.count())
                    if str(model_combo.itemText(index) or "").strip()
                ]
            except Exception:
                items = []
        return {
            "provider": provider,
            "selected_model": selected_model,
            "models": items,
            "in_flight": bool(getattr(self._window, "_model_refresh_in_flight", False)),
            "refresh_provider": str(getattr(self._window, "_model_refresh_provider", "") or ""),
            "refresh_available": hasattr(self._window, "request_model_list_refresh"),
            "deferred": False,
            "message": "Live model refresh is available.",
            "source": "qt_app",
        }

    def refresh(self, provider_id: str | None = None, *, quiet: bool = True, wait_for_reachable: bool = False):
        refresh = getattr(self._window, "request_model_list_refresh", None)
        if callable(refresh):
            refresh(quiet=bool(quiet), wait_for_reachable=bool(wait_for_reachable))
        return self.snapshot(provider_id)


class QtEngineLifecycleService:
    def __init__(self, window):
        self._window = window

    def snapshot(self):
        running = _runtime_running(self._window)
        read_state = getattr(self._window, 'runtime_engine_state', None)
        flags = dict(read_state() or {}) if callable(read_state) else {}
        runtime_status = {}
        if hasattr(self._window, "build_runtime_status_snapshot"):
            try:
                runtime_status = self._window.build_runtime_status_snapshot().to_dict()
            except Exception:
                runtime_status = {}
        return {
            "running": running,
            **{key: bool(flags.get(key, False)) for key in
               ('starting', 'initializing', 'stopping', 'cancelling', 'cleanup_pending')},
            "shell_mode": False,
            "engine_connected": running,
            "runtime_status": runtime_status,
            "message": "Engine lifecycle is available.",
            "source": "qt_app",
        }

    def start_engine(self, *, offline_replay_only: bool = False):
        start = getattr(self._window, "start_engine", None)
        if callable(start):
            start(offline_replay_only=bool(offline_replay_only))
        return self.snapshot()

    def stop_engine(self):
        stop = getattr(self._window, "stop_engine", None)
        if callable(stop):
            stop()
        return self.snapshot()

    def reset_chat_memory(self):
        reset = getattr(self._window, "reset_chat_session", None)
        if callable(reset):
            reset()
        return self.snapshot()

    def start(self, **kwargs):
        return self.start_engine(**kwargs)

    def stop(self):
        return self.stop_engine()

    def reset(self):
        return self.reset_chat_memory()


class QtRuntimeControlService:
    SUPPORTED_ACTIONS = (
        "interrupt_response",
        "regenerate_response",
        "retry_user_input",
        "pause_speech",
        "skip_speech",
        "skip_user_reply",
        "replay_last_assistant",
        "replay_chat_session",
    )

    def __init__(self, window, *,
                 web_search_status: Callable[[], dict[str, Any] | None] | None = None,
                 set_web_search_enabled: Callable[[bool], dict[str, Any]] | None = None):
        self._window = window
        self._last_action = ""
        self._interrupt_response = addon_runtime_operations(window).interrupt_speech
        self._web_search_status = web_search_status
        self._set_web_search_enabled = set_web_search_enabled

    def web_search_snapshot(self) -> dict[str, bool]:
        # Only finite display state crosses the phone boundary.
        status_reader = getattr(self, "_web_search_status", None)
        try:
            status = status_reader() if callable(status_reader) else None
        except (RuntimeError, TypeError, ValueError):
            status = None
        available = isinstance(status, dict) and callable(getattr(self, "_set_web_search_enabled", None))
        status = status or {}
        return {"available": available,
                "enabled": available and str(status.get("mode") or "auto") != "off",
                "online": available and int(dict(status.get("backend") or {}).get("online_count") or 0) > 0}

    def set_web_search_enabled(self, enabled: bool) -> dict[str, Any]:
        if not self.web_search_snapshot()["available"]:
            return {"accepted": False, "message": "Web Search is unavailable. Enable its desktop addon first."}
        result = dict(self._set_web_search_enabled(bool(enabled)) or {})
        accepted = result.get("accepted") is True
        reason = str(result.get("reason") or "unavailable").replace("_", " ")
        message = ("Web Search is starting." if result.get("starting") else
                   f"Web Search: {'On' if enabled else 'Off'}.") if accepted else f"Web Search: {reason}. Check desktop Web Search settings."
        return {"accepted": accepted, "message": message}

    def snapshot(self):
        return {
            "actions": list(self.SUPPORTED_ACTIONS),
            "web_search": self.web_search_snapshot(),
            "last_action": self._last_action,
            "shell_mode": False,
            "runtime_connected": _runtime_running(self._window),
            "message": "Runtime control actions are available.",
            "source": "qt_app",
        }

    def trigger(self, action: str):
        action_key = str(action or "").strip()
        if action_key == "interrupt_response":
            try:
                result = dict(
                    self._interrupt_response(
                        reason="phone_live_mic",
                        cancel_llm_streams=True,
                    )
                    or {}
                )
            except Exception as exc:
                return {
                    **self.snapshot(),
                    "accepted": False,
                    "action": action_key,
                    "message": str(exc) or "Could not interrupt the active response.",
                }
            self._last_action = action_key
            return {
                **self.snapshot(),
                "accepted": True,
                "action": action_key,
                "interrupt": {
                    "cancelled_controllers": max(0, int(result.get("cancelled_controllers") or 0)),
                    "cancelled_streams": max(0, int(result.get("cancelled_streams") or 0)),
                },
            }
        accepted = False
        if action_key:
            trigger = getattr(self._window, "trigger_control_action", None)
            if callable(trigger):
                trigger(action_key)
                self._last_action = action_key
                accepted = True
        return {**self.snapshot(), "accepted": accepted, "action": action_key}


class QtChatContextService:
    document_context_version = 3
    def __init__(self, window, *, app_root=None, on_phone_load=None):
        self._window = window
        self._last_action = ""
        operations = addon_runtime_operations(window)
        self._history_snapshot = operations.conversation_history_snapshot
        self._addon_contexts = operations.collect_addon_chat_contexts
        # Legacy hosts can still provide a one-argument collector. Advertise
        # attribution only when the bound callable accepts it; never retry a
        # failed retrieval after a TypeError, which could duplicate provider work.
        import inspect
        try:
            parameters = inspect.signature(self._addon_contexts).parameters
            keywords = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values())
            self.document_context_version = (
                3 if "document_package_id" in parameters or keywords
                else 2 if "document_memory" in parameters
                else int("request_kind" in parameters))
        except (TypeError, ValueError):
            self.document_context_version = 0
        self._phone_load_callback = on_phone_load
        self._story_store = None
        self._story_executor = None
        self._story_timer = None
        self._story_lock = None
        self._story_started = False
        if app_root is not None and getattr(window, "_application", None) is not None:
            from concurrent.futures import ThreadPoolExecutor
            from threading import RLock
            from .story_checkpoint import StoryCheckpointStore

            self._story_store = StoryCheckpointStore(window._application, Path(app_root))
            self._story_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nc-story-checkpoint")
            self._story_lock = RLock()

    @property
    def phone_story_available(self) -> bool:
        return self._story_store is not None

    def start_story_persistence(self) -> None:
        if not self.phone_story_available or self._story_started:
            return
        self._story_started = True

        def restore() -> None:
            try:
                if self._story_store.has_named_context():
                    # Named chat loading belongs to desktop startup. Keep the
                    # old checkpoint until the loaded history is published.
                    return
                restored = self._story_store.restore_if_empty()
                if restored and callable(self._phone_load_callback):
                    self._phone_load_callback(False)
                if not self._story_store.has_named_context():
                    self._story_store.save()
            except Exception:
                # Keep the existing checkpoint if it cannot be read or exported.
                import logging
                logging.getLogger(__name__).exception("Could not restore phone story checkpoint")

        self._story_executor.submit(restore)

    def story_history_changed(self) -> None:
        if not self._story_started or self._story_executor is None:
            return
        from threading import Timer

        with self._story_lock:
            if self._story_timer is not None:
                self._story_timer.cancel()
            timer = Timer(0.5, self.flush_story_checkpoint)
            timer.daemon = True
            self._story_timer = timer
            timer.start()

    def flush_story_checkpoint(self) -> None:
        if not self._story_started or self._story_executor is None:
            return
        with self._story_lock:
            if self._story_timer is not None:
                self._story_timer.cancel()
                self._story_timer = None

        def save() -> None:
            try:
                if self._story_store.has_named_context() and not self._story_store.has_messages():
                    # The first remote poll may run before desktop Load ends.
                    # Reset clears the named path, so empty reset tombstones
                    # still replace the checkpoint normally.
                    return
                self._story_store.save()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Could not save phone story checkpoint")

        self._story_executor.submit(save)

    def phone_quick_save(self) -> str:
        if not self.phone_story_available:
            raise RuntimeError("Phone chat saves are unavailable.")
        from .chat_context_io import write_chat_context
        target = self._story_store.manual_path
        return self._story_executor.submit(write_chat_context, self._window._application, target).result(timeout=30)

    def export_story(self, target: Path) -> dict[str, int]:
        """Private named-story export; Quick Save's single slot is untouched."""
        if not self.phone_story_available:
            raise RuntimeError("Phone chat saves are unavailable.")
        from .chat_context_io import write_chat_context_with_report

        _path, report = self._story_executor.submit(
            write_chat_context_with_report, self._window._application, target).result(timeout=30)
        return report

    def import_story(self, payload: dict, source: Path) -> str:
        """Load a transformed version while resolving its images at the source."""
        if not self.phone_story_available:
            raise RuntimeError("Phone chat saves are unavailable.")
        from .chat_context_io import load_chat_context_payload

        detail = self._story_executor.submit(
            load_chat_context_payload, self._window._application, payload, source).result(timeout=30)
        if callable(self._phone_load_callback):
            self._phone_load_callback(False)
        return detail

    def phone_quick_load(self) -> str:
        if not self.phone_story_available:
            raise RuntimeError("Phone chat saves are unavailable.")
        from .chat_context_io import load_chat_context
        target = self._story_store.manual_path

        def load() -> str:
            detail = load_chat_context(self._window._application, target)
            self._story_store.save()
            if callable(self._phone_load_callback):
                self._phone_load_callback(True)
            return detail

        return self._story_executor.submit(load).result(timeout=30)

    def history_snapshot(self):
        return tuple(self._history_snapshot() or ())

    def addon_contexts(self, history, *, request_kind=None, document_memory=None, document_package_id=None):
        options = {"request_kind": request_kind} if request_kind is not None else {}
        if document_memory is not None:
            if self.document_context_version < 2:
                raise RuntimeError("This host does not support Persona Document Memory overrides.")
            options["document_memory"] = bool(document_memory)
        if document_package_id and document_memory is not False:
            if self.document_context_version < 3:
                raise RuntimeError("This host does not support Persona document package overrides.")
            options["document_package_id"] = str(document_package_id).strip()
        return tuple(self._addon_contexts(list(history or ()), **options) or ())

    def snapshot(self):
        quick_path = None
        try:
            quick_path_fn = getattr(self._window, "_quick_chat_context_path", None)
            if callable(quick_path_fn):
                quick_path = str(quick_path_fn())
        except Exception:
            quick_path = None
        return {
            "last_action": self._last_action,
            "shell_mode": False,
            "file_operations_available": True,
            "quick_context_path": quick_path,
            "message": "Chat context file operations are available.",
            "source": "qt_app",
        }

    def save_chat_context(self):
        self._last_action = "save_chat_context"
        handler = getattr(self._window, "save_chat_context", None)
        if callable(handler):
            handler()
        return self.snapshot()

    def save_chat_context_as(self):
        self._last_action = "save_chat_context_as"
        handler = getattr(self._window, "save_chat_context_as", None)
        if callable(handler):
            handler()
        return self.snapshot()

    def load_chat_context(self):
        self._last_action = "load_chat_context"
        handler = getattr(self._window, "load_chat_context", None)
        if callable(handler):
            handler()
        return self.snapshot()

    def quick_save_chat_context(self):
        self._last_action = "quick_save_chat_context"
        handler = getattr(self._window, "quick_save_chat_context", None)
        if callable(handler):
            handler()
        return self.snapshot()

    def quick_load_chat_context(self):
        self._last_action = "quick_load_chat_context"
        handler = getattr(self._window, "quick_load_chat_context", None)
        if callable(handler):
            handler()
        return self.snapshot()

    def reset_chat_memory(self):
        self._last_action = "reset_chat_memory"
        handler = getattr(self._window, "reset_chat_session", None)
        if callable(handler):
            handler()
        return self.snapshot()


class QtTutorialService:
    def __init__(self, window):
        self._window = window

    def list_tutorials(self):
        from core import tutorial_catalog

        return list(tutorial_catalog.list_tutorials() or [])

    def load_tutorial(self, tutorial_id: str):
        from core import tutorial_catalog

        return dict(tutorial_catalog.load_tutorial(str(tutorial_id or "")) or {})

    def start_tutorial(self, tutorial_id: str):
        handler = getattr(self._window, "start_tutorial", None)
        if callable(handler):
            handler(str(tutorial_id or ""))
        return {
            "started": bool(str(tutorial_id or "").strip()),
            "tutorial_id": str(tutorial_id or "").strip(),
            "shell_mode": False,
            "source": "qt_app",
        }

    def refresh_tutorials(self):
        handler = getattr(self._window, "refresh_tutorial_list", None)
        if callable(handler):
            handler()
        return self.list_tutorials()


class QtHotkeyService:
    def __init__(self, window):
        self._window = window

    def list_bindings(self):
        return list(self._window.hotkey_catalog())

    def register_actions(self, actions, labels):
        runtime_hotkeys.register_ui_action_hotkeys(
            dict(actions or {}),
            dict(labels or {}),
        )
        refresher = getattr(self._window, "_refresh_hotkey_labels", None)
        if callable(refresher):
            refresher()
        return self.list_bindings()

    def set_binding(self, action: str, binding: str):
        return self._window.set_hotkey_binding(str(action or "").strip(), str(binding or ""))

    def reset_defaults(self):
        return dict(self._window.reset_hotkey_bindings() or {})

    def build_ui_hotkey_timer(self):
        return self._window._build_ui_hotkey_timer()

    def button_titles(self):
        return self._window._hotkey_button_titles()

    def supported_actions(self):
        return self._window._supported_ui_hotkey_actions()

    def dispatch_action(self, action):
        return self._window._dispatch_hotkey_action(action)

    def refresh_shortcuts(self):
        return self._window._refresh_hotkey_shortcuts()

    def poll_exact(self):
        return self._window._poll_exact_ui_hotkeys()

    def refresh_labels(self):
        return self._window._refresh_hotkey_labels()


class QtSensoryService:
    def __init__(self, window):
        self._window = window
        self._runtime_config = RuntimeConfigService(window)

    def _refresh_ui(self):
        if hasattr(self._window, "refresh_sensory_feedback_source_options"):
            selected_value = None
            try:
                selected_value = str(self._runtime_config.get("sensory_feedback_source", "off") or "off")
            except Exception:
                selected_value = None
            self._window.refresh_sensory_feedback_source_options(selected_value=selected_value)
        elif hasattr(self._window, "_refresh_sensory_feedback_source_tabs"):
            self._window._refresh_sensory_feedback_source_tabs()

    def notify_settings_changed(self) -> None:
        refresher = getattr(self._window, "_refresh_preset_dirty_state", None)
        if callable(refresher):
            refresher()
        saver = getattr(self._window, "save_session", None)
        if callable(saver):
            saver()

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
        provider = sensory.register_provider(
            provider_id=provider_id,
            label=label,
            instruction=instruction,
            description=description,
            order=order,
            capture_handler=capture_handler,
            metadata=metadata,
        )
        self._refresh_ui()
        return provider.to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        removed = bool(sensory.unregister_provider(provider_id))
        if removed and hasattr(self._window, "refresh_sensory_feedback_source_options"):
            self._window.refresh_sensory_feedback_source_options()
        return removed

    def list_providers(self):
        return [provider.to_summary() for provider in sensory.list_providers()]


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
        contributor = sensory.register_prompt_contributor(
            contributor_id=contributor_id,
            source_id=source_id,
            label=label,
            prompt=prompt,
            order=order,
            metadata=metadata,
        )
        return contributor.to_summary()

    def unregister_prompt_contributor(self, contributor_id: str) -> bool:
        removed = bool(sensory.unregister_prompt_contributor(contributor_id))
        return removed

    def list_prompt_contributors(self, source_id: str | None = None):
        return [item.to_summary() for item in sensory.list_prompt_contributors(source_id)]


class QtPromptRefinementService:
    """Narrow instruction-refinement port for addon-owned UI fields."""

    def __init__(self, window):
        self._refine = addon_runtime_operations(window).refine_instruction

    def refine(self, text: str, *, label: str = "Instruction", guidance: str = "") -> str:
        return str(
            self._refine(
                str(text or ""),
                label=str(label or "Instruction"),
                guidance=str(guidance or ""),
            )
            or ""
        )


class QtChatProviderService:
    exact_provider_version = 1

    @staticmethod
    def _verify_exact_provider(selection, provider_id, required):
        if required and (not provider_id or selection.provider_id != str(provider_id).strip().lower()):
            raise RuntimeError(f"Persona language model provider {provider_id!r} is unavailable.")

    def __init__(self, window):
        self._window = window
        operations = addon_runtime_operations(window)
        self._provider_config_snapshot = operations.provider_config_snapshot
        self._capture_provider_selection = operations.provider_capture_selection
        self._prepare_provider_request = operations.provider_prepare
        self._complete_provider_request = operations.provider_complete
        self._stream_provider_request = operations.provider_stream
        self._apply_provider_generation_fields = operations.provider_apply_generation_fields
        self._ensure_model_ready = operations.ensure_chat_provider_model_ready

    def _refresh_ui(self, selected_provider_id: str | None = None):
        if hasattr(self._window, "_populate_chat_provider_combo"):
            self._window._populate_chat_provider_combo(selected_provider_id)

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        description: str = "",
        order: int = 1000,
        client_factory=None,
        model_list_handler=None,
        completion_handler=None,
        stream_handler=None,
        connection_check_handler=None,
        api_key_getter=None,
        base_url_getter=None,
        metadata: dict | None = None,
        frozen_prepare_handler=None,
        frozen_completion_handler=None,
        frozen_stream_handler=None,
        model_capabilities_handler=None,
        frozen_model_lifecycle_handler=None,
        token_counter=None,
        frozen_private_config_getter=None,
        frozen_public_config_fields=None,
        normal_chat_capable: bool = True,
        frozen_execution_version: int | None = None,
    ):
        provider = chat_providers.register_provider(
            provider_id=provider_id,
            label=label,
            description=description,
            order=order,
            client_factory=client_factory,
            model_list_handler=model_list_handler,
            completion_handler=completion_handler,
            stream_handler=stream_handler,
            connection_check_handler=connection_check_handler,
            api_key_getter=api_key_getter,
            base_url_getter=base_url_getter,
            metadata=metadata,
            frozen_prepare_handler=frozen_prepare_handler,
            frozen_completion_handler=frozen_completion_handler,
            frozen_stream_handler=frozen_stream_handler,
            model_capabilities_handler=model_capabilities_handler,
            frozen_model_lifecycle_handler=frozen_model_lifecycle_handler,
            token_counter=token_counter,
            frozen_private_config_getter=frozen_private_config_getter,
            frozen_public_config_fields=frozen_public_config_fields,
            normal_chat_capable=normal_chat_capable,
            frozen_execution_version=frozen_execution_version,
        )
        self._refresh_ui(getattr(provider, "id", ""))
        return provider.to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        removed = bool(chat_providers.unregister_provider(provider_id))
        if removed:
            self._refresh_ui()
        return removed

    def list_providers(self):
        return [provider.to_summary() for provider in chat_providers.list_providers()]

    def get_provider_settings(self, provider_id: str | None = None):
        return chat_providers.get_provider_settings(provider_id)

    def get_provider_setting(self, provider_id: str, field_id: str):
        return chat_providers.get_provider_setting(provider_id, field_id)

    def complete(
        self,
        params,
        additional_params=None,
        *,
        provider_id=None,
        model_id=None,
        cancellation=None,
        use_generation_fields=False,
        require_exact_provider=False,
    ) -> str:
        from core.runtime.prompt_assembly import PromptRequest

        request_params = dict(params or {})
        requested_model = model_id
        if requested_model is None:
            requested_model = request_params.get("model")
        selection = self._capture_provider_selection(
            self._provider_config_snapshot(),
            provider_id=provider_id,
            model_id=requested_model,
        )
        self._verify_exact_provider(selection, provider_id, require_exact_provider)
        additional = dict(additional_params or {})
        if use_generation_fields:
            if not callable(self._apply_provider_generation_fields):
                raise RuntimeError("Provider generation-field capability is unavailable.")
            explicit_params = dict(request_params)
            explicit_additional = dict(additional)
            self._apply_provider_generation_fields(selection, request_params, additional)
            request_params.update(explicit_params)
            additional.update(explicit_additional)
        frozen = self._prepare_provider_request(
            selection,
            PromptRequest.from_payload(
                request_params,
                additional,
            ),
        )
        result = self._complete_provider_request(frozen, cancellation)
        if not result.accepted:
            failure = result.failure
            cause = getattr(failure, "cause", None)
            if isinstance(cause, BaseException):
                raise cause
            raise RuntimeError(getattr(failure, "message", "Provider completion failed."))
        return str(result.value or "")

    def stream(
        self,
        params,
        additional_params=None,
        *,
        provider_id=None,
        model_id=None,
        cancellation=None,
        use_generation_fields=False,
        require_exact_provider=False,
    ):
        if not callable(self._stream_provider_request):
            raise RuntimeError("Provider streaming capability is unavailable.")
        from core.runtime.prompt_assembly import PromptRequest

        request_params = dict(params or {})
        requested_model = model_id if model_id is not None else request_params.get("model")
        selection = self._capture_provider_selection(
            self._provider_config_snapshot(),
            provider_id=provider_id,
            model_id=requested_model,
        )
        self._verify_exact_provider(selection, provider_id, require_exact_provider)
        additional = dict(additional_params or {})
        if use_generation_fields:
            if not callable(self._apply_provider_generation_fields):
                raise RuntimeError("Provider generation-field capability is unavailable.")
            explicit_params = dict(request_params)
            explicit_additional = dict(additional)
            self._apply_provider_generation_fields(selection, request_params, additional)
            request_params.update(explicit_params)
            additional.update(explicit_additional)
        frozen = self._prepare_provider_request(
            selection,
            PromptRequest.from_payload(request_params, additional),
        )
        return self._stream_provider_request(frozen, cancellation)

    def structured_complete(
        self,
        params,
        response_model,
        *,
        additional_params=None,
        provider_id=None,
        model_id=None,
        cancellation=None,
    ):
        import json

        text = self.complete(
            params,
            additional_params,
            provider_id=provider_id,
            model_id=model_id,
            cancellation=cancellation,
        )
        payload = json.loads(text)
        validator = getattr(response_model, "model_validate", None)
        if callable(validator):
            value = validator(payload)
            exporter = getattr(value, "model_dump", None)
            return exporter() if callable(exporter) else payload
        parser = getattr(response_model, "parse_obj", None)
        if callable(parser):
            value = parser(payload)
            exporter = getattr(value, "dict", None)
            return exporter() if callable(exporter) else payload
        return payload

    def ensure_model_ready(self, provider_id: str, model_id: str) -> bool:
        return bool(self._ensure_model_ready(str(provider_id or ""), str(model_id or "")))


class QtAvatarProviderService:
    def __init__(self, window):
        self._window = window

    def _refresh_ui(self, selected_provider_id: str | None = None):
        refresh = getattr(self._window, "refresh_avatar_engine_options", None)
        if callable(refresh):
            refresh(selected_provider_id=selected_provider_id)

    def register_provider(
        self,
        *,
        provider_id: str,
        label: str,
        factory,
        description: str = "",
        order: int = 1000,
        metadata: dict | None = None,
        construction_input_type: type | None = None,
    ):
        provider = avatar_runtime.register_provider(
            provider_id=provider_id,
            label=label,
            factory=factory,
            description=description,
            order=order,
            metadata=metadata,
            construction_input_type=construction_input_type,
        )
        self._refresh_ui(getattr(provider, "id", ""))
        return provider.to_summary()

    def unregister_provider(self, provider_id: str) -> bool:
        removed = bool(avatar_runtime.unregister_provider(provider_id))
        if removed:
            self._refresh_ui()
        return removed

    def list_providers(self):
        return [provider.to_summary() for provider in avatar_runtime.list_providers()]


class QtChatReplayService:
    def __init__(self, window):
        self._window = window
        operations = addon_runtime_operations(window)
        self._snapshot_chat_session = operations.snapshot_chat_session
        self._replayable_chat_entries = operations.replayable_chat_entries
        self._replayable_chat_messages = operations.replayable_chat_messages
        self._replayable_assistant_entries = operations.replayable_assistant_entries
        self._replayable_assistant_messages = operations.replayable_assistant_messages
        self._build_replay_action = operations.build_replay_session_action

    def snapshot_chat_session(self):
        return dict(self._snapshot_chat_session() or {})

    def replayable_chat_entries(self):
        return list(self._replayable_chat_entries() or [])

    def replayable_chat_messages(self):
        return list(self._replayable_chat_messages() or [])

    def replayable_assistant_entries(self):
        return list(self._replayable_assistant_entries() or [])

    def replayable_assistant_messages(self):
        return list(self._replayable_assistant_messages() or [])

    def is_engine_running(self) -> bool:
        return _runtime_running(self._window)

    def is_offline_replay_only(self) -> bool:
        checker = getattr(self._window, "_engine_is_offline_replay_only", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                return False
        return False

    def trigger_control_action(self, action: str) -> None:
        self._window.trigger_control_action(str(action or "").strip())

    def replay_latest_reply(self) -> None:
        self.trigger_control_action("replay_last_assistant")

    def replay_chat_session(self) -> None:
        self.trigger_control_action("replay_chat_session")

    def replay_chat_session_from_index(self, start_index: int) -> None:
        action = str(self._build_replay_action(int(start_index)) or "").strip()
        if action:
            self.trigger_control_action(action)

    def load_chat_context(self) -> None:
        self._window.load_chat_context()

    def quick_load_chat_context(self) -> None:
        self._window.quick_load_chat_context()

    def save_chat_context(self) -> None:
        self._window.save_chat_context()

    def save_chat_context_as(self) -> None:
        handler = getattr(self._window, "save_chat_context_as", None)
        if callable(handler):
            handler()

    def quick_save_chat_context(self) -> None:
        self._window.quick_save_chat_context()


class AddonCapabilityBridgeService:
    def __init__(self, manager_getter):
        self._manager_getter = manager_getter

    def invoke(self, capability: str, payload=None):
        manager = self._manager_getter()
        if manager is None:
            return None
        return manager.invoke_capability(str(capability or ""), dict(payload or {}))


class QtFileTranscriptionService:
    """Finite addon port for transcription of one existing local file."""

    def __init__(self, _window=None):
        self._transcribe = addon_runtime_operations(_window).transcribe_file
        self._prepare = addon_runtime_operations(_window).prepare_transcription

    def ensure_ready(self) -> bool:
        if not callable(self._prepare):
            raise RuntimeError("STT initialization is unavailable from this host.")
        return bool(self._prepare())

    def transcribe(self, path: str, *, language: str | None = None):
        return _project_stt_value(self._transcribe(str(path), language=language))


def _project_runtime_data(value):
    if value is None or isinstance(value, (str, bytes, int, float, bool, Path)):
        return value
    if isinstance(value, dict):
        return {
            _project_runtime_data(key): _project_runtime_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_project_runtime_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_project_runtime_data(item) for item in value)
    if isinstance(value, set):
        return {_project_runtime_data(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_project_runtime_data(item) for item in value)
    raise TypeError(f"Runtime capability returned unsupported data: {type(value).__name__}")


def _project_stt_value(value):
    try:
        return _project_runtime_data(value)
    except TypeError:
        text = getattr(value, "text", None)
        if text is not None:
            return {"text": str(text or "")}
        try:
            return tuple(_project_stt_value(item) for item in iter(value))
        except TypeError:
            return {}


class QtAcceptedTurnService:
    def __init__(self, _window=None):
        self._submit = addon_runtime_operations(_window).submit_accepted_turn

    def submit(self, text: str, *, role: str = "user", metadata=None):
        return dict(
            _project_runtime_data(self._submit(
                str(text or ""),
                role=str(role or "user"),
                metadata=dict(metadata or {}),
            ))
            or {}
        )


class QtSpeechPlaybackService:
    def __init__(self, _window=None, *, release_idle_models=None):
        operations = addon_runtime_operations(_window)
        self._window = _window
        self._operations = operations
        self._release_idle_models = release_idle_models
        self._snapshot = operations.speech_snapshot
        self._set_paused = operations.set_speech_paused
        self._interrupt = operations.interrupt_speech
        self._ensure_ready = operations.ensure_speech_ready
        self._speak = operations.speak

    def snapshot(self):
        return dict(self._snapshot() or {})

    def set_paused(self, paused: bool) -> bool:
        return bool(self._set_paused(bool(paused)))

    def interrupt(self, *, reason: str = "addon", cancel_llm_streams: bool = False):
        return dict(
            self._interrupt(
                reason=str(reason or "addon"),
                cancel_llm_streams=bool(cancel_llm_streams),
            )
            or {}
        )

    def ensure_ready(self) -> bool:
        return bool(self._ensure_ready())

    def runtime_config(self):
        return dict(RuntimeConfigService(self._window).snapshot() or {})

    def release_idle_models(self):
        if self._release_idle_models is None:
            return {'ok': True, 'unloaded': 0}
        return dict(self._release_idle_models())

    def engine_loaded(self) -> bool:
        return bool(self.snapshot().get("ready", False))

    def init_tts(self) -> bool:
        return self.ensure_ready()

    def tts_seed(self) -> int:
        return int(self.runtime_config().get("tts_seed", 0) or 0)

    def set_seed(self, seed: int):
        return self._operations.set_seed(int(seed))

    def tts_generation_kwargs(self):
        config = self.runtime_config()
        top_p = config.get("tts_top_p", 0.9)
        top_k = config.get("tts_top_k", 40)
        return {
            "temperature": float(config.get("tts_temperature", 0.8) or 0.8),
            "top_p": float(0.9 if top_p is None or top_p == "" else top_p),
            "top_k": int(40 if top_k is None or top_k == "" else top_k),
            "repetition_penalty": float(config.get("tts_repeat_penalty", 1.2) or 1.2),
            "norm_loudness": bool(config.get("tts_normalize_loudness", False)),
        }

    def intelligent_chunk_text(self, text: str, target_chars: int, max_chars: int):
        return tuple(self._operations.chunk_text(str(text), int(target_chars), int(max_chars)))

    def generate_tts(self, text: str, **kwargs):
        return self._operations.generate_tts(str(text), **dict(kwargs))

    def tts_sample_rate(self, default: int = 24000) -> int:
        return int(self._operations.tts_sample_rate(int(default)))

    def save_tts_wav(self, path: str, wav, sample_rate: int):
        return self._operations.save_wav(str(path), wav, int(sample_rate))

    def speak(
        self,
        text: str,
        *,
        segments=None,
        voice_path: str | None = None,
        runtime_config_override=None,
    ):
        return self._speak(
            str(text or ""),
            text_iterable=None if segments is None else tuple(segments),
            voice_path_override=voice_path,
            runtime_config_override=(
                None
                if runtime_config_override is None
                else dict(runtime_config_override)
            ),
        )


class QtCompanionOrbRuntimeService:
    def __init__(self, _window=None):
        operations = addon_runtime_operations(_window)
        self._busy = operations.orb_busy_snapshot
        self._extract = operations.orb_extract_selected_text
        self._ground_region = operations.orb_ground_region
        self._generate_visual_guidance = operations.orb_generate_visual_guidance
        self._release_vision_model = operations.orb_release_vision_model
        self._ensure_vision_model = operations.orb_ensure_vision_model
        self._observe_visual = operations.orb_observe_visual
        self._watch_scope = getattr(operations, 'orb_conversation_scope', None)
        self._watch_intent = getattr(operations, 'orb_interpret_watch_intent', None)
        self._watch_observe = getattr(operations, 'orb_observe_watch', None)
        self._record_communication = getattr(operations, 'orb_record_communication', None)
        self._comment = operations.orb_ephemeral_comment
        self._proactive = operations.orb_submit_proactive
        self._sensory_cycle = operations.orb_run_sensory_cycle
        self._generate_drop_guidance = operations.orb_generate_drop_guidance
        self._format_drop_guidance = operations.orb_format_drop_guidance

    def conversation_scope(self):
        if not callable(self._watch_scope):
            return {'available': False}
        return dict(self._watch_scope())

    def interpret_watch_intent(self, **kwargs):
        if not callable(self._watch_intent):
            raise RuntimeError('Orb watch interpretation is unavailable.')
        return dict(self._watch_intent(**kwargs))

    def observe_watch(self, **kwargs):
        if not callable(self._watch_observe):
            raise RuntimeError('Orb watch observation is unavailable.')
        return dict(self._watch_observe(**kwargs))

    def record_communication(self, **kwargs):
        if callable(self._record_communication):
            return self._record_communication(**kwargs)

    def busy_snapshot(self):
        return dict(self._busy() or {})

    def extract_selected_text(self, image_path: str, *, screen_bounds=()):
        return str(
            self._extract(
                image_path=str(image_path),
                screen_bounds=list(screen_bounds),
            )
            or ""
        )

    def ground_region(
        self,
        image_path: str,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "auto_load",
        capture_bounds=(),
        gaze_point=(),
    ):
        return dict(
            self._ground_region(
                image_path=str(image_path),
                provider_id=str(provider_id or ""),
                model_id=str(model_id or ""),
                base_url=str(base_url or ""),
                model_handling=str(model_handling or "auto_load"),
                capture_bounds=list(capture_bounds),
                gaze_point=list(gaze_point),
            )
            or {}
        )

    def generate_visual_guidance(
        self,
        image_path: str,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "auto_load",
        restore_main_model: bool = False,
        reaction_scope: str = "gaze",
    ):
        result = self._generate_visual_guidance(
            image_path=str(image_path),
            provider_id=str(provider_id or ""),
            model_id=str(model_id or ""),
            base_url=str(base_url or ""),
            model_handling=str(model_handling or "auto_load"),
            restore_main_model=bool(restore_main_model),
            reaction_scope=str(reaction_scope or "gaze"),
        )
        return _project_runtime_data(dict(result or {}))

    def release_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ) -> bool:
        return bool(
            self._release_vision_model(
                provider_id=str(provider_id or ""),
                model_id=str(model_id or ""),
                base_url=str(base_url or ""),
                model_handling=str(model_handling or "parallel_pinned"),
            )
        )

    def ensure_vision_model(
        self,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
    ):
        if self._ensure_vision_model is None:
            raise RuntimeError("Companion Orb vision residency is unavailable.")
        return dict(
            self._ensure_vision_model(
                provider_id=str(provider_id or ""),
                model_id=str(model_id or ""),
                base_url=str(base_url or ""),
                model_handling=str(model_handling or "parallel_pinned"),
            )
            or {}
        )

    def observe_visual(
        self,
        image_path: str,
        *,
        provider_id: str,
        model_id: str,
        base_url: str = "",
        model_handling: str = "parallel_pinned",
        capture_bounds=(),
        reaction_scope: str = "gaze",
        capability_mode: str = "auto",
        target_text: str = "",
        question_text: str = "",
        timeout_seconds: float = 15.0,
        cancel_token=None,
        trace_id: str = "",
    ):
        if self._observe_visual is None:
            raise RuntimeError("Companion Orb unified vision is unavailable.")
        result = self._observe_visual(
            image_path=str(image_path),
            provider_id=str(provider_id or ""),
            model_id=str(model_id or ""),
            base_url=str(base_url or ""),
            model_handling=str(model_handling or "parallel_pinned"),
            capture_bounds=list(capture_bounds),
            reaction_scope=str(reaction_scope or "gaze"),
            capability_mode=str(capability_mode or "auto"),
            target_text=str(target_text or ""),
            question_text=str(question_text or ""),
            timeout_seconds=float(timeout_seconds),
            cancel_token=cancel_token,
            trace_id=str(trace_id or ""),
        )
        return _project_runtime_data(dict(result or {}))

    def ephemeral_comment(self, **request):
        return str(self._comment(**dict(request)) or "")

    def submit_proactive(self, text: str, **request) -> bool:
        return bool(self._proactive(str(text or ""), **dict(request)))

    def run_sensory_cycle(self, **request) -> bool:
        return bool(self._sensory_cycle(**dict(request)))

    def drop_guidance(self, **request):
        payload = dict(request)
        guidance = payload.pop("guidance", None)
        if guidance is None:
            guidance = self._generate_drop_guidance(**payload)
        return {
            "guidance": _project_runtime_data(dict(guidance or {})),
            "text": str(self._format_drop_guidance(guidance) or ""),
        }


class QtAudioStoryRuntimeService:
    """Finite Audio Story audio/config port with no callback registry exposure."""

    def __init__(self, window=None):
        from pydub import AudioSegment

        self._audio_segment = AudioSegment
        self._config = RuntimeConfigService(window)
        self._transcription = QtFileTranscriptionService(window)
        self._speech = QtSpeechPlaybackService(window)
        operations = addon_runtime_operations(window)
        self._chunk_limits = operations.text_chunk_limits
        self._chunk_text = operations.chunk_text
        self._set_seed = operations.set_seed
        self._generate_tts = operations.generate_tts
        self._save_wav = operations.save_wav
        self._safe_delete = operations.safe_delete
        self._sample_rate = operations.tts_sample_rate

    def runtime_config(self):
        return dict(self._config.snapshot() or {})

    def runtime_config_value(self, key: str, default=None):
        return self._config.get(str(key), default)

    def update_runtime_config(self, key: str, value):
        return self._config.update(str(key), value)

    def engine_loaded(self) -> bool:
        return bool(self._speech.snapshot().get("ready", False))

    def ensure_stt_ready(self) -> bool:
        return True

    def transcribe_audio(self, path: str):
        return self._transcription.transcribe(str(path))

    def init_tts(self) -> bool:
        return self._speech.ensure_ready()

    def audio_from_file(self, path: str):
        return self._audio_segment.from_file(str(path))

    def audio_from_wav(self, path: str):
        return self._audio_segment.from_wav(str(path))

    def audio_silent(self, duration: int = 0):
        return self._audio_segment.silent(duration=int(duration))

    def audio_duration_seconds(self, path: str) -> float:
        return float(self.audio_from_file(path).duration_seconds or 0.0)

    def get_text_chunk_limits(self):
        return tuple(self._chunk_limits())

    def intelligent_chunk_text(self, text: str, target_chars: int, max_chars: int):
        return tuple(self._chunk_text(str(text), int(target_chars), int(max_chars)))

    def tts_sample_rate(self, default: int = 24000) -> int:
        return int(self._sample_rate(int(default)))

    def tts_voice_path(self) -> str:
        path = str(self.runtime_config_value("voice_path", "") or "").strip()
        return path if not path or Path(path).exists() else ""

    def tts_seed(self) -> int:
        return int(self.runtime_config_value("tts_seed", 0) or 0)

    def set_seed(self, seed: int):
        return self._set_seed(int(seed))

    def tts_generation_kwargs(self):
        top_p = self.runtime_config_value("tts_top_p", 0.9)
        top_k = self.runtime_config_value("tts_top_k", 40)
        return {
            "temperature": float(self.runtime_config_value("tts_temperature", 0.8) or 0.8),
            "top_p": float(0.9 if top_p is None or top_p == "" else top_p),
            "top_k": int(40 if top_k is None or top_k == "" else top_k),
            "repetition_penalty": float(self.runtime_config_value("tts_repeat_penalty", 1.2) or 1.2),
            "norm_loudness": bool(self.runtime_config_value("tts_normalize_loudness", False)),
        }

    def tts_settings_snapshot(self):
        top_p = self.runtime_config_value("tts_top_p", 0.9)
        top_k = self.runtime_config_value("tts_top_k", 40)
        return {
            "backend": str(self.runtime_config_value("tts_backend", "chatterbox") or "chatterbox"),
            "voice_path": str(self.runtime_config_value("voice_path", "") or ""),
            "tts_seed": self.tts_seed(),
            "tts_temperature": float(self.runtime_config_value("tts_temperature", 0.8) or 0.8),
            "tts_top_p": float(0.9 if top_p is None or top_p == "" else top_p),
            "tts_top_k": int(40 if top_k is None or top_k == "" else top_k),
            "tts_repeat_penalty": float(self.runtime_config_value("tts_repeat_penalty", 1.2) or 1.2),
            "tts_min_p": float(self.runtime_config_value("tts_min_p", 0.0) or 0.0),
            "tts_normalize_loudness": bool(self.runtime_config_value("tts_normalize_loudness", False)),
        }

    def generate_tts(self, text: str, **kwargs):
        return self._generate_tts(str(text), **dict(kwargs))

    def save_tts_wav(self, path: str, wav, sample_rate: int):
        return self._save_wav(str(path), wav, int(sample_rate))

    def safe_delete(self, path: str):
        return self._safe_delete(str(path))
