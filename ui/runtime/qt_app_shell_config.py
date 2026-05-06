"""Dependency wiring for the runtime-backed Designer UI.

This module intentionally keeps the old qt_app wiring functions as thin,
relocatable glue. qt_app injects its current globals before using these
functions so the runtime bridge can be carved out without changing behavior.
"""

_DEPENDENCY_KEYS_TO_SKIP = {"__name__", "__package__", "__spec__", "__loader__", "__cached__"}

from ui.runtime.qt_app_shell_service_factories import (
    configure_qt_app_shell_service_factory_dependencies,
    _ui_shell_chat_context_service,
    _ui_shell_chat_replay_service,
    _ui_shell_dry_run_service,
    _ui_shell_engine_lifecycle_service,
    _ui_shell_input_actions_service,
    _ui_shell_input_settings_service,
    _ui_shell_model_refresh_service,
    _ui_shell_performance_profile_service,
    _ui_shell_persona_avatar_service,
    _ui_shell_runtime_controls_service,
    _ui_shell_runtime_status_service,
    _ui_shell_tutorial_service,
)


def configure_qt_app_shell_dependencies(dependencies):
    """Provide qt_app symbols used by the migrated wiring functions."""
    for key, value in dict(dependencies or {}).items():
        if key not in _DEPENDENCY_KEYS_TO_SKIP:
            globals()[key] = value
    configure_qt_app_shell_service_factory_dependencies(globals())


def _configure_real_ui_bridge_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    configure_real_ui_bridge_dependencies({
        "APP_THEME_PRESET_LABELS": APP_THEME_PRESET_LABELS,
        "APP_THEME_PRESET_WIDGETS": APP_THEME_PRESET_WIDGETS,
        "APP_TITLE": APP_TITLE,
        "AddonCapabilityBridgeService": AddonCapabilityBridgeService,
        "CompanionQtMainWindow": CompanionQtMainWindow,
        "DEFAULT_APP_THEME_PRESET": DEFAULT_APP_THEME_PRESET,
        "QtChatContextService": QtChatContextService,
        "QtEngineLifecycleService": QtEngineLifecycleService,
        "QtInputActionService": QtInputActionService,
        "QtModelRefreshService": QtModelRefreshService,
        "QtRuntimeControlService": QtRuntimeControlService,
        "QtRuntimeStatusService": QtRuntimeStatusService,
        "QtVisualReplyPanel": QtVisualReplyPanel,
        "RUNTIME_CONFIG": RUNTIME_CONFIG,
        "SESSION_PATH": SESSION_PATH,
        "UI_REAL_PREVIEW_ONLY_ROOTS": UI_REAL_PREVIEW_ONLY_ROOTS,
        "UI_SHELL_BODY_POSE_SPECS": UI_SHELL_BODY_POSE_SPECS,
        "UI_SHELL_CHUNKING_SPECS": UI_SHELL_CHUNKING_SPECS,
        "__file__": __file__,
        "_WIN32_DOCK_OWNER_SUPPORTED": _WIN32_DOCK_OWNER_SUPPORTED,
        "_WIN32_GWLP_HWNDPARENT": _WIN32_GWLP_HWNDPARENT,
        "_win32_set_window_owner": _win32_set_window_owner,
        "_app_theme_palette": _app_theme_palette,
        "_apply_engine_action_button_accents": _apply_engine_action_button_accents,
        "_apply_inline_theme_styles": _apply_inline_theme_styles,
        "_apply_readable_input_palettes": _apply_readable_input_palettes,
        "_apply_workspace_view_constraints": _apply_workspace_view_constraints,
        "_build_app_stylesheet_for_preset": _build_app_stylesheet_for_preset,
        "_normalize_app_theme_preset_id": _normalize_app_theme_preset_id,
        "_read_ui_shell_session_snapshot": _read_ui_shell_session_snapshot,
        "_load_ui_preview_window": _load_ui_preview_window,
        "_resolve_ui_path": _resolve_ui_path,
        "_split_collapsible_section_text": _split_collapsible_section_text,
        "_ui_shell_audio_device_labels": _ui_shell_audio_device_labels,
        "_ui_shell_body_slider_raw_to_value": _ui_shell_body_slider_raw_to_value,
        "_ui_shell_body_value_to_slider_raw": _ui_shell_body_value_to_slider_raw,
        "_ui_shell_chunking_slider_spec": _ui_shell_chunking_slider_spec,
        "_ui_shell_combo_select_label": _ui_shell_combo_select_label,
        "_ui_shell_combo_set_items": _ui_shell_combo_set_items,
        "_ui_shell_update_body_label": _ui_shell_update_body_label,
        "_ui_shell_update_chunking_label": _ui_shell_update_chunking_label,
        "ctypes": ctypes,
        "engine": engine,
        "shared_state": shared_state,
        "tutorial_framework": tutorial_framework,
        "update_runtime_config": update_runtime_config,
    })


