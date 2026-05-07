from PySide6 import QtCore


def sync_frontend_combo_to_controller(bridge):
    controller = bridge._audio_story_controller()
    frontend_combo = bridge._ui_object("audio_story_playback_combo")
    backend_combo = getattr(controller, "audio_story_playback_mode_combo", None) if controller is not None else None
    if frontend_combo is None or backend_combo is None:
        return
    bridge._sync_combo_like_widget(frontend_combo, backend_combo)
    QtCore.QTimer.singleShot(0, lambda: bridge._sync_backend_to_ui(force=True))


def sync_frontend_slider_to_controller(bridge, value):
    controller = bridge._audio_story_controller()
    backend_slider = getattr(controller, "audio_story_transcribe_seconds_slider", None) if controller is not None else None
    if backend_slider is None or not hasattr(backend_slider, "setValue"):
        return
    try:
        backend_slider.setValue(int(value))
    except Exception:
        return
    QtCore.QTimer.singleShot(0, lambda: bridge._sync_backend_to_ui(force=True))


def apply_seek_from_frontend(bridge):
    controller = bridge._audio_story_controller()
    frontend_slider = bridge._ui_object("audio_story_seek_slider")
    backend_slider = getattr(controller, "audio_story_position_slider", None) if controller is not None else None
    if frontend_slider is None or backend_slider is None or not hasattr(frontend_slider, "value") or not hasattr(backend_slider, "setValue"):
        return
    try:
        backend_slider.setValue(int(frontend_slider.value()))
    except Exception:
        return
    callback = getattr(controller, "_on_slider_released", None)
    if callable(callback):
        try:
            callback()
        finally:
            QtCore.QTimer.singleShot(0, lambda: bridge._sync_backend_to_ui(force=True))


def bind_duplicate_controls(bridge):
    import_button = bridge._ui_object("import_audio_button")
    if import_button is not None and hasattr(import_button, "clicked"):
        import_button.clicked.connect(lambda: bridge._invoke_audio_story_controller("_choose_audio_file"))
    transcribe_button = bridge._ui_object("transcribe_audio_button")
    if transcribe_button is not None and hasattr(transcribe_button, "clicked"):
        transcribe_button.clicked.connect(lambda: bridge._invoke_audio_story_controller("_start_transcription"))
    play_button = bridge._ui_object("audio_story_play_button")
    if play_button is not None and hasattr(play_button, "clicked"):
        play_button.clicked.connect(lambda: bridge._invoke_audio_story_controller("_play_story"))
    pause_button = bridge._ui_object("audio_story_pause_button")
    if pause_button is not None and hasattr(pause_button, "clicked"):
        pause_button.clicked.connect(lambda: bridge._invoke_audio_story_controller("_pause_story"))
    stop_button = bridge._ui_object("audio_story_stop_button")
    if stop_button is not None and hasattr(stop_button, "clicked"):
        stop_button.clicked.connect(lambda: bridge._invoke_audio_story_controller("_stop_story"))
    playback_combo = bridge._ui_object("audio_story_playback_combo")
    if playback_combo is not None and hasattr(playback_combo, "currentIndexChanged"):
        playback_combo.currentIndexChanged.connect(lambda _index: sync_frontend_combo_to_controller(bridge))
    transcribe_slider = bridge._ui_object("transcribe_seconds_slider")
    if transcribe_slider is not None and hasattr(transcribe_slider, "valueChanged"):
        transcribe_slider.valueChanged.connect(lambda value: sync_frontend_slider_to_controller(bridge, value))
    seek_slider = bridge._ui_object("audio_story_seek_slider")
    if seek_slider is not None and hasattr(seek_slider, "sliderReleased"):
        seek_slider.sliderReleased.connect(lambda: apply_seek_from_frontend(bridge))


