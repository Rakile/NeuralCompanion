"""Shared shell/runtime UI spec tables.

These constants are intentionally data-only. Keeping them outside qt_app.py makes
the binders easier to split without changing runtime behavior.
"""

from collections import OrderedDict


UI_SHELL_DEFAULT_LOCAL_VAM_ROOT = ""
UI_SHELL_BODY_EMOTIONS = ("Neutral", "Happy", "Sad", "Angry", "Shy", "Surprised")

WORKSPACE_VIEW_MIN_WIDTH = 890
WORKSPACE_VIEW_MIN_HEIGHT = 780
WORKSPACE_VIEW_MAX_HEIGHT = 1360
WORKSPACE_WINDOW_MAX_HEIGHT = 1600
WORKSPACE_DOCKED_VIEW_MIN_WIDTH = 360
WORKSPACE_DOCKED_AUX_MIN_HEIGHT = 420
WORKSPACE_INNER_MIN_WIDTH = 840
WORKSPACE_INNER_MIN_HEIGHT = 700
WORKSPACE_PREVIEW_FRAME_MIN_HEIGHT = 560

UI_SHELL_DEFAULT_CHUNKING_VALUES = {
    "chunk_target_chars": 100,
    "chunk_max_chars": 200,
    "musetalk_chunk_target_chars": 110,
    "musetalk_chunk_max_chars": 220,
    "musetalk_quickstart_1_target_chars": 170,
    "musetalk_quickstart_1_max_chars": 320,
    "musetalk_quickstart_2_target_chars": 130,
    "musetalk_quickstart_2_max_chars": 240,
    "stream_chunk_target_chars": 85,
    "stream_chunk_max_chars": 170,
    "stream_first_chunk_min_chars": 28,
    "stream_force_flush_seconds": 0.9,
    "stream_force_flush_later_seconds": 1.4,
}

UI_SHELL_MUSE_VRAM_MODE_LABELS = OrderedDict([
    ("quality", "Quality"),
    ("balanced", "Balanced"),
    ("low", "Low VRAM"),
    ("very_low", "Very Low VRAM"),
])

UI_SHELL_CHUNKING_SPECS = OrderedDict([
    ("chunk_target_chars", {
        "widget": "chunk_target_chars_slider",
        "label": "chunk_target_chars_label",
        "title": "Target Chars",
        "minimum": 40,
        "maximum": 220,
        "default": 100,
    }),
    ("chunk_max_chars", {
        "widget": "chunk_max_chars_slider",
        "label": "chunk_max_chars_label",
        "title": "Max Chars",
        "minimum": 60,
        "maximum": 320,
        "default": 200,
    }),
    ("musetalk_chunk_target_chars", {
        "widget": "musetalk_chunk_target_chars_slider",
        "label": "musetalk_chunk_target_chars_label",
        "title": "Target Chars",
        "minimum": 60,
        "maximum": 220,
        "default": 110,
    }),
    ("musetalk_chunk_max_chars", {
        "widget": "musetalk_chunk_max_chars_slider",
        "label": "musetalk_chunk_max_chars_label",
        "title": "Max Chars",
        "minimum": 80,
        "maximum": 320,
        "default": 220,
    }),
    ("musetalk_quickstart_1_target_chars", {
        "widget": "musetalk_quickstart_1_target_chars_slider",
        "label": "musetalk_quickstart_1_target_chars_label",
        "title": "Quickstart 1 Target",
        "minimum": 60,
        "maximum": 260,
        "default": 170,
    }),
    ("musetalk_quickstart_1_max_chars", {
        "widget": "musetalk_quickstart_1_max_chars_slider",
        "label": "musetalk_quickstart_1_max_chars_label",
        "title": "Quickstart 1 Max",
        "minimum": 80,
        "maximum": 360,
        "default": 320,
    }),
    ("musetalk_quickstart_2_target_chars", {
        "widget": "musetalk_quickstart_2_target_chars_slider",
        "label": "musetalk_quickstart_2_target_chars_label",
        "title": "Quickstart 2 Target",
        "minimum": 60,
        "maximum": 240,
        "default": 130,
    }),
    ("musetalk_quickstart_2_max_chars", {
        "widget": "musetalk_quickstart_2_max_chars_slider",
        "label": "musetalk_quickstart_2_max_chars_label",
        "title": "Quickstart 2 Max",
        "minimum": 80,
        "maximum": 320,
        "default": 240,
    }),
    ("stream_chunk_target_chars", {
        "widget": "stream_chunk_target_chars_slider",
        "label": "stream_chunk_target_chars_label",
        "title": "Target Chars",
        "minimum": 40,
        "maximum": 220,
        "default": 85,
    }),
    ("stream_chunk_max_chars", {
        "widget": "stream_chunk_max_chars_slider",
        "label": "stream_chunk_max_chars_label",
        "title": "Max Chars",
        "minimum": 60,
        "maximum": 320,
        "default": 170,
    }),
    ("stream_first_chunk_min_chars", {
        "widget": "stream_first_chunk_min_chars_slider",
        "label": "stream_first_chunk_min_chars_label",
        "title": "First Chunk Min",
        "minimum": 10,
        "maximum": 80,
        "default": 28,
    }),
    ("stream_force_flush_seconds", {
        "widget": "stream_force_flush_seconds_slider",
        "label": "stream_force_flush_seconds_label",
        "title": "First Flush (s)",
        "minimum": 0.2,
        "maximum": 2.5,
        "default": 0.9,
        "is_int": False,
        "scale": 100,
    }),
    ("stream_force_flush_later_seconds", {
        "widget": "stream_force_flush_later_seconds_slider",
        "label": "stream_force_flush_later_seconds_label",
        "title": "Later Flush (s)",
        "minimum": 0.3,
        "maximum": 4.0,
        "default": 1.4,
        "is_int": False,
        "scale": 100,
    }),
])

