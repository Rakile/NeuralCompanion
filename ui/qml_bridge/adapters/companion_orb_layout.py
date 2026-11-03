"""Presentation-only layout policy for the Companion Orb native surface.

The generated parity contract and addon controller remain authoritative for
control identity, values, and actions.  This module only gives the large Orb
surface stable, task-oriented cards understood by ``NCLiveControlsGroup``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from ui.qml_bridge.native_contracts import NativeControl, NativeControlKind

COMPANION_ORB_SECTION_ORDER = (
    "Overview",
    "Look",
    "Behavior",
    "Eye Tracking",
    "Reading",
    "Awareness",
    "Hotkeys",
    "Vision & Actions",
    "Advanced",
)


def ordered_companion_orb_sections(sections: Iterable[str]) -> tuple[str, ...]:
    """Keep the task-oriented order and append future contract sections."""

    discovered = tuple(dict.fromkeys(str(section) for section in sections))
    return COMPANION_ORB_SECTION_ORDER + tuple(
        section
        for section in discovered
        if section not in COMPANION_ORB_SECTION_ORDER
    )


@dataclass(frozen=True, slots=True)
class _Card:
    key: str
    title: str
    order: int
    span: int = 1
    description: str = ""


def _card(
    key: str,
    title: str,
    order: int,
    *,
    span: int = 1,
    description: str = "",
) -> _Card:
    return _Card(key, title, order, span, description)


def _numbered_occurrence(control_id: str, prefix: str) -> int | None:
    if control_id == prefix:
        return 1
    match = re.fullmatch(re.escape(prefix) + r"#(\d+)", control_id)
    return int(match.group(1)) if match else None


def _behavior_rule_index(control_id: str) -> int | None:
    text_occurrence = _numbered_occurrence(
        control_id, "unnamed_qplaintextedit_qplaintextedit"
    )
    if text_occurrence is not None:
        return (text_occurrence + 1) // 2
    for prefix in (
        "unnamed_qcheckbox_enabled",
        "unnamed_qtoolbutton_advanced",
        "unnamed_qpushbutton_remove",
        "unnamed_qcombobox_strictness",
        "unnamed_qcombobox_emotion_override",
        "unnamed_qcombobox_repeat_mode",
        "unnamed_qspinbox_nth_match_interval",
    ):
        occurrence = _numbered_occurrence(control_id, prefix)
        if occurrence is not None:
            return occurrence
    return None


def _overview_card(control_id: str) -> _Card:
    if control_id in {"unnamed_qlabel_qlabel", "unnamed_qlabel_qlabel#2"}:
        return _card("overview_intro", "Companion Orb", 10, span=2)
    if control_id in {
        "companion_orb_enabled_checkbox",
        "companion_orb_display_mode_combo",
        "companion_orb_activation_status",
        "companion_orb_show_button",
        "companion_orb_placement_mode_button",
        "companion_orb_reset_position_button",
    }:
        return _card("overview_activation", "Activation", 20, span=2)
    if control_id in {
        "unnamed_qlabel_qlabel#11",
        "companion_orb_lfm_interactive_guide_button",
    }:
        return _card("overview_guide", "Getting started", 30, span=2)
    if control_id.startswith("companion_orb_preset_"):
        return _card("overview_presets", "Presets", 40, span=2)
    if control_id in {
        "companion_orb_position_combo",
        "companion_orb_response_style_combo",
        "companion_orb_edit_mode_button",
        "companion_orb_clear_target_button",
    }:
        return _card("overview_display", "Placement and response", 50)
    if control_id in {
        "companion_orb_always_on_top_checkbox",
        "companion_orb_remember_position_checkbox",
    }:
        return _card("overview_window", "Window behavior", 60)
    return _card("overview_status", "Current status", 70, span=2)


def _look_card(control_id: str) -> _Card:
    if control_id in {
        "companion_orb_custom_colors_enabled_checkbox",
        "companion_orb_color_palette_combo",
        "companion_orb_mood_color_mode_combo",
        "companion_orb_manual_mood_combo",
        "companion_orb_color_source_status",
    }:
        return _card("look_palette", "Palette and mood", 10, span=2)
    if any(
        token in control_id
        for token in (
            "primary_color",
            "secondary_color",
            "accent_color",
            "glow_color",
            "apply_custom_colors",
            "save_custom_colors",
        )
    ):
        return _card("look_custom_colors", "Custom colors", 20, span=2)
    if control_id in {
        "companion_orb_state_colors_enabled_checkbox",
        "companion_orb_state_animation_enabled_checkbox",
    }:
        return _card("look_state_overrides", "State overrides", 30)
    if any(
        token in control_id
        for token in ("idle_color", "thinking_color", "speaking_color")
    ):
        return _card("look_state_colors", "State colors", 40)
    if any(
        token in control_id
        for token in ("idle_animation", "thinking_animation", "speaking_animation")
    ):
        return _card("look_state_animations", "State animation", 50)
    if control_id in {
        "unnamed_nowheelslider_orb_size_92",
        "unnamed_nowheelslider_orb_opacity_0_82",
    }:
        return _card("look_size_visibility", "Size and visibility", 60)
    if control_id in {
        "unnamed_nowheelslider_trail_length_0_55",
        "unnamed_nowheelslider_orb_particles_30",
        "unnamed_nowheelslider_drip_particles_18",
        "unnamed_nowheelslider_drip_lifetime_3_8",
        "unnamed_nowheelslider_smoke_intensity_0_35",
        "unnamed_nowheelslider_orb_glow_1_0",
        "unnamed_nowheelslider_orb_mood_color_0_85",
    }:
        return _card("look_visual_texture", "Glow, particles, and trail", 70)
    if control_id in {
        "unnamed_nowheelslider_orb_voice_reactivity_1_5",
        "companion_orb_voice_sync_enabled_checkbox",
    }:
        return _card("look_voice_sync", "Voice response", 80)
    if control_id in {
        "companion_orb_render_backend_combo",
        "companion_orb_visual_style_combo",
    }:
        return _card("look_appearance", "Rendering and style", 90)
    return _card("look_effects", "GPU effects", 100)


def _behavior_card(control_id: str) -> _Card:
    if control_id in {
        "companion_orb_movement_enabled_checkbox",
        "companion_orb_aware_motion_enabled_checkbox",
        "companion_orb_avoid_center_checkbox",
    }:
        return _card("behavior_motion", "Motion behavior", 10)
    if control_id in {
        "companion_orb_avoid_mouse_checkbox",
        "companion_orb_mouse_near_fade_checkbox",
        "companion_orb_click_through_default_checkbox",
    }:
        return _card("behavior_pointer", "Pointer interaction", 20)
    if control_id in {
        "unnamed_nowheelslider_movement_speed_0_65",
        "unnamed_nowheelslider_movement_range_18",
        "unnamed_nowheelslider_return_home_delay_2_5",
        "unnamed_nowheelslider_awareness_0_55",
        "unnamed_nowheelslider_focus_pull_0_65",
        "unnamed_nowheelslider_idle_pauses_0_45",
    }:
        return _card("behavior_dynamics", "Motion dynamics", 30, span=2)
    return _card("behavior_pointer_tuning", "Pointer and nudge tuning", 40, span=2)


def _eye_tracking_card(control_id: str) -> _Card:
    if control_id in {
        "companion_orb_eye_tracking_status_label",
        "companion_orb_eye_tracking_runtime_label",
        "companion_orb_eye_tracking_click_target_checkbox",
        "companion_orb_eye_tracking_action_hint",
        "companion_orb_eye_tracking_mode_combo",
        "companion_orb_eye_tracking_reaction_mode_combo",
        "companion_orb_eye_tracking_screen_combo",
    }:
        return _card("eye_setup", "Tracking and reactions", 10, span=2)
    if "calibration" in control_id:
        return _card("eye_calibration", "Calibration", 20, span=2)
    if control_id in {
        "unnamed_nowheelslider_dwell_delay_ms_700",
        "unnamed_nowheelslider_stable_radius_px_60",
        "unnamed_nowheelslider_smoothing_0_85",
        "unnamed_nowheelslider_radial_menu_opacity_0_9",
        "unnamed_nowheelslider_comment_cooldown_s_45",
    }:
        return _card("eye_gaze_tuning", "Gaze tuning", 30)
    if control_id in {
        "unnamed_nowheelslider_x_offset_px_0",
        "unnamed_nowheelslider_y_offset_px_0",
    }:
        return _card("eye_placement", "Gaze placement", 40)
    if "pointer_clearance" in control_id or control_id in {
        "unnamed_nowheelslider_move_distance_px_160",
        "unnamed_nowheelslider_interference_timeout_s_8",
    }:
        return _card("eye_pointer_clearance", "Pointer clearance", 50, span=2)
    if control_id in {
        "companion_orb_eye_tracking_long_gaze_checkbox",
        "companion_orb_eye_tracking_expand_read_text_area_checkbox",
        "companion_orb_eye_tracking_radial_focus_beam_checkbox",
        "companion_orb_eye_tracking_long_gaze_ms_spin",
        "companion_orb_eye_tracking_radial_button_gaze_ms_spin",
        "companion_orb_eye_tracking_gaze_timer_color_edit",
        "companion_orb_eye_tracking_gaze_timer_color_pick_button",
    }:
        return _card("eye_radial_menu", "Long gaze menu", 60, span=2)
    if control_id in {
        "companion_orb_eye_tracking_blink_click_allowed_checkbox",
        "companion_orb_eye_tracking_blink_status_label",
        "unnamed_nowheelslider_minimum_blink_ms_80",
        "unnamed_nowheelslider_slow_blink_ms_260",
        "unnamed_nowheelslider_maximum_blink_ms_900",
        "unnamed_nowheelslider_recovery_stability_ms_80",
        "unnamed_nowheelslider_double_blink_window_ms_1200",
        "unnamed_nowheelslider_click_cooldown_ms_450",
    }:
        return _card("eye_blink_detection", "Blink detection", 70, span=2)
    if control_id in {
        "unnamed_nowheelslider_long_blink_minimum_ms_1000",
        "unnamed_nowheelslider_long_blink_maximum_ms_2000",
        "unnamed_nowheelslider_triple_blink_window_ms_450",
        "unnamed_nowheelslider_back_cooldown_ms_1500",
        "unnamed_nowheelslider_scroll_speed_5",
        "unnamed_nowheelslider_scroll_dead_zone_px_100",
    }:
        return _card("eye_commands", "Eye commands", 80, span=2)
    if control_id in {
        "companion_orb_eye_tracking_dll_path_edit",
        "companion_orb_eye_tracking_browse_button",
        "companion_orb_eye_tracking_stable_preset_button",
        "companion_orb_eye_tracking_reconnect_button",
        "companion_orb_eye_tracking_react_button",
    }:
        return _card("eye_runtime", "Runtime and tools", 90, span=2)
    if control_id in {
        "companion_orb_eye_tracking_bounding_boxes_enabled_checkbox",
        "companion_orb_eye_tracking_bounding_box_labels_enabled_checkbox",
        "companion_orb_eye_tracking_bounding_box_freeze_selected_checkbox",
        "companion_orb_eye_tracking_region_select_dwell_ms_spin",
        "companion_orb_eye_tracking_bounding_box_opacity_spin",
        "companion_orb_eye_tracking_bounding_box_width_spin",
        "companion_orb_eye_tracking_bounding_box_min_confidence_spin",
        "companion_orb_eye_tracking_bounding_box_max_visible_spin",
    }:
        return _card("eye_grounded_options", "Grounded-region overlay", 100, span=2)
    if "bounding_box" in control_id and "color" in control_id:
        return _card("eye_grounded_colors", "Grounded-region colors", 110, span=2)
    return _card("eye_grounded_categories", "Visible region types", 120, span=2)


def _reading_card(control_id: str) -> _Card:
    if control_id in {
        "unnamed_qlabel_qlabel#8",
        "companion_orb_reader_exclude_from_memory_checkbox",
        "companion_orb_reading_max_chunk_chars_spin",
    }:
        return _card("reading_selected_text", "Selected text", 10)
    if control_id in {
        "unnamed_qlabel_qlabel#9",
        "companion_orb_smart_drop_guidance_enabled_checkbox",
        "companion_orb_smart_drop_guidance_mode_combo",
    }:
        return _card("reading_drop_reply", "Drop and reading replies", 20)
    return _card("reading_prompt", "Commentary prompt", 30, span=2)


def _awareness_card(control_id: str) -> _Card:
    if control_id in {'companion_orb_capture_scope_combo', 'companion_orb_capture_scope_label'}:
        return _card('awareness_capture_scope', 'What the Orb can see', 95, span=2)
    if control_id in {'companion_orb_include_all_monitors_checkbox',
                      'companion_orb_require_target_confirmation_checkbox', 'companion_orb_include_process_name_checkbox'}:
        return _card('awareness_advanced_capture', 'Advanced capture options', 160, span=2)
    if control_id.startswith('companion_orb_watch_'):
        return _card('awareness_watches', 'Conversational watches', 15, span=2)
    if control_id.startswith('companion_orb_behavior_') or control_id == 'btn_companion_orb_supervisor_add_behavior':
        return _card('awareness_rules', 'Behavior rules', 30, span=2)
    rule_index = _behavior_rule_index(control_id)
    if rule_index is not None:
        return _card(
            f"awareness_rule_{rule_index}",
            f"Behavior rule {rule_index}",
            20 + rule_index,
            span=2,
        )
    if control_id == "unnamed_qlabel_qlabel#4":
        return _card("awareness_intro", "Awareness", 10, span=2)
    if control_id in {
        "companion_orb_supervisor_enabled_checkbox",
        "companion_orb_supervisor_state_label",
        "btn_companion_orb_supervisor_add_persona",
        "btn_companion_orb_supervisor_rename_persona",
        "btn_companion_orb_supervisor_delete_persona",
        "companion_orb_supervisor_persona_combo",
        "companion_orb_supervisor_persona_style_edit",
        "btn_companion_orb_supervisor_add_behavior",
    }:
        return _card("awareness_persona", "Supervisor profile", 20, span=2)
    if control_id in {
        "unnamed_qlabel_qlabel#5",
        "btn_companion_orb_supervisor_reset_template",
        "companion_orb_supervisor_template_edit",
        "companion_orb_supervisor_preview_edit",
    }:
        return _card("awareness_template", "Supervisor prompt", 40, span=2)
    if control_id in {
        "companion_orb_reply_style_prompt_hint",
        "companion_orb_reply_style_editor_combo",
        "companion_orb_reply_style_prompt_edit",
        "btn_companion_orb_reply_style_save",
        "btn_companion_orb_reply_style_load",
        "btn_companion_orb_reply_style_default",
        "btn_companion_orb_reply_style_reset_all",
        "companion_orb_reply_style_prompt_status",
    }:
        return _card("awareness_reply_style", "Reply style", 50, span=2)
    if control_id in {
        "companion_orb_harassment_enabled_checkbox",
        "companion_orb_snapshot_on_pointer_reached_checkbox",
        "companion_orb_right_drag_focus_enabled_checkbox",
    }:
        return _card("awareness_triggers", "Response triggers", 60)
    if control_id == "companion_orb_supervisor_flow_preview":
        return _card("awareness_flow", "Supervisor flow", 70, span=2)
    if control_id == "companion_orb_supervisor_focus_preview":
        return _card("awareness_focus", "Focus behavior", 80, span=2)
    if control_id == "unnamed_qlabel_qlabel#6":
        return _card("awareness_capture_intro", "Sensory capture", 90, span=2)
    if control_id in {
        "companion_orb_sensory_target_enabled_checkbox",
        "companion_orb_pingpong_enabled_checkbox",
        "companion_orb_full_screen_context_enabled_checkbox",
        "companion_orb_watch_status_label",
        'companion_orb_exclude_nc_from_captures_checkbox',
        'companion_orb_capture_exclusion_status_label',
    }:
        return _card("awareness_sources", "Sensory sources", 100)
    if control_id in {
        "unnamed_qlabel_qlabel#7",
        "companion_orb_target_mode_combo",
        "companion_orb_show_target_label_checkbox",
        "companion_orb_require_target_confirmation_checkbox",
        "companion_orb_include_process_name_checkbox",
    }:
        return _card("awareness_target", "Target selection", 110)
    if control_id in {
        "unnamed_nowheelslider_target_region_width_640",
        "unnamed_nowheelslider_target_region_height_420",
    }:
        return _card("awareness_region", "Capture region", 120)
    if control_id in {
        "companion_orb_capture_show_button",
        "companion_orb_capture_clear_target_button",
        "companion_orb_capture_reset_position_button",
    }:
        return _card("awareness_capture_actions", "Capture actions", 130, span=2)
    if control_id == "companion_orb_source_guidance_preview":
        return _card("awareness_source_guidance", "Source guidance", 140, span=2)
    return _card("awareness_source_metadata", "Source diagnostics", 150, span=2)


def _hotkeys_card(control_id: str) -> _Card:
    if control_id == "companion_orb_hotkeys_enabled_checkbox":
        return _card("hotkeys_toggle", "Hotkey behavior", 10)
    return _card("hotkeys_shortcuts", "Shortcuts", 20, span=2)


def _vision_card(control_id: str) -> _Card:
    if control_id in {
        "companion_orb_vision_enabled_checkbox",
        "companion_orb_spatial_capture_scope_combo",
        "companion_orb_spatial_capture_scope_note",
        "companion_orb_vision_runtime_status_label",
        "companion_orb_show_vision_pipeline_indicator_checkbox",
        "companion_orb_vision_pipeline_status_label",
        "companion_orb_vision_pipeline_details_button",
        "companion_orb_vision_target_fallback_only_checkbox",
    }:
        return _card("vision_activation", "Activation and status", 10, span=2)
    if control_id in {
        "companion_orb_vision_provider_id_edit",
        "companion_orb_vision_model_id_edit",
        "companion_orb_vision_models_refresh",
        "companion_orb_vision_provider_configure",
        "companion_orb_vision_catalog_status",
        "companion_orb_vision_capability_mode_combo",
        "companion_orb_vision_timeout_seconds_spin",
        "companion_orb_vision_min_confidence_spin",
        "companion_orb_vision_capability_hint",
    }:
        return _card("vision_model", "Vision model", 20, span=2)
    if control_id in {
        "companion_orb_vision_click_enabled_checkbox",
        "companion_orb_vision_click_confirmation_method_combo",
        "companion_orb_vision_click_confirmation_dwell_ms_spin",
        "companion_orb_vision_click_verification_timeout_seconds_spin",
        "companion_orb_vision_click_label_similarity_spin",
        "companion_orb_vision_click_bounds_overlap_spin",
        "companion_orb_vision_click_sound_enabled_checkbox",
        "companion_orb_vision_actions_help",
    }:
        return _card("vision_click", "Confirmed clicks", 30, span=2)
    if control_id in {
        "unnamed_qlabel_qlabel#3",
        "companion_orb_spatial_scan_mode_combo",
        "companion_orb_spatial_scan_interval_seconds_spin",
        "companion_orb_spatial_map_max_age_seconds_spin",
        "companion_orb_spatial_change_detection_enabled_checkbox",
        "companion_orb_spatial_change_threshold_spin",
        "companion_orb_spatial_max_regions_spin",
    }:
        return _card("vision_spatial_scan", "Desktop map scanning", 40, span=2)
    if control_id.startswith("companion_orb_spatial_include_"):
        return _card("vision_spatial_categories", "Desktop map content", 50)
    if control_id in {
        "companion_orb_spatial_explicit_commands_enabled_checkbox",
        "companion_orb_spatial_conversational_focus_enabled_checkbox",
        "companion_orb_spatial_follow_target_enabled_checkbox",
        "companion_orb_spatial_stay_during_speech_checkbox",
        "companion_orb_spatial_conversational_min_confidence_spin",
        "companion_orb_spatial_movement_cooldown_seconds_spin",
        "companion_orb_spatial_hover_offset_px_spin",
        "companion_orb_spatial_return_behavior_combo",
        "companion_orb_spatial_lan_privacy_note",
    }:
        return _card("vision_spatial_behavior", "Movement and focus", 60, span=2)
    if control_id in {
        "companion_orb_visual_guidance_enabled_checkbox",
        "companion_orb_visual_guidance_gaze_enabled_checkbox",
        "companion_orb_visual_guidance_drop_enabled_checkbox",
        "companion_orb_visual_guidance_reading_enabled_checkbox",
    }:
        return _card("vision_guidance_scope", "Visual guidance", 70)
    return _card("vision_guidance_runtime", "Vision runtime", 80, span=2)


def _advanced_card(control_id: str) -> _Card:
    if control_id in {
        "companion_orb_full_screen_tiling_enabled_checkbox",
        "companion_orb_full_screen_tile_count_spin",
        "companion_orb_full_screen_tiling_help",
    }:
        return _card("advanced_tiling", "Full-screen detail tiling", 10, span=2)
    if control_id in {
        "companion_orb_spatial_diagnostics_keep_last_capture_checkbox",
        "companion_orb_spatial_diagnostics_privacy_note",
        "companion_orb_spatial_test_grounding_button",
        "companion_orb_spatial_diagnostics_status",
    }:
        return _card("advanced_spatial", "Spatial diagnostics", 20, span=2)
    if control_id == "companion_orb_debug_enabled_checkbox":
        return _card("advanced_debug", "Debug recorder", 30)
    if control_id in {
        "companion_orb_reading_keep_debug_crops_checkbox",
        "companion_orb_debug_log_path_preview",
        "btn_companion_orb_open_debug_log_folder",
        "btn_companion_orb_clear_debug_log",
        "btn_companion_orb_copy_debug_log_path",
        "btn_companion_orb_copy_latest_vision_trace_path",
    }:
        return _card("advanced_debug_records", "Debug records", 40, span=2)
    if control_id in {
        "companion_orb_external_runtime_enabled_checkbox",
        "companion_orb_reduced_effects_checkbox",
    }:
        return _card("advanced_runtime", "Runtime mode", 50)
    return _card("advanced_timing", "Rendering performance", 60)


_SECTION_LAYOUT = {
    "Overview": _overview_card,
    "Look": _look_card,
    "Behavior": _behavior_card,
    "Eye Tracking": _eye_tracking_card,
    "Reading": _reading_card,
    "Awareness": _awareness_card,
    "Hotkeys": _hotkeys_card,
    "Vision & Actions": _vision_card,
    "Advanced": _advanced_card,
}


_ACTION_LABELS = {
    "companion_orb_primary_color_pick_button": "Pick primary",
    "companion_orb_secondary_color_pick_button": "Pick secondary",
    "companion_orb_accent_color_pick_button": "Pick accent",
    "companion_orb_glow_color_pick_button": "Pick glow",
    "companion_orb_idle_color_pick_button": "Pick idle",
    "companion_orb_thinking_color_pick_button": "Pick thinking",
    "companion_orb_speaking_color_pick_button": "Pick speaking",
    "companion_orb_eye_tracking_gaze_timer_color_pick_button": "Pick timer color",
    "companion_orb_eye_tracking_bounding_box_normal_color_pick_button": "Pick normal",
    "companion_orb_eye_tracking_bounding_box_hover_color_pick_button": "Pick hover",
    "companion_orb_eye_tracking_bounding_box_selected_color_pick_button": "Pick selected",
}


def apply_companion_orb_layout(
    controls: Iterable[NativeControl],
) -> tuple[NativeControl, ...]:
    """Decorate controls with stable card and responsive editor metadata."""

    rendered: list[NativeControl] = []
    for control in controls:
        resolver = _SECTION_LAYOUT.get(control.section)
        if resolver is None:
            card = _card(
                f"{control.section.lower().replace(' ', '_')}_other",
                "Other settings",
                1000,
                span=2,
            )
        else:
            card = resolver(control.id)
        metadata = dict(control.metadata)
        everyday = {
            'companion_orb_capture_scope_combo', 'companion_orb_capture_scope_label',
            'companion_orb_exclude_nc_from_captures_checkbox', 'companion_orb_capture_exclusion_status_label',
            'companion_orb_capture_show_button', 'companion_orb_capture_clear_target_button',
            'unnamed_nowheelslider_target_region_width_640', 'unnamed_nowheelslider_target_region_height_420',
            'companion_orb_vision_provider_id_edit', 'companion_orb_vision_model_id_edit',
            'companion_orb_vision_models_refresh', 'companion_orb_vision_provider_configure',
            'companion_orb_vision_catalog_status',
        }
        if control.section in {'Awareness', 'Vision & Actions'}:
            metadata['orbAdvanced'] = control.id not in everyday
        if control.id in {'unnamed_nowheelslider_target_region_width_640', 'unnamed_nowheelslider_target_region_height_420'}:
            metadata['orbScopeOnly'] = 'region'
        if control.id == 'companion_orb_include_all_monitors_checkbox':
            metadata['orbScopeOnly'] = 'screen'
        if control.id in {'companion_orb_target_mode_combo', 'companion_orb_full_screen_context_enabled_checkbox',
                           'unnamed_qlabel_qlabel#6', 'unnamed_qlabel_qlabel#7', 'companion_orb_watch_setup_apply'}:
            metadata['presentationHidden'] = True
        if control.section == 'Awareness' and _behavior_rule_index(control.id) is not None:
            metadata['presentationHidden'] = True
        metadata.update(
            groupKey=card.key,
            groupTitle=card.title,
            groupDescription=card.description,
            groupOrder=card.order,
            groupColumnSpan=card.span,
        )
        if control.kind is NativeControlKind.ACTION:
            metadata.update(actionStrip=True, compactActionWidth=148)
            if control.id in _ACTION_LABELS:
                metadata["label"] = _ACTION_LABELS[control.id]
        if control.kind is NativeControlKind.MULTILINE:
            metadata.update(
                stackedLayout=True,
                scrollable=True,
                editorPreferredHeight=(
                    156 if bool(metadata.get("readOnly")) else 176
                ),
            )
        rendered.append(replace(control, metadata=metadata))
    return tuple(rendered)


__all__ = [
    "COMPANION_ORB_SECTION_ORDER",
    "apply_companion_orb_layout",
    "ordered_companion_orb_sections",
]
