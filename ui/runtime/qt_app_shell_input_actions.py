"""Input action shell-local bindings for the Designer UI."""

_DEPENDENCIES = {}


def configure_qt_app_shell_input_action_dependencies(dependencies):
    _DEPENDENCIES.update(dict(dependencies or {}))
    globals().update(_DEPENDENCIES)


def _bind_ui_shell_input_action_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_input_actions_service(window)
    bound = []
    deferred = [
        "btn_push_to_talk",
        "import_audio_button",
        "transcribe_audio_button",
        "audio_story_play_button",
        "audio_story_pause_button",
        "audio_story_stop_button",
    ]

    input_mode_combo = _ui_shell_find_object(window, "input_mode_combo")
    push_to_talk_button = _ui_shell_find_object(window, "btn_push_to_talk")
    audio_file_path_edit = _ui_shell_find_object(window, "audio_file_path_edit")
    import_audio_button = _ui_shell_find_object(window, "import_audio_button")
    audio_story_playback_combo = _ui_shell_find_object(window, "audio_story_playback_combo")
    transcribe_seconds_label = _ui_shell_find_object(window, "transcribe_seconds_label")
    transcribe_seconds_slider = _ui_shell_find_object(window, "transcribe_seconds_slider")
    transcribe_audio_button = _ui_shell_find_object(window, "transcribe_audio_button")
    audio_story_play_button = _ui_shell_find_object(window, "audio_story_play_button")
    audio_story_pause_button = _ui_shell_find_object(window, "audio_story_pause_button")
    audio_story_stop_button = _ui_shell_find_object(window, "audio_story_stop_button")
    audio_story_seek_slider = _ui_shell_find_object(window, "audio_story_seek_slider")
    audio_story_position_label = _ui_shell_find_object(window, "audio_story_position_label")

    if audio_file_path_edit is not None:
        if hasattr(audio_file_path_edit, "setReadOnly"):
            audio_file_path_edit.setReadOnly(False)
        if hasattr(audio_file_path_edit, "setText"):
            audio_file_path_edit.setText(str(session.get("audio_story_mode_audio_path", "") or ""))
        if hasattr(audio_file_path_edit, "setToolTip"):
            audio_file_path_edit.setToolTip("Shell-local Audio Story path preview. Paste a local path here; no file is opened or saved.")

    if audio_story_playback_combo is not None:
        _ui_shell_combo_set_items(audio_story_playback_combo, list(_UiShellInputActionService.AUDIO_STORY_PLAYBACK_MODES))
        _ui_shell_combo_select_label(audio_story_playback_combo, str(session.get("audio_story_mode_playback_mode", "Play Imported Audio") or "Play Imported Audio"))
        audio_story_playback_combo.setToolTip("Shell-local Audio Story playback mode preview. No player or TTS narration is started.")

    if transcribe_seconds_slider is not None:
        try:
            transcribe_seconds_slider.setRange(1, 60)
        except Exception:
            pass
        _ui_shell_set_slider_value(transcribe_seconds_slider, int(session.get("audio_story_mode_transcribe_seconds", _UiShellInputActionService.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS) or _UiShellInputActionService.AUDIO_STORY_DEFAULT_TRANSCRIBE_SECONDS))
        transcribe_seconds_slider.setToolTip("Shell-local transcription-window preview. No Whisper/STT runtime is started.")

    if audio_story_seek_slider is not None:
        try:
            audio_story_seek_slider.setRange(0, 100)
        except Exception:
            pass
        _ui_shell_set_slider_value(audio_story_seek_slider, 0)
        audio_story_seek_slider.setToolTip("Shell-local Audio Story seek preview. No playback runtime is connected.")

    def refresh_preview():
        snapshot = service.snapshot()
        if push_to_talk_button is not None:
            if hasattr(push_to_talk_button, "setEnabled"):
                push_to_talk_button.setEnabled(bool(snapshot.get("push_to_talk_enabled")))
            if hasattr(push_to_talk_button, "setText"):
                push_to_talk_button.setText("Talking..." if snapshot.get("push_to_talk_held") else "Hold To Talk")
            if hasattr(push_to_talk_button, "setToolTip"):
                if snapshot.get("push_to_talk_enabled"):
                    push_to_talk_button.setToolTip(
                        f"Shell-local push-to-talk preview. Hotkey: {snapshot.get('push_to_talk_hotkey') or 'Right Ctrl'}. No microphone capture is started."
                    )
                else:
                    push_to_talk_button.setToolTip("Switch Input Mode to Push-to-Talk to preview this button. No microphone capture is started.")

        base_transcribe_label = ""
        if transcribe_seconds_label is not None and hasattr(transcribe_seconds_label, "setText"):
            base_transcribe_label = str(getattr(transcribe_seconds_label, "_nc_ui_shell_base_text", "") or "").strip()
            if not base_transcribe_label:
                base_transcribe_label = str(transcribe_seconds_label.text() or "Transcribe Seconds").strip() or "Transcribe Seconds"
                setattr(transcribe_seconds_label, "_nc_ui_shell_base_text", base_transcribe_label)
            transcribe_seconds_label.setText(f"{base_transcribe_label} ({int(snapshot.get('audio_story_transcribe_seconds', 0) or 0)}s)")

        has_audio = bool(snapshot.get("audio_story_has_audio"))
        playback_state = str(snapshot.get("audio_story_playback_state") or "stopped").strip().lower()
        seek_percent = int(snapshot.get("audio_story_seek_percent", 0) or 0)
        if import_audio_button is not None and hasattr(import_audio_button, "setEnabled"):
            import_audio_button.setEnabled(True)
        if import_audio_button is not None and hasattr(import_audio_button, "setToolTip"):
            import_audio_button.setToolTip("Shell-local preview only. The import dialog remains deferred; paste a path into the field to simulate import.")
        if transcribe_audio_button is not None and hasattr(transcribe_audio_button, "setEnabled"):
            transcribe_audio_button.setEnabled(has_audio)
        if transcribe_audio_button is not None and hasattr(transcribe_audio_button, "setToolTip"):
            transcribe_audio_button.setToolTip("Shell-local preview only. No Whisper/STT runtime is started.")
        if audio_story_play_button is not None and hasattr(audio_story_play_button, "setEnabled"):
            audio_story_play_button.setEnabled(has_audio and playback_state != "playing")
        if audio_story_play_button is not None and hasattr(audio_story_play_button, "setToolTip"):
            audio_story_play_button.setToolTip("Shell-local playback preview only. No media player or TTS narration is started.")
        if audio_story_pause_button is not None and hasattr(audio_story_pause_button, "setEnabled"):
            audio_story_pause_button.setEnabled(has_audio and playback_state == "playing")
        if audio_story_pause_button is not None and hasattr(audio_story_pause_button, "setToolTip"):
            audio_story_pause_button.setToolTip("Shell-local playback preview only.")
        if audio_story_stop_button is not None and hasattr(audio_story_stop_button, "setEnabled"):
            audio_story_stop_button.setEnabled(has_audio and (playback_state in {"playing", "paused"} or seek_percent > 0))
        if audio_story_stop_button is not None and hasattr(audio_story_stop_button, "setToolTip"):
            audio_story_stop_button.setToolTip("Shell-local playback preview only.")
        if audio_story_seek_slider is not None:
            if hasattr(audio_story_seek_slider, "setEnabled"):
                audio_story_seek_slider.setEnabled(has_audio)
            if not (hasattr(audio_story_seek_slider, "isSliderDown") and audio_story_seek_slider.isSliderDown()):
                _ui_shell_set_slider_value(audio_story_seek_slider, seek_percent)
        if audio_story_position_label is not None and hasattr(audio_story_position_label, "setText"):
            audio_story_position_label.setText(str(snapshot.get("audio_story_position_text") or "00:00 / 01:00"))
        return snapshot

    def append_service_message(result):
        message = str(result.get("message") or "").strip()
        if message:
            _ui_shell_append_console(window, f"[UI Shell] {message}")

    def bind_line_edit(widget, attr_name):
        if widget is None:
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        text_attr = f"{attr_name}_text_changed"
        finished_attr = f"{attr_name}_editing_finished"
        if hasattr(widget, "textChanged") and not getattr(widget, text_attr, False):
            widget.textChanged.connect(lambda *_args: refresh_preview())
            setattr(widget, text_attr, True)
        if hasattr(widget, "editingFinished") and not getattr(widget, finished_attr, False):
            widget.editingFinished.connect(
                lambda: (
                    append_service_message(service.set_audio_file_path(_ui_shell_line_edit_value(window, "audio_file_path_edit", ""))),
                    refresh_preview(),
                )
            )
            setattr(widget, finished_attr, True)

    def bind_combo(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "currentIndexChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_changed(_index=None):
            snapshot = refresh_preview()
            _ui_shell_append_console(window, on_log(snapshot))

        widget.currentIndexChanged.connect(on_changed)
        setattr(widget, attr_name, True)

    def bind_slider(widget, attr_name, on_change=None, on_release=None):
        if widget is None:
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        change_attr = f"{attr_name}_value_changed"
        release_attr = f"{attr_name}_slider_released"
        if hasattr(widget, "valueChanged") and not getattr(widget, change_attr, False):
            widget.valueChanged.connect(lambda value=None: on_change(value) if callable(on_change) else refresh_preview())
            setattr(widget, change_attr, True)
        if hasattr(widget, "sliderReleased") and callable(on_release) and not getattr(widget, release_attr, False):
            widget.sliderReleased.connect(on_release)
            setattr(widget, release_attr, True)

    def bind_click(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "clicked"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return
        widget.clicked.connect(lambda _checked=False: handler())
        setattr(widget, attr_name, True)

    if push_to_talk_button is not None:
        bound.append(str(push_to_talk_button.objectName() if hasattr(push_to_talk_button, "objectName") else "btn_push_to_talk"))
        if hasattr(push_to_talk_button, "pressed") and not getattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_press_bound", False):
            push_to_talk_button.pressed.connect(
                lambda: (
                    append_service_message(service.set_push_to_talk_hold(True)),
                    refresh_preview(),
                )
            )
            setattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_press_bound", True)
        if hasattr(push_to_talk_button, "released") and not getattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_release_bound", False):
            push_to_talk_button.released.connect(
                lambda: (
                    append_service_message(service.set_push_to_talk_hold(False)),
                    refresh_preview(),
                )
            )
            setattr(push_to_talk_button, "_nc_ui_shell_push_to_talk_release_bound", True)

    if input_mode_combo is not None and hasattr(input_mode_combo, "currentIndexChanged") and not getattr(input_mode_combo, "_nc_ui_shell_push_to_talk_mode_refresh_bound", False):
        input_mode_combo.currentIndexChanged.connect(lambda _index=None: refresh_preview())
        setattr(input_mode_combo, "_nc_ui_shell_push_to_talk_mode_refresh_bound", True)

    bind_line_edit(audio_file_path_edit, "_nc_ui_shell_audio_story_path_bound")
    bind_combo(
        audio_story_playback_combo,
        "_nc_ui_shell_audio_story_playback_bound",
        lambda snapshot: f"Audio Story playback preview mode: {snapshot.get('audio_story_playback_mode') or 'Play Imported Audio'}. No audio runtime changed.",
    )
    bind_slider(
        transcribe_seconds_slider,
        "_nc_ui_shell_audio_story_transcribe_slider_bound",
        on_change=lambda _value=None: refresh_preview(),
        on_release=lambda: _ui_shell_append_console(
            window,
            f"[UI Shell] Audio Story transcribe window preview: {int(service.snapshot().get('audio_story_transcribe_seconds', 0) or 0)} second(s). No STT runtime changed.",
        ),
    )
    bind_click(import_audio_button, "_nc_ui_shell_import_audio_bound", lambda: (append_service_message(service.request_audio_import()), refresh_preview()))
    bind_click(transcribe_audio_button, "_nc_ui_shell_transcribe_audio_bound", lambda: (append_service_message(service.request_audio_transcription()), refresh_preview()))
    bind_click(audio_story_play_button, "_nc_ui_shell_audio_story_play_bound", lambda: (append_service_message(service.play_audio_story()), refresh_preview()))
    bind_click(audio_story_pause_button, "_nc_ui_shell_audio_story_pause_bound", lambda: (append_service_message(service.pause_audio_story()), refresh_preview()))
    bind_click(audio_story_stop_button, "_nc_ui_shell_audio_story_stop_bound", lambda: (append_service_message(service.stop_audio_story()), refresh_preview()))
    bind_slider(
        audio_story_seek_slider,
        "_nc_ui_shell_audio_story_seek_bound",
        on_change=lambda value=None: (
            service.seek_audio_story(0 if value is None else int(value)),
            refresh_preview(),
        ),
        on_release=lambda: _ui_shell_append_console(
            window,
            f"[UI Shell] Audio Story seek preview: {int(service.snapshot().get('audio_story_seek_percent', 0) or 0)}%. No playback runtime was moved.",
        ),
    )

    snapshot = refresh_preview()
    return {
        "bound": bound,
        "deferred": sorted(set(deferred)),
        "push_to_talk_enabled": bool(snapshot.get("push_to_talk_enabled")),
        "audio_story_has_audio": bool(snapshot.get("audio_story_has_audio")),
        "audio_story_playback_state": str(snapshot.get("audio_story_playback_state") or "stopped"),
    }
