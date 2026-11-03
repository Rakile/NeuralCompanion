.pragma library

// Presentation only. Native descriptors still own values, validation and actions.
var groupCards = {
    awareness_capture_scope: "capture", awareness_sources: "capture",
    awareness_target: "capture", awareness_region: "capture",
    awareness_capture_actions: "capture", awareness_advanced_capture: "capture_details",
    awareness_persona: "personality", awareness_rules: "rules",
    awareness_triggers: "triggers", awareness_template: "supervisor",
    awareness_reply_style: "reply_style", awareness_source_guidance: "source_guidance",
    awareness_flow: "supervisor_status", awareness_focus: "supervisor_status",
    awareness_intro: "supervisor_status", awareness_source_metadata: "source_status",
    vision_activation: "pipeline", vision_model: "model",
    vision_click: "click", vision_spatial_scan: "scan",
    vision_spatial_categories: "categories", vision_spatial_behavior: "movement",
    vision_guidance_scope: "guidance", vision_guidance_runtime: "runtime"
}

var cardOverrides = {
    companion_orb_include_all_monitors_checkbox: "capture",
    companion_orb_vision_enabled_checkbox: "model",
    companion_orb_vision_runtime_status_label: "model",
    companion_orb_vision_capability_mode_combo: "model_tuning",
    companion_orb_vision_timeout_seconds_spin: "model_tuning",
    companion_orb_vision_min_confidence_spin: "model_tuning",
    companion_orb_vision_capability_hint: "model_tuning",
    companion_orb_vision_target_fallback_only_checkbox: "model_tuning",
    companion_orb_spatial_capture_scope_combo: "scan",
    companion_orb_spatial_capture_scope_note: "scan",
    companion_orb_visual_guidance_help: "guidance"
}

var detailIds = [
    "companion_orb_behavior_strictness", "companion_orb_behavior_emotion",
    "companion_orb_behavior_repeat_mode", "companion_orb_behavior_repeat_interval",
    "companion_orb_supervisor_preview_edit", "btn_companion_orb_reply_style_reset_all",
    "companion_orb_spatial_change_threshold_spin", "companion_orb_spatial_max_regions_spin",
    "companion_orb_spatial_conversational_min_confidence_spin",
    "companion_orb_spatial_movement_cooldown_seconds_spin",
    "companion_orb_spatial_hover_offset_px_spin", "companion_orb_spatial_return_behavior_combo",
    "companion_orb_vision_click_verification_timeout_seconds_spin",
    "companion_orb_vision_click_label_similarity_spin", "companion_orb_vision_click_bounds_overlap_spin",
    "companion_orb_vision_actions_help", "companion_orb_visual_guidance_help"
]

var labels = {
    companion_orb_vision_runtime_status_label: "Model status",
    companion_orb_supervisor_persona_combo: "Orb style",
    companion_orb_supervisor_template_edit: "Supervisor template",
    companion_orb_supervisor_preview_edit: "Supervisor prompt preview",
    companion_orb_reply_style_editor_combo: "Reply style",
    companion_orb_reply_style_prompt_edit: "Reply style prompt",
    companion_orb_vision_runtime_location_combo: "Runtime location",
    companion_orb_vision_base_url_edit: "Base URL",
    companion_orb_vision_model_handling_combo: "Model handling",
    companion_orb_vision_connection_timeout_seconds_spin: "Connection timeout (seconds)",
    companion_orb_vision_capability_mode_combo: "Capability mode",
    companion_orb_vision_timeout_seconds_spin: "Vision timeout (seconds)",
    companion_orb_vision_min_confidence_spin: "Minimum confidence",
    companion_orb_spatial_capture_scope_combo: "Desktop map capture scope",
    companion_orb_spatial_scan_mode_combo: "Scan mode",
    companion_orb_spatial_scan_interval_seconds_spin: "Scan interval (seconds)",
    companion_orb_spatial_map_max_age_seconds_spin: "Maximum map age (seconds)",
    companion_orb_spatial_change_threshold_spin: "Change threshold",
    companion_orb_spatial_max_regions_spin: "Maximum regions",
    companion_orb_spatial_conversational_min_confidence_spin: "Movement confidence",
    companion_orb_spatial_movement_cooldown_seconds_spin: "Movement cooldown (seconds)",
    companion_orb_spatial_hover_offset_px_spin: "Hover offset (pixels)",
    companion_orb_spatial_return_behavior_combo: "Return behavior",
    companion_orb_vision_click_confirmation_method_combo: "Confirmation method",
    companion_orb_vision_click_confirmation_dwell_ms_spin: "Confirmation dwell (ms)",
    companion_orb_vision_click_verification_timeout_seconds_spin: "Verification timeout (seconds)",
    companion_orb_vision_click_label_similarity_spin: "Label similarity",
    companion_orb_vision_click_bounds_overlap_spin: "Bounds overlap"
}

var firstControls = {
    capture: ["companion_orb_capture_scope_combo", "companion_orb_capture_scope_label",
              "unnamed_nowheelslider_target_region_width_640", "unnamed_nowheelslider_target_region_height_420",
              "companion_orb_include_all_monitors_checkbox", "companion_orb_exclude_nc_from_captures_checkbox",
              "companion_orb_capture_exclusion_status_label", "companion_orb_show_target_label_checkbox"],
    model: ["companion_orb_vision_enabled_checkbox", "companion_orb_vision_provider_id_edit",
            "companion_orb_vision_model_id_edit", "companion_orb_vision_catalog_status"]
}

function localId(control) {
    return String(control.id || "").split("::").pop()
}

function placement(control) {
    var id = localId(control)
    if (Boolean(control.presentationHidden) || id.indexOf("companion_orb_watch_") === 0)
        return null // The dedicated watch panel owns these controls.
    return {card: cardOverrides[id] || groupCards[String(control.groupKey || "")] || "other",
            detail: detailIds.indexOf(id) >= 0}
}

function controlsFor(controls, card, detail, scope) {
    var result = []
    for (var i = 0; i < controls.length; ++i) {
        var source = controls[i]
        var target = placement(source)
        if (!target || target.card !== card || target.detail !== detail
                || (source.orbScopeOnly && source.orbScopeOnly !== scope))
            continue
        var copy = {}
        for (var key in source)
            copy[key] = source[key]
        if (labels[localId(source)])
            copy.label = labels[localId(source)]
        result.push(copy)
    }
    var order = firstControls[card] || []
    result.sort(function(left, right) {
        var a = order.indexOf(localId(left))
        var b = order.indexOf(localId(right))
        return (a < 0 ? order.length : a) - (b < 0 ? order.length : b)
    })
    return result
}
