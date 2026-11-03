from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Mapping
from pathlib import Path
import uuid

from PySide6 import QtCore

from core import companion_orb_reply_styles
from core.sensory_prompt_defaults import resolve_prompt
from addons.ai_presence_mode.native_controller import (
    AIPresenceModeController,
    COMPANION_ORB_SESSION_KEYS,
    DEFAULT_SETTINGS,
    ORB_DISPLAY_MODES,
    ORB_POSITIONS,
    ORB_RESPONSE_STYLES,
    ORB_TARGET_MODES,
    ORB_VISUAL_STYLES,
)
from addons.companion_orb_overlay.companion_orb.sensory_source import (
    COMPANION_ORB_TARGET_METADATA,
    COMPANION_ORB_TARGET_PINGPONG_PROMPT,
    PROVIDER_ID as COMPANION_ORB_PROVIDER_ID,
)
from addons.companion_orb_overlay.companion_orb import orb_palettes
from addons.companion_orb_overlay.companion_orb import reading_actions
from addons.companion_orb_overlay.companion_orb import eye_tracking
from addons.companion_orb_overlay.companion_orb.presets import (
    MAX_PRESET_COMMENT_LENGTH,
    MAX_PRESET_NAME_LENGTH,
    CompanionOrbPresetStore,
    OrbPresetCatalog,
    OrbPresetRecord,
)
from addons.companion_orb_overlay.native_controls import (
    native_control_state as build_native_control_state,
    native_update_control as apply_native_control_update,
)
from addons.companion_orb_overlay.native_actions import (
    native_control_action as dispatch_native_control_action,
)
from addons.companion_orb_overlay.companion_orb.vision_guidance import (
    capability_supports_regions,
    normalize_lmstudio_base_url,
    normalize_model_handling,
    normalize_runtime_location,
    normalize_vision_capability_mode,
    probe_lmstudio_models,
)


class _CompanionOrbVisionProbeSignals(QtCore.QObject):
    finished = QtCore.Signal(object)







COMPANION_ORB_AWARE_MOTION_SESSION_KEYS = [
    "companion_orb_aware_motion_enabled",
    "companion_orb_awareness",
    "companion_orb_focus_pull",
    "companion_orb_idle_pause",
]
COMPANION_ORB_AWARE_MOTION_DEFAULTS = {
    "companion_orb_aware_motion_enabled": True,
    "companion_orb_awareness": 0.55,
    "companion_orb_focus_pull": 0.65,
    "companion_orb_idle_pause": 0.45,
}
DEFAULT_SETTINGS.update({key: value for key, value in COMPANION_ORB_AWARE_MOTION_DEFAULTS.items() if key not in DEFAULT_SETTINGS})

COMPANION_ORB_EYE_TRACKING_SESSION_KEYS = [
    "companion_orb_eye_tracking_mode",
    "companion_orb_eye_tracking_reaction_mode",
    "companion_orb_eye_tracking_dwell_ms",
    "companion_orb_eye_tracking_long_gaze_enabled",
    "companion_orb_eye_tracking_click_target_enabled",
    "companion_orb_eye_tracking_long_gaze_ms",
    "companion_orb_eye_tracking_radial_button_gaze_ms",
    "companion_orb_eye_tracking_radial_menu_opacity",
    "companion_orb_eye_tracking_radial_focus_beam_enabled",
    "companion_orb_eye_tracking_expand_read_text_area",
    "companion_orb_eye_tracking_gaze_timer_color",
    "companion_orb_eye_tracking_radius_px",
    "companion_orb_eye_tracking_smoothing",
    "companion_orb_eye_tracking_reaction_cooldown_seconds",
    "companion_orb_eye_tracking_screen_index",
    "companion_orb_eye_tracking_dll_path",
    "companion_orb_eye_tracking_offset_x_px",
    "companion_orb_eye_tracking_offset_y_px",
    "companion_orb_eye_tracking_calibration",
    "companion_orb_eye_tracking_pointer_clearance_enabled",
    "companion_orb_eye_tracking_pointer_clearance_distance_px",
    "companion_orb_eye_tracking_pointer_clearance_timeout_seconds",
    "companion_orb_eye_tracking_blink_click_allowed",
    "companion_orb_eye_tracking_blink_min_ms",
    "companion_orb_eye_tracking_blink_slow_min_ms",
    "companion_orb_eye_tracking_blink_max_ms",
    "companion_orb_eye_tracking_blink_recovery_ms",
    "companion_orb_eye_tracking_blink_double_gap_ms",
    "companion_orb_eye_tracking_blink_click_cooldown_ms",
    "companion_orb_eye_tracking_menu_blink_min_ms",
    "companion_orb_eye_tracking_menu_blink_max_ms",
    "companion_orb_eye_tracking_triple_blink_gap_ms",
    "companion_orb_eye_tracking_back_cooldown_ms",
    "companion_orb_eye_tracking_scroll_speed",
    "companion_orb_eye_tracking_scroll_dead_zone_px",
    "companion_orb_eye_tracking_hotkey",
]
COMPANION_ORB_EYE_TRACKING_DEFAULTS: dict[str, object] = {
    "companion_orb_eye_tracking_mode": "dwell",
    "companion_orb_eye_tracking_reaction_mode": "meaningful",
    "companion_orb_eye_tracking_dwell_ms": 700,
    "companion_orb_eye_tracking_long_gaze_enabled": False,
    "companion_orb_eye_tracking_click_target_enabled": False,
    "companion_orb_eye_tracking_long_gaze_ms": 3000,
    "companion_orb_eye_tracking_radial_button_gaze_ms": 650,
    "companion_orb_eye_tracking_radial_menu_opacity": 0.90,
    "companion_orb_eye_tracking_radial_focus_beam_enabled": True,
    "companion_orb_eye_tracking_expand_read_text_area": True,
    "companion_orb_eye_tracking_gaze_timer_color": "#facc15",
    "companion_orb_eye_tracking_radius_px": 60,
    "companion_orb_eye_tracking_smoothing": 0.28,
    "companion_orb_eye_tracking_reaction_cooldown_seconds": 45,
    "companion_orb_eye_tracking_screen_index": -1,
    "companion_orb_eye_tracking_dll_path": "",
    "companion_orb_eye_tracking_offset_x_px": 0,
    "companion_orb_eye_tracking_offset_y_px": 0,
    "companion_orb_eye_tracking_calibration": {},
    "companion_orb_eye_tracking_pointer_clearance_enabled": False,
    "companion_orb_eye_tracking_pointer_clearance_distance_px": 160,
    "companion_orb_eye_tracking_pointer_clearance_timeout_seconds": 8,
    "companion_orb_eye_tracking_blink_click_allowed": True,
    "companion_orb_eye_tracking_blink_min_ms": 80,
    "companion_orb_eye_tracking_blink_slow_min_ms": 260,
    "companion_orb_eye_tracking_blink_max_ms": 900,
    "companion_orb_eye_tracking_blink_recovery_ms": 80,
    "companion_orb_eye_tracking_blink_double_gap_ms": 1200,
    "companion_orb_eye_tracking_blink_click_cooldown_ms": 450,
    "companion_orb_eye_tracking_menu_blink_min_ms": 1000,
    "companion_orb_eye_tracking_menu_blink_max_ms": 2000,
    "companion_orb_eye_tracking_triple_blink_gap_ms": 450,
    "companion_orb_eye_tracking_back_cooldown_ms": 1500,
    "companion_orb_eye_tracking_scroll_speed": 5,
    "companion_orb_eye_tracking_scroll_dead_zone_px": 100,
    "companion_orb_eye_tracking_hotkey": "Ctrl+Alt+G",
}
DEFAULT_SETTINGS.update(
    {key: value for key, value in COMPANION_ORB_EYE_TRACKING_DEFAULTS.items() if key not in DEFAULT_SETTINGS}
)

COMPANION_ORB_VISION_SESSION_KEYS = [
    'companion_orb_include_all_monitors',
    'companion_orb_screen_target',
    'companion_orb_exclude_nc_from_captures',
    "companion_orb_vision_enabled",
    "companion_orb_show_vision_pipeline_indicator",
    "companion_orb_vision_capability_mode",
    "companion_orb_vision_provider_id",
    "companion_orb_vision_model_id",
    "companion_orb_vision_timeout_seconds",
    "companion_orb_vision_min_confidence",
    "companion_orb_vision_target_fallback_only",
    "companion_orb_visual_guidance_enabled",
    "companion_orb_visual_guidance_gaze_enabled",
    "companion_orb_visual_guidance_drop_enabled",
    "companion_orb_visual_guidance_reading_enabled",
    "companion_orb_vision_runtime_location",
    "companion_orb_vision_base_url",
    "companion_orb_vision_model_handling",
    "companion_orb_vision_connection_timeout_seconds",
    "companion_orb_vision_restore_main_model",
    "companion_orb_vision_primary_parallel_models",
    "companion_orb_vision_click_enabled",
    "companion_orb_vision_click_confirmation_method",
    "companion_orb_vision_click_confirmation_dwell_ms",
    "companion_orb_vision_click_verification_timeout_seconds",
    "companion_orb_vision_click_label_similarity",
    "companion_orb_vision_click_bounds_overlap",
    "companion_orb_vision_click_sound_enabled",
    "companion_orb_spatial_scan_mode",
    "companion_orb_spatial_scan_interval_seconds",
    "companion_orb_spatial_map_max_age_seconds",
    "companion_orb_spatial_change_detection_enabled",
    "companion_orb_spatial_change_threshold",
    "companion_orb_spatial_max_regions",
    "companion_orb_spatial_capture_scope",
    "companion_orb_spatial_include_images",
    "companion_orb_spatial_include_text",
    "companion_orb_spatial_include_controls",
    "companion_orb_spatial_include_windows",
    "companion_orb_spatial_include_media",
    "companion_orb_spatial_include_other_objects",
    "companion_orb_spatial_explicit_commands_enabled",
    "companion_orb_spatial_conversational_focus_enabled",
    "companion_orb_spatial_conversational_min_confidence",
    "companion_orb_spatial_movement_cooldown_seconds",
    "companion_orb_spatial_hover_offset_px",
    "companion_orb_spatial_follow_target_enabled",
    "companion_orb_spatial_stay_during_speech",
    "companion_orb_spatial_return_behavior",
    "companion_orb_eye_tracking_bounding_boxes_enabled",
    "companion_orb_eye_tracking_bounding_box_labels_enabled",
    "companion_orb_eye_tracking_region_select_dwell_ms",
    "companion_orb_eye_tracking_bounding_box_opacity",
    "companion_orb_eye_tracking_bounding_box_width",
    "companion_orb_eye_tracking_bounding_box_normal_color",
    "companion_orb_eye_tracking_bounding_box_hover_color",
    "companion_orb_eye_tracking_bounding_box_selected_color",
    "companion_orb_eye_tracking_bounding_box_min_confidence",
    "companion_orb_eye_tracking_bounding_box_max_visible",
    "companion_orb_eye_tracking_bounding_box_freeze_selected",
    "companion_orb_eye_tracking_bounding_box_show_images",
    "companion_orb_eye_tracking_bounding_box_show_text",
    "companion_orb_eye_tracking_bounding_box_show_controls",
    "companion_orb_eye_tracking_bounding_box_show_windows",
    "companion_orb_eye_tracking_bounding_box_show_media",
    "companion_orb_eye_tracking_bounding_box_show_other",
    "companion_orb_spatial_diagnostics_keep_last_capture",
]
COMPANION_ORB_VISION_DEFAULTS: dict[str, object] = {
    'companion_orb_include_all_monitors': False,
    'companion_orb_screen_target': {},
    'companion_orb_exclude_nc_from_captures': False,
    "companion_orb_vision_enabled": False,
    "companion_orb_show_vision_pipeline_indicator": True,
    "companion_orb_vision_capability_mode": "auto",
    "companion_orb_vision_provider_id": "lmstudio",
    "companion_orb_vision_model_id": "",
    "companion_orb_vision_timeout_seconds": 15.0,
    "companion_orb_vision_min_confidence": 0.45,
    "companion_orb_vision_target_fallback_only": True,
    "companion_orb_visual_guidance_enabled": False,
    "companion_orb_visual_guidance_gaze_enabled": True,
    "companion_orb_visual_guidance_drop_enabled": True,
    "companion_orb_visual_guidance_reading_enabled": True,
    "companion_orb_vision_runtime_location": "primary",
    "companion_orb_vision_base_url": "",
    "companion_orb_vision_model_handling": "auto_load",
    "companion_orb_vision_connection_timeout_seconds": 3.0,
    "companion_orb_vision_restore_main_model": False,
    "companion_orb_vision_primary_parallel_models": True,
    "companion_orb_vision_click_enabled": False,
    "companion_orb_vision_click_confirmation_method": "long_gaze",
    "companion_orb_vision_click_confirmation_dwell_ms": 1200,
    "companion_orb_vision_click_verification_timeout_seconds": 5.0,
    "companion_orb_vision_click_label_similarity": 0.80,
    "companion_orb_vision_click_bounds_overlap": 0.35,
    "companion_orb_vision_click_sound_enabled": True,
    "companion_orb_spatial_scan_mode": "smart_cached",
    "companion_orb_spatial_scan_interval_seconds": 8.0,
    "companion_orb_spatial_map_max_age_seconds": 20.0,
    "companion_orb_spatial_change_detection_enabled": True,
    "companion_orb_spatial_change_threshold": 0.08,
    "companion_orb_spatial_max_regions": 48,
    "companion_orb_spatial_capture_scope": "active_monitor",
    "companion_orb_spatial_include_images": True,
    "companion_orb_spatial_include_text": True,
    "companion_orb_spatial_include_controls": True,
    "companion_orb_spatial_include_windows": True,
    "companion_orb_spatial_include_media": True,
    "companion_orb_spatial_include_other_objects": True,
    "companion_orb_spatial_explicit_commands_enabled": True,
    "companion_orb_spatial_conversational_focus_enabled": True,
    "companion_orb_spatial_conversational_min_confidence": 0.72,
    "companion_orb_spatial_movement_cooldown_seconds": 8.0,
    "companion_orb_spatial_hover_offset_px": 28,
    "companion_orb_spatial_follow_target_enabled": False,
    "companion_orb_spatial_stay_during_speech": True,
    "companion_orb_spatial_return_behavior": "after_speech",
    "companion_orb_eye_tracking_bounding_boxes_enabled": False,
    "companion_orb_eye_tracking_bounding_box_labels_enabled": True,
    "companion_orb_eye_tracking_region_select_dwell_ms": 700,
    "companion_orb_eye_tracking_bounding_box_opacity": 0.70,
    "companion_orb_eye_tracking_bounding_box_width": 2.0,
    "companion_orb_eye_tracking_bounding_box_normal_color": "#38bdf8",
    "companion_orb_eye_tracking_bounding_box_hover_color": "#facc15",
    "companion_orb_eye_tracking_bounding_box_selected_color": "#a78bfa",
    "companion_orb_eye_tracking_bounding_box_min_confidence": 0.55,
    "companion_orb_eye_tracking_bounding_box_max_visible": 24,
    "companion_orb_eye_tracking_bounding_box_freeze_selected": True,
    "companion_orb_eye_tracking_bounding_box_show_images": True,
    "companion_orb_eye_tracking_bounding_box_show_text": True,
    "companion_orb_eye_tracking_bounding_box_show_controls": True,
    "companion_orb_eye_tracking_bounding_box_show_windows": True,
    "companion_orb_eye_tracking_bounding_box_show_media": True,
    "companion_orb_eye_tracking_bounding_box_show_other": False,
    "companion_orb_spatial_diagnostics_keep_last_capture": True,
}
SPATIAL_SCAN_MODES = (
    ("On demand", "on_demand"),
    ("Smart cached", "smart_cached"),
    ("Continuous interval", "continuous"),
)
SPATIAL_CAPTURE_SCOPES = (
    ("Off - target crops only", "off"),
    ("Active monitor (recommended)", "active_monitor"),
    ("Active window", "active_window"),
    ("Selected monitor", "selected_monitor"),
    ("All monitors", "all_screens"),
)
SPATIAL_RETURN_BEHAVIORS = (
    ("After speech", "after_speech"),
    ("After movement cooldown", "after_delay"),
    ("Stay at target", "stay"),
)
COMPANION_ORB_SPATIAL_SETTING_KEYS = frozenset(
    key
    for key in COMPANION_ORB_VISION_SESSION_KEYS
    if key.startswith("companion_orb_spatial_")
    or key.startswith("companion_orb_eye_tracking_bounding_box_")
    or key == "companion_orb_eye_tracking_region_select_dwell_ms"
)
DEFAULT_SETTINGS.update(
    {key: value for key, value in COMPANION_ORB_VISION_DEFAULTS.items() if key not in DEFAULT_SETTINGS}
)

