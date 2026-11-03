"""Qt property bridge consumed by the AI Presence QML overlay."""

from __future__ import annotations

import math

from PySide6 import QtCore

from .audio_reactive_meter import clamp_level

try:
    from addons.ai_presence_mode.mood_color_resolver import resolve_mood_colors
except Exception:  # pragma: no cover - addon resolver should be available, but keep runtime optional.
    def resolve_mood_colors(_value):
        return {
            "moodName": "neutral",
            "primaryColor": "#38bdf8",
            "secondaryColor": "#22d3ee",
            "accentColor": "#a78bfa",
            "glowColor": "#67e8f9",
            "backgroundColor": "#030712",
            "pulseSpeedMultiplier": 1.0,
            "glowIntensityMultiplier": 1.0,
            "particleIntensityMultiplier": 1.0,
        }


def _float_setting(settings, key, default, minimum, maximum) -> float:
    try:
        value = float((settings or {}).get(key, default))
    except Exception:
        value = float(default)
    return max(float(minimum), min(float(maximum), value))


def _opacity_override(settings, key):
    raw = (settings or {}).get(key)
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, value)) if math.isfinite(value) else None


def resolve_presence_opacities(settings) -> tuple[float, float]:
    """Resolve independent overrides while retaining legacy effective opacity."""
    values = settings or {}
    legacy_full = _float_setting(values, "ai_presence_overlay_opacity", 0.72, 0.10, 1.0)
    legacy_floating = legacy_full * _float_setting(
        values, "ai_presence_floating_opacity", 0.92, 0.35, 1.0
    )
    full = _opacity_override(values, "ai_presence_fullscreen_opacity")
    floating = _opacity_override(values, "ai_presence_floating_window_opacity")
    return (legacy_full if full is None else full,
            legacy_floating if floating is None else floating)


def _int_setting(settings, key, default, minimum, maximum) -> int:
    try:
        value = int((settings or {}).get(key, default))
    except Exception:
        value = int(default)
    return max(int(minimum), min(int(maximum), value))


def _ambient_noise_gate_setting(settings) -> float:
    """Read the literal gate while migrating the former 0..2 preset scale."""

    try:
        configured = max(
            0.0,
            float((settings or {}).get(
                "ai_presence_voice_thread_ambient_noise_gate", 0.04
            )),
        )
    except Exception:
        configured = 0.04
    if 0.25 < configured <= 2.0:
        return min(0.10, configured * 0.04)
    return min(0.25, configured)


def _hex_color_setting(settings, key, default) -> str:
    value = str((settings or {}).get(key, default) or default).strip()
    if not value.startswith("#"):
        value = "#" + value
    if len(value) == 4:
        value = "#" + "".join(channel * 2 for channel in value[1:])
    if len(value) != 7:
        return str(default)
    try:
        int(value[1:], 16)
    except ValueError:
        return str(default)
    return value.lower()


def _normalized_spectrum(values, count: int = 12) -> list[float]:
    try:
        source = list(values or ())
    except Exception:
        source = []
    result: list[float] = []
    for index in range(max(1, int(count))):
        try:
            value = float(source[index])
        except (IndexError, TypeError, ValueError):
            value = 0.0
        result.append(clamp_level(value) if math.isfinite(value) else 0.0)
    return result


