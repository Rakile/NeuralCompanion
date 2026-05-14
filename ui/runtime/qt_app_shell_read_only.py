"""Read-only shell preview population for the Designer UI."""

from core.musetalk_session_schema import with_flat_musetalk_settings
from core.sensory_session_schema import with_flat_sensory_settings
from core.tts_session_schema import with_flat_tts_runtime_settings

_DEPENDENCIES = {}


def configure_qt_app_shell_read_only_dependencies(dependencies):
    _DEPENDENCIES.update(dict(dependencies or {}))
    globals().update(_DEPENDENCIES)


def _apply_ui_shell_read_only_config(window):
    session = with_flat_sensory_settings(with_flat_musetalk_settings(with_flat_tts_runtime_settings(_read_ui_shell_session_snapshot())))
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
        (
            "visual_reply_provider_combo",
            ["OpenAI", "xAI / Grok", "Runware"],
            {
                "openai": "OpenAI",
                "xai": "xAI / Grok",
                "runware": "Runware",
            }.get(str(session.get("visual_reply_provider", "")).strip().lower(), session.get("visual_reply_provider", "")),
        ),
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