UI_SHELL_BODY_POSE_SPECS = OrderedDict([
    ("idle_fwd_left", {
        "widget": "idle_fwd_left_slider",
        "label": "idle_fwd_left_label",
        "title": "L Depth",
        "minimum": -200.0,
        "maximum": 200.0,
        "default": 0.0,
        "scale": 1,
    }),
    ("idle_fwd_right", {
        "widget": "idle_fwd_right_slider",
        "label": "idle_fwd_right_label",
        "title": "R Depth",
        "minimum": -100.0,
        "maximum": 100.0,
        "default": 0.0,
        "scale": 1,
    }),
    ("idle_arm_down", {
        "widget": "idle_arm_down_slider",
        "label": "idle_arm_down_label",
        "title": "Shoulder Down",
        "minimum": -100.0,
        "maximum": 100.0,
        "default": 0.0,
        "scale": 1,
    }),
    ("idle_shoulder_back", {
        "widget": "idle_shoulder_back_slider",
        "label": "idle_shoulder_back_label",
        "title": "Shoulder Back",
        "minimum": -100.0,
        "maximum": 100.0,
        "default": 0.0,
        "scale": 1,
    }),
    ("idle_elbow_bend", {
        "widget": "idle_elbow_bend_slider",
        "label": "idle_elbow_bend_label",
        "title": "Elbow Bend",
        "minimum": -250.0,
        "maximum": 250.0,
        "default": 0.0,
        "scale": 1,
    }),
    ("idle_arm_twist", {
        "widget": "idle_arm_twist_slider",
        "label": "idle_arm_twist_label",
        "title": "Arm Twist",
        "minimum": -100.0,
        "maximum": 100.0,
        "default": 0.0,
        "scale": 1,
    }),
    ("spine_sway_mult", {
        "widget": "spine_sway_mult_slider",
        "label": "spine_sway_mult_label",
        "title": "Spine Sway",
        "minimum": 0.0,
        "maximum": 3.0,
        "default": 0.0,
        "scale": 100,
    }),
    ("spine_twist_mult", {
        "widget": "spine_twist_mult_slider",
        "label": "spine_twist_mult_label",
        "title": "Spine Twist",
        "minimum": 0.0,
        "maximum": 3.0,
        "default": 0.0,
        "scale": 100,
    }),
    ("neck_stabilize", {
        "widget": "neck_stabilize_slider",
        "label": "neck_stabilize_label",
        "title": "Head Stabilize",
        "minimum": 0.0,
        "maximum": 3.0,
        "default": 0.0,
        "scale": 100,
    }),
    ("eye_activity", {
        "widget": "eye_activity_slider",
        "label": "eye_activity_label",
        "title": "Eye Activity",
        "minimum": 0.0,
        "maximum": 3.0,
        "default": 0.0,
        "scale": 100,
    }),
    ("breath_speed", {
        "widget": "breath_speed_slider",
        "label": "breath_speed_label",
        "title": "Breath Speed",
        "minimum": 0.1,
        "maximum": 4.0,
        "default": 0.0,
        "scale": 100,
    }),
    ("shoulder_lift", {
        "widget": "shoulder_lift_slider",
        "label": "shoulder_lift_label",
        "title": "Shoulder Lift",
        "minimum": 0.0,
        "maximum": 5.0,
        "default": 0.0,
        "scale": 100,
    }),
    ("idle_speed", {
        "widget": "idle_speed_slider",
        "label": "idle_speed_label",
        "title": "Body Sway Speed",
        "minimum": 0.2,
        "maximum": 3.0,
        "default": 0.0,
        "scale": 100,
    }),
    ("idle_intensity", {
        "widget": "idle_intensity_slider",
        "label": "idle_intensity_label",
        "title": "Body Sway Intensity",
        "minimum": 0.5,
        "maximum": 10.0,
        "default": 0.0,
        "scale": 100,
    }),
])

UI_SHELL_LIVE_ADDON_IDS = {
    "nc.audio_story_mode",
    "nc.chatterbox_tts",
    "nc.chat_provider_lmstudio",
    "nc.chat_provider_openai",
    "nc.chat_provider_xai",
    "nc.chat_session_player",
    "nc.claude_provider",
    "nc.clipboard_source",
    "nc.clipboard_supervisor",
    "nc.gemini_tts_preview",
    "nc.heart_rate_behavior",
    "nc.hotkeys",
    "nc.mock_heart_rate",
    "nc.musetalk_avatar",
    "nc.musetalk_preprocess",
    "nc.no_avatar",
    "nc.pockettts",
    "nc.screen_supervisor",
    "nc.vam_avatar",
    "nc.visual_reply",
    "nc.visual_story_settings",
    "nc.vseeface_avatar",
    "nc.webcam_supervisor",
}
