"""Host/core shell-local bindings for the Designer UI."""

_DEPENDENCIES = {}


def configure_qt_app_shell_host_core_dependencies(dependencies):
    _DEPENDENCIES.update(dict(dependencies or {}))
    globals().update(_DEPENDENCIES)


def _bind_ui_shell_host_core_controls(window, sensory_providers=None):
    _configure_ui_shell_service_dependencies()
    session = dict(_read_ui_shell_session_snapshot() or {})
    audio_devices = _ui_shell_audio_device_labels()
    avatar_pack_options = _ui_shell_musetalk_avatar_pack_options(session)
    visual_reply_service = _UiShellVisualReplyService(window)
    visual_reply_snapshot = dict(visual_reply_service.settings_snapshot() or {})
    sensory_options = _ui_shell_sensory_source_options(sensory_providers=sensory_providers, selected_value=session.get("sensory_feedback_source", "off"))
    default_max_response_tokens = 600

    audio_input_combo = _ui_shell_find_object(window, "audio_input_device_combo")
    audio_output_combo = _ui_shell_find_object(window, "audio_output_device_combo")
    input_mode_combo = _ui_shell_find_object(window, "input_mode_combo")
    input_role_combo = _ui_shell_find_object(window, "input_role_combo")
    stream_mode_combo = _ui_shell_find_object(window, "stream_mode_combo")
    musetalk_vram_combo = _ui_shell_find_object(window, "musetalk_vram_combo")
    musetalk_avatar_pack_combo = _ui_shell_find_object(window, "musetalk_avatar_pack_combo")
    context_window_spin = _ui_shell_find_object(window, "chat_context_window_spin")
    stored_history_spin = _ui_shell_find_object(window, "stored_chat_history_limit_spin")
    overflow_combo = _ui_shell_find_object(window, "chat_overflow_policy_combo")
    allow_proactive_checkbox = _ui_shell_find_object(window, "allow_proactive_checkbox")
    require_first_user_checkbox = _ui_shell_find_object(window, "require_first_user_checkbox")
    listen_idle_window_spin = _ui_shell_find_object(window, "listen_idle_window_spin")
    proactive_delay_spin = _ui_shell_find_object(window, "proactive_delay_spin")
    limit_response_checkbox = _ui_shell_find_object(window, "limit_response_checkbox")
    max_response_tokens_spin = _ui_shell_find_object(window, "max_response_tokens_spin")
    sensory_feedback_source_combo = _ui_shell_find_object(window, "sensory_feedback_source_combo")
    sensory_feedback_interval_spin = _ui_shell_find_object(window, "sensory_feedback_interval_spin")
    sensory_pingpong_checkbox = _ui_shell_find_object(window, "sensory_pingpong_checkbox")
    sensory_allow_hidden_proactive_checkbox = _ui_shell_find_object(window, "sensory_allow_hidden_proactive_checkbox")
    sensory_allow_hidden_visual_checkbox = _ui_shell_find_object(window, "sensory_allow_hidden_visual_checkbox")
    sensory_pingpong_history_spin = _ui_shell_find_object(window, "sensory_pingpong_history_spin")
    visual_reply_mode_combo = _ui_shell_find_object(window, "visual_reply_mode_combo")
    visual_reply_provider_combo = _ui_shell_find_object(window, "visual_reply_provider_combo")
    visual_reply_size_combo = _ui_shell_find_object(window, "visual_reply_size_combo")
    visual_reply_model_edit = _ui_shell_find_object(window, "visual_reply_model_edit")
    visual_reply_api_key_edit = _ui_shell_find_object(window, "visual_reply_api_key_edit")
    visual_reply_auto_show_checkbox = _ui_shell_find_object(window, "visual_reply_auto_show_checkbox")
    visual_reply_hint = _ui_shell_find_object(window, "visual_reply_hint")

    if audio_input_combo is not None:
        _ui_shell_combo_set_items(audio_input_combo, list(audio_devices.get("inputs") or ["Default Input"]))
        _ui_shell_combo_select_label(audio_input_combo, session.get("audio_input_device", "Default Input"))
        audio_input_combo.setToolTip("Shell-local audio input preview. No microphone capture is started.")
    if audio_output_combo is not None:
        _ui_shell_combo_set_items(audio_output_combo, list(audio_devices.get("outputs") or ["Default Output"]))
        _ui_shell_combo_select_label(audio_output_combo, session.get("audio_output_device", "Default Output"))
        audio_output_combo.setToolTip("Shell-local audio output preview. No playback device is opened.")
    if input_mode_combo is not None and hasattr(input_mode_combo, "setToolTip"):
        input_mode_combo.setToolTip("Shell-local input-mode preview. Changes update only the shell status line.")
    if input_role_combo is not None and hasattr(input_role_combo, "setToolTip"):
        input_role_combo.setToolTip("Shell-local input-role preview. Changes update only the shell status line.")
    if stream_mode_combo is not None and hasattr(stream_mode_combo, "setToolTip"):
        stream_mode_combo.setToolTip("Shell-local stream-mode preview. Changes update only the shell status line.")
    if musetalk_vram_combo is not None and hasattr(musetalk_vram_combo, "setToolTip"):
        musetalk_vram_combo.setToolTip("Shell-local MuseTalk VRAM preview. No runtime adapter is reconfigured.")
    if musetalk_avatar_pack_combo is not None and hasattr(musetalk_avatar_pack_combo, "clear"):
        saved_pack_id = str(session.get("musetalk_avatar_pack_id", "") or "").strip()
        musetalk_avatar_pack_combo.blockSignals(True)
        try:
            musetalk_avatar_pack_combo.clear()
            for item in avatar_pack_options:
                label = str(item.get("label") or item.get("id") or "").strip()
                pack_id = str(item.get("id") or "").strip()
                if not label:
                    continue
                musetalk_avatar_pack_combo.addItem(label, pack_id)
            if musetalk_avatar_pack_combo.count() <= 0:
                musetalk_avatar_pack_combo.addItem("No avatar packs found", "")
            index = musetalk_avatar_pack_combo.findData(saved_pack_id)
            musetalk_avatar_pack_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            musetalk_avatar_pack_combo.blockSignals(False)
        musetalk_avatar_pack_combo.setToolTip("Shell-local MuseTalk avatar-pack preview. No adapter or worker is started.")
    if context_window_spin is not None and hasattr(context_window_spin, "setToolTip"):
        context_window_spin.setToolTip("Shell-local chat-context preview. Changes are not saved or applied to runtime.")
    if stored_history_spin is not None and hasattr(stored_history_spin, "setToolTip"):
        stored_history_spin.setToolTip("Shell-local stored-history preview. Changes are not saved or applied to runtime.")
    if overflow_combo is not None and hasattr(overflow_combo, "setToolTip"):
        overflow_combo.setToolTip("Shell-local overflow-policy preview. Changes are not saved or applied to runtime.")
    if allow_proactive_checkbox is not None:
        _ui_shell_set_checked(allow_proactive_checkbox, session.get("allow_proactive_replies", False))
        allow_proactive_checkbox.setToolTip("Shell-local proactive-reply preview. Changes are not saved or applied to runtime.")
    if require_first_user_checkbox is not None:
        _ui_shell_set_checked(require_first_user_checkbox, session.get("require_first_user_before_proactive", False))
        require_first_user_checkbox.setToolTip("Shell-local proactive gating preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_double_value(listen_idle_window_spin, session.get("listen_idle_window_seconds", 5.0)) and listen_idle_window_spin is not None:
        listen_idle_window_spin.setToolTip("Shell-local idle-window preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_double_value(proactive_delay_spin, session.get("proactive_delay_seconds", 10.0)) and proactive_delay_spin is not None:
        proactive_delay_spin.setToolTip("Shell-local proactive-delay preview. Changes are not saved or applied to runtime.")
    if limit_response_checkbox is not None:
        _ui_shell_set_checked(limit_response_checkbox, session.get("limit_response_length", False))
        limit_response_checkbox.setToolTip("Shell-local response-length preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_spin_value(max_response_tokens_spin, session.get("max_response_tokens", default_max_response_tokens)) and max_response_tokens_spin is not None:
        max_response_tokens_spin.setToolTip("Shell-local max-response preview. Changes are not saved or applied to runtime.")
        try:
            max_response_tokens_spin.setEnabled(bool(limit_response_checkbox.isChecked()) if limit_response_checkbox is not None and hasattr(limit_response_checkbox, "isChecked") else False)
        except Exception:
            pass
    if sensory_feedback_source_combo is not None:
        sensory_feedback_source_combo.blockSignals(True)
        try:
            sensory_feedback_source_combo.clear()
            for label, value in sensory_options:
                sensory_feedback_source_combo.addItem(label, value)
            requested = str(session.get("sensory_feedback_source", "off") or "off").strip().lower()
            index = sensory_feedback_source_combo.findData(requested)
            sensory_feedback_source_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            sensory_feedback_source_combo.blockSignals(False)
        sensory_feedback_source_combo.setToolTip("Shell-local sensory-source preview. Capture and hidden-loop delivery remain deferred.")
    if _ui_shell_set_double_value(sensory_feedback_interval_spin, session.get("sensory_feedback_interval_seconds", 7.0)) and sensory_feedback_interval_spin is not None:
        sensory_feedback_interval_spin.setToolTip("Shell-local sensory refresh preview. Changes are not saved or applied to runtime.")
    if sensory_pingpong_checkbox is not None:
        _ui_shell_set_checked(sensory_pingpong_checkbox, session.get("sensory_pingpong_enabled", False))
        sensory_pingpong_checkbox.setToolTip("Shell-local hidden PING/PONG preview. No hidden runtime loop is started.")
    if sensory_allow_hidden_proactive_checkbox is not None:
        _ui_shell_set_checked(sensory_allow_hidden_proactive_checkbox, session.get("sensory_allow_hidden_proactive_speech", False))
        sensory_allow_hidden_proactive_checkbox.setToolTip("Shell-local sensory speech preview. Changes are not saved or applied to runtime.")
    if sensory_allow_hidden_visual_checkbox is not None:
        _ui_shell_set_checked(sensory_allow_hidden_visual_checkbox, session.get("sensory_allow_hidden_visual_generation", False))
        sensory_allow_hidden_visual_checkbox.setToolTip("Shell-local sensory image-generation preview. Changes are not saved or applied to runtime.")
    if _ui_shell_set_spin_value(sensory_pingpong_history_spin, session.get("sensory_pingpong_history_depth", 3)) and sensory_pingpong_history_spin is not None:
        sensory_pingpong_history_spin.setToolTip("Shell-local PING/PONG history preview. Changes are not saved or applied to runtime.")
    if visual_reply_mode_combo is not None:
        _ui_shell_combo_set_items(visual_reply_mode_combo, list(visual_reply_service.mode_labels()))
        _ui_shell_combo_select_label(visual_reply_mode_combo, visual_reply_service.mode_label_from_value(visual_reply_snapshot.get("mode_value", "off")))
    if visual_reply_provider_combo is not None:
        _ui_shell_combo_set_items(visual_reply_provider_combo, list(visual_reply_service.provider_labels()))
        _ui_shell_combo_select_label(visual_reply_provider_combo, visual_reply_service.provider_label_from_value(visual_reply_snapshot.get("provider_value", "openai")))
    if visual_reply_size_combo is not None:
        _ui_shell_combo_set_items(visual_reply_size_combo, list(visual_reply_service.size_labels()))
        _ui_shell_combo_select_label(visual_reply_size_combo, visual_reply_service.size_label_from_value(visual_reply_snapshot.get("size_value", "1024x1024")))
    if visual_reply_model_edit is not None and hasattr(visual_reply_model_edit, "setText"):
        visual_reply_model_edit.setText(str(visual_reply_snapshot.get("model_name", visual_reply_service.default_model_for_provider(visual_reply_snapshot.get("provider_value"))) or visual_reply_service.default_model_for_provider(visual_reply_snapshot.get("provider_value"))))
    if visual_reply_api_key_edit is not None:
        try:
            visual_reply_api_key_edit.setEchoMode(visual_reply_api_key_edit.Password)
        except Exception:
            pass
    if visual_reply_auto_show_checkbox is not None:
        _ui_shell_set_checked(visual_reply_auto_show_checkbox, visual_reply_snapshot.get("auto_show", True))
    visual_reply_service.attach_settings_widgets(
        mode_combo=visual_reply_mode_combo,
        provider_combo=visual_reply_provider_combo,
        size_combo=visual_reply_size_combo,
        model_edit=visual_reply_model_edit,
        api_key_edit=visual_reply_api_key_edit,
        auto_show_checkbox=visual_reply_auto_show_checkbox,
        hint_label=visual_reply_hint,
    )
    visual_reply_service.refresh_hint()

    def refresh_status():
        return _ui_shell_refresh_host_core_status(window)

    bound = []

    def bind_combo(combo, attr_name, message_factory, on_changed=None):
        if combo is None or not hasattr(combo, "currentIndexChanged"):
            return
        bound.append(str(combo.objectName() if hasattr(combo, "objectName") else attr_name))
        if getattr(combo, attr_name, False):
            return
        on_changed_callback = on_changed

        def handle(_index=None):
            if callable(on_changed_callback):
                on_changed_callback(_index)
            refresh_status()
            _ui_shell_append_console(window, message_factory())

        combo.currentIndexChanged.connect(handle)
        setattr(combo, attr_name, True)

    def bind_spin(widget, attr_name, message_factory):
        if widget is None or not hasattr(widget, "valueChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def on_changed(_value=None):
            refresh_status()
            _ui_shell_append_console(window, message_factory())

        widget.valueChanged.connect(on_changed)
        setattr(widget, attr_name, True)

    def bind_check(widget, attr_name, message_factory, on_changed=None):
        if widget is None or not hasattr(widget, "toggled"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            if callable(on_changed):
                on_changed(bool(widget.isChecked()) if hasattr(widget, "isChecked") else bool(_checked))
            refresh_status()
            _ui_shell_append_console(window, message_factory())

        widget.toggled.connect(handle)
        setattr(widget, attr_name, True)

    bind_combo(
        audio_input_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Audio input preview: {str(audio_input_combo.currentText() or 'Default Input').strip()} selected; capture remains deferred.",
    )
    bind_combo(
        audio_output_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Audio output preview: {str(audio_output_combo.currentText() or 'Default Output').strip()} selected; playback remains deferred.",
    )
    bind_combo(
        input_mode_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Input Mode preview: {str(input_mode_combo.currentText() or 'Voice Activation').strip()} selected; runtime input handling remains disconnected.",
    )
    bind_combo(
        input_role_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Input Role preview: {str(input_role_combo.currentText() or 'User Message').strip()} selected; runtime message routing remains disconnected.",
    )
    bind_combo(
        stream_mode_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Stream Mode preview: {str(stream_mode_combo.currentText() or 'Off').strip()} selected; live provider streaming remains deferred.",
    )
    bind_combo(
        musetalk_vram_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] MuseTalk VRAM preview: {str(musetalk_vram_combo.currentText() or 'Quality').strip()} selected; no runtime reconfiguration was applied.",
    )
    bind_combo(
        musetalk_avatar_pack_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] MuseTalk avatar pack preview: {str(musetalk_avatar_pack_combo.currentText() or 'No avatar packs found').strip()} selected; no adapter was rebuilt.",
    )
    bind_combo(
        overflow_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Chat overflow preview: {str(overflow_combo.currentText() or 'Rolling Window').strip()} selected; chat-context files and runtime limits remain unchanged.",
    )
    bind_spin(
        context_window_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Chat context window preview: {int(context_window_spin.value()) if hasattr(context_window_spin, 'value') else 20} message(s); runtime context remains unchanged.",
    )
    bind_spin(
        stored_history_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Stored history preview: {int(stored_history_spin.value()) if hasattr(stored_history_spin, 'value') else 0} message(s); no session file was updated.",
    )
    bind_check(
        allow_proactive_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Proactive replies preview: {'enabled' if allow_proactive_checkbox.isChecked() else 'disabled'}; runtime behavior remains unchanged.",
    )
    bind_check(
        require_first_user_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] First-user gate preview: {'enabled' if require_first_user_checkbox.isChecked() else 'disabled'}; runtime behavior remains unchanged.",
    )
    bind_spin(
        listen_idle_window_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Idle wait preview: {float(listen_idle_window_spin.value()) if hasattr(listen_idle_window_spin, 'value') else 5.0:.1f}s; runtime behavior remains unchanged.",
    )
    bind_spin(
        proactive_delay_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Proactive delay preview: {float(proactive_delay_spin.value()) if hasattr(proactive_delay_spin, 'value') else 10.0:.1f}s; runtime behavior remains unchanged.",
    )
    bind_check(
        limit_response_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Response limit preview: {'enabled' if limit_response_checkbox.isChecked() else 'disabled'}; runtime behavior remains unchanged.",
        on_changed=lambda checked: max_response_tokens_spin.setEnabled(bool(checked)) if max_response_tokens_spin is not None and hasattr(max_response_tokens_spin, "setEnabled") else None,
    )
    bind_spin(
        max_response_tokens_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Max response preview: {int(max_response_tokens_spin.value()) if hasattr(max_response_tokens_spin, 'value') else default_max_response_tokens} token(s); runtime behavior remains unchanged.",
    )
    bind_combo(
        sensory_feedback_source_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Sensory source preview: {str(sensory_feedback_source_combo.currentText() or 'Off').strip()} selected; capture remains deferred.",
    )
    bind_spin(
        sensory_feedback_interval_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Sensory refresh preview: {float(sensory_feedback_interval_spin.value()) if hasattr(sensory_feedback_interval_spin, 'value') else 7.0:.1f}s; hidden capture remains deferred.",
    )
    bind_check(
        sensory_pingpong_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden PING/PONG preview: {'enabled' if sensory_pingpong_checkbox.isChecked() else 'disabled'}; no hidden loop was started.",
    )
    bind_check(
        sensory_allow_hidden_proactive_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden proactive speech preview: {'enabled' if sensory_allow_hidden_proactive_checkbox.isChecked() else 'disabled'}; no runtime behavior changed.",
    )
    bind_check(
        sensory_allow_hidden_visual_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden visual generation preview: {'enabled' if sensory_allow_hidden_visual_checkbox.isChecked() else 'disabled'}; no runtime behavior changed.",
    )
    bind_spin(
        sensory_pingpong_history_spin,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Hidden PING/PONG history preview: {int(sensory_pingpong_history_spin.value()) if hasattr(sensory_pingpong_history_spin, 'value') else 3}; runtime behavior remains unchanged.",
    )
    bind_combo(
        visual_reply_mode_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply mode preview: {str(visual_reply_mode_combo.currentText() or 'Auto').strip()} selected; no image generation was started.",
        on_changed=lambda _checked=None: (visual_reply_service.apply_mode(visual_reply_mode_combo.currentText()), visual_reply_service.refresh_hint()),
    )
    bind_combo(
        visual_reply_provider_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply provider preview: {str(visual_reply_provider_combo.currentText() or 'OpenAI').strip()} selected; no network call was made.",
        on_changed=lambda _checked=None: (visual_reply_service.apply_provider(visual_reply_provider_combo.currentText()), visual_reply_service.refresh_hint()),
    )
    bind_combo(
        visual_reply_size_combo,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply size preview: {str(visual_reply_size_combo.currentText() or '1024x1024').strip()} selected; no image generation was started.",
        on_changed=lambda _checked=None: (visual_reply_service.apply_size(visual_reply_size_combo.currentText()), visual_reply_service.refresh_hint()),
    )
    bind_check(
        visual_reply_auto_show_checkbox,
        "_nc_ui_shell_host_core_bound",
        lambda: f"[UI Shell] Visual Reply auto-show preview: {'enabled' if visual_reply_auto_show_checkbox.isChecked() else 'disabled'}; dock behavior remains shell-local.",
        on_changed=lambda checked: (visual_reply_service.apply_auto_show(checked), visual_reply_service.refresh_hint()),
    )
    if visual_reply_model_edit is not None and hasattr(visual_reply_model_edit, "editingFinished"):
        bound.append(str(visual_reply_model_edit.objectName() if hasattr(visual_reply_model_edit, "objectName") else "visual_reply_model_edit"))
        if not getattr(visual_reply_model_edit, "_nc_ui_shell_host_core_bound", False):
            def on_visual_model_changed():
                visual_reply_service.apply_model()
                refresh_status()
                _ui_shell_append_console(window, f"[UI Shell] Visual Reply model preview: {str(visual_reply_model_edit.text() or 'gpt-image-1').strip()} selected; no image generation was started.")
            visual_reply_model_edit.editingFinished.connect(on_visual_model_changed)
            setattr(visual_reply_model_edit, "_nc_ui_shell_host_core_bound", True)
    if visual_reply_api_key_edit is not None and hasattr(visual_reply_api_key_edit, "editingFinished"):
        bound.append(str(visual_reply_api_key_edit.objectName() if hasattr(visual_reply_api_key_edit, "objectName") else "visual_reply_api_key_edit"))
        if not getattr(visual_reply_api_key_edit, "_nc_ui_shell_host_core_bound", False):
            def on_visual_api_key_changed():
                visual_reply_service.apply_api_key()
                refresh_status()
                _ui_shell_append_console(window, "[UI Shell] Visual Reply API key preview updated; no network call was made.")
            visual_reply_api_key_edit.editingFinished.connect(on_visual_api_key_changed)
            setattr(visual_reply_api_key_edit, "_nc_ui_shell_host_core_bound", True)

    refresh_status()
    return {
        "bound": bound,
        "audio_inputs": max(0, len(list(audio_devices.get("inputs") or [])) - 1),
        "audio_outputs": max(0, len(list(audio_devices.get("outputs") or [])) - 1),
        "avatar_packs": len(avatar_pack_options),
        "sensory_providers": len(list(sensory_providers or [])),
    }