def _configure_app_entry_dependencies():
    configure_app_entry_dependencies({
        "APP_TITLE": APP_TITLE,
        "CompanionQtMainWindow": CompanionQtMainWindow,
        "MainUiRealRuntimeBridge": MainUiRealRuntimeBridge,
        "SESSION_PATH": SESSION_PATH,
        "_configure_main_window_docking": _configure_main_window_docking,
        "_configure_real_ui_bridge_dependencies": _configure_real_ui_bridge_dependencies,
        "_install_no_wheel_input_guard": _install_no_wheel_input_guard,
        "_load_ui_preview_window": _load_ui_preview_window,
        "_resolve_ui_path": _resolve_ui_path,
    })


def _configure_ui_shell_service_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    _configure_ui_shell_addon_report_dependencies()
    configure_qt_app_shell_service_factory_dependencies(globals())
    configure_shell_service_dependencies(globals())


def _configure_ui_shell_addon_report_dependencies():
    configure_shell_addon_report_dependencies(globals())
    configure_shell_addon_mount_dependencies(globals())




def _configure_ui_shell_status_layout_dependencies():
    _configure_ui_shell_addon_report_dependencies()
    configure_shell_status_layout_dependencies(globals())




def _configure_ui_shell_local_bindings_dependencies():
    _configure_ui_shell_status_layout_dependencies()
    configure_shell_local_bindings_dependencies(globals())




def _configure_ui_shell_runtime_cards_dependencies():
    _configure_ui_shell_local_bindings_dependencies()
    configure_shell_runtime_cards_dependencies(globals())




def _configure_ui_shell_session_config_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    configure_shell_session_config_dependencies(globals())




def _configure_ui_shell_chunking_profiles_dependencies():
    _configure_ui_shell_session_config_dependencies()
    configure_shell_chunking_profiles_dependencies(globals())




































































































def _ui_shell_dry_run_status_text(latest, *, target_samples=0, auto_replies=True, preview_state="idle"):
    latest = dict(latest or {})
    if preview_state == "armed":
        target_text = "Auto" if int(target_samples or 0) <= 0 else str(int(target_samples))
        return f"Dry Run shell preview armed for {target_text} sample(s)." + (" Hands-free preview enabled." if auto_replies else "")
    if latest:
        confidence = float(latest.get("confidence", 0.0) or 0.0)
        stability = float(latest.get("stability", 0.0) or 0.0)
        return f"Dry Run idle. Last saved profile confidence {confidence:.2f}, stability {stability:.2f}."
    return "Dry Run idle."


