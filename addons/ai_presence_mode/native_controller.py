from __future__ import annotations

import re
from collections.abc import Mapping

from PySide6 import QtCore

from core import companion_orb_reply_styles


DISPLAY_MODES = [
    ("Off", "off"),
    ("Fullscreen", "fullscreen"),
    ("Floating Window", "floating"),
    ("Both", "both"),
]

VISUAL_STYLES = [
    ("Neural Network Pulse", "neural_network_pulse"),
    ("Living Voice Thread", "living_voice_thread"),
    ("Silk Drift", "silk_drift"),
]

RENDER_BACKENDS = [
    ("GPU Native (recommended)", "gpu_native"),
    ("Legacy Canvas (compatibility)", "legacy_canvas"),
]

VOICE_THREAD_MOTION_STYLES = [
    ("Organic drift", "organic_drift"),
    ("Breathing ribbon", "breathing_ribbon"),
    ("Tidal sweep", "tidal_sweep"),
    ("Resonant bloom", "resonant_bloom"),
]

VOICE_THREAD_AMBIENT_TARGETS = [
    ("Glow only", "glow_only"),
    ("Shape and glow", "shape_glow"),
    ("Full spectrum", "full_spectrum"),
]

VOICE_THREAD_PHYSICS_FEELS = [
    ("Natural cord", "natural"),
    ("Light silk", "silk"),
    ("Heavy cable", "cable"),
]

VOICE_THREAD_TUNING_KEYS = (
    "ai_presence_voice_thread_motion_style",
    "ai_presence_voice_thread_strand_multiplier",
    "ai_presence_voice_thread_audio_reactivity",
    "ai_presence_voice_thread_motion_scale",
    "ai_presence_voice_thread_idle_motion",
    "ai_presence_voice_thread_animation_speed",
    "ai_presence_voice_thread_response_smoothing",
    "ai_presence_voice_thread_spectrum_smoothing",
    "ai_presence_voice_thread_spectrum_scale",
    "ai_presence_voice_thread_peak_emphasis",
    "ai_presence_voice_thread_glow_radius",
    "ai_presence_voice_thread_reflection_enabled",
    "ai_presence_voice_thread_reflection_distance",
    "ai_presence_voice_thread_glow_intensity",
    "ai_presence_voice_thread_flux_strength",
    "ai_presence_voice_thread_fiber_spread",
    "ai_presence_voice_thread_ambient_fiber_spread_enabled",
    "ai_presence_voice_thread_bendiness",
    "ai_presence_voice_thread_organic_variation",
    "ai_presence_voice_thread_phrase_motion",
    "ai_presence_voice_thread_gesture_intensity",
    "ai_presence_voice_thread_motion_memory",
    "ai_presence_voice_thread_accent_sensitivity",
    "ai_presence_music_reactivity",
    "ai_presence_voice_thread_ambient_reaction_target",
    "ai_presence_voice_thread_ambient_smoothing",
    "ai_presence_voice_thread_ambient_noise_gate",
    "ai_presence_voice_thread_ambient_quiet_detail",
    "ai_presence_voice_thread_ambient_transient_punch",
    "ai_presence_voice_thread_ambient_attack_ms",
    "ai_presence_voice_thread_ambient_release_ms",
    "ai_presence_voice_thread_ambient_mix",
    "ai_presence_voice_thread_ambient_link_main_controls",
    "ai_presence_voice_thread_ambient_shape_strength",
    "ai_presence_voice_thread_ambient_travel_strength",
    "ai_presence_voice_thread_ambient_glow_strength",
    "ai_presence_voice_thread_ambient_fiber_strength",
    "ai_presence_voice_thread_ambient_color_strength",
    "ai_presence_voice_thread_audio_colors_enabled",
    "ai_presence_voice_thread_voice_colors_enabled",
    "ai_presence_voice_thread_desktop_colors_enabled",
    "ai_presence_voice_thread_color_vividness",
    "ai_presence_voice_thread_color_bass_influence",
    "ai_presence_voice_thread_color_mid_influence",
    "ai_presence_voice_thread_color_high_influence",
    "ai_presence_voice_thread_color_smoothing",
    "ai_presence_voice_thread_ambient_motion_ceiling",
    "ai_presence_voice_thread_ambient_bass_bend",
    "ai_presence_voice_thread_ambient_mid_ripple",
    "ai_presence_voice_thread_ambient_high_shimmer",
    "ai_presence_voice_thread_physics_feel",
    "ai_presence_voice_thread_physics_slack",
    "ai_presence_voice_thread_interaction_area",
    "ai_presence_voice_thread_gravity",
    "ai_presence_voice_thread_retension_time",
    "ai_presence_voice_thread_show_placement_guide",
    "ai_presence_voice_thread_size",
    "ai_presence_voice_thread_horizontal_span",
)

VOICE_THREAD_CUSTOM_CAPTURE_KEYS = (
    "ai_presence_voice_thread_variation",
    "ai_presence_voice_thread_palette",
    "ai_presence_voice_thread_primary_color",
    "ai_presence_voice_thread_accent_color",
    "ai_presence_voice_thread_highlight_color",
    *VOICE_THREAD_TUNING_KEYS,
)