def mirror_duplicate_widgets(bridge):
    controller = bridge._audio_story_controller()
    if controller is None:
        return
    frontend_path = bridge._ui_object("audio_file_path_edit")
    backend_path = getattr(controller, "audio_story_path_edit", None)
    if frontend_path is not None and backend_path is not None:
        bridge._copy_text_state(backend_path, frontend_path)
        if hasattr(frontend_path, "setReadOnly"):
            try:
                frontend_path.setReadOnly(True)
            except Exception:
                pass
    frontend_combo = bridge._ui_object("audio_story_playback_combo")
    backend_combo = getattr(controller, "audio_story_playback_mode_combo", None)
    if frontend_combo is not None and backend_combo is not None:
        bridge._copy_combo_state(backend_combo, frontend_combo)
        if hasattr(frontend_combo, "setEnabled") and hasattr(backend_combo, "isEnabled"):
            try:
                frontend_combo.setEnabled(bool(backend_combo.isEnabled()))
            except Exception:
                pass
    frontend_transcribe_slider = bridge._ui_object("transcribe_seconds_slider")
    backend_transcribe_slider = getattr(controller, "audio_story_transcribe_seconds_slider", None)
    if frontend_transcribe_slider is not None and backend_transcribe_slider is not None:
        if hasattr(frontend_transcribe_slider, "setRange") and hasattr(backend_transcribe_slider, "minimum") and hasattr(backend_transcribe_slider, "maximum"):
            try:
                frontend_transcribe_slider.setRange(int(backend_transcribe_slider.minimum()), int(backend_transcribe_slider.maximum()))
            except Exception:
                pass
        if not (hasattr(frontend_transcribe_slider, "isSliderDown") and frontend_transcribe_slider.isSliderDown()):
            bridge._copy_spin_state(backend_transcribe_slider, frontend_transcribe_slider)
        if hasattr(frontend_transcribe_slider, "setEnabled") and hasattr(backend_transcribe_slider, "isEnabled"):
            try:
                frontend_transcribe_slider.setEnabled(bool(backend_transcribe_slider.isEnabled()))
            except Exception:
                pass
    button_pairs = (
        ("import_audio_button", "audio_story_import_button"),
        ("transcribe_audio_button", "audio_story_transcribe_button"),
        ("audio_story_play_button", "audio_story_play_button"),
        ("audio_story_pause_button", "audio_story_pause_button"),
        ("audio_story_stop_button", "audio_story_stop_button"),
    )
    for frontend_name, backend_name in button_pairs:
        frontend_widget = bridge._ui_object(frontend_name)
        backend_widget = getattr(controller, backend_name, None)
        if frontend_widget is None or backend_widget is None:
            continue
        if hasattr(frontend_widget, "setEnabled") and hasattr(backend_widget, "isEnabled"):
            try:
                frontend_widget.setEnabled(bool(backend_widget.isEnabled()))
            except Exception:
                pass
        if hasattr(frontend_widget, "setText") and hasattr(backend_widget, "text"):
            try:
                frontend_widget.setText(str(backend_widget.text() or ""))
            except Exception:
                pass
    frontend_seek = bridge._ui_object("audio_story_seek_slider")
    backend_seek = getattr(controller, "audio_story_position_slider", None)
    if frontend_seek is not None and backend_seek is not None:
        if hasattr(frontend_seek, "setRange") and hasattr(backend_seek, "minimum") and hasattr(backend_seek, "maximum"):
            try:
                frontend_seek.setRange(int(backend_seek.minimum()), int(backend_seek.maximum()))
            except Exception:
                pass
        if not (hasattr(frontend_seek, "isSliderDown") and frontend_seek.isSliderDown()):
            bridge._copy_spin_state(backend_seek, frontend_seek)
        if hasattr(frontend_seek, "setEnabled") and hasattr(backend_seek, "isEnabled"):
            try:
                frontend_seek.setEnabled(bool(backend_seek.isEnabled()))
            except Exception:
                pass
    frontend_position = bridge._ui_object("audio_story_position_label")
    backend_time = getattr(controller, "audio_story_time_label", None)
    backend_status = getattr(controller, "audio_story_status_label", None)
    if frontend_position is not None and backend_time is not None and hasattr(backend_time, "text") and hasattr(frontend_position, "setText"):
        try:
            frontend_position.setText(str(backend_time.text() or ""))
        except Exception:
            pass
    if frontend_position is not None and backend_status is not None and hasattr(backend_status, "text") and hasattr(frontend_position, "setToolTip"):
        try:
            frontend_position.setToolTip(str(backend_status.text() or ""))
        except Exception:
            pass
