from __future__ import annotations

from pathlib import Path

from core import avatar_runtime, sensory, chat_providers
import shared_state
from PySide6 import QtCore, QtGui, QtWidgets


class QtDialogService:
    _last_directory: Path | None = None

    def __init__(self, window):
        self._window = window

    @classmethod
    def _resolve_start_dir(cls, start_dir: str | Path | None) -> str:
        if cls._last_directory is not None and cls._last_directory.exists():
            return str(cls._last_directory)
        candidate = Path(str(start_dir or "").strip() or Path.cwd())
        if candidate.is_file():
            candidate = candidate.parent
        return str(candidate if candidate.exists() else Path.cwd())

    @classmethod
    def _remember_path(cls, selected_path: str | Path | None) -> None:
        raw = str(selected_path or "").strip()
        if not raw:
            return
        try:
            candidate = Path(raw)
            remember = candidate if candidate.is_dir() else candidate.parent
            if remember.exists():
                cls._last_directory = remember.resolve()
        except Exception:
            pass

    def open_file(self, title: str, start_dir: str, file_filter: str):
        start = self._resolve_start_dir(start_dir)
        path, selected_filter = QtWidgets.QFileDialog.getOpenFileName(self._window, str(title), start, str(file_filter))
        self._remember_path(path)
        return path, selected_filter

    def save_file(self, title: str, start_path: str, file_filter: str):
        start = self._resolve_start_dir(start_path)
        path, selected_filter = QtWidgets.QFileDialog.getSaveFileName(self._window, str(title), start, str(file_filter))
        self._remember_path(path)
        return path, selected_filter

    def open_directory(self, title: str, start_dir: str):
        start = self._resolve_start_dir(start_dir)
        path = QtWidgets.QFileDialog.getExistingDirectory(self._window, str(title), start)
        self._remember_path(path)
        return path

    def warning(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.warning(self._window, str(title), str(message))

    def information(self, title: str, message: str) -> None:
        QtWidgets.QMessageBox.information(self._window, str(title), str(message))


class QtShellService:
    def __init__(self, window):
        self._window = window

    def open_local_path(self, path) -> bool:
        return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(Path(path).resolve())))

    def notify_settings_changed(self) -> None:
        if hasattr(self._window, "_refresh_preset_dirty_state"):
            self._window._refresh_preset_dirty_state()
        if hasattr(self._window, "save_session"):
            self._window.save_session()


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
        self._window = window

    def _combo(self, name: str):
        return getattr(self._window, str(name), None)

    def _spin(self, name: str):
        return getattr(self._window, str(name), None)

    def _checkbox(self, name: str):
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
        if widget is None or not hasattr(widget, "setCurrentText"):
            return
        text = str(value or "").strip()
        if not text:
            return
        try:
            widget.setCurrentText(text)
        except Exception:
            pass

    def _set_spin_value(self, name: str, value) -> None:
        widget = self._spin(name)
        if widget is None or not hasattr(widget, "setValue"):
            return
        try:
            widget.setValue(value)
        except Exception:
            pass

    def _set_checked(self, name: str, value) -> None:
        widget = self._checkbox(name)
        if widget is None or not hasattr(widget, "setChecked"):
            return
        try:
            widget.setChecked(bool(value))
        except Exception:
            pass

    def snapshot(self):
        import engine

        runtime = getattr(engine, "RUNTIME_CONFIG", {}) or {}
        overflow_label_fn = getattr(self._window, "_chat_overflow_policy_label_from_value", None)
        overflow_label = (
            overflow_label_fn(runtime.get("chat_context_overflow_policy", "rolling_window"))
            if callable(overflow_label_fn)
            else str(runtime.get("chat_context_overflow_policy", "rolling_window") or "rolling_window")
        )
        return {
            "audio_input_device": self._combo_text("audio_input_device_combo", "Default Input"),
            "audio_output_device": self._combo_text("audio_output_device_combo", "Default Output"),
            "audio_input_options": self._combo_items("audio_input_device_combo") or ["Default Input"],
            "audio_output_options": self._combo_items("audio_output_device_combo") or ["Default Output"],
            "input_mode": self._combo_text("input_mode_combo", str(runtime.get("input_mode", "Voice Activation") or "Voice Activation")),
            "input_role": self._combo_text("input_role_combo", str(runtime.get("input_message_role", "User Message") or "User Message")),
            "stream_mode": self._combo_text("stream_mode_combo", "On" if bool(runtime.get("stream_mode", False)) else "Off"),
            "allow_proactive_replies": self._checked("allow_proactive_checkbox", bool(runtime.get("allow_proactive_replies", True))),
            "require_first_user_before_proactive": self._checked("require_first_user_checkbox", bool(runtime.get("require_first_user_before_proactive", False))),
            "listen_idle_window_seconds": float(self._spin_value("listen_idle_window_spin", float(runtime.get("listen_idle_window_seconds", 5.0) or 5.0))),
            "proactive_delay_seconds": float(self._spin_value("proactive_delay_spin", float(runtime.get("proactive_delay_seconds", 10.0) or 10.0))),
            "chat_context_window_messages": int(self._spin_value("chat_context_window_spin", int(runtime.get("chat_context_window_messages", 20) or 20))),
            "stored_chat_history_limit": int(self._spin_value("stored_chat_history_limit_spin", int(runtime.get("stored_chat_history_limit", 0) or 0))),
            "chat_context_overflow_policy": self._combo_text("chat_overflow_policy_combo", overflow_label),
            "limit_response_length": self._checked("limit_response_checkbox", bool(runtime.get("limit_response_length", False))),
            "max_response_tokens": int(self._spin_value("max_response_tokens_spin", int(runtime.get("max_response_tokens", 600) or 600))),
            "shell_mode": False,
            "message": "Input/session settings are available.",
            "source": "qt_app",
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
            label_fn = getattr(self._window, "_input_role_label_from_value", None)
            self._set_combo_text("input_role_combo", label_fn(value) if callable(label_fn) else value)
        if "stream_mode" in payload:
            value = payload.get("stream_mode")
            label = "On" if bool(value) and str(value).strip().lower() not in {"off", "false", "0"} else "Off"
            if isinstance(value, str) and value.strip():
                label = value
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
            value = payload.get("chat_context_overflow_policy")
            label_fn = getattr(self._window, "_chat_overflow_policy_label_from_value", None)
            self._set_combo_text("chat_overflow_policy_combo", label_fn(value) if callable(label_fn) else value)
        if "limit_response_length" in payload:
            self._set_checked("limit_response_checkbox", payload.get("limit_response_length"))
        if "max_response_tokens" in payload:
            self._set_spin_value("max_response_tokens_spin", int(payload.get("max_response_tokens") or 600))
        return self.snapshot()


class QtInputActionService:
    AUDIO_STORY_PREVIEW_TOTAL_SECONDS = 60

    def __init__(self, window):
        self._window = window
        self._last_action = ""
        self._push_to_talk_held = False

    def _widget(self, name: str):
        widget = getattr(self._window, str(name), None)
        if widget is not None:
            return widget
        if hasattr(self._window, "findChild"):
            try:
                return self._window.findChild(QtCore.QObject, str(name))
            except Exception:
                return None
        return None

    def _combo_text(self, name: str, default: str = "") -> str:
        widget = self._widget(name)
        if widget is not None and hasattr(widget, "currentText"):
            try:
                text = str(widget.currentText() or "").strip()
                if text:
                    return text
            except Exception:
                pass
        return str(default or "").strip()

    def _line_value(self, name: str, default: str = "") -> str:
        widget = self._widget(name)
        if widget is not None and hasattr(widget, "text"):
            try:
                return str(widget.text() or "").strip()
            except Exception:
                pass
        return str(default or "").strip()

    def _slider_value(self, name: str, default: int = 0) -> int:
        widget = self._widget(name)
        if widget is not None and hasattr(widget, "value"):
            try:
                return int(widget.value())
            except Exception:
                pass
        return int(default)

    def _format_clock_seconds(self, seconds: int) -> str:
        total = max(0, int(seconds or 0))
        minutes, secs = divmod(total, 60)
        return f"{minutes:02d}:{secs:02d}"

    def _push_to_talk_enabled(self) -> bool:
        input_mode = self._combo_text("input_mode_combo", "Voice Activation")
        dry_run_active = False
        dry_run_check = getattr(self._window, "_dry_run_is_active", None)
        if callable(dry_run_check):
            try:
                dry_run_active = bool(dry_run_check())
            except Exception:
                dry_run_active = False
        running = bool(getattr(self._window, "thread", None) and self._window.thread.is_alive())
        return running and input_mode == "Push-to-Talk" and not dry_run_active

    def snapshot(self):
        try:
            import engine
            push_to_talk_hotkey = str(engine.get_push_to_talk_hotkey() or "Right Ctrl").strip() or "Right Ctrl"
        except Exception:
            push_to_talk_hotkey = "Right Ctrl"
        push_enabled = self._push_to_talk_enabled()
        if not push_enabled:
            self._push_to_talk_held = False
        audio_path = self._line_value("audio_file_path_edit", "")
        seek_percent = max(0, min(100, self._slider_value("audio_story_seek_slider", 0)))
        total_seconds = int(self.AUDIO_STORY_PREVIEW_TOTAL_SECONDS)
        current_seconds = int(round(total_seconds * seek_percent / 100.0))
        return {
            "last_action": self._last_action,
            "push_to_talk_enabled": push_enabled,
            "push_to_talk_held": bool(self._push_to_talk_held and push_enabled),
            "push_to_talk_hotkey": push_to_talk_hotkey,
            "audio_story_audio_path": audio_path,
            "audio_story_has_audio": bool(audio_path),
            "audio_story_playback_mode": self._combo_text("audio_story_playback_combo", "Play Imported Audio"),
            "audio_story_transcribe_seconds": max(1, self._slider_value("transcribe_seconds_slider", 8)),
            "audio_story_playback_state": "unavailable",
            "audio_story_seek_percent": seek_percent,
            "audio_story_position_text": f"{self._format_clock_seconds(current_seconds)} / {self._format_clock_seconds(total_seconds)}",
            "shell_mode": False,
            "push_to_talk_runtime_available": True,
            "audio_story_runtime_available": self._widget("transcribe_audio_button") is not None,
            "message": "Input/runtime-adjacent actions are available when the owning UI/runtime exists.",
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
            import engine
            engine.set_push_to_talk_hold(bool(held))
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

    def set_audio_file_path(self, path: str):
        self._last_action = "set_audio_file_path"
        widget = self._widget("audio_file_path_edit")
        accepted = False
        if widget is not None and hasattr(widget, "setText"):
            try:
                widget.setText(str(path or "").strip())
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio Story path updated." if accepted else "Audio Story path field is unavailable in this UI mode.",
        })
        return payload

    def request_audio_import(self):
        self._last_action = "request_audio_import"
        payload = self.snapshot()
        payload.update({
            "accepted": False,
            "deferred": True,
            "message": "Audio import remains owned by the runtime Audio Story surface.",
        })
        return payload

    def request_audio_transcription(self):
        self._last_action = "request_audio_transcription"
        button = self._widget("transcribe_audio_button")
        accepted = False
        if button is not None and hasattr(button, "click"):
            try:
                button.click()
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio transcription requested." if accepted else "Audio transcription is unavailable in this UI mode.",
        })
        return payload

    def play_audio_story(self):
        self._last_action = "play_audio_story"
        button = self._widget("audio_story_play_button")
        accepted = False
        if button is not None and hasattr(button, "click"):
            try:
                button.click()
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio Story play requested." if accepted else "Audio Story play is unavailable in this UI mode.",
        })
        return payload

    def pause_audio_story(self):
        self._last_action = "pause_audio_story"
        button = self._widget("audio_story_pause_button")
        accepted = False
        if button is not None and hasattr(button, "click"):
            try:
                button.click()
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio Story pause requested." if accepted else "Audio Story pause is unavailable in this UI mode.",
        })
        return payload

    def stop_audio_story(self):
        self._last_action = "stop_audio_story"
        button = self._widget("audio_story_stop_button")
        accepted = False
        if button is not None and hasattr(button, "click"):
            try:
                button.click()
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio Story stop requested." if accepted else "Audio Story stop is unavailable in this UI mode.",
        })
        return payload

    def seek_audio_story(self, position_percent: int):
        self._last_action = "seek_audio_story"
        slider = self._widget("audio_story_seek_slider")
        accepted = False
        if slider is not None and hasattr(slider, "setValue"):
            try:
                slider.setValue(max(0, min(100, int(position_percent or 0))))
                accepted = True
            except Exception:
                accepted = False
        payload = self.snapshot()
        payload.update({
            "accepted": accepted,
            "message": "Audio Story seek updated." if accepted else "Audio Story seek is unavailable in this UI mode.",
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
    _VAM_STATE_KEYS = (
        "vam_root",
        "vam_bridge_root",
        "vam_target_atom_uid",
        "vam_target_storable_id",
        "vam_vmc_host",
        "vam_vmc_port",
        "vam_vmc_enabled",
        "vam_bridge_enabled",
        "vam_play_audio_in_vam",
        "vam_timeline_auto_resume",
    )

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
            "vam_settings": {
                "vam_root": self._line_value("vam_root_edit"),
                "vam_bridge_root": self._line_value("vam_bridge_root_edit"),
                "vam_target_atom_uid": self._line_value("vam_target_atom_uid_edit", "Person"),
                "vam_target_storable_id": self._line_value("vam_target_storable_id_edit"),
                "vam_vmc_host": self._line_value("vam_vmc_host_edit", "127.0.0.1"),
                "vam_vmc_port": int(getattr(self._window, "vam_vmc_port_spin", None).value()) if hasattr(getattr(self._window, "vam_vmc_port_spin", None), "value") else 39539,
                "vam_vmc_enabled": self._checked("vam_vmc_enabled_checkbox", True),
                "vam_bridge_enabled": self._checked("vam_bridge_enabled_checkbox", True),
                "vam_play_audio_in_vam": self._checked("vam_play_audio_in_vam_checkbox", False),
                "vam_timeline_auto_resume": self._checked("vam_timeline_auto_resume_checkbox", True),
            },
            "shell_mode": False,
            "message": "Persona/body/VaM controls are available.",
            "source": "qt_app",
        }

    def export_vam_settings(self):
        return dict(self.snapshot().get("vam_settings", {}) or {})

    def _set_line_text_quietly(self, name: str, text: str):
        widget = self._line_edit(name)
        if widget is None or not hasattr(widget, "setText"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_checkbox_quietly(self, name: str, checked: bool):
        widget = self._checkbox(name)
        if widget is None or not hasattr(widget, "setChecked"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setChecked(bool(checked))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_spin_value_quietly(self, name: str, value: int):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setValue"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setValue(int(value))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def import_vam_settings(self, payload):
        import engine

        data = dict(payload or {})
        if not any(key in data for key in self._VAM_STATE_KEYS):
            return None

        raw_root = data.get("vam_root") or data.get("vam_bridge_root") or getattr(engine, "DEFAULT_VAM_ROOT", "")
        normalized_root = engine.normalize_vam_root(raw_root)
        bridge_root = engine.derive_vam_bridge_root(normalized_root)
        state = {
            "vam_root": normalized_root,
            "vam_bridge_root": bridge_root,
            "vam_target_atom_uid": str(data.get("vam_target_atom_uid", "Person") or "Person").strip() or "Person",
            "vam_target_storable_id": str(data.get("vam_target_storable_id", "plugin#0_NeuralCompanionBridge") or "plugin#0_NeuralCompanionBridge").strip(),
            "vam_vmc_host": str(data.get("vam_vmc_host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1",
            "vam_vmc_port": int(data.get("vam_vmc_port", 39539) or 39539),
            "vam_vmc_enabled": bool(data.get("vam_vmc_enabled", True)),
            "vam_bridge_enabled": bool(data.get("vam_bridge_enabled", True)),
            "vam_play_audio_in_vam": bool(data.get("vam_play_audio_in_vam", False)),
            "vam_timeline_auto_resume": bool(data.get("vam_timeline_auto_resume", True)),
        }
        for key, value in state.items():
            engine.update_runtime_config(key, value)

        self._set_line_text_quietly("vam_root_edit", state["vam_root"])
        self._set_line_text_quietly("vam_bridge_root_edit", state["vam_bridge_root"])
        self._set_line_text_quietly("vam_target_atom_uid_edit", state["vam_target_atom_uid"])
        self._set_line_text_quietly("vam_target_storable_id_edit", state["vam_target_storable_id"])
        self._set_line_text_quietly("vam_vmc_host_edit", state["vam_vmc_host"])
        self._set_spin_value_quietly("vam_vmc_port_spin", state["vam_vmc_port"])
        self._set_checkbox_quietly("vam_vmc_enabled_checkbox", state["vam_vmc_enabled"])
        self._set_checkbox_quietly("vam_bridge_enabled_checkbox", state["vam_bridge_enabled"])
        self._set_checkbox_quietly("vam_play_audio_in_vam_checkbox", state["vam_play_audio_in_vam"])
        self._set_checkbox_quietly("vam_timeline_auto_resume_checkbox", state["vam_timeline_auto_resume"])
        return None

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

    def launch_vam(self, target: str = "desktop"):
        mode = str(target or "desktop").strip().lower()
        if mode == "vr":
            launch = getattr(self._window, "on_start_vam_vr_clicked", None)
        else:
            launch = getattr(self._window, "on_start_vam_desktop_clicked", None)
        if callable(launch):
            launch()
        return self.snapshot()

    def open_external_avatar_view(self, mode: str = "vseeface"):
        value = str(mode or "vseeface").strip().lower()
        if value == "vam":
            handler = getattr(self._window, "enter_external_avatar_focus", None)
            if callable(handler):
                handler("VaM")
        else:
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
        thread = getattr(self._window, "thread", None)
        running = bool(thread and thread.is_alive())
        runtime_status = {}
        if hasattr(self._window, "build_runtime_status_snapshot"):
            try:
                runtime_status = self._window.build_runtime_status_snapshot().to_dict()
            except Exception:
                runtime_status = {}
        return {
            "running": running,
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
        "regenerate_response",
        "retry_user_input",
        "pause_speech",
        "skip_speech",
        "skip_user_reply",
        "replay_last_assistant",
        "replay_chat_session",
    )

    def __init__(self, window):
        self._window = window
        self._last_action = ""

    def snapshot(self):
        return {
            "actions": list(self.SUPPORTED_ACTIONS),
            "last_action": self._last_action,
            "shell_mode": False,
            "runtime_connected": bool(getattr(self._window, "thread", None) and self._window.thread.is_alive()),
            "message": "Runtime control actions are available.",
            "source": "qt_app",
        }

    def trigger(self, action: str):
        action_key = str(action or "").strip()
        accepted = False
        if action_key:
            trigger = getattr(self._window, "trigger_control_action", None)
            if callable(trigger):
                trigger(action_key)
                self._last_action = action_key
                accepted = True
        return {**self.snapshot(), "accepted": accepted, "action": action_key}


class QtChatContextService:
    def __init__(self, window):
        self._window = window
        self._last_action = ""

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
        import tutorial_framework

        return list(tutorial_framework.list_tutorials() or [])

    def load_tutorial(self, tutorial_id: str):
        import tutorial_framework

        return dict(tutorial_framework.load_tutorial(str(tutorial_id or "")) or {})

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

    def set_binding(self, action: str, binding: str):
        return self._window.set_hotkey_binding(str(action or "").strip(), str(binding or ""))

    def reset_defaults(self):
        return dict(self._window.reset_hotkey_bindings() or {})


class QtVisualReplyService:
    _STATE_KEYS = (
        "visual_reply_mode",
        "visual_reply_provider",
        "visual_reply_size",
        "visual_reply_model",
        "visual_reply_auto_show_dock",
    )

    def __init__(self, window):
        self._window = window

    def get_runtime_config(self, key, default=None):
        import engine

        return (getattr(engine, "RUNTIME_CONFIG", {}) or {}).get(str(key), default)

    def update_runtime_config(self, key, value):
        import engine

        return engine.update_runtime_config(str(key), value)

    def export_session_state(self):
        snapshot = self.settings_snapshot()
        return {
            "visual_reply_mode": str(snapshot.get("mode_value", "auto") or "auto"),
            "visual_reply_provider": str(snapshot.get("provider_value", "openai") or "openai"),
            "visual_reply_size": str(snapshot.get("size_value", "1024x1024") or "1024x1024"),
            "visual_reply_model": str(snapshot.get("model_name", "gpt-image-1") or "gpt-image-1"),
            "visual_reply_auto_show_dock": bool(snapshot.get("auto_show", True)),
        }

    def export_preset_state(self):
        return self.export_session_state()

    def _set_combo_text_quietly(self, widget, text):
        if widget is None:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setCurrentText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_widget_text_quietly(self, widget, text):
        if widget is None:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_checked_quietly(self, widget, checked):
        if widget is None:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setChecked(bool(checked))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _sync_core_widgets_from_runtime(self):
        window = self._window
        self._set_combo_text_quietly(
            getattr(window, "visual_reply_mode_combo", None),
            self.mode_label_from_value(self.get_runtime_config("visual_reply_mode", "auto")),
        )
        self._set_combo_text_quietly(
            getattr(window, "visual_reply_provider_combo", None),
            self.provider_label_from_value(self.get_runtime_config("visual_reply_provider", "openai")),
        )
        self._set_combo_text_quietly(
            getattr(window, "visual_reply_size_combo", None),
            self.size_label_from_value(self.get_runtime_config("visual_reply_size", "1024x1024")),
        )
        self._set_widget_text_quietly(
            getattr(window, "visual_reply_model_edit", None),
            str(self.get_runtime_config("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
        )
        self._set_checked_quietly(
            getattr(window, "visual_reply_auto_show_checkbox", None),
            bool(self.get_runtime_config("visual_reply_auto_show_dock", True)),
        )
        self.refresh_hint()

    def import_session_state(self, session):
        payload = dict(session or {})
        for key in self._STATE_KEYS:
            if key in payload:
                self.update_runtime_config(key, payload.get(key))
        if "visual_reply_mode" in payload:
            self.update_runtime_config("visual_replies_enabled", str(payload.get("visual_reply_mode") or "auto").strip().lower() != "off")
        self._sync_core_widgets_from_runtime()

    def import_preset_state(self, preset):
        return self.import_session_state(preset)

    def settings_snapshot(self):
        import engine

        runtime = getattr(engine, "RUNTIME_CONFIG", {}) or {}
        theme_presets = list(getattr(engine, "VISUAL_REPLY_STORY_THEME_PRESETS", ()) or ())
        raw_theme_prompts = runtime.get("visual_reply_story_theme_prompts", {})
        if not isinstance(raw_theme_prompts, dict):
            raw_theme_prompts = {}
        raw_theme_enabled = runtime.get("visual_reply_story_theme_enabled", [])
        if isinstance(raw_theme_enabled, (str, bytes)):
            raw_theme_enabled = [raw_theme_enabled]
        if not isinstance(raw_theme_enabled, (list, tuple, set)):
            raw_theme_enabled = []
        theme_enabled = {str(item or "").strip().lower() for item in raw_theme_enabled}
        try:
            story_max_images = max(1, int(runtime.get("visual_reply_story_max_images", 3) or 3))
        except Exception:
            story_max_images = 3
        try:
            story_continuity_strength = float(runtime.get("visual_reply_story_continuity_strength", 0.8) or 0.8)
        except Exception:
            story_continuity_strength = 0.8
        if story_continuity_strength > 1.0:
            story_continuity_strength = story_continuity_strength / 100.0
        story_continuity_strength = max(0.0, min(1.0, story_continuity_strength))
        return {
            "mode_value": str(runtime.get("visual_reply_mode", "auto") or "auto"),
            "provider_value": str(runtime.get("visual_reply_provider", "openai") or "openai"),
            "size_value": str(runtime.get("visual_reply_size", "1024x1024") or "1024x1024"),
            "model_name": str(runtime.get("visual_reply_model", "gpt-image-1") or "gpt-image-1"),
            "auto_show": bool(runtime.get("visual_reply_auto_show_dock", True)),
            "master_prompt_safe": bool(runtime.get("visual_reply_master_prompt_safe", False)),
            "master_prompt_no_speech_bubbles": bool(runtime.get("visual_reply_master_prompt_no_speech_bubbles", False)),
            "story_mode": bool(runtime.get("visual_reply_story_mode", False)),
            "story_max_images": story_max_images,
            "story_continuity_strength": story_continuity_strength,
            "story_themes": [
                {
                    "id": str(theme.get("id") or "").strip().lower(),
                    "label": str(theme.get("label") or theme.get("id") or "").strip(),
                    "prompt": str(raw_theme_prompts.get(str(theme.get("id") or "").strip().lower(), theme.get("prompt", "")) or theme.get("prompt", "")).strip(),
                    "enabled": str(theme.get("id") or "").strip().lower() in theme_enabled,
                }
                for theme in theme_presets
                if str(theme.get("id") or "").strip()
            ],
        }

    def mode_labels(self):
        return ["Off", "Auto"]

    def provider_labels(self):
        return ["OpenAI", "xAI / Grok"]

    def size_labels(self):
        return ["Auto", "1024x1024", "1024x1536", "1536x1024"]

    def mode_label_from_value(self, value: str):
        return self._window._visual_reply_mode_label_from_value(value)

    def provider_label_from_value(self, value: str):
        return self._window._visual_reply_provider_label_from_value(value)

    def size_label_from_value(self, value: str):
        return self._window._visual_reply_size_label_from_value(value)

    def normalize_size(self, value: str):
        return self._window._normalize_visual_reply_size(value)

    def attach_settings_widgets(
        self,
        *,
        mode_combo,
        provider_combo,
        size_combo,
        model_edit,
        auto_show_checkbox,
        hint_label,
        story_mode_button=None,
        story_max_images_spin=None,
        story_continuity_slider=None,
        story_continuity_value_label=None,
        story_theme_buttons=None,
        story_theme_edits=None,
    ) -> None:
        self._window.visual_reply_mode_combo = mode_combo
        self._window.visual_reply_provider_combo = provider_combo
        self._window.visual_reply_size_combo = size_combo
        self._window.visual_reply_model_edit = model_edit
        self._window.visual_reply_auto_show_checkbox = auto_show_checkbox
        self._window.visual_reply_hint = hint_label
        if story_mode_button is not None:
            self._window.visual_reply_story_mode_button = story_mode_button
        if story_max_images_spin is not None:
            self._window.visual_reply_story_max_images_spin = story_max_images_spin
        if story_continuity_slider is not None:
            self._window.visual_reply_story_continuity_slider = story_continuity_slider
        if story_continuity_value_label is not None:
            self._window.visual_reply_story_continuity_value_label = story_continuity_value_label
        if story_theme_buttons is not None:
            self._window.visual_reply_story_theme_buttons = dict(story_theme_buttons or {})
        if story_theme_edits is not None:
            self._window.visual_reply_story_theme_edits = dict(story_theme_edits or {})

    def apply_mode(self, choice: str) -> None:
        self._window.on_visual_reply_mode_changed(choice)

    def apply_provider(self, choice: str) -> None:
        self._window.on_visual_reply_provider_changed(choice)

    def apply_size(self, choice: str) -> None:
        self._window.on_visual_reply_size_changed(choice)

    def apply_model(self) -> None:
        self._window.on_visual_reply_model_changed()

    def apply_auto_show(self, checked: bool) -> None:
        self._window.on_visual_reply_auto_show_changed(bool(checked))

    def apply_story_mode(self, checked: bool) -> None:
        self._window.on_visual_reply_story_mode_changed(bool(checked))

    def apply_story_max_images(self, value: int) -> None:
        self._window.on_visual_reply_story_max_images_changed(int(value))

    def apply_story_continuity_strength(self, value: int) -> None:
        self._window.on_visual_reply_story_continuity_strength_changed(int(value))

    def apply_story_theme_toggle(self, theme_id: str, checked: bool) -> None:
        self._window.on_visual_reply_story_theme_toggled(str(theme_id or ""), bool(checked))

    def apply_story_theme_text(self, theme_id: str, text: str) -> None:
        self._window.on_visual_reply_story_theme_text_changed(str(theme_id or ""), str(text or ""))

    def refresh_hint(self) -> None:
        self._window._refresh_visual_reply_hint()

    def replace_panel(self, panel) -> bool:
        dock = getattr(self._window, "visual_reply_dock", None)
        if dock is None or panel is None:
            return False
        old_widget = dock.widget()
        try:
            load_signal = getattr(panel, "loadRequested", None)
            if load_signal is not None:
                load_signal.connect(self._window.prompt_visual_reply_image)
        except Exception:
            pass
        try:
            caption_signal = getattr(panel, "captionRequested", None)
            if caption_signal is not None:
                caption_signal.connect(self._window.prompt_visual_reply_caption)
        except Exception:
            pass
        try:
            clear_signal = getattr(panel, "clearRequested", None)
            if clear_signal is not None:
                clear_signal.connect(lambda: self._window.clear_visual_reply(auto_show=False))
        except Exception:
            pass
        dock.setWidget(panel)
        self._window.visual_reply_panel = panel
        if old_widget is not None and old_widget is not panel:
            try:
                old_widget.deleteLater()
            except Exception:
                pass
        return True

    def show(self) -> None:
        self._window.show_visual_reply_dock()

    def hide(self) -> None:
        dock = getattr(self._window, 'visual_reply_dock', None)
        if dock is not None:
            dock.hide()

    def clear(self, status_text: str = "Visual Reply idle", detail_text: str = "No visual reply yet.\nWhen NC creates an image, it will appear here.", auto_show: bool = False) -> bool:
        return bool(self._window.clear_visual_reply(status_text=status_text, detail_text=detail_text, auto_show=auto_show))

    def set_loading(self, status_text: str = "Visual Reply generating...", detail_text: str = "Preparing image...", auto_show: bool = True) -> bool:
        return bool(self._window.set_visual_reply_loading(status_text=status_text, detail_text=detail_text, auto_show=auto_show))

    def show_image(self, image_path: str, caption: str = "", status_text: str = "Visual Reply", auto_show: bool = True) -> bool:
        return bool(self._window.show_visual_reply_image(image_path, caption=caption, status_text=status_text, auto_show=auto_show))



class QtSensoryService:
    def __init__(self, window):
        self._window = window

    def _refresh_ui(self):
        if hasattr(self._window, "refresh_sensory_feedback_source_options"):
            selected_value = None
            try:
                import engine
                selected_value = str(getattr(engine, "RUNTIME_CONFIG", {}).get("sensory_feedback_source", "off") or "off")
            except Exception:
                selected_value = None
            self._window.refresh_sensory_feedback_source_options(selected_value=selected_value)
        elif hasattr(self._window, "_refresh_sensory_feedback_source_tabs"):
            self._window._refresh_sensory_feedback_source_tabs()

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
        if hasattr(self._window, "refresh_sensory_feedback_source_options"):
            self._window.refresh_sensory_feedback_source_options(selected_value=getattr(provider, "id", ""))
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


class QtChatProviderService:
    def __init__(self, window):
        self._window = window

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
    ):
        provider = avatar_runtime.register_provider(
            provider_id=provider_id,
            label=label,
            factory=factory,
            description=description,
            order=order,
            metadata=metadata,
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

    def snapshot_chat_session(self):
        import engine

        return dict(engine.export_chat_session_state() or {})

    def replayable_assistant_entries(self):
        import engine

        return list(engine.collect_replayable_assistant_entries())

    def replayable_assistant_messages(self):
        import engine

        return list(engine.collect_replayable_assistant_messages())

    def is_engine_running(self) -> bool:
        thread = getattr(self._window, "thread", None)
        return bool(thread and thread.is_alive())

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
        import engine

        self.trigger_control_action(engine.build_replay_chat_session_from_action(start_index))

    def load_chat_context(self) -> None:
        self._window.load_chat_context()

    def quick_load_chat_context(self) -> None:
        self._window.quick_load_chat_context()

    def save_chat_context(self) -> None:
        self._window.save_chat_context()

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


class QtMuseTalkUIService:
    _VRAM_LABELS = {
        "quality": "Quality",
        "balanced": "Balanced",
        "low_vram": "Low VRAM",
        "very_low_vram": "Very Low VRAM",
    }

    def __init__(self, window):
        self._window = window

    def _preview_widget(self):
        return getattr(self._window, "embedded_musetalk_preview", None)

    def _combo_text(self, name: str, default: str = "") -> str:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "currentText"):
            try:
                text = str(widget.currentText() or "").strip()
                if text:
                    return text
            except Exception:
                pass
        return str(default or "").strip()

    def _combo_data(self, name: str, default: str = "") -> str:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "currentData"):
            try:
                value = str(widget.currentData() or "").strip()
                if value:
                    return value
            except Exception:
                pass
        return str(default or "").strip()

    def _spin_value(self, name: str, default: int = 0) -> int:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "value"):
            try:
                return int(widget.value())
            except Exception:
                pass
        return int(default)

    def _checked(self, name: str, default: bool = False) -> bool:
        widget = getattr(self._window, str(name), None)
        if widget is not None and hasattr(widget, "isChecked"):
            try:
                return bool(widget.isChecked())
            except Exception:
                pass
        return bool(default)

    def _vram_key_from_label(self, label: str) -> str:
        wanted = str(label or "").strip()
        for key, value in self._VRAM_LABELS.items():
            if value == wanted:
                return key
        return "quality"

    def export_avatar_runtime_settings(self):
        import engine

        runtime = getattr(engine, "RUNTIME_CONFIG", {}) or {}
        default_fade = int(getattr(engine, "QT_MUSETALK_LOOP_FADE_MS", 150) or 150)
        return {
            "musetalk_avatar_pack_id": self._combo_data("musetalk_avatar_pack_combo", runtime.get("musetalk_avatar_pack_id", "")),
            "musetalk_vram_mode": self._vram_key_from_label(self._combo_text("musetalk_vram_combo", self._VRAM_LABELS.get(str(runtime.get("musetalk_vram_mode", "quality") or "quality"), "Quality"))),
            "musetalk_loop_fade_ms": self._spin_value("musetalk_loop_fade_spin", int(runtime.get("musetalk_loop_fade_ms", default_fade) or default_fade)),
            "musetalk_use_frame_cache": self._checked("musetalk_use_frame_cache_checkbox", bool(runtime.get("musetalk_use_frame_cache", True))),
        }

    def _set_combo_text_quietly(self, name: str, text: str):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setCurrentText"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setCurrentText(str(text or ""))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_spin_value_quietly(self, name: str, value: int):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setValue"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setValue(int(value))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _set_checked_quietly(self, name: str, checked: bool):
        widget = getattr(self._window, str(name), None)
        if widget is None or not hasattr(widget, "setChecked"):
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setChecked(bool(checked))
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def _select_avatar_pack_quietly(self, pack_id: str):
        refresh = getattr(self._window, "refresh_musetalk_avatar_pack_list", None)
        if callable(refresh):
            refresh(selected_pack_id=pack_id)
        widget = getattr(self._window, "musetalk_avatar_pack_combo", None)
        if widget is None or not hasattr(widget, "findData"):
            return
        index = widget.findData(str(pack_id or ""))
        if index < 0:
            return
        previous = False
        try:
            previous = bool(widget.blockSignals(True))
            widget.setCurrentIndex(index)
        finally:
            try:
                widget.blockSignals(previous)
            except Exception:
                pass

    def import_avatar_runtime_settings(self, payload):
        import engine

        data = dict(payload or {})
        keys = {
            "musetalk_avatar_pack_id",
            "musetalk_vram_mode",
            "musetalk_loop_fade_ms",
            "musetalk_use_frame_cache",
        }
        if not any(key in data for key in keys):
            return None
        if "musetalk_avatar_pack_id" in data:
            pack_id = str(data.get("musetalk_avatar_pack_id") or "").strip()
            engine.update_runtime_config("musetalk_avatar_pack_id", pack_id)
            self._select_avatar_pack_quietly(pack_id)
        if "musetalk_vram_mode" in data:
            mode = str(data.get("musetalk_vram_mode") or "quality").strip().lower()
            if mode not in self._VRAM_LABELS:
                mode = "quality"
            engine.update_runtime_config("musetalk_vram_mode", mode)
            self._set_combo_text_quietly("musetalk_vram_combo", self._VRAM_LABELS.get(mode, "Quality"))
        if "musetalk_loop_fade_ms" in data:
            fade_ms = max(0, int(data.get("musetalk_loop_fade_ms") or 0))
            engine.update_runtime_config("musetalk_loop_fade_ms", fade_ms)
            self._set_spin_value_quietly("musetalk_loop_fade_spin", fade_ms)
        if "musetalk_use_frame_cache" in data:
            enabled = bool(data.get("musetalk_use_frame_cache"))
            engine.update_runtime_config("musetalk_use_frame_cache", enabled)
            self._set_checked_quietly("musetalk_use_frame_cache_checkbox", enabled)
        return None

    def publish_preview_frame(self, *, frame_path: str, avatar_id: str, mode_label: str) -> bool:
        import time

        publish_time = time.time()
        frame_identity = Path(frame_path).stem if frame_path else "frame"
        chunk_id = f"first_frame_test:{avatar_id}:{frame_identity}"
        shared_state.set_current_musetalk_frame_data({
            "frame_paths": [frame_path] if frame_path else [],
            "frame_dir": str(Path(frame_path).parent) if frame_path else "",
            "fps": 24,
            "sync_time": publish_time,
            "duration_seconds": 0.0,
            "expected_frame_count": 1,
            "trim_start_frames": 0,
            "chunk_id": chunk_id,
            "text": f"{mode_label} for {avatar_id}",
            "status": "ready",
            "loop": False,
            "start_index": 0,
            "source_indices": [0],
            "avatar_id": avatar_id,
            "published_at": publish_time,
        })
        shared_state.write_musetalk_preview_frame({
            "chunk_id": chunk_id,
            "status": "ready",
            "loop": False,
            "frame_path": frame_path,
            "frame_index": 0,
            "source_index": 0,
            "fps": 24,
            "emitted_at": publish_time,
        })
        preview_loaded = False
        preview_dock = getattr(self._window, "preview_dock", None)
        if preview_dock is not None:
            preview_dock.show()
            preview_dock.raise_()
        preview_widget = self._preview_widget()
        if preview_widget is not None:
            preview_loaded = bool(
                preview_widget.show_static_frame(
                    frame_path,
                    f"MuseTalk {mode_label.lower()}: {avatar_id}",
                )
            )
        return preview_loaded

    def configure_debug_mask_editor(self, *, base_frame_path: str, mask_frame_path: str, bbox, crop_box, modified_mask_path: str | None = None) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "configure_debug_mask_editor"):
            return False
        return bool(
            preview_widget.configure_debug_mask_editor(
                base_frame_path=base_frame_path,
                mask_frame_path=mask_frame_path,
                bbox=bbox,
                crop_box=crop_box,
                modified_mask_path=modified_mask_path,
            )
        )

    def set_debug_mask_brush(self, *, radius: int | None = None, feather: int | None = None) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "set_debug_mask_brush"):
            return False
        return bool(preview_widget.set_debug_mask_brush(radius=radius, feather=feather))

    def adjust_preview_zoom(self, factor_delta: float) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "adjust_zoom"):
            return False
        return bool(preview_widget.adjust_zoom(factor_delta))

    def reset_preview_zoom(self) -> bool:
        preview_widget = self._preview_widget()
        if preview_widget is None or not hasattr(preview_widget, "reset_zoom"):
            return False
        return bool(preview_widget.reset_zoom())

    def clear_debug_mask_editor(self) -> None:
        preview_widget = self._preview_widget()
        if preview_widget is not None and hasattr(preview_widget, "clear_debug_mask_editor"):
            preview_widget.clear_debug_mask_editor()