class VisualPresenceBridge(QtCore.QObject):
    ai_state_changed = QtCore.Signal(str)
    audio_level_changed = QtCore.Signal(float)
    peak_level_changed = QtCore.Signal(float)
    music_level_changed = QtCore.Signal(float)
    music_peak_changed = QtCore.Signal(float)
    music_spectrum_changed = QtCore.Signal()
    voice_spectrum_changed = QtCore.Signal()
    spectral_flux_changed = QtCore.Signal(float)
    spectral_centroid_changed = QtCore.Signal(float)
    user_voice_analysis_changed = QtCore.Signal()
    enabled_changed = QtCore.Signal(bool)
    display_mode_changed = QtCore.Signal(str)
    visual_style_changed = QtCore.Signal(str)
    settings_changed = QtCore.Signal()
    live_setting_requested = QtCore.Signal(str, object)
    floating_thread_drag_started = QtCore.Signal(float, float)
    floating_thread_drag_finished = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_state = "idle"
        self._audio_level = 0.0
        self._peak_level = 0.0
        self._music_level = 0.0
        self._music_peak = 0.0
        self._music_spectrum = [0.0] * 12
        self._voice_spectrum = [0.0] * 12
        self._spectral_flux = 0.0
        self._spectral_centroid = 0.0
        self._user_voice_level = 0.0
        self._user_voice_peak = 0.0
        self._user_voice_spectrum = [0.0] * 12
        self._user_spectral_flux = 0.0
        self._user_spectral_centroid = 0.0
        self._user_voice_active = False
        self._enabled = False
        self._display_mode = "fullscreen"
        self._visual_style = "breathing_orb"
        self._render_backend = "gpu_native"
        self._fullscreen = True
        self._overlay_opacity = 0.72
        self._floating_opacity = 0.72 * 0.92
        self._floating_content_opacity = 0.72
        self._floating_always_on_top = True
        self._remember_floating_geometry = True
        self._click_through_default = False
        self._right_drag_move_enabled = False
        self._transparent_background = False
        self._pulse_intensity = 0.55
        self._speaking_reactivity = 0.85
        self._voice_thread_variation = "silk_ribbon"
        self._voice_thread_palette = "persona_mood"
        self._voice_thread_peak_emphasis = 0.60
        self._voice_thread_glow_radius = 1.0
        self._voice_thread_reflection_enabled = True
        self._voice_thread_reflection_distance = 0.25
        self._voice_thread_strand_multiplier = 1
        self._voice_thread_motion_style = "organic_drift"
        self._voice_thread_audio_reactivity = 1.0
        self._voice_thread_motion_scale = 1.0
        self._voice_thread_idle_motion = 0.16
        self._voice_thread_animation_speed = 1.0
        self._voice_thread_response_smoothing = 0.58
        self._voice_thread_spectrum_smoothing = 0.45
        self._voice_thread_spectrum_scale = 1.0
        self._voice_thread_glow_intensity = 1.0
        self._voice_thread_flux_strength = 1.0
        self._voice_thread_fiber_spread = 1.0
        self._voice_thread_bendiness = 1.0
        self._voice_thread_organic_variation = 1.0
        self._voice_thread_phrase_motion = 1.0
        self._voice_thread_gesture_intensity = 1.0
        self._voice_thread_motion_memory = 0.65
        self._voice_thread_accent_sensitivity = 0.55
        self._voice_thread_ambient_reaction_target = "shape_glow"
        self._voice_thread_ambient_smoothing = 0.72
        self._voice_thread_ambient_noise_gate = 0.04
        self._voice_thread_ambient_quiet_detail = 1.40
        self._voice_thread_ambient_transient_punch = 1.60
        self._voice_thread_ambient_attack_ms = 35
        self._voice_thread_ambient_release_ms = 260
        self._voice_thread_ambient_mix = 1.45
        self._voice_thread_ambient_link_main_controls = True
        self._voice_thread_ambient_fiber_spread_enabled = True
        self._voice_thread_ambient_shape_strength = 1.80
        self._voice_thread_ambient_travel_strength = 1.35
        self._voice_thread_ambient_glow_strength = 1.65
        self._voice_thread_ambient_fiber_strength = 1.25
        self._voice_thread_ambient_color_strength = 1.50
        self._voice_thread_audio_colors_enabled = True
        self._voice_thread_voice_colors_enabled = True
        self._voice_thread_desktop_colors_enabled = True
        self._voice_thread_color_vividness = 1.0
        self._voice_thread_color_bass_influence = 1.0
        self._voice_thread_color_mid_influence = 1.0
        self._voice_thread_color_high_influence = 1.0
        self._voice_thread_color_smoothing = 0.65
        self._voice_thread_ambient_motion_ceiling = 2.20
        self._voice_thread_ambient_bass_bend = 0.55
        self._voice_thread_ambient_mid_ripple = 0.38
        self._voice_thread_ambient_high_shimmer = 0.42
        self._voice_thread_mouse_physics_enabled = False
        self._voice_thread_physics_feel = "natural"
        self._voice_thread_physics_slack = 1.0
        self._voice_thread_interaction_area = 1.6
        self._voice_thread_gravity = 1.2
        self._voice_thread_retension_time = 0.65
        self._voice_thread_show_placement_guide = True
        self._voice_thread_size = 1.0
        self._voice_thread_horizontal_span = 1.0
        self._voice_thread_position_x = 0.5
        self._voice_thread_position_y = 0.5
        self._voice_thread_frame_rate = 30
        self._voice_thread_primary_color = "#22d3ee"
        self._voice_thread_accent_color = "#a78bfa"
        self._voice_thread_highlight_color = "#ecfeff"
        self._node_density = 32
        self._particle_density = 28
        self._reduced_effects = False
        self._shaders_enabled = True
        self._particles_enabled = True
        self._space_closes_fullscreen = True
        self._music_reactivity_enabled = False
        self._music_reactivity = 2.80
        self._microphone_reactivity_enabled = False
        self._presence_mood = "neutral"
        self._mood_colors_enabled = True
        self._mood_color_mode = "automatic"
        self._manual_mood = "neutral"
        self._mood_color_intensity = 0.85
        self._story_mood_override = True
        self._persona_mood_override = True
        self._primary_color = "#38bdf8"
        self._secondary_color = "#22d3ee"
        self._accent_color = "#a78bfa"
        self._glow_color = "#67e8f9"
        self._background_color = "#030712"
        self._mood_pulse_multiplier = 1.0
        self._mood_glow_multiplier = 1.0
        self._mood_particle_multiplier = 1.0
        self._glow_strength = 1.0
        self._animation_speed = 1.0
        self._idle_motion_strength = 0.16
        self._primary_color_strength = 1.0
        self._secondary_color_strength = 1.0
        self._background_darkness = 1.0
        self._halo_thickness = 1.0
        self._waveform_strength = 1.0
        self._ring_expansion_speed = 1.0
        self._blur_softness = 0.35
        self._line_brightness = 1.0
        self._live_controls_visible = False
        self._neural_face_enabled = False
        self._neural_face_variant = "auto"
        self._neural_face_size = 1.0
        self._neural_face_opacity = 0.0
        self._neural_face_animation_intensity = 0.0
        self._neural_face_lipsync_strength = 0.0
        self._neural_face_eye_movement_enabled = False
        self._neural_face_blink_enabled = False
        self._neural_face_glow_enabled = False
        self._neural_face_emotion_enabled = False
        self._neural_face_use_tts_emotion = False
        self._neural_face_audio_lipsync_enabled = False
        self._neural_face_reduced_animation = False
        self._female_neural_face_enabled = False
        self._female_reference_nodes = False
        self._female_show_wire_nodes = False
        self._female_show_wire_lines = False
        self._female_node_glow_enabled = False
        self._female_wire_pulse_enabled = False
        self._female_depth_enabled = False

    @QtCore.Property(str, notify=ai_state_changed)
    def aiState(self):
        return self._ai_state

    @QtCore.Property(float, notify=audio_level_changed)
    def audioLevel(self):
        return self._audio_level

    @QtCore.Property(float, notify=peak_level_changed)
    def peakLevel(self):
        return self._peak_level

    @QtCore.Property(float, notify=music_level_changed)
    def musicLevel(self):
        return self._music_level

    @QtCore.Property(float, notify=music_peak_changed)
    def musicPeak(self):
        return self._music_peak

    @QtCore.Property("QVariantList", notify=music_spectrum_changed)
    def musicSpectrum(self):
        return list(self._music_spectrum)

    @QtCore.Property("QVariantList", notify=voice_spectrum_changed)
    def voiceSpectrum(self):
        return list(self._voice_spectrum)

    @QtCore.Property(float, notify=spectral_flux_changed)
    def spectralFlux(self):
        return self._spectral_flux

    @QtCore.Property(float, notify=spectral_centroid_changed)
    def spectralCentroid(self):
        return self._spectral_centroid

    @QtCore.Property(float, notify=user_voice_analysis_changed)
    def userVoiceLevel(self):
        return self._user_voice_level

    @QtCore.Property(float, notify=user_voice_analysis_changed)
    def userVoicePeak(self):
        return self._user_voice_peak

    @QtCore.Property("QVariantList", notify=user_voice_analysis_changed)
    def userVoiceSpectrum(self):
        return list(self._user_voice_spectrum)

    @QtCore.Property(float, notify=user_voice_analysis_changed)
    def userSpectralFlux(self):
        return self._user_spectral_flux

    @QtCore.Property(float, notify=user_voice_analysis_changed)
    def userSpectralCentroid(self):
        return self._user_spectral_centroid

    @QtCore.Property(bool, notify=user_voice_analysis_changed)
    def userVoiceActive(self):
        return self._user_voice_active

    @QtCore.Property(bool, notify=settings_changed)
    def microphoneReactionEnabled(self):
        return self._microphone_reactivity_enabled

    @QtCore.Property(bool, notify=enabled_changed)
    def enabled(self):
        return self._enabled

    @QtCore.Property(str, notify=display_mode_changed)
    def displayMode(self):
        return self._display_mode

    @QtCore.Property(str, notify=visual_style_changed)
    def visualStyle(self):
        return self._visual_style

    @QtCore.Property(str, notify=settings_changed)
    def renderBackend(self):
        return self._render_backend

    @QtCore.Property(bool, notify=settings_changed)
    def fullscreen(self):
        return self._fullscreen

    @QtCore.Property(float, notify=settings_changed)
    def overlayOpacity(self):
        return self._overlay_opacity

    @QtCore.Property(float, notify=settings_changed)
    def floatingOpacity(self):
        return self._floating_opacity

    @QtCore.Property(float, notify=settings_changed)
    def floatingContentOpacity(self):
        return self._floating_content_opacity

    @QtCore.Property(bool, notify=settings_changed)
    def floatingAlwaysOnTop(self):
        return self._floating_always_on_top

    @QtCore.Property(bool, notify=settings_changed)
    def rememberFloatingGeometry(self):
        return self._remember_floating_geometry

    @QtCore.Property(bool, notify=settings_changed)
    def clickThroughDefault(self):
        return self._click_through_default

    @QtCore.Property(bool, notify=settings_changed)
    def rightDragMoveEnabled(self):
        return self._right_drag_move_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def transparentBackground(self):
        return self._transparent_background

    @QtCore.Property(float, notify=settings_changed)
    def pulseIntensity(self):
        return self._pulse_intensity

    @QtCore.Property(float, notify=settings_changed)
    def speakingReactivity(self):
        return self._speaking_reactivity

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadVariation(self):
        return self._voice_thread_variation

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadPalette(self):
        return self._voice_thread_palette

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadPeakEmphasis(self):
        return self._voice_thread_peak_emphasis

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadGlowRadius(self):
        return self._voice_thread_glow_radius

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadReflectionEnabled(self):
        return self._voice_thread_reflection_enabled

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadReflectionDistance(self):
        return self._voice_thread_reflection_distance

    @QtCore.Property(int, notify=settings_changed)
    def voiceThreadStrandMultiplier(self):
        return self._voice_thread_strand_multiplier

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadMotionStyle(self):
        return self._voice_thread_motion_style

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAudioReactivity(self):
        return self._voice_thread_audio_reactivity

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadMotionScale(self):
        return self._voice_thread_motion_scale

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadIdleMotion(self):
        return self._voice_thread_idle_motion

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAnimationSpeed(self):
        return self._voice_thread_animation_speed

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadResponseSmoothing(self):
        return self._voice_thread_response_smoothing

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadSpectrumSmoothing(self):
        return self._voice_thread_spectrum_smoothing

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadSpectrumScale(self):
        return self._voice_thread_spectrum_scale

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadGlowIntensity(self):
        return self._voice_thread_glow_intensity

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadFluxStrength(self):
        return self._voice_thread_flux_strength

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadFiberSpread(self):
        return self._voice_thread_fiber_spread

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadBendiness(self):
        return self._voice_thread_bendiness

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadOrganicVariation(self):
        return self._voice_thread_organic_variation

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadPhraseMotion(self):
        return self._voice_thread_phrase_motion

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadGestureIntensity(self):
        return self._voice_thread_gesture_intensity

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadMotionMemory(self):
        return self._voice_thread_motion_memory

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAccentSensitivity(self):
        return self._voice_thread_accent_sensitivity

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadAmbientReactionTarget(self):
        return self._voice_thread_ambient_reaction_target

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientSmoothing(self):
        return self._voice_thread_ambient_smoothing

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientNoiseGate(self):
        return self._voice_thread_ambient_noise_gate

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientQuietDetail(self):
        return self._voice_thread_ambient_quiet_detail

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientTransientPunch(self):
        return self._voice_thread_ambient_transient_punch

    @QtCore.Property(int, notify=settings_changed)
    def voiceThreadAmbientAttackMs(self):
        return self._voice_thread_ambient_attack_ms

    @QtCore.Property(int, notify=settings_changed)
    def voiceThreadAmbientReleaseMs(self):
        return self._voice_thread_ambient_release_ms

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientMix(self):
        return self._voice_thread_ambient_mix

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadAmbientLinkMainControls(self):
        return self._voice_thread_ambient_link_main_controls

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadAmbientFiberSpreadEnabled(self):
        return self._voice_thread_ambient_fiber_spread_enabled

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientShapeStrength(self):
        return self._voice_thread_ambient_shape_strength

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientTravelStrength(self):
        return self._voice_thread_ambient_travel_strength

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientGlowStrength(self):
        return self._voice_thread_ambient_glow_strength

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientFiberStrength(self):
        return self._voice_thread_ambient_fiber_strength

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientColorStrength(self):
        return self._voice_thread_ambient_color_strength

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadAudioColorsEnabled(self):
        return self._voice_thread_audio_colors_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadVoiceColorsEnabled(self):
        return self._voice_thread_voice_colors_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadDesktopColorsEnabled(self):
        return self._voice_thread_desktop_colors_enabled

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadColorVividness(self):
        return self._voice_thread_color_vividness

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadColorBassInfluence(self):
        return self._voice_thread_color_bass_influence

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadColorMidInfluence(self):
        return self._voice_thread_color_mid_influence

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadColorHighInfluence(self):
        return self._voice_thread_color_high_influence

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadColorSmoothing(self):
        return self._voice_thread_color_smoothing

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientMotionCeiling(self):
        return self._voice_thread_ambient_motion_ceiling

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientBassBend(self):
        return self._voice_thread_ambient_bass_bend

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientMidRipple(self):
        return self._voice_thread_ambient_mid_ripple

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadAmbientHighShimmer(self):
        return self._voice_thread_ambient_high_shimmer

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadMousePhysicsEnabled(self):
        return self._voice_thread_mouse_physics_enabled

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadPhysicsFeel(self):
        return self._voice_thread_physics_feel

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadPhysicsSlack(self):
        return self._voice_thread_physics_slack

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadInteractionArea(self):
        return self._voice_thread_interaction_area

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadGravity(self):
        return self._voice_thread_gravity

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadRetensionTime(self):
        return self._voice_thread_retension_time

    @QtCore.Property(bool, notify=settings_changed)
    def voiceThreadShowPlacementGuide(self):
        return self._voice_thread_show_placement_guide

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadSize(self):
        return self._voice_thread_size

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadHorizontalSpan(self):
        return self._voice_thread_horizontal_span

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadPositionX(self):
        return self._voice_thread_position_x

    @QtCore.Property(float, notify=settings_changed)
    def voiceThreadPositionY(self):
        return self._voice_thread_position_y

    @QtCore.Property(int, notify=settings_changed)
    def voiceThreadFrameRate(self):
        return self._voice_thread_frame_rate

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadPrimaryColor(self):
        return self._voice_thread_primary_color

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadAccentColor(self):
        return self._voice_thread_accent_color

    @QtCore.Property(str, notify=settings_changed)
    def voiceThreadHighlightColor(self):
        return self._voice_thread_highlight_color

    @QtCore.Property(int, notify=settings_changed)
    def nodeDensity(self):
        return self._node_density

    @QtCore.Property(int, notify=settings_changed)
    def particleDensity(self):
        return self._particle_density

    @QtCore.Property(bool, notify=settings_changed)
    def reducedEffects(self):
        return self._reduced_effects

    @QtCore.Property(bool, notify=settings_changed)
    def shadersEnabled(self):
        return self._shaders_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def particlesEnabled(self):
        return self._particles_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def spaceClosesFullscreen(self):
        return self._space_closes_fullscreen

    @QtCore.Property(bool, notify=settings_changed)
    def musicReactivityEnabled(self):
        return self._music_reactivity_enabled

    @QtCore.Property(float, notify=settings_changed)
    def musicReactivity(self):
        return self._music_reactivity

    @QtCore.Property(str, notify=settings_changed)
    def moodName(self):
        return self._presence_mood

    @QtCore.Property(bool, notify=settings_changed)
    def moodColorsEnabled(self):
        return self._mood_colors_enabled and self._mood_color_mode != "off"

    @QtCore.Property(str, notify=settings_changed)
    def moodColorMode(self):
        return self._mood_color_mode

    @QtCore.Property(str, notify=settings_changed)
    def primaryColor(self):
        return self._primary_color

    @QtCore.Property(str, notify=settings_changed)
    def secondaryColor(self):
        return self._secondary_color

    @QtCore.Property(str, notify=settings_changed)
    def accentColor(self):
        return self._accent_color

    @QtCore.Property(str, notify=settings_changed)
    def glowColor(self):
        return self._glow_color

    @QtCore.Property(str, notify=settings_changed)
    def backgroundColor(self):
        return self._background_color

    @QtCore.Property(float, notify=settings_changed)
    def moodPulseMultiplier(self):
        return self._mood_pulse_multiplier

    @QtCore.Property(float, notify=settings_changed)
    def moodGlowMultiplier(self):
        return self._mood_glow_multiplier

    @QtCore.Property(float, notify=settings_changed)
    def moodParticleMultiplier(self):
        return self._mood_particle_multiplier

    @QtCore.Property(float, notify=settings_changed)
    def moodColorIntensity(self):
        return self._mood_color_intensity

    @QtCore.Property(float, notify=settings_changed)
    def glowStrength(self):
        return self._glow_strength

    @QtCore.Property(float, notify=settings_changed)
    def animationSpeed(self):
        return self._animation_speed

    @QtCore.Property(float, notify=settings_changed)
    def idleMotionStrength(self):
        return self._idle_motion_strength

    @QtCore.Property(float, notify=settings_changed)
    def primaryColorStrength(self):
        return self._primary_color_strength

    @QtCore.Property(float, notify=settings_changed)
    def secondaryColorStrength(self):
        return self._secondary_color_strength

    @QtCore.Property(float, notify=settings_changed)
    def backgroundDarkness(self):
        return self._background_darkness

    @QtCore.Property(float, notify=settings_changed)
    def haloThickness(self):
        return self._halo_thickness

    @QtCore.Property(float, notify=settings_changed)
    def waveformStrength(self):
        return self._waveform_strength

    @QtCore.Property(float, notify=settings_changed)
    def ringExpansionSpeed(self):
        return self._ring_expansion_speed

    @QtCore.Property(float, notify=settings_changed)
    def blurSoftness(self):
        return self._blur_softness

    @QtCore.Property(float, notify=settings_changed)
    def lineBrightness(self):
        return self._line_brightness

    @QtCore.Property(bool, notify=settings_changed)
    def liveControlsVisible(self):
        return self._live_controls_visible

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceEnabled(self):
        return self._neural_face_enabled

    @QtCore.Property(str, notify=settings_changed)
    def neuralFaceVariant(self):
        return self._neural_face_variant

    @QtCore.Property(float, notify=settings_changed)
    def neuralFaceSize(self):
        return self._neural_face_size

    @QtCore.Property(float, notify=settings_changed)
    def neuralFaceOpacity(self):
        return self._neural_face_opacity

    @QtCore.Property(float, notify=settings_changed)
    def neuralFaceAnimationIntensity(self):
        return self._neural_face_animation_intensity

    @QtCore.Property(float, notify=settings_changed)
    def neuralFaceLipSyncStrength(self):
        return self._neural_face_lipsync_strength

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceEyeMovementEnabled(self):
        return self._neural_face_eye_movement_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceBlinkEnabled(self):
        return self._neural_face_blink_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceGlowEnabled(self):
        return self._neural_face_glow_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceEmotionEnabled(self):
        return self._neural_face_emotion_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceUseTtsEmotion(self):
        return self._neural_face_use_tts_emotion

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceAudioLipSyncEnabled(self):
        return self._neural_face_audio_lipsync_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def neuralFaceReducedAnimation(self):
        return self._neural_face_reduced_animation

    @QtCore.Property(bool, notify=settings_changed)
    def femaleNeuralFaceEnabled(self):
        return self._female_neural_face_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def femaleReferenceNodes(self):
        return self._female_reference_nodes

    @QtCore.Property(bool, notify=settings_changed)
    def femaleShowWireNodes(self):
        return self._female_show_wire_nodes

    @QtCore.Property(bool, notify=settings_changed)
    def femaleShowWireLines(self):
        return self._female_show_wire_lines

    @QtCore.Property(bool, notify=settings_changed)
    def femaleNodeGlowEnabled(self):
        return self._female_node_glow_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def femaleWirePulseEnabled(self):
        return self._female_wire_pulse_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def femaleDepthEnabled(self):
        return self._female_depth_enabled

    @QtCore.Slot(str)
    def setAiState(self, state):
        value = str(state or "idle").strip().lower()
        if value not in {"idle", "listening", "thinking", "speaking"}:
            value = "idle"
        if value == self._ai_state:
            return
        self._ai_state = value
        self.ai_state_changed.emit(self._ai_state)

    @QtCore.Slot(float)
    def setAudioLevel(self, level):
        value = clamp_level(level)
        if abs(value - self._audio_level) < 0.003:
            changed = False
        else:
            changed = True
            self._audio_level = value
            self.audio_level_changed.emit(self._audio_level)
        peak = clamp_level(max(value, self._peak_level * 0.92))
        if abs(peak - self._peak_level) >= 0.003:
            self._peak_level = peak
            self.peak_level_changed.emit(self._peak_level)
        if not changed:
            return

    @QtCore.Slot(float)
    def setMusicLevel(self, level):
        value = clamp_level(level)
        if abs(value - self._music_level) >= 0.003:
            self._music_level = value
            self.music_level_changed.emit(self._music_level)
        peak = clamp_level(max(value, self._music_peak * 0.94))
        if abs(peak - self._music_peak) >= 0.003:
            self._music_peak = peak
            self.music_peak_changed.emit(self._music_peak)

    @QtCore.Slot(object)
    def setMusicSpectrum(self, values):
        normalized = _normalized_spectrum(values)
        if max(
            (abs(left - right) for left, right in zip(normalized, self._music_spectrum)),
            default=0.0,
        ) < 0.004:
            return
        self._music_spectrum = normalized
        self.music_spectrum_changed.emit()

    @QtCore.Slot(object, float, float)
    def setVoiceAnalysis(self, values, flux, centroid):
        normalized = _normalized_spectrum(values)
        normalized_flux = clamp_level(flux)
        normalized_centroid = clamp_level(centroid)
        spectrum_changed = max(
            (
                abs(left - right)
                for left, right in zip(normalized, self._voice_spectrum)
            ),
            default=0.0,
        ) >= 0.004
        flux_changed = abs(normalized_flux - self._spectral_flux) >= 0.003
        centroid_changed = (
            abs(normalized_centroid - self._spectral_centroid) >= 0.003
        )
        if not (spectrum_changed or flux_changed or centroid_changed):
            return

        # Store the full frame before notifying any QML binding so observers
        # can never see spectrum, flux, and centroid from different frames.
        self._voice_spectrum = normalized
        self._spectral_flux = normalized_flux
        self._spectral_centroid = normalized_centroid
        if spectrum_changed:
            self.voice_spectrum_changed.emit()
        if flux_changed:
            self.spectral_flux_changed.emit(self._spectral_flux)
        if centroid_changed:
            self.spectral_centroid_changed.emit(self._spectral_centroid)

    @QtCore.Slot(object, float, float, float, float, bool)
    def setUserVoiceAnalysis(self, values, level, peak, flux, centroid, active):
        normalized = _normalized_spectrum(values)
        updated = (
            normalized != self._user_voice_spectrum
            or abs(clamp_level(level) - self._user_voice_level) >= 0.003
            or abs(clamp_level(peak) - self._user_voice_peak) >= 0.003
            or abs(clamp_level(flux) - self._user_spectral_flux) >= 0.003
            or abs(clamp_level(centroid) - self._user_spectral_centroid) >= 0.003
            or bool(active) != self._user_voice_active
        )
        if not updated:
            return
        self._user_voice_spectrum = normalized
        self._user_voice_level = clamp_level(level)
        self._user_voice_peak = clamp_level(peak)
        self._user_spectral_flux = clamp_level(flux)
        self._user_spectral_centroid = clamp_level(centroid)
        self._user_voice_active = bool(active)
        self.user_voice_analysis_changed.emit()

    @QtCore.Slot(bool)
    def setEnabled(self, enabled):
        value = bool(enabled)
        if value == self._enabled:
            return
        self._enabled = value
        self.enabled_changed.emit(self._enabled)

    @QtCore.Slot(str)
    def setPresenceMood(self, mood):
        colors = resolve_mood_colors(mood)
        value = str(colors.get("moodName") or "neutral")
        if value == self._presence_mood:
            return
        self._presence_mood = value
        self._apply_mood_colors(colors)
        self.settings_changed.emit()

    @QtCore.Slot(bool)
    def setLiveControlsVisible(self, visible):
        value = bool(visible)
        if value == self._live_controls_visible:
            return
        self._live_controls_visible = value
        self.settings_changed.emit()

    @QtCore.Slot()
    def toggleLiveControls(self):
        self.setLiveControlsVisible(not self._live_controls_visible)

    @QtCore.Slot(str, float)
    def setNumericSetting(self, key, value):
        self.live_setting_requested.emit(str(key or ""), float(value))

    @QtCore.Slot(str, bool)
    def setBooleanSetting(self, key, value):
        self.live_setting_requested.emit(str(key or ""), bool(value))

    @QtCore.Slot(float, float)
    def beginFloatingThreadDrag(self, offset_x, offset_y):
        """Start a left-drag that repositions the floating Presence window."""

        self.floating_thread_drag_started.emit(float(offset_x), float(offset_y))

    @QtCore.Slot()
    def endFloatingThreadDrag(self):
        """Finish the active floating-window filament drag, if any."""

        self.floating_thread_drag_finished.emit()

    def _apply_mood_colors(self, colors):
        self._primary_color = str(colors.get("primaryColor") or "#38bdf8")
        self._secondary_color = str(colors.get("secondaryColor") or "#22d3ee")
        self._accent_color = str(colors.get("accentColor") or "#a78bfa")
        self._glow_color = str(colors.get("glowColor") or "#67e8f9")
        self._background_color = str(colors.get("backgroundColor") or "#030712")
        self._mood_pulse_multiplier = max(0.25, min(2.0, float(colors.get("pulseSpeedMultiplier", 1.0) or 1.0)))
        self._mood_glow_multiplier = max(0.1, min(2.0, float(colors.get("glowIntensityMultiplier", 1.0) or 1.0)))
        self._mood_particle_multiplier = max(0.0, min(2.0, float(colors.get("particleIntensityMultiplier", 1.0) or 1.0)))

    def apply_settings(self, settings):
        settings = dict(settings or {})
        changed = False

        enabled = bool(settings.get("ai_presence_enabled", False))
        if enabled != self._enabled:
            self._enabled = enabled
            self.enabled_changed.emit(self._enabled)

        display_mode = str(settings.get("ai_presence_display_mode", "fullscreen") or "fullscreen").strip().lower()
        if display_mode not in {"off", "fullscreen", "floating", "both"}:
            display_mode = "fullscreen"
        if display_mode != self._display_mode:
            self._display_mode = display_mode
            self.display_mode_changed.emit(self._display_mode)

        visual_style = str(settings.get("ai_presence_visual_style", "breathing_orb") or "breathing_orb").strip().lower()
        valid_styles = {
            "classic_neural_orb",
            "breathing_orb",
            "neural_network_pulse",
            "living_voice_thread",
            "silk_drift",
            "blue_flame_smoke",
            "vector_voice_orb",
            "circular_audio_waveform",
            "halo_rings",
            "minimal_dot",
            "hologram_core",
            "signal_bloom",
            "crystal_prism",
        }
        if visual_style not in valid_styles:
            visual_style = "neural_network_pulse"
        if visual_style != self._visual_style:
            self._visual_style = visual_style
            self.visual_style_changed.emit(self._visual_style)

        render_backend = str(settings.get("ai_presence_render_backend", "gpu_native") or "gpu_native").strip().lower()
        if render_backend not in {"gpu_native", "legacy_canvas"}:
            render_backend = "gpu_native"

        fullscreen = bool(settings.get("ai_presence_fullscreen", True))
        overlay_opacity, floating_opacity = resolve_presence_opacities(settings)
        floating_content_opacity = (
            _float_setting(settings, "ai_presence_overlay_opacity", 0.72, 0.10, 1.0)
            if _opacity_override(settings, "ai_presence_floating_window_opacity") is None else 1.0
        )
        floating_always_on_top = bool(settings.get("ai_presence_floating_always_on_top", True))
        remember_floating_geometry = bool(settings.get("ai_presence_remember_floating_geometry", True))
        click_through_default = bool(settings.get("ai_presence_click_through_default", False))
        right_drag_move_enabled = bool(settings.get("ai_presence_right_drag_move_enabled", False))
        transparent_background = bool(settings.get("ai_presence_transparent_background", False))
        pulse_intensity = _float_setting(settings, "ai_presence_thinking_pulse", 0.55, 0.10, 1.0)
        speaking_reactivity = _float_setting(settings, "ai_presence_speaking_reactivity", 0.85, 0.10, 1.5)
        voice_thread_variation = str(
            settings.get("ai_presence_voice_thread_variation", "silk_ribbon") or "silk_ribbon"
        ).strip().lower()
        if voice_thread_variation not in {"silk_ribbon", "double_helix", "harmonic_threads"}:
            voice_thread_variation = "silk_ribbon"
        voice_thread_palette = str(
            settings.get("ai_presence_voice_thread_palette", "persona_mood") or "persona_mood"
        ).strip().lower()
        if voice_thread_palette not in {"persona_mood", "aurora", "electric_cyan", "ember", "ghost", "custom"}:
            voice_thread_palette = "persona_mood"
        voice_thread_peak_emphasis = _float_setting(
            settings, "ai_presence_voice_thread_peak_emphasis", 0.60, 0.0, 4.0
        )
        voice_thread_glow_radius = _float_setting(
            settings, "ai_presence_voice_thread_glow_radius", 1.0, 0.25, 4.0
        )
        voice_thread_reflection_enabled = bool(
            settings.get("ai_presence_voice_thread_reflection_enabled", True)
        )
        voice_thread_reflection_distance = _float_setting(
            settings,
            "ai_presence_voice_thread_reflection_distance",
            0.25,
            0.0,
            4.0,
        )
        voice_thread_strand_multiplier = _int_setting(
            settings,
            "ai_presence_voice_thread_strand_multiplier",
            1,
            1,
            5,
        )
        voice_thread_motion_style = str(
            settings.get(
                "ai_presence_voice_thread_motion_style", "organic_drift"
            )
            or "organic_drift"
        ).strip().lower()
        if voice_thread_motion_style not in {
            "organic_drift",
            "breathing_ribbon",
            "tidal_sweep",
            "resonant_bloom",
        }:
            voice_thread_motion_style = "organic_drift"
        voice_thread_audio_reactivity = _float_setting(
            settings, "ai_presence_voice_thread_audio_reactivity", 1.0, 0.0, 4.0
        )
        voice_thread_motion_scale = _float_setting(
            settings, "ai_presence_voice_thread_motion_scale", 1.0, 0.0, 4.0
        )
        voice_thread_idle_motion = _float_setting(
            settings, "ai_presence_voice_thread_idle_motion", 0.16, 0.0, 3.0
        )
        voice_thread_animation_speed = _float_setting(
            settings, "ai_presence_voice_thread_animation_speed", 1.0, 0.25, 3.0
        )
        voice_thread_response_smoothing = _float_setting(
            settings,
            "ai_presence_voice_thread_response_smoothing",
            0.58,
            0.0,
            2.0,
        )
        voice_thread_spectrum_smoothing = _float_setting(
            settings,
            "ai_presence_voice_thread_spectrum_smoothing",
            0.45,
            0.0,
            2.0,
        )
        voice_thread_spectrum_scale = _float_setting(
            settings, "ai_presence_voice_thread_spectrum_scale", 1.0, 0.0, 4.0
        )
        voice_thread_glow_intensity = _float_setting(
            settings, "ai_presence_voice_thread_glow_intensity", 1.0, 0.0, 4.0
        )
        voice_thread_flux_strength = _float_setting(
            settings, "ai_presence_voice_thread_flux_strength", 1.0, 0.0, 4.0
        )
        voice_thread_fiber_spread = _float_setting(
            settings, "ai_presence_voice_thread_fiber_spread", 1.0, 0.25, 4.0
        )
        voice_thread_bendiness = _float_setting(
            settings, "ai_presence_voice_thread_bendiness", 1.0, 0.0, 4.0
        )
        voice_thread_organic_variation = _float_setting(
            settings,
            "ai_presence_voice_thread_organic_variation",
            1.0,
            0.0,
            4.0,
        )
        voice_thread_phrase_motion = _float_setting(
            settings, "ai_presence_voice_thread_phrase_motion", 1.0, 0.0, 4.0
        )
        voice_thread_gesture_intensity = _float_setting(
            settings,
            "ai_presence_voice_thread_gesture_intensity",
            1.0,
            0.0,
            4.0,
        )
        voice_thread_motion_memory = _float_setting(
            settings, "ai_presence_voice_thread_motion_memory", 0.65, 0.0, 2.0
        )
        voice_thread_accent_sensitivity = _float_setting(
            settings,
            "ai_presence_voice_thread_accent_sensitivity",
            0.55,
            0.0,
            4.0,
        )
        voice_thread_ambient_reaction_target = str(
            settings.get(
                "ai_presence_voice_thread_ambient_reaction_target",
                "shape_glow",
            )
            or "shape_glow"
        ).strip().lower()
        if voice_thread_ambient_reaction_target not in {
            "glow_only",
            "shape_glow",
            "full_spectrum",
        }:
            voice_thread_ambient_reaction_target = "shape_glow"
        voice_thread_ambient_smoothing = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_smoothing",
            0.72,
            0.0,
            2.0,
        )
        voice_thread_ambient_noise_gate = _ambient_noise_gate_setting(settings)
        voice_thread_ambient_quiet_detail = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_quiet_detail",
            1.40,
            0.0,
            2.5,
        )
        voice_thread_ambient_transient_punch = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_transient_punch",
            1.60,
            0.0,
            3.0,
        )
        voice_thread_ambient_attack_ms = _int_setting(
            settings,
            "ai_presence_voice_thread_ambient_attack_ms",
            35,
            5,
            250,
        )
        voice_thread_ambient_release_ms = _int_setting(
            settings,
            "ai_presence_voice_thread_ambient_release_ms",
            260,
            40,
            700,
        )
        voice_thread_ambient_mix = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_mix",
            1.45,
            0.0,
            2.0,
        )
        voice_thread_ambient_link_main_controls = bool(
            settings.get(
                "ai_presence_voice_thread_ambient_link_main_controls", True
            )
        )
        voice_thread_ambient_fiber_spread_enabled = bool(
            settings.get(
                "ai_presence_voice_thread_ambient_fiber_spread_enabled", True
            )
        )
        voice_thread_ambient_shape_strength = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_shape_strength",
            1.80,
            0.0,
            3.0,
        )
        voice_thread_ambient_travel_strength = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_travel_strength",
            1.35,
            0.0,
            3.0,
        )
        voice_thread_ambient_glow_strength = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_glow_strength",
            1.65,
            0.0,
            3.0,
        )
        voice_thread_ambient_fiber_strength = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_fiber_strength",
            1.25,
            0.0,
            3.0,
        )
        voice_thread_ambient_color_strength = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_color_strength",
            1.50,
            0.0,
            3.0,
        )
        voice_thread_audio_colors_enabled = bool(
            settings.get("ai_presence_voice_thread_audio_colors_enabled", True)
        )
        voice_thread_voice_colors_enabled = bool(
            settings.get("ai_presence_voice_thread_voice_colors_enabled", True)
        )
        voice_thread_desktop_colors_enabled = bool(
            settings.get("ai_presence_voice_thread_desktop_colors_enabled", True)
        )
        voice_thread_color_vividness = _float_setting(
            settings,
            "ai_presence_voice_thread_color_vividness",
            1.0,
            0.0,
            4.0,
        )
        voice_thread_color_bass_influence = _float_setting(
            settings,
            "ai_presence_voice_thread_color_bass_influence",
            1.0,
            0.0,
            4.0,
        )
        voice_thread_color_mid_influence = _float_setting(
            settings,
            "ai_presence_voice_thread_color_mid_influence",
            1.0,
            0.0,
            4.0,
        )
        voice_thread_color_high_influence = _float_setting(
            settings,
            "ai_presence_voice_thread_color_high_influence",
            1.0,
            0.0,
            4.0,
        )
        voice_thread_color_smoothing = _float_setting(
            settings,
            "ai_presence_voice_thread_color_smoothing",
            0.65,
            0.0,
            2.0,
        )
        voice_thread_ambient_motion_ceiling = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_motion_ceiling",
            2.20,
            0.25,
            3.0,
        )
        voice_thread_ambient_bass_bend = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_bass_bend",
            0.55,
            0.0,
            4.0,
        )
        voice_thread_ambient_mid_ripple = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_mid_ripple",
            0.38,
            0.0,
            4.0,
        )
        voice_thread_ambient_high_shimmer = _float_setting(
            settings,
            "ai_presence_voice_thread_ambient_high_shimmer",
            0.42,
            0.0,
            4.0,
        )
        voice_thread_mouse_physics_enabled = bool(
            settings.get("ai_presence_voice_thread_mouse_physics_enabled", False)
        )
        voice_thread_physics_feel = str(
            settings.get("ai_presence_voice_thread_physics_feel", "natural")
            or "natural"
        ).strip().lower()
        if voice_thread_physics_feel not in {"natural", "silk", "cable"}:
            voice_thread_physics_feel = "natural"
        voice_thread_physics_slack = _float_setting(
            settings,
            "ai_presence_voice_thread_physics_slack",
            1.0,
            0.0,
            4.0,
        )
        voice_thread_interaction_area = _float_setting(
            settings,
            "ai_presence_voice_thread_interaction_area",
            1.6,
            1.2,
            5.0,
        )
        voice_thread_gravity = _float_setting(
            settings,
            "ai_presence_voice_thread_gravity",
            1.2,
            0.2,
            4.0,
        )
        voice_thread_retension_time = _float_setting(
            settings,
            "ai_presence_voice_thread_retension_time",
            0.65,
            0.2,
            2.0,
        )
        voice_thread_show_placement_guide = bool(
            settings.get(
                "ai_presence_voice_thread_show_placement_guide",
                True,
            )
        )
        voice_thread_size = _float_setting(
            settings,
            "ai_presence_voice_thread_size",
            1.0,
            0.25,
            6.0,
        )
        voice_thread_horizontal_span = _float_setting(
            settings,
            "ai_presence_voice_thread_horizontal_span",
            1.0,
            1.0,
            4.0,
        )
        voice_thread_position_x = _float_setting(
            settings,
            "ai_presence_voice_thread_position_x",
            0.5,
            0.0,
            1.0,
        )
        voice_thread_position_y = _float_setting(
            settings,
            "ai_presence_voice_thread_position_y",
            0.5,
            0.0,
            1.0,
        )
        voice_thread_frame_rate = _int_setting(
            settings,
            "ai_presence_voice_thread_frame_rate",
            30,
            15,
            120,
        )
        voice_thread_primary_color = _hex_color_setting(
            settings, "ai_presence_voice_thread_primary_color", "#22d3ee"
        )
        voice_thread_accent_color = _hex_color_setting(
            settings, "ai_presence_voice_thread_accent_color", "#a78bfa"
        )
        voice_thread_highlight_color = _hex_color_setting(
            settings, "ai_presence_voice_thread_highlight_color", "#ecfeff"
        )
        node_density = _int_setting(settings, "ai_presence_node_density", 32, 8, 96)
        particle_density = _int_setting(settings, "ai_presence_particle_density", 28, 0, 120)
        reduced_effects = bool(settings.get("ai_presence_reduced_effects", False))
        shaders_enabled = bool(settings.get("ai_presence_shaders_enabled", True))
        particles_enabled = bool(settings.get("ai_presence_particles_enabled", True))
        space_closes_fullscreen = bool(settings.get("ai_presence_space_closes_fullscreen", True))
        music_reactivity_enabled = bool(settings.get("ai_presence_music_reactivity_enabled", False))
        music_reactivity = _float_setting(settings, "ai_presence_music_reactivity", 2.80, 0.0, 4.0)
        microphone_reactivity_enabled = bool(
            settings.get("ai_presence_microphone_reactivity_enabled", False)
        )
        mood_colors_enabled = bool(settings.get("ai_presence_mood_colors_enabled", True))
        mood_color_mode = str(settings.get("ai_presence_mood_color_mode", "automatic") or "automatic").strip().lower()
        if mood_color_mode not in {"automatic", "manual", "off"}:
            mood_color_mode = "automatic"
        manual_mood = str(settings.get("ai_presence_manual_mood", "neutral") or "neutral").strip().lower()
        mood_color_intensity = _float_setting(settings, "ai_presence_mood_color_intensity", 0.85, 0.0, 1.0)
        story_mood_override = bool(settings.get("ai_presence_allow_story_mood_override", True))
        persona_mood_override = bool(settings.get("ai_presence_allow_persona_mood_override", True))
        glow_strength = _float_setting(settings, "ai_presence_glow_strength", 1.0, 0.0, 1.75)
        animation_speed = _float_setting(settings, "ai_presence_animation_speed", 1.0, 0.35, 1.75)
        idle_motion_strength = _float_setting(settings, "ai_presence_idle_motion_strength", 0.16, 0.0, 1.0)
        primary_color_strength = _float_setting(settings, "ai_presence_primary_color_strength", 1.0, 0.0, 1.5)
        secondary_color_strength = _float_setting(settings, "ai_presence_secondary_color_strength", 1.0, 0.0, 1.5)
        background_darkness = _float_setting(settings, "ai_presence_background_darkness", 1.0, 0.0, 1.0)
        halo_thickness = _float_setting(settings, "ai_presence_halo_thickness", 1.0, 0.35, 2.0)
        waveform_strength = _float_setting(settings, "ai_presence_waveform_strength", 1.0, 0.2, 2.0)
        ring_expansion_speed = _float_setting(settings, "ai_presence_ring_expansion_speed", 1.0, 0.25, 2.0)
        blur_softness = _float_setting(settings, "ai_presence_blur_softness", 0.35, 0.0, 1.0)
        line_brightness = _float_setting(settings, "ai_presence_line_brightness", 1.0, 0.2, 2.0)
        live_controls_visible = bool(settings.get("ai_presence_live_controls_visible", False))
        neural_face_enabled = False
        neural_face_variant = "auto"
        neural_face_size = 1.0
        neural_face_opacity = 0.0
        neural_face_animation_intensity = 0.0
        neural_face_lipsync_strength = 0.0
        neural_face_eye_movement_enabled = False
        neural_face_blink_enabled = False
        neural_face_glow_enabled = False
        neural_face_emotion_enabled = False
        neural_face_use_tts_emotion = False
        neural_face_audio_lipsync_enabled = False
        neural_face_reduced_animation = False
        female_neural_face_enabled = False
        female_reference_nodes = False
        female_show_wire_nodes = False
        female_show_wire_lines = False
        female_node_glow_enabled = False
        female_wire_pulse_enabled = False
        female_depth_enabled = False

        mood_source = manual_mood if mood_color_mode == "manual" else self._presence_mood
        colors = resolve_mood_colors(mood_source)
        resolved_mood = str(colors.get("moodName") or "neutral")

        for attr, value in [
            ("_render_backend", render_backend),
            ("_fullscreen", fullscreen),
            ("_overlay_opacity", overlay_opacity),
            ("_floating_opacity", floating_opacity),
            ("_floating_content_opacity", floating_content_opacity),
            ("_floating_always_on_top", floating_always_on_top),
            ("_remember_floating_geometry", remember_floating_geometry),
            ("_click_through_default", click_through_default),
            ("_right_drag_move_enabled", right_drag_move_enabled),
            ("_transparent_background", transparent_background),
            ("_pulse_intensity", pulse_intensity),
            ("_speaking_reactivity", speaking_reactivity),
            ("_voice_thread_variation", voice_thread_variation),
            ("_voice_thread_palette", voice_thread_palette),
            ("_voice_thread_peak_emphasis", voice_thread_peak_emphasis),
            ("_voice_thread_glow_radius", voice_thread_glow_radius),
            (
                "_voice_thread_reflection_enabled",
                voice_thread_reflection_enabled,
            ),
            (
                "_voice_thread_reflection_distance",
                voice_thread_reflection_distance,
            ),
            (
                "_voice_thread_strand_multiplier",
                voice_thread_strand_multiplier,
            ),
            ("_voice_thread_motion_style", voice_thread_motion_style),
            ("_voice_thread_audio_reactivity", voice_thread_audio_reactivity),
            ("_voice_thread_motion_scale", voice_thread_motion_scale),
            ("_voice_thread_idle_motion", voice_thread_idle_motion),
            ("_voice_thread_animation_speed", voice_thread_animation_speed),
            ("_voice_thread_response_smoothing", voice_thread_response_smoothing),
            ("_voice_thread_spectrum_smoothing", voice_thread_spectrum_smoothing),
            ("_voice_thread_spectrum_scale", voice_thread_spectrum_scale),
            ("_voice_thread_glow_intensity", voice_thread_glow_intensity),
            ("_voice_thread_flux_strength", voice_thread_flux_strength),
            ("_voice_thread_fiber_spread", voice_thread_fiber_spread),
            ("_voice_thread_bendiness", voice_thread_bendiness),
            ("_voice_thread_organic_variation", voice_thread_organic_variation),
            ("_voice_thread_phrase_motion", voice_thread_phrase_motion),
            ("_voice_thread_gesture_intensity", voice_thread_gesture_intensity),
            ("_voice_thread_motion_memory", voice_thread_motion_memory),
            ("_voice_thread_accent_sensitivity", voice_thread_accent_sensitivity),
            (
                "_voice_thread_ambient_reaction_target",
                voice_thread_ambient_reaction_target,
            ),
            ("_voice_thread_ambient_smoothing", voice_thread_ambient_smoothing),
            ("_voice_thread_ambient_noise_gate", voice_thread_ambient_noise_gate),
            ("_voice_thread_ambient_quiet_detail", voice_thread_ambient_quiet_detail),
            (
                "_voice_thread_ambient_transient_punch",
                voice_thread_ambient_transient_punch,
            ),
            ("_voice_thread_ambient_attack_ms", voice_thread_ambient_attack_ms),
            ("_voice_thread_ambient_release_ms", voice_thread_ambient_release_ms),
            ("_voice_thread_ambient_mix", voice_thread_ambient_mix),
            (
                "_voice_thread_ambient_link_main_controls",
                voice_thread_ambient_link_main_controls,
            ),
            (
                "_voice_thread_ambient_fiber_spread_enabled",
                voice_thread_ambient_fiber_spread_enabled,
            ),
            (
                "_voice_thread_ambient_shape_strength",
                voice_thread_ambient_shape_strength,
            ),
            (
                "_voice_thread_ambient_travel_strength",
                voice_thread_ambient_travel_strength,
            ),
            (
                "_voice_thread_ambient_glow_strength",
                voice_thread_ambient_glow_strength,
            ),
            (
                "_voice_thread_ambient_fiber_strength",
                voice_thread_ambient_fiber_strength,
            ),
            (
                "_voice_thread_ambient_color_strength",
                voice_thread_ambient_color_strength,
            ),
            (
                "_voice_thread_audio_colors_enabled",
                voice_thread_audio_colors_enabled,
            ),
            (
                "_voice_thread_voice_colors_enabled",
                voice_thread_voice_colors_enabled,
            ),
            (
                "_voice_thread_desktop_colors_enabled",
                voice_thread_desktop_colors_enabled,
            ),
            (
                "_voice_thread_color_vividness",
                voice_thread_color_vividness,
            ),
            (
                "_voice_thread_color_bass_influence",
                voice_thread_color_bass_influence,
            ),
            (
                "_voice_thread_color_mid_influence",
                voice_thread_color_mid_influence,
            ),
            (
                "_voice_thread_color_high_influence",
                voice_thread_color_high_influence,
            ),
            (
                "_voice_thread_color_smoothing",
                voice_thread_color_smoothing,
            ),
            (
                "_voice_thread_ambient_motion_ceiling",
                voice_thread_ambient_motion_ceiling,
            ),
            ("_voice_thread_ambient_bass_bend", voice_thread_ambient_bass_bend),
            ("_voice_thread_ambient_mid_ripple", voice_thread_ambient_mid_ripple),
            (
                "_voice_thread_ambient_high_shimmer",
                voice_thread_ambient_high_shimmer,
            ),
            (
                "_voice_thread_mouse_physics_enabled",
                voice_thread_mouse_physics_enabled,
            ),
            ("_voice_thread_physics_feel", voice_thread_physics_feel),
            ("_voice_thread_physics_slack", voice_thread_physics_slack),
            ("_voice_thread_interaction_area", voice_thread_interaction_area),
            ("_voice_thread_gravity", voice_thread_gravity),
            ("_voice_thread_retension_time", voice_thread_retension_time),
            (
                "_voice_thread_show_placement_guide",
                voice_thread_show_placement_guide,
            ),
            ("_voice_thread_size", voice_thread_size),
            ("_voice_thread_horizontal_span", voice_thread_horizontal_span),
            ("_voice_thread_position_x", voice_thread_position_x),
            ("_voice_thread_position_y", voice_thread_position_y),
            ("_voice_thread_frame_rate", voice_thread_frame_rate),
            ("_voice_thread_primary_color", voice_thread_primary_color),
            ("_voice_thread_accent_color", voice_thread_accent_color),
            ("_voice_thread_highlight_color", voice_thread_highlight_color),
            ("_node_density", node_density),
            ("_particle_density", particle_density),
            ("_reduced_effects", reduced_effects),
            ("_shaders_enabled", shaders_enabled),
            ("_particles_enabled", particles_enabled),
            ("_space_closes_fullscreen", space_closes_fullscreen),
            ("_music_reactivity_enabled", music_reactivity_enabled),
            ("_music_reactivity", music_reactivity),
            ("_microphone_reactivity_enabled", microphone_reactivity_enabled),
            ("_mood_colors_enabled", mood_colors_enabled),
            ("_mood_color_mode", mood_color_mode),
            ("_manual_mood", manual_mood),
            ("_mood_color_intensity", mood_color_intensity),
            ("_story_mood_override", story_mood_override),
            ("_persona_mood_override", persona_mood_override),
            ("_glow_strength", glow_strength),
            ("_animation_speed", animation_speed),
            ("_idle_motion_strength", idle_motion_strength),
            ("_primary_color_strength", primary_color_strength),
            ("_secondary_color_strength", secondary_color_strength),
            ("_background_darkness", background_darkness),
            ("_halo_thickness", halo_thickness),
            ("_waveform_strength", waveform_strength),
            ("_ring_expansion_speed", ring_expansion_speed),
            ("_blur_softness", blur_softness),
            ("_line_brightness", line_brightness),
            ("_live_controls_visible", live_controls_visible),
            ("_neural_face_enabled", neural_face_enabled),
            ("_neural_face_variant", neural_face_variant),
            ("_neural_face_size", neural_face_size),
            ("_neural_face_opacity", neural_face_opacity),
            ("_neural_face_animation_intensity", neural_face_animation_intensity),
            ("_neural_face_lipsync_strength", neural_face_lipsync_strength),
            ("_neural_face_eye_movement_enabled", neural_face_eye_movement_enabled),
            ("_neural_face_blink_enabled", neural_face_blink_enabled),
            ("_neural_face_glow_enabled", neural_face_glow_enabled),
            ("_neural_face_emotion_enabled", neural_face_emotion_enabled),
            ("_neural_face_use_tts_emotion", neural_face_use_tts_emotion),
            ("_neural_face_audio_lipsync_enabled", neural_face_audio_lipsync_enabled),
            ("_neural_face_reduced_animation", neural_face_reduced_animation),
            ("_female_neural_face_enabled", female_neural_face_enabled),
            ("_female_reference_nodes", female_reference_nodes),
            ("_female_show_wire_nodes", female_show_wire_nodes),
            ("_female_show_wire_lines", female_show_wire_lines),
            ("_female_node_glow_enabled", female_node_glow_enabled),
            ("_female_wire_pulse_enabled", female_wire_pulse_enabled),
            ("_female_depth_enabled", female_depth_enabled),
        ]:
            if getattr(self, attr) != value:
                setattr(self, attr, value)
                changed = True
        if mood_color_mode == "manual" and self._presence_mood != resolved_mood:
            self._presence_mood = resolved_mood
            changed = True
        previous_colors = (
            self._primary_color,
            self._secondary_color,
            self._accent_color,
            self._glow_color,
            self._background_color,
            self._mood_pulse_multiplier,
            self._mood_glow_multiplier,
            self._mood_particle_multiplier,
        )
        self._apply_mood_colors(colors)
        if previous_colors != (
            self._primary_color,
            self._secondary_color,
            self._accent_color,
            self._glow_color,
            self._background_color,
            self._mood_pulse_multiplier,
            self._mood_glow_multiplier,
            self._mood_particle_multiplier,
        ):
            changed = True
        if changed:
            self.settings_changed.emit()
