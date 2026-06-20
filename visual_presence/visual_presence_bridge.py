"""Qt property bridge consumed by the AI Presence QML overlay."""

from __future__ import annotations

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


def _int_setting(settings, key, default, minimum, maximum) -> int:
    try:
        value = int((settings or {}).get(key, default))
    except Exception:
        value = int(default)
    return max(int(minimum), min(int(maximum), value))


class VisualPresenceBridge(QtCore.QObject):
    ai_state_changed = QtCore.Signal(str)
    audio_level_changed = QtCore.Signal(float)
    peak_level_changed = QtCore.Signal(float)
    music_level_changed = QtCore.Signal(float)
    music_peak_changed = QtCore.Signal(float)
    enabled_changed = QtCore.Signal(bool)
    display_mode_changed = QtCore.Signal(str)
    visual_style_changed = QtCore.Signal(str)
    settings_changed = QtCore.Signal()
    live_setting_requested = QtCore.Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_state = "idle"
        self._audio_level = 0.0
        self._peak_level = 0.0
        self._music_level = 0.0
        self._music_peak = 0.0
        self._enabled = False
        self._display_mode = "fullscreen"
        self._visual_style = "breathing_orb"
        self._fullscreen = True
        self._overlay_opacity = 0.72
        self._floating_opacity = 0.92
        self._floating_always_on_top = True
        self._remember_floating_geometry = True
        self._click_through_default = False
        self._right_drag_move_enabled = False
        self._transparent_background = False
        self._pulse_intensity = 0.55
        self._speaking_reactivity = 0.85
        self._node_density = 32
        self._particle_density = 28
        self._reduced_effects = False
        self._shaders_enabled = True
        self._particles_enabled = True
        self._space_closes_fullscreen = True
        self._music_reactivity_enabled = False
        self._music_reactivity = 0.65
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
        self._neural_face_enabled = True
        self._neural_face_variant = "auto"
        self._neural_face_size = 1.0
        self._neural_face_opacity = 0.92
        self._neural_face_animation_intensity = 0.78
        self._neural_face_lipsync_strength = 1.0
        self._neural_face_eye_movement_enabled = True
        self._neural_face_blink_enabled = True
        self._neural_face_glow_enabled = True
        self._neural_face_emotion_enabled = True
        self._neural_face_use_tts_emotion = True
        self._neural_face_audio_lipsync_enabled = True
        self._neural_face_reduced_animation = False
        self._female_neural_face_enabled = True
        self._female_reference_nodes = True
        self._female_show_wire_nodes = True
        self._female_show_wire_lines = True
        self._female_node_glow_enabled = True
        self._female_wire_pulse_enabled = True
        self._female_depth_enabled = True

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

    @QtCore.Property(bool, notify=enabled_changed)
    def enabled(self):
        return self._enabled

    @QtCore.Property(str, notify=display_mode_changed)
    def displayMode(self):
        return self._display_mode

    @QtCore.Property(str, notify=visual_style_changed)
    def visualStyle(self):
        return self._visual_style

    @QtCore.Property(bool, notify=settings_changed)
    def fullscreen(self):
        return self._fullscreen

    @QtCore.Property(float, notify=settings_changed)
    def overlayOpacity(self):
        return self._overlay_opacity

    @QtCore.Property(float, notify=settings_changed)
    def floatingOpacity(self):
        return self._floating_opacity

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
            "blue_flame_smoke",
            "neural_face_male",
            "neural_face_female",
            "neural_face_auto",
            "vector_voice_orb",
            "circular_audio_waveform",
            "halo_rings",
            "minimal_dot",
            "hologram_core",
            "signal_bloom",
            "crystal_prism",
        }
        if visual_style not in valid_styles:
            visual_style = "breathing_orb"
        if visual_style != self._visual_style:
            self._visual_style = visual_style
            self.visual_style_changed.emit(self._visual_style)

        fullscreen = bool(settings.get("ai_presence_fullscreen", True))
        overlay_opacity = _float_setting(settings, "ai_presence_overlay_opacity", 0.72, 0.10, 1.0)
        floating_opacity = _float_setting(settings, "ai_presence_floating_opacity", 0.92, 0.35, 1.0)
        floating_always_on_top = bool(settings.get("ai_presence_floating_always_on_top", True))
        remember_floating_geometry = bool(settings.get("ai_presence_remember_floating_geometry", True))
        click_through_default = bool(settings.get("ai_presence_click_through_default", False))
        right_drag_move_enabled = bool(settings.get("ai_presence_right_drag_move_enabled", False))
        transparent_background = bool(settings.get("ai_presence_transparent_background", False))
        pulse_intensity = _float_setting(settings, "ai_presence_thinking_pulse", 0.55, 0.10, 1.0)
        speaking_reactivity = _float_setting(settings, "ai_presence_speaking_reactivity", 0.85, 0.10, 1.5)
        node_density = _int_setting(settings, "ai_presence_node_density", 32, 8, 96)
        particle_density = _int_setting(settings, "ai_presence_particle_density", 28, 0, 120)
        reduced_effects = bool(settings.get("ai_presence_reduced_effects", False))
        shaders_enabled = bool(settings.get("ai_presence_shaders_enabled", True))
        particles_enabled = bool(settings.get("ai_presence_particles_enabled", True))
        space_closes_fullscreen = bool(settings.get("ai_presence_space_closes_fullscreen", True))
        music_reactivity_enabled = bool(settings.get("ai_presence_music_reactivity_enabled", False))
        music_reactivity = _float_setting(settings, "ai_presence_music_reactivity", 0.65, 0.0, 1.5)
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
        neural_face_enabled = bool(settings.get("ai_presence_neural_face_enabled", True))
        neural_face_variant = str(settings.get("ai_presence_neural_face_variant", "auto") or "auto").strip().lower()
        if neural_face_variant not in {"auto", "male", "female"}:
            neural_face_variant = "auto"
        neural_face_size = _float_setting(settings, "ai_presence_neural_face_size", 1.0, 0.55, 1.35)
        neural_face_opacity = _float_setting(settings, "ai_presence_neural_face_opacity", 0.92, 0.15, 1.0)
        neural_face_animation_intensity = _float_setting(settings, "ai_presence_neural_face_animation_intensity", 0.78, 0.0, 1.5)
        neural_face_lipsync_strength = _float_setting(settings, "ai_presence_neural_face_lipsync_strength", 1.0, 0.0, 1.75)
        neural_face_eye_movement_enabled = bool(settings.get("ai_presence_neural_face_eye_movement_enabled", True))
        neural_face_blink_enabled = bool(settings.get("ai_presence_neural_face_blink_enabled", True))
        neural_face_glow_enabled = bool(settings.get("ai_presence_neural_face_glow_enabled", True))
        neural_face_emotion_enabled = bool(settings.get("ai_presence_neural_face_emotion_enabled", True))
        neural_face_use_tts_emotion = bool(settings.get("ai_presence_neural_face_use_tts_emotion", True))
        neural_face_audio_lipsync_enabled = bool(settings.get("ai_presence_neural_face_audio_lipsync_enabled", True))
        neural_face_reduced_animation = bool(settings.get("ai_presence_neural_face_reduced_animation", False))
        female_neural_face_enabled = bool(settings.get("ai_presence_female_neural_face_enabled", True))
        female_reference_nodes = bool(settings.get("ai_presence_female_reference_nodes", True))
        female_show_wire_nodes = bool(settings.get("ai_presence_female_show_wire_nodes", True))
        female_show_wire_lines = bool(settings.get("ai_presence_female_show_wire_lines", True))
        female_node_glow_enabled = bool(settings.get("ai_presence_female_node_glow_enabled", True))
        female_wire_pulse_enabled = bool(settings.get("ai_presence_female_wire_pulse_enabled", True))
        female_depth_enabled = bool(settings.get("ai_presence_female_depth_enabled", True))

        mood_source = manual_mood if mood_color_mode == "manual" else self._presence_mood
        colors = resolve_mood_colors(mood_source)
        resolved_mood = str(colors.get("moodName") or "neutral")

        for attr, value in [
            ("_fullscreen", fullscreen),
            ("_overlay_opacity", overlay_opacity),
            ("_floating_opacity", floating_opacity),
            ("_floating_always_on_top", floating_always_on_top),
            ("_remember_floating_geometry", remember_floating_geometry),
            ("_click_through_default", click_through_default),
            ("_right_drag_move_enabled", right_drag_move_enabled),
            ("_transparent_background", transparent_background),
            ("_pulse_intensity", pulse_intensity),
            ("_speaking_reactivity", speaking_reactivity),
            ("_node_density", node_density),
            ("_particle_density", particle_density),
            ("_reduced_effects", reduced_effects),
            ("_shaders_enabled", shaders_enabled),
            ("_particles_enabled", particles_enabled),
            ("_space_closes_fullscreen", space_closes_fullscreen),
            ("_music_reactivity_enabled", music_reactivity_enabled),
            ("_music_reactivity", music_reactivity),
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