VOICE_THREAD_BUILTIN_PRESETS = {
    "default": {
        "label": "Default",
        "settings": {
            "ai_presence_music_reactivity": 2.32,
            "ai_presence_voice_thread_accent_color": "#fa2d00",
            "ai_presence_voice_thread_accent_sensitivity": 1.66,
            "ai_presence_voice_thread_ambient_attack_ms": 17,
            "ai_presence_voice_thread_ambient_bass_bend": 0.8,
            "ai_presence_voice_thread_ambient_color_strength": 2,
            "ai_presence_voice_thread_ambient_fiber_spread_enabled": True,
            "ai_presence_voice_thread_ambient_fiber_strength": 1.02,
            "ai_presence_voice_thread_ambient_glow_strength": 2.2,
            "ai_presence_voice_thread_ambient_high_shimmer": 0.85,
            "ai_presence_voice_thread_ambient_link_main_controls": True,
            "ai_presence_voice_thread_ambient_mid_ripple": 1.03,
            "ai_presence_voice_thread_ambient_mix": 0.96,
            "ai_presence_voice_thread_ambient_motion_ceiling": 0.79,
            "ai_presence_voice_thread_ambient_noise_gate": 0.07,
            "ai_presence_voice_thread_ambient_quiet_detail": 1.1,
            "ai_presence_voice_thread_ambient_reaction_target": "full_spectrum",
            "ai_presence_voice_thread_ambient_release_ms": 127,
            "ai_presence_voice_thread_ambient_shape_strength": 2.6,
            "ai_presence_voice_thread_ambient_smoothing": 0.52,
            "ai_presence_voice_thread_ambient_transient_punch": 2.6,
            "ai_presence_voice_thread_ambient_travel_strength": 2.25,
            "ai_presence_voice_thread_animation_speed": 0.52,
            "ai_presence_voice_thread_audio_colors_enabled": True,
            "ai_presence_voice_thread_audio_reactivity": 1.79,
            "ai_presence_voice_thread_bendiness": 0.39,
            "ai_presence_voice_thread_color_bass_influence": 4,
            "ai_presence_voice_thread_color_high_influence": 2.34,
            "ai_presence_voice_thread_color_mid_influence": 4,
            "ai_presence_voice_thread_color_smoothing": 0.41,
            "ai_presence_voice_thread_color_vividness": 4,
            "ai_presence_voice_thread_desktop_colors_enabled": True,
            "ai_presence_voice_thread_fiber_spread": 1.27,
            "ai_presence_voice_thread_flux_strength": 1.42,
            "ai_presence_voice_thread_gesture_intensity": 1.55,
            "ai_presence_voice_thread_glow_intensity": 4,
            "ai_presence_voice_thread_glow_radius": 0.61,
            "ai_presence_voice_thread_gravity": 1.2,
            "ai_presence_voice_thread_highlight_color": "#0fff00",
            "ai_presence_voice_thread_horizontal_span": 1.33,
            "ai_presence_voice_thread_idle_motion": 1.27,
            "ai_presence_voice_thread_interaction_area": 1.6,
            "ai_presence_voice_thread_motion_memory": 0.5,
            "ai_presence_voice_thread_motion_scale": 0.74,
            "ai_presence_voice_thread_motion_style": "breathing_ribbon",
            "ai_presence_voice_thread_organic_variation": 2.65,
            "ai_presence_voice_thread_palette": "custom",
            "ai_presence_voice_thread_peak_emphasis": 0.82,
            "ai_presence_voice_thread_phrase_motion": 1.35,
            "ai_presence_voice_thread_physics_feel": "natural",
            "ai_presence_voice_thread_physics_slack": 1.45,
            "ai_presence_voice_thread_primary_color": "#0013ee",
            "ai_presence_voice_thread_reflection_distance": 0.81,
            "ai_presence_voice_thread_reflection_enabled": True,
            "ai_presence_voice_thread_response_smoothing": 0.73,
            "ai_presence_voice_thread_retension_time": 0.65,
            "ai_presence_voice_thread_show_placement_guide": False,
            "ai_presence_voice_thread_size": 1.85,
            "ai_presence_voice_thread_spectrum_scale": 0.99,
            "ai_presence_voice_thread_spectrum_smoothing": 0.32,
            "ai_presence_voice_thread_strand_multiplier": 1,
            "ai_presence_voice_thread_variation": "silk_ribbon",
            "ai_presence_voice_thread_voice_colors_enabled": True,
        },
    },
    "balanced": {
        "label": "Balanced",
        "settings": {
            "ai_presence_voice_thread_motion_style": "organic_drift",
            "ai_presence_voice_thread_audio_reactivity": 1.0,
            "ai_presence_voice_thread_motion_scale": 1.0,
            "ai_presence_voice_thread_idle_motion": 0.16,
            "ai_presence_voice_thread_animation_speed": 1.0,
            "ai_presence_voice_thread_response_smoothing": 0.58,
            "ai_presence_voice_thread_spectrum_smoothing": 0.45,
            "ai_presence_voice_thread_spectrum_scale": 1.0,
            "ai_presence_voice_thread_peak_emphasis": 0.60,
            "ai_presence_voice_thread_glow_radius": 1.0,
            "ai_presence_voice_thread_glow_intensity": 1.0,
            "ai_presence_voice_thread_flux_strength": 1.0,
            "ai_presence_voice_thread_fiber_spread": 1.0,
            "ai_presence_voice_thread_bendiness": 1.0,
            "ai_presence_voice_thread_organic_variation": 1.0,
            "ai_presence_voice_thread_phrase_motion": 1.0,
            "ai_presence_voice_thread_gesture_intensity": 1.0,
            "ai_presence_voice_thread_motion_memory": 0.65,
            "ai_presence_voice_thread_accent_sensitivity": 0.55,
            "ai_presence_music_reactivity": 2.80,
            "ai_presence_voice_thread_ambient_reaction_target": "shape_glow",
            "ai_presence_voice_thread_ambient_smoothing": 0.72,
            "ai_presence_voice_thread_ambient_noise_gate": 0.04,
            "ai_presence_voice_thread_ambient_quiet_detail": 1.40,
            "ai_presence_voice_thread_ambient_transient_punch": 1.60,
            "ai_presence_voice_thread_ambient_attack_ms": 35,
            "ai_presence_voice_thread_ambient_release_ms": 260,
            "ai_presence_voice_thread_ambient_mix": 1.45,
            "ai_presence_voice_thread_ambient_link_main_controls": True,
            "ai_presence_voice_thread_ambient_fiber_spread_enabled": True,
            "ai_presence_voice_thread_ambient_shape_strength": 1.80,
            "ai_presence_voice_thread_ambient_travel_strength": 1.35,
            "ai_presence_voice_thread_ambient_glow_strength": 1.65,
            "ai_presence_voice_thread_ambient_fiber_strength": 1.25,
            "ai_presence_voice_thread_ambient_color_strength": 1.50,
            "ai_presence_voice_thread_audio_colors_enabled": True,
            "ai_presence_voice_thread_voice_colors_enabled": True,
            "ai_presence_voice_thread_desktop_colors_enabled": True,
            "ai_presence_voice_thread_color_vividness": 1.0,
            "ai_presence_voice_thread_color_bass_influence": 1.0,
            "ai_presence_voice_thread_color_mid_influence": 1.0,
            "ai_presence_voice_thread_color_high_influence": 1.0,
            "ai_presence_voice_thread_color_smoothing": 0.65,
            "ai_presence_voice_thread_ambient_motion_ceiling": 2.20,
            "ai_presence_voice_thread_ambient_bass_bend": 0.55,
            "ai_presence_voice_thread_ambient_mid_ripple": 0.38,
            "ai_presence_voice_thread_ambient_high_shimmer": 0.42,
            "ai_presence_voice_thread_physics_slack": 1.0,
        },
    },
    "calm": {
        "label": "Calm",
        "settings": {
            "ai_presence_voice_thread_motion_style": "breathing_ribbon",
            "ai_presence_voice_thread_audio_reactivity": 0.78,
            "ai_presence_voice_thread_motion_scale": 0.62,
            "ai_presence_voice_thread_idle_motion": 0.20,
            "ai_presence_voice_thread_animation_speed": 0.72,
            "ai_presence_voice_thread_response_smoothing": 0.78,
            "ai_presence_voice_thread_spectrum_smoothing": 0.68,
            "ai_presence_voice_thread_spectrum_scale": 0.82,
            "ai_presence_voice_thread_peak_emphasis": 0.38,
            "ai_presence_voice_thread_glow_radius": 0.90,
            "ai_presence_voice_thread_glow_intensity": 0.82,
            "ai_presence_voice_thread_flux_strength": 0.52,
            "ai_presence_voice_thread_fiber_spread": 0.84,
            "ai_presence_voice_thread_bendiness": 0.72,
            "ai_presence_voice_thread_organic_variation": 0.65,
            "ai_presence_voice_thread_phrase_motion": 0.72,
            "ai_presence_voice_thread_gesture_intensity": 0.48,
            "ai_presence_voice_thread_motion_memory": 0.82,
            "ai_presence_voice_thread_accent_sensitivity": 0.42,
            "ai_presence_music_reactivity": 2.30,
            "ai_presence_voice_thread_ambient_reaction_target": "shape_glow",
            "ai_presence_voice_thread_ambient_smoothing": 0.82,
            "ai_presence_voice_thread_ambient_noise_gate": 0.05,
            "ai_presence_voice_thread_ambient_quiet_detail": 1.70,
            "ai_presence_voice_thread_ambient_transient_punch": 0.65,
            "ai_presence_voice_thread_ambient_attack_ms": 75,
            "ai_presence_voice_thread_ambient_release_ms": 520,
            "ai_presence_voice_thread_ambient_mix": 1.10,
            "ai_presence_voice_thread_ambient_link_main_controls": True,
            "ai_presence_voice_thread_ambient_fiber_spread_enabled": True,
            "ai_presence_voice_thread_ambient_shape_strength": 1.20,
            "ai_presence_voice_thread_ambient_travel_strength": 0.65,
            "ai_presence_voice_thread_ambient_glow_strength": 1.40,
            "ai_presence_voice_thread_ambient_fiber_strength": 1.00,
            "ai_presence_voice_thread_ambient_color_strength": 1.20,
            "ai_presence_voice_thread_audio_colors_enabled": True,
            "ai_presence_voice_thread_voice_colors_enabled": True,
            "ai_presence_voice_thread_desktop_colors_enabled": True,
            "ai_presence_voice_thread_color_vividness": 0.82,
            "ai_presence_voice_thread_color_bass_influence": 1.15,
            "ai_presence_voice_thread_color_mid_influence": 0.72,
            "ai_presence_voice_thread_color_high_influence": 0.55,
            "ai_presence_voice_thread_color_smoothing": 1.20,
            "ai_presence_voice_thread_ambient_motion_ceiling": 1.60,
            "ai_presence_voice_thread_ambient_bass_bend": 0.35,
            "ai_presence_voice_thread_ambient_mid_ripple": 0.22,
            "ai_presence_voice_thread_ambient_high_shimmer": 0.28,
            "ai_presence_voice_thread_physics_slack": 0.72,
        },
    },
    "expressive": {
        "label": "Expressive",
        "settings": {
            "ai_presence_voice_thread_motion_style": "resonant_bloom",
            "ai_presence_voice_thread_audio_reactivity": 1.32,
            "ai_presence_voice_thread_motion_scale": 1.28,
            "ai_presence_voice_thread_idle_motion": 0.14,
            "ai_presence_voice_thread_animation_speed": 1.12,
            "ai_presence_voice_thread_response_smoothing": 0.38,
            "ai_presence_voice_thread_spectrum_smoothing": 0.32,
            "ai_presence_voice_thread_spectrum_scale": 1.28,
            "ai_presence_voice_thread_peak_emphasis": 0.82,
            "ai_presence_voice_thread_glow_radius": 1.28,
            "ai_presence_voice_thread_glow_intensity": 1.25,
            "ai_presence_voice_thread_flux_strength": 1.42,
            "ai_presence_voice_thread_fiber_spread": 1.20,
            "ai_presence_voice_thread_bendiness": 1.55,
            "ai_presence_voice_thread_organic_variation": 1.40,
            "ai_presence_voice_thread_phrase_motion": 1.35,
            "ai_presence_voice_thread_gesture_intensity": 1.55,
            "ai_presence_voice_thread_motion_memory": 0.50,
            "ai_presence_voice_thread_accent_sensitivity": 0.72,
            "ai_presence_music_reactivity": 3.25,
            "ai_presence_voice_thread_ambient_reaction_target": "full_spectrum",
            "ai_presence_voice_thread_ambient_smoothing": 0.52,
            "ai_presence_voice_thread_ambient_noise_gate": 0.03,
            "ai_presence_voice_thread_ambient_quiet_detail": 1.10,
            "ai_presence_voice_thread_ambient_transient_punch": 2.60,
            "ai_presence_voice_thread_ambient_attack_ms": 15,
            "ai_presence_voice_thread_ambient_release_ms": 150,
            "ai_presence_voice_thread_ambient_mix": 1.85,
            "ai_presence_voice_thread_ambient_link_main_controls": True,
            "ai_presence_voice_thread_ambient_fiber_spread_enabled": True,
            "ai_presence_voice_thread_ambient_shape_strength": 2.60,
            "ai_presence_voice_thread_ambient_travel_strength": 2.25,
            "ai_presence_voice_thread_ambient_glow_strength": 2.20,
            "ai_presence_voice_thread_ambient_fiber_strength": 1.65,
            "ai_presence_voice_thread_ambient_color_strength": 2.00,
            "ai_presence_voice_thread_audio_colors_enabled": True,
            "ai_presence_voice_thread_voice_colors_enabled": True,
            "ai_presence_voice_thread_desktop_colors_enabled": True,
            "ai_presence_voice_thread_color_vividness": 1.45,
            "ai_presence_voice_thread_color_bass_influence": 1.15,
            "ai_presence_voice_thread_color_mid_influence": 1.45,
            "ai_presence_voice_thread_color_high_influence": 1.70,
            "ai_presence_voice_thread_color_smoothing": 0.55,
            "ai_presence_voice_thread_ambient_motion_ceiling": 2.85,
            "ai_presence_voice_thread_ambient_bass_bend": 0.80,
            "ai_presence_voice_thread_ambient_mid_ripple": 0.70,
            "ai_presence_voice_thread_ambient_high_shimmer": 0.85,
            "ai_presence_voice_thread_physics_slack": 1.45,
        },
    },
    "cinematic": {
        "label": "Cinematic",
        "settings": {
            "ai_presence_voice_thread_motion_style": "tidal_sweep",
            "ai_presence_voice_thread_audio_reactivity": 1.12,
            "ai_presence_voice_thread_motion_scale": 1.55,
            "ai_presence_voice_thread_idle_motion": 0.18,
            "ai_presence_voice_thread_animation_speed": 0.82,
            "ai_presence_voice_thread_response_smoothing": 0.56,
            "ai_presence_voice_thread_spectrum_smoothing": 0.52,
            "ai_presence_voice_thread_spectrum_scale": 1.16,
            "ai_presence_voice_thread_peak_emphasis": 0.74,
            "ai_presence_voice_thread_glow_radius": 1.62,
            "ai_presence_voice_thread_glow_intensity": 1.48,
            "ai_presence_voice_thread_flux_strength": 1.52,
            "ai_presence_voice_thread_fiber_spread": 1.38,
            "ai_presence_voice_thread_bendiness": 1.42,
            "ai_presence_voice_thread_organic_variation": 1.25,
            "ai_presence_voice_thread_phrase_motion": 1.45,
            "ai_presence_voice_thread_gesture_intensity": 1.30,
            "ai_presence_voice_thread_motion_memory": 0.78,
            "ai_presence_voice_thread_accent_sensitivity": 0.62,
            "ai_presence_music_reactivity": 2.85,
            "ai_presence_voice_thread_ambient_reaction_target": "shape_glow",
            "ai_presence_voice_thread_ambient_smoothing": 0.68,
            "ai_presence_voice_thread_ambient_noise_gate": 0.03,
            "ai_presence_voice_thread_ambient_quiet_detail": 1.60,
            "ai_presence_voice_thread_ambient_transient_punch": 1.30,
            "ai_presence_voice_thread_ambient_attack_ms": 45,
            "ai_presence_voice_thread_ambient_release_ms": 430,
            "ai_presence_voice_thread_ambient_mix": 1.65,
            "ai_presence_voice_thread_ambient_link_main_controls": True,
            "ai_presence_voice_thread_ambient_fiber_spread_enabled": True,
            "ai_presence_voice_thread_ambient_shape_strength": 2.35,
            "ai_presence_voice_thread_ambient_travel_strength": 1.15,
            "ai_presence_voice_thread_ambient_glow_strength": 2.10,
            "ai_presence_voice_thread_ambient_fiber_strength": 1.80,
            "ai_presence_voice_thread_ambient_color_strength": 2.20,
            "ai_presence_voice_thread_audio_colors_enabled": True,
            "ai_presence_voice_thread_voice_colors_enabled": True,
            "ai_presence_voice_thread_desktop_colors_enabled": True,
            "ai_presence_voice_thread_color_vividness": 1.70,
            "ai_presence_voice_thread_color_bass_influence": 1.50,
            "ai_presence_voice_thread_color_mid_influence": 1.20,
            "ai_presence_voice_thread_color_high_influence": 1.80,
            "ai_presence_voice_thread_color_smoothing": 0.72,
            "ai_presence_voice_thread_ambient_motion_ceiling": 2.50,
            "ai_presence_voice_thread_ambient_bass_bend": 0.95,
            "ai_presence_voice_thread_ambient_mid_ripple": 0.52,
            "ai_presence_voice_thread_ambient_high_shimmer": 0.62,
            "ai_presence_voice_thread_physics_slack": 1.22,
        },
    },
    "minimal": {
        "label": "Minimal",
        "settings": {
            "ai_presence_voice_thread_motion_style": "organic_drift",
            "ai_presence_voice_thread_audio_reactivity": 0.68,
            "ai_presence_voice_thread_motion_scale": 0.36,
            "ai_presence_voice_thread_idle_motion": 0.08,
            "ai_presence_voice_thread_animation_speed": 0.66,
            "ai_presence_voice_thread_response_smoothing": 0.76,
            "ai_presence_voice_thread_spectrum_smoothing": 0.72,
            "ai_presence_voice_thread_spectrum_scale": 0.64,
            "ai_presence_voice_thread_peak_emphasis": 0.28,
            "ai_presence_voice_thread_glow_radius": 0.64,
            "ai_presence_voice_thread_glow_intensity": 0.46,
            "ai_presence_voice_thread_flux_strength": 0.30,
            "ai_presence_voice_thread_fiber_spread": 0.70,
            "ai_presence_voice_thread_bendiness": 0.42,
            "ai_presence_voice_thread_organic_variation": 0.35,
            "ai_presence_voice_thread_phrase_motion": 0.40,
            "ai_presence_voice_thread_gesture_intensity": 0.30,
            "ai_presence_voice_thread_motion_memory": 0.88,
            "ai_presence_voice_thread_accent_sensitivity": 0.32,
            "ai_presence_music_reactivity": 1.80,
            "ai_presence_voice_thread_ambient_reaction_target": "glow_only",
            "ai_presence_voice_thread_ambient_smoothing": 0.85,
            "ai_presence_voice_thread_ambient_noise_gate": 0.06,
            "ai_presence_voice_thread_ambient_quiet_detail": 1.10,
            "ai_presence_voice_thread_ambient_transient_punch": 0.45,
            "ai_presence_voice_thread_ambient_attack_ms": 90,
            "ai_presence_voice_thread_ambient_release_ms": 600,
            "ai_presence_voice_thread_ambient_mix": 0.65,
            "ai_presence_voice_thread_ambient_link_main_controls": True,
            "ai_presence_voice_thread_ambient_fiber_spread_enabled": True,
            "ai_presence_voice_thread_ambient_shape_strength": 0.60,
            "ai_presence_voice_thread_ambient_travel_strength": 0.45,
            "ai_presence_voice_thread_ambient_glow_strength": 0.85,
            "ai_presence_voice_thread_ambient_fiber_strength": 0.55,
            "ai_presence_voice_thread_ambient_color_strength": 0.70,
            "ai_presence_voice_thread_audio_colors_enabled": True,
            "ai_presence_voice_thread_voice_colors_enabled": True,
            "ai_presence_voice_thread_desktop_colors_enabled": True,
            "ai_presence_voice_thread_color_vividness": 0.65,
            "ai_presence_voice_thread_color_bass_influence": 0.80,
            "ai_presence_voice_thread_color_mid_influence": 0.65,
            "ai_presence_voice_thread_color_high_influence": 0.45,
            "ai_presence_voice_thread_color_smoothing": 1.40,
            "ai_presence_voice_thread_ambient_motion_ceiling": 1.15,
            "ai_presence_voice_thread_ambient_bass_bend": 0.24,
            "ai_presence_voice_thread_ambient_mid_ripple": 0.12,
            "ai_presence_voice_thread_ambient_high_shimmer": 0.20,
            "ai_presence_voice_thread_physics_slack": 0.45,
        },
    },
}


