"""Typed control bindings for the complete Companion Orb native-QML surface."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from addons.companion_orb_overlay.native_contract import NATIVE_CONTROL_SPECS, BEHAVIOR_EDITOR_FIELDS
from addons.ai_presence_mode.native_controller import ORB_VISUAL_STYLES
from core import companion_orb_reply_styles


_SPECS = {str(spec["id"]): dict(spec) for spec in NATIVE_CONTROL_SPECS}
_ACTION_IDS = {key for key, spec in _SPECS.items() if spec["kind"] == "action"}
_READ_ONLY_IDS = {key for key, spec in _SPECS.items() if bool(spec.get("read_only"))}
_SUFFIXES = ("_checkbox", "_combo", "_spin", "_slider", "_edit", "_line_edit", "_text_edit")
_HUNDREDTH_SCALE_SETTINGS = frozenset(
    {
        "companion_orb_eye_tracking_smoothing",
        "companion_orb_eye_tracking_radial_menu_opacity",
        "companion_orb_movement_speed",
        "companion_orb_return_home_delay",
        "companion_orb_mouse_near_opacity",
        "companion_orb_opacity",
        "companion_orb_trail_length",
        "companion_orb_falling_particle_lifetime",
        "companion_orb_smoke_intensity",
        "companion_orb_glow_strength",
        "companion_orb_mood_color_intensity",
        "companion_orb_speaking_reactivity",
    }
)

_MANUAL_SETTINGS = {
    "unnamed_nowheelslider_orb_frame_rate_120": "companion_orb_frame_rate",
    "unnamed_nowheelslider_orb_sync_rate_29": "companion_orb_audio_refresh_hz",
    "unnamed_nowheelslider_target_region_width_640": "companion_orb_target_region_width",
    "unnamed_nowheelslider_target_region_height_420": "companion_orb_target_region_height",
    "companion_orb_eye_tracking_click_target_checkbox": "companion_orb_eye_tracking_click_target_enabled",
    "companion_orb_eye_tracking_screen_combo": "companion_orb_eye_tracking_screen_index",
    "unnamed_nowheelslider_dwell_delay_ms_700": "companion_orb_eye_tracking_dwell_ms",
    "unnamed_nowheelslider_stable_radius_px_60": "companion_orb_eye_tracking_radius_px",
    "unnamed_nowheelslider_smoothing_0_85": "companion_orb_eye_tracking_smoothing",
    "unnamed_nowheelslider_radial_menu_opacity_0_9": "companion_orb_eye_tracking_radial_menu_opacity",
    "unnamed_nowheelslider_comment_cooldown_s_45": "companion_orb_eye_tracking_reaction_cooldown_seconds",
    "unnamed_nowheelslider_x_offset_px_0": "companion_orb_eye_tracking_offset_x_px",
    "unnamed_nowheelslider_y_offset_px_0": "companion_orb_eye_tracking_offset_y_px",
    "companion_orb_eye_tracking_pointer_clearance_checkbox": "companion_orb_eye_tracking_pointer_clearance_enabled",
    "unnamed_nowheelslider_move_distance_px_160": "companion_orb_eye_tracking_pointer_clearance_distance_px",
    "unnamed_nowheelslider_interference_timeout_s_8": "companion_orb_eye_tracking_pointer_clearance_timeout_seconds",
    "companion_orb_eye_tracking_long_gaze_checkbox": "companion_orb_eye_tracking_long_gaze_enabled",
    "companion_orb_eye_tracking_radial_focus_beam_checkbox": "companion_orb_eye_tracking_radial_focus_beam_enabled",
    "unnamed_nowheelslider_minimum_blink_ms_80": "companion_orb_eye_tracking_blink_min_ms",
    "unnamed_nowheelslider_slow_blink_ms_260": "companion_orb_eye_tracking_blink_slow_min_ms",
    "unnamed_nowheelslider_maximum_blink_ms_900": "companion_orb_eye_tracking_blink_max_ms",
    "unnamed_nowheelslider_recovery_stability_ms_80": "companion_orb_eye_tracking_blink_recovery_ms",
    "unnamed_nowheelslider_double_blink_window_ms_1200": "companion_orb_eye_tracking_blink_double_gap_ms",
    "unnamed_nowheelslider_click_cooldown_ms_450": "companion_orb_eye_tracking_blink_click_cooldown_ms",
    "unnamed_nowheelslider_long_blink_minimum_ms_1000": "companion_orb_eye_tracking_menu_blink_min_ms",
    "unnamed_nowheelslider_long_blink_maximum_ms_2000": "companion_orb_eye_tracking_menu_blink_max_ms",
    "unnamed_nowheelslider_triple_blink_window_ms_450": "companion_orb_eye_tracking_triple_blink_gap_ms",
    "unnamed_nowheelslider_back_cooldown_ms_1500": "companion_orb_eye_tracking_back_cooldown_ms",
    "unnamed_nowheelslider_scroll_speed_5": "companion_orb_eye_tracking_scroll_speed",
    "unnamed_nowheelslider_scroll_dead_zone_px_100": "companion_orb_eye_tracking_scroll_dead_zone_px",
    "unnamed_nowheelslider_movement_speed_0_65": "companion_orb_movement_speed",
    "unnamed_nowheelslider_movement_range_18": "companion_orb_movement_range",
    "unnamed_nowheelslider_return_home_delay_2_5": "companion_orb_return_home_delay",
    "unnamed_nowheelslider_awareness_0_55": "companion_orb_awareness",
    "unnamed_nowheelslider_focus_pull_0_65": "companion_orb_focus_pull",
    "unnamed_nowheelslider_idle_pauses_0_45": "companion_orb_idle_pause",
    "unnamed_nowheelslider_playful_nudge_delay_45": "companion_orb_harassment_timer_seconds",
    "unnamed_nowheelslider_mouse_fade_distance_120": "companion_orb_mouse_near_fade_distance",
    "unnamed_nowheelslider_mouse_near_opacity_0_28": "companion_orb_mouse_near_opacity",
    "unnamed_nowheelslider_orb_size_92": "companion_orb_size",
    "unnamed_nowheelslider_orb_opacity_0_82": "companion_orb_opacity",
    "unnamed_nowheelslider_trail_length_0_55": "companion_orb_trail_length",
    "unnamed_nowheelslider_orb_particles_30": "companion_orb_particle_density",
    "unnamed_nowheelslider_drip_particles_18": "companion_orb_falling_particle_density",
    "unnamed_nowheelslider_drip_lifetime_3_8": "companion_orb_falling_particle_lifetime",
    "unnamed_nowheelslider_smoke_intensity_0_35": "companion_orb_smoke_intensity",
    "unnamed_nowheelslider_orb_glow_1_0": "companion_orb_glow_strength",
    "unnamed_nowheelslider_orb_mood_color_0_85": "companion_orb_mood_color_intensity",
    "unnamed_nowheelslider_orb_voice_reactivity_1_5": "companion_orb_speaking_reactivity",
}

_LOCAL_IDS = {
    'companion_orb_capture_scope_combo',
    "companion_orb_supervisor_persona_combo",
    "companion_orb_supervisor_persona_style_edit",
    "companion_orb_supervisor_template_edit",
    "companion_orb_reply_style_editor_combo",
    "companion_orb_reply_style_prompt_edit",
    "companion_orb_pingpong_enabled_checkbox",
    "companion_orb_preset_combo",
    "companion_orb_preset_comment_edit",
}


def _activation_status(config: Mapping[str, Any]) -> str:
    enabled = bool(config.get("companion_orb_enabled", False))
    mode = str(config.get("companion_orb_display_mode", "off") or "off").strip().lower()
    if not enabled:
        return "Not running. Turn on Start Companion Orb or use Start and show Orb."
    if mode == "off":
        return "Enabled, but hidden because Visibility mode is Off."
    if mode == "interaction":
        return "Running. Visible while NeuralCompanion is listening, thinking, or speaking."
    if mode == "always":
        return "Running. Always visible."
    return "Running. Docked at its home position."


def _update_bound_setting(controller: Any, setting_key: str, value: Any) -> None:
    """Apply one mapped control while preserving the established runtime path.

    The Orb controller's own toggle already chooses Docked mode when it is
    started from an Off display mode. Mirror that rule for native-QML edits so
    the visible master switch cannot leave a newly enabled Orb hidden.
    """

    if (
        setting_key == "companion_orb_enabled"
        and bool(value)
        and str(
            controller._runtime_config().get("companion_orb_display_mode", "off")
            or "off"
        ).strip().lower()
        == "off"
    ):
        controller.native_update_setting("companion_orb_display_mode", "docked")
    controller.native_update_setting(setting_key, value)


def _setting_map(controller: Any) -> dict[str, str]:
    session_keys = set(controller.SESSION_KEYS)
    result = dict(_MANUAL_SETTINGS)
    for control_id in _SPECS:
        candidate = control_id
        for suffix in _SUFFIXES:
            if candidate.endswith(suffix):
                candidate = candidate[: -len(suffix)]
                break
        if candidate in session_keys:
            result[control_id] = candidate
    return result


def _coerce(control_id: str, value: Any) -> Any:
    kind = str(_SPECS[control_id]["kind"])
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)
    if kind in {"integer", "slider", "progress"}:
        return int(float(value or 0))
    if kind == "number":
        return float(value or 0.0)
    return str(value or "") if kind in {"text", "multiline", "choice"} else value


def _control_value(setting_key: str, value: Any) -> Any:
    if setting_key in _HUNDREDTH_SCALE_SETTINGS:
        return int(round(float(value) * 100.0))
    return copy.deepcopy(value)


def _runtime_value(setting_key: str, value: Any) -> Any:
    if setting_key in _HUNDREDTH_SCALE_SETTINGS:
        return float(value) / 100.0
    return value


def _behavior_slot(control_id: str) -> tuple[int, str] | None:
    patterns = (
        ("unnamed_qcheckbox_enabled", "enabled"),
        ("unnamed_qtoolbutton_advanced", "advanced"),
        ("unnamed_qcombobox_strictness", "strictness"),
        ("unnamed_qcombobox_emotion_override", "emotion"),
        ("unnamed_qcombobox_repeat_mode", "repeat_mode"),
        ("unnamed_qspinbox_nth_match_interval", "repeat_interval"),
    )
    for prefix, field in patterns:
        if control_id == prefix:
            return 0, field
        if control_id.startswith(prefix + "#"):
            return max(0, int(control_id.rsplit("#", 1)[1]) - 1), field
    if control_id.startswith("unnamed_qplaintextedit_qplaintextedit"):
        occurrence = 1
        if "#" in control_id:
            occurrence = int(control_id.rsplit("#", 1)[1])
        return (occurrence - 1) // 2, "trigger" if occurrence % 2 else "action"
    return None


def _selected_persona(controller: Any) -> dict[str, Any]:
    return dict(controller._selected_companion_orb_supervisor_persona() or {})


def selected_behavior_index(controller: Any) -> int | None:
    behaviors = list(_selected_persona(controller).get('behaviors') or [])
    selected = str(getattr(controller, '_native_selected_behavior_id', '') or '')
    index = next((i for i, rule in enumerate(behaviors) if rule.get('id') == selected), None)
    if index is None and behaviors:
        index = 0
    controller._native_selected_behavior_id = str(behaviors[index].get('id') or '') if index is not None else ''
    return index


def _reply_style_ids() -> tuple[tuple[str, str], ...]:
    return tuple(
        (style_id, str(label))
        for label, style_id in companion_orb_reply_styles.ORB_RESPONSE_STYLES
    )


def native_control_state(controller: Any) -> dict[str, Any]:
    config = controller._runtime_config()
    values = {key: copy.deepcopy(spec.get("default")) for key, spec in _SPECS.items()}
    options: dict[str, tuple[tuple[Any, str], ...]] = {}
    enabled: dict[str, bool] = {}
    setting_map = _setting_map(controller)
    for control_id, setting_key in setting_map.items():
        if setting_key in config:
            values[control_id] = _control_value(setting_key, config[setting_key])

    vision = controller._service_snapshot("vision_runtime_snapshot") or dict(controller._last_vision_runtime_snapshot)
    eye = controller._service_snapshot("eye_tracking_status")
    watch = controller._service_snapshot('watch_status_snapshot')
    from .companion_orb.capture_scope import capture_mode
    scope = controller._service_snapshot('capture_scope_snapshot')
    values['companion_orb_capture_scope_combo'] = capture_mode(config)
    values['companion_orb_capture_scope_label'] = str(scope.get('label') or 'Choose a capture target')
    values.update({
        'companion_orb_watch_instruction': str(watch.get('instruction') or ''),
        'companion_orb_watch_checked': str(watch.get('checked') or 'Not checked yet'),
        'companion_orb_watch_observation': str(watch.get('observation_text') or ''),
    })
    enabled['companion_orb_watch_stop'] = bool(watch.get('active'))
    enabled['companion_orb_watch_open_capture'] = bool(watch.get('capture_available'))
    persona = _selected_persona(controller)
    behaviors = [dict(item) for item in list(persona.get("behaviors") or []) if isinstance(item, Mapping)]
    selected_index = selected_behavior_index(controller)
    selected_rule = behaviors[selected_index] if selected_index is not None else {}
    values['companion_orb_behavior_selected'] = str(selected_rule.get('id') or '')
    options['companion_orb_behavior_selected'] = tuple(
        (str(rule.get('id') or ''), str(rule.get('trigger') or 'New reaction rule')[:90])
        for rule in behaviors) or (('', 'No rules'),)
    enabled['companion_orb_behavior_selected'] = bool(behaviors)
    enabled['companion_orb_behavior_remove'] = bool(selected_rule)
    for key, (field, _source, _label) in BEHAVIOR_EDITOR_FIELDS.items():
        values[key] = copy.deepcopy(selected_rule.get(field, values[key]))
        enabled[key] = bool(selected_rule)
    presets = list(controller._companion_orb_preset_store.catalog().records)
    selected_preset = str(getattr(controller, "_native_selected_preset_id", "") or "")
    if selected_preset not in {record.preset_id for record in presets}:
        selected_preset = presets[0].preset_id if presets else ""
        controller._native_selected_preset_id = selected_preset
    selected_record = next((record for record in presets if record.preset_id == selected_preset), None)
    reply_style_id = str(getattr(controller, "_native_reply_style_id", "") or "friendly")
    reply_overrides = controller._reply_style_prompt_overrides()

    values.update(
        {
            "companion_orb_activation_status": _activation_status(config),
            'companion_orb_capture_exclusion_status_label': str((controller._service_snapshot('capture_exclusion_status_snapshot') or {}).get('message') or 'Not requested.'),
            "companion_orb_watch_status_label": str(watch.get('message') or 'No active conversational watch.'),
            "companion_orb_vision_runtime_status_label": str(vision.get("message") or vision.get("state") or "Auxiliary vision is inactive."),
            "companion_orb_vision_pipeline_status_label": str(vision.get("pipeline_status") or vision.get("message") or "Auxiliary vision is inactive."),
            "companion_orb_vision_connection_status_label": str(controller._native_vision_probe_status or "Not tested"),
            "companion_orb_spatial_diagnostics_status": str(controller._native_spatial_status or "Not tested"),
            "companion_orb_eye_tracking_connection_label": str(eye.get("message") or eye.get("code") or "Eye tracking is inactive."),
            "companion_orb_eye_tracking_runtime_label": str(eye.get("runtime") or eye.get("dll_path") or "Automatic discovery"),
            "companion_orb_eye_tracking_status_label": str(eye.get("message") or eye.get("code") or "Eye tracking is inactive."),
            "companion_orb_eye_tracking_calibration_status_label": str(eye.get("calibration_status") or "Not calibrated"),
            "companion_orb_eye_tracking_calibration_result_label": str(eye.get("calibration_result") or "No saved calibration result."),
            "companion_orb_eye_tracking_pointer_clearance_status_label": str(eye.get("pointer_clearance_status") or "Inactive"),
            "companion_orb_eye_tracking_blink_status_label": str(eye.get("blink_status") or "Blink click is inactive."),
            "companion_orb_supervisor_state_label": "Active" if bool(config.get("companion_orb_supervisor_enabled", False)) else "Off",
            "companion_orb_supervisor_persona_combo": str(persona.get("id") or ""),
            "companion_orb_supervisor_persona_style_edit": str(persona.get("style") or ""),
            "companion_orb_supervisor_template_edit": controller._companion_orb_supervisor_template(),
            "companion_orb_supervisor_preview_edit": controller._render_companion_orb_supervisor_prompt(),
            "companion_orb_reply_style_editor_combo": reply_style_id,
            "companion_orb_reply_style_prompt_edit": str(
                getattr(controller, "_native_reply_style_prompt", "")
                or companion_orb_reply_styles.effective_reply_style_prompt(
                    reply_style_id, reply_overrides
                )
            ),
            "companion_orb_reply_style_prompt_status": "Custom override" if reply_style_id in reply_overrides else "Recommended default",
            "companion_orb_pingpong_enabled_checkbox": bool(config.get("sensory_pingpong_enabled", False)),
            "companion_orb_preset_combo": selected_preset,
            "companion_orb_preset_comment_edit": str(
                getattr(controller, "_native_preset_comment", "")
                or (selected_record.comment if selected_record else "")
            ),
            "companion_orb_debug_log_path_preview": str(
                Path(getattr(controller.context, "app_root", Path.cwd()) or Path.cwd())
                / "runtime"
                / "companion_orb"
                / "debug"
                / "companion_orb_debug.log"
            ),
            "companion_orb_reader_commentary_prompt_edit": controller._reader_commentary_prompt_value(),
        }
    )
    for control_id in _SPECS:
        slot = _behavior_slot(control_id)
        if slot is None:
            continue
        index, field = slot
        behavior = behaviors[index] if index < len(behaviors) else {}
        if field == "advanced":
            values[control_id] = str(behavior.get("id") or "") in controller._companion_orb_supervisor_expanded_behavior_ids
        else:
            values[control_id] = copy.deepcopy(behavior.get(field, values[control_id]))
        enabled[control_id] = bool(behavior)

    personas = controller._companion_orb_supervisor_personas()
    options["companion_orb_supervisor_persona_combo"] = tuple(
        (str(item.get("id") or ""), str(item.get("name") or "Orb Supervisor"))
        for item in personas
    )
    options["companion_orb_reply_style_editor_combo"] = _reply_style_ids()
    options["companion_orb_visual_style_combo"] = tuple(
        (style_id, label) for label, style_id in ORB_VISUAL_STYLES
    )
    options["companion_orb_preset_combo"] = tuple(
        (record.preset_id, record.name) for record in presets
    ) or (("", "No saved presets"),)
    return {"values": values, "options": options, "enabled": enabled, "watch_rows": watch.get('rows', []),
            'capture_scope': scope, 'watch_paused_reasons': watch.get('paused_reasons', [])}


def _update_behavior(controller: Any, control_id: str, value: Any) -> None:
    if control_id in BEHAVIOR_EDITOR_FIELDS:
        index = selected_behavior_index(controller)
        if index is None:
            raise ValueError('Add a behavior rule before editing it.')
        slot = (index, BEHAVIOR_EDITOR_FIELDS[control_id][0])
    else:
        slot = _behavior_slot(control_id)
    if slot is None:
        raise KeyError(control_id)
    index, field = slot
    personas = controller._companion_orb_supervisor_personas()
    selected_id = str(controller._selected_companion_orb_supervisor_persona().get("id") or "")
    persona = next((item for item in personas if str(item.get("id") or "") == selected_id), None)
    if persona is None:
        raise ValueError("Choose a Companion Orb supervisor persona first.")
    behaviors = list(persona.get("behaviors") or [])
    if index >= len(behaviors):
        raise ValueError("Add a behavior rule before editing this slot.")
    behavior = dict(behaviors[index])
    if field == "advanced":
        behavior_id = str(behavior.get("id") or "")
        if bool(value):
            controller._companion_orb_supervisor_expanded_behavior_ids.add(behavior_id)
        else:
            controller._companion_orb_supervisor_expanded_behavior_ids.discard(behavior_id)
        return
    behavior[field] = value
    behaviors[index] = behavior
    persona["behaviors"] = behaviors
    controller._set_companion_orb_supervisor_personas(personas)


def native_update_control(controller: Any, control_id: str, value: Any) -> dict[str, Any]:
    key = str(control_id or "").strip()
    if key not in _SPECS:
        raise KeyError(f"Unknown Companion Orb control {control_id!r}.")
    if key in _ACTION_IDS:
        raise ValueError(f"Companion Orb action {key!r} must be triggered.")
    if key in _READ_ONLY_IDS:
        raise ValueError(f"Companion Orb control {key!r} is read-only.")
    converted = _coerce(key, value)
    if key == 'companion_orb_capture_scope_combo':
        return controller._companion_orb_service().select_capture_mode(str(converted))
    setting_key = _setting_map(controller).get(key)
    if setting_key:
        _update_bound_setting(
            controller,
            setting_key,
            _runtime_value(setting_key, converted),
        )
    elif key == 'companion_orb_behavior_selected':
        behaviors = list(_selected_persona(controller).get('behaviors') or [])
        if converted not in {str(rule.get('id') or '') for rule in behaviors}:
            raise ValueError('Choose an existing behavior rule.')
        controller._native_selected_behavior_id = str(converted)
    elif key in BEHAVIOR_EDITOR_FIELDS or _behavior_slot(key) is not None:
        _update_behavior(controller, key, converted)
        controller._publish_companion_orb_supervisor()
    elif key == "companion_orb_supervisor_persona_combo":
        controller._native_selected_behavior_id = ''
        controller._update_runtime_config("companion_orb_supervisor_selected_persona_id", str(converted))
        controller._publish_companion_orb_supervisor()
    elif key == "companion_orb_supervisor_persona_style_edit":
        personas = controller._companion_orb_supervisor_personas()
        selected = str(controller._selected_companion_orb_supervisor_persona().get("id") or "")
        for persona in personas:
            if str(persona.get("id") or "") == selected:
                persona["style"] = str(converted)
        controller._set_companion_orb_supervisor_personas(personas)
    elif key == "companion_orb_supervisor_template_edit":
        controller.native_update_setting("companion_orb_supervisor_prompt_template", converted)
    elif key == "companion_orb_reply_style_editor_combo":
        controller._native_reply_style_id = str(converted)
        controller._native_reply_style_prompt = ""
    elif key == "companion_orb_reply_style_prompt_edit":
        controller._native_reply_style_prompt = str(converted)
    elif key == "companion_orb_pingpong_enabled_checkbox":
        controller._update_runtime_config("sensory_pingpong_enabled", bool(converted))
        controller._save_session()
    elif key == "companion_orb_preset_combo":
        controller._native_selected_preset_id = str(converted)
        controller._native_preset_comment = ""
    elif key == "companion_orb_preset_comment_edit":
        controller._native_preset_comment = str(converted)
    else:
        raise KeyError(f"Companion Orb control {key!r} has no native binding.")
    return native_control_state(controller)


def unsupported_editable_control_ids(controller: Any) -> tuple[str, ...]:
    supported = set(_setting_map(controller)) | set(_LOCAL_IDS)
    supported |= set(BEHAVIOR_EDITOR_FIELDS) | {'companion_orb_behavior_selected'}
    supported |= {key for key in _SPECS if _behavior_slot(key) is not None}
    editable = set(_SPECS) - _ACTION_IDS - _READ_ONLY_IDS
    return tuple(sorted(editable - supported))


__all__ = ["native_control_state", "native_update_control", "unsupported_editable_control_ids"]