COMPANION_ORB_EYE_TRACKING_MODES = [
    ("Dwell Focus", "dwell"),
    ("Continuous Follow", "continuous"),
    ("Manual Only", "manual"),
    ("Off", "off"),
]
COMPANION_ORB_EYE_TRACKING_REACTION_MODES = [
    ("Meaningful changes", "meaningful"),
    ("Every new dwell", "every_dwell"),
    ("Off", "off"),
]


def _eye_tracking_connection_presentation(code: str) -> tuple[str, str]:
    normalized = str(code or "").strip().lower()
    presentations = {
        "connected": ("Connected", "#22c55e"),
        "connecting": ("Connecting", "#f59e0b"),
        "starting": ("Connecting", "#f59e0b"),
        "reconnecting": ("Reconnecting", "#f59e0b"),
        "stopping": ("Stopping", "#f59e0b"),
        "no_device": ("Tracker not found", "#ef4444"),
        "no_dll": ("Runtime not found", "#ef4444"),
        "error": ("Connection error", "#ef4444"),
        "reaction_error": ("Connection error", "#ef4444"),
        "off": ("Off", "#94a3b8"),
        "orb_disabled": ("Orb inactive", "#94a3b8"),
    }
    return presentations.get(normalized, ("Unavailable", "#ef4444"))


def _eye_tracking_calibration_presentation(state: str) -> tuple[str, str]:
    normalized = str(state or "").strip().lower()
    presentations = {
        "calibrated": ("Calibrated", "#22c55e"),
        "calibrating": ("Calibrating", "#f59e0b"),
        "not_calibrated": ("Not calibrated", "#94a3b8"),
        "recalibration_required": ("Recalibration required", "#f59e0b"),
        "error": ("Calibration error", "#ef4444"),
    }
    return presentations.get(normalized, ("Not calibrated", "#94a3b8"))


def _eye_tracking_pointer_clearance_presentation(
    state: str,
    *,
    enabled: bool,
) -> tuple[str, str]:
    if not bool(enabled):
        return "Off", "#94a3b8"
    normalized = str(state or "").strip().lower()
    presentations = {
        "clear": ("Clear", "#22c55e"),
        "avoiding": ("Moved aside", "#f59e0b"),
        "timeout": ("Temporarily hidden", "#f59e0b"),
    }
    return presentations.get(normalized, ("Clear", "#22c55e"))


def _stable_eye_tracking_movement_preset(orb_size: float) -> dict[str, object]:
    try:
        size = float(orb_size)
    except (TypeError, ValueError):
        size = 92.0
    size = max(36.0, min(220.0, size))
    side_offset = max(64.0, min(140.0, size * 0.55))
    centered_x_offset = -int(round(side_offset + size * 0.5))
    return {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_dwell_ms": 650,
        "companion_orb_eye_tracking_radius_px": 110,
        "companion_orb_eye_tracking_smoothing": 0.16,
        "companion_orb_eye_tracking_offset_x_px": centered_x_offset,
        "companion_orb_eye_tracking_offset_y_px": 0,
        "companion_orb_movement_enabled": False,
        "companion_orb_aware_motion_enabled": False,
        "companion_orb_avoid_mouse": False,
        "companion_orb_harassment_enabled": False,
    }

COMPANION_ORB_READING_SESSION_KEYS = [
    "companion_orb_reader_exclude_from_memory",
    "companion_orb_reader_commentary_prompt",
    "companion_orb_reading_max_chunk_chars",
    "companion_orb_reading_keep_debug_crops",
    "companion_orb_smart_drop_guidance_enabled",
    "companion_orb_smart_drop_guidance_mode",
]
COMPANION_ORB_READING_DEFAULTS: dict[str, object] = {
    **reading_actions.READING_SETTINGS_DEFAULTS,
    "companion_orb_reading_max_chunk_chars": 900,
    "companion_orb_reading_keep_debug_crops": False,
    "companion_orb_smart_drop_guidance_enabled": False,
    "companion_orb_smart_drop_guidance_mode": "smart",
}
DEFAULT_SETTINGS.update({key: value for key, value in COMPANION_ORB_READING_DEFAULTS.items() if key not in DEFAULT_SETTINGS})

COMPANION_ORB_MOOD_DEFAULTS: dict[str, object] = {
    "companion_orb_mood_color_mode": "automatic",
    "companion_orb_manual_mood": "neutral",
}
DEFAULT_SETTINGS.update({key: value for key, value in COMPANION_ORB_MOOD_DEFAULTS.items() if key not in DEFAULT_SETTINGS})

COMPANION_ORB_SMART_DROP_GUIDANCE_MODES = [
    ("Off", "off"),
    ("Fast local hint", "fast"),
    ("Smart image guidance", "smart"),
]
VALID_COMPANION_ORB_SMART_DROP_GUIDANCE_MODES = {value for _label, value in COMPANION_ORB_SMART_DROP_GUIDANCE_MODES}
ORB_COLOR_PALETTE_OPTIONS = orb_palettes.palette_options()
ORB_COLOR_SETTING_KEYS = tuple(orb_palettes.palette_for_id(orb_palettes.CUSTOM_PALETTE_ID).as_color_settings().keys())
COMPANION_ORB_MOOD_COLOR_MODES = [
    ("Automatic", "automatic"),
    ("Manual", "manual"),
    ("Off", "off"),
]
COMPANION_ORB_MOOD_CHOICES = [
    ("Neutral", "neutral"),
    ("Happy", "happy"),
    ("Sad", "sad"),
    ("Angry", "angry"),
    ("Calm", "calm"),
    ("Curious", "curious"),
    ("Excited", "excited"),
    ("Tension", "tension"),
    ("Story / Fantasy", "story"),
    ("Focus", "focus"),
    ("Dark", "dark"),
    ("Epic", "epic"),
    ("Energetic", "energetic"),
]


ORB_STATE_ANIMATIONS = [
    ("Style default", "style_default"),
    ("Calm breathe", "calm_breathe"),
    ("Slow orbit", "slow_orbit"),
    ("Focused pulse", "focused_pulse"),
    ("Thinking swirl", "thinking_swirl"),
    ("Voice ripple", "voice_ripple"),
    ("Energetic sparkle", "energetic_sparkle"),
]

COMPANION_ORB_SUPERVISOR_CONTRIBUTOR_ID = "nc.companion_orb_overlay.behavior"
_LEGACY_ORB_SUPERVISOR_TEMPLATE_HASHES = (
    "a8f8abdbba4d23b4d942bdb639e3dfb3d03ad728c5d604a94ce7ecba4d345050",
    "49bc1b151103e4c8faf767a3c1ad42b2af6d92c552a904a97563366a55db0feb",
    "9d28f4645b717d0b85d05f0055a62615af33c078953e96f7cb3fbdf145594bc8",
)
COMPANION_ORB_SUPERVISOR_TEMPLATE = """Use these rules only for Companion Orb Target input.

Configured rules:
__BEHAVIOR_RULES__

Select at most one rule whose trigger, input scope, and repeat policy match the visible evidence. Set should_speak=true only for that permitted match and include its exact [orb_rule:<rule id>], [companion_orb_supervisor_match], and [orb_subject:<stable visible subject>] tags. Keep the evidence in summary and focus fields; leave proactive_candidate="". When no rule matches, set should_speak=false.
Always set should_generate_image=false and visual_candidate="". Include focus_bounds for the matched visible subject when available."""

SUPERVISOR_STRICTNESS_OPTIONS = [
    "Interpret freely",
    "Follow closely",
    "Say almost exactly",
]
SUPERVISOR_DEFAULT_STRICTNESS = SUPERVISOR_STRICTNESS_OPTIONS[0]
SUPERVISOR_EMOTION_OPTIONS = [
    "Auto",
    "neutral",
    "happy",
    "angry",
    "calculating",
    "condescending",
    "sad",
    "shy",
    "surprised",
]
SUPERVISOR_DEFAULT_EMOTION = SUPERVISOR_EMOTION_OPTIONS[0]
SUPERVISOR_REPEAT_MODE_OPTIONS = [
    "One-off",
    "Every Nth match",
    "Meaningful change only",
]
SUPERVISOR_DEFAULT_REPEAT_MODE = SUPERVISOR_REPEAT_MODE_OPTIONS[2]
SUPERVISOR_DEFAULT_REPEAT_INTERVAL = 3


def _new_supervisor_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"