def _voice_thread_preset_slug(value: object) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower())
    return text.strip("-")[:48]

CORE_VISUAL_STYLES = list(VISUAL_STYLES)

MOOD_COLOR_MODES = [
    ("Automatic", "automatic"),
    ("Manual", "manual"),
    ("Off", "off"),
]

MOOD_CHOICES = [
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

ORB_DISPLAY_MODES = [
    ("Off", "off"),
    ("Docked only", "docked"),
    ("During interaction only", "interaction"),
    ("Always visible", "always"),
]

ORB_POSITIONS = [
    ("Top center", "top-center"),
    ("Bottom left", "bottom-left"),
    ("Top right", "top-right"),
    ("Top left", "top-left"),
    ("Custom", "custom"),
]

ORB_VISUAL_STYLES = [
    ("Neural Spark Orb", "neural_spark"),
    ("Silk Drift", "silk_drift"),
    ("Aurora Glass Orb", "aurora_glass"),
    ("Prismatic Pulse Ring", "prismatic_pulse"),
    ("Aether Wisp Orb", "aether_wisp"),
    ("Celestial Firetrail Orb", "celestial_firetrail"),
    ("Quantum Halo Orb", "quantum_halo"),
    ("Event Horizon Orb", "event_horizon"),
    ("Holographic Iris Orb", "holographic_iris"),
    ("Synaptic Bloom Orb", "synaptic_bloom"),
    ("Liquid Core Orb", "liquid_core"),
    ("Void Prism Orb", "void_prism"),
]

ORB_TARGET_MODES = [
    ("Window under orb", "window"),
    ("Region around orb", "region"),
]

ORB_RESPONSE_STYLES = list(companion_orb_reply_styles.ORB_RESPONSE_STYLES)

BOOL_SETTINGS = {
    "ai_presence_enabled",
    "ai_presence_fullscreen",
    "ai_presence_floating_always_on_top",
    "ai_presence_remember_floating_geometry",
    "ai_presence_click_through_default",
    "ai_presence_right_drag_move_enabled",
    "ai_presence_transparent_background",
    "ai_presence_external_runtime_enabled",
    "ai_presence_reduced_effects",
    "ai_presence_shaders_enabled",
    "ai_presence_particles_enabled",
    "ai_presence_space_closes_fullscreen",
    "ai_presence_music_reactivity_enabled",
    "ai_presence_voice_thread_ambient_link_main_controls",
    "ai_presence_voice_thread_ambient_fiber_spread_enabled",
    "ai_presence_voice_thread_audio_colors_enabled",
    "ai_presence_voice_thread_voice_colors_enabled",
    "ai_presence_voice_thread_desktop_colors_enabled",
    "ai_presence_voice_thread_mouse_physics_enabled",
    "ai_presence_voice_thread_show_placement_guide",
    "ai_presence_voice_thread_reflection_enabled",
    "ai_presence_mood_colors_enabled",
    "ai_presence_allow_story_mood_override",
    "ai_presence_allow_persona_mood_override",
    "companion_orb_enabled",
    "companion_orb_always_on_top",
    "companion_orb_click_through_default",
    "companion_orb_right_drag_focus_enabled",
    "companion_orb_interaction_defaults_version",
    "companion_orb_click_through_explicit",
    "companion_orb_remember_position",
    "companion_orb_external_runtime_enabled",
    "companion_orb_movement_enabled",
    "companion_orb_harassment_enabled",
    "companion_orb_snapshot_on_pointer_reached",
    "companion_orb_debug_enabled",
    "companion_orb_avoid_center",
    "companion_orb_avoid_mouse",
    "companion_orb_mouse_near_fade",
    "companion_orb_voice_sync_enabled",
    "companion_orb_falling_particles_enabled",
    "companion_orb_reduced_effects",
    "companion_orb_particles_enabled",
    "companion_orb_shaders_enabled",
    "companion_orb_custom_colors_enabled",
    "companion_orb_state_colors_enabled",
    "companion_orb_state_animation_enabled",
    "companion_orb_sensory_target_enabled",
    "companion_orb_full_screen_context_enabled",
    "companion_orb_full_screen_tiling_enabled",
    "companion_orb_supervisor_enabled",
    "companion_orb_show_target_label",
    "companion_orb_include_process_name",
    "companion_orb_require_target_confirmation",
    "companion_orb_hotkeys_enabled",
}

AI_PRESENCE_SESSION_KEYS = [
    "ai_presence_enabled",
    "ai_presence_display_mode",
    "ai_presence_visual_style",
    "ai_presence_render_backend",
    "ai_presence_fullscreen",
    "ai_presence_overlay_opacity",
    "ai_presence_floating_opacity",
    "ai_presence_fullscreen_opacity",
    "ai_presence_floating_window_opacity",
    "ai_presence_floating_always_on_top",
    "ai_presence_remember_floating_geometry",
    "ai_presence_click_through_default",
    "ai_presence_right_drag_move_enabled",
    "ai_presence_transparent_background",
    "ai_presence_floating_geometry",
    "ai_presence_external_runtime_enabled",
    "ai_presence_thinking_pulse",
    "ai_presence_speaking_reactivity",
    "ai_presence_audio_refresh_hz",
    "ai_presence_node_density",
    "ai_presence_particle_density",
    "ai_presence_reduced_effects",
    "ai_presence_shaders_enabled",
    "ai_presence_particles_enabled",
    "ai_presence_space_closes_fullscreen",
    "ai_presence_music_reactivity_enabled",
    "ai_presence_music_reactivity",
    "ai_presence_mood_colors_enabled",
    "ai_presence_mood_color_mode",
    "ai_presence_manual_mood",
    "ai_presence_mood_color_intensity",
    "ai_presence_allow_story_mood_override",
    "ai_presence_allow_persona_mood_override",
    "ai_presence_glow_strength",
    "ai_presence_animation_speed",
    "ai_presence_idle_motion_strength",
    "ai_presence_primary_color_strength",
    "ai_presence_secondary_color_strength",
    "ai_presence_background_darkness",
    "ai_presence_halo_thickness",
    "ai_presence_waveform_strength",
    "ai_presence_ring_expansion_speed",
    "ai_presence_blur_softness",
    "ai_presence_line_brightness",
    "ai_presence_voice_thread_variation",
    "ai_presence_voice_thread_palette",
    "ai_presence_voice_thread_peak_emphasis",
    "ai_presence_voice_thread_glow_radius",
    "ai_presence_voice_thread_reflection_enabled",
    "ai_presence_voice_thread_reflection_distance",
    "ai_presence_voice_thread_strand_multiplier",
    "ai_presence_voice_thread_motion_style",
    "ai_presence_voice_thread_audio_reactivity",
    "ai_presence_voice_thread_motion_scale",
    "ai_presence_voice_thread_idle_motion",
    "ai_presence_voice_thread_animation_speed",
    "ai_presence_voice_thread_response_smoothing",
    "ai_presence_voice_thread_spectrum_smoothing",
    "ai_presence_voice_thread_spectrum_scale",
    "ai_presence_voice_thread_glow_intensity",
    "ai_presence_voice_thread_flux_strength",
    "ai_presence_voice_thread_fiber_spread",
    "ai_presence_voice_thread_bendiness",
    "ai_presence_voice_thread_organic_variation",
    "ai_presence_voice_thread_phrase_motion",
    "ai_presence_voice_thread_gesture_intensity",
    "ai_presence_voice_thread_motion_memory",
    "ai_presence_voice_thread_accent_sensitivity",
    "ai_presence_voice_thread_ambient_reaction_target",
    "ai_presence_voice_thread_ambient_smoothing",
    "ai_presence_voice_thread_ambient_noise_gate",
    "ai_presence_voice_thread_ambient_quiet_detail",
    "ai_presence_voice_thread_ambient_transient_punch",
    "ai_presence_voice_thread_ambient_attack_ms",
    "ai_presence_voice_thread_ambient_release_ms",
    "ai_presence_voice_thread_ambient_mix",
    "ai_presence_voice_thread_ambient_link_main_controls",
    "ai_presence_voice_thread_ambient_fiber_spread_enabled",
    "ai_presence_voice_thread_ambient_shape_strength",
    "ai_presence_voice_thread_ambient_travel_strength",
    "ai_presence_voice_thread_ambient_glow_strength",
    "ai_presence_voice_thread_ambient_fiber_strength",
    "ai_presence_voice_thread_ambient_color_strength",
    "ai_presence_voice_thread_audio_colors_enabled",
    "ai_presence_voice_thread_voice_colors_enabled",
    "ai_presence_voice_thread_desktop_colors_enabled",
    "ai_presence_voice_thread_color_vividness",
    "ai_presence_voice_thread_color_bass_influence",
    "ai_presence_voice_thread_color_mid_influence",
    "ai_presence_voice_thread_color_high_influence",
    "ai_presence_voice_thread_color_smoothing",
    "ai_presence_voice_thread_ambient_motion_ceiling",
    "ai_presence_voice_thread_ambient_bass_bend",
    "ai_presence_voice_thread_ambient_mid_ripple",
    "ai_presence_voice_thread_ambient_high_shimmer",
    "ai_presence_voice_thread_mouse_physics_enabled",
    "ai_presence_voice_thread_physics_feel",
    "ai_presence_voice_thread_physics_slack",
    "ai_presence_voice_thread_interaction_area",
    "ai_presence_voice_thread_gravity",
    "ai_presence_voice_thread_retension_time",
    "ai_presence_voice_thread_show_placement_guide",
    "ai_presence_voice_thread_size",
    "ai_presence_voice_thread_horizontal_span",
    "ai_presence_voice_thread_position_x",
    "ai_presence_voice_thread_position_y",
    "ai_presence_voice_thread_frame_rate",
    "ai_presence_voice_thread_selected_preset",
    "ai_presence_voice_thread_custom_presets",
    "ai_presence_voice_thread_primary_color",
    "ai_presence_voice_thread_accent_color",
    "ai_presence_voice_thread_highlight_color",
    "ai_presence_live_controls_visible",
    "companion_orb_enabled",
    "companion_orb_display_mode",
    "companion_orb_position",
    "companion_orb_size",
    "companion_orb_opacity",
    "companion_orb_always_on_top",
    "companion_orb_click_through_default",
    "companion_orb_right_drag_focus_enabled",
    "companion_orb_interaction_defaults_version",
    "companion_orb_click_through_explicit",
    "companion_orb_remember_position",
    "companion_orb_external_runtime_enabled",
    "companion_orb_custom_position",
    "companion_orb_movement_enabled",
    "companion_orb_movement_speed",
    "companion_orb_movement_range",
    "companion_orb_frame_rate",
    "companion_orb_return_home_delay",
    "companion_orb_harassment_enabled",
    "companion_orb_response_style",
    "companion_orb_response_style_prompts",
    "companion_orb_popup_compact_mode",
    "companion_orb_popup_pinned",
    "companion_orb_popup_position",
    "companion_orb_popup_width",
    "companion_orb_harassment_timer_seconds",
    "companion_orb_snapshot_on_pointer_reached",
    "companion_orb_debug_enabled",
    "companion_orb_avoid_center",
    "companion_orb_avoid_mouse",
    "companion_orb_mouse_near_fade",
    "companion_orb_mouse_near_fade_distance",
    "companion_orb_mouse_near_opacity",
    "companion_orb_visual_style",
    "companion_orb_render_backend",
    "companion_orb_trail_length",
    "companion_orb_particle_density",
    "companion_orb_falling_particles_enabled",
    "companion_orb_falling_particle_density",
    "companion_orb_falling_particle_lifetime",
    "companion_orb_smoke_intensity",
    "companion_orb_glow_strength",
    "companion_orb_mood_color_intensity",
    "companion_orb_mood_color_mode",
    "companion_orb_manual_mood",
    "companion_orb_color_palette",
    "companion_orb_custom_colors_enabled",
    "companion_orb_primary_color",
    "companion_orb_secondary_color",
    "companion_orb_accent_color",
    "companion_orb_glow_color",
    "companion_orb_state_colors_enabled",
    "companion_orb_idle_color",
    "companion_orb_thinking_color",
    "companion_orb_speaking_color",
    "companion_orb_state_animation_enabled",
    "companion_orb_idle_animation",
    "companion_orb_thinking_animation",
    "companion_orb_speaking_animation",
    "companion_orb_speaking_reactivity",
    "companion_orb_voice_sync_enabled",
    "companion_orb_audio_refresh_hz",
    "companion_orb_reduced_effects",
    "companion_orb_particles_enabled",
    "companion_orb_shaders_enabled",
    "companion_orb_sensory_target_enabled",
    "companion_orb_full_screen_context_enabled",
    "companion_orb_full_screen_tiling_enabled",
    "companion_orb_full_screen_tile_count",
    "companion_orb_supervisor_enabled",
    "companion_orb_supervisor_prompt_template",
    "companion_orb_supervisor_personas",
    "companion_orb_supervisor_selected_persona_id",
    "companion_orb_target_mode",
    "companion_orb_target_region_width",
    "companion_orb_target_region_height",
    "companion_orb_show_target_label",
    "companion_orb_include_process_name",
    "companion_orb_require_target_confirmation",
    "companion_orb_hotkeys_enabled",
    "companion_orb_toggle_hotkey",
    "companion_orb_edit_hotkey",
    "companion_orb_placement_hotkey",
    "companion_orb_clear_target_hotkey",
    "companion_orb_click_through_hotkey",
    "companion_orb_reset_position_hotkey",
    "companion_orb_target_info",
]

COMPANION_ORB_SESSION_KEYS = [
    key for key in AI_PRESENCE_SESSION_KEYS if key.startswith("companion_orb_")
]

AI_PRESENCE_CORE_SESSION_KEYS = [
    key
    for key in AI_PRESENCE_SESSION_KEYS
    if key not in set(COMPANION_ORB_SESSION_KEYS)
]

DEFAULT_SETTINGS = {
    "ai_presence_enabled": False,
    "ai_presence_display_mode": "floating",
    "ai_presence_visual_style": "living_voice_thread",
    "ai_presence_render_backend": "gpu_native",
    "ai_presence_fullscreen": True,
    "ai_presence_overlay_opacity": 0.72,
    "ai_presence_floating_opacity": 0.92,
    "ai_presence_fullscreen_opacity": 0.72,
    "ai_presence_floating_window_opacity": 1,
    "ai_presence_floating_always_on_top": True,
    "ai_presence_remember_floating_geometry": True,
    "ai_presence_click_through_default": True,
    "ai_presence_right_drag_move_enabled": True,
    "ai_presence_transparent_background": True,
    "ai_presence_floating_geometry": [],
    "ai_presence_external_runtime_enabled": False,
    "ai_presence_thinking_pulse": 0.55,
    "ai_presence_speaking_reactivity": 0.98,
    "ai_presence_audio_refresh_hz": 90,
    "ai_presence_node_density": 96,
    "ai_presence_particle_density": 120,
    "ai_presence_reduced_effects": False,
    "ai_presence_shaders_enabled": True,
    "ai_presence_particles_enabled": True,
    "ai_presence_space_closes_fullscreen": True,
    "ai_presence_music_reactivity_enabled": True,
    "ai_presence_music_reactivity": 2.32,
    "ai_presence_mood_colors_enabled": True,
    "ai_presence_mood_color_mode": "automatic",
    "ai_presence_manual_mood": "neutral",
    "ai_presence_mood_color_intensity": 0.85,
    "ai_presence_allow_story_mood_override": True,
    "ai_presence_allow_persona_mood_override": True,
    "ai_presence_glow_strength": 0.65,
    "ai_presence_animation_speed": 1.0,
    "ai_presence_idle_motion_strength": 0,
    "ai_presence_primary_color_strength": 1.44,
    "ai_presence_secondary_color_strength": 0.81,
    "ai_presence_background_darkness": 1.0,
    "ai_presence_halo_thickness": 2,
    "ai_presence_waveform_strength": 2,
    "ai_presence_ring_expansion_speed": 2,
    "ai_presence_blur_softness": 0.11,
    "ai_presence_line_brightness": 2,
    "ai_presence_voice_thread_variation": "silk_ribbon",
    "ai_presence_voice_thread_palette": "custom",
    "ai_presence_voice_thread_peak_emphasis": 0.82,
    "ai_presence_voice_thread_glow_radius": 0.61,
    "ai_presence_voice_thread_reflection_enabled": True,
    "ai_presence_voice_thread_reflection_distance": 0.81,
    "ai_presence_voice_thread_strand_multiplier": 1,
    "ai_presence_voice_thread_motion_style": "breathing_ribbon",
    "ai_presence_voice_thread_audio_reactivity": 1.79,
    "ai_presence_voice_thread_motion_scale": 0.74,
    "ai_presence_voice_thread_idle_motion": 1.27,
    "ai_presence_voice_thread_animation_speed": 0.52,
    "ai_presence_voice_thread_response_smoothing": 0.73,
    "ai_presence_voice_thread_spectrum_smoothing": 0.32,
    "ai_presence_voice_thread_spectrum_scale": 0.99,
    "ai_presence_voice_thread_glow_intensity": 4,
    "ai_presence_voice_thread_flux_strength": 1.42,
    "ai_presence_voice_thread_fiber_spread": 1.27,
    "ai_presence_voice_thread_bendiness": 0.39,
    "ai_presence_voice_thread_organic_variation": 2.65,
    "ai_presence_voice_thread_phrase_motion": 1.35,
    "ai_presence_voice_thread_gesture_intensity": 1.55,
    "ai_presence_voice_thread_motion_memory": 0.5,
    "ai_presence_voice_thread_accent_sensitivity": 1.66,
    "ai_presence_voice_thread_ambient_reaction_target": "full_spectrum",
    "ai_presence_voice_thread_ambient_smoothing": 0.52,
    "ai_presence_voice_thread_ambient_noise_gate": 0.07,
    "ai_presence_voice_thread_ambient_quiet_detail": 1.1,
    "ai_presence_voice_thread_ambient_transient_punch": 2.6,
    "ai_presence_voice_thread_ambient_attack_ms": 17,
    "ai_presence_voice_thread_ambient_release_ms": 127,
    "ai_presence_voice_thread_ambient_mix": 0.96,
    "ai_presence_voice_thread_ambient_link_main_controls": True,
    "ai_presence_voice_thread_ambient_fiber_spread_enabled": True,
    "ai_presence_voice_thread_ambient_shape_strength": 2.6,
    "ai_presence_voice_thread_ambient_travel_strength": 2.25,
    "ai_presence_voice_thread_ambient_glow_strength": 2.2,
    "ai_presence_voice_thread_ambient_fiber_strength": 1.02,
    "ai_presence_voice_thread_ambient_color_strength": 2,
    "ai_presence_voice_thread_audio_colors_enabled": True,
    "ai_presence_voice_thread_voice_colors_enabled": True,
    "ai_presence_voice_thread_desktop_colors_enabled": True,
    "ai_presence_voice_thread_color_vividness": 4,
    "ai_presence_voice_thread_color_bass_influence": 4,
    "ai_presence_voice_thread_color_mid_influence": 4,
    "ai_presence_voice_thread_color_high_influence": 2.34,
    "ai_presence_voice_thread_color_smoothing": 0.41,
    "ai_presence_voice_thread_ambient_motion_ceiling": 0.79,
    "ai_presence_voice_thread_ambient_bass_bend": 0.8,
    "ai_presence_voice_thread_ambient_mid_ripple": 1.03,
    "ai_presence_voice_thread_ambient_high_shimmer": 0.85,
    "ai_presence_voice_thread_mouse_physics_enabled": False,
    "ai_presence_voice_thread_physics_feel": "natural",
    "ai_presence_voice_thread_physics_slack": 1.45,
    "ai_presence_voice_thread_interaction_area": 1.6,
    "ai_presence_voice_thread_gravity": 1.2,
    "ai_presence_voice_thread_retension_time": 0.65,
    "ai_presence_voice_thread_show_placement_guide": False,
    "ai_presence_voice_thread_size": 1.85,
    "ai_presence_voice_thread_horizontal_span": 1.33,
    "ai_presence_voice_thread_position_x": 0.5,
    "ai_presence_voice_thread_position_y": 0.5,
    "ai_presence_voice_thread_frame_rate": 120,
    "ai_presence_voice_thread_selected_preset": "default",
    "ai_presence_voice_thread_custom_presets": {},
    "ai_presence_voice_thread_primary_color": "#0013ee",
    "ai_presence_voice_thread_accent_color": "#fa2d00",
    "ai_presence_voice_thread_highlight_color": "#0fff00",
    "ai_presence_live_controls_visible": False,
    "companion_orb_enabled": False,
    "companion_orb_display_mode": "off",
    "companion_orb_position": "top-center",
    "companion_orb_size": 92,
    "companion_orb_opacity": 0.82,
    "companion_orb_always_on_top": True,
    "companion_orb_click_through_default": False,
    "companion_orb_right_drag_focus_enabled": True,
    "companion_orb_interaction_defaults_version": 2,
    "companion_orb_click_through_explicit": False,
    "companion_orb_remember_position": True,
    "companion_orb_external_runtime_enabled": True,
    "companion_orb_custom_position": [],
    "companion_orb_movement_enabled": True,
    "companion_orb_movement_speed": 0.65,
    "companion_orb_movement_range": 18,
    "companion_orb_frame_rate": 60,
    "companion_orb_return_home_delay": 2.5,
    "companion_orb_harassment_enabled": False,
    "companion_orb_response_style": "friendly",
    "companion_orb_response_style_prompts": {},
    "companion_orb_popup_compact_mode": False,
    "companion_orb_popup_pinned": False,
    "companion_orb_popup_position": [],
    "companion_orb_popup_width": 520,
    "companion_orb_harassment_timer_seconds": 45,
    "companion_orb_snapshot_on_pointer_reached": False,
    "companion_orb_debug_enabled": False,
    "companion_orb_avoid_center": True,
    "companion_orb_avoid_mouse": False,
    "companion_orb_mouse_near_fade": False,
    "companion_orb_mouse_near_fade_distance": 120,
    "companion_orb_mouse_near_opacity": 0.28,
    "companion_orb_visual_style": "neural_spark",
    "companion_orb_render_backend": "gpu_native",
    "companion_orb_trail_length": 0.55,
    "companion_orb_particle_density": 30,
    "companion_orb_falling_particles_enabled": False,
    "companion_orb_falling_particle_density": 18,
    "companion_orb_falling_particle_lifetime": 3.8,
    "companion_orb_smoke_intensity": 0.35,
    "companion_orb_glow_strength": 1.0,
    "companion_orb_mood_color_intensity": 0.85,
    "companion_orb_mood_color_mode": "automatic",
    "companion_orb_manual_mood": "neutral",
    "companion_orb_color_palette": "custom",
    "companion_orb_custom_colors_enabled": False,
    "companion_orb_primary_color": "#22d3ee",
    "companion_orb_secondary_color": "#38bdf8",
    "companion_orb_accent_color": "#a78bfa",
    "companion_orb_glow_color": "#67e8f9",
    "companion_orb_state_colors_enabled": False,
    "companion_orb_idle_color": "#38bdf8",
    "companion_orb_thinking_color": "#a78bfa",
    "companion_orb_speaking_color": "#f472b6",
    "companion_orb_state_animation_enabled": False,
    "companion_orb_idle_animation": "calm_breathe",
    "companion_orb_thinking_animation": "thinking_swirl",
    "companion_orb_speaking_animation": "voice_ripple",
    "companion_orb_speaking_reactivity": 0.85,
    "companion_orb_voice_sync_enabled": True,
    "companion_orb_audio_refresh_hz": 24,
    "companion_orb_reduced_effects": False,
    "companion_orb_particles_enabled": True,
    "companion_orb_shaders_enabled": True,
    "companion_orb_sensory_target_enabled": False,
    "companion_orb_full_screen_context_enabled": False,
    "companion_orb_full_screen_tiling_enabled": False,
    "companion_orb_full_screen_tile_count": 5,
    "companion_orb_supervisor_enabled": False,
    "companion_orb_supervisor_prompt_template": "",
    "companion_orb_supervisor_personas": [],
    "companion_orb_supervisor_selected_persona_id": "",
    "companion_orb_target_mode": "window",
    "companion_orb_target_region_width": 640,
    "companion_orb_target_region_height": 420,
    "companion_orb_show_target_label": True,
    "companion_orb_include_process_name": True,
    "companion_orb_require_target_confirmation": True,
    "companion_orb_hotkeys_enabled": True,
    "companion_orb_toggle_hotkey": "Ctrl+Alt+O",
    "companion_orb_edit_hotkey": "Ctrl+Alt+Shift+O",
    "companion_orb_placement_hotkey": "Ctrl+Alt+P",
    "companion_orb_clear_target_hotkey": "Ctrl+Alt+Backspace",
    "companion_orb_click_through_hotkey": "Ctrl+Alt+C",
    "companion_orb_reset_position_hotkey": "Ctrl+Alt+R",
    "companion_orb_target_info": {},
}


class AIPresenceModeController(QtCore.QObject):
    SESSION_KEYS = AI_PRESENCE_CORE_SESSION_KEYS
    APPLY_STATUS_MESSAGE = "AI Presence settings applied."

    def __init__(self, context):
        super().__init__()
        self.context = context
        self.runtime_config = context.capabilities.runtime_config
        # Native QML owns presentation. These empty collections keep the
        # presentation-neutral refresh path backward compatible without
        # constructing or searching for widgets.
        self._widgets = []
        self._controls = {}
        self._preview_timer = None
        self._preview_restore_settings = None
        self._preview_generation = 0
        self._native_status = "AI Presence addon controls are ready."

    def _runtime_config(self) -> dict:
        return dict(self.runtime_config.snapshot() or {})

    def _setting(self, key):
        return self.runtime_config.get(str(key), DEFAULT_SETTINGS.get(key))

    def _update_runtime_config(self, key, value):
        return self.runtime_config.update(str(key), value)

    def _on_setting_changed(self, key, value, *, persist=True):
        key = str(key or "").strip()
        if not key:
            return
        normalized = self._normalize_setting(key, value)
        if key in {"ai_presence_enabled", "ai_presence_display_mode", "ai_presence_fullscreen"}:
            self._preview_restore_settings = None
        self._update_runtime_config(key, normalized)
        self._apply_runtime_config()
        if persist:
            self._save_session()

    def _normalize_setting(self, key, value):
        if key in {"ai_presence_fullscreen_opacity", "ai_presence_floating_window_opacity"}:
            return None if value is None else max(0.0, min(1.0, float(value)))
        if key in BOOL_SETTINGS:
            return bool(value)
        if key == "ai_presence_display_mode":
            mode = str(value or "fullscreen").strip().lower()
            return mode if mode in {item[1] for item in DISPLAY_MODES} else "fullscreen"
        if key == "ai_presence_visual_style":
            style = str(value or "neural_network_pulse").strip().lower()
            return style if style in {item[1] for item in VISUAL_STYLES} else "neural_network_pulse"
        if key == "ai_presence_voice_thread_variation":
            variation = str(value or "silk_ribbon").strip().lower()
            allowed = {"silk_ribbon", "double_helix", "harmonic_threads"}
            return variation if variation in allowed else "silk_ribbon"
        if key == "ai_presence_voice_thread_palette":
            palette = str(value or "persona_mood").strip().lower()
            allowed = {"persona_mood", "aurora", "electric_cyan", "ember", "ghost", "custom"}
            return palette if palette in allowed else "persona_mood"
        if key == "ai_presence_voice_thread_motion_style":
            style = str(value or "organic_drift").strip().lower()
            allowed = {item[1] for item in VOICE_THREAD_MOTION_STYLES}
            return style if style in allowed else "organic_drift"
        if key == "ai_presence_voice_thread_ambient_reaction_target":
            target = str(value or "shape_glow").strip().lower()
            allowed = {item[1] for item in VOICE_THREAD_AMBIENT_TARGETS}
            return target if target in allowed else "shape_glow"
        if key == "ai_presence_voice_thread_physics_feel":
            feel = str(value or "natural").strip().lower()
            allowed = {item[1] for item in VOICE_THREAD_PHYSICS_FEELS}
            return feel if feel in allowed else "natural"
        if key == "ai_presence_voice_thread_selected_preset":
            selected = str(value or "balanced").strip().lower()
            if selected in VOICE_THREAD_BUILTIN_PRESETS:
                return selected
            if selected.startswith("custom:"):
                slug = _voice_thread_preset_slug(selected.split(":", 1)[1])
                return f"custom:{slug}" if slug else "balanced"
            return "balanced"
        if key == "ai_presence_voice_thread_custom_presets":
            if not isinstance(value, Mapping):
                return {}
            normalized_presets: dict[str, dict[str, object]] = {}
            for raw_key, raw_preset in list(value.items())[:24]:
                slug = _voice_thread_preset_slug(raw_key)
                if not slug or not isinstance(raw_preset, Mapping):
                    continue
                label = str(raw_preset.get("label") or raw_key).strip()[:64]
                raw_settings = raw_preset.get("settings")
                if not label or not isinstance(raw_settings, Mapping):
                    continue
                preset_settings = {
                    setting_key: self._normalize_setting(
                        setting_key, raw_settings[setting_key]
                    )
                    for setting_key in VOICE_THREAD_CUSTOM_CAPTURE_KEYS
                    if setting_key in raw_settings
                }
                normalized_presets[slug] = {
                    "label": label,
                    "settings": preset_settings,
                }
            return normalized_presets
        if key in {"ai_presence_render_backend", "companion_orb_render_backend"}:
            backend = str(value or "gpu_native").strip().lower()
            return backend if backend in {item[1] for item in RENDER_BACKENDS} else "gpu_native"
        if key == "companion_orb_display_mode":
            mode = str(value or "off").strip().lower()
            return mode if mode in {item[1] for item in ORB_DISPLAY_MODES} else "off"
        if key == "companion_orb_position":
            position = str(value or "top-center").strip().lower()
            return position if position in {item[1] for item in ORB_POSITIONS} else "top-center"
        if key == "companion_orb_response_style":
            return companion_orb_reply_styles.normalize_reply_style(value)
        if key == "companion_orb_response_style_prompts":
            return companion_orb_reply_styles.normalize_reply_style_prompts(value)
        if key == "companion_orb_visual_style":
            style = str(value or "neural_spark").strip().lower()
            return style if style in {item[1] for item in ORB_VISUAL_STYLES} else "neural_spark"
        if key == "companion_orb_target_mode":
            mode = str(value or "window").strip().lower()
            return mode if mode in {item[1] for item in ORB_TARGET_MODES} else "window"
        if key == "ai_presence_mood_color_mode":
            mode = str(value or "automatic").strip().lower()
            return mode if mode in {item[1] for item in MOOD_COLOR_MODES} else "automatic"
        if key == "ai_presence_manual_mood":
            mood = str(value or "neutral").strip().lower()
            return mood if mood in {item[1] for item in MOOD_CHOICES} else "neutral"
        if key == "companion_orb_mood_color_mode":
            mode = str(value or "automatic").strip().lower()
            return mode if mode in {item[1] for item in MOOD_COLOR_MODES} else "automatic"
        if key == "companion_orb_manual_mood":
            mood = str(value or "neutral").strip().lower()
            return mood if mood in {item[1] for item in MOOD_CHOICES} else "neutral"
        if key == "ai_presence_audio_refresh_hz":
            return max(5, min(120, int(value)))
        if key == "ai_presence_node_density":
            return max(8, min(96, int(value)))
        if key == "ai_presence_particle_density":
            return max(0, min(120, int(value)))
        if key == "ai_presence_speaking_reactivity":
            return max(0.10, min(1.50, float(value)))
        if key == "ai_presence_voice_thread_peak_emphasis":
            return max(0.00, min(4.00, float(value)))
        if key == "ai_presence_voice_thread_glow_radius":
            return max(0.25, min(4.00, float(value)))
        if key in {
            "ai_presence_voice_thread_audio_reactivity",
            "ai_presence_voice_thread_motion_scale",
            "ai_presence_voice_thread_spectrum_scale",
            "ai_presence_voice_thread_glow_intensity",
            "ai_presence_voice_thread_flux_strength",
            "ai_presence_voice_thread_bendiness",
            "ai_presence_voice_thread_organic_variation",
            "ai_presence_voice_thread_phrase_motion",
            "ai_presence_voice_thread_gesture_intensity",
            "ai_presence_voice_thread_accent_sensitivity",
            "ai_presence_voice_thread_ambient_bass_bend",
            "ai_presence_voice_thread_ambient_mid_ripple",
            "ai_presence_voice_thread_ambient_high_shimmer",
            "ai_presence_voice_thread_color_vividness",
            "ai_presence_voice_thread_color_bass_influence",
            "ai_presence_voice_thread_color_mid_influence",
            "ai_presence_voice_thread_color_high_influence",
            "ai_presence_voice_thread_physics_slack",
            "ai_presence_voice_thread_reflection_distance",
        }:
            return max(0.00, min(4.00, float(value)))
        if key == "ai_presence_voice_thread_size":
            return max(0.25, min(6.00, float(value)))
        if key == "ai_presence_voice_thread_horizontal_span":
            return max(1.00, min(4.00, float(value)))
        if key == "ai_presence_voice_thread_interaction_area":
            return max(1.20, min(5.00, float(value)))
        if key == "ai_presence_voice_thread_gravity":
            return max(0.20, min(4.00, float(value)))
        if key == "ai_presence_voice_thread_retension_time":
            return max(0.20, min(2.00, float(value)))
        if key in {
            "ai_presence_voice_thread_position_x",
            "ai_presence_voice_thread_position_y",
        }:
            return max(0.00, min(1.00, float(value)))
        if key == "ai_presence_voice_thread_fiber_spread":
            return max(0.25, min(4.00, float(value)))
        if key == "ai_presence_voice_thread_animation_speed":
            return max(0.25, min(3.00, float(value)))
        if key == "ai_presence_voice_thread_idle_motion":
            return max(0.00, min(3.00, float(value)))
        if key in {
            "ai_presence_voice_thread_response_smoothing",
            "ai_presence_voice_thread_spectrum_smoothing",
            "ai_presence_voice_thread_motion_memory",
            "ai_presence_voice_thread_ambient_smoothing",
            "ai_presence_voice_thread_color_smoothing",
        }:
            return max(0.00, min(2.00, float(value)))
        if key == "ai_presence_voice_thread_ambient_noise_gate":
            configured = max(0.00, float(value))
            if 0.25 < configured <= 2.00:
                return min(0.10, configured * 0.04)
            return min(0.25, configured)
        if key == "ai_presence_voice_thread_ambient_quiet_detail":
            return max(0.00, min(2.50, float(value)))
        if key in {
            "ai_presence_voice_thread_ambient_transient_punch",
            "ai_presence_voice_thread_ambient_shape_strength",
            "ai_presence_voice_thread_ambient_travel_strength",
            "ai_presence_voice_thread_ambient_glow_strength",
            "ai_presence_voice_thread_ambient_fiber_strength",
            "ai_presence_voice_thread_ambient_color_strength",
        }:
            return max(0.00, min(3.00, float(value)))
        if key == "ai_presence_voice_thread_ambient_mix":
            return max(0.00, min(2.00, float(value)))
        if key == "ai_presence_voice_thread_ambient_motion_ceiling":
            return max(0.25, min(3.00, float(value)))
        if key == "ai_presence_voice_thread_ambient_attack_ms":
            return max(5, min(250, int(value)))
        if key == "ai_presence_voice_thread_ambient_release_ms":
            return max(40, min(700, int(value)))
        if key == "ai_presence_music_reactivity":
            return max(0.00, min(4.00, float(value)))
        if key == "ai_presence_voice_thread_frame_rate":
            return max(15, min(120, int(value)))
        if key == "ai_presence_voice_thread_strand_multiplier":
            return max(1, min(5, int(value)))
        if key == "ai_presence_glow_strength":
            return max(0.00, min(1.75, float(value)))
        if key == "ai_presence_animation_speed":
            return max(0.35, min(1.75, float(value)))
        if key == "ai_presence_idle_motion_strength":
            return max(0.00, min(1.00, float(value)))
        if key in {"ai_presence_primary_color_strength", "ai_presence_secondary_color_strength"}:
            return max(0.00, min(1.50, float(value)))
        if key == "ai_presence_background_darkness":
            return max(0.00, min(1.00, float(value)))
        if key in {"ai_presence_halo_thickness", "ai_presence_waveform_strength", "ai_presence_ring_expansion_speed", "ai_presence_line_brightness"}:
            return max(0.20, min(2.00, float(value)))
        if key == "ai_presence_blur_softness":
            return max(0.00, min(1.00, float(value)))
        if key == "ai_presence_floating_opacity":
            return max(0.35, min(1.00, float(value)))
        if key == "ai_presence_mood_color_intensity":
            return max(0.00, min(1.00, float(value)))
        if key == "companion_orb_size":
            return max(36, min(220, int(value)))
        if key in {"companion_orb_target_region_width", "companion_orb_target_region_height"}:
            return max(64, min(2560, int(value)))
        if key == "companion_orb_full_screen_tile_count":
            return max(2, min(12, int(value)))
        if key == "companion_orb_particle_density":
            return max(0, min(120, int(value)))
        if key == "companion_orb_falling_particle_density":
            return max(0, min(80, int(value)))
        if key == "companion_orb_falling_particle_lifetime":
            return max(0.80, min(8.00, float(value)))
        if key == "companion_orb_movement_range":
            return max(0, min(90, int(value)))
        if key == "companion_orb_frame_rate":
            try:
                fps = int(value)
            except Exception:
                fps = int(DEFAULT_SETTINGS.get(key, 60))
            return min((30, 60, 90, 120), key=lambda candidate: abs(candidate - fps))
        if key == "companion_orb_audio_refresh_hz":
            return max(5, min(30, int(value)))
        if key == "companion_orb_mouse_near_fade_distance":
            return max(24, min(420, int(value)))
        if key in {"companion_orb_opacity", "companion_orb_trail_length", "companion_orb_smoke_intensity", "companion_orb_mood_color_intensity", "companion_orb_mouse_near_opacity"}:
            return max(0.00, min(1.00, float(value)))
        if key in {"companion_orb_glow_strength", "companion_orb_speaking_reactivity", "companion_orb_movement_speed"}:
            return max(0.10, min(1.75, float(value)))
        if key == "companion_orb_return_home_delay":
            return max(0.25, min(30.00, float(value)))
        if key == "companion_orb_harassment_timer_seconds":
            return max(5, min(300, int(value)))
        if key in {
            "ai_presence_voice_thread_primary_color",
            "ai_presence_voice_thread_accent_color",
            "ai_presence_voice_thread_highlight_color",
            "companion_orb_primary_color",
            "companion_orb_secondary_color",
            "companion_orb_accent_color",
            "companion_orb_glow_color",
            "companion_orb_idle_color",
            "companion_orb_thinking_color",
            "companion_orb_speaking_color",
        }:
            text = str(value or DEFAULT_SETTINGS.get(key, "#38bdf8") or "#38bdf8").strip()
            if not text.startswith("#"):
                text = "#" + text
            text = text[:7]
            if len(text) != 7:
                return DEFAULT_SETTINGS.get(key, "#38bdf8")
            try:
                int(text[1:], 16)
            except ValueError:
                return DEFAULT_SETTINGS.get(key, "#38bdf8")
            return text.lower()
        if key in {"companion_orb_idle_animation", "companion_orb_thinking_animation", "companion_orb_speaking_animation"}:
            animation = str(value or DEFAULT_SETTINGS.get(key, "style_default")).strip().lower()
            allowed = {"style_default", "calm_breathe", "slow_orbit", "focused_pulse", "thinking_swirl", "voice_ripple", "energetic_sparkle"}
            return animation if animation in allowed else DEFAULT_SETTINGS.get(key, "style_default")
        if key.endswith("_hotkey"):
            return str(value or DEFAULT_SETTINGS.get(key, "") or "").strip()
        if key in {
            "companion_orb_custom_position",
            "companion_orb_popup_position",
        }:
            return list(value or []) if isinstance(value, (list, tuple)) else []
        if key == "companion_orb_popup_width":
            try:
                return max(440, min(760, int(value)))
            except (TypeError, ValueError, OverflowError):
                return 520
        if key == "companion_orb_target_info":
            return dict(value or {}) if isinstance(value, dict) else {}
        if key in {"ai_presence_overlay_opacity", "ai_presence_thinking_pulse"}:
            return max(0.10, min(1.00, float(value)))
        return value

    def _apply_settings_payload(self, settings, *, update_status=True):
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.apply_settings(dict(settings or {}))
        except Exception as exc:
            self._set_status(f"AI Presence settings could not be applied: {exc}")
            return False
        if update_status:
            self._set_status(self.APPLY_STATUS_MESSAGE)
        return True

    def _presentation_settings(self):
        # Preview display values belong only to the visual payload. Session
        # saves, including unrelated saves, must read the durable config.
        settings = self._runtime_config()
        if self._preview_restore_settings is not None:
            settings.update(ai_presence_enabled=True,
                            ai_presence_display_mode="fullscreen",
                            ai_presence_fullscreen=True)
        return settings

    def _apply_runtime_config(self):
        self._apply_settings_payload(self._presentation_settings())

    def native_snapshot(self):
        config = self._runtime_config()
        return {
            "settings": {
                key: config.get(key, DEFAULT_SETTINGS.get(key))
                for key in self.SESSION_KEYS
            },
            "status": str(self._native_status or "AI Presence addon controls are ready."),
        }

    def native_update_setting(self, key, value):
        setting_key = str(key or "").strip()
        if setting_key not in self.SESSION_KEYS:
            raise KeyError(f"Unknown AI Presence setting: {setting_key}")
        self._on_setting_changed(setting_key, value, persist=False)
        return self.native_snapshot()

    def native_preview_setting(self, key, value):
        setting_key = str(key or "").strip()
        if setting_key not in self.SESSION_KEYS:
            raise KeyError(f"Unknown AI Presence setting: {setting_key}")
        preview_settings = self._presentation_settings()
        preview_settings[setting_key] = self._normalize_setting(setting_key, value)
        self._apply_settings_payload(preview_settings, update_status=False)
        return {
            "settings": preview_settings,
            "status": str(
                self._native_status or "AI Presence addon controls are ready."
            ),
            "preview": True,
        }

    def _voice_thread_custom_presets(self) -> dict[str, dict[str, object]]:
        return dict(
            self._normalize_setting(
                "ai_presence_voice_thread_custom_presets",
                self._setting("ai_presence_voice_thread_custom_presets"),
            )
        )

    def _load_voice_thread_preset(self) -> None:
        selected = self._normalize_setting(
            "ai_presence_voice_thread_selected_preset",
            self._setting("ai_presence_voice_thread_selected_preset"),
        )
        if selected in VOICE_THREAD_BUILTIN_PRESETS:
            preset = VOICE_THREAD_BUILTIN_PRESETS[selected]
        else:
            slug = selected.split(":", 1)[1] if ":" in selected else ""
            preset = self._voice_thread_custom_presets().get(slug)
            if preset is None:
                raise ValueError("The selected Living Voice Thread preset no longer exists.")
        settings = dict(preset.get("settings") or {})
        for key, value in settings.items():
            if key in VOICE_THREAD_CUSTOM_CAPTURE_KEYS:
                self._update_runtime_config(
                    key, self._normalize_setting(key, value)
                )
        self._update_runtime_config(
            "ai_presence_voice_thread_selected_preset", selected
        )
        self._apply_runtime_config()
        self._set_status(
            f"Living Voice Thread preset loaded: {preset.get('label') or selected}."
        )

    def _save_voice_thread_preset(self, payload) -> None:
        label = str(payload or "").strip()[:64]
        slug = _voice_thread_preset_slug(label)
        if not label or not slug:
            raise ValueError("Enter a name for the Living Voice Thread preset.")
        presets = self._voice_thread_custom_presets()
        presets[slug] = {
            "label": label,
            "settings": {
                key: self._normalize_setting(key, self._setting(key))
                for key in VOICE_THREAD_CUSTOM_CAPTURE_KEYS
            },
        }
        presets = dict(list(presets.items())[-24:])
        selected = f"custom:{slug}"
        self._update_runtime_config(
            "ai_presence_voice_thread_custom_presets", presets
        )
        self._update_runtime_config(
            "ai_presence_voice_thread_selected_preset", selected
        )
        self._set_status(f"Living Voice Thread preset saved: {label}.")

    def _delete_voice_thread_preset(self) -> None:
        selected = self._normalize_setting(
            "ai_presence_voice_thread_selected_preset",
            self._setting("ai_presence_voice_thread_selected_preset"),
        )
        if not selected.startswith("custom:"):
            raise ValueError("Built-in Living Voice Thread presets cannot be deleted.")
        slug = selected.split(":", 1)[1]
        presets = self._voice_thread_custom_presets()
        removed = presets.pop(slug, None)
        if removed is None:
            raise ValueError("The selected Living Voice Thread preset no longer exists.")
        self._update_runtime_config(
            "ai_presence_voice_thread_custom_presets", presets
        )
        self._update_runtime_config(
            "ai_presence_voice_thread_selected_preset", "balanced"
        )
        self._set_status(
            f"Living Voice Thread preset deleted: {removed.get('label') or slug}."
        )

    def native_action(self, action, payload=None):
        action_name = str(action or "").strip().lower()
        if action_name == "preview_fullscreen":
            self._show_fullscreen_preview(persist=False)
        elif action_name == "open_floating":
            self._show_floating(persist=False)
        elif action_name == "show_presence":
            self._show_ai_presence()
        elif action_name == "activate_silk_threads":
            self._activate_silk_threads()
        elif action_name == "reset_floating_position":
            self._reset_floating_position(persist=False)
        elif action_name == "load_voice_thread_preset":
            self._load_voice_thread_preset()
        elif action_name == "save_voice_thread_preset":
            self._save_voice_thread_preset(payload)
        elif action_name == "delete_voice_thread_preset":
            self._delete_voice_thread_preset()
        elif action_name == "reset_voice_thread_placement":
            self._update_runtime_config("ai_presence_voice_thread_position_x", 0.5)
            self._update_runtime_config("ai_presence_voice_thread_position_y", 0.5)
            self._apply_runtime_config()
            self._set_status("Living Voice Thread placement centered.")
        else:
            raise KeyError(f"Unknown AI Presence action: {action_name}")
        return self.native_snapshot()

    def _show_ai_presence(self) -> None:
        if self._preview_restore_settings is not None:
            self._update_runtime_config("ai_presence_display_mode", "fullscreen")
            self._update_runtime_config("ai_presence_fullscreen", True)
        self._preview_restore_settings = None
        self._update_runtime_config("ai_presence_enabled", True)
        mode = str(self._setting("ai_presence_display_mode") or "off").strip().lower()
        if mode == "off":
            self._update_runtime_config("ai_presence_display_mode", "floating")
        self._apply_runtime_config()
        self._set_status("AI Presence is active and visible.")

    def _activate_silk_threads(self) -> None:
        """Enable the recommended Living Voice Thread setup without resetting tuning."""

        if self._preview_restore_settings is not None:
            self._update_runtime_config("ai_presence_display_mode", "fullscreen")
            self._update_runtime_config("ai_presence_fullscreen", True)
        self._preview_restore_settings = None
        self._update_runtime_config("ai_presence_enabled", True)
        mode = str(self._setting("ai_presence_display_mode") or "off").strip().lower()
        if mode == "off":
            self._update_runtime_config("ai_presence_display_mode", "floating")
        self._update_runtime_config("ai_presence_visual_style", "living_voice_thread")
        self._update_runtime_config("ai_presence_render_backend", "gpu_native")
        self._update_runtime_config("ai_presence_voice_thread_variation", "silk_ribbon")
        self._update_runtime_config(
            "ai_presence_voice_thread_voice_colors_enabled", True
        )
        self._apply_runtime_config()
        self._set_status(
            "Silk Threads is active. Open the Silk Threads page to tune or save presets."
        )

    def _show_fullscreen_preview(self, *, persist=True):
        self._preview_generation += 1
        generation = self._preview_generation
        if self._preview_restore_settings is None:
            self._preview_restore_settings = {
                key: self._setting(key) for key in (
                    "ai_presence_enabled", "ai_presence_display_mode", "ai_presence_fullscreen"
                )
            }
        self.refresh_from_runtime()
        self._apply_runtime_config()
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_ai_state("speaking")
            visual_presence_runtime.set_audio_level(0.58)
            QtCore.QTimer.singleShot(7000, lambda: self._finish_preview(generation))
            self._set_status("Fullscreen preview running.")
        except Exception as exc:
            self._set_status(f"AI Presence preview failed: {exc}")

    def _show_floating(self, *, persist=True):
        self._preview_restore_settings = None
        self._update_runtime_config("ai_presence_enabled", True)
        self._update_runtime_config("ai_presence_display_mode", "floating")
        self.refresh_from_runtime()
        self._apply_runtime_config()
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_ai_state("idle")
            visual_presence_runtime.set_audio_level(0.0)
            self._set_status("Floating AI Presence window opened.")
        except Exception as exc:
            self._set_status(f"Floating AI Presence failed: {exc}")
        if persist:
            self._save_session()

    def _reset_floating_position(self, *, persist=True):
        self._preview_restore_settings = None
        self._update_runtime_config("ai_presence_enabled", True)
        self._update_runtime_config("ai_presence_display_mode", "floating")
        self.refresh_from_runtime()
        self._apply_runtime_config()
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.reset_ai_presence_floating_position()
            self._set_status("AI Presence floating window centered.")
        except Exception as exc:
            self._set_status(f"AI Presence floating position reset failed: {exc}")
        if persist:
            self._save_session()

    def _show_companion_orb(self):
        self._update_runtime_config("companion_orb_enabled", True)
        if str(self._runtime_config().get("companion_orb_display_mode", "off") or "off") == "off":
            self._update_runtime_config("companion_orb_display_mode", "docked")
        self.refresh_from_runtime()
        self._apply_runtime_config()
        self._set_status("Companion Orb enabled.")
        self._save_session()

    def _toggle_companion_orb_edit_mode(self):
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_companion_orb_edit_mode(True)
            self._set_status("Companion Orb edit mode enabled. Drag with left mouse button, then press Esc or toggle off.")
        except Exception as exc:
            self._set_status(f"Companion Orb edit mode failed: {exc}")

    def _toggle_companion_orb_placement_mode(self):
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_companion_orb_placement_mode(True)
            self._set_status("Companion Orb placement mode enabled. Hold right mouse button over a window, move, then release.")
        except Exception as exc:
            self._set_status(f"Companion Orb placement mode failed: {exc}")

    def _clear_companion_orb_target(self):
        self._update_runtime_config("companion_orb_target_info", {})
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.clear_companion_orb_target()
        except Exception:
            pass
        self._set_status("Companion Orb sensory target cleared.")
        self._save_session()

    def _reset_companion_orb_position(self):
        self._update_runtime_config("companion_orb_custom_position", [])
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.reset_companion_orb_position()
        except Exception:
            pass
        self._set_status("Companion Orb position reset.")
        self._save_session()

    def _finish_preview(self, generation=None):
        if generation is not None and generation != self._preview_generation:
            return
        self._preview_generation += 1
        previous = self._preview_restore_settings
        self._preview_restore_settings = None
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_audio_level(0.0)
            visual_presence_runtime.set_ai_state("idle")
        except Exception:
            pass
        if previous is not None:
            self._apply_runtime_config()

    def refresh_from_runtime(self):
        self._apply_runtime_config()

    def _save_session(self):
        session = getattr(
            getattr(self.context, "capabilities", None),
            "shell_session",
            None,
        )
        notifier = getattr(session, "notify_settings_changed", None)
        if callable(notifier):
            try:
                notifier()
            except Exception:
                pass

    def _set_status(self, text):
        self._native_status = str(text or "")
        label = getattr(self, "status_label", None)
        if label is not None:
            label.setText(str(text or ""))

    def export_session_state(self):
        config = self._runtime_config()
        return {key: config.get(key) for key in self.SESSION_KEYS if key in config}

    def import_session_state(self, session):
        payload = dict(session or {})
        if any(key in payload for key in (
            "ai_presence_enabled", "ai_presence_display_mode", "ai_presence_fullscreen"
        )):
            self._preview_restore_settings = None
        # Old sessions own legacy opacity values, so stale explicit overrides
        # must not mask them. Sparse floating-only imports keep fullscreen.
        if "ai_presence_overlay_opacity" in payload:
            for key in ("ai_presence_fullscreen_opacity", "ai_presence_floating_window_opacity"):
                if key not in payload:
                    self._update_runtime_config(key, None)
        elif "ai_presence_floating_opacity" in payload and "ai_presence_floating_window_opacity" not in payload:
            self._update_runtime_config("ai_presence_floating_window_opacity", None)
        for key in self.SESSION_KEYS:
            if key in payload:
                self._update_runtime_config(key, self._normalize_setting(key, payload.get(key)))
        self.refresh_from_runtime()
        self._apply_runtime_config()
        return None

    def shutdown(self):
        if self._preview_restore_settings is not None:
            self._finish_preview()
        else:
            self._preview_generation += 1
        self._widgets.clear()
        self._controls.clear()
        return None
