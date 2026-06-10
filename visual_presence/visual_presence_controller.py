"""Native Qt Quick overlay controller for AI Presence Mode."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

try:
    from PySide6.QtQuickWidgets import QQuickWidget
except Exception:  # pragma: no cover - depends on optional Qt Quick deployment.
    QQuickWidget = None

from . import runtime as presence_runtime
from .visual_presence_bridge import VisualPresenceBridge


VALID_DISPLAY_MODES = {"off", "fullscreen", "floating", "both"}
FLOATING_STYLE_CYCLE = [
    "classic_neural_orb",
    "breathing_orb",
    "neural_network_pulse",
    "blue_flame_smoke",
    "vector_voice_orb",
    "circular_audio_waveform",
    "halo_rings",
    "minimal_dot",
    "hologram_core",
    "signal_bloom",
    "crystal_prism",
]

_LIVE_SETTING_RANGES = {
    "ai_presence_overlay_opacity": (0.10, 1.0, float),
    "ai_presence_thinking_pulse": (0.10, 1.0, float),
    "ai_presence_speaking_reactivity": (0.10, 1.5, float),
    "ai_presence_glow_strength": (0.0, 1.75, float),
    "ai_presence_animation_speed": (0.35, 1.75, float),
    "ai_presence_mood_color_intensity": (0.0, 1.0, float),
    "ai_presence_primary_color_strength": (0.0, 1.5, float),
    "ai_presence_secondary_color_strength": (0.0, 1.5, float),
    "ai_presence_background_darkness": (0.0, 1.0, float),
    "ai_presence_particle_density": (0, 120, int),
    "ai_presence_node_density": (8, 96, int),
    "ai_presence_halo_thickness": (0.35, 2.0, float),
    "ai_presence_waveform_strength": (0.2, 2.0, float),
    "ai_presence_ring_expansion_speed": (0.25, 2.0, float),
    "ai_presence_blur_softness": (0.0, 1.0, float),
    "ai_presence_line_brightness": (0.2, 2.0, float),
}

_LIVE_BOOLEAN_SETTINGS = {
    "ai_presence_reduced_effects",
    "ai_presence_particles_enabled",
    "ai_presence_shaders_enabled",
}


def _normalize_display_mode(value) -> str:
    mode = str(value or "fullscreen").strip().lower()
    return mode if mode in VALID_DISPLAY_MODES else "fullscreen"


def _next_visual_style(current) -> str:
    style = str(current or "").strip().lower()
    if style not in FLOATING_STYLE_CYCLE:
        return FLOATING_STYLE_CYCLE[0]
    return FLOATING_STYLE_CYCLE[(FLOATING_STYLE_CYCLE.index(style) + 1) % len(FLOATING_STYLE_CYCLE)]


def _no_shadow_window_hint():
    return getattr(QtCore.Qt, "NoDropShadowWindowHint", QtCore.Qt.WindowType(0))


def _transparent_for_input_hint():
    return getattr(QtCore.Qt, "WindowTransparentForInput", QtCore.Qt.WindowType(0))


def _style_palette(style: str, speaking: bool):
    style = str(style or "breathing_orb").strip().lower()
    if speaking:
        return QtGui.QColor("#22d3ee"), QtGui.QColor("#34d399")
    palettes = {
        "classic_neural_orb": ("#a78bfa", "#f472b6"),
        "breathing_orb": ("#a78bfa", "#f472b6"),
        "neural_network_pulse": ("#a78bfa", "#f472b6"),
        "blue_flame_smoke": ("#38bdf8", "#93c5fd"),
        "neural_face_male": ("#38bdf8", "#67e8f9"),
        "neural_face_female": ("#38bdf8", "#67e8f9"),
        "neural_face_auto": ("#38bdf8", "#67e8f9"),
        "vector_voice_orb": ("#38bdf8", "#f472b6"),
        "circular_audio_waveform": ("#2dd4bf", "#38bdf8"),
        "halo_rings": ("#f59e0b", "#f472b6"),
        "minimal_dot": ("#e5e7eb", "#38bdf8"),
        "hologram_core": ("#67e8f9", "#22d3ee"),
        "signal_bloom": ("#86efac", "#38bdf8"),
        "crystal_prism": ("#c4b5fd", "#fb7185"),
    }
    primary, accent = palettes.get(style, palettes["breathing_orb"])
    return QtGui.QColor(primary), QtGui.QColor(accent)


class _FallbackPresenceWindow(QtWidgets.QWidget):
    """Always-available QWidget presence view used when QML cannot render."""

    def __init__(self, bridge, *, floating=False, parent=None):
        self._floating = bool(floating)
        if self._floating:
            flags = QtCore.Qt.Tool | QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | _no_shadow_window_hint()
            if bool(getattr(bridge, "floatingAlwaysOnTop", True)):
                flags |= QtCore.Qt.WindowStaysOnTopHint
        else:
            flags = (
                QtCore.Qt.FramelessWindowHint
                | QtCore.Qt.Tool
                | QtCore.Qt.WindowStaysOnTopHint
                | _no_shadow_window_hint()
                | QtCore.Qt.WindowDoesNotAcceptFocus
            )
        super().__init__(parent, flags)
        self.bridge = bridge
        self._tick = 0.0
        self._render_voice_level = 0.0
        self._render_peak_level = 0.0
        self._render_music_level = 0.0
        self._render_music_peak = 0.0
        self._waiting_level = 0.0
        self.setObjectName("ai_presence_floating_fallback_window" if self._floating else "ai_presence_fallback_overlay_window")
        self.setWindowTitle("AI Presence Mode")
        self.setFocusPolicy(QtCore.Qt.NoFocus if not self._floating else QtCore.Qt.StrongFocus)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)
        self.setAutoFillBackground(False)
        if not self._floating:
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        else:
            self.setMinimumSize(220, 180)
            self.resize(420, 360)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._advance)

    def _advance(self):
        interval = 50 if bool(getattr(self.bridge, "reducedEffects", False)) else 33
        if self._timer.interval() != interval:
            self._timer.setInterval(interval)
        speed = max(0.15, min(2.8, float(getattr(self.bridge, "animationSpeed", 1.0) or 1.0) * float(getattr(self.bridge, "moodPulseMultiplier", 1.0) or 1.0)))
        self._tick += (interval / 1000.0) * speed
        voice_target = self._clamp01(getattr(self.bridge, "audioLevel", 0.0))
        peak_target = max(voice_target, self._clamp01(getattr(self.bridge, "peakLevel", 0.0)))
        music_target = (
            self._clamp01(float(getattr(self.bridge, "musicLevel", 0.0) or 0.0) * float(getattr(self.bridge, "musicReactivity", 0.65) or 0.65))
            if bool(getattr(self.bridge, "musicReactivityEnabled", False))
            else 0.0
        )
        music_peak_target = (
            max(music_target, self._clamp01(float(getattr(self.bridge, "musicPeak", 0.0) or 0.0) * float(getattr(self.bridge, "musicReactivity", 0.65) or 0.65)))
            if bool(getattr(self.bridge, "musicReactivityEnabled", False))
            else 0.0
        )
        wait_target = (
            0.18 + math.sin(self._tick * 1.25) * 0.06
            if str(getattr(self.bridge, "aiState", "") or "") == "thinking"
            else 0.06 + math.sin(self._tick * 0.75) * 0.025
        )
        self._render_voice_level = self._smooth_level(self._render_voice_level, voice_target, 0.50, 0.24)
        self._render_peak_level = self._smooth_level(self._render_peak_level, peak_target, 0.42, 0.14)
        self._render_music_level = self._smooth_level(self._render_music_level, music_target, 0.38, 0.16)
        self._render_music_peak = self._smooth_level(self._render_music_peak, music_peak_target, 0.34, 0.10)
        self._waiting_level = self._smooth_level(self._waiting_level, wait_target, 0.22, 0.14)
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._timer.isActive():
            self._timer.stop()

    def _with_alpha(self, color, alpha: int) -> QtGui.QColor:
        value = QtGui.QColor(color)
        value.setAlpha(max(0, min(255, int(alpha))))
        return value

    def _clamp01(self, value) -> float:
        try:
            numeric = float(value)
        except Exception:
            numeric = 0.0
        return max(0.0, min(1.0, numeric))

    def _smooth_level(self, current, target, attack, release) -> float:
        try:
            current_value = float(current)
            target_value = float(target)
        except Exception:
            return 0.0
        factor = attack if target_value > current_value else release
        return current_value + (target_value - current_value) * factor

    def _mix_color(self, base, target, amount: float) -> QtGui.QColor:
        base_color = QtGui.QColor(base)
        target_color = QtGui.QColor(target)
        mix = self._clamp01(amount)
        return QtGui.QColor(
            int(round(base_color.red() * (1.0 - mix) + target_color.red() * mix)),
            int(round(base_color.green() * (1.0 - mix) + target_color.green() * mix)),
            int(round(base_color.blue() * (1.0 - mix) + target_color.blue() * mix)),
            int(round(base_color.alpha() * (1.0 - mix) + target_color.alpha() * mix)),
        )

    def _scaled_color(self, color, factor: float, *, minimum: int = 0) -> QtGui.QColor:
        value = QtGui.QColor(color)
        return QtGui.QColor(
            max(minimum, min(255, int(value.red() * factor))),
            max(minimum, min(255, int(value.green() * factor))),
            max(minimum, min(255, int(value.blue() * factor))),
            value.alpha(),
        )

    def _resolved_palette(self, style: str, speaking: bool):
        primary, accent = _style_palette(style, speaking)
        if bool(getattr(self.bridge, "moodColorsEnabled", False)):
            mood_amount = self._clamp01(float(getattr(self.bridge, "moodColorIntensity", 0.85) or 0.85))
            primary = self._mix_color(
                primary,
                QtGui.QColor(str(getattr(self.bridge, "primaryColor", "#38bdf8") or "#38bdf8")),
                mood_amount * max(0.0, min(1.5, float(getattr(self.bridge, "primaryColorStrength", 1.0) or 1.0))) / 1.5,
            )
            accent = self._mix_color(
                accent,
                QtGui.QColor(str(getattr(self.bridge, "accentColor", "#a78bfa") or "#a78bfa")),
                mood_amount * max(0.0, min(1.5, float(getattr(self.bridge, "secondaryColorStrength", 1.0) or 1.0))) / 1.5,
            )
        return primary, accent

    def _draw_transparent_aura(self, painter, center, width, height, color, accent, level):
        if bool(getattr(self.bridge, "reducedEffects", False)) or not bool(getattr(self.bridge, "shadersEnabled", True)):
            return
        glow_strength = max(0.0, min(1.75, float(getattr(self.bridge, "glowStrength", 1.0) or 1.0))) * max(0.1, min(2.0, float(getattr(self.bridge, "moodGlowMultiplier", 1.0) or 1.0)))
        blur = max(0.0, min(1.0, float(getattr(self.bridge, "blurSoftness", 0.35) or 0.35)))
        darkness = max(0.0, min(1.0, float(getattr(self.bridge, "backgroundDarkness", 1.0) or 1.0)))
        radius = min(width, height) * (0.50 + blur * 0.28 + level * 0.12)
        aura = QtGui.QRadialGradient(center, radius)
        aura.setColorAt(0.00, self._with_alpha(accent, (66 + int(level * 42)) * glow_strength))
        aura.setColorAt(0.24, self._with_alpha(self._scaled_color(accent, 0.32, minimum=5), (42 + int(level * 26)) * glow_strength * darkness))
        aura.setColorAt(0.54, QtGui.QColor(10, 12, 25, int((24 + level * 18) * glow_strength * darkness)))
        aura.setColorAt(1.00, QtGui.QColor(0, 0, 0, 0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(aura))
        painter.drawEllipse(center, radius, radius)

        color_glow = QtGui.QRadialGradient(center, radius * 0.72)
        color_glow.setColorAt(0.00, self._with_alpha(color, (46 + int(level * 54)) * glow_strength))
        color_glow.setColorAt(0.44, self._with_alpha(accent, (24 + int(level * 34)) * glow_strength))
        color_glow.setColorAt(1.00, QtGui.QColor(0, 0, 0, 0))
        painter.setBrush(QtGui.QBrush(color_glow))
        painter.drawEllipse(center, radius * 0.72, radius * 0.72)

    def _draw_neural_particles(self, painter, center, width, height, color, accent, level):
        if not bool(getattr(self.bridge, "particlesEnabled", True)) or bool(getattr(self.bridge, "reducedEffects", False)):
            return
        particle_multiplier = max(0.0, min(2.0, float(getattr(self.bridge, "moodParticleMultiplier", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        count = max(0, min(160, int(getattr(self.bridge, "particleDensity", 28) * 1.35 * particle_multiplier)))
        radius = min(width, height) * 0.36
        painter.setPen(QtCore.Qt.NoPen)
        for index in range(count):
            angle = self._tick * (0.13 + index * 0.0025) * max(0.25, min(2.0, float(getattr(self.bridge, "ringExpansionSpeed", 1.0) or 1.0))) + index * 1.618
            band = 0.44 + ((index * 29) % 100) / 145.0
            float_x = math.sin(self._tick * 0.31 + index * 0.73) * (6.0 + level * 10.0)
            float_y = math.cos(self._tick * 0.27 + index * 0.61) * (5.0 + level * 8.0)
            point = QtCore.QPointF(
                center.x() + math.cos(angle) * radius * band + float_x,
                center.y() + math.sin(angle * 0.96) * radius * band + float_y,
            )
            particle_color = self._with_alpha(accent if index % 3 else color, (28 + (index % 5) * 12 + int(level * 54)) * line_brightness)
            painter.setBrush(QtGui.QBrush(particle_color))
            size = 1.2 + (index % 4) * 0.45 + level * 1.4
            painter.drawEllipse(point, size, size)

    def _draw_nodes(self, painter, center, width, height, color, accent, level):
        count = max(8, int(self.bridge.nodeDensity * (0.45 if self.bridge.reducedEffects else 1.0)))
        orbit = min(width, height) * 0.32
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        points = []
        for index in range(count):
            angle = (index / count) * math.tau + math.sin(self._tick * 0.45 + index) * 0.12
            distance = orbit * (0.42 + ((index * 37) % 100) / 180.0)
            point = QtCore.QPointF(center.x() + math.cos(angle) * distance, center.y() + math.sin(angle) * distance)
            points.append(point)
        line_color = QtGui.QColor(color)
        line_color.setAlpha(max(0, min(255, int((45 + level * 80) * line_brightness))))
        painter.setPen(QtGui.QPen(line_color, max(0.6, halo)))
        for index, point in enumerate(points):
            if index + 1 < len(points):
                painter.drawLine(point, points[index + 1])
            dot_color = QtGui.QColor(accent)
            dot_color.setAlpha(max(0, min(255, int((150 + level * 80) * line_brightness))))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(dot_color))
            painter.drawEllipse(point, 2.4 + level * 3.0, 2.4 + level * 3.0)

    def _draw_neural_network_pulse(self, painter, center, width, height, color, accent, level, *, orb_radius=None, voice=None):
        self._draw_transparent_aura(painter, center, width, height, color, accent, level)
        self._draw_neural_particles(painter, center, width, height, color, accent, level)

        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        waveform = max(0.2, min(2.0, float(getattr(self.bridge, "waveformStrength", 1.0) or 1.0)))
        ring_speed = max(0.25, min(2.0, float(getattr(self.bridge, "ringExpansionSpeed", 1.0) or 1.0)))
        count = max(10, int(getattr(self.bridge, "nodeDensity", 32) * (0.55 if self.bridge.reducedEffects else 1.20)))
        radius = min(width, height) * 0.34
        points: list[QtCore.QPointF] = []
        lanes: list[int] = []
        for index in range(count):
            angle = (index / count) * math.tau + math.sin(self._tick * 0.42 * ring_speed + index) * 0.12
            band = 0.38 + ((index * 37) % 100) / 165.0
            wobble = math.sin(self._tick * (0.55 + (index % 5) * 0.11) * ring_speed + index * 1.71) * (12.0 + level * 26.0) * waveform
            points.append(
                QtCore.QPointF(
                    center.x() + math.cos(angle) * (radius * band + wobble),
                    center.y() + math.sin(angle) * (radius * band + wobble),
                )
            )
            lanes.append(index % 3)

        max_steps = 2 if self.bridge.reducedEffects else 4
        for index, point in enumerate(points):
            for step in range(1, max_steps + 1):
                other = points[(index + step * 2) % len(points)]
                distance = math.hypot(point.x() - other.x(), point.y() - other.y())
                if distance > radius * (0.38 + step * 0.025):
                    continue
                line_color = self._with_alpha(color if step % 2 else accent, (18 + int(level * 46) - step * 3) * line_brightness)
                painter.setPen(QtGui.QPen(line_color, (0.75 if step > 2 else 1.0) * halo))
                painter.drawLine(point, other)

        for index, point in enumerate(points):
            lane = lanes[index]
            dot_color = self._with_alpha(accent if lane == 0 else color, (88 + lane * 18 + int(level * 76)) * line_brightness)
            painter.setPen(QtCore.Qt.NoPen)
            if index % 6 == 0:
                node_halo = self._with_alpha(accent, (24 + int(level * 42)) * line_brightness)
                painter.setBrush(QtGui.QBrush(node_halo))
                painter.drawEllipse(point, 4.8 * halo + level * 3.0, 4.8 * halo + level * 3.0)
            painter.setBrush(QtGui.QBrush(dot_color))
            size = (1.7 + lane * 0.55 + level * 2.0) * max(0.8, halo)
            painter.drawEllipse(point, size, size)

        final_orb_radius = float(orb_radius) if orb_radius is not None else min(width, height) * 0.19 * 0.74
        orb_level = self._clamp01(level if voice is None else voice)
        self._draw_rich_orb(painter, center, max(18.0, final_orb_radius), color, accent, orb_level)

    def _draw_rich_orb(self, painter, center, radius, color, accent, level):
        glow_strength = max(0.0, min(1.75, float(getattr(self.bridge, "glowStrength", 1.0) or 1.0))) * max(0.1, min(2.0, float(getattr(self.bridge, "moodGlowMultiplier", 1.0) or 1.0)))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        blur = max(0.0, min(1.0, float(getattr(self.bridge, "blurSoftness", 0.35) or 0.35)))
        glow_radius = radius * (1.95 + blur * 0.72 + level * 0.42)
        glow = QtGui.QRadialGradient(center, glow_radius)
        glow.setColorAt(0.00, self._with_alpha(color, (132 + int(level * 52)) * glow_strength))
        glow.setColorAt(0.40, self._with_alpha(accent, (58 + int(level * 50)) * glow_strength))
        glow.setColorAt(0.78, self._with_alpha(accent, (14 + int(level * 24)) * glow_strength))
        glow.setColorAt(1.00, QtGui.QColor(0, 0, 0, 0))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(glow))
        painter.drawEllipse(center, glow_radius, glow_radius)

        mid_color = self._mix_color(color, QtGui.QColor(10, 18, 35), 0.34)
        deep_color = self._mix_color(self._scaled_color(color, 0.22, minimum=2), QtGui.QColor(2, 6, 23), 0.58)
        core = QtGui.QRadialGradient(
            QtCore.QPointF(center.x() - radius * 0.28, center.y() - radius * 0.34),
            radius * 1.35,
        )
        core.setColorAt(0.00, QtGui.QColor(248, 251, 255, 236))
        core.setColorAt(0.18, self._with_alpha(self._mix_color(color, QtGui.QColor(255, 255, 255), 0.34), 230))
        core.setColorAt(0.44, self._with_alpha(mid_color, 224))
        core.setColorAt(0.72, self._with_alpha(self._scaled_color(color, 0.42, minimum=4), 238))
        core.setColorAt(1.00, self._with_alpha(deep_color, 248))
        painter.setBrush(QtGui.QBrush(core))
        painter.setPen(QtGui.QPen(self._with_alpha(accent, 172 + int(level * 54)), (2.0 + level * 2.0) * halo))
        painter.drawEllipse(center, radius, radius)

        shade = QtGui.QRadialGradient(
            QtCore.QPointF(center.x() + radius * 0.28, center.y() + radius * 0.34),
            radius * 1.05,
        )
        shade.setColorAt(0.00, QtGui.QColor(0, 0, 0, 0))
        shade.setColorAt(0.58, QtGui.QColor(0, 0, 0, 18))
        shade.setColorAt(1.00, QtGui.QColor(0, 0, 0, 108))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(shade))
        painter.drawEllipse(center, radius * 0.98, radius * 0.98)

        highlight = QtGui.QRadialGradient(
            QtCore.QPointF(center.x() - radius * 0.36, center.y() - radius * 0.36),
            radius * 0.38,
        )
        highlight.setColorAt(0.00, QtGui.QColor(255, 255, 255, 188))
        highlight.setColorAt(0.55, QtGui.QColor(255, 255, 255, 70))
        highlight.setColorAt(1.00, QtGui.QColor(255, 255, 255, 0))
        painter.setBrush(QtGui.QBrush(highlight))
        painter.drawEllipse(
            QtCore.QPointF(center.x() - radius * 0.34, center.y() - radius * 0.34),
            radius * 0.34,
            radius * 0.34,
        )

    def _draw_transparent_rings(self, painter, center, radius, color, accent, level, *, count=5, wide=False):
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        ring_speed = max(0.25, min(2.0, float(getattr(self.bridge, "ringExpansionSpeed", 1.0) or 1.0)))
        ring_count = min(2, count) if bool(getattr(self.bridge, "reducedEffects", False)) else count
        for index in range(ring_count):
            pulse = (self._tick * ring_speed * (0.18 + level * 0.55) + index * 0.16) % 0.36
            ring_radius = radius * (1.18 + index * (0.44 if wide else 0.30) + level * 0.42 + pulse)
            alpha = max(0, min(255, int(max(10, 72 - index * 8 + level * 52) * line_brightness)))
            ring_color = self._with_alpha(color if index % 2 == 0 else accent, alpha)
            painter.setPen(QtGui.QPen(ring_color, (2.2 if index == 0 else 1.1) * halo))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(center, ring_radius, ring_radius)

    def _draw_vector_voice_orb(self, painter, center, width, height, radius, color, accent, voice, outer):
        self._draw_transparent_aura(painter, center, width, height, color, accent, max(voice, outer * 0.45))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        ring_speed = max(0.25, min(2.0, float(getattr(self.bridge, "ringExpansionSpeed", 1.0) or 1.0)))
        outer_radius = radius * (1.42 + outer * 0.20)
        for ring in range(3):
            sides = 14 + ring * 4
            ring_radius = outer_radius * (0.72 + ring * 0.18 + outer * 0.025)
            rotation = self._tick * ring_speed * (0.10 + ring * 0.045) * (-1 if ring == 1 else 1)
            path = QtGui.QPainterPath()
            for index in range(sides + 1):
                angle = (index / sides) * math.tau + rotation
                wobble = math.sin(self._tick * 0.85 + index * 1.9 + ring) * (2.0 + outer * 6.0)
                point = QtCore.QPointF(
                    center.x() + math.cos(angle) * (ring_radius + wobble),
                    center.y() + math.sin(angle) * (ring_radius * 0.86 + wobble * 0.45),
                )
                if index == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            painter.setPen(QtGui.QPen(self._with_alpha(color if ring % 2 == 0 else accent, max(18, int((44 + outer * 64 - ring * 9) * line_brightness))), (1.6 if ring == 0 else 1.0) * halo))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPath(path)

        node_count = 12 if bool(getattr(self.bridge, "reducedEffects", False)) else 18
        points = []
        for index in range(node_count):
            lane = index % 2
            angle = (index / node_count) * math.tau + self._tick * ring_speed * (0.16 if lane == 0 else -0.11)
            node_radius = outer_radius * (0.80 + lane * 0.15) + math.sin(self._tick * 0.7 + index) * (4.0 + outer * 10.0)
            points.append(
                (
                    QtCore.QPointF(
                        center.x() + math.cos(angle) * node_radius,
                        center.y() + math.sin(angle) * node_radius * 0.82,
                    ),
                    lane,
                )
            )
        for index, (point, _lane) in enumerate(points):
            next_point = points[(index + 1) % len(points)][0]
            skip_point = points[(index + 3) % len(points)][0]
            painter.setPen(QtGui.QPen(self._with_alpha(color, (18 + outer * 48) * line_brightness), max(0.7, halo * 0.75)))
            painter.drawLine(point, next_point)
            if not bool(getattr(self.bridge, "reducedEffects", False)) and index % 3 == 0:
                painter.setPen(QtGui.QPen(self._with_alpha(accent, (12 + outer * 34) * line_brightness), max(0.5, halo * 0.55)))
                painter.drawLine(point, skip_point)
        painter.setPen(QtCore.Qt.NoPen)
        for point, lane in points:
            painter.setBrush(QtGui.QBrush(self._with_alpha(color if lane == 0 else accent, (102 + outer * 64) * line_brightness)))
            dot_size = 1.8 + outer * 1.7
            painter.drawEllipse(point, dot_size, dot_size)

        center_pulse = 1.0 + voice * 0.42 * max(0.1, min(1.5, float(getattr(self.bridge, "speakingReactivity", 0.85) or 0.85)))
        core_radius = radius * (0.36 + voice * 0.10) * center_pulse
        self._draw_rich_orb(painter, center, max(32.0, core_radius), color, accent, voice)

        if str(getattr(self.bridge, "aiState", "") or "") != "speaking" or voice < 0.08:
            roam = core_radius * 0.56
        else:
            roam = core_radius * 0.14
        small_x = center.x() + math.sin(self._tick * 0.53 + math.sin(self._tick * 0.21) * 2.1) * roam
        small_y = center.y() + math.cos(self._tick * 0.47 + math.sin(self._tick * 0.29) * 1.7) * roam * 0.74
        small_radius = core_radius * (0.18 + outer * 0.06)
        small_center = QtCore.QPointF(small_x, small_y)
        painter.setBrush(QtGui.QBrush(self._with_alpha(accent, 42 + outer * 46)))
        painter.setPen(QtGui.QPen(self._with_alpha(QtGui.QColor("#ecfeff"), 72 + outer * 54), max(0.8, halo * 0.85)))
        painter.drawEllipse(small_center, small_radius, small_radius)

    def _draw_blue_flame_smoke(self, painter, center, width, height, radius, color, accent, voice, outer):
        level = self._clamp01(max(voice, outer * 0.72))
        waveform = max(0.2, min(2.0, float(getattr(self.bridge, "waveformStrength", 1.0) or 1.0)))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        ring_speed = max(0.25, min(2.0, float(getattr(self.bridge, "ringExpansionSpeed", 1.0) or 1.0)))
        glow_strength = max(0.0, min(1.75, float(getattr(self.bridge, "glowStrength", 1.0) or 1.0))) * max(0.1, min(2.0, float(getattr(self.bridge, "moodGlowMultiplier", 1.0) or 1.0)))
        flame_center = QtCore.QPointF(center.x(), center.y() + radius * 0.20)
        self._draw_transparent_aura(painter, flame_center, width, height, color, accent, max(level, outer * 0.55))

        if bool(getattr(self.bridge, "particlesEnabled", True)) and not bool(getattr(self.bridge, "reducedEffects", False)):
            smoke_count = max(4, min(56, int(float(getattr(self.bridge, "particleDensity", 28) or 28) * 0.52)))
            painter.setPen(QtCore.Qt.NoPen)
            for index in range(smoke_count):
                lane = (index * 37) % 100 / 100.0
                rise = (self._tick * (0.11 + lane * 0.09) * ring_speed + index * 0.073) % 1.0
                sway = math.sin(self._tick * (0.38 + lane * 0.18) + index * 1.71) * radius * (0.24 + level * 0.18)
                smoke_center = QtCore.QPointF(
                    center.x() + sway + (lane - 0.5) * radius * 0.52,
                    center.y() - radius * (0.38 + rise * (1.22 + level * 0.42)),
                )
                smoke_radius = radius * (0.060 + lane * 0.055 + rise * 0.080)
                smoke_alpha = max(0, min(130, int((34 + level * 42) * (1.0 - rise * 0.74) * line_brightness)))
                smoke = QtGui.QRadialGradient(smoke_center, smoke_radius * 2.0)
                smoke.setColorAt(0.0, QtGui.QColor(205, 238, 255, smoke_alpha))
                smoke.setColorAt(0.45, QtGui.QColor(85, 139, 190, max(0, int(smoke_alpha * 0.45))))
                smoke.setColorAt(1.0, QtGui.QColor(25, 35, 55, 0))
                painter.setBrush(QtGui.QBrush(smoke))
                painter.drawEllipse(smoke_center, smoke_radius * 1.7, smoke_radius * (0.82 + lane * 0.25))

        flame_height = radius * (1.18 + level * 0.86 * waveform)
        base_width = radius * (0.52 + level * 0.12)
        base_y = center.y() + radius * 0.70
        tip_y = center.y() - flame_height * (0.68 + level * 0.07)
        flicker = (
            math.sin(self._tick * 4.8 * ring_speed) * radius * (0.045 + level * 0.040)
            + math.sin(self._tick * 8.9 * ring_speed + 1.7) * radius * (0.020 + level * 0.025)
        )

        glow_radius = radius * (1.10 + level * 0.28)
        flame_glow = QtGui.QRadialGradient(QtCore.QPointF(center.x(), center.y() + radius * 0.05), glow_radius * 1.8)
        flame_glow.setColorAt(0.00, self._with_alpha(QtGui.QColor("#bfdbfe"), (88 + int(level * 80)) * glow_strength))
        flame_glow.setColorAt(0.32, self._with_alpha(color, (50 + int(level * 66)) * glow_strength))
        flame_glow.setColorAt(0.70, self._with_alpha(accent, (18 + int(level * 34)) * glow_strength))
        flame_glow.setColorAt(1.00, QtGui.QColor(0, 0, 0, 0))
        painter.setBrush(QtGui.QBrush(flame_glow))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(center, glow_radius * 1.35, glow_radius * 1.18)

        outer_path = QtGui.QPainterPath()
        outer_path.moveTo(center.x() + flicker * 0.35, tip_y)
        outer_path.cubicTo(
            center.x() - radius * (0.62 + level * 0.12) + flicker * 0.28,
            center.y() - radius * (0.62 + level * 0.34),
            center.x() - base_width,
            base_y - radius * 0.28,
            center.x() - base_width,
            base_y,
        )
        outer_path.cubicTo(
            center.x() - base_width * 0.46,
            base_y + radius * 0.26,
            center.x() + base_width * 0.44,
            base_y + radius * 0.26,
            center.x() + base_width,
            base_y,
        )
        outer_path.cubicTo(
            center.x() + radius * (0.60 + level * 0.12) + flicker * 0.54,
            center.y() - radius * (0.48 + level * 0.30),
            center.x() + radius * 0.18 + flicker,
            tip_y + radius * 0.27,
            center.x() + flicker * 0.35,
            tip_y,
        )
        outer_path.closeSubpath()
        outer_gradient = QtGui.QLinearGradient(center.x(), tip_y, center.x(), base_y + radius * 0.18)
        outer_gradient.setColorAt(0.00, QtGui.QColor(236, 254, 255, 210))
        outer_gradient.setColorAt(0.20, self._with_alpha(QtGui.QColor("#7dd3fc"), 214))
        outer_gradient.setColorAt(0.55, self._with_alpha(color, 190 + int(level * 40)))
        outer_gradient.setColorAt(1.00, self._with_alpha(QtGui.QColor("#0f3d68"), 170))
        painter.setBrush(QtGui.QBrush(outer_gradient))
        painter.setPen(QtGui.QPen(self._with_alpha(accent, (120 + int(level * 70)) * line_brightness), (1.4 + level * 1.8) * halo))
        painter.drawPath(outer_path)

        inner_path = QtGui.QPainterPath()
        inner_width = base_width * (0.44 + level * 0.06)
        inner_tip_y = center.y() - flame_height * (0.44 + level * 0.10) + math.sin(self._tick * 6.1) * radius * 0.035
        inner_path.moveTo(center.x() - flicker * 0.08, inner_tip_y)
        inner_path.cubicTo(
            center.x() - inner_width * 0.82,
            center.y() - radius * (0.22 + level * 0.18),
            center.x() - inner_width,
            base_y - radius * 0.12,
            center.x() - inner_width * 0.58,
            base_y + radius * 0.08,
        )
        inner_path.cubicTo(
            center.x() - inner_width * 0.12,
            base_y + radius * 0.20,
            center.x() + inner_width * 0.52,
            base_y + radius * 0.08,
            center.x() + inner_width * 0.58,
            base_y - radius * 0.05,
        )
        inner_path.cubicTo(
            center.x() + inner_width * 0.92 + flicker * 0.25,
            center.y() - radius * (0.18 + level * 0.18),
            center.x() + inner_width * 0.18,
            inner_tip_y + radius * 0.18,
            center.x() - flicker * 0.08,
            inner_tip_y,
        )
        inner_path.closeSubpath()
        inner_gradient = QtGui.QLinearGradient(center.x(), inner_tip_y, center.x(), base_y + radius * 0.14)
        inner_gradient.setColorAt(0.00, QtGui.QColor(255, 255, 255, 226))
        inner_gradient.setColorAt(0.30, QtGui.QColor(186, 230, 253, 214))
        inner_gradient.setColorAt(0.78, self._with_alpha(QtGui.QColor("#38bdf8"), 180 + int(level * 45)))
        inner_gradient.setColorAt(1.00, self._with_alpha(QtGui.QColor("#0ea5e9"), 80))
        painter.setBrush(QtGui.QBrush(inner_gradient))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawPath(inner_path)

        base_glow = QtGui.QRadialGradient(QtCore.QPointF(center.x(), base_y - radius * 0.05), radius * (0.78 + level * 0.15))
        base_glow.setColorAt(0.00, QtGui.QColor(224, 242, 254, 210))
        base_glow.setColorAt(0.35, self._with_alpha(color, 144 + int(level * 70)))
        base_glow.setColorAt(1.00, QtGui.QColor(14, 116, 144, 0))
        painter.setBrush(QtGui.QBrush(base_glow))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(QtCore.QPointF(center.x(), base_y - radius * 0.05), radius * (0.58 + level * 0.08), radius * (0.22 + level * 0.04))

        wave_count = 1 if bool(getattr(self.bridge, "reducedEffects", False)) else 3
        for index in range(wave_count):
            wave_path = QtGui.QPainterPath()
            wave_radius = radius * (0.58 + index * 0.18 + level * 0.16)
            y = base_y - radius * (0.18 + index * 0.10)
            wave_path.moveTo(center.x() - wave_radius, y + math.sin(self._tick * 2.7 + index) * 2.5)
            wave_path.cubicTo(
                center.x() - wave_radius * 0.36,
                y - radius * (0.15 + level * 0.10),
                center.x() + wave_radius * 0.36,
                y + radius * (0.14 + level * 0.08),
                center.x() + wave_radius,
                y + math.cos(self._tick * 2.4 + index) * 2.5,
            )
            painter.setPen(QtGui.QPen(self._with_alpha(accent if index % 2 else color, (42 + int(level * 62) - index * 10) * line_brightness), max(0.65, halo * 0.72)))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPath(wave_path)

    def _draw_transparent_style(self, painter, rect, center, width, height, radius, color, accent, voice, outer, style):
        style = str(style or "breathing_orb").strip().lower()
        level = max(voice, outer * 0.55)
        if style in {"neural_face_male", "neural_face_female", "neural_face_auto"}:
            style = "neural_network_pulse"
        if style == "vector_voice_orb":
            self._draw_vector_voice_orb(painter, center, width, height, radius, color, accent, voice, outer)
            return
        if style == "blue_flame_smoke":
            self._draw_blue_flame_smoke(painter, center, width, height, radius, color, accent, voice, outer)
            return
        if style == "circular_audio_waveform":
            self._draw_transparent_aura(painter, center, width, height, color, accent, level)
            self._draw_neural_particles(painter, center, width, height, color, accent, outer)
            self._draw_waveform(painter, center, radius, color, accent, max(voice, outer * 0.65))
            self._draw_rich_orb(painter, center, radius * 0.48, color, accent, max(voice, outer * 0.65))
            return
        if style == "halo_rings":
            self._draw_transparent_aura(painter, center, width, height, color, accent, level)
            self._draw_neural_particles(painter, center, width, height, color, accent, outer)
            self._draw_transparent_rings(painter, center, radius, color, accent, outer, count=7, wide=True)
            self._draw_rich_orb(painter, center, radius * 0.58, color, accent, voice)
            return
        if style == "minimal_dot":
            self._draw_transparent_aura(painter, center, width, height, color, accent, level * 0.55)
            self._draw_transparent_rings(painter, center, radius, color, accent, outer, count=2, wide=False)
            self._draw_rich_orb(painter, center, max(8.0, radius * 0.42), color, accent, voice)
            return
        if style == "hologram_core":
            self._draw_transparent_aura(painter, center, width, height, color, accent, level)
            self._draw_hologram(painter, rect, center, radius, color, accent, level)
            self._draw_rich_orb(painter, center, radius * 0.62, color, accent, voice)
            return
        if style == "signal_bloom":
            self._draw_transparent_aura(painter, center, width, height, color, accent, level)
            self._draw_signal(painter, center, radius, color, accent, level)
            self._draw_rich_orb(painter, center, radius * 0.56, color, accent, voice)
            return
        if style == "crystal_prism":
            self._draw_transparent_aura(painter, center, width, height, color, accent, level)
            self._draw_neural_particles(painter, center, width, height, color, accent, outer * 0.75)
            self._draw_crystal(painter, center, radius * 1.08, color, accent, level)
            return

        self._draw_transparent_aura(painter, center, width, height, color, accent, level)
        self._draw_neural_particles(painter, center, width, height, color, accent, outer)
        self._draw_transparent_rings(painter, center, radius, color, accent, outer, count=5, wide=False)
        self._draw_rich_orb(painter, center, radius, color, accent, voice)

    def _draw_waveform(self, painter, center, radius, color, accent, level):
        path = QtGui.QPainterPath()
        points = 96
        waveform = max(0.2, min(2.0, float(getattr(self.bridge, "waveformStrength", 1.0) or 1.0)))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        for index in range(points + 1):
            angle = (index / points) * math.tau
            wave = math.sin(angle * 8.0 + self._tick * 4.0) * (8.0 + level * 34.0) * waveform
            r = radius * 1.18 + wave
            point = QtCore.QPointF(center.x() + math.cos(angle) * r, center.y() + math.sin(angle) * r)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        wave_color = self._with_alpha(accent, (145 + int(level * 80)) * line_brightness)
        pen = QtGui.QPen(wave_color, (2 + level * 5) * halo)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawPath(path)

    def _draw_hologram(self, painter, rect, center, radius, color, accent, level):
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        painter.setPen(QtGui.QPen(self._with_alpha(accent, (26 + int(level * 52)) * line_brightness), max(0.65, halo * 0.75)))
        step = 18 if self.bridge.reducedEffects else 10
        for y in range(0, rect.height(), step):
            painter.drawLine(0, y, rect.width(), y)
        painter.setPen(QtGui.QPen(self._with_alpha(color, (92 + int(level * 68)) * line_brightness), (1.4 + level * 2.4) * halo))
        for index in range(4):
            r = radius * (1.0 + index * 0.25)
            painter.drawEllipse(center, r, r * (0.62 + index * 0.04))

    def _draw_signal(self, painter, center, radius, color, accent, level):
        rings = 1 if self.bridge.reducedEffects else 5
        ring_speed = max(0.25, min(2.0, float(getattr(self.bridge, "ringExpansionSpeed", 1.0) or 1.0)))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        for index in range(rings):
            r = radius * (0.7 + index * 0.45 + ((self._tick * ring_speed * (0.18 + level * 0.5) + index * 0.18) % 0.45))
            ring = QtGui.QColor(accent if index % 2 else color)
            ring.setAlpha(max(0, min(255, int(max(24, 130 - index * 22 + level * 70) * line_brightness))))
            painter.setPen(QtGui.QPen(ring, (2 + level * 4) * halo))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(center, r, r)

    def _draw_crystal(self, painter, center, radius, color, accent, level):
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        sides = 6
        polygon = QtGui.QPolygonF()
        for index in range(sides):
            angle = (index / sides) * math.tau + self._tick * 0.18
            r = radius * (0.85 + (0.08 * math.sin(self._tick + index)) + level * 0.12)
            polygon.append(QtCore.QPointF(center.x() + math.cos(angle) * r, center.y() + math.sin(angle) * r))
        fill = QtGui.QColor(color)
        fill.setAlpha(max(0, min(255, int((78 + level * 58) * line_brightness))))
        painter.setPen(QtGui.QPen(self._with_alpha(accent, (122 + int(level * 66)) * line_brightness), 1.6 * halo))
        painter.setBrush(QtGui.QBrush(fill))
        painter.drawPolygon(polygon)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, max(24, min(128, int((48 + level * 42) * line_brightness)))), max(0.65, halo * 0.65)))
        for point in polygon:
            painter.drawLine(center, point)

    def _draw_classic_network(self, painter, center, width, height, color, accent, level):
        count = max(10, int(self.bridge.nodeDensity * (0.42 if self.bridge.reducedEffects else 0.72)))
        base_radius = min(width, height) * 0.30
        orbit = self._tick * 0.105
        points = []
        for index in range(count):
            lane = index % 3
            angle = (index / count) * math.tau + orbit * (-0.55 if lane == 1 else 1.0)
            band = base_radius * (1.00 + lane * 0.17)
            float_phase = self._tick * (0.27 + lane * 0.07) + index * 1.37
            wobble = math.sin(float_phase) * (10.0 + level * 18.0)
            vertical_drift = math.sin(float_phase * 0.71 + lane) * (10.0 + level * 10.0)
            points.append(
                (
                    QtCore.QPointF(
                        center.x() + math.cos(angle) * (band + wobble),
                        center.y() + math.sin(angle) * (band * 0.82 + wobble * 0.45) + vertical_drift,
                    ),
                    lane,
                )
            )

        line_color = QtGui.QColor(color)
        line_color.setAlpha(26 + int(level * 32))
        painter.setPen(QtGui.QPen(line_color, 1))
        for index, (point, _lane) in enumerate(points):
            for other_index in range(index + 1, min(len(points), index + 6)):
                other, _other_lane = points[other_index]
                dx = point.x() - other.x()
                dy = point.y() - other.y()
                if math.sqrt((dx * dx) + (dy * dy)) <= base_radius * 0.30:
                    painter.drawLine(point, other)

        for index, (point, lane) in enumerate(points):
            dot_color = QtGui.QColor(accent if lane == 1 else color)
            dot_color.setAlpha(132 + int(level * 62))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QBrush(dot_color))
            size = 2.0 + lane * 0.6 + level * 1.7
            painter.drawEllipse(point, size, size)
            if index % 5 == 0:
                tether = QtGui.QColor(accent)
                tether.setAlpha(26 + int(level * 22))
                painter.setPen(QtGui.QPen(tether, 1))
                painter.drawLine(
                    point,
                    QtCore.QPointF(
                        center.x() + (point.x() - center.x()) * 0.54,
                        center.y() + (point.y() - center.y()) * 0.54,
                    ),
                )

    def _draw_classic_circle(self, painter, center, radius, color, accent, level):
        pulse = 1.0 + level * 0.16 * self.bridge.speakingReactivity
        core_radius = radius * pulse
        fill = QtGui.QColor(color)
        fill.setAlpha(86 + int(level * 46))
        border = QtGui.QColor(accent)
        border.setAlpha(148 + int(level * 56))
        painter.setPen(QtGui.QPen(border, 2))
        painter.setBrush(QtGui.QBrush(fill))
        painter.drawEllipse(center, core_radius, core_radius)

        inner = QtGui.QColor(color)
        inner.setAlpha(46 + int(level * 30))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(inner))
        painter.drawEllipse(center, core_radius * 0.66, core_radius * 0.66)

        rings = 2 if self.bridge.reducedEffects else 4
        for index in range(rings):
            ring = QtGui.QColor(color if index % 2 == 0 else accent)
            ring.setAlpha(max(16, 72 - index * 12 + int(level * 32)))
            painter.setPen(QtGui.QPen(ring, 2 if index == 0 else 1))
            painter.setBrush(QtCore.Qt.NoBrush)
            ring_radius = radius * (1.42 + index * 0.31 + level * 0.22)
            painter.drawEllipse(center, ring_radius, ring_radius)

        bars = 18 if self.bridge.reducedEffects else 36
        painter.setPen(QtGui.QPen(QtGui.QColor(204, 251, 241, 52 + int(level * 52)), 1))
        for index in range(bars):
            angle = (index / bars) * math.tau
            inner_radius = core_radius * 0.76
            outer_radius = inner_radius + 5 + math.sin(self._tick * 2.2 + index) * 2 + level * 12
            painter.drawLine(
                QtCore.QPointF(center.x() + math.cos(angle) * inner_radius, center.y() + math.sin(angle) * inner_radius),
                QtCore.QPointF(center.x() + math.cos(angle) * outer_radius, center.y() + math.sin(angle) * outer_radius),
            )

        eye_width = core_radius * (1.12 + level * 0.12)
        eye_height = core_radius * (0.34 + level * 0.05)
        lid_drift = math.sin(self._tick * 0.9) * core_radius * 0.025
        eye = QtGui.QPainterPath()
        eye.moveTo(center.x() - eye_width * 0.5, center.y() + lid_drift)
        eye.quadTo(center.x(), center.y() - eye_height, center.x() + eye_width * 0.5, center.y() + lid_drift)
        eye.quadTo(center.x(), center.y() + eye_height, center.x() - eye_width * 0.5, center.y() + lid_drift)
        eye.closeSubpath()
        painter.setPen(QtGui.QPen(QtGui.QColor(204, 251, 241, 118 + int(level * 60)), 1.6 + level * 1.2))
        painter.setBrush(QtGui.QBrush(QtGui.QColor(2, 6, 23, 76)))
        painter.drawPath(eye)

        iris_radius = core_radius * (0.15 + level * 0.05)
        iris = QtGui.QRadialGradient(QtCore.QPointF(center.x() - iris_radius * 0.25, center.y() - iris_radius * 0.25), iris_radius * 1.5)
        iris_start = QtGui.QColor(236, 254, 255, 184)
        iris_mid = QtGui.QColor(color)
        iris_mid.setAlpha(174 + int(level * 46))
        iris_end = QtGui.QColor(accent)
        iris_end.setAlpha(76)
        iris.setColorAt(0.0, iris_start)
        iris.setColorAt(0.38, iris_mid)
        iris.setColorAt(1.0, iris_end)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(iris))
        painter.drawEllipse(center, iris_radius, iris_radius)
        painter.setBrush(QtGui.QBrush(QtGui.QColor(2, 6, 23, 158)))
        painter.drawEllipse(center, max(2.5, iris_radius * 0.36), max(2.5, iris_radius * 0.36))

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect()
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        painter.fillRect(rect, QtGui.QColor(0, 0, 0, 0))
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        width = max(1, rect.width())
        height = max(1, rect.height())
        opacity = max(0.10, min(1.0, float(self.bridge.floatingOpacity if self._floating else self.bridge.overlayOpacity)))
        voice_level = self._clamp01(self._render_voice_level)
        peak_level = max(voice_level, self._clamp01(self._render_peak_level))
        music_level = self._clamp01(self._render_music_level)
        music_peak = max(music_level, self._clamp01(self._render_music_peak))
        outer_level = max(music_peak, self._clamp01(self._waiting_level), peak_level * 0.32)
        if bool(getattr(self.bridge, "moodColorsEnabled", False)):
            outer_level = self._clamp01(outer_level * max(0.0, min(2.0, float(getattr(self.bridge, "moodParticleMultiplier", 1.0) or 1.0))))
        level = max(voice_level, outer_level * 0.42)
        speaking = str(self.bridge.aiState or "") == "speaking"
        style = str(self.bridge.visualStyle or "breathing_orb").strip().lower()
        color, accent = self._resolved_palette(style, speaking)
        glow_strength = max(0.0, min(1.75, float(getattr(self.bridge, "glowStrength", 1.0) or 1.0))) * max(0.1, min(2.0, float(getattr(self.bridge, "moodGlowMultiplier", 1.0) or 1.0)))
        halo = max(0.35, min(2.0, float(getattr(self.bridge, "haloThickness", 1.0) or 1.0)))
        line_brightness = max(0.2, min(2.0, float(getattr(self.bridge, "lineBrightness", 1.0) or 1.0)))
        ring_speed = max(0.25, min(2.0, float(getattr(self.bridge, "ringExpansionSpeed", 1.0) or 1.0)))
        blur = max(0.0, min(1.0, float(getattr(self.bridge, "blurSoftness", 0.35) or 0.35)))

        transparent = bool(getattr(self.bridge, "transparentBackground", False))
        if not transparent:
            background = QtGui.QColor(str(getattr(self.bridge, "backgroundColor", "#030712") or "#030712"))
            darkness = max(0.0, min(1.0, float(getattr(self.bridge, "backgroundDarkness", 1.0) or 1.0)))
            background.setAlpha(int((92 + darkness * (120 if self._floating else 148)) * opacity))
            painter.fillRect(rect, background)
        center = QtCore.QPointF(width * 0.5, height * 0.5)
        pulse = 1.0 + math.sin(self._tick * 2.0) * 0.035 * self.bridge.pulseIntensity + voice_level * 0.12 * self.bridge.speakingReactivity
        base = min(width, height) * (0.075 if style == "minimal_dot" else 0.19)
        radius = max(18.0 if style == "minimal_dot" else 42.0, base * pulse)

        if style == "classic_neural_orb":
            if not transparent:
                painter.fillRect(rect, QtGui.QColor(3, 7, 18, int((60 if self._floating else 72) * opacity)))
            self._draw_classic_network(painter, center, width, height, color, accent, outer_level)
            self._draw_classic_circle(painter, center, max(46.0, min(width, height) * (0.145 + voice_level * 0.018)), color, accent, voice_level)
            return
        if style == "neural_network_pulse":
            self._draw_neural_network_pulse(painter, center, width, height, color, accent, outer_level, orb_radius=radius * 0.74, voice=voice_level)
            return
        if transparent:
            self._draw_transparent_style(
                painter,
                rect,
                center,
                width,
                height,
                radius,
                color,
                accent,
                voice_level,
                outer_level,
                style,
            )
            return

        if style == "blue_flame_smoke":
            self._draw_blue_flame_smoke(painter, center, width, height, radius, color, accent, voice_level, outer_level)
            return
        if style == "vector_voice_orb" and not self.bridge.reducedEffects:
            self._draw_nodes(painter, center, width, height, color, accent, level)
        elif style == "circular_audio_waveform":
            self._draw_waveform(painter, center, radius, color, accent, level)
        elif style == "hologram_core":
            self._draw_hologram(painter, rect, center, radius, color, accent, level)
        elif style == "signal_bloom":
            self._draw_signal(painter, center, radius, color, accent, level)
        elif style == "crystal_prism":
            self._draw_crystal(painter, center, radius, color, accent, level)

        rings = 1 if style == "minimal_dot" else (3 if self.bridge.reducedEffects else 6)
        if style in {"classic_neural_orb", "halo_rings", "breathing_orb", "hologram_core", "signal_bloom", "minimal_dot", "vector_voice_orb"}:
            for index in range(rings):
                ring_radius = radius * (1.28 + index * 0.34 + level * 0.45 + ((self._tick * ring_speed * (0.18 + level * 0.55) + index * 0.16) % 0.24))
                ring_color = QtGui.QColor(color if index % 2 == 0 else accent)
                ring_color.setAlpha(max(0, min(255, int(max(18, 82 - index * 8 + level * 45) * line_brightness))))
                painter.setPen(QtGui.QPen(ring_color, (2 if index == 0 else 1) * halo))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawEllipse(center, ring_radius, ring_radius)

        glow = QtGui.QRadialGradient(center, radius * (1.55 + blur * 0.65))
        glow_color = QtGui.QColor(color)
        glow_color.setAlpha(max(0, min(255, int((120 + level * 84) * glow_strength))))
        edge_color = QtGui.QColor(color)
        edge_color.setAlpha(0)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(0.72, self._with_alpha(accent, (42 + int(level * 66)) * glow_strength))
        glow.setColorAt(1.0, edge_color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(glow))
        painter.drawEllipse(center, radius * (1.45 + blur * 0.45), radius * (1.45 + blur * 0.45))

        if style != "crystal_prism":
            painter.setPen(QtGui.QPen(accent, (2 + level * 2) * halo))
            painter.setBrush(QtGui.QBrush(QtGui.QColor(color.red(), color.green(), color.blue(), 220)))
            painter.drawEllipse(center, radius, radius)


class _PresenceCommandProxy(QtCore.QObject):
    state_requested = QtCore.Signal(str)
    level_requested = QtCore.Signal(float)
    music_level_requested = QtCore.Signal(float)
    mood_requested = QtCore.Signal(str)
    settings_requested = QtCore.Signal(dict)
    reset_floating_requested = QtCore.Signal()


class VisualPresenceController(QtCore.QObject):
    def __init__(self, main_window, runtime_config=None):
        super().__init__(main_window)
        self.main_window = main_window
        self.bridge = VisualPresenceBridge(self)
        self.available = False
        self.error = ""
        self._fullscreen_window = None
        self._fullscreen_quick_widget = None
        self._floating_window = None
        self._floating_quick_widget = None
        self._floating_size_grip = None
        self._floating_drag_offset = None
        self._display_mode = "fullscreen"
        self._fullscreen = True
        self._fullscreen_suppressed = False
        self._floating_geometry_restored = False
        self._last_runtime_config = dict(runtime_config or {})
        self._proxy = _PresenceCommandProxy(self)
        self._proxy.state_requested.connect(self._set_ai_state, QtCore.Qt.QueuedConnection)
        self._proxy.level_requested.connect(self._set_audio_level, QtCore.Qt.QueuedConnection)
        self._proxy.music_level_requested.connect(self._set_music_level, QtCore.Qt.QueuedConnection)
        self._proxy.mood_requested.connect(self._set_presence_mood, QtCore.Qt.QueuedConnection)
        self._proxy.settings_requested.connect(self.apply_runtime_config, QtCore.Qt.QueuedConnection)
        self._proxy.reset_floating_requested.connect(self.reset_floating_position, QtCore.Qt.QueuedConnection)
        self.bridge.live_setting_requested.connect(self._apply_live_setting, QtCore.Qt.QueuedConnection)

        self._geometry_timer = QtCore.QTimer(self)
        self._geometry_timer.setInterval(350)
        self._geometry_timer.timeout.connect(self._sync_geometry)

        self._floating_save_timer = QtCore.QTimer(self)
        self._floating_save_timer.setSingleShot(True)
        self._floating_save_timer.setInterval(350)
        self._floating_save_timer.timeout.connect(self._save_floating_geometry)

        self._live_settings_save_timer = QtCore.QTimer(self)
        self._live_settings_save_timer.setSingleShot(True)
        self._live_settings_save_timer.setInterval(850)
        self._live_settings_save_timer.timeout.connect(self._save_live_settings_session)

        self._install_key_filter()
        self._create_fullscreen_window()
        self._create_floating_window()
        self.apply_runtime_config(dict(runtime_config or {}))

    def _install_key_filter(self):
        app = QtWidgets.QApplication.instance()
        if app is not None:
            try:
                app.installEventFilter(self)
            except Exception:
                pass

    def eventFilter(self, watched, event):
        try:
            if (
                event.type() == QtCore.QEvent.KeyPress
                and bool(self.bridge.spaceClosesFullscreen)
                and self._fullscreen_window is not None
                and self._fullscreen_window.isVisible()
                and event.key() in {QtCore.Qt.Key_Space, QtCore.Qt.Key_Escape}
                and (event.key() == QtCore.Qt.Key_Space or not bool(self.bridge.liveControlsVisible))
            ):
                self.hide_fullscreen_temporarily()
                event.accept()
                return True
            if event.type() == QtCore.QEvent.KeyPress and self._presence_window_visible() and not self._focus_is_text_input():
                if event.key() == QtCore.Qt.Key_H:
                    self.bridge.toggleLiveControls()
                    event.accept()
                    return True
                if event.key() == QtCore.Qt.Key_Escape and bool(self.bridge.liveControlsVisible):
                    self.bridge.setLiveControlsVisible(False)
                    event.accept()
                    return True
            if watched is self._floating_window and event.type() in {QtCore.QEvent.Move, QtCore.QEvent.Resize}:
                self._position_floating_size_grip()
                self._schedule_save_floating_geometry()
            if watched in (self._floating_window, self._floating_quick_widget) and self._floating_window is not None:
                if event.type() == QtCore.QEvent.MouseButtonDblClick and event.button() == QtCore.Qt.RightButton:
                    self._cycle_floating_visual_style()
                    event.accept()
                    return True
                drag_button = QtCore.Qt.RightButton if bool(self.bridge.rightDragMoveEnabled) else QtCore.Qt.LeftButton
                if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == drag_button:
                    self._floating_drag_offset = self._event_global_pos(event) - self._floating_window.frameGeometry().topLeft()
                    event.accept()
                    return True
                if event.type() == QtCore.QEvent.MouseMove and self._floating_drag_offset is not None:
                    self._floating_window.move(self._event_global_pos(event) - self._floating_drag_offset)
                    event.accept()
                    return True
                if event.type() == QtCore.QEvent.MouseButtonRelease:
                    self._floating_drag_offset = None
        except Exception:
            pass
        return super().eventFilter(watched, event)

    def _presence_window_visible(self):
        for window in (self._fullscreen_window, self._floating_window):
            try:
                if window is not None and window.isVisible():
                    return True
            except Exception:
                pass
        return False

    def _focus_is_text_input(self):
        app = QtWidgets.QApplication.instance()
        focus = app.focusWidget() if app is not None else None
        return isinstance(
            focus,
            (
                QtWidgets.QLineEdit,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QComboBox,
            ),
        )

    def _event_global_pos(self, event):
        try:
            return event.globalPosition().toPoint()
        except Exception:
            try:
                return event.globalPos()
            except Exception:
                return QtCore.QPoint(0, 0)

    def _window_flags(self, *, floating=False):
        if floating:
            flags = QtCore.Qt.Tool | QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint | _no_shadow_window_hint()
            if bool(self.bridge.floatingAlwaysOnTop):
                flags |= QtCore.Qt.WindowStaysOnTopHint
            return flags
        return (
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
            | _no_shadow_window_hint()
            | QtCore.Qt.WindowDoesNotAcceptFocus
        )

    def _sync_qml_window_background(self, window=None, quick=None):
        transparent = bool(self.bridge.transparentBackground)
        window = window or self._floating_window
        quick = quick or self._floating_quick_widget
        if window is not None:
            try:
                window.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                window.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
                window.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)
                window.setAutoFillBackground(False)
                palette = window.palette()
                palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0, 0 if transparent else 1))
                window.setPalette(palette)
                window.setStyleSheet("background: transparent; border: none;")
            except Exception:
                pass
        if quick is not None:
            try:
                quick.setClearColor(QtGui.QColor(0, 0, 0, 0))
                quick.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
                quick.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
                quick.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)
                quick.setAutoFillBackground(False)
                quick.setStyleSheet("background: transparent; border: none;")
            except Exception:
                pass

    def _floating_click_through_enabled(self) -> bool:
        return bool(self.bridge.clickThroughDefault) and not bool(self.bridge.rightDragMoveEnabled) and not bool(self.bridge.liveControlsVisible)

    def _apply_floating_click_through(self):
        enabled = self._floating_click_through_enabled()
        widgets = [self._floating_window, self._floating_quick_widget]
        for parent in (self._floating_window, self._floating_quick_widget):
            if parent is None:
                continue
            try:
                widgets.extend(parent.findChildren(QtWidgets.QWidget))
            except Exception:
                pass
        seen = set()
        for widget in widgets:
            if widget is None:
                continue
            marker = id(widget)
            if marker in seen:
                continue
            seen.add(marker)
            try:
                widget.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, enabled)
            except Exception:
                pass
            try:
                widget.setFocusPolicy(QtCore.Qt.NoFocus if enabled else QtCore.Qt.StrongFocus)
            except Exception:
                pass
        self._apply_windows_floating_click_through(enabled)

    def _apply_windows_floating_click_through(self, enabled: bool):
        if self._floating_window is None:
            return
        try:
            import sys

            if not sys.platform.startswith("win"):
                return
            import ctypes

            hwnd = int(self._floating_window.winId())
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_FRAMECHANGED = 0x0020
            handles = [hwnd]
            if self._floating_quick_widget is not None:
                try:
                    handles.append(int(self._floating_quick_widget.winId()))
                except Exception:
                    pass
            for handle in dict.fromkeys(handles):
                current = ctypes.windll.user32.GetWindowLongW(handle, GWL_EXSTYLE)
                next_style = current | WS_EX_LAYERED
                if enabled:
                    next_style |= WS_EX_TRANSPARENT
                else:
                    next_style &= ~WS_EX_TRANSPARENT
                ctypes.windll.user32.SetWindowLongW(handle, GWL_EXSTYLE, next_style)
                ctypes.windll.user32.SetWindowPos(handle, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
        except Exception:
            pass

    def _create_qml_window(self, *, floating=False):
        if QQuickWidget is None:
            raise RuntimeError("Qt Quick Widgets are not available.")
        window = QtWidgets.QWidget(None, self._window_flags(floating=floating))
        window.setObjectName("ai_presence_floating_window" if floating else "ai_presence_overlay_window")
        window.setWindowTitle("AI Presence Mode")
        window.setFocusPolicy(QtCore.Qt.StrongFocus if floating else QtCore.Qt.NoFocus)
        window.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        window.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        window.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)
        window.setAutoFillBackground(False)
        if not floating:
            window.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        else:
            window.setMinimumSize(220, 180)
            window.resize(420, 360)
        layout = QtWidgets.QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        quick = QQuickWidget(window)
        quick.setObjectName("ai_presence_floating_quick_widget" if floating else "ai_presence_quick_widget")
        quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        try:
            surface_format = quick.format()
            surface_format.setAlphaBufferSize(8)
            quick.setFormat(surface_format)
        except Exception:
            pass
        quick.setClearColor(QtGui.QColor(0, 0, 0, 0))
        quick.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        quick.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        quick.setAttribute(QtCore.Qt.WA_OpaquePaintEvent, False)
        quick.setAutoFillBackground(False)
        quick.setStyleSheet("background: transparent; border: none;")
        quick.rootContext().setContextProperty("presenceBridge", self.bridge)
        self._sync_qml_window_background(window, quick)
        quick.setSource(QtCore.QUrl.fromLocalFile(str(Path(__file__).with_name("visual_overlay.qml"))))
        if quick.status() == QQuickWidget.Error:
            errors = "; ".join(str(error.toString()) for error in quick.errors())
            window.deleteLater()
            raise RuntimeError(errors or "QML load failed")
        layout.addWidget(quick)
        if floating:
            grip = QtWidgets.QSizeGrip(window)
            grip.setObjectName("ai_presence_floating_size_grip")
            grip.resize(18, 18)
            grip.setToolTip("Drag to resize the transparent AI Presence window.")
            self._floating_size_grip = grip
            self._position_floating_size_grip()
        return window, quick

    def _create_fullscreen_window(self):
        try:
            window, quick = self._create_qml_window(floating=False)
            self._fullscreen_window = window
            self._fullscreen_quick_widget = quick
            self.available = True
            self._sync_geometry()
            print("[AI Presence] Qt Quick fullscreen overlay ready.")
        except Exception as exc:
            self.error = str(exc)
            print(f"[AI Presence] Fullscreen QML unavailable: {exc}. Using QWidget fallback.")
            try:
                self._fullscreen_window = _FallbackPresenceWindow(self.bridge, floating=False)
                self._fullscreen_quick_widget = None
                self.available = True
                self._sync_geometry()
                print("[AI Presence] QWidget fullscreen fallback ready.")
            except Exception as fallback_exc:
                self.error = str(fallback_exc)
                self._fullscreen_window = None
                print(f"[AI Presence] Fullscreen fallback disabled: {fallback_exc}")

    def _create_floating_window(self):
        self._floating_size_grip = None
        if self._floating_prefers_widget_renderer():
            try:
                self._floating_window = _FallbackPresenceWindow(self.bridge, floating=True)
                self._floating_quick_widget = None
                self.available = True
                print("[AI Presence] QWidget transparent floating window ready.")
            except Exception as exc:
                self._floating_window = None
                print(f"[AI Presence] Transparent floating renderer disabled: {exc}")
        else:
            try:
                window, quick = self._create_qml_window(floating=True)
                self._floating_window = window
                self._floating_quick_widget = quick
                self.available = True
                print("[AI Presence] Qt Quick floating window ready.")
            except Exception as exc:
                print(f"[AI Presence] Floating QML unavailable: {exc}. Using QWidget fallback.")
                try:
                    self._floating_window = _FallbackPresenceWindow(self.bridge, floating=True)
                    self._floating_quick_widget = None
                    self.available = True
                    print("[AI Presence] QWidget floating fallback ready.")
                except Exception as fallback_exc:
                    self._floating_window = None
                    print(f"[AI Presence] Floating fallback disabled: {fallback_exc}")
        if self._floating_window is not None:
            try:
                self._floating_window.installEventFilter(self)
                if self._floating_quick_widget is not None:
                    self._floating_quick_widget.installEventFilter(self)
            except Exception:
                pass
            if self._floating_size_grip is None:
                try:
                    self._floating_size_grip = QtWidgets.QSizeGrip(self._floating_window)
                    self._floating_size_grip.setObjectName("ai_presence_floating_size_grip")
                    self._floating_size_grip.resize(18, 18)
                    self._floating_size_grip.setToolTip("Drag to resize the transparent AI Presence window.")
                except Exception:
                    self._floating_size_grip = None
            self._restore_floating_geometry()
            self._position_floating_size_grip()

    def _floating_prefers_widget_renderer(self) -> bool:
        return bool(self.bridge.transparentBackground)

    def _floating_uses_widget_renderer(self) -> bool:
        return self._floating_window is not None and self._floating_quick_widget is None

    def _remember_current_floating_geometry(self):
        window = self._floating_window
        if window is None:
            return
        try:
            geometry = window.geometry()
            payload = [int(geometry.x()), int(geometry.y()), int(geometry.width()), int(geometry.height())]
            self._last_runtime_config["ai_presence_floating_geometry"] = payload
        except Exception:
            pass

    def _destroy_floating_window(self):
        window = self._floating_window
        if window is None:
            return
        self._remember_current_floating_geometry()
        try:
            window.removeEventFilter(self)
        except Exception:
            pass
        try:
            if self._floating_quick_widget is not None:
                self._floating_quick_widget.removeEventFilter(self)
        except Exception:
            pass
        try:
            window.hide()
            window.deleteLater()
        except Exception:
            pass
        self._floating_window = None
        self._floating_quick_widget = None
        self._floating_size_grip = None
        self._floating_drag_offset = None
        self._floating_geometry_restored = False

    def _ensure_floating_renderer(self):
        wants_widget = self._floating_prefers_widget_renderer()
        if self._floating_window is None:
            self._create_floating_window()
            return
        if wants_widget == self._floating_uses_widget_renderer():
            return
        was_visible = bool(self._floating_window.isVisible())
        self._destroy_floating_window()
        self._create_floating_window()
        self._apply_floating_window_settings()
        if was_visible and self._floating_window is not None:
            self._floating_window.show()
            if bool(self.bridge.floatingAlwaysOnTop):
                self._floating_window.raise_()

    def request_ai_state(self, state):
        self._proxy.state_requested.emit(str(state or "idle"))

    def request_audio_level(self, level):
        try:
            value = float(level)
        except Exception:
            value = 0.0
        self._proxy.level_requested.emit(value)

    def request_music_level(self, level):
        try:
            value = float(level)
        except Exception:
            value = 0.0
        self._proxy.music_level_requested.emit(value)

    def request_presence_mood(self, mood):
        self._proxy.mood_requested.emit(str(mood or "neutral"))

    def request_settings(self, settings):
        self._proxy.settings_requested.emit(dict(settings or {}))

    def request_reset_floating_position(self):
        self._proxy.reset_floating_requested.emit()

    @QtCore.Slot(str)
    def _set_ai_state(self, state):
        self.bridge.setAiState(state)
        if str(self.bridge.aiState or "") == "idle":
            self._fullscreen_suppressed = False
        self._refresh_visibility()

    @QtCore.Slot(float)
    def _set_audio_level(self, level):
        self.bridge.setAudioLevel(level)
        self._update_fallback_windows()

    @QtCore.Slot(float)
    def _set_music_level(self, level):
        self.bridge.setMusicLevel(level)
        self._update_fallback_windows()

    @QtCore.Slot(str)
    def _set_presence_mood(self, mood):
        self.bridge.setPresenceMood(mood)
        self._update_fallback_windows()

    def _cycle_floating_visual_style(self):
        next_style = _next_visual_style(self.bridge.visualStyle)
        self._last_runtime_config["ai_presence_visual_style"] = next_style
        try:
            from ui.runtime.engine_access import update_runtime_config

            update_runtime_config("ai_presence_visual_style", next_style)
        except Exception:
            pass
        self.bridge.apply_settings(self._last_runtime_config)
        self._update_fallback_windows()
        self._save_live_settings_session()

    @QtCore.Slot(str, object)
    def _apply_live_setting(self, key, value):
        key = str(key or "").strip()
        if key not in _LIVE_SETTING_RANGES and key not in _LIVE_BOOLEAN_SETTINGS:
            return
        normalized = self._normalize_live_setting(key, value)
        self._last_runtime_config[key] = normalized
        try:
            from ui.runtime.engine_access import update_runtime_config

            update_runtime_config(key, normalized)
        except Exception:
            pass
        self.bridge.apply_settings(self._last_runtime_config)
        self._update_fallback_windows()
        if self._live_settings_save_timer.isActive():
            self._live_settings_save_timer.stop()
        self._live_settings_save_timer.start()

    def _normalize_live_setting(self, key, value):
        if key in _LIVE_BOOLEAN_SETTINGS:
            return bool(value)
        minimum, maximum, value_type = _LIVE_SETTING_RANGES[key]
        try:
            numeric = float(value)
        except Exception:
            numeric = minimum
        numeric = max(float(minimum), min(float(maximum), numeric))
        return int(round(numeric)) if value_type is int else float(numeric)

    def _save_live_settings_session(self):
        window = self.main_window
        callback = getattr(window, "save_session", None)
        if callable(callback):
            try:
                callback()
            except Exception:
                pass

    def _update_fallback_windows(self):
        for window, quick in (
            (self._fullscreen_window, self._fullscreen_quick_widget),
            (self._floating_window, self._floating_quick_widget),
        ):
            if window is None or quick is not None:
                continue
            try:
                window.update()
            except Exception:
                pass

    @QtCore.Slot(dict)
    def apply_runtime_config(self, runtime_config):
        config = dict(runtime_config or {})
        self._last_runtime_config = config
        self.bridge.apply_settings(config)
        self._display_mode = _normalize_display_mode(config.get("ai_presence_display_mode", self.bridge.displayMode))
        self._fullscreen = bool(config.get("ai_presence_fullscreen", True))
        self._ensure_floating_renderer()
        self._apply_floating_window_settings()
        self._restore_floating_geometry()
        self._sync_geometry()
        self._refresh_visibility()

    def _target_geometry(self, *, floating=False):
        if floating:
            return self._floating_default_geometry()
        if self.main_window is None:
            screen = QtWidgets.QApplication.primaryScreen()
            return screen.geometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        if self._fullscreen:
            screen = self.main_window.screen()
            handle = self.main_window.windowHandle()
            if handle is not None and handle.screen() is not None:
                screen = handle.screen()
            if screen is not None:
                return screen.geometry()
        return self.main_window.frameGeometry()

    def _floating_default_geometry(self):
        screen = QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        width = min(520, max(320, int(available.width() * 0.28)))
        height = min(420, max(260, int(available.height() * 0.34)))
        x = available.right() - width - 28
        y = available.top() + 72
        return QtCore.QRect(x, y, width, height)

    def _floating_center_geometry(self):
        window = self._floating_window
        if window is not None:
            screen = window.screen()
            if screen is None and window.windowHandle() is not None:
                screen = window.windowHandle().screen()
        elif self.main_window is not None:
            screen = self.main_window.screen()
            handle = self.main_window.windowHandle()
            if handle is not None and handle.screen() is not None:
                screen = handle.screen()
        else:
            screen = QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else QtCore.QRect(0, 0, 1280, 720)
        current = window.geometry() if window is not None else self._floating_default_geometry()
        width = max(220, min(current.width(), available.width()))
        height = max(180, min(current.height(), available.height()))
        x = available.x() + max(0, int((available.width() - width) / 2))
        y = available.y() + max(0, int((available.height() - height) / 2))
        return QtCore.QRect(x, y, width, height)

    def _configured_floating_geometry(self):
        raw = self._last_runtime_config.get("ai_presence_floating_geometry", [])
        if isinstance(raw, (list, tuple)) and len(raw) == 4:
            try:
                x, y, width, height = [int(value) for value in raw]
                return QtCore.QRect(x, y, max(220, width), max(180, height))
            except Exception:
                return None
        return None

    def _restore_floating_geometry(self):
        if self._floating_window is None or self._floating_geometry_restored:
            return
        geometry = self._configured_floating_geometry() if bool(self.bridge.rememberFloatingGeometry) else None
        if geometry is None:
            geometry = self._floating_default_geometry()
        try:
            self._floating_window.setGeometry(geometry)
            self._floating_geometry_restored = True
        except Exception:
            pass

    def _sync_geometry(self):
        if self._fullscreen_window is not None:
            try:
                self._fullscreen_window.setGeometry(self._target_geometry(floating=False))
            except Exception:
                pass
        self._position_floating_size_grip()

    def _position_floating_size_grip(self):
        grip = self._floating_size_grip
        window = self._floating_window
        if grip is None or window is None:
            return
        try:
            size = grip.sizeHint()
            width = max(14, int(size.width()))
            height = max(14, int(size.height()))
            grip.resize(width, height)
            grip.move(max(0, window.width() - width - 2), max(0, window.height() - height - 2))
            grip.setVisible(bool(window.isVisible()) and not self._floating_click_through_enabled())
            if grip.isVisible():
                grip.raise_()
        except Exception:
            pass

    def _apply_floating_window_settings(self):
        window = self._floating_window
        if window is None:
            return
        try:
            window.setWindowOpacity(max(0.35, min(1.0, float(self.bridge.floatingOpacity))))
        except Exception:
            pass
        try:
            was_visible = window.isVisible()
            window.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, bool(self.bridge.floatingAlwaysOnTop))
            window.setWindowFlag(QtCore.Qt.FramelessWindowHint, True)
            window.setWindowFlag(_no_shadow_window_hint(), True)
            window.setWindowFlag(_transparent_for_input_hint(), self._floating_click_through_enabled())
            self._sync_qml_window_background()
            self._apply_floating_click_through()
            try:
                quick = self._floating_quick_widget
                if quick is not None:
                    quick.update()
            except Exception:
                pass
            if was_visible:
                window.show()
        except Exception:
            pass
        self._apply_floating_click_through()
        self._position_floating_size_grip()

    def _schedule_save_floating_geometry(self):
        if not bool(self.bridge.rememberFloatingGeometry):
            return
        if self._floating_save_timer.isActive():
            self._floating_save_timer.stop()
        self._floating_save_timer.start()

    def _save_floating_geometry(self):
        if self._floating_window is None or not bool(self.bridge.rememberFloatingGeometry):
            return
        try:
            geometry = self._floating_window.geometry()
            payload = [int(geometry.x()), int(geometry.y()), int(geometry.width()), int(geometry.height())]
            self._last_runtime_config["ai_presence_floating_geometry"] = payload
            from ui.runtime.engine_access import update_runtime_config

            update_runtime_config("ai_presence_floating_geometry", payload)
        except Exception:
            pass

    @QtCore.Slot()
    def reset_floating_position(self):
        if self._floating_window is None:
            return
        geometry = self._floating_center_geometry()
        try:
            if self._floating_save_timer.isActive():
                self._floating_save_timer.stop()
            self._floating_window.setGeometry(geometry)
            self._floating_geometry_restored = True
            payload = [int(geometry.x()), int(geometry.y()), int(geometry.width()), int(geometry.height())]
            self._last_runtime_config["ai_presence_floating_geometry"] = payload
            from ui.runtime.engine_access import update_runtime_config

            update_runtime_config("ai_presence_floating_geometry", payload)
        except Exception:
            pass
        self._position_floating_size_grip()
        self._save_live_settings_session()

    def hide_fullscreen_temporarily(self):
        self._fullscreen_suppressed = True
        if self._fullscreen_window is not None:
            try:
                self._fullscreen_window.hide()
            except Exception:
                pass

    def _refresh_visibility(self):
        enabled = bool(self.bridge.enabled) and self._display_mode != "off"
        active = bool(self.bridge.aiState in {"thinking", "speaking"})
        show_fullscreen = bool(enabled and active and self._display_mode in {"fullscreen", "both"} and not self._fullscreen_suppressed)
        show_floating = bool(enabled and self._display_mode in {"floating", "both"})

        if self._fullscreen_window is not None:
            if show_fullscreen:
                self._sync_geometry()
                self._fullscreen_window.show()
                self._fullscreen_window.raise_()
            else:
                self._fullscreen_window.hide()

        if self._floating_window is not None:
            if show_floating:
                self._restore_floating_geometry()
                self._floating_window.show()
                if bool(self.bridge.floatingAlwaysOnTop):
                    self._floating_window.raise_()
            else:
                self._floating_window.hide()

        if show_fullscreen or show_floating:
            if not self._geometry_timer.isActive():
                self._geometry_timer.start()
        elif self._geometry_timer.isActive():
            self._geometry_timer.stop()

    def shutdown(self):
        presence_runtime.unregister_controller(self)
        app = QtWidgets.QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        self._save_floating_geometry()
        self.bridge.setAudioLevel(0.0)
        self.bridge.setMusicLevel(0.0)
        self.bridge.setAiState("idle")
        for window in (self._fullscreen_window, self._floating_window):
            if window is not None:
                window.hide()
                window.deleteLater()
        self._fullscreen_window = None
        self._fullscreen_quick_widget = None
        self._floating_window = None
        self._floating_quick_widget = None


def install_visual_presence(main_window, runtime_config=None):
    controller = VisualPresenceController(main_window, runtime_config)
    presence_runtime.register_controller(controller)
    setattr(main_window, "visual_presence_controller", controller)
    return controller