COMPANION_ORB_TOOLTIPS = {
    "companion_orb_enabled": "Turns the desktop Companion Orb overlay on or off.",
    "companion_orb_enabled_checkbox": "Turns the desktop Companion Orb overlay on or off.",
    "companion_orb_display_mode": "Controls when the orb is visible: off, docked, during interaction, or always visible.",
    "companion_orb_display_mode_combo": "Controls when the orb is visible: off, docked, during interaction, or always visible.",
    "companion_orb_visual_style": "Chooses the Companion Orb visual appearance.",
    "companion_orb_visual_style_combo": "Chooses the Companion Orb visual appearance.",
    "companion_orb_render_backend": "Uses the GPU-native matte renderer, or the original Canvas renderer for compatibility.",
    "companion_orb_render_backend_combo": "Uses the GPU-native matte renderer, or the original Canvas renderer for compatibility.",
    "companion_orb_position": "Chooses the default corner or custom position used when the orb is reset.",
    "companion_orb_position_combo": "Chooses the default corner or custom position used when the orb is reset.",
    "companion_orb_response_style": "Sets the tone used for Companion Orb proactive comments and right-click menu response style.",
    "companion_orb_response_style_combo": "Sets the tone used for Companion Orb proactive comments and right-click menu response style.",
    "companion_orb_reply_style_prompt_group": "The complete, user-visible behavior prompt used when Companion Orb turns visual focus into a spoken reply.",
    "companion_orb_reply_style_editor_combo": "Chooses which Companion Orb reply style prompt is shown in the editor.",
    "companion_orb_reply_style_prompt_edit": "The exact behavior prompt sent for the selected Companion Orb reply style. Save it to override the recommended default.",
    "btn_companion_orb_reply_style_save": "Save the editor text as the selected Companion Orb reply style override.",
    "btn_companion_orb_reply_style_load": "Reload the saved or recommended text for the selected reply style.",
    "btn_companion_orb_reply_style_default": "Remove the custom override for the selected reply style and reload the recommended prompt.",
    "btn_companion_orb_reply_style_reset_all": "Remove all custom Companion Orb reply style prompt overrides.",
    "companion_orb_reader_settings_group": "Settings for the Companion Orb right-click read and comment actions.",
    "companion_orb_reader_exclude_from_memory": "Keeps selected text out of chat memory/history. Comment actions still send the selected text to the selected provider for that one response.",
    "companion_orb_reader_exclude_from_memory_checkbox": "Keeps selected text out of chat memory/history. Comment actions still send the selected text to the selected provider for that one response.",
    "companion_orb_reader_commentary_prompt": "Instruction used when Companion Orb comments on text you selected.",
    "companion_orb_reader_commentary_prompt_edit": "Instruction used when Companion Orb comments on text you selected.",
    "btn_companion_orb_reader_commentary_reload": "Reload the saved selected-text commentary prompt.",
    "btn_companion_orb_reader_commentary_default": "Restore the recommended selected-text commentary prompt.",
    "companion_orb_reading_max_chunk_chars": "Maximum characters per spoken reading chunk.",
    "companion_orb_reading_max_chunk_chars_spin": "Maximum characters per spoken reading chunk.",
    "companion_orb_reading_keep_debug_crops": "Keeps selected-area OCR crops while Orb debug logging is enabled. Use only while debugging.",
    "companion_orb_reading_keep_debug_crops_checkbox": "Keeps selected-area OCR crops while Orb debug logging is enabled. Use only while debugging.",
    "companion_orb_reading_diagnostics_group": "Tools for opening or clearing the Companion Orb selected-area reading debug log.",
    "btn_companion_orb_open_debug_log_folder": "Open the folder containing the Companion Orb debug log.",
    "btn_companion_orb_clear_debug_log": "Clear the Companion Orb debug log.",
    "btn_companion_orb_copy_debug_log_path": "Copy the Companion Orb debug log path to the clipboard.",
    "btn_companion_orb_copy_latest_vision_trace_path": "Copy the latest end-to-end auxiliary vision, Main Chat, and TTS trace path.",
    "companion_orb_smart_drop_guidance_enabled": "Lets Companion Orb prepare one-shot guidance for drop snapshot replies.",
    "companion_orb_smart_drop_guidance_enabled_checkbox": "Lets Companion Orb prepare one-shot guidance for drop snapshot replies.",
    "companion_orb_smart_drop_guidance_mode": "Chooses whether drop snapshot replies use no guidance, a fast local hint, or a smart vision-model guidance pass.",
    "companion_orb_smart_drop_guidance_mode_combo": "Chooses whether drop snapshot replies use no guidance, a fast local hint, or a smart vision-model guidance pass.",
    "companion_orb_show_button": "Shows the Companion Orb overlay and enables its runtime controller.",
    "companion_orb_edit_mode_button": "Temporarily disables click-through so the orb can be moved directly.",
    "companion_orb_placement_mode_button": "Lets the orb choose a focus target from the window or region under it.",
    "companion_orb_clear_target_button": "Clears the current hidden sensory focus target.",
    "companion_orb_reset_position_button": "Moves the orb back to its configured default position.",
    "companion_orb_always_on_top": "Keeps the orb above normal application windows.",
    "companion_orb_always_on_top_checkbox": "Keeps the orb above normal application windows.",
    "companion_orb_click_through_default": "Lets mouse clicks pass through the orb when it is not in edit or menu mode.",
    "companion_orb_click_through_default_checkbox": "Lets mouse clicks pass through the orb when it is not in edit or menu mode.",
    "companion_orb_remember_position": "Stores the custom orb position between sessions.",
    "companion_orb_remember_position_checkbox": "Stores the custom orb position between sessions.",
    "companion_orb_external_runtime_enabled": "Runs the animated orb window in a separate lightweight Python process so NC UI stalls affect it less.",
    "companion_orb_external_runtime_enabled_checkbox": "Runs the animated orb window in a separate lightweight Python process so NC UI stalls affect it less.",
    "companion_orb_movement_enabled": "Allows the orb to drift, return home, and move toward sensory focus targets.",
    "companion_orb_movement_enabled_checkbox": "Allows the orb to drift, return home, and move toward sensory focus targets.",
    "companion_orb_aware_motion_enabled": "Adds subtle pauses, steadier focus, and less mechanical idle paths without increasing speed.",
    "companion_orb_aware_motion_enabled_checkbox": "Adds subtle pauses, steadier focus, and less mechanical idle paths without increasing speed.",
    "companion_orb_avoid_center": "Biases idle movement away from the middle of the screen.",
    "companion_orb_avoid_center_checkbox": "Biases idle movement away from the middle of the screen.",
    "companion_orb_avoid_mouse": "Makes idle movement avoid the pointer instead of hovering near it.",
    "companion_orb_avoid_mouse_checkbox": "Makes idle movement avoid the pointer instead of hovering near it.",
    "companion_orb_mouse_near_fade": "Fades the orb when the pointer is close so it blocks less of the desktop.",
    "companion_orb_mouse_near_fade_checkbox": "Fades the orb when the pointer is close so it blocks less of the desktop.",
    "companion_orb_voice_sync_enabled": "Lets the orb animation react to NC TTS voice level.",
    "companion_orb_voice_sync_enabled_checkbox": "Lets the orb animation react to NC TTS voice level.",
    "companion_orb_falling_particles_enabled": "Adds slow particles dripping from the orb.",
    "companion_orb_falling_particles_enabled_checkbox": "Adds slow particles dripping from the orb.",
    "companion_orb_reduced_effects": "Reduces animation cost for smoother UI performance.",
    "companion_orb_reduced_effects_checkbox": "Reduces animation cost for smoother UI performance.",
    "companion_orb_particles_enabled": "Shows or hides orbiting particles and network points.",
    "companion_orb_particles_enabled_checkbox": "Shows or hides orbiting particles and network points.",
    "companion_orb_shaders_enabled": "Shows or hides glow and shader-like canvas effects.",
    "companion_orb_shaders_enabled_checkbox": "Shows or hides glow and shader-like canvas effects.",
    "companion_orb_custom_colors_enabled": "Uses the custom color fields below instead of style or mood colors.",
    "companion_orb_custom_colors_enabled_checkbox": "Uses the custom color fields below instead of style or mood colors.",
    "companion_orb_color_palette": "Applies a coordinated color palette to the existing Companion Orb visual style.",
    "companion_orb_color_palette_combo": "Applies a coordinated color palette to the existing Companion Orb visual style.",
    "companion_orb_color_workbench_group": "Preview the selected Companion Orb palette before tuning individual channels.",
    "companion_orb_color_channels_group": "Fine-tune the four color channels used by Companion Orb custom colors.",
    "companion_orb_color_preview": "Static preview of the selected Companion Orb palette and custom color channels.",
    "companion_orb_color_source_status": "Shows whether mood colors, a custom palette, or state overrides currently control the orb colors.",
    "btn_companion_orb_apply_custom_colors": "Apply the current custom orb color fields to the running Companion Orb now.",
    "btn_companion_orb_save_custom_colors": "Save the current custom orb color fields and apply them to the running Companion Orb.",
    "companion_orb_primary_color": "Main orb body color. Enable custom orb colors to apply it.",
    "companion_orb_primary_color_edit": "Main orb body color as a hex value. Enable custom orb colors to apply it.",
    "companion_orb_primary_color_pick_button": "Pick the main orb body color.",
    "companion_orb_primary_color_swatch": "Preview of the main orb body color.",
    "companion_orb_secondary_color": "Secondary orb color used for gradients, particles, and accents.",
    "companion_orb_secondary_color_edit": "Secondary orb color as a hex value. Enable custom orb colors to apply it.",
    "companion_orb_secondary_color_pick_button": "Pick the secondary orb color.",
    "companion_orb_secondary_color_swatch": "Preview of the secondary orb color.",
    "companion_orb_accent_color": "Accent color used for rings, highlights, and target markers.",
    "companion_orb_accent_color_edit": "Accent color as a hex value. Enable custom orb colors to apply it.",
    "companion_orb_accent_color_pick_button": "Pick the accent color.",
    "companion_orb_accent_color_swatch": "Preview of the accent color.",
    "companion_orb_glow_color": "Glow color used by the outer light aura.",
    "companion_orb_glow_color_edit": "Glow color as a hex value. Enable custom orb colors to apply it.",
    "companion_orb_glow_color_pick_button": "Pick the glow color.",
    "companion_orb_glow_color_swatch": "Preview of the glow color.",
    "companion_orb_state_colors_enabled": "Overrides mood/custom colors with a dedicated color for idle, thinking, and speaking states.",
    "companion_orb_state_colors_enabled_checkbox": "Overrides mood/custom colors with a dedicated color for idle, thinking, and speaking states.",
    "companion_orb_idle_color": "Orb color used when NC is idle or waiting.",
    "companion_orb_idle_color_edit": "Idle color as a hex value. Enable state color overrides to apply it.",
    "companion_orb_idle_color_pick_button": "Pick the idle/waiting orb color.",
    "companion_orb_idle_color_swatch": "Preview of the idle/waiting orb color.",
    "companion_orb_thinking_color": "Orb color used while NC is thinking or generating.",
    "companion_orb_thinking_color_edit": "Thinking color as a hex value. Enable state color overrides to apply it.",
    "companion_orb_thinking_color_pick_button": "Pick the thinking orb color.",
    "companion_orb_thinking_color_swatch": "Preview of the thinking orb color.",
    "companion_orb_speaking_color": "Orb color used while NC is speaking through TTS.",
    "companion_orb_speaking_color_edit": "Speaking color as a hex value. Enable state color overrides to apply it.",
    "companion_orb_speaking_color_pick_button": "Pick the speaking orb color.",
    "companion_orb_speaking_color_swatch": "Preview of the speaking orb color.",
    "companion_orb_state_animation_enabled": "Applies separate idle, thinking, and speaking animation behavior on top of the selected orb style.",
    "companion_orb_state_animation_enabled_checkbox": "Applies separate idle, thinking, and speaking animation behavior on top of the selected orb style.",
    "companion_orb_idle_animation": "Animation behavior used when NC is idle or waiting.",
    "companion_orb_idle_animation_combo": "Animation behavior used when NC is idle or waiting.",
    "companion_orb_thinking_animation": "Animation behavior used while NC is thinking or generating.",
    "companion_orb_thinking_animation_combo": "Animation behavior used while NC is thinking or generating.",
    "companion_orb_speaking_animation": "Animation behavior used while NC is speaking through TTS.",
    "companion_orb_speaking_animation_combo": "Animation behavior used while NC is speaking through TTS.",
    "companion_orb_size": "Changes the rendered orb size.",
    "companion_orb_size_slider": "Changes the rendered orb size.",
    "companion_orb_opacity": "Controls overall orb transparency.",
    "companion_orb_opacity_slider": "Controls overall orb transparency.",
    "companion_orb_movement_speed": "Controls how quickly the orb drifts, follows targets, and returns home.",
    "companion_orb_movement_speed_slider": "Controls how quickly the orb drifts, follows targets, and returns home.",
    "companion_orb_movement_range": "Controls how far the orb may wander around its resting point.",
    "companion_orb_movement_range_slider": "Controls how far the orb may wander around its resting point.",
    "companion_orb_awareness": "How strongly aware motion makes the orb settle, arc, and watch focus targets.",
    "companion_orb_awareness_slider": "How strongly aware motion makes the orb settle, arc, and watch focus targets.",
    "companion_orb_focus_pull": "How strongly the orb perches near visual focus targets instead of drifting past them.",
    "companion_orb_focus_pull_slider": "How strongly the orb perches near visual focus targets instead of drifting past them.",
    "companion_orb_idle_pause": "How often idle movement pauses briefly as if observing the desktop.",
    "companion_orb_idle_pause_slider": "How often idle movement pauses briefly as if observing the desktop.",
    "companion_orb_frame_rate": "Orb animation update rate. The slider snaps to 30, 60, 90, or 120 FPS.",
    "companion_orb_frame_rate_slider": "Orb animation update rate. The slider snaps to 30, 60, 90, or 120 FPS.",
    "companion_orb_return_home_delay": "Seconds of inactivity before the orb starts easing back toward home.",
    "companion_orb_return_delay_slider": "Seconds of inactivity before the orb starts easing back toward home.",
    "companion_orb_harassment_timer_seconds": "Seconds of no interaction before playful nudges can start.",
    "companion_orb_harassment_timer_slider": "Seconds of no interaction before playful nudges can start.",
    "companion_orb_mouse_near_fade_distance": "Pointer distance at which mouse-near fading begins.",
    "companion_orb_mouse_fade_distance_slider": "Pointer distance at which mouse-near fading begins.",
    "companion_orb_mouse_near_opacity": "Opacity used while the pointer is near the orb.",
    "companion_orb_mouse_near_opacity_slider": "Opacity used while the pointer is near the orb.",
    "companion_orb_trail_length": "Controls how long particle trails and orbit traces feel.",
    "companion_orb_trail_length_slider": "Controls how long particle trails and orbit traces feel.",
    "companion_orb_particle_density": "Number of orbiting particles and network points.",
    "companion_orb_particle_density_slider": "Number of orbiting particles and network points.",
    "companion_orb_falling_particle_density": "Number of falling drip particles.",
    "companion_orb_falling_particle_density_slider": "Number of falling drip particles.",
    "companion_orb_falling_particle_lifetime": "How long falling particles remain visible.",
    "companion_orb_falling_particle_lifetime_slider": "How long falling particles remain visible.",
    "companion_orb_smoke_intensity": "Controls smoke/wisp strength for styles that use it.",
    "companion_orb_smoke_intensity_slider": "Controls smoke/wisp strength for styles that use it.",
    "companion_orb_glow_strength": "Controls outer glow size and intensity.",
    "companion_orb_glow_strength_slider": "Controls outer glow size and intensity.",
    "companion_orb_mood_color_intensity": "Controls how strongly automatic mood colors tint the selected visual style when custom colors are off.",
    "companion_orb_mood_intensity_slider": "Controls how strongly automatic mood colors tint the selected visual style when custom colors are off.",
    "companion_orb_mood_color_mode": "Chooses whether the Companion Orb uses automatic, manual, or no mood tinting.",
    "companion_orb_mood_color_mode_combo": "Chooses whether the Companion Orb uses automatic, manual, or no mood tinting.",
    "companion_orb_manual_mood": "Manual Companion Orb mood tint used when Orb mood colors are set to Manual.",
    "companion_orb_manual_mood_combo": "Manual Companion Orb mood tint used when Orb mood colors are set to Manual.",
    "companion_orb_speaking_reactivity": "Controls how strongly the orb reacts to voice audio level.",
    "companion_orb_speaking_reactivity_slider": "Controls how strongly the orb reacts to voice audio level.",
    "companion_orb_audio_refresh_hz": "How often the orb samples voice level for animation sync.",
    "companion_orb_audio_refresh_slider": "How often the orb samples voice level for animation sync.",
    "companion_orb_sensory_tabs": "Settings for how Companion Orb background awareness is captured and used.",
    "companion_orb_source_guidance_preview": "The background-awareness guidance sent with Companion Orb Target.",
    "companion_orb_source_provider_preview": "Provider metadata declared for Companion Orb Target.",
    "companion_orb_source_ping_payload_preview": "What Companion Orb Target may notice during a background check-in.",
    "companion_orb_source_pong_influence_preview": "How returned observations can guide orb speech and movement.",
    "companion_orb_source_tag_subscriptions_preview": "Event tags this source listens to.",
    "companion_orb_sensory_target_enabled": "Adds Companion Orb Target to hidden sensory feedback so the orb can provide target or full-screen context.",
    "companion_orb_sensory_target_enabled_checkbox": "Adds Companion Orb Target to hidden sensory feedback so the orb can provide target or full-screen context.",
    "companion_orb_full_screen_context_enabled": "Captures a desktop-wide context map so the orb can talk about and move toward content across the screen.",
    "companion_orb_full_screen_context_enabled_checkbox": "Captures a desktop-wide context map so the orb can talk about and move toward content across the screen.",
    "sensory_pingpong_enabled": "Runs background check-ins so selected sensory sources can be reviewed while NC is idle.",
    "companion_orb_pingpong_enabled_checkbox": "Runs background check-ins so Companion Orb Target can be reviewed while NC is idle.",
    "companion_orb_hidden_proactive_speech_checkbox": "Allows grounded Companion Orb background observations to become spoken TTS comments. This is the same safety switch as HOST hidden proactive replies.",
    "companion_orb_target_mode": "Chooses whether the orb targets the window under it or a region around it.",
    "companion_orb_target_mode_combo": "Chooses whether the orb targets the window under it or a region around it.",
    "companion_orb_show_target_label": "Shows a small focus label under the orb when a target is active.",
    "companion_orb_show_target_label_checkbox": "Shows a small focus label under the orb when a target is active.",
    "companion_orb_require_target_confirmation": "Asks before using a newly selected target for hidden sensory feedback.",
    "companion_orb_require_target_confirmation_checkbox": "Asks before using a newly selected target for hidden sensory feedback.",
    "companion_orb_include_process_name": "Allows hidden sensory labels to mention executable or process names.",
    "companion_orb_include_process_name_checkbox": "Allows hidden sensory labels to mention executable or process names.",
    "companion_orb_target_region_width": "Width of the region captured around the orb target.",
    "companion_orb_target_width_slider": "Width of the region captured around the orb target.",
    "companion_orb_target_region_height": "Height of the region captured around the orb target.",
    "companion_orb_target_height_slider": "Height of the region captured around the orb target.",
    "companion_orb_capture_show_button": "Shows the orb before choosing or testing a target.",
    "companion_orb_capture_clear_target_button": "Clears the selected capture target.",
    "companion_orb_capture_reset_position_button": "Moves the orb back to its configured default position.",
    "companion_orb_harassment_enabled": "Lets the orb seek the pointer and make playful comments after the timer expires.",
    "companion_orb_harassment_enabled_checkbox": "Lets the orb seek the pointer and make playful comments after the timer expires.",
    "companion_orb_snapshot_on_pointer_reached": "Takes a snapshot when the orb reaches the pointer during playful seeking.",
    "companion_orb_snapshot_on_pointer_reached_checkbox": "Takes a snapshot when the orb reaches the pointer during playful seeking.",
    "companion_orb_right_drag_focus_enabled": "Right-click dragging and dropping the orb selects a new focus area.",
    "companion_orb_right_drag_focus_enabled_checkbox": "Right-click dragging and dropping the orb selects a new focus area.",
    "companion_orb_debug_enabled": "Writes Orb events and end-to-end image pipeline traces: sent image, auxiliary-vision request/response, Main Chat request/response, and TTS text. Credentials and embedded image data are redacted.",
    "companion_orb_debug_enabled_checkbox": "Writes Orb events and end-to-end image pipeline traces: sent image, auxiliary-vision request/response, Main Chat request/response, and TTS text. Credentials and embedded image data are redacted.",
    "companion_orb_debug_log_path_preview": "Path used for the Companion Orb debug log.",
    "companion_orb_supervisor_enabled": "Enables optional saved behavior rules. Conversational watches work independently with this off.",
    "companion_orb_supervisor_enabled_checkbox": "Enables optional saved behavior rules. Conversational watches work independently with this off.",
    "companion_orb_supervisor_behavior_designer": "Orb personality rules for Companion Orb Target, separate from the HOST Screen Supervisor.",
    "companion_orb_supervisor_persona_combo": "Choose which Companion Orb supervisor persona owns the behavior rules being edited.",
    "companion_orb_supervisor_persona_style_edit": "Tone/style used by the active Companion Orb supervisor persona.",
    "btn_companion_orb_supervisor_add_persona": "Add a new Companion Orb supervisor persona.",
    "btn_companion_orb_supervisor_rename_persona": "Rename the active Companion Orb supervisor persona.",
    "btn_companion_orb_supervisor_delete_persona": "Delete the active Companion Orb supervisor persona.",
    "btn_companion_orb_supervisor_add_behavior": "Add a new visual behavior rule for Companion Orb Target.",
    "companion_orb_supervisor_behaviors_widget": "List of Companion Orb Target visual trigger and action rules.",
    "companion_orb_supervisor_template_edit": "Prompt template that wraps Companion Orb behavior rules before background check-ins.",
    "btn_companion_orb_supervisor_reset_template": "Restore the recommended Companion Orb supervisor prompt template.",
    "companion_orb_supervisor_preview_edit": "Rendered prompt currently sent as behavior guidance for Companion Orb Target.",
    "companion_orb_supervisor_flow_preview": "Overview of the hidden sensory response flow.",
    "companion_orb_supervisor_focus_preview": "Explains the fields that move the orb toward the content it comments on.",
    "companion_orb_hotkeys_enabled": "Enables Companion Orb keyboard shortcuts.",
    "companion_orb_hotkeys_enabled_checkbox": "Enables Companion Orb keyboard shortcuts.",
    "companion_orb_toggle_hotkey": "Shortcut that toggles the orb.",
    "companion_orb_toggle_hotkey_edit": "Shortcut that toggles the orb.",
    "companion_orb_edit_hotkey": "Shortcut that toggles direct orb edit mode.",
    "companion_orb_edit_hotkey_edit": "Shortcut that toggles direct orb edit mode.",
    "companion_orb_placement_hotkey": "Shortcut that toggles target placement mode.",
    "companion_orb_placement_hotkey_edit": "Shortcut that toggles target placement mode.",
    "companion_orb_clear_target_hotkey": "Shortcut that clears the selected focus target.",
    "companion_orb_clear_target_hotkey_edit": "Shortcut that clears the selected focus target.",
    "companion_orb_click_through_hotkey": "Shortcut that toggles click-through behavior.",
    "companion_orb_click_through_hotkey_edit": "Shortcut that toggles click-through behavior.",
    "companion_orb_reset_position_hotkey": "Shortcut that resets the orb position.",
    "companion_orb_reset_position_hotkey_edit": "Shortcut that resets the orb position.",
    "companion_orb_eye_tracking_group": "Optional local Tobii gaze input for Companion Orb motion and visual comments.",
    "companion_orb_eye_tracking_mode_combo": "Dwell Focus follows gaze immediately while a stable dwell gates visual comments. Continuous Follow, Manual Only, and Off provide the other tracking behaviors.",
    "companion_orb_eye_tracking_reaction_mode_combo": "Choose when a completed gaze dwell may request a visual comment.",
    "companion_orb_eye_tracking_screen_combo": "Display calibrated for the eye tracker. Primary display is the safest default.",
    "companion_orb_eye_tracking_dwell_slider": "How long gaze must remain stable before Dwell Focus may capture and request a visual comment. Movement remains immediate.",
    "companion_orb_eye_tracking_long_gaze_checkbox": "Opens a fixed gaze-selectable response menu after one uninterrupted long gaze.",
    "companion_orb_eye_tracking_click_target_checkbox": "Enables the Action gaze button for system-wide application and browser controls. When disabled, no control discovery or target capture runs.",
    "companion_orb_eye_tracking_expand_read_text_area_checkbox": "Doubles only the radial Read text capture width toward the right while preserving its height.",
    "companion_orb_eye_tracking_long_gaze_ms_spin": "Exact uninterrupted gaze time required before the radial response menu opens.",
    "companion_orb_eye_tracking_radial_button_gaze_ms_spin": "Exact time gaze must remain on one radial button before that action is selected.",
    "companion_orb_eye_tracking_radial_menu_opacity_slider": "Controls the Orbital Glass radial menu transparency without changing its gaze targets.",
    "companion_orb_eye_tracking_radial_focus_beam_checkbox": "Shows a red, amber, and yellow charging pulse from the center to the active gaze target.",
    "companion_orb_eye_tracking_gaze_timer_color": "Color blended into the Orb while a normal, long, or radial-button gaze timer is running.",
    "companion_orb_eye_tracking_gaze_timer_color_edit": "Hex color blended into the Orb during gaze countdowns.",
    "companion_orb_eye_tracking_gaze_timer_color_pick_button": "Choose the gaze countdown color.",
    "companion_orb_eye_tracking_gaze_timer_color_swatch": "Preview of the gaze countdown color.",
    "companion_orb_eye_tracking_radius_slider": "How far gaze may move while it is considered one stable focus.",
    "companion_orb_eye_tracking_smoothing_slider": "Balances gaze responsiveness against visible jitter.",
    "companion_orb_eye_tracking_cooldown_slider": "Minimum delay between automatic gaze-triggered comments.",
    "companion_orb_eye_tracking_offset_x_slider": "Fine-tunes the Orb horizontally after gaze mapping. Negative values move it left.",
    "companion_orb_eye_tracking_offset_y_slider": "Fine-tunes the Orb vertically after gaze mapping. Negative values move it up.",
    "companion_orb_eye_tracking_calibration_indicator": "Shows whether a display-specific gaze calibration is missing, running, active, or needs attention.",
    "companion_orb_eye_tracking_calibration_status_label": "Current five-point gaze calibration state.",
    "companion_orb_eye_tracking_calibration_result_label": "Saved calibration quality, aggregate error, and completion time. Raw gaze samples are never shown or stored.",
    "companion_orb_eye_tracking_calibration_start_button": "Starts five three-second targets inside the centered Tobii-supported display area.",
    "companion_orb_eye_tracking_calibration_cancel_button": "Stops calibration without replacing the previous valid calibration.",
    "companion_orb_eye_tracking_calibration_reset_button": "Removes the saved gaze correction while preserving the Orb placement offsets.",
    "companion_orb_eye_tracking_pointer_clearance_checkbox": "Temporarily moves the gaze-following Orb when the mouse pointer needs the same area.",
    "companion_orb_eye_tracking_pointer_clearance_distance_slider": "Maximum temporary distance the Orb may move away from the pointer.",
    "companion_orb_eye_tracking_pointer_clearance_timeout_slider": "How long the Orb stays transparent after repeated pointer interference.",
    "companion_orb_eye_tracking_pointer_clearance_status_label": "Current pointer-clearance state.",
    "companion_orb_eye_tracking_blink_click_allowed_checkbox": "Allows blink-click and eye-command gestures. Blink-click mode itself always starts disabled.",
    "companion_orb_eye_tracking_blink_status_label": "Live blink-click state. Slow blinks toggle the mode; a quick blink clicks only while the radial menu is closed.",
    "companion_orb_eye_tracking_blink_min_ms_slider": "Shortest loss of explicit Tobii gaze validity that can count as a blink.",
    "companion_orb_eye_tracking_blink_slow_min_ms_slider": "Closure duration that reserves a blink for the slow double-blink toggle gesture.",
    "companion_orb_eye_tracking_blink_max_ms_slider": "Longest loss of gaze validity that can count as a blink instead of tracking loss.",
    "companion_orb_eye_tracking_blink_recovery_ms_slider": "Valid gaze required after reopening before a blink is accepted.",
    "companion_orb_eye_tracking_blink_double_gap_ms_slider": "Maximum time between two slow blinks used to enable or disable click mode.",
    "companion_orb_eye_tracking_blink_click_cooldown_ms_slider": "Minimum delay between quick-blink mouse clicks.",
    "companion_orb_eye_tracking_menu_blink_min_ms_slider": "Shortest continuous eye closure that toggles the long-gaze radial-menu setting.",
    "companion_orb_eye_tracking_menu_blink_max_ms_slider": "Longest continuous eye closure accepted as a long-gaze setting toggle instead of tracking loss.",
    "companion_orb_eye_tracking_triple_blink_gap_ms_slider": "Maximum interval between each fast blink in the browser Back gesture.",
    "companion_orb_eye_tracking_back_cooldown_ms_slider": "Minimum delay before another triple-blink Back command can run.",
    "companion_orb_eye_tracking_scroll_speed_slider": "Maximum gaze-controlled scrolling speed.",
    "companion_orb_eye_tracking_scroll_dead_zone_px_slider": "Vertical area around the radial center where gaze does not scroll.",
    "companion_orb_eye_tracking_stable_preset_button": "Applies stable Dwell Focus tuning and disables competing idle, aware, pointer-avoidance, and playful-nudge movement.",
    "companion_orb_eye_tracking_dll_path_edit": "Optional path to the official Tobii Stream Engine DLL.",
    "companion_orb_eye_tracking_browse_button": "Select the official tobii_stream_engine.dll supplied by Tobii.",
    "companion_orb_eye_tracking_reconnect_button": "Restart the local Tobii connection after changing hardware or DLL path.",
    "companion_orb_eye_tracking_react_button": "Request one comment for the latest valid gaze point.",
    "companion_orb_eye_tracking_status_indicator": "Green when the local Tobii tracker is connected, red when unavailable, amber while changing state, and gray when inactive.",
    "companion_orb_eye_tracking_connection_label": "Current local Tobii connection state.",
    "companion_orb_eye_tracking_runtime_label": "Stream Engine DLL currently selected by automatic discovery or the manual path.",
    "companion_orb_eye_tracking_status_label": "Current local eye-tracker connection state. Gaze coordinates are never shown or logged.",
    "companion_orb_eye_tracking_hotkey": "Shortcut that requests a comment at the latest gaze point.",
    "companion_orb_eye_tracking_hotkey_edit": "Shortcut that requests a comment at the latest gaze point.",
}