def _ui_shell_dry_run_summary_text(latest, *, target_samples=0, auto_replies=True, preview_state="idle"):
    latest = dict(latest or {})
    if preview_state == "armed":
        target_text = "Auto" if int(target_samples or 0) <= 0 else str(int(target_samples))
        return (
            "Shell preview only.\n"
            f"- Requested target samples: {target_text}\n"
            f"- Hands-free preview: {'enabled' if auto_replies else 'disabled'}\n"
            "- Starting a real Dry Run session remains deferred in --ui-shell.\n"
            "- No engine, model, or profiling worker was started."
        )
    if not latest:
        return "Arm a Dry Run to collect reply samples and generate machine-specific recommendations."
    summary = dict(latest.get("summary") or {})
    recommendation = dict(latest.get("recommendation") or {})
    settings = dict(recommendation.get("settings") or {})
    lines = [
        "Latest saved Dry Run profile:",
        f"- Name: {str(latest.get('saved_name') or latest.get('display_name') or '<unnamed>').strip()}",
        f"- Sample count: {int(latest.get('sample_count', 0) or 0)}",
        f"- Confidence: {float(latest.get('confidence', 0.0) or 0.0):.2f}",
        f"- Stability: {float(latest.get('stability', 0.0) or 0.0):.2f}",
    ]
    updated_at = latest.get("updated_at")
    try:
        lines.append(f"- Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(updated_at)))}")
    except Exception:
        pass
    if summary:
        lines.extend([
            "",
            "Measured startup profile:",
            f"- Avg first audio chunk: {float(summary.get('avg_first_audio_chunk_ms', 0.0) or 0.0):.1f} ms",
            f"- Avg first visual buffer wait: {float(summary.get('avg_buffer_wait_ms', 0.0) or 0.0):.1f} ms",
            f"- Avg chunk quality: {float(summary.get('avg_chunk_quality', 0.0) or 0.0):.2f}",
            f"- Avg emitted chunk chars: {float(summary.get('avg_chunk_chars', 0.0) or 0.0):.1f}",
        ])
    if settings:
        lines.extend([
            "",
            "Recommended visible settings:",
            f"- Stream mode: {'On' if bool(settings.get('stream_mode')) else 'Off'}",
            f"- MuseTalk VRAM: {UI_SHELL_MUSE_VRAM_MODE_LABELS.get(str(settings.get('musetalk_vram_mode') or '').strip().lower(), 'Quality')}",
        ])
        for key in (
            "stream_chunk_target_chars",
            "stream_chunk_max_chars",
            "stream_first_chunk_min_chars",
            "musetalk_chunk_target_chars",
            "musetalk_chunk_max_chars",
            "musetalk_quickstart_1_target_chars",
        ):
            if key in settings:
                title = str(_ui_shell_chunking_slider_spec(key).get("title") or key).strip()
                lines.append(f"- {title}: {_ui_shell_format_chunking_value(settings.get(key))}")
        lines.extend([
            "",
            "Use Apply Recommendation to preview the shell-visible subset only.",
        ])
    else:
        lines.extend([
            "",
            "No saved recommendation settings were found in the latest profile.",
        ])
    lines.extend([
        "",
        "Shell preview note:",
        "- Dry Run start/stop remains deferred here.",
    ])
    return "\n".join(lines)




























