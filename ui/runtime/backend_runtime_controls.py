def _runtime_config():
    from ui.runtime import engine_access as engine

    return getattr(engine, "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


def _audio_device_labels():
    from qt_app import _ui_shell_audio_device_labels

    return _ui_shell_audio_device_labels()


class BackendRuntimeControlsMixin:
    """Small runtime-control state helpers shared by legacy and real UI bindings."""

    def _resolve_audio_device_label(self, label, *, direction):
        default_label = "Default Output" if direction == "output" else "Default Input"
        selected = str(label or "").strip() or default_label
        options_key = "outputs" if direction == "output" else "inputs"
        options = list((_audio_device_labels().get(options_key) or [default_label]))
        for option in options:
            if str(option or "").strip().lower() == selected.lower():
                return str(option or "").strip() or default_label
        return default_label

    def on_audio_input_device_change(self, choice):
        resolved = self._resolve_audio_device_label(choice, direction="input")
        _update_runtime_config("audio_input_device", resolved)
        self.save_session()

    def on_audio_output_device_change(self, choice):
        resolved = self._resolve_audio_device_label(choice, direction="output")
        _update_runtime_config("audio_output_device", resolved)
        self.save_session()

    def _update_push_to_talk_button(self):
        enabled = (
            bool(self.thread and self.thread.is_alive())
            and self.input_mode_combo.currentText() == "Push-to-Talk"
            and not self._dry_run_is_active()
        )
        if hasattr(self, "btn_push_to_talk"):
            self.btn_push_to_talk.setEnabled(enabled)

    def _update_restart_sensitive_controls(self):
        running = bool(self.thread and self.thread.is_alive())
        controls = [
            getattr(self, "engine_combo", None),
            getattr(self, "model_combo", None),
            getattr(self, "tts_backend_combo", None),
            getattr(self, "stream_mode_combo", None),
        ]
        avatar_mode = self._current_avatar_mode_value() if hasattr(self, "engine_combo") else str(_runtime_config().get("avatar_mode", "") or "")
        tts_backend = self._current_tts_backend_value() if hasattr(self, "tts_backend_combo") else str(_runtime_config().get("tts_backend", "") or "")
        avatar_controls = self._invoke_addon_service_capability(
            "avatar_provider_registry",
            "runtime.restart_sensitive_widgets",
            {"backend": self, "runtime_config": _runtime_config()},
            default=[],
            provider_id=avatar_mode,
        )
        tts_controls = self._invoke_addon_service_capability(
            "tts_backend_service",
            "runtime.restart_sensitive_widgets",
            {"backend": self, "runtime_config": _runtime_config()},
            default=[],
            backend_id=tts_backend,
        )
        controls.extend(list(avatar_controls or []))
        controls.extend(list(tts_controls or []))
        for control in controls:
            if control is not None:
                control.setEnabled(not running)

    def _engine_is_offline_replay_only(self):
        return bool(self.thread and self.thread.is_alive() and _runtime_config().get("offline_replay_only", False))

    def _update_control_action_buttons(self):
        running = bool(self.thread and self.thread.is_alive())
        dry_run_active = self._dry_run_is_active()
        offline_replay_only = self._engine_is_offline_replay_only()
        enabled = running and not dry_run_active and not offline_replay_only
        replay_runtime_enabled = running and not dry_run_active and offline_replay_only
        for name in ["btn_regenerate", "btn_retry", "btn_skip_user"]:
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled(enabled)
        for name in ["btn_pause", "btn_skip"]:
            button = getattr(self, name, None)
            if button is not None:
                button.setEnabled((running and not dry_run_active and not offline_replay_only) or replay_runtime_enabled)