class CompanionOrbOverlaySettingsController(AIPresenceModeController):
    _spatial_diagnostics_requested = QtCore.Signal()
    SESSION_KEYS = list(
        dict.fromkeys(
            [
                *COMPANION_ORB_SESSION_KEYS,
                *COMPANION_ORB_AWARE_MOTION_SESSION_KEYS,
                *COMPANION_ORB_EYE_TRACKING_SESSION_KEYS,
                *COMPANION_ORB_READING_SESSION_KEYS,
                *COMPANION_ORB_VISION_SESSION_KEYS,
            ]
        )
    )
    PRESET_SETTING_KEYS = tuple(
        key for key in SESSION_KEYS if key != "companion_orb_target_info"
    )
    APPLY_STATUS_MESSAGE = "Companion Orb Overlay settings applied."

    def __init__(self, context):
        super().__init__(context)
        self._companion_orb_supervisor_expanded_behavior_ids: set[str] = set()
        self._vision_probe_signals = _CompanionOrbVisionProbeSignals(self)
        self._vision_probe_signals.finished.connect(
            self._finish_companion_orb_vision_probe
        )
        self._native_vision_probe_status = "Not tested"
        self._native_vision_probe_error = False
        self._last_vision_runtime_snapshot: dict[str, object] = {}
        self._native_spatial_status = "Not tested"
        self._native_spatial_error = False
        self._native_spatial_diagnostics: dict[str, object] = {}
        self._native_selected_preset_id = ""
        self._native_preset_comment = ""
        self._native_reply_style_id = "friendly"
        self._native_reply_style_prompt = ""
        self._spatial_diagnostics_started_epoch = 0.0
        self._spatial_diagnostics_deadline = 0.0
        self._spatial_diagnostics_expected_generation = 0
        self._spatial_diagnostics_poll_timer = QtCore.QTimer(self)
        self._spatial_diagnostics_poll_timer.setInterval(120)
        self._spatial_diagnostics_poll_timer.timeout.connect(
            self._poll_companion_orb_spatial_diagnostics
        )
        self._spatial_diagnostics_requested.connect(
            self._start_companion_orb_spatial_diagnostics,
            QtCore.Qt.QueuedConnection,
        )
        storage = getattr(context, "storage", None)
        resolve_storage = getattr(storage, "resolve", None)
        preset_root = (
            Path(resolve_storage("presets"))
            if callable(resolve_storage)
            else Path("runtime") / "companion_orb_overlay" / "presets"
        )
        self._companion_orb_preset_store = CompanionOrbPresetStore(
            preset_root,
            self.PRESET_SETTING_KEYS,
        )
        self._companion_orb_direct_service = None
        self._register_companion_orb_supervisor_contributor()

    def _default_companion_orb_supervisor_personas(self):
        return [
            {
                "id": "orb_supervisor_persona",
                "name": "Orb Supervisor",
                "style": "playful, observant desktop companion that comments on visible content with concise curiosity",
                "behaviors": [
                    {
                        "id": "orb_behavior_manual_drop",
                        "enabled": True,
                        "trigger": "The user manually drops or places the orb over readable text, a button, an image, an alert, a panel, or another visually meaningful detail.",
                        "action": "Comment on the visible content inside that selected crop and move toward the exact text, image, button, or object being discussed.",
                        "strictness": SUPERVISOR_DEFAULT_STRICTNESS,
                        "emotion": SUPERVISOR_DEFAULT_EMOTION,
                        "repeat_mode": SUPERVISOR_DEFAULT_REPEAT_MODE,
                        "repeat_interval": SUPERVISOR_DEFAULT_REPEAT_INTERVAL,
                    },
                    {
                        "id": "orb_behavior_full_screen_subject",
                        "enabled": False,
                        "trigger": "The full-screen context map shows a newly interesting visible subject, such as an active document, image, video, alert, search result, or UI control.",
                        "action": "Make one short grounded observation about that subject and provide focus_bounds so the orb can hover near it.",
                        "strictness": SUPERVISOR_DEFAULT_STRICTNESS,
                        "emotion": SUPERVISOR_DEFAULT_EMOTION,
                        "repeat_mode": SUPERVISOR_DEFAULT_REPEAT_MODE,
                        "repeat_interval": SUPERVISOR_DEFAULT_REPEAT_INTERVAL,
                    },
                ],
            }
        ]

    def _normalize_supervisor_strictness(self, value):
        text = str(value or SUPERVISOR_DEFAULT_STRICTNESS).strip()
        return text if text in SUPERVISOR_STRICTNESS_OPTIONS else SUPERVISOR_DEFAULT_STRICTNESS

    def _normalize_supervisor_emotion(self, value):
        text = str(value or SUPERVISOR_DEFAULT_EMOTION).strip()
        return text if text in SUPERVISOR_EMOTION_OPTIONS else SUPERVISOR_DEFAULT_EMOTION

    def _normalize_supervisor_repeat_mode(self, value):
        text = str(value or SUPERVISOR_DEFAULT_REPEAT_MODE).strip()
        return text if text in SUPERVISOR_REPEAT_MODE_OPTIONS else SUPERVISOR_DEFAULT_REPEAT_MODE

    def _normalize_supervisor_repeat_interval(self, value):
        try:
            number = int(value)
        except Exception:
            number = SUPERVISOR_DEFAULT_REPEAT_INTERVAL
        return max(1, min(999, number))

    def _normalize_companion_orb_supervisor_personas(self, value):
        items = []
        for raw_persona in list(value or []):
            if not isinstance(raw_persona, Mapping):
                continue
            persona_id = str(raw_persona.get("id") or "").strip() or _new_supervisor_id("orb_persona")
            name = str(raw_persona.get("name") or "").strip() or "Orb Supervisor"
            style = str(raw_persona.get("style") or "").strip() or "playful, observant desktop companion"
            behaviors = []
            for raw_behavior in list(raw_persona.get("behaviors") or []):
                if not isinstance(raw_behavior, Mapping):
                    continue
                trigger = str(raw_behavior.get("trigger") or "").strip()
                action = str(raw_behavior.get("action") or "").strip()
                behaviors.append(
                    {
                        "id": str(raw_behavior.get("id") or "").strip() or _new_supervisor_id("orb_behavior"),
                        "enabled": bool(raw_behavior.get("enabled", True)),
                        "trigger": trigger,
                        "action": action,
                        "strictness": self._normalize_supervisor_strictness(raw_behavior.get("strictness")),
                        "emotion": self._normalize_supervisor_emotion(raw_behavior.get("emotion")),
                        "repeat_mode": self._normalize_supervisor_repeat_mode(raw_behavior.get("repeat_mode")),
                        "repeat_interval": self._normalize_supervisor_repeat_interval(raw_behavior.get("repeat_interval")),
                    }
                )
            items.append({"id": persona_id, "name": name, "style": style, "behaviors": behaviors})
        return items or self._default_companion_orb_supervisor_personas()

    def _companion_orb_supervisor_personas(self):
        personas = self._normalize_companion_orb_supervisor_personas(
            self._runtime_config().get("companion_orb_supervisor_personas", [])
        )
        if personas != self._runtime_config().get("companion_orb_supervisor_personas"):
            self._update_runtime_config("companion_orb_supervisor_personas", personas)
        return personas

    def _set_companion_orb_supervisor_personas(self, personas):
        normalized = self._normalize_companion_orb_supervisor_personas(personas)
        selected_id = str(self._runtime_config().get("companion_orb_supervisor_selected_persona_id") or "").strip()
        if selected_id not in {item["id"] for item in normalized}:
            self._update_runtime_config("companion_orb_supervisor_selected_persona_id", normalized[0]["id"])
        self._update_runtime_config("companion_orb_supervisor_personas", normalized)
        self._publish_companion_orb_supervisor()
        return normalized

    def _selected_companion_orb_supervisor_persona(self):
        personas = self._companion_orb_supervisor_personas()
        selected_id = str(self._runtime_config().get("companion_orb_supervisor_selected_persona_id") or "").strip()
        for persona in personas:
            if persona["id"] == selected_id:
                return persona
        self._update_runtime_config("companion_orb_supervisor_selected_persona_id", personas[0]["id"])
        return personas[0]

    def _find_companion_orb_supervisor_persona(self, persona_id):
        key = str(persona_id or "").strip()
        for persona in self._companion_orb_supervisor_personas():
            if persona["id"] == key:
                return persona
        return None

    def _find_companion_orb_supervisor_behavior(self, persona, behavior_id):
        key = str(behavior_id or "").strip()
        for behavior in list((persona or {}).get("behaviors") or []):
            if behavior.get("id") == key:
                return behavior
        return None

    def _companion_orb_supervisor_template(self):
        return resolve_prompt(
            self._runtime_config().get("companion_orb_supervisor_prompt_template", ""),
            COMPANION_ORB_SUPERVISOR_TEMPLATE,
            legacy_hashes=_LEGACY_ORB_SUPERVISOR_TEMPLATE_HASHES,
        )

    def _strictness_instruction(self, value):
        strictness = self._normalize_supervisor_strictness(value)
        if strictness == "Say almost exactly":
            return "Use the Action wording as closely as possible while still grounding it in visible evidence."
        if strictness == "Follow closely":
            return "Follow the Action closely, adapting only what is needed for the current visible content."
        return "Use the Action as intent and adapt naturally to the current visible content."

    def _repeat_policy_instruction(self, mode, interval):
        repeat_mode = self._normalize_supervisor_repeat_mode(mode)
        repeat_interval = self._normalize_supervisor_repeat_interval(interval)
        if repeat_mode == "Every Nth match":
            return f"Comment only every {repeat_interval} matching refresh(es), unless the user manually selected the target."
        if repeat_mode == "Meaningful change only":
            return "Comment only when the visible subject or evidence meaningfully changes, or when the user manually selected a fresh target."
        return "Comment once for this matching subject, then stay quiet until the subject changes."

    def _render_companion_orb_supervisor_behavior_rules(self, persona=None, *, include_delivery_details=False):
        active = persona or self._selected_companion_orb_supervisor_persona()
        lines = []
        index = 0
        for behavior in list(active.get("behaviors") or []):
            if not bool(behavior.get("enabled", True)):
                continue
            trigger = str(behavior.get("trigger") or "").strip()
            action = str(behavior.get("action") or "").strip()
            if not trigger or not action:
                continue
            index += 1
            emotion = self._normalize_supervisor_emotion(behavior.get("emotion"))
            emotion_line = "Auto." if emotion == SUPERVISOR_DEFAULT_EMOTION else f"Prefer emotion={emotion}."
            behavior_id = str(behavior.get("id") or "").strip()
            if behavior.get('background_check_in') is False or behavior_id == "orb_behavior_manual_drop":
                input_scope = "Manual Orb inspection only; never match an ordinary timed background check-in."
            elif behavior.get('manual_inspection') is False or behavior_id == "orb_behavior_full_screen_subject":
                input_scope = "Timed full-screen background check-ins only."
            else:
                input_scope = "Manual Orb inspections or timed background check-ins."
            fields = [
                f"{index}. Rule ID: {behavior_id}",
                f"   Visual Trigger: {trigger}",
            ]
            if include_delivery_details:
                fields.extend((
                    f"   Action: {action}",
                    f"   Strictness: {self._strictness_instruction(behavior.get('strictness'))}",
                    f"   Emotion override: {emotion_line}",
                ))
            fields.extend((
                f"   Match tag: [orb_rule:{behavior_id}]",
                f"   Input scope: {input_scope}",
                f"   Repeat policy: {self._repeat_policy_instruction(behavior.get('repeat_mode'), behavior.get('repeat_interval'))}",
            ))
            lines.append("\n".join(fields))
        if not lines:
            return "No Companion Orb supervisor behaviors are configured. Set should_speak=false for this behavior."
        return "\n".join(lines)

    def _render_companion_orb_supervisor_prompt(self, persona=None, *, use_default_template=False):
        active = persona or self._selected_companion_orb_supervisor_persona()
        rendered = (COMPANION_ORB_SUPERVISOR_TEMPLATE if use_default_template
                    else self._companion_orb_supervisor_template())
        custom_template = (rendered.strip().replace('\r\n', '\n')
                           != COMPANION_ORB_SUPERVISOR_TEMPLATE.strip().replace('\r\n', '\n'))
        rendered = rendered.replace("__PERSONA_NAME__", str(active.get("name") or "Orb Supervisor"))
        rendered = rendered.replace("__PERSONA_STYLE__", str(active.get("style") or "playful, observant desktop companion"))
        rendered = rendered.replace(
            "__BEHAVIOR_RULES__",
            self._render_companion_orb_supervisor_behavior_rules(
                active,
                include_delivery_details=custom_template,
            ),
        )
        return rendered.strip()

    def _sensory_service(self):
        return self.context.capabilities.sensory_targets

    def _register_companion_orb_supervisor_contributor(self):
        sensory_service = self._sensory_service()
        if sensory_service is None:
            return
        config = self._runtime_config()
        supervisor_enabled = bool(config.get("companion_orb_supervisor_enabled", False))
        orb = self._companion_orb_service()
        watch_owner = getattr(orb, 'watch_context', None)
        watch = watch_owner.current(config) if watch_owner is not None else {}
        if not supervisor_enabled and not watch.get('active'):
            sensory_service.unregister_prompt_contributor(COMPANION_ORB_SUPERVISOR_CONTRIBUTOR_ID)
            return
        active = (self._selected_companion_orb_supervisor_persona() if supervisor_enabled
                  else dict(name='Conversational watch', style='concise, grounded observations', behaviors=[]))
        active_behaviors = [
            {
                "id": str(behavior.get("id") or "").strip(),
                "trigger": str(behavior.get("trigger") or "").strip(),
                "action": str(behavior.get("action") or "").strip(),
                "strictness": self._normalize_supervisor_strictness(behavior.get("strictness")),
                "emotion": self._normalize_supervisor_emotion(behavior.get("emotion")),
                "manual_inspection": str(behavior.get("id") or "").strip()
                != "orb_behavior_full_screen_subject",
                "background_check_in": str(behavior.get("id") or "").strip()
                != "orb_behavior_manual_drop",
                "repeat_mode": self._normalize_supervisor_repeat_mode(behavior.get("repeat_mode")),
                "repeat_interval": self._normalize_supervisor_repeat_interval(behavior.get("repeat_interval")),
            }
            for behavior in list(active.get("behaviors") or [])
            if bool(behavior.get("enabled", True))
            and str(behavior.get("trigger") or "").strip()
            and str(behavior.get("action") or "").strip()
        ]
        from addons.companion_orb_overlay.companion_orb.watch_evidence import project_watch_behaviors
        active_behaviors = project_watch_behaviors(active_behaviors, watch)
        if not active_behaviors and not watch:
            sensory_service.unregister_prompt_contributor(COMPANION_ORB_SUPERVISOR_CONTRIBUTOR_ID)
            return
        sensory_service.register_prompt_contributor(
            contributor_id=COMPANION_ORB_SUPERVISOR_CONTRIBUTOR_ID,
            source_id=COMPANION_ORB_PROVIDER_ID,
            label="Companion Orb Supervisor",
            prompt=self._render_companion_orb_supervisor_prompt(
                dict(active, behaviors=active_behaviors), use_default_template=not supervisor_enabled),
            order=212,
            metadata={
                "type": "behavior_rule",
                "persona_name": str(active.get("name") or "Orb Supervisor"),
                "persona_style": str(active.get("style") or "playful, observant desktop companion"),
                "behavior_count": len(list(active.get("behaviors") or [])),
                "active_behaviors": active_behaviors,
                "orb_watch": watch,
            },
        )

    def _publish_companion_orb_supervisor(self):
        self._register_companion_orb_supervisor_contributor()
        self._notify_host_settings_changed()
        self._save_session()

    def _unregister_companion_orb_supervisor_contributor(self):
        sensory_service = self._sensory_service()
        if sensory_service is not None:
            sensory_service.unregister_prompt_contributor(COMPANION_ORB_SUPERVISOR_CONTRIBUTOR_ID)

    def _parse_sensory_sources(self, value=None):
        raw = self._runtime_config().get("sensory_feedback_source", "off") if value is None else value
        if isinstance(raw, (list, tuple, set)):
            tokens = [str(item or "").strip().lower() for item in list(raw or [])]
        else:
            tokens = [part.strip().lower() for part in str(raw or "off").split(",")]
        selected = []
        seen = set()
        for token in tokens:
            if not token or token == "off" or token in seen:
                continue
            selected.append(token)
            seen.add(token)
        return selected

    def _sensory_sources_value(self, sources):
        selected = self._parse_sensory_sources(sources)
        return ",".join(selected) if selected else "off"

    def _notify_host_settings_changed(self) -> bool:
        try:
            shell = self.context.capabilities.shell if getattr(self, "context", None) is not None else None
            notifier = getattr(shell, "notify_settings_changed", None)
            if not callable(notifier):
                return False
            notifier()
            return True
        except Exception:
            return False

    def _save_session(self) -> None:
        if self._notify_host_settings_changed():
            return
        super()._save_session()








    def _companion_orb_preset_settings_snapshot(self) -> dict[str, object]:
        config = self._runtime_config()
        payload = {
            key: config[key]
            for key in self.PRESET_SETTING_KEYS
            if key in config
        }
        return payload

    def _apply_companion_orb_preset_record(self, record: OrbPresetRecord) -> None:
        normalized = {
            key: self._normalize_setting(key, value)
            for key, value in record.settings.items()
            if key in self.PRESET_SETTING_KEYS
        }
        for key, value in normalized.items():
            self._update_runtime_config(key, value)
        self.refresh_from_runtime()
        self._apply_runtime_config()
        self._save_session()
        self._set_status(f"Loaded Companion Orb preset: {record.name}.")







    def _set_companion_orb_source_included(self, enabled: bool):
        selected = self._parse_sensory_sources()
        selected_set = set(selected)
        if enabled:
            selected_set.add(COMPANION_ORB_PROVIDER_ID)
        else:
            selected_set.discard(COMPANION_ORB_PROVIDER_ID)
        ordered = [provider_id for provider_id in selected if provider_id in selected_set]
        if enabled and COMPANION_ORB_PROVIDER_ID not in ordered:
            ordered.append(COMPANION_ORB_PROVIDER_ID)
        config_value = self._sensory_sources_value(ordered)
        if config_value != str(self._runtime_config().get("sensory_feedback_source", "off") or "off"):
            self._update_runtime_config("sensory_feedback_source", config_value)
            self._notify_host_settings_changed()
        return config_value

    def _companion_orb_source_included(self):
        return COMPANION_ORB_PROVIDER_ID in set(self._parse_sensory_sources())

    def _reply_style_prompt_overrides(self):
        return companion_orb_reply_styles.normalize_reply_style_prompts(
            self._runtime_config().get("companion_orb_response_style_prompts", {})
        )







    def _reader_commentary_prompt_default(self) -> str:
        return str(
            reading_actions.READING_SETTINGS_DEFAULTS.get(
                "companion_orb_reader_commentary_prompt",
                reading_actions.DEFAULT_COMMENTARY_PROMPT,
            )
            or reading_actions.DEFAULT_COMMENTARY_PROMPT
        )

    def _reader_commentary_prompt_value(self) -> str:
        text = str(
            self._runtime_config().get(
                "companion_orb_reader_commentary_prompt",
                self._reader_commentary_prompt_default(),
            )
            or ""
        ).strip()
        return text or self._reader_commentary_prompt_default()

    def _reading_chunk_size_value(self) -> int:
        return int(
            self._normalize_setting(
                "companion_orb_reading_max_chunk_chars",
                self._runtime_config().get(
                    "companion_orb_reading_max_chunk_chars",
                    COMPANION_ORB_READING_DEFAULTS["companion_orb_reading_max_chunk_chars"],
                ),
            )
        )












    def _normalize_setting(self, key, value):
            key = str(key or "").strip()
            if key in COMPANION_ORB_SPATIAL_SETTING_KEYS:
                return self._normalize_spatial_setting(key, value)
            if key in {
                "companion_orb_vision_enabled",
                "companion_orb_vision_target_fallback_only",
                "companion_orb_visual_guidance_enabled",
                "companion_orb_visual_guidance_gaze_enabled",
                "companion_orb_visual_guidance_drop_enabled",
                "companion_orb_visual_guidance_reading_enabled",
                "companion_orb_vision_restore_main_model",
                "companion_orb_vision_primary_parallel_models",
                "companion_orb_vision_click_enabled",
                "companion_orb_vision_click_sound_enabled",
            }:
                if isinstance(value, str):
                    return value.strip().lower() not in {"0", "false", "no", "off", ""}
                return bool(value)
            if key in {
                "companion_orb_vision_provider_id",
                "companion_orb_vision_model_id",
            }:
                return str(value or "").strip()
            if key == "companion_orb_vision_capability_mode":
                return normalize_vision_capability_mode(value)
            if key == "companion_orb_vision_timeout_seconds":
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = float(COMPANION_ORB_VISION_DEFAULTS[key])
                if numeric == 3.0:
                    numeric = float(COMPANION_ORB_VISION_DEFAULTS[key])
                return max(0.5, min(60.0, numeric))
            if key == "companion_orb_vision_connection_timeout_seconds":
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = float(COMPANION_ORB_VISION_DEFAULTS[key])
                return max(0.5, min(15.0, numeric))
            if key == "companion_orb_vision_runtime_location":
                return normalize_runtime_location(value)
            if key == "companion_orb_vision_model_handling":
                return normalize_model_handling(value)
            if key == "companion_orb_vision_base_url":
                return str(value or "").strip()
            if key == "companion_orb_vision_min_confidence":
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = float(COMPANION_ORB_VISION_DEFAULTS[key])
                return max(0.0, min(1.0, numeric))
            if key == "companion_orb_vision_click_confirmation_method":
                normalized = str(value or "").strip().lower()
                return normalized if normalized in {"long_gaze", "double_blink"} else "long_gaze"
            if key == "companion_orb_vision_click_confirmation_dwell_ms":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_VISION_DEFAULTS[key])
                return max(500, min(5000, numeric))
            if key == "companion_orb_vision_click_verification_timeout_seconds":
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = float(COMPANION_ORB_VISION_DEFAULTS[key])
                return max(1.0, min(15.0, numeric))
            if key in {
                "companion_orb_vision_click_label_similarity",
                "companion_orb_vision_click_bounds_overlap",
            }:
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = float(COMPANION_ORB_VISION_DEFAULTS[key])
                return max(0.0, min(1.0, numeric))
            if key == "companion_orb_eye_tracking_mode":
                return eye_tracking.normalize_tracking_mode(value)
            if key == "companion_orb_eye_tracking_reaction_mode":
                return eye_tracking.normalize_reaction_mode(value)
            if key == "companion_orb_eye_tracking_dwell_ms":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(300, min(2000, numeric))
            if key in {
                "companion_orb_eye_tracking_long_gaze_enabled",
                "companion_orb_eye_tracking_click_target_enabled",
                "companion_orb_eye_tracking_radial_focus_beam_enabled",
                "companion_orb_eye_tracking_expand_read_text_area",
                "companion_orb_eye_tracking_pointer_clearance_enabled",
                "companion_orb_eye_tracking_blink_click_allowed",
            }:
                if isinstance(value, str):
                    return value.strip().lower() not in {"0", "false", "no", "off", ""}
                return bool(value)
            if key == "companion_orb_eye_tracking_long_gaze_ms":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(1000, min(15000, numeric))
            if key == "companion_orb_eye_tracking_radial_button_gaze_ms":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(250, min(3000, numeric))
            if key == "companion_orb_eye_tracking_radial_menu_opacity":
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = float(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(0.35, min(1.0, numeric))
            if key == "companion_orb_eye_tracking_gaze_timer_color":
                text = str(value or COMPANION_ORB_EYE_TRACKING_DEFAULTS[key]).strip()
                if not text.startswith("#"):
                    text = "#" + text
                text = text[:7]
                if len(text) != 7:
                    return str(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                try:
                    int(text[1:], 16)
                except ValueError:
                    return str(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return text.lower()
            if key == "companion_orb_eye_tracking_radius_px":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(24, min(180, numeric))
            if key == "companion_orb_eye_tracking_smoothing":
                try:
                    numeric = float(value)
                except (TypeError, ValueError):
                    numeric = float(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(0.05, min(0.85, numeric))
            if key == "companion_orb_eye_tracking_reaction_cooldown_seconds":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(10, min(300, numeric))
            if key == "companion_orb_eye_tracking_screen_index":
                try:
                    return max(-1, min(31, int(value)))
                except (TypeError, ValueError):
                    return -1
            if key == "companion_orb_eye_tracking_dll_path":
                return str(value or "").strip().strip('"')
            if key in {
                "companion_orb_eye_tracking_offset_x_px",
                "companion_orb_eye_tracking_offset_y_px",
            }:
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(-400, min(400, numeric))
            if key == "companion_orb_eye_tracking_calibration":
                return dict(value) if isinstance(value, dict) else {}
            if key == "companion_orb_eye_tracking_pointer_clearance_distance_px":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(40, min(400, numeric))
            if key == "companion_orb_eye_tracking_pointer_clearance_timeout_seconds":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                return max(1, min(30, numeric))
            blink_ranges = {
                "companion_orb_eye_tracking_blink_min_ms": (40, 300),
                "companion_orb_eye_tracking_blink_slow_min_ms": (150, 700),
                "companion_orb_eye_tracking_blink_max_ms": (400, 1500),
                "companion_orb_eye_tracking_blink_recovery_ms": (30, 300),
                "companion_orb_eye_tracking_blink_double_gap_ms": (400, 2500),
                "companion_orb_eye_tracking_blink_click_cooldown_ms": (200, 1500),
                "companion_orb_eye_tracking_menu_blink_min_ms": (700, 1800),
                "companion_orb_eye_tracking_menu_blink_max_ms": (1200, 3000),
                "companion_orb_eye_tracking_triple_blink_gap_ms": (200, 900),
                "companion_orb_eye_tracking_back_cooldown_ms": (500, 5000),
                "companion_orb_eye_tracking_scroll_speed": (1, 10),
                "companion_orb_eye_tracking_scroll_dead_zone_px": (40, 300),
            }
            if key in blink_ranges:
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
                minimum, maximum = blink_ranges[key]
                return max(minimum, min(maximum, numeric))
            if key == "companion_orb_reader_exclude_from_memory":
                if isinstance(value, str):
                    return value.strip().lower() not in {"0", "false", "no", "off"}
                return bool(value)
            if key == "companion_orb_reader_commentary_prompt":
                text = str(value or "").strip()
                return text or self._reader_commentary_prompt_default()
            if key == "companion_orb_reading_max_chunk_chars":
                try:
                    numeric = int(value)
                except (TypeError, ValueError):
                    numeric = int(COMPANION_ORB_READING_DEFAULTS["companion_orb_reading_max_chunk_chars"])
                return max(100, min(5000, numeric))
            if key == "companion_orb_reading_keep_debug_crops":
                if isinstance(value, str):
                    return value.strip().lower() not in {"0", "false", "no", "off"}
                return bool(value)
            if key == "companion_orb_smart_drop_guidance_enabled":
                if isinstance(value, str):
                    return value.strip().lower() not in {"0", "false", "no", "off"}
                return bool(value)
            if key == "companion_orb_smart_drop_guidance_mode":
                mode = str(value or "off").strip().lower()
                return mode if mode in VALID_COMPANION_ORB_SMART_DROP_GUIDANCE_MODES else "smart"
            if key == "companion_orb_color_palette":
                return orb_palettes.normalize_palette_id(value)
            return super()._normalize_setting(key, value)


    def _apply_runtime_config(self):
        super()._apply_runtime_config()
        self._push_companion_orb_runtime_settings()

    def _push_companion_orb_runtime_settings(self):
        try:
            orb = self._companion_orb_service()
            requester = getattr(orb, "request_settings", None)
            if callable(requester):
                requester(dict(self._runtime_config()))
        except Exception:
            pass



    def _set_companion_orb_vision_probe_status(
        self,
        message: str,
        *,
        error: bool = False,
    ) -> None:
        self._native_vision_probe_status = str(message or "")
        self._native_vision_probe_error = bool(error)
        self._set_status(self._native_vision_probe_status)

    def _start_companion_orb_vision_probe(self):
        settings = dict(self._runtime_config())
        location = normalize_runtime_location(
            settings.get("companion_orb_vision_runtime_location", "primary")
        )
        if location == "primary":
            provider_settings = settings.get("chat_provider_settings", {})
            lmstudio_settings = (
                provider_settings.get("lmstudio", {})
                if isinstance(provider_settings, Mapping)
                else {}
            )
            raw_base_url = (
                lmstudio_settings.get("base_url", "")
                if isinstance(lmstudio_settings, Mapping)
                else ""
            )
            raw_base_url = raw_base_url or "http://127.0.0.1:1234/v1"
        else:
            raw_base_url = settings.get("companion_orb_vision_base_url", "")
        try:
            base_url = normalize_lmstudio_base_url(raw_base_url, required=True)
        except ValueError as exc:
            self._finish_companion_orb_vision_probe(
                {"ok": False, "error": str(exc)}
            )
            return
        timeout_seconds = self._normalize_setting(
            "companion_orb_vision_connection_timeout_seconds",
            settings.get("companion_orb_vision_connection_timeout_seconds", 3.0),
        )
        model_id = str(
            settings.get("companion_orb_vision_model_id", "") or ""
        ).strip()
        self._set_companion_orb_vision_probe_status("Testing connection...")

        def worker() -> None:
            try:
                models = probe_lmstudio_models(
                    base_url,
                    timeout_seconds=float(timeout_seconds),
                )
                payload = {"ok": True, "models": models, "model_id": model_id}
            except Exception as exc:
                reason = re.sub(
                    r"https?://\S+",
                    "[server]",
                    str(exc or exc.__class__.__name__),
                    flags=re.IGNORECASE,
                )
                reason = re.sub(r"\s+", " ", reason).strip()[:160]
                payload = {
                    "ok": False,
                    "error": reason or exc.__class__.__name__,
                }
            self._vision_probe_signals.finished.emit(payload)

        threading.Thread(
            target=worker,
            name="companion-orb-lfm-probe",
            daemon=True,
        ).start()

    def _finish_companion_orb_vision_probe(self, payload: object) -> None:
        result = dict(payload) if isinstance(payload, Mapping) else {}
        if not bool(result.get("ok")):
            self._set_companion_orb_vision_probe_status(
                "Connection failed: "
                + str(result.get("error") or "unavailable"),
                error=True,
            )
            return
        models = tuple(
            str(item or "").strip() for item in result.get("models", ())
        )
        model_id = str(result.get("model_id") or "").strip()
        message = (
            "Connected - model available"
            if model_id and model_id in models
            else "Connected - configured model not listed"
        )
        self._set_companion_orb_vision_probe_status(message)

    @staticmethod
    def _spatial_diagnostics_error(value: object) -> str:
        message = re.sub(
            r"https?://\S+",
            "[server]",
            str(value or "Visual grounding failed."),
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", message).strip()[:320]

    @staticmethod
    def _spatial_diagnostics_json(payload: Mapping[str, object]) -> str:
        data = dict(payload or {}) if isinstance(payload, Mapping) else {}
        details = {
            "state": data.get("state"),
            "generation": data.get("generation"),
            "duration_seconds": data.get("duration_seconds"),
            "map_age_seconds": data.get("map_age_seconds"),
            "capture_bounds": data.get("capture_bounds"),
            "scene_summary": data.get("scene_summary"),
            "normalized_regions": data.get("normalized_regions") or [],
            "raw_response": data.get("raw_response") or {},
            "error": data.get("error") or "",
        }
        try:
            rendered = json.dumps(
                details,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        except Exception:
            rendered = json.dumps(
                {"error": "Diagnostics could not be serialized."},
                indent=2,
            )
        return rendered[:120000]

    def _set_spatial_diagnostics_status(
        self,
        message: str,
        *,
        error: bool = False,
    ) -> None:
        self._native_spatial_status = str(message or "")
        self._native_spatial_error = bool(error)
        self._set_status(self._native_spatial_status)

    def _log_spatial_diagnostics(self, message: str) -> None:
        print(f"[Companion Orb grounding diagnostic] {message}", flush=True)

    @QtCore.Slot()
    def _start_companion_orb_spatial_diagnostics(self) -> None:
        timer_thread_match = (
            QtCore.QThread.currentThread() == self._spatial_diagnostics_poll_timer.thread()
        )
        self._log_spatial_diagnostics(
            f"requested timer_thread_match={timer_thread_match}"
        )
        if not timer_thread_match:
            self._native_spatial_status = (
                "Capturing the desktop and testing structured visual grounding..."
            )
            self._native_spatial_error = False
            self._spatial_diagnostics_requested.emit()
            return
        orb = self._companion_orb_service()
        request_scan = getattr(orb, "request_spatial_scan", None)
        if not callable(request_scan):
            self._finish_companion_orb_spatial_diagnostics(
                {
                    "state": "error",
                    "error": "Companion Orb vision is unavailable.",
                }
            )
            return
        self._spatial_diagnostics_started_epoch = time.time()
        timeout = self._normalize_setting(
            "companion_orb_vision_timeout_seconds",
            self._runtime_config().get(
                "companion_orb_vision_timeout_seconds", 15.0
            ),
        )
        self._spatial_diagnostics_deadline = time.monotonic() + max(
            8.0,
            float(timeout) + 8.0,
        )
        try:
            result = dict(request_scan("diagnostic", force=True) or {})
        except Exception as exc:
            self._finish_companion_orb_spatial_diagnostics(
                {"state": "error", "error": str(exc)}
            )
            return
        self._spatial_diagnostics_expected_generation = int(
            result.get("generation") or 0
        )
        if not bool(result.get("queued") or result.get("coalesced")):
            self._log_spatial_diagnostics("scan request rejected")
            self._finish_companion_orb_spatial_diagnostics(
                {
                    "state": "error",
                    "error": str(
                        result.get("reason")
                        or "Visual grounding was not queued."
                    ),
                }
            )
            return
        self._set_spatial_diagnostics_status(
            "Capturing the desktop and testing structured visual grounding..."
        )
        self._spatial_diagnostics_poll_timer.start()
        self._log_spatial_diagnostics(
            "scan request queued "
            f"generation={self._spatial_diagnostics_expected_generation} "
            f"timer_active={self._spatial_diagnostics_poll_timer.isActive()}"
        )

    def _poll_companion_orb_spatial_diagnostics(self) -> None:
        orb = self._companion_orb_service()
        getter = getattr(orb, "spatial_diagnostics_snapshot", None)
        try:
            payload = dict(getter() or {}) if callable(getter) else {}
        except Exception as exc:
            payload = {"state": "error", "error": str(exc)}
        state = str(payload.get("state") or "").strip().lower()
        try:
            generation = int(payload.get("generation") or 0)
            completed_at = float(payload.get("completed_at") or 0.0)
        except (TypeError, ValueError, OverflowError):
            generation = 0
            completed_at = 0.0
        expected = int(self._spatial_diagnostics_expected_generation or 0)
        if (
            state in {"ready", "reused", "error"}
            and completed_at >= self._spatial_diagnostics_started_epoch
            and (not expected or generation >= expected)
        ):
            self._finish_companion_orb_spatial_diagnostics(payload)
            return
        if time.monotonic() >= self._spatial_diagnostics_deadline:
            payload["state"] = "error"
            payload["error"] = "Visual grounding diagnostics timed out."
            self._log_spatial_diagnostics(
                f"poll timeout generation={expected} last_scan_state={state or 'unknown'}"
            )
            self._finish_companion_orb_spatial_diagnostics(payload)

    def _finish_companion_orb_spatial_diagnostics(
        self,
        payload: Mapping[str, object],
    ) -> None:
        self._spatial_diagnostics_poll_timer.stop()
        result = dict(payload or {}) if isinstance(payload, Mapping) else {}
        self._log_spatial_diagnostics(
            "finished "
            f"generation={result.get('generation') or self._spatial_diagnostics_expected_generation} "
            f"state={str(result.get('state') or 'unknown').strip().lower()}"
        )
        if str(result.get("state") or "").strip().lower() == "error":
            error = self._spatial_diagnostics_error(result.get("error"))
            result["error"] = error
            self._set_spatial_diagnostics_status(error, error=True)
        else:
            region_count = len(list(result.get("normalized_regions") or []))
            duration = float(result.get("duration_seconds") or 0.0)
            self._set_spatial_diagnostics_status(
                f"Grounding complete: {region_count} regions in {duration:.2f} s."
            )
        self._show_companion_orb_spatial_diagnostics(result)

    def _show_companion_orb_spatial_diagnostics(
        self,
        payload: Mapping[str, object],
    ) -> None:
        self._native_spatial_diagnostics = (
            dict(payload or {}) if isinstance(payload, Mapping) else {}
        )

    def _normalize_spatial_setting(self, key, value):
        spatial_bool_keys = {
            "companion_orb_spatial_change_detection_enabled",
            "companion_orb_spatial_include_images",
            "companion_orb_spatial_include_text",
            "companion_orb_spatial_include_controls",
            "companion_orb_spatial_include_windows",
            "companion_orb_spatial_include_media",
            "companion_orb_spatial_include_other_objects",
            "companion_orb_spatial_explicit_commands_enabled",
            "companion_orb_spatial_conversational_focus_enabled",
            "companion_orb_spatial_follow_target_enabled",
            "companion_orb_spatial_stay_during_speech",
            "companion_orb_eye_tracking_bounding_boxes_enabled",
            "companion_orb_eye_tracking_bounding_box_labels_enabled",
            "companion_orb_eye_tracking_bounding_box_freeze_selected",
            "companion_orb_eye_tracking_bounding_box_show_images",
            "companion_orb_eye_tracking_bounding_box_show_text",
            "companion_orb_eye_tracking_bounding_box_show_controls",
            "companion_orb_eye_tracking_bounding_box_show_windows",
            "companion_orb_eye_tracking_bounding_box_show_media",
            "companion_orb_eye_tracking_bounding_box_show_other",
            "companion_orb_spatial_diagnostics_keep_last_capture",
        }
        if key in spatial_bool_keys:
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized in {"0", "false", "no", "off"}:
                    return False
                if normalized in {"1", "true", "yes", "on"}:
                    return True
            return bool(value)
        if key == "companion_orb_spatial_scan_mode":
            normalized = str(value or "").strip().lower()
            allowed = {item[1] for item in SPATIAL_SCAN_MODES}
            return normalized if normalized in allowed else "smart_cached"
        if key == "companion_orb_spatial_capture_scope":
            normalized = str(value or "").strip().lower()
            allowed = {item[1] for item in SPATIAL_CAPTURE_SCOPES}
            return normalized if normalized in allowed else "active_monitor"
        if key == "companion_orb_spatial_return_behavior":
            normalized = str(value or "").strip().lower()
            allowed = {item[1] for item in SPATIAL_RETURN_BEHAVIORS}
            return normalized if normalized in allowed else "after_speech"
        integer_ranges = {
            "companion_orb_spatial_max_regions": (1, 96),
            "companion_orb_spatial_hover_offset_px": (0, 300),
            "companion_orb_eye_tracking_region_select_dwell_ms": (200, 3000),
            "companion_orb_eye_tracking_bounding_box_max_visible": (1, 96),
        }
        if key in integer_ranges:
            minimum, maximum = integer_ranges[key]
            try:
                number = int(value)
            except (TypeError, ValueError, OverflowError):
                number = int(COMPANION_ORB_VISION_DEFAULTS[key])
            return max(minimum, min(maximum, number))
        float_ranges = {
            "companion_orb_spatial_scan_interval_seconds": (2.0, 300.0),
            "companion_orb_spatial_map_max_age_seconds": (2.0, 600.0),
            "companion_orb_spatial_change_threshold": (0.0, 1.0),
            "companion_orb_spatial_conversational_min_confidence": (0.0, 1.0),
            "companion_orb_spatial_movement_cooldown_seconds": (0.0, 120.0),
            "companion_orb_eye_tracking_bounding_box_opacity": (0.1, 1.0),
            "companion_orb_eye_tracking_bounding_box_width": (1.0, 8.0),
            "companion_orb_eye_tracking_bounding_box_min_confidence": (0.0, 1.0),
        }
        if key in float_ranges:
            minimum, maximum = float_ranges[key]
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                number = float(COMPANION_ORB_VISION_DEFAULTS[key])
            return max(minimum, min(maximum, number))
        if key in {
            "companion_orb_eye_tracking_bounding_box_normal_color",
            "companion_orb_eye_tracking_bounding_box_hover_color",
            "companion_orb_eye_tracking_bounding_box_selected_color",
        }:
            return self._normalized_hex_color(
                value,
                str(COMPANION_ORB_VISION_DEFAULTS[key]),
            )
        return value

    def _on_setting_changed(self, key, value):
        key = str(key or "").strip()
        if key == "companion_orb_color_palette":
            self._apply_companion_orb_palette(value)
            return
        if key == "companion_orb_vision_base_url":
            location = normalize_runtime_location(
                self._runtime_config().get(
                    "companion_orb_vision_runtime_location",
                    "primary",
                )
            )
            try:
                value = normalize_lmstudio_base_url(
                    value,
                    required=location != "primary",
                )
            except ValueError as exc:
                self._set_companion_orb_vision_probe_status(
                    str(exc),
                    error=True,
                )
                raise
        if key in ORB_COLOR_SETTING_KEYS and not bool(
            self._runtime_config().get(
                "companion_orb_custom_colors_enabled", False
            )
        ):
            self._update_runtime_config(
                "companion_orb_custom_colors_enabled", True
            )
        super()._on_setting_changed(key, value)
        if key == "companion_orb_custom_colors_enabled" and not bool(value):
            self._update_runtime_config(
                "companion_orb_color_palette",
                orb_palettes.CUSTOM_PALETTE_ID,
            )
            self._apply_runtime_config()
            self._save_session()
        if key == "companion_orb_sensory_target_enabled":
            self._set_companion_orb_source_included(bool(value))
        elif key == "companion_orb_full_screen_context_enabled" and bool(value):
            if not bool(
                self._runtime_config().get(
                    "companion_orb_sensory_target_enabled", False
                )
            ):
                self._update_runtime_config(
                    "companion_orb_sensory_target_enabled", True
                )
            self._set_companion_orb_source_included(True)
        elif key == "companion_orb_supervisor_enabled":
            self._publish_companion_orb_supervisor()
        elif key in {
            "sensory_pingpong_enabled",
            "sensory_allow_hidden_proactive_speech",
        }:
            self._notify_host_settings_changed()
        if key in {
            "companion_orb_sensory_target_enabled",
            "companion_orb_full_screen_context_enabled",
            "companion_orb_supervisor_enabled",
            "sensory_pingpong_enabled",
            "sensory_allow_hidden_proactive_speech",
        }:
            self._save_session()

    def _apply_companion_orb_palette(self, value):
        palette_id = orb_palettes.normalize_palette_id(value)
        self._update_runtime_config(
            "companion_orb_color_palette", palette_id
        )
        if palette_id != orb_palettes.CUSTOM_PALETTE_ID:
            palette = orb_palettes.palette_for_id(palette_id)
            self._update_runtime_config(
                "companion_orb_custom_colors_enabled", True
            )
            for color_key, color_value in palette.as_color_settings().items():
                self._update_runtime_config(color_key, color_value)
        self._apply_runtime_config()
        self._save_session()















    def _companion_orb_service(self):
        direct_service = getattr(self, "_companion_orb_direct_service", None)
        if direct_service is not None:
            return direct_service
        return None

    def set_companion_orb_service(self, service) -> None:
        self._companion_orb_direct_service = service
        self._push_companion_orb_runtime_settings()


    @staticmethod
    def _vision_pipeline_details_json(snapshot: Mapping[str, object]) -> str:
        pipeline = dict(snapshot.get("pipeline") or {})
        safe_pipeline = {
            key: pipeline.get(key)
            for key in (
                "stage",
                "status",
                "scope",
                "route",
                "cache",
                "revision",
                "updated_at",
            )
            if key in pipeline
        }
        events: list[dict[str, object]] = []
        for item in tuple(snapshot.get("events") or ())[-10:]:
            if not isinstance(item, Mapping):
                continue
            events.append(
                {
                    key: item.get(key)
                    for key in (
                        "at",
                        "kind",
                        "state",
                        "route",
                        "model_id",
                        "endpoint",
                        "reason",
                        "cache",
                    )
                    if key in item
                }
            )
        safe = {
            "pipeline": safe_pipeline,
            "model_id": str(snapshot.get("model_id") or ""),
            "endpoint": str(snapshot.get("endpoint") or ""),
            "active_requests": int(snapshot.get("active_requests") or 0),
            "cache_entries": int(snapshot.get("cache_entries") or 0),
            "events": events,
        }
        return json.dumps(safe, indent=2, ensure_ascii=False)




    def _invoke_eye_tracking_calibration(self, method_name: str):
        orb = self._companion_orb_service()
        callback = getattr(orb, str(method_name or ""), None)
        result = None
        if callable(callback):
            try:
                result = callback()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
        if not isinstance(result, dict):
            result = {
                "ok": False,
                "error": (
                    "The Companion Orb eye-tracking service is unavailable."
                ),
            }
        if not bool(result.get("ok")):
            self._set_status(
                str(
                    result.get("error")
                    or "Gaze calibration could not be changed."
                )
            )
        return result

    def _start_eye_tracking_calibration(self):
        return self._invoke_eye_tracking_calibration(
            "start_eye_tracking_calibration"
        )

    def _cancel_eye_tracking_calibration(self):
        return self._invoke_eye_tracking_calibration(
            "cancel_eye_tracking_calibration"
        )

    def _reset_eye_tracking_calibration(self):
        result = self._invoke_eye_tracking_calibration(
            "reset_eye_tracking_calibration"
        )
        if bool(result.get("ok")):
            self._update_runtime_config("companion_orb_eye_tracking_calibration", {})
            self._save_session()
        return result



    def _apply_stable_eye_tracking_movement_preset(self) -> None:
        preset = _stable_eye_tracking_movement_preset(
            self._runtime_config().get("companion_orb_size", 92)
        )
        for key, value in preset.items():
            self._update_runtime_config(
                key,
                self._normalize_setting(key, value),
            )
        self._apply_runtime_config()
        self.refresh_from_runtime()
        self._save_session()
        self._set_status(
            "Stable Gaze preset applied. Idle, aware, mouse-avoidance, "
            "and playful-nudge movement are off."
        )

















    def _normalized_hex_color(self, value, default="#38bdf8"):
        fallback = str(default or "#38bdf8")
        text = str(value or fallback).strip()
        if not text.startswith("#"):
            text = "#" + text
        text = text[:7]
        if len(text) != 7:
            return fallback
        try:
            int(text[1:], 16)
        except ValueError:
            return fallback
        return text.lower()

    def _color_swatch_style(self, color):
        return (
            "QLabel {"
            f"  background: {self._normalized_hex_color(color)};"
            "  border: 1px solid #56718f;"
            "  border-radius: 5px;"
            "  min-width: 22px;"
            "  max-width: 22px;"
            "  min-height: 22px;"
            "  max-height: 22px;"
            "}"
        )



    def refresh_from_runtime(self):
        super().refresh_from_runtime()
        self._register_companion_orb_supervisor_contributor()

    def _service_snapshot(self, method_name: str) -> dict[str, object]:
        service = self._companion_orb_service()
        callback = getattr(service, method_name, None)
        if not callable(callback):
            return {}
        try:
            value = callback()
        except Exception as exc:
            return {"error": str(exc)}
        return dict(value or {}) if isinstance(value, Mapping) else {}

    def native_snapshot(self):
        config = self._runtime_config()
        vision_runtime = self._service_snapshot("vision_runtime_snapshot")
        if vision_runtime:
            self._last_vision_runtime_snapshot = dict(vision_runtime)
        else:
            vision_runtime = dict(self._last_vision_runtime_snapshot)
        eye_tracking_status = self._service_snapshot("eye_tracking_status")
        catalog = self._companion_orb_preset_store.catalog()
        payload = {
            "settings": {
                key: config.get(key, DEFAULT_SETTINGS.get(key))
                for key in self.SESSION_KEYS
            },
            "status": str(
                self._native_status
                or "Companion Orb addon controls are ready."
            ),
            "vision_runtime": vision_runtime,
            "eye_tracking": eye_tracking_status,
            "vision_probe": {
                "status": self._native_vision_probe_status,
                "error": self._native_vision_probe_error,
            },
            "spatial_diagnostics": {
                "status": self._native_spatial_status,
                "error": self._native_spatial_error,
                "payload": dict(self._native_spatial_diagnostics),
            },
            "presets": [
                {
                    "preset_id": record.preset_id,
                    "name": record.name,
                    "comment": record.comment,
                    "saved_at": record.saved_at,
                }
                for record in catalog.records
            ],
            "preset_errors": list(catalog.errors),
        }
        payload["controls"] = build_native_control_state(self)
        return payload

    def native_update_control(self, control_id, value):
        apply_native_control_update(self, control_id, value)
        return self.native_snapshot()

    def native_control_action(self, control_id, payload=None):
        return dispatch_native_control_action(self, control_id, payload)

    def native_update_setting(self, key, value):
        setting_key = str(key or "").strip()
        if setting_key not in self.SESSION_KEYS:
            raise KeyError(
                f"Unknown Companion Orb setting: {setting_key}"
            )
        normalized = self._normalize_setting(setting_key, value)
        self._on_setting_changed(setting_key, normalized)
        return self.native_snapshot()

    def native_action(self, action, payload=None):
        action_name = str(action or "").strip().lower()
        request = dict(payload or {})
        if action_name in {
            "preview_fullscreen",
            "open_floating",
            "reset_floating_position",
        }:
            return super().native_action(action_name)
        if action_name == "show_orb":
            self._show_companion_orb()
        elif action_name == "start_eye_calibration":
            return self._start_eye_tracking_calibration()
        elif action_name == "cancel_eye_calibration":
            return self._cancel_eye_tracking_calibration()
        elif action_name == "reset_eye_calibration":
            return self._reset_eye_tracking_calibration()
        elif action_name == "stable_gaze_preset":
            self._apply_stable_eye_tracking_movement_preset()
        elif action_name == "test_vision":
            self._start_companion_orb_vision_probe()
        elif action_name == "test_spatial_grounding":
            self._start_companion_orb_spatial_diagnostics()
        elif action_name == "load_preset":
            record = self._companion_orb_preset_store.load(
                str(request.get("preset_id") or "")
            )
            self._apply_companion_orb_preset_record(record)
        elif action_name in {"save_preset", "save_preset_as"}:
            self._companion_orb_preset_store.save(
                str(request.get("name") or "").strip(),
                str(request.get("comment") or ""),
                self._companion_orb_preset_settings_snapshot(),
                overwrite=bool(
                    request.get(
                        "overwrite",
                        action_name == "save_preset",
                    )
                ),
            )
        elif action_name == "delete_preset":
            self._companion_orb_preset_store.delete(
                str(request.get("preset_id") or "")
            )
        else:
            raise KeyError(
                f"Unknown Companion Orb action: {action_name}"
            )
        return self.native_snapshot()

    def perform_tutorial_try_action(self, action):
        request = dict(action or {})
        action_type = str(request.get("type") or "").strip().lower()
        target = str(request.get("target") or "").strip()
        click_actions = {
            "companion_orb_vision_test_connection_button": (
                self._start_companion_orb_vision_probe
            ),
            "companion_orb_spatial_test_grounding_button": (
                self._start_companion_orb_spatial_diagnostics
            ),
        }
        setting_targets = {
            "companion_orb_eye_tracking_bounding_boxes_enabled_checkbox": (
                "companion_orb_eye_tracking_bounding_boxes_enabled"
            ),
        }
        if action_type == "click" and target in click_actions:
            click_actions[target]()
            return {"accepted": True, "target": target}
        if action_type == "temporary_checkbox" and target in setting_targets:
            key = setting_targets[target]
            previous = bool(self._runtime_config().get(key, False))
            next_value = bool(request.get("value", True))
            self._on_setting_changed(key, next_value)
            return {
                "accepted": True,
                "target": target,
                "restore": {"key": key, "value": previous},
            }
        return {
            "accepted": False,
            "target": target,
            "error": (
                "This tutorial exercise is not available in the native "
                "interface."
            ),
        }

    def restore_tutorial_settings(self, settings):
        restored = []
        allowed = {
            "companion_orb_eye_tracking_bounding_boxes_enabled"
        }
        for key, value in dict(settings or {}).items():
            normalized_key = str(key or "").strip()
            if normalized_key not in allowed:
                continue
            self._on_setting_changed(normalized_key, bool(value))
            restored.append(normalized_key)
        return {"accepted": True, "restored": restored}


    def import_session_state(self, session):
        result = super().import_session_state(session)
        self._register_companion_orb_supervisor_contributor()
        return result

    def shutdown(self):
        self._spatial_diagnostics_poll_timer.stop()
        self._unregister_companion_orb_supervisor_contributor()
        self._companion_orb_supervisor_expanded_behavior_ids.clear()
        return super().shutdown()
