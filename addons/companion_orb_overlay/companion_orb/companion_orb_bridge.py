from __future__ import annotations

from typing import Any

from PySide6 import QtCore

try:
    from addons.ai_presence_mode.mood_color_resolver import resolve_mood_colors
except Exception:  # pragma: no cover
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


def _color_setting(settings, key, default) -> str:
    text = str((settings or {}).get(key, default) or default).strip()
    if not text.startswith("#"):
        text = "#" + text
    text = text[:7]
    if len(text) != 7:
        return str(default)
    try:
        int(text[1:], 16)
    except ValueError:
        return str(default)
    return text.lower()


def _animation_setting(settings, key, default) -> str:
    value = str((settings or {}).get(key, default) or default).strip().lower()
    allowed = {"style_default", "calm_breathe", "slow_orbit", "focused_pulse", "thinking_swirl", "voice_ripple", "energetic_sparkle"}
    return value if value in allowed else str(default)


def _visual_style_setting(settings, key, default) -> str:
    value = str((settings or {}).get(key, default) or default).strip().lower()
    allowed = {"neural_spark", "aurora_glass", "prismatic_pulse", "aether_wisp", "celestial_firetrail"}
    return value if value in allowed else str(default)


class CompanionOrbBridge(QtCore.QObject):
    state_changed = QtCore.Signal()
    level_changed = QtCore.Signal()
    settings_changed = QtCore.Signal()
    target_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_state = "idle"
        self._audio_level = 0.0
        self._mood_name = "neutral"
        self._primary_color = "#38bdf8"
        self._secondary_color = "#22d3ee"
        self._accent_color = "#a78bfa"
        self._glow_color = "#67e8f9"
        self._custom_colors_enabled = False
        self._custom_primary_color = "#22d3ee"
        self._custom_secondary_color = "#38bdf8"
        self._custom_accent_color = "#a78bfa"
        self._custom_glow_color = "#67e8f9"
        self._state_colors_enabled = False
        self._idle_color = "#38bdf8"
        self._thinking_color = "#a78bfa"
        self._speaking_color = "#f472b6"
        self._state_animation_enabled = False
        self._idle_animation = "calm_breathe"
        self._thinking_animation = "thinking_swirl"
        self._speaking_animation = "voice_ripple"
        self._enabled = False
        self._display_mode = "off"
        self._visual_style = "neural_spark"
        self._orb_size = 92
        self._orb_opacity = 0.82
        self._trail_length = 0.55
        self._particle_density = 30
        self._falling_particles_enabled = False
        self._falling_particle_density = 18
        self._falling_particle_lifetime = 3.8
        self._smoke_intensity = 0.35
        self._glow_strength = 1.0
        self._mood_color_intensity = 0.85
        self._speaking_reactivity = 0.85
        self._frame_rate = 60
        self._voice_sync_enabled = True
        self._reduced_effects = False
        self._particles_enabled = True
        self._shaders_enabled = True
        self._edit_mode = False
        self._placement_mode = False
        self._click_through = True
        self._target_info: dict[str, Any] = {}
        self._show_target_label = True

    @QtCore.Property(str, notify=state_changed)
    def aiState(self):
        return self._ai_state

    @QtCore.Property(float, notify=level_changed)
    def audioLevel(self):
        return self._audio_level

    @QtCore.Property(str, notify=settings_changed)
    def moodName(self):
        return self._mood_name

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

    @QtCore.Property(bool, notify=settings_changed)
    def customColorsEnabled(self):
        return self._custom_colors_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def stateColorsEnabled(self):
        return self._state_colors_enabled

    @QtCore.Property(str, notify=settings_changed)
    def idleColor(self):
        return self._idle_color

    @QtCore.Property(str, notify=settings_changed)
    def thinkingColor(self):
        return self._thinking_color

    @QtCore.Property(str, notify=settings_changed)
    def speakingColor(self):
        return self._speaking_color

    @QtCore.Property(bool, notify=settings_changed)
    def stateAnimationEnabled(self):
        return self._state_animation_enabled

    @QtCore.Property(str, notify=settings_changed)
    def idleAnimation(self):
        return self._idle_animation

    @QtCore.Property(str, notify=settings_changed)
    def thinkingAnimation(self):
        return self._thinking_animation

    @QtCore.Property(str, notify=settings_changed)
    def speakingAnimation(self):
        return self._speaking_animation

    @QtCore.Property(bool, notify=settings_changed)
    def enabled(self):
        return self._enabled

    @QtCore.Property(str, notify=settings_changed)
    def displayMode(self):
        return self._display_mode

    @QtCore.Property(str, notify=settings_changed)
    def visualStyle(self):
        return self._visual_style

    @QtCore.Property(int, notify=settings_changed)
    def orbSize(self):
        return self._orb_size

    @QtCore.Property(float, notify=settings_changed)
    def orbOpacity(self):
        return self._orb_opacity

    @QtCore.Property(float, notify=settings_changed)
    def trailLength(self):
        return self._trail_length

    @QtCore.Property(int, notify=settings_changed)
    def particleDensity(self):
        return self._particle_density

    @QtCore.Property(bool, notify=settings_changed)
    def fallingParticlesEnabled(self):
        return self._falling_particles_enabled

    @QtCore.Property(int, notify=settings_changed)
    def fallingParticleDensity(self):
        return self._falling_particle_density

    @QtCore.Property(float, notify=settings_changed)
    def fallingParticleLifetime(self):
        return self._falling_particle_lifetime

    @QtCore.Property(float, notify=settings_changed)
    def smokeIntensity(self):
        return self._smoke_intensity

    @QtCore.Property(float, notify=settings_changed)
    def glowStrength(self):
        return self._glow_strength

    @QtCore.Property(float, notify=settings_changed)
    def moodColorIntensity(self):
        return self._mood_color_intensity

    @QtCore.Property(float, notify=settings_changed)
    def speakingReactivity(self):
        return self._speaking_reactivity

    @QtCore.Property(int, notify=settings_changed)
    def frameRate(self):
        return self._frame_rate

    @QtCore.Property(bool, notify=settings_changed)
    def voiceSyncEnabled(self):
        return self._voice_sync_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def reducedEffects(self):
        return self._reduced_effects

    @QtCore.Property(bool, notify=settings_changed)
    def particlesEnabled(self):
        return self._particles_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def shadersEnabled(self):
        return self._shaders_enabled

    @QtCore.Property(bool, notify=settings_changed)
    def editMode(self):
        return self._edit_mode

    @QtCore.Property(bool, notify=settings_changed)
    def placementMode(self):
        return self._placement_mode

    @QtCore.Property(bool, notify=settings_changed)
    def clickThrough(self):
        return self._click_through

    @QtCore.Property(bool, notify=target_changed)
    def targetActive(self):
        return bool(self._target_info)

    @QtCore.Property(str, notify=target_changed)
    def targetTitle(self):
        title = str(self._target_info.get("title") or "").strip()
        target_type = str(self._target_info.get("target_type") or "").strip().lower()
        if target_type == "window":
            process_name = str(self._target_info.get("process_name") or "").strip()
            return title if not process_name else f"{title} - {process_name}"
        if target_type == "region":
            return title or "Region around Companion Orb"
        return title

    @QtCore.Property(bool, notify=settings_changed)
    def showTargetLabel(self):
        return self._show_target_label

    @QtCore.Slot(str)
    def setAiState(self, state):
        value = str(state or "idle").strip().lower()
        if value not in {"idle", "listening", "thinking", "speaking"}:
            value = "idle"
        if value == self._ai_state:
            return
        self._ai_state = value
        self.state_changed.emit()

    @QtCore.Slot(float)
    def setAudioLevel(self, level):
        if not self._voice_sync_enabled:
            value = 0.0
            if value == self._audio_level:
                return
            self._audio_level = value
            self.level_changed.emit()
            return
        try:
            value = float(level)
        except Exception:
            value = 0.0
        value = max(0.0, min(1.0, value))
        if abs(value - self._audio_level) < 0.003:
            return
        self._audio_level = value
        self.level_changed.emit()

    @QtCore.Slot(str)
    def setPresenceMood(self, mood):
        colors = resolve_mood_colors(mood)
        self._mood_name = str(colors.get("moodName") or "neutral")
        self._apply_color_palette(colors)
        self.settings_changed.emit()

    def _apply_color_palette(self, mood_colors=None):
        colors = dict(mood_colors or resolve_mood_colors(self._mood_name))
        if self._custom_colors_enabled:
            self._primary_color = self._custom_primary_color
            self._secondary_color = self._custom_secondary_color
            self._accent_color = self._custom_accent_color
            self._glow_color = self._custom_glow_color
            return
        self._primary_color = str(colors.get("primaryColor") or "#38bdf8")
        self._secondary_color = str(colors.get("secondaryColor") or "#22d3ee")
        self._accent_color = str(colors.get("accentColor") or "#a78bfa")
        self._glow_color = str(colors.get("glowColor") or "#67e8f9")

    def apply_settings(self, settings):
        payload = dict(settings or {})
        self._enabled = bool(payload.get("companion_orb_enabled", False))
        mode = str(payload.get("companion_orb_display_mode", "off") or "off").strip().lower()
        self._display_mode = mode if mode in {"off", "docked", "interaction", "always"} else "off"
        self._visual_style = _visual_style_setting(payload, "companion_orb_visual_style", "neural_spark")
        self._orb_size = _int_setting(payload, "companion_orb_size", 92, 36, 220)
        self._orb_opacity = _float_setting(payload, "companion_orb_opacity", 0.82, 0.10, 1.0)
        self._trail_length = _float_setting(payload, "companion_orb_trail_length", 0.55, 0.0, 1.0)
        self._particle_density = _int_setting(payload, "companion_orb_particle_density", 30, 0, 120)
        self._falling_particles_enabled = bool(payload.get("companion_orb_falling_particles_enabled", False))
        self._falling_particle_density = _int_setting(payload, "companion_orb_falling_particle_density", 18, 0, 80)
        self._falling_particle_lifetime = _float_setting(payload, "companion_orb_falling_particle_lifetime", 3.8, 0.8, 8.0)
        self._smoke_intensity = _float_setting(payload, "companion_orb_smoke_intensity", 0.35, 0.0, 1.0)
        self._glow_strength = _float_setting(payload, "companion_orb_glow_strength", payload.get("ai_presence_glow_strength", 1.0), 0.0, 1.75)
        self._mood_color_intensity = _float_setting(payload, "companion_orb_mood_color_intensity", payload.get("ai_presence_mood_color_intensity", 0.85), 0.0, 1.0)
        self._custom_colors_enabled = bool(payload.get("companion_orb_custom_colors_enabled", False))
        self._custom_primary_color = _color_setting(payload, "companion_orb_primary_color", "#22d3ee")
        self._custom_secondary_color = _color_setting(payload, "companion_orb_secondary_color", "#38bdf8")
        self._custom_accent_color = _color_setting(payload, "companion_orb_accent_color", "#a78bfa")
        self._custom_glow_color = _color_setting(payload, "companion_orb_glow_color", "#67e8f9")
        self._state_colors_enabled = bool(payload.get("companion_orb_state_colors_enabled", False))
        self._idle_color = _color_setting(payload, "companion_orb_idle_color", "#38bdf8")
        self._thinking_color = _color_setting(payload, "companion_orb_thinking_color", "#a78bfa")
        self._speaking_color = _color_setting(payload, "companion_orb_speaking_color", "#f472b6")
        self._state_animation_enabled = bool(payload.get("companion_orb_state_animation_enabled", False))
        self._idle_animation = _animation_setting(payload, "companion_orb_idle_animation", "calm_breathe")
        self._thinking_animation = _animation_setting(payload, "companion_orb_thinking_animation", "thinking_swirl")
        self._speaking_animation = _animation_setting(payload, "companion_orb_speaking_animation", "voice_ripple")
        self._speaking_reactivity = _float_setting(payload, "companion_orb_speaking_reactivity", payload.get("ai_presence_speaking_reactivity", 0.85), 0.1, 1.5)
        raw_frame_rate = _int_setting(payload, "companion_orb_frame_rate", 60, 30, 120)
        self._frame_rate = min((30, 60, 90, 120), key=lambda candidate: abs(candidate - raw_frame_rate))
        self._voice_sync_enabled = bool(payload.get("companion_orb_voice_sync_enabled", True))
        if not self._voice_sync_enabled:
            self.setAudioLevel(0.0)
        self._reduced_effects = bool(payload.get("companion_orb_reduced_effects", payload.get("ai_presence_reduced_effects", False)))
        self._particles_enabled = bool(payload.get("companion_orb_particles_enabled", payload.get("ai_presence_particles_enabled", True)))
        self._shaders_enabled = bool(payload.get("companion_orb_shaders_enabled", payload.get("ai_presence_shaders_enabled", True)))
        self._show_target_label = bool(payload.get("companion_orb_show_target_label", True))
        if str(payload.get("ai_presence_mood_color_mode", "automatic")).strip().lower() == "manual":
            self.setPresenceMood(payload.get("ai_presence_manual_mood", "neutral"))
        else:
            self._apply_color_palette()
        self.settings_changed.emit()

    def set_modes(self, *, edit_mode=None, placement_mode=None, click_through=None):
        if edit_mode is not None:
            self._edit_mode = bool(edit_mode)
        if placement_mode is not None:
            self._placement_mode = bool(placement_mode)
        if click_through is not None:
            self._click_through = bool(click_through)
        self.settings_changed.emit()

    def set_target_info(self, target_info: dict[str, Any] | None):
        self._target_info = dict(target_info or {})
        self.target_changed.emit()

    def target_info(self) -> dict[str, Any]:
        return dict(self._target_info or {})