def _apply_ui_shell_read_only_config(window):
    session = _read_ui_shell_session_snapshot()
    audio_devices = _ui_shell_audio_device_labels()
    avatar_pack_options = _ui_shell_musetalk_avatar_pack_options(session)
    provider_labels = {
        "lmstudio": "LM Studio",
        "openai": "OpenAI",
        "xai": "xAI / Grok",
        "claude": "Claude",
    }
    visual_mode_labels = {
        "off": "Off",
        "manual": "Manual",
        "auto": "Auto",
    }
    tts_labels = {
        "chatterbox": "Chatterbox",
        "pockettts": "PocketTTS",
        "gemini_tts_preview": "Gemini TTS Preview",
    }
    avatar_labels = {
        "vseeface": "VSeeFace",
        "musetalk": "MuseTalk",
        "vam": "VaM",
        "none": "None",
    }
    applied = []

    combo_specs = (
        ("audio_input_device_combo", list(audio_devices.get("inputs") or ["Default Input"]), session.get("audio_input_device", "Default Input")),
        ("audio_output_device_combo", list(audio_devices.get("outputs") or ["Default Output"]), session.get("audio_output_device", "Default Output")),
        ("engine_combo", list(avatar_labels.values()), avatar_labels.get(str(session.get("avatar_mode", "")).strip().lower(), session.get("avatar_mode", ""))),
        ("input_mode_combo", ["Voice Activation", "Push-to-Talk"], session.get("input_mode", "")),
        ("input_role_combo", ["User Message", "System Message", "Assistant Message"], session.get("input_message_role", "")),
        ("stream_mode_combo", ["Off", "On"], session.get("stream_mode", "")),
        ("tts_backend_combo", list(tts_labels.values()), tts_labels.get(str(session.get("tts_backend", "")).strip().lower(), session.get("tts_backend", ""))),
        ("chat_provider_combo", list(provider_labels.values()), provider_labels.get(str(session.get("chat_provider", "")).strip().lower(), session.get("chat_provider", ""))),
        ("musetalk_vram_combo", ["Quality", "Balanced", "Low VRAM", "Very Low VRAM"], str(session.get("musetalk_vram_mode", "") or "").replace("_", " ").title().replace("Vram", "VRAM")),
        (
            "musetalk_avatar_pack_combo",
            [str(item.get("label") or "").strip() for item in avatar_pack_options] or [str(session.get("musetalk_avatar_pack_id", "") or "No avatar packs found")],
            next(
                (
                    str(item.get("label") or "").strip()
                    for item in avatar_pack_options
                    if str(item.get("id") or "").strip() == str(session.get("musetalk_avatar_pack_id", "") or "").strip()
                ),
                session.get("musetalk_avatar_pack_id", ""),
            ),
        ),
        (
            "chat_overflow_policy_combo",
            ["Rolling Window", "Truncate Middle", "Stop At Limit"],
            {
                "rolling_window": "Rolling Window",
                "truncate_middle": "Truncate Middle",
                "stop_at_limit": "Stop At Limit",
            }.get(str(session.get("chat_context_overflow_policy", "rolling_window") or "rolling_window").strip(), session.get("chat_context_overflow_policy", "")),
        ),
        ("visual_reply_mode_combo", ["Off", "Manual", "Auto"], visual_mode_labels.get(str(session.get("visual_reply_mode", "")).strip().lower(), session.get("visual_reply_mode", ""))),
        ("visual_reply_provider_combo", ["OpenAI", "xAI / Grok"], provider_labels.get(str(session.get("visual_reply_provider", "")).strip().lower(), session.get("visual_reply_provider", ""))),
        ("visual_reply_size_combo", ["1024x1024", "1024x1792", "1792x1024"], session.get("visual_reply_size", "")),
    )
    for object_name, labels, selected in combo_specs:
        combo = _ui_shell_find_object(window, object_name)
        _ui_shell_combo_set_items(combo, labels)
        if _ui_shell_combo_select_label(combo, selected):
            applied.append(object_name)
        _ui_shell_set_read_only_tooltip(combo)

    preset_combo = _ui_shell_find_object(window, "preset_combo")
    preset_names = _ui_shell_preset_names()
    _ui_shell_combo_set_items(preset_combo, preset_names or ["No presets found"])
    if _ui_shell_combo_select_label(preset_combo, session.get("last_preset", "")):
        applied.append("preset_combo")
    _ui_shell_set_read_only_tooltip(preset_combo)

    model_combo = _ui_shell_find_object(window, "model_combo")
    model_name = str(session.get("model_name", "") or "").strip()
    _ui_shell_combo_set_items(model_combo, [model_name] if model_name else ["No model saved"])
    if model_name and _ui_shell_combo_select_label(model_combo, model_name):
        applied.append("model_combo")
    _ui_shell_set_read_only_tooltip(model_combo, "Model refresh is not connected.")

    visual_model = _ui_shell_find_object(window, "visual_reply_model_edit")
    if visual_model is not None and hasattr(visual_model, "setText"):
        visual_model.setText(str(session.get("visual_reply_model", "") or ""))
        _ui_shell_set_read_only_tooltip(visual_model)
        applied.append("visual_reply_model_edit")

    numeric_specs = (
        ("chat_context_window_spin", session.get("chat_context_window_messages")),
        ("stored_chat_history_limit_spin", session.get("stored_chat_history_limit")),
        ("musetalk_loop_fade_spin", session.get("musetalk_loop_fade_ms")),
        ("tts_seed_spin", session.get("tts_seed")),
    )
    for object_name, value in numeric_specs:
        if value is None:
            continue
        widget = _ui_shell_find_object(window, object_name)
        if _ui_shell_set_spin_value(widget, value):
            _ui_shell_set_read_only_tooltip(widget)
            applied.append(object_name)

    double_specs = (
        ("tts_temperature_spin", session.get("tts_temperature")),
        ("tts_top_p_spin", session.get("tts_top_p")),
        ("tts_repeat_penalty_spin", session.get("tts_repeat_penalty")),
        ("tts_min_p_spin", session.get("tts_min_p")),
    )
    for object_name, value in double_specs:
        if value is None:
            continue
        widget = _ui_shell_find_object(window, object_name)
        if _ui_shell_set_double_value(widget, value):
            _ui_shell_set_read_only_tooltip(widget)
            applied.append(object_name)

    top_k_spin = _ui_shell_find_object(window, "tts_top_k_spin")
    if _ui_shell_set_spin_value(top_k_spin, session.get("tts_top_k", 0)):
        _ui_shell_set_read_only_tooltip(top_k_spin)
        applied.append("tts_top_k_spin")

    normalize_checkbox = _ui_shell_find_object(window, "tts_normalize_loudness_checkbox")
    if _ui_shell_set_checked(normalize_checkbox, session.get("tts_normalize_loudness", False)):
        _ui_shell_set_read_only_tooltip(normalize_checkbox)
        applied.append("tts_normalize_loudness_checkbox")

    provider_placeholder = _ui_shell_find_object(window, "chat_provider_fields_placeholder")
    if provider_placeholder is not None and hasattr(provider_placeholder, "setText"):
        provider_placeholder.setText("Read-only shell preview. Provider-specific fields mount here in the live app.")
    generation_placeholder = _ui_shell_find_object(window, "chat_provider_generation_fields_placeholder")
    if generation_placeholder is not None and hasattr(generation_placeholder, "setText"):
        generation_placeholder.setText("Read-only shell preview. Generation controls mount here in the live app.")

    return {
        "session_loaded": bool(session),
        "applied": sorted(set(applied)),
        "session_path": str(Path(__file__).resolve().parent / "qt_session.json"),
    }


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
        _ui_shell_set_checked(allow_proactive_checkbox, session.get("allow_proactive_replies", True))
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
        _ui_shell_combo_select_label(visual_reply_mode_combo, visual_reply_service.mode_label_from_value(visual_reply_snapshot.get("mode_value", "auto")))
    if visual_reply_provider_combo is not None:
        _ui_shell_combo_set_items(visual_reply_provider_combo, list(visual_reply_service.provider_labels()))
        _ui_shell_combo_select_label(visual_reply_provider_combo, visual_reply_service.provider_label_from_value(visual_reply_snapshot.get("provider_value", "openai")))
    if visual_reply_size_combo is not None:
        _ui_shell_combo_set_items(visual_reply_size_combo, list(visual_reply_service.size_labels()))
        _ui_shell_combo_select_label(visual_reply_size_combo, visual_reply_service.size_label_from_value(visual_reply_snapshot.get("size_value", "1024x1024")))
    if visual_reply_model_edit is not None and hasattr(visual_reply_model_edit, "setText"):
        visual_reply_model_edit.setText(str(visual_reply_snapshot.get("model_name", "gpt-image-1") or "gpt-image-1"))
    if visual_reply_auto_show_checkbox is not None:
        _ui_shell_set_checked(visual_reply_auto_show_checkbox, visual_reply_snapshot.get("auto_show", True))
    visual_reply_service.attach_settings_widgets(
        mode_combo=visual_reply_mode_combo,
        provider_combo=visual_reply_provider_combo,
        size_combo=visual_reply_size_combo,
        model_edit=visual_reply_model_edit,
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

    refresh_status()
    return {
        "bound": bound,
        "audio_inputs": max(0, len(list(audio_devices.get("inputs") or [])) - 1),
        "audio_outputs": max(0, len(list(audio_devices.get("outputs") or [])) - 1),
        "avatar_packs": len(avatar_pack_options),
        "sensory_providers": len(list(sensory_providers or [])),
    }




def _bind_ui_shell_dry_run_controls(window):
    session = dict(_read_ui_shell_session_snapshot() or {})
    service = _ui_shell_dry_run_service(window)
    bound = []
    deferred = ["btn_dry_run_start", "btn_dry_run_stop"]

    target_spin = _ui_shell_find_object(window, "dry_run_target_spin")
    auto_replies_checkbox = _ui_shell_find_object(window, "dry_run_auto_replies_checkbox")
    start_button = _ui_shell_find_object(window, "btn_dry_run_start")
    stop_button = _ui_shell_find_object(window, "btn_dry_run_stop")
    apply_button = _ui_shell_find_object(window, "btn_dry_run_apply")
    status_label = _ui_shell_find_object(window, "dry_run_status_label")
    summary_edit = _ui_shell_find_object(window, "dry_run_summary")

    if target_spin is not None:
        _ui_shell_set_spin_value(target_spin, int(session.get("dry_run_target_samples", 0) or 0))
        if hasattr(target_spin, "setToolTip"):
            target_spin.setToolTip("Shell-local Dry Run preview target. No profiling session is started.")
    if auto_replies_checkbox is not None:
        _ui_shell_set_checked(auto_replies_checkbox, bool(session.get("dry_run_auto_replies", True)))
        if hasattr(auto_replies_checkbox, "setToolTip"):
            auto_replies_checkbox.setToolTip("Shell-local Dry Run hands-free preview. No profiling session is started.")
    if summary_edit is not None:
        try:
            summary_edit.setReadOnly(True)
        except Exception:
            pass
        if hasattr(summary_edit, "setToolTip"):
            summary_edit.setToolTip("Shell-local Dry Run preview summary. No profiling metrics are collected here.")

    def refresh_preview():
        snapshot = service.refresh_preview()
        if status_label is not None and hasattr(status_label, "setText"):
            status_label.setText(str(snapshot.get("status_text") or "Dry Run idle."))
        if summary_edit is not None and hasattr(summary_edit, "setPlainText"):
            summary_edit.setPlainText(str(snapshot.get("summary_text") or ""))
        if stop_button is not None and hasattr(stop_button, "setEnabled"):
            stop_button.setEnabled(str(snapshot.get("state") or "idle") == "armed")
        if start_button is not None and hasattr(start_button, "setEnabled"):
            start_button.setEnabled(str(snapshot.get("state") or "idle") != "armed")
        if apply_button is not None and hasattr(apply_button, "setEnabled"):
            apply_button.setEnabled(bool(snapshot.get("has_recommendation")))
        return snapshot

    def bind_spin(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "valueChanged"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_value=None):
            refresh_preview()
            _ui_shell_append_console(window, on_log())

        widget.valueChanged.connect(handle)
        setattr(widget, attr_name, True)

    def bind_check(widget, attr_name, on_log):
        if widget is None or not hasattr(widget, "toggled"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            refresh_preview()
            _ui_shell_append_console(window, on_log())

        widget.toggled.connect(handle)
        setattr(widget, attr_name, True)

    def bind_button(widget, attr_name, handler):
        if widget is None or not hasattr(widget, "clicked"):
            return
        bound.append(str(widget.objectName() if hasattr(widget, "objectName") else attr_name))
        if getattr(widget, attr_name, False):
            return

        def handle(_checked=False):
            handler()

        widget.clicked.connect(handle)
        setattr(widget, attr_name, True)

    bind_spin(
        target_spin,
        "_nc_ui_shell_dry_run_bound",
        lambda: f"[UI Shell] Dry Run target preview: {int(target_spin.value()) if hasattr(target_spin, 'value') else 0} sample(s); no profiling session was started.",
    )
    bind_check(
        auto_replies_checkbox,
        "_nc_ui_shell_dry_run_bound",
        lambda: f"[UI Shell] Dry Run hands-free preview: {'enabled' if auto_replies_checkbox.isChecked() else 'disabled'}; no profiling session was started.",
    )
    bind_button(
        start_button,
        "_nc_ui_shell_dry_run_bound",
        lambda: (
            service.start_session(),
            refresh_preview(),
            _ui_shell_append_console(window, "[UI Shell] Dry Run arm request deferred; no engine, model, or profiling worker was started."),
        ),
    )
    bind_button(
        stop_button,
        "_nc_ui_shell_dry_run_bound",
        lambda: (
            service.stop_session(),
            refresh_preview(),
            _ui_shell_append_console(window, "[UI Shell] Dry Run stop request deferred; no profiling session was running."),
        ),
    )

    def apply_recommendation():
        result = service.apply_recommendation()
        refresh_preview()
        if result.get("applied"):
            deferred_keys = [str(key) for key in list(result.get("deferred_keys") or []) if str(key).strip()]
            deferred_suffix = f" Deferred keys: {', '.join(deferred_keys)}." if deferred_keys else ""
            _ui_shell_append_console(window, f"[UI Shell] Dry Run recommendation preview applied to the shell-visible subset only.{deferred_suffix}")
        else:
            _ui_shell_append_console(window, f"[UI Shell] {result.get('message') or 'No saved Dry Run recommendation is available.'}")

    bind_button(apply_button, "_nc_ui_shell_dry_run_bound", apply_recommendation)

    refresh_preview()
    return {
        "bound": bound,
        "deferred": sorted(set(deferred)),
        "has_recommendation": bool(service.snapshot().get("has_recommendation")),
    }


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




def _configure_ui_shell_smoke_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    _configure_ui_shell_addon_report_dependencies()
    configure_ui_shell_smoke_dependencies({
        "UI_VALIDATION_REQUIRED_GROUPS": UI_VALIDATION_REQUIRED_GROUPS,
        "_apply_ui_shell_addon_placeholders": _apply_ui_shell_addon_placeholders,
        "_apply_ui_shell_read_only_config": _apply_ui_shell_read_only_config,
        "_bind_ui_shell_avatar_runtime": _bind_ui_shell_avatar_runtime,
        "_bind_ui_shell_chat_context_controls": _bind_ui_shell_chat_context_controls,
        "_bind_ui_shell_chat_runtime": _bind_ui_shell_chat_runtime,
        "_bind_ui_shell_chunking_profile_controls": _bind_ui_shell_chunking_profile_controls,
        "_bind_ui_shell_dry_run_controls": _bind_ui_shell_dry_run_controls,
        "_bind_ui_shell_host_core_controls": _bind_ui_shell_host_core_controls,
        "_bind_ui_shell_input_action_controls": _bind_ui_shell_input_action_controls,
        "_bind_ui_shell_lifecycle_local_controls": _bind_ui_shell_lifecycle_local_controls,
        "_bind_ui_shell_persona_body_vam_controls": _bind_ui_shell_persona_body_vam_controls,
        "_bind_ui_shell_preset_session_controls": _bind_ui_shell_preset_session_controls,
        "_bind_ui_shell_runtime_action_controls": _bind_ui_shell_runtime_action_controls,
        "_bind_ui_shell_tts_runtime": _bind_ui_shell_tts_runtime,
        "_bind_ui_shell_tutorial_controls": _bind_ui_shell_tutorial_controls,
        "_load_ui_shell_for_smoke": _load_ui_shell_for_smoke,
        "_print_ui_shell_addon_mount_report": _print_ui_shell_addon_mount_report,
        "_print_ui_shell_static_addon_comparison": _print_ui_shell_static_addon_comparison,
        "_resolve_ui_path": _resolve_ui_path,
        "_ui_shell_addon_mount_report": _ui_shell_addon_mount_report,
        "_ui_shell_class_matches": _ui_shell_class_matches,
        "_ui_shell_cleanup_live_addons": _ui_shell_cleanup_live_addons,
        "_ui_shell_compose_status_line": _ui_shell_compose_status_line,
        "_ui_shell_find_object": _ui_shell_find_object,
        "_ui_shell_mount_live_addons": _ui_shell_mount_live_addons,
    })


def _configure_ui_shell_preview_dependencies():
    _configure_ui_shell_runtime_cards_dependencies()
    _configure_ui_shell_session_config_dependencies()
    _configure_ui_shell_chunking_profiles_dependencies()
    _configure_ui_shell_local_bindings_dependencies()
    _configure_ui_shell_status_layout_dependencies()
    _configure_ui_shell_addon_report_dependencies()
    configure_ui_shell_preview_dependencies({
        "_QtWidgets": _QtWidgets,
        "_apply_ui_shell_addon_placeholders": _apply_ui_shell_addon_placeholders,
        "_apply_ui_shell_preview_status": _apply_ui_shell_preview_status,
        "_apply_ui_shell_read_only_config": _apply_ui_shell_read_only_config,
        "_bind_ui_shell_avatar_runtime": _bind_ui_shell_avatar_runtime,
        "_bind_ui_shell_chat_context_controls": _bind_ui_shell_chat_context_controls,
        "_bind_ui_shell_chat_runtime": _bind_ui_shell_chat_runtime,
        "_bind_ui_shell_chunking_profile_controls": _bind_ui_shell_chunking_profile_controls,
        "_bind_ui_shell_console_chat_local_controls": _bind_ui_shell_console_chat_local_controls,
        "_bind_ui_shell_dry_run_controls": _bind_ui_shell_dry_run_controls,
        "_bind_ui_shell_host_core_controls": _bind_ui_shell_host_core_controls,
        "_bind_ui_shell_input_action_controls": _bind_ui_shell_input_action_controls,
        "_bind_ui_shell_lifecycle_local_controls": _bind_ui_shell_lifecycle_local_controls,
        "_bind_ui_shell_persona_body_vam_controls": _bind_ui_shell_persona_body_vam_controls,
        "_bind_ui_shell_preset_session_controls": _bind_ui_shell_preset_session_controls,
        "_bind_ui_shell_runtime_action_controls": _bind_ui_shell_runtime_action_controls,
        "_bind_ui_shell_tts_runtime": _bind_ui_shell_tts_runtime,
        "_bind_ui_shell_tutorial_controls": _bind_ui_shell_tutorial_controls,
        "_load_ui_shell_for_smoke": _load_ui_shell_for_smoke,
        "_print_ui_shell_static_addon_comparison": _print_ui_shell_static_addon_comparison,
        "_resolve_ui_path": _resolve_ui_path,
        "_ui_shell_addon_mount_report": _ui_shell_addon_mount_report,
        "_ui_shell_cleanup_live_addons": _ui_shell_cleanup_live_addons,
        "_ui_shell_compose_status_line": _ui_shell_compose_status_line,
        "_ui_shell_mount_live_addons": _ui_shell_mount_live_addons,
    })

