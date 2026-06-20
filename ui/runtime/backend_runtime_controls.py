def _runtime_config():
    from ui.runtime import engine_access as engine

    return getattr(engine, "RUNTIME_CONFIG", {})


def _update_runtime_config(key, value):
    from ui.runtime.engine_access import update_runtime_config

    return update_runtime_config(key, value)


_AI_PRESENCE_DISPLAY_MODES = {"off", "fullscreen", "floating", "both"}
_AI_PRESENCE_VISUAL_STYLES = {
    "neural_network_pulse",
}


def _normalize_ai_presence_display_mode(value):
    mode = str(value or "fullscreen").strip().lower()
    return mode if mode in _AI_PRESENCE_DISPLAY_MODES else "fullscreen"


def _normalize_ai_presence_visual_style(value):
    style = str(value or "neural_network_pulse").strip().lower()
    return style if style in _AI_PRESENCE_VISUAL_STYLES else "neural_network_pulse"


def _audio_device_labels(*, show_all_inputs=False, include_input_mode_actions=False):
    from qt_app import _ui_shell_audio_device_labels

    return _ui_shell_audio_device_labels(
        show_all_inputs=show_all_inputs,
        include_input_mode_actions=include_input_mode_actions,
    )


class BackendRuntimeControlsMixin:
    """Small runtime-control state helpers shared by legacy and real UI bindings."""

    def _resolve_audio_device_label(self, label, *, direction):
        default_label = "Default Output" if direction == "output" else "Default Input"
        selected = str(label or "").strip() or default_label
        options_key = "outputs" if direction == "output" else "inputs"
        options = list((_audio_device_labels(show_all_inputs=(direction == "input")).get(options_key) or [default_label]))
        for option in options:
            if str(option or "").strip().lower() == selected.lower():
                return str(option or "").strip() or default_label
        return default_label

    def _audio_input_mode_action(self, label):
        from qt_app import SHOW_ALL_AUDIO_INPUT_DEVICES_LABEL, SHOW_MICROPHONE_AUDIO_INPUT_DEVICES_LABEL

        text = str(label or "").strip().casefold()
        if text == str(SHOW_ALL_AUDIO_INPUT_DEVICES_LABEL).strip().casefold():
            return "show_all"
        if text == str(SHOW_MICROPHONE_AUDIO_INPUT_DEVICES_LABEL).strip().casefold():
            return "microphones_only"
        return ""

    def _audio_input_show_all_enabled(self):
        widget = getattr(self, "show_all_audio_inputs_checkbox", None)
        if widget is not None and hasattr(widget, "isChecked"):
            return bool(widget.isChecked())
        return bool(_runtime_config().get("show_all_audio_input_devices", False))

    def _refresh_audio_input_device_options(self, selected=None):
        combo = getattr(self, "audio_input_device_combo", None)
        if combo is None:
            return
        choice = str(selected or (combo.currentText() if hasattr(combo, "currentText") else "") or "Default Input").strip()
        options = list(
            (
                _audio_device_labels(
                    show_all_inputs=self._audio_input_show_all_enabled(),
                    include_input_mode_actions=True,
                ).get("inputs")
                or ["Default Input"]
            )
        )
        from qt_app import _ui_shell_combo_select_label, _ui_shell_combo_set_items

        _ui_shell_combo_set_items(combo, options)
        _ui_shell_combo_select_label(combo, choice if choice in options else "Default Input")

    def on_audio_input_device_change(self, choice):
        action = self._audio_input_mode_action(choice)
        if action:
            show_all = action == "show_all"
            checkbox = getattr(self, "show_all_audio_inputs_checkbox", None)
            if checkbox is not None and hasattr(checkbox, "setChecked"):
                checkbox.blockSignals(True)
                checkbox.setChecked(show_all)
                checkbox.blockSignals(False)
            _update_runtime_config("show_all_audio_input_devices", show_all)
            self._refresh_audio_input_device_options(_runtime_config().get("audio_input_device", "Default Input"))
            self.save_session()
            return
        resolved = self._resolve_audio_device_label(choice, direction="input")
        _update_runtime_config("audio_input_device", resolved)
        self.save_session()

    def on_show_all_audio_inputs_change(self, checked):
        _update_runtime_config("show_all_audio_input_devices", bool(checked))
        self._refresh_audio_input_device_options(_runtime_config().get("audio_input_device", "Default Input"))
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
        refresh_preset_load = getattr(self, "_refresh_preset_load_button_state", None)
        if callable(refresh_preset_load):
            refresh_preset_load()

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

    def _apply_ai_presence_runtime_config(self):
        controller = getattr(self, "visual_presence_controller", None)
        if controller is not None and hasattr(controller, "apply_runtime_config"):
            try:
                controller.apply_runtime_config(dict(_runtime_config()))
            except Exception:
                pass

    def _set_ai_presence_combo_value(self, attr, value):
        combo = getattr(self, attr, None)
        if combo is None or not hasattr(combo, "count"):
            return
        try:
            combo.blockSignals(True)
            target = str(value or "").strip().lower()
            for index in range(combo.count()):
                data = str(combo.itemData(index) or "").strip().lower()
                if data == target:
                    combo.setCurrentIndex(index)
                    return
        finally:
            try:
                combo.blockSignals(False)
            except Exception:
                pass

    def _current_ai_presence_combo_data(self, attr, fallback):
        combo = getattr(self, attr, None)
        if combo is not None and hasattr(combo, "currentData"):
            try:
                data = combo.currentData()
                if data:
                    return data
            except Exception:
                pass
        return fallback

    def _set_ai_presence_checked(self, attr, checked):
        widget = getattr(self, attr, None)
        if widget is None or not hasattr(widget, "setChecked"):
            return
        try:
            widget.blockSignals(True)
            widget.setChecked(bool(checked))
        finally:
            try:
                widget.blockSignals(False)
            except Exception:
                pass

    def on_ai_presence_enabled_changed(self, checked):
        _update_runtime_config("ai_presence_enabled", bool(checked))
        if bool(checked) and _normalize_ai_presence_display_mode(_runtime_config().get("ai_presence_display_mode", "fullscreen")) == "off":
            _update_runtime_config("ai_presence_display_mode", "fullscreen")
            self._set_ai_presence_combo_value("ai_presence_display_mode_combo", "fullscreen")
        self._apply_ai_presence_runtime_config()
        self.save_session()

    def on_ai_presence_preview_requested(self):
        _update_runtime_config("ai_presence_enabled", True)
        _update_runtime_config("ai_presence_display_mode", "fullscreen")
        _update_runtime_config("ai_presence_fullscreen", True)
        self._set_ai_presence_combo_value("ai_presence_display_mode_combo", "fullscreen")
        for attr in ("ai_presence_enabled_checkbox", "ai_presence_fullscreen_checkbox"):
            widget = getattr(self, attr, None)
            if widget is not None and hasattr(widget, "setChecked"):
                try:
                    widget.blockSignals(True)
                    widget.setChecked(True)
                finally:
                    try:
                        widget.blockSignals(False)
                    except Exception:
                        pass
        if getattr(self, "visual_presence_controller", None) is None and hasattr(self, "_install_visual_presence_overlay"):
            try:
                self._install_visual_presence_overlay()
            except Exception:
                pass
        self._apply_ai_presence_runtime_config()
        try:
            from PySide6 import QtCore
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.apply_settings(_runtime_config())
            visual_presence_runtime.set_ai_state("speaking")
            visual_presence_runtime.set_audio_level(0.58)

            def _finish_preview():
                try:
                    visual_presence_runtime.set_audio_level(0.0)
                    visual_presence_runtime.set_ai_state("idle")
                except Exception:
                    pass

            QtCore.QTimer.singleShot(7000, _finish_preview)
        except Exception as exc:
            label = getattr(self, "ai_presence_status_label", None)
            if label is not None and hasattr(label, "setText"):
                label.setText(f"AI Presence preview failed: {exc}")
        self.save_session()

    def on_ai_presence_show_floating_requested(self):
        _update_runtime_config("ai_presence_enabled", True)
        _update_runtime_config("ai_presence_display_mode", "floating")
        self._set_ai_presence_checked("ai_presence_enabled_checkbox", True)
        self._set_ai_presence_combo_value("ai_presence_display_mode_combo", "floating")
        if getattr(self, "visual_presence_controller", None) is None and hasattr(self, "_install_visual_presence_overlay"):
            try:
                self._install_visual_presence_overlay()
            except Exception:
                pass
        self._apply_ai_presence_runtime_config()
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.apply_settings(_runtime_config())
            visual_presence_runtime.set_ai_state("idle")
            visual_presence_runtime.set_audio_level(0.0)
        except Exception as exc:
            label = getattr(self, "ai_presence_status_label", None)
            if label is not None and hasattr(label, "setText"):
                label.setText(f"AI Presence floating window failed: {exc}")
        self.save_session()

    def on_ai_presence_display_mode_changed(self, value):
        raw_value = self._current_ai_presence_combo_data("ai_presence_display_mode_combo", value)
        mode = _normalize_ai_presence_display_mode(raw_value)
        _update_runtime_config("ai_presence_display_mode", mode)
        enabled = mode != "off"
        _update_runtime_config("ai_presence_enabled", enabled)
        self._set_ai_presence_checked("ai_presence_enabled_checkbox", enabled)
        self._apply_ai_presence_runtime_config()
        self.save_session()

    def on_ai_presence_visual_style_changed(self, value):
        raw_value = self._current_ai_presence_combo_data("ai_presence_visual_style_combo", value)
        style = _normalize_ai_presence_visual_style(raw_value)
        _update_runtime_config("ai_presence_visual_style", style)
        self._apply_ai_presence_runtime_config()
        self.save_session()

    def on_ai_presence_setting_changed(self, key, value):
        key = str(key or "").strip()
        if key == "ai_presence_display_mode":
            self.on_ai_presence_display_mode_changed(value)
            return
        if key == "ai_presence_visual_style":
            self.on_ai_presence_visual_style_changed(value)
            return
        if key not in {
            "ai_presence_fullscreen",
            "ai_presence_overlay_opacity",
            "ai_presence_floating_opacity",
            "ai_presence_floating_always_on_top",
            "ai_presence_remember_floating_geometry",
            "ai_presence_transparent_background",
            "ai_presence_thinking_pulse",
            "ai_presence_speaking_reactivity",
            "ai_presence_audio_refresh_hz",
            "ai_presence_node_density",
            "ai_presence_particle_density",
            "ai_presence_reduced_effects",
            "ai_presence_shaders_enabled",
            "ai_presence_particles_enabled",
            "ai_presence_space_closes_fullscreen",
            "ai_presence_music_reactivity_enabled",
            "ai_presence_music_reactivity",
        }:
            return
        if key in {
            "ai_presence_fullscreen",
            "ai_presence_floating_always_on_top",
            "ai_presence_remember_floating_geometry",
            "ai_presence_transparent_background",
            "ai_presence_reduced_effects",
            "ai_presence_shaders_enabled",
            "ai_presence_particles_enabled",
            "ai_presence_space_closes_fullscreen",
            "ai_presence_music_reactivity_enabled",
        }:
            normalized = bool(value)
        elif key == "ai_presence_audio_refresh_hz":
            normalized = max(5, min(30, int(value)))
        elif key == "ai_presence_node_density":
            normalized = max(8, min(96, int(value)))
        elif key == "ai_presence_particle_density":
            normalized = max(0, min(120, int(value)))
        elif key == "ai_presence_speaking_reactivity":
            normalized = max(0.10, min(1.50, float(value)))
        elif key == "ai_presence_music_reactivity":
            normalized = max(0.00, min(1.50, float(value)))
        elif key == "ai_presence_floating_opacity":
            normalized = max(0.35, min(1.00, float(value)))
        else:
            normalized = max(0.10, min(1.00, float(value)))
        _update_runtime_config(key, normalized)
        self._apply_ai_presence_runtime_config()
        self.save_session()
