from __future__ import annotations

from pathlib import Path

from core import avatar_hand_state, avatar_runtime, sensory, chat_providers, engine_access, user_image_turns
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


class QtRuntimeConfigService:
    def __init__(self, window):
        self._window = window

    def _engine(self):
        return engine_access.engine_module()

    def snapshot(self) -> dict:
        return dict(getattr(self._engine(), "RUNTIME_CONFIG", {}) or {})

    def get(self, key, default=None):
        return (getattr(self._engine(), "RUNTIME_CONFIG", {}) or {}).get(str(key), default)

    def set(self, key, value):
        return self.update(str(key), value)

    def update(self, key, value):
        return self._engine().update_runtime_config(str(key), value)

    def engine_attr(self, name: str, default=None):
        return getattr(self._engine(), str(name), default)


class QtUserImageTurnService:
    def __init__(self, window):
        self._window = window

    def clear_pending_attachment(self) -> None:
        user_image_turns.clear_pending_attachment()

    def set_pending_attachment(self, image_path: str, *, source: str = "clipboard") -> None:
        user_image_turns.set_pending_attachment(str(image_path or ""), source=str(source or "clipboard"))

    def queue_image_turn(self, image_path: str, *, content: str | None = None, source: str = "clipboard") -> None:
        user_image_turns.queue_image_turn(str(image_path or ""), content=content, source=str(source or "clipboard"))


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
        self._window = window
        self._runtime_config = QtRuntimeConfigService(window)

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
        runtime = self._runtime_config.snapshot()
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
    def __init__(self, window):
        self._window = window
        self._runtime_config = QtRuntimeConfigService(window)
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
            getter = self._runtime_config.engine_attr("get_push_to_talk_hotkey", None)
            push_to_talk_hotkey = str(getter() if callable(getter) else "Right Ctrl").strip() or "Right Ctrl"
        except Exception:
            push_to_talk_hotkey = "Right Ctrl"
        push_enabled = self._push_to_talk_enabled()
        if not push_enabled:
            self._push_to_talk_held = False
        return {
            "last_action": self._last_action,
            "push_to_talk_enabled": push_enabled,
            "push_to_talk_held": bool(self._push_to_talk_held and push_enabled),
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
            setter = self._runtime_config.engine_attr("set_push_to_talk_hold", None)
            if not callable(setter):
                raise RuntimeError("Push-to-Talk runtime action unavailable.")
            setter(bool(held))
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


class QtSensoryService:
    def __init__(self, window):
        self._window = window
        self._runtime_config = QtRuntimeConfigService(window)

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
        self._runtime_config = QtRuntimeConfigService(window)

    def snapshot_chat_session(self):
        exporter = self._runtime_config.engine_attr("export_chat_session_state", None)
        return dict(exporter() if callable(exporter) else {})

    def replayable_chat_entries(self):
        collector = self._runtime_config.engine_attr("collect_replayable_chat_entries", None)
        return list(collector() if callable(collector) else [])

    def replayable_chat_messages(self):
        collector = self._runtime_config.engine_attr("collect_replayable_chat_messages", None)
        return list(collector() if callable(collector) else [])

    def replayable_assistant_entries(self):
        collector = self._runtime_config.engine_attr("collect_replayable_assistant_entries", None)
        return list(collector() if callable(collector) else [])

    def replayable_assistant_messages(self):
        collector = self._runtime_config.engine_attr("collect_replayable_assistant_messages", None)
        return list(collector() if callable(collector) else [])

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
        builder = self._runtime_config.engine_attr("build_replay_chat_session_from_action", None)
        if callable(builder):
            self.trigger_control_action(builder(start_index))

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
