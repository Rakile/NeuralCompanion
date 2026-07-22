from __future__ import annotations

import json
from pathlib import Path
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from core import companion_orb_reply_styles
from ui.widgets.basic import NoWheelComboBox, NoWheelSpinBox, NoWheelTabBar, NoWheelTabWidget

from addons.ai_presence_mode.controller import (
    AIPresenceModeController,
    COMPANION_ORB_SESSION_KEYS,
    DEFAULT_SETTINGS,
    ORB_DISPLAY_MODES,
    ORB_POSITIONS,
    ORB_RESPONSE_STYLES,
    ORB_TARGET_MODES,
    ORB_VISUAL_STYLES,
    _ResponsiveGridWidget,
    _runtime_config,
    _update_runtime_config,
)
from addons.companion_orb_overlay.companion_orb.sensory_source import (
    COMPANION_ORB_TARGET_METADATA,
    COMPANION_ORB_TARGET_PINGPONG_PROMPT,
    PROVIDER_ID as COMPANION_ORB_PROVIDER_ID,
)
from addons.companion_orb_overlay.companion_orb import orb_palettes
from addons.companion_orb_overlay.companion_orb import reading_actions
from addons.companion_orb_overlay.companion_orb import eye_tracking

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
COMPANION_ORB_SUPERVISOR_TEMPLATE = """This behavior applies only to Companion Orb Target input.

Active supervisor persona: __PERSONA_NAME__.
Persona style: __PERSONA_STYLE__.

Configured behaviors:
__BEHAVIOR_RULES__

When one configured behavior matches the selected orb target, manual drop snapshot, or full-screen context map, set should_speak=true only when the behavior's repeat policy allows a useful new comment now.
When no configured behavior matches, set should_speak=false for this behavior.
Always set should_generate_image=false and visual_candidate="" for Companion Orb supervisor behavior.
When should_speak=true, proactive_candidate must respond to visible content, not to the fact that the orb moved, captured, dragged, dropped, or inspected something.
When should_speak=true, include focus_bounds for the visible thing being discussed whenever metadata.ocr_regions, metadata.drop_focus_bounds, metadata.manual_inspection.focus_bounds, or metadata.screen_bounds can support it.
When and only when a configured behavior matches and you set should_speak=true, include the tag "[companion_orb_supervisor_match]" in tags and one "[orb_subject:<stable visible subject>]" tag.
Keep interruptions short, grounded, and in the active supervisor persona's voice."""

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


class _CompanionOrbSensoryTabBar(NoWheelTabBar):
    """Draw Companion Orb awareness tabs as MPRC-style icon cards."""

    _MIN_WIDTH = 68
    _HEIGHT = 68
    _HORIZONTAL_PADDING = 10
    _TOP_PADDING = 5
    _TITLE_HEIGHT = 20
    _ICON_TEXT_GAP = 1
    _TEXT_WIDTH_SAFETY = 8
    _INTER_TAB_GUTTER = 5
    _STRIP_VERTICAL_GUTTER = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("_companion_orb_mprc_tab_style", True)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(QtCore.Qt.ElideNone)
        self.setIconSize(QtCore.QSize(36, 36))

    def _title_font(self):
        title_font = QtGui.QFont(self.font())
        title_font.setBold(True)
        return title_font

    def tabSizeHint(self, index):
        title_font = self._title_font()
        text_width = QtGui.QFontMetrics(title_font).horizontalAdvance(self.tabText(index))
        icon_width = 0 if self.tabIcon(index).isNull() else self.iconSize().width()
        width = max(
            self._MIN_WIDTH,
            max(text_width + self._TEXT_WIDTH_SAFETY, icon_width) + (self._HORIZONTAL_PADDING * 2),
        )
        return QtCore.QSize(width + self._INTER_TAB_GUTTER, self._HEIGHT + (self._STRIP_VERTICAL_GUTTER * 2))

    def _tab_metadata(self, index):
        try:
            data = self.tabData(index)
        except Exception:
            return {}
        return dict(data) if isinstance(data, dict) else {}

    def _tab_accent(self, index):
        color = str(self._tab_metadata(index).get("accent") or "#38bdf8").strip()
        accent = QtGui.QColor(color)
        return accent if accent.isValid() else QtGui.QColor("#38bdf8")

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        title_font = self._title_font()
        for index in range(self.count()):
            rect = self.tabRect(index).adjusted(0, self._STRIP_VERTICAL_GUTTER, -self._INTER_TAB_GUTTER, -self._STRIP_VERTICAL_GUTTER)
            if not event.rect().intersects(rect):
                continue
            selected = index == self.currentIndex()
            enabled = self.isTabEnabled(index)
            accent = self._tab_accent(index)
            border = accent if selected else QtGui.QColor("#36506d")
            background = QtGui.QColor("#1c2d43" if selected else "#111b28")

            path = QtGui.QPainterPath()
            path.addRoundedRect(QtCore.QRectF(rect), 9, 9)
            painter.fillPath(path, background)
            painter.setPen(QtGui.QPen(border, 1))
            painter.drawPath(path)

            content = rect.adjusted(self._HORIZONTAL_PADDING, self._TOP_PADDING, -self._HORIZONTAL_PADDING, -5)
            title_rect = QtCore.QRect(content.left(), content.top(), content.width(), self._TITLE_HEIGHT)
            painter.setFont(title_font)
            painter.setPen(accent if enabled else QtGui.QColor("#728095"))
            painter.drawText(
                title_rect,
                QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter | QtCore.Qt.TextSingleLine,
                self.tabText(index),
            )

            icon = self.tabIcon(index)
            if not icon.isNull():
                icon_size = self.iconSize()
                icon_top = title_rect.bottom() + self._ICON_TEXT_GAP
                icon_rect = QtCore.QRect(
                    content.center().x() - (icon_size.width() // 2),
                    icon_top,
                    icon_size.width(),
                    icon_size.height(),
                )
                icon_mode = QtGui.QIcon.Normal if enabled else QtGui.QIcon.Disabled
                icon_state = QtGui.QIcon.On if selected else QtGui.QIcon.Off
                icon.paint(painter, icon_rect, QtCore.Qt.AlignCenter, icon_mode, icon_state)
        painter.end()


class _CompanionOrbColorPreview(QtWidgets.QWidget):
    """Static Orb color preview for the Companion Orb settings UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("companion_orb_color_preview")
        self.setMinimumSize(170, 138)
        self.setMaximumHeight(170)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self._primary = QtGui.QColor("#22d3ee")
        self._secondary = QtGui.QColor("#38bdf8")
        self._accent = QtGui.QColor("#a78bfa")
        self._glow = QtGui.QColor("#67e8f9")

    def _color(self, value, fallback):
        color = QtGui.QColor(str(value or fallback))
        return color if color.isValid() else QtGui.QColor(fallback)

    def set_colors(self, primary, secondary, accent, glow):
        self._primary = self._color(primary, "#22d3ee")
        self._secondary = self._color(secondary, "#38bdf8")
        self._accent = self._color(accent, "#a78bfa")
        self._glow = self._color(glow, "#67e8f9")
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        bounds = self.rect().adjusted(4, 4, -4, -4)

        background = QtGui.QPainterPath()
        background.addRoundedRect(QtCore.QRectF(bounds), 10, 10)
        painter.fillPath(background, QtGui.QColor("#08111d"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#29445f"), 1))
        painter.drawPath(background)

        center = QtCore.QPointF(bounds.center().x(), bounds.top() + 62)
        radius = min(bounds.width(), bounds.height()) * 0.27

        glow_color = QtGui.QColor(self._glow)
        glow_color.setAlpha(110)
        transparent_glow = QtGui.QColor(self._glow)
        transparent_glow.setAlpha(0)
        glow = QtGui.QRadialGradient(center, radius * 2.15)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(1.0, transparent_glow)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QBrush(glow))
        painter.drawEllipse(center, radius * 2.15, radius * 2.15)

        outer_pen = QtGui.QPen(self._accent, 2)
        outer_pen.setCosmetic(True)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(outer_pen)
        painter.drawEllipse(center, radius * 1.42, radius * 1.42)
        ring_pen = QtGui.QPen(self._secondary, 1)
        ring_pen.setCosmetic(True)
        painter.setPen(ring_pen)
        painter.drawEllipse(center, radius * 1.12, radius * 1.12)

        body = QtGui.QRadialGradient(center, radius)
        highlight = self._color("#e0f2fe", "#e0f2fe")
        body.setColorAt(0.0, highlight)
        body.setColorAt(0.28, self._primary)
        body.setColorAt(0.72, self._secondary)
        body.setColorAt(1.0, QtGui.QColor("#020617"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#7dd3fc"), 1))
        painter.setBrush(QtGui.QBrush(body))
        painter.drawEllipse(center, radius, radius)

        painter.setPen(QtGui.QPen(self._accent, 2))
        painter.setBrush(self._accent)
        for point in (
            QtCore.QPointF(center.x() - radius * 0.34, center.y() - radius * 0.12),
            QtCore.QPointF(center.x() + radius * 0.18, center.y() - radius * 0.30),
            QtCore.QPointF(center.x() + radius * 0.36, center.y() + radius * 0.18),
        ):
            painter.drawEllipse(point, 3.0, 3.0)

        swatch_top = bounds.bottom() - 28
        swatch_width = 24
        swatch_gap = 7
        total_width = (swatch_width * 4) + (swatch_gap * 3)
        swatch_left = bounds.center().x() - (total_width // 2)
        for index, color in enumerate((self._primary, self._secondary, self._accent, self._glow)):
            rect = QtCore.QRectF(swatch_left + (index * (swatch_width + swatch_gap)), swatch_top, swatch_width, 13)
            painter.setPen(QtGui.QPen(QtGui.QColor("#56718f"), 1))
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 4, 4)

        painter.end()


def _companion_orb_sensory_tab_icon(kind: str, color: str) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(50, 50)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    accent = QtGui.QColor(str(color or "#38bdf8"))
    if not accent.isValid():
        accent = QtGui.QColor("#38bdf8")
    painter.setPen(QtGui.QPen(accent, 3))
    painter.setBrush(QtGui.QColor(17, 27, 40))
    painter.drawRoundedRect(4, 4, 42, 42, 10, 10)
    painter.setBrush(accent)
    painter.setPen(QtGui.QPen(accent, 3))

    key = str(kind or "").strip().lower()
    if key == "noticed":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(11, 17, 28, 16)
        painter.drawEllipse(21, 21, 8, 8)
        painter.drawLine(15, 38, 35, 38)
    elif key == "capture":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(12, 12, 26, 26, 5, 5)
        painter.drawLine(25, 8, 25, 17)
        painter.drawLine(25, 33, 25, 42)
        painter.drawLine(8, 25, 17, 25)
        painter.drawLine(33, 25, 42, 25)
        painter.drawEllipse(22, 22, 6, 6)
    elif key == "personality":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(18, 11, 14, 14)
        painter.drawArc(13, 25, 24, 17, 20 * 16, 140 * 16)
        painter.drawRoundedRect(30, 10, 10, 8, 3, 3)
    elif key == "overview":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(12, 12, 26, 26)
        painter.drawEllipse(21, 21, 8, 8)
        painter.drawLine(25, 7, 25, 14)
        painter.drawLine(25, 36, 25, 43)
    elif key == "look":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(10, 17, 30, 16)
        painter.setBrush(accent)
        painter.drawEllipse(21, 21, 8, 8)
    elif key == "eye_tracking":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(9, 17, 32, 16)
        painter.drawEllipse(20, 20, 10, 10)
        painter.setBrush(accent)
        painter.drawEllipse(23, 23, 4, 4)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawLine(8, 13, 8, 9)
        painter.drawLine(8, 9, 12, 9)
        painter.drawLine(42, 13, 42, 9)
        painter.drawLine(42, 9, 38, 9)
        painter.drawLine(8, 37, 8, 41)
        painter.drawLine(8, 41, 12, 41)
        painter.drawLine(42, 37, 42, 41)
        painter.drawLine(42, 41, 38, 41)
    elif key == "behavior":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawLine(13, 35, 20, 17)
        painter.drawLine(20, 17, 30, 30)
        painter.drawLine(30, 30, 38, 12)
        painter.drawEllipse(11, 33, 5, 5)
        painter.drawEllipse(18, 15, 5, 5)
        painter.drawEllipse(28, 28, 5, 5)
    elif key == "reading":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(12, 12, 26, 28, 4, 4)
        painter.drawLine(25, 13, 25, 38)
        painter.drawLine(16, 20, 22, 20)
        painter.drawLine(28, 20, 34, 20)
        painter.drawLine(16, 27, 22, 27)
    elif key == "awareness":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(10, 10, 30, 30)
        painter.drawEllipse(18, 18, 14, 14)
        painter.drawLine(25, 25, 37, 13)
    elif key == "hotkeys":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRoundedRect(10, 14, 30, 22, 4, 4)
        for row in range(2):
            for column in range(3):
                painter.drawRect(14 + (column * 8), 19 + (row * 7), 4, 3)
    elif key == "advanced":
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(17, 17, 16, 16)
        painter.drawLine(25, 9, 25, 15)
        painter.drawLine(25, 35, 25, 41)
        painter.drawLine(9, 25, 15, 25)
        painter.drawLine(35, 25, 41, 25)
    else:
        painter.drawRoundedRect(14, 13, 22, 24, 5, 5)
        painter.drawLine(18, 20, 32, 20)
        painter.drawLine(18, 27, 32, 27)

    painter.end()
    return QtGui.QIcon(pixmap)


COMPANION_ORB_TOOLTIPS = {
    "companion_orb_enabled": "Turns the desktop Companion Orb overlay on or off.",
    "companion_orb_enabled_checkbox": "Turns the desktop Companion Orb overlay on or off.",
    "companion_orb_display_mode": "Controls when the orb is visible: off, docked, during interaction, or always visible.",
    "companion_orb_display_mode_combo": "Controls when the orb is visible: off, docked, during interaction, or always visible.",
    "companion_orb_visual_style": "Chooses the Companion Orb visual appearance.",
    "companion_orb_visual_style_combo": "Chooses the Companion Orb visual appearance.",
    "companion_orb_position": "Chooses the default corner or custom position used when the orb is reset.",
    "companion_orb_position_combo": "Chooses the default corner or custom position used when the orb is reset.",
    "companion_orb_response_style": "Sets the tone used for Companion Orb proactive comments and right-click menu response style.",
    "companion_orb_response_style_combo": "Sets the tone used for Companion Orb proactive comments and right-click menu response style.",
    "companion_orb_reply_style_prompt_group": "Edit the style prompt used when Companion Orb turns visual focus into a spoken reply.",
    "companion_orb_reply_style_editor_combo": "Chooses which Companion Orb reply style prompt is shown in the editor.",
    "companion_orb_reply_style_prompt_edit": "Custom prompt for the selected Companion Orb reply style. Save it to override the recommended default.",
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
    "companion_orb_frame_rate": "Canvas and movement update rate. The slider snaps to 30, 60, 90, or 120 FPS.",
    "companion_orb_frame_rate_slider": "Canvas and movement update rate. The slider snaps to 30, 60, 90, or 120 FPS.",
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
    "companion_orb_debug_enabled": "Writes movement, target, snapshot, OCR, selected-area reading/comment, and hidden sensory debug events to the runtime log.",
    "companion_orb_debug_enabled_checkbox": "Writes movement, target, snapshot, OCR, selected-area reading/comment, and hidden sensory debug events to the runtime log.",
    "companion_orb_debug_log_path_preview": "Path used for the Companion Orb debug log.",
    "companion_orb_supervisor_enabled": "Adds orb personality rules to Companion Orb Target background awareness.",
    "companion_orb_supervisor_enabled_checkbox": "Adds orb personality rules to Companion Orb Target background awareness.",
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
    SESSION_KEYS = list(
        dict.fromkeys(
            [
                *COMPANION_ORB_SESSION_KEYS,
                *COMPANION_ORB_AWARE_MOTION_SESSION_KEYS,
                *COMPANION_ORB_EYE_TRACKING_SESSION_KEYS,
                *COMPANION_ORB_READING_SESSION_KEYS,
            ]
        )
    )
    APPLY_STATUS_MESSAGE = "Companion Orb Overlay settings applied."

    def __init__(self, context):
        super().__init__(context)
        self._orb_color_swatches: dict[str, QtWidgets.QLabel] = {}
        self._orb_color_source_status: QtWidgets.QLabel | None = None
        self._orb_color_preview: _CompanionOrbColorPreview | None = None
        self._companion_orb_supervisor_expanded_behavior_ids: set[str] = set()
        self._reply_style_prompt_combo: NoWheelComboBox | None = None
        self._reply_style_prompt_edit: QtWidgets.QPlainTextEdit | None = None
        self._reply_style_prompt_status: QtWidgets.QLabel | None = None
        self._refresh_companion_orb_supervisor_designer = None
        self._syncing_reply_style_prompt = False
        self._reader_commentary_prompt_edit: QtWidgets.QPlainTextEdit | None = None
        self._reader_commentary_prompt_status: QtWidgets.QLabel | None = None
        self._reader_commentary_prompt_timer: QtCore.QTimer | None = None
        self._syncing_reader_commentary_prompt = False
        self._companion_orb_diagnostics_status: QtWidgets.QLabel | None = None
        self._eye_tracking_status_indicator: QtWidgets.QLabel | None = None
        self._eye_tracking_connection_label: QtWidgets.QLabel | None = None
        self._eye_tracking_runtime_label: QtWidgets.QLabel | None = None
        self._eye_tracking_status_label: QtWidgets.QLabel | None = None
        self._eye_tracking_blink_status_label: QtWidgets.QLabel | None = None
        self._eye_tracking_calibration_indicator: QtWidgets.QLabel | None = None
        self._eye_tracking_calibration_status_label: QtWidgets.QLabel | None = None
        self._eye_tracking_calibration_result_label: QtWidgets.QLabel | None = None
        self._eye_tracking_calibration_start_button: QtWidgets.QPushButton | None = None
        self._eye_tracking_calibration_cancel_button: QtWidgets.QPushButton | None = None
        self._eye_tracking_calibration_reset_button: QtWidgets.QPushButton | None = None
        self._eye_tracking_pointer_clearance_status_label: QtWidgets.QLabel | None = None
        self._companion_orb_direct_service = None
        self._eye_tracking_status_timer = QtCore.QTimer(self)
        self._eye_tracking_status_timer.setInterval(1000)
        self._eye_tracking_status_timer.timeout.connect(self._refresh_eye_tracking_status)
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
            if not isinstance(raw_persona, dict):
                continue
            persona_id = str(raw_persona.get("id") or "").strip() or _new_supervisor_id("orb_persona")
            name = str(raw_persona.get("name") or "").strip() or "Orb Supervisor"
            style = str(raw_persona.get("style") or "").strip() or "playful, observant desktop companion"
            behaviors = []
            for raw_behavior in list(raw_persona.get("behaviors") or []):
                if not isinstance(raw_behavior, dict):
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
            _runtime_config().get("companion_orb_supervisor_personas", [])
        )
        if personas != _runtime_config().get("companion_orb_supervisor_personas"):
            _update_runtime_config("companion_orb_supervisor_personas", personas)
        return personas

    def _set_companion_orb_supervisor_personas(self, personas):
        normalized = self._normalize_companion_orb_supervisor_personas(personas)
        selected_id = str(_runtime_config().get("companion_orb_supervisor_selected_persona_id") or "").strip()
        if selected_id not in {item["id"] for item in normalized}:
            _update_runtime_config("companion_orb_supervisor_selected_persona_id", normalized[0]["id"])
        _update_runtime_config("companion_orb_supervisor_personas", normalized)
        self._publish_companion_orb_supervisor()
        return normalized

    def _selected_companion_orb_supervisor_persona(self):
        personas = self._companion_orb_supervisor_personas()
        selected_id = str(_runtime_config().get("companion_orb_supervisor_selected_persona_id") or "").strip()
        for persona in personas:
            if persona["id"] == selected_id:
                return persona
        _update_runtime_config("companion_orb_supervisor_selected_persona_id", personas[0]["id"])
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
        template = str(_runtime_config().get("companion_orb_supervisor_prompt_template", "") or "").strip()
        return template or COMPANION_ORB_SUPERVISOR_TEMPLATE

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

    def _render_companion_orb_supervisor_behavior_rules(self, persona=None):
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
            lines.append(
                f"{index}. Visual Trigger: {trigger}\n"
                f"   Action: {action}\n"
                f"   Strictness: {self._strictness_instruction(behavior.get('strictness'))}\n"
                f"   Emotion override: {emotion_line}\n"
                f"   Repeat policy: {self._repeat_policy_instruction(behavior.get('repeat_mode'), behavior.get('repeat_interval'))}"
            )
        if not lines:
            return "No Companion Orb supervisor behaviors are configured. Set should_speak=false for this behavior."
        return "\n".join(lines)

    def _render_companion_orb_supervisor_prompt(self):
        active = self._selected_companion_orb_supervisor_persona()
        rendered = self._companion_orb_supervisor_template()
        rendered = rendered.replace("__PERSONA_NAME__", str(active.get("name") or "Orb Supervisor"))
        rendered = rendered.replace("__PERSONA_STYLE__", str(active.get("style") or "playful, observant desktop companion"))
        rendered = rendered.replace("__BEHAVIOR_RULES__", self._render_companion_orb_supervisor_behavior_rules(active))
        return rendered.strip()

    def _sensory_service(self):
        return self.context.get_service("qt.sensory") if getattr(self, "context", None) is not None else None

    def _register_companion_orb_supervisor_contributor(self):
        sensory_service = self._sensory_service()
        if sensory_service is None:
            return
        if not bool(_runtime_config().get("companion_orb_supervisor_enabled", False)):
            sensory_service.unregister_prompt_contributor(COMPANION_ORB_SUPERVISOR_CONTRIBUTOR_ID)
            return
        active = self._selected_companion_orb_supervisor_persona()
        sensory_service.register_prompt_contributor(
            contributor_id=COMPANION_ORB_SUPERVISOR_CONTRIBUTOR_ID,
            source_id=COMPANION_ORB_PROVIDER_ID,
            label="Companion Orb Supervisor",
            prompt=self._render_companion_orb_supervisor_prompt(),
            order=212,
            metadata={
                "type": "behavior_rule",
                "persona_name": str(active.get("name") or "Orb Supervisor"),
                "behavior_count": len(list(active.get("behaviors") or [])),
                "active_behaviors": [
                    {
                        "trigger": str(behavior.get("trigger") or "").strip(),
                        "action": str(behavior.get("action") or "").strip(),
                        "repeat_mode": self._normalize_supervisor_repeat_mode(behavior.get("repeat_mode")),
                        "repeat_interval": self._normalize_supervisor_repeat_interval(behavior.get("repeat_interval")),
                    }
                    for behavior in list(active.get("behaviors") or [])
                    if bool(behavior.get("enabled", True))
                    and str(behavior.get("trigger") or "").strip()
                    and str(behavior.get("action") or "").strip()
                ],
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
        raw = _runtime_config().get("sensory_feedback_source", "off") if value is None else value
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

    def _notify_host_settings_changed(self):
        try:
            shell = self.context.get_service("qt.shell") if getattr(self, "context", None) is not None else None
            notifier = getattr(shell, "notify_settings_changed", None)
            if callable(notifier):
                notifier()
        except Exception:
            pass

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
        if config_value != str(_runtime_config().get("sensory_feedback_source", "off") or "off"):
            _update_runtime_config("sensory_feedback_source", config_value)
            self._notify_host_settings_changed()
        return config_value

    def _companion_orb_source_included(self):
        return COMPANION_ORB_PROVIDER_ID in set(self._parse_sensory_sources())

    def _reply_style_prompt_overrides(self):
        return companion_orb_reply_styles.normalize_reply_style_prompts(
            _runtime_config().get("companion_orb_response_style_prompts", {})
        )

    def _selected_reply_style_prompt_style(self):
        combo = self._reply_style_prompt_combo
        if combo is not None:
            return companion_orb_reply_styles.normalize_reply_style(combo.currentData())
        return companion_orb_reply_styles.normalize_reply_style(
            _runtime_config().get("companion_orb_response_style", "friendly")
        )

    def _set_reply_style_prompt_combo_value(self, style):
        combo = self._reply_style_prompt_combo
        if combo is None:
            return
        normalized = companion_orb_reply_styles.normalize_reply_style(style)
        for index in range(combo.count()):
            if str(combo.itemData(index) or "").strip().lower() == normalized:
                combo.setCurrentIndex(index)
                return

    def _sync_reply_style_prompt_editor_from_runtime(self, style=None):
        editor = self._reply_style_prompt_edit
        if editor is None:
            return
        normalized_style = companion_orb_reply_styles.normalize_reply_style(
            style if style is not None else self._selected_reply_style_prompt_style()
        )
        overrides = self._reply_style_prompt_overrides()
        prompt = companion_orb_reply_styles.effective_reply_style_prompt(normalized_style, overrides)
        self._syncing_reply_style_prompt = True
        try:
            combo = self._reply_style_prompt_combo
            if combo is not None:
                try:
                    combo.blockSignals(True)
                    self._set_reply_style_prompt_combo_value(normalized_style)
                finally:
                    combo.blockSignals(False)
            try:
                editor.blockSignals(True)
                editor.setPlainText(prompt)
            finally:
                editor.blockSignals(False)
        finally:
            self._syncing_reply_style_prompt = False
        label = companion_orb_reply_styles.reply_style_label(normalized_style)
        source = "custom override" if normalized_style in overrides else "recommended default"
        if self._reply_style_prompt_status is not None:
            self._reply_style_prompt_status.setText(f"Loaded {source} for {label}.")

    def _save_reply_style_prompt_override(self):
        editor = self._reply_style_prompt_edit
        if editor is None:
            return
        style = self._selected_reply_style_prompt_style()
        text = str(editor.toPlainText() or "").strip()
        if not text:
            text = companion_orb_reply_styles.default_reply_style_prompt(style)
        overrides = self._reply_style_prompt_overrides()
        overrides[style] = text
        _update_runtime_config("companion_orb_response_style_prompts", overrides)
        self._set_status(f"Saved Companion Orb reply style: {companion_orb_reply_styles.reply_style_label(style)}.")
        if self._reply_style_prompt_status is not None:
            self._reply_style_prompt_status.setText(f"Saved custom override for {companion_orb_reply_styles.reply_style_label(style)}.")
        self._save_session()

    def _reset_reply_style_prompt_override(self):
        style = self._selected_reply_style_prompt_style()
        overrides = self._reply_style_prompt_overrides()
        overrides.pop(style, None)
        _update_runtime_config("companion_orb_response_style_prompts", overrides)
        self._sync_reply_style_prompt_editor_from_runtime(style)
        self._set_status(f"Restored recommended Companion Orb reply style: {companion_orb_reply_styles.reply_style_label(style)}.")
        self._save_session()

    def _reset_all_reply_style_prompt_overrides(self):
        _update_runtime_config("companion_orb_response_style_prompts", {})
        self._sync_reply_style_prompt_editor_from_runtime()
        self._set_status("Restored all recommended Companion Orb reply style prompts.")
        self._save_session()

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
            _runtime_config().get(
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
                _runtime_config().get(
                    "companion_orb_reading_max_chunk_chars",
                    COMPANION_ORB_READING_DEFAULTS["companion_orb_reading_max_chunk_chars"],
                ),
            )
        )

    def _sync_reader_settings_from_runtime(self, *, force_prompt: bool = False):
        exclude_checkbox = self._controls.get("companion_orb_reader_exclude_from_memory")
        if isinstance(exclude_checkbox, QtWidgets.QCheckBox):
            try:
                exclude_checkbox.blockSignals(True)
                exclude_checkbox.setChecked(
                    bool(
                        self._normalize_setting(
                            "companion_orb_reader_exclude_from_memory",
                            _runtime_config().get(
                                "companion_orb_reader_exclude_from_memory",
                                COMPANION_ORB_READING_DEFAULTS["companion_orb_reader_exclude_from_memory"],
                            ),
                        )
                    )
                )
            finally:
                exclude_checkbox.blockSignals(False)

        chunk_spin = self._controls.get("companion_orb_reading_max_chunk_chars")
        if isinstance(chunk_spin, QtWidgets.QSpinBox):
            try:
                chunk_spin.blockSignals(True)
                chunk_spin.setValue(self._reading_chunk_size_value())
            finally:
                chunk_spin.blockSignals(False)

        editor = self._reader_commentary_prompt_edit
        if editor is None:
            return
        document = editor.document()
        has_unsaved_user_edit = bool(document is not None and document.isModified() and editor.hasFocus())
        if has_unsaved_user_edit and not force_prompt:
            return
        self._syncing_reader_commentary_prompt = True
        try:
            editor.blockSignals(True)
            editor.setPlainText(self._reader_commentary_prompt_value())
            if document is not None:
                document.setModified(False)
        finally:
            editor.blockSignals(False)
            self._syncing_reader_commentary_prompt = False
        if self._reader_commentary_prompt_status is not None:
            self._reader_commentary_prompt_status.setText("Loaded saved selected-text prompt.")

    def _schedule_reader_commentary_prompt_save(self):
        if self._syncing_reader_commentary_prompt:
            return
        timer = self._reader_commentary_prompt_timer
        if timer is not None:
            timer.start()

    def _save_reader_commentary_prompt(self):
        editor = self._reader_commentary_prompt_edit
        if editor is None or self._syncing_reader_commentary_prompt:
            return
        raw_text = str(editor.toPlainText() or "").strip()
        text = raw_text or self._reader_commentary_prompt_default()
        if text != str(_runtime_config().get("companion_orb_reader_commentary_prompt", "") or ""):
            self._on_setting_changed("companion_orb_reader_commentary_prompt", text)
        document = editor.document()
        if document is not None:
            document.setModified(False)
        if not raw_text:
            self._sync_reader_settings_from_runtime(force_prompt=True)
        if self._reader_commentary_prompt_status is not None:
            self._reader_commentary_prompt_status.setText("Saved selected-text prompt.")

    def _reset_reader_commentary_prompt(self):
        self._on_setting_changed("companion_orb_reader_commentary_prompt", reading_actions.DEFAULT_COMMENTARY_PROMPT)
        self._sync_reader_settings_from_runtime(force_prompt=True)
        self._set_status("Restored recommended Companion Orb selected-text prompt.")

    def _companion_orb_debug_log_path(self) -> Path:
        root = Path(getattr(self.context, "app_root", Path.cwd()) or Path.cwd())
        return root / "runtime" / "companion_orb" / "debug" / "companion_orb_debug.log"

    def _set_companion_orb_diagnostics_status(self, text: str) -> None:
        label = getattr(self, "_companion_orb_diagnostics_status", None)
        if label is not None:
            label.setText(str(text or ""))
        try:
            self._set_status(str(text or ""))
        except Exception:
            pass

    def _open_companion_orb_debug_log_folder(self) -> None:
        path = self._companion_orb_debug_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.parent)))
            self._set_companion_orb_diagnostics_status(f"Opened debug log folder: {path.parent}")
        except Exception as exc:
            self._set_companion_orb_diagnostics_status(f"Could not open debug log folder: {exc}")

    def _clear_companion_orb_debug_log(self) -> None:
        path = self._companion_orb_debug_log_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
            self._set_companion_orb_diagnostics_status("Cleared Companion Orb debug log.")
        except Exception as exc:
            self._set_companion_orb_diagnostics_status(f"Could not clear Companion Orb debug log: {exc}")

    def _copy_companion_orb_debug_log_path(self) -> None:
        path = self._companion_orb_debug_log_path()
        app = QtWidgets.QApplication.instance()
        try:
            if app is None:
                raise RuntimeError("QApplication is not available.")
            app.clipboard().setText(str(path))
            self._set_companion_orb_diagnostics_status("Copied Companion Orb debug log path.")
        except Exception as exc:
            self._set_companion_orb_diagnostics_status(f"Could not copy debug log path: {exc}")

    def _build_companion_orb_color_workbench(self):
        container = QtWidgets.QWidget()
        container.setObjectName("companion_orb_custom_colors_group")
        container.setAccessibleName("Custom Colors")
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        workbench_group, workbench_layout = self._section_group("Preview & Palette", "companion_orb_color_workbench_group")
        preview_row = QtWidgets.QWidget()
        preview_row.setObjectName("companion_orb_color_preview_row")
        preview_layout = QtWidgets.QHBoxLayout(preview_row)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(12)

        controls_panel = QtWidgets.QWidget()
        controls_panel.setObjectName("companion_orb_color_controls_panel")
        controls_layout = QtWidgets.QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.setSpacing(8)
        controls_layout.addWidget(
            self._checkbox(
                "Custom orb colors",
                "companion_orb_custom_colors_enabled_checkbox",
                "companion_orb_custom_colors_enabled",
                False,
            )
        )

        palette_row = QtWidgets.QWidget()
        palette_row.setObjectName("companion_orb_color_palette_row")
        palette_layout = QtWidgets.QHBoxLayout(palette_row)
        palette_layout.setContentsMargins(0, 0, 0, 0)
        palette_layout.setSpacing(6)
        palette_layout.addWidget(self._compact_label("Palette"))
        palette_layout.addWidget(
            self._combo(
                "companion_orb_color_palette_combo",
                ORB_COLOR_PALETTE_OPTIONS,
                "companion_orb_color_palette",
                orb_palettes.CUSTOM_PALETTE_ID,
            ),
            1,
        )
        controls_layout.addWidget(palette_row)

        mood_row = QtWidgets.QWidget()
        mood_row.setObjectName("companion_orb_mood_color_row")
        mood_layout = QtWidgets.QHBoxLayout(mood_row)
        mood_layout.setContentsMargins(0, 0, 0, 0)
        mood_layout.setSpacing(6)
        mood_layout.addWidget(self._compact_label("Mood colors"))
        mood_layout.addWidget(
            self._combo(
                "companion_orb_mood_color_mode_combo",
                COMPANION_ORB_MOOD_COLOR_MODES,
                "companion_orb_mood_color_mode",
                "automatic",
            ),
            1,
        )
        mood_layout.addWidget(self._compact_label("Manual"))
        mood_layout.addWidget(
            self._combo(
                "companion_orb_manual_mood_combo",
                COMPANION_ORB_MOOD_CHOICES,
                "companion_orb_manual_mood",
                "neutral",
            ),
            1,
        )
        controls_layout.addWidget(mood_row)

        self._orb_color_source_status = QtWidgets.QLabel()
        self._orb_color_source_status.setObjectName("companion_orb_color_source_status")
        self._orb_color_source_status.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        controls_layout.addWidget(self._orb_color_source_status)
        controls_layout.addStretch(1)

        self._orb_color_preview = _CompanionOrbColorPreview()
        preview_layout.addWidget(controls_panel, 1)
        preview_layout.addWidget(self._orb_color_preview, 0, QtCore.Qt.AlignTop | QtCore.Qt.AlignRight)
        workbench_layout.addWidget(preview_row)
        container_layout.addWidget(workbench_group)

        channels_group, channels_layout = self._section_group("Color Channels", "companion_orb_color_channels_group")
        color_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=4, horizontal_spacing=10, vertical_spacing=6)
        color_grid.setObjectName("companion_orb_custom_color_grid")
        for label, key, default in (
            ("Primary", "companion_orb_primary_color", "#22d3ee"),
            ("Secondary", "companion_orb_secondary_color", "#38bdf8"),
            ("Accent", "companion_orb_accent_color", "#a78bfa"),
            ("Glow", "companion_orb_glow_color", "#67e8f9"),
        ):
            color_grid.add_widget(self._color_setting_row(label, key, default))
        channels_layout.addWidget(color_grid)
        color_action_row = QtWidgets.QHBoxLayout()
        color_action_row.setContentsMargins(0, 2, 0, 0)
        color_action_row.setSpacing(8)
        apply_colors_button = QtWidgets.QPushButton("Apply Colors")
        apply_colors_button.setObjectName("btn_companion_orb_apply_custom_colors")
        save_colors_button = QtWidgets.QPushButton("Save Colors")
        save_colors_button.setObjectName("btn_companion_orb_save_custom_colors")
        for button in (apply_colors_button, save_colors_button):
            button.setMinimumHeight(27)
            button.setMaximumHeight(31)
            button.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
            color_action_row.addWidget(button)
        color_action_row.addStretch(1)
        apply_colors_button.clicked.connect(lambda *_args: self._apply_companion_orb_custom_colors(save=False))
        save_colors_button.clicked.connect(lambda *_args: self._apply_companion_orb_custom_colors(save=True))
        channels_layout.addLayout(color_action_row)
        container_layout.addWidget(channels_group)

        self._refresh_orb_color_preview()
        return container

    def _normalize_setting(self, key, value):
        key = str(key or "").strip()
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
            color = QtGui.QColor(text[:7])
            return color.name() if color.isValid() else str(COMPANION_ORB_EYE_TRACKING_DEFAULTS[key])
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

    def eventFilter(self, watched, event):
        if watched is self._reader_commentary_prompt_edit and event.type() == QtCore.QEvent.FocusOut:
            timer = self._reader_commentary_prompt_timer
            if timer is not None and timer.isActive():
                timer.stop()
            self._save_reader_commentary_prompt()
        return super().eventFilter(watched, event)

    def _apply_runtime_config(self):
        super()._apply_runtime_config()
        self._push_companion_orb_runtime_settings()

    def _push_companion_orb_runtime_settings(self):
        try:
            orb = self._companion_orb_service()
            requester = getattr(orb, "request_settings", None)
            if callable(requester):
                requester(dict(_runtime_config()))
        except Exception:
            pass

    def _on_setting_changed(self, key, value):
        key = str(key or "").strip()
        if key == "companion_orb_color_palette":
            self._apply_companion_orb_palette(value)
            return
        if key in ORB_COLOR_SETTING_KEYS and not bool(_runtime_config().get("companion_orb_custom_colors_enabled", False)):
            _update_runtime_config("companion_orb_custom_colors_enabled", True)
            self._sync_checkbox("companion_orb_custom_colors_enabled", True)
        super()._on_setting_changed(key, value)
        if key in ORB_COLOR_SETTING_KEYS:
            self._sync_orb_color_source_status()
            self._refresh_orb_color_preview()
        elif key == "companion_orb_custom_colors_enabled":
            if not bool(value):
                _update_runtime_config("companion_orb_color_palette", orb_palettes.CUSTOM_PALETTE_ID)
                self._sync_orb_palette_combo(orb_palettes.CUSTOM_PALETTE_ID)
                self._apply_runtime_config()
                self._save_session()
            self._sync_orb_color_source_status()
            self._refresh_orb_color_preview()
        elif key == "companion_orb_state_colors_enabled":
            self._sync_orb_color_source_status()
        elif key in {"companion_orb_mood_color_mode", "companion_orb_manual_mood"}:
            self._sync_orb_color_source_status()
        if key == "companion_orb_sensory_target_enabled":
            self._set_companion_orb_source_included(bool(value))
        elif key == "companion_orb_full_screen_context_enabled" and bool(value):
            if not bool(_runtime_config().get("companion_orb_sensory_target_enabled", False)):
                _update_runtime_config("companion_orb_sensory_target_enabled", True)
                self._sync_checkbox("companion_orb_sensory_target_enabled", True)
            self._set_companion_orb_source_included(True)
        elif key == "companion_orb_supervisor_enabled":
            self._publish_companion_orb_supervisor()
            self._refresh_companion_orb_supervisor_designer_if_available()
        elif key == "sensory_pingpong_enabled":
            self._notify_host_settings_changed()
        if key in COMPANION_ORB_EYE_TRACKING_SESSION_KEYS:
            QtCore.QTimer.singleShot(120, self._refresh_eye_tracking_status)
        if key in {
            "companion_orb_sensory_target_enabled",
            "companion_orb_full_screen_context_enabled",
            "companion_orb_supervisor_enabled",
            "sensory_pingpong_enabled",
        }:
            self._save_session()

    def _apply_companion_orb_palette(self, value):
        palette_id = orb_palettes.normalize_palette_id(value)
        _update_runtime_config("companion_orb_color_palette", palette_id)
        if palette_id != orb_palettes.CUSTOM_PALETTE_ID:
            palette = orb_palettes.palette_for_id(palette_id)
            _update_runtime_config("companion_orb_custom_colors_enabled", True)
            self._sync_checkbox("companion_orb_custom_colors_enabled", True)
            for color_key, color_value in palette.as_color_settings().items():
                _update_runtime_config(color_key, color_value)
                self._sync_orb_color_control(color_key, color_value)
        self._apply_runtime_config()
        self._save_session()
        self._sync_orb_color_source_status()
        self._refresh_orb_color_preview()

    def _custom_orb_color_field_values(self):
        defaults = orb_palettes.palette_for_id(orb_palettes.CUSTOM_PALETTE_ID).as_color_settings()
        values = {}
        for key, default in defaults.items():
            widget = self._controls.get(key)
            raw_value = widget.text() if widget is not None and hasattr(widget, "text") else _runtime_config().get(key, default)
            values[key] = self._normalized_hex_color(raw_value, default)
        return values

    def _refresh_orb_color_preview(self):
        if self._orb_color_preview is None:
            return
        values = self._custom_orb_color_field_values()
        self._orb_color_preview.set_colors(
            values.get("companion_orb_primary_color", "#22d3ee"),
            values.get("companion_orb_secondary_color", "#38bdf8"),
            values.get("companion_orb_accent_color", "#a78bfa"),
            values.get("companion_orb_glow_color", "#67e8f9"),
        )

    def _apply_companion_orb_custom_colors(self, *, save=False):
        values = self._custom_orb_color_field_values()
        _update_runtime_config("companion_orb_custom_colors_enabled", True)
        self._sync_checkbox("companion_orb_custom_colors_enabled", True)
        for color_key, color_value in values.items():
            _update_runtime_config(color_key, color_value)
            self._sync_orb_color_control(color_key, color_value)
        self._apply_runtime_config()
        self._save_session()
        self._sync_orb_color_source_status()
        self._refresh_orb_color_preview()
        self._set_status("Companion Orb custom colors saved." if save else "Companion Orb custom colors applied.")

    def _sync_orb_color_control(self, key: str, color: str):
        widget = self._controls.get(key)
        if widget is not None and hasattr(widget, "setText"):
            try:
                widget.blockSignals(True)
                widget.setText(self._normalized_hex_color(color, color))
            finally:
                widget.blockSignals(False)
        swatch = self._orb_color_swatches.get(key)
        if swatch is not None:
            swatch.setStyleSheet(self._color_swatch_style(color))

    def _sync_orb_palette_combo(self, palette_id: str):
        combo = self._controls.get("companion_orb_color_palette")
        if combo is None or not hasattr(self, "_set_combo_value"):
            return
        try:
            combo.blockSignals(True)
            self._set_combo_value(combo, palette_id)
        finally:
            combo.blockSignals(False)

    def _sync_orb_color_source_status(self):
        label = self._orb_color_source_status
        if label is None:
            return
        if bool(_runtime_config().get("companion_orb_state_colors_enabled", False)):
            text = "Color source: State overrides"
        elif bool(_runtime_config().get("companion_orb_custom_colors_enabled", False)):
            palette = orb_palettes.palette_for_id(_runtime_config().get("companion_orb_color_palette", "custom"))
            text = f"Color source: {palette.label}"
        else:
            mode = str(_runtime_config().get("companion_orb_mood_color_mode", "automatic") or "automatic").strip().lower()
            if mode == "off":
                text = "Color source: Orb mood colors off"
            elif mode == "manual":
                mood = str(_runtime_config().get("companion_orb_manual_mood", "neutral") or "neutral").strip().lower()
                text = f"Color source: Manual Orb mood ({mood})"
            else:
                text = "Color source: Automatic Orb mood colors"
        label.setText(text)

    def build_tab(self):
        scroll, card_layout = self._build_card_shell(
            "companion_orb_overlay_addon_tab",
            "companion_orb_overlay_content",
            "companion_orb_overlay_card",
            "COMPANION ORB OVERLAY",
        )

        intro = QtWidgets.QLabel(
            "Own settings for the desktop Companion Orb. These controls manage the orb overlay, movement, particles, voice sync, sensory target, and hotkeys without changing AI Presence controls."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        card_layout.addWidget(intro)

        card_layout.addWidget(self._build_companion_orb_section())

        self.status_label = self._status_label("Companion Orb Overlay controls are ready.", "companion_orb_overlay_status_label")
        card_layout.addWidget(self.status_label)
        self.refresh_from_runtime()
        return scroll

    def _read_only_text(self, text, object_name, *, height=120):
        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName(object_name)
        editor.setReadOnly(True)
        editor.setPlainText(str(text or "").strip())
        editor.setMinimumHeight(int(height))
        editor.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        editor.setStyleSheet(
            f"QPlainTextEdit#{object_name} {{"
            "  background: rgba(3, 9, 17, 0.55);"
            "  border: 1px solid #29445f;"
            "  border-radius: 6px;"
            "  color: #dbeafe;"
            "  selection-background-color: #1d4ed8;"
            "  font-size: 11px;"
            "}"
        )
        return editor

    def _metadata_items_text(self, items):
        lines = []
        for item in list(items or []):
            if isinstance(item, dict):
                field = str(item.get("field") or "field").strip()
                description = str(item.get("description") or "").strip()
                if description:
                    lines.append(f"- {field}: {description}")
                else:
                    lines.append(f"- {field}")
            else:
                lines.append(f"- {item}")
        return "\n".join(lines) if lines else "- none declared"

    def _metadata_overview_text(self):
        metadata = dict(COMPANION_ORB_TARGET_METADATA or {})
        summary = {
            "target_source": metadata.get("target_source"),
            "privacy": metadata.get("privacy"),
            "prompt_fragment_enabled": metadata.get("prompt_fragment_enabled"),
        }
        return json.dumps(summary, indent=2, sort_keys=True)

    def _build_reply_style_prompt_editor(self):
        group, layout = self._section_group("Reply Style Prompt", "companion_orb_reply_style_prompt_group")
        hint = QtWidgets.QLabel(
            "Edit the instruction used when Companion Orb turns a visual focus cue into a spoken reply. Saved text overrides the recommended style prompt for that style only."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(hint)

        selector_row = QtWidgets.QHBoxLayout()
        selector_row.setContentsMargins(0, 0, 0, 0)
        selector_row.setSpacing(8)
        selector_row.addWidget(self._compact_label("Style"))
        style_combo = NoWheelComboBox()
        style_combo.setObjectName("companion_orb_reply_style_editor_combo")
        for label, value in ORB_RESPONSE_STYLES:
            style_combo.addItem(label, value)
        style_combo.setMinimumHeight(26)
        style_combo.setMaximumHeight(30)
        style_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._reply_style_prompt_combo = style_combo
        selector_row.addWidget(style_combo, 1)
        layout.addLayout(selector_row)

        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("companion_orb_reply_style_prompt_edit")
        editor.setMinimumHeight(145)
        editor.setPlaceholderText("Write the style instruction for Companion Orb replies...")
        editor.setStyleSheet(
            "QPlainTextEdit#companion_orb_reply_style_prompt_edit {"
            "  background: rgba(3, 9, 17, 0.55);"
            "  border: 1px solid #29445f;"
            "  border-radius: 6px;"
            "  color: #dbeafe;"
            "  selection-background-color: #1d4ed8;"
            "  font-size: 11px;"
            "}"
        )
        self._reply_style_prompt_edit = editor
        layout.addWidget(editor)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        save_button = QtWidgets.QPushButton("Save Style")
        save_button.setObjectName("btn_companion_orb_reply_style_save")
        load_button = QtWidgets.QPushButton("Load Saved")
        load_button.setObjectName("btn_companion_orb_reply_style_load")
        default_button = QtWidgets.QPushButton("Use Recommended")
        default_button.setObjectName("btn_companion_orb_reply_style_default")
        reset_all_button = QtWidgets.QPushButton("Reset All")
        reset_all_button.setObjectName("btn_companion_orb_reply_style_reset_all")
        for button in (save_button, load_button, default_button, reset_all_button):
            button.setMinimumHeight(27)
            button.setMaximumHeight(31)
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        status = QtWidgets.QLabel("")
        status.setObjectName("companion_orb_reply_style_prompt_status")
        status.setWordWrap(True)
        status.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self._reply_style_prompt_status = status
        layout.addWidget(status)

        style_combo.currentIndexChanged.connect(
            lambda *_args: None
            if self._syncing_reply_style_prompt
            else self._sync_reply_style_prompt_editor_from_runtime(self._selected_reply_style_prompt_style())
        )
        save_button.clicked.connect(lambda *_args: self._save_reply_style_prompt_override())
        load_button.clicked.connect(lambda *_args: self._sync_reply_style_prompt_editor_from_runtime(self._selected_reply_style_prompt_style()))
        default_button.clicked.connect(lambda *_args: self._reset_reply_style_prompt_override())
        reset_all_button.clicked.connect(lambda *_args: self._reset_all_reply_style_prompt_overrides())
        self._sync_reply_style_prompt_editor_from_runtime(
            _runtime_config().get("companion_orb_response_style", "friendly")
        )
        return group

    def _companion_orb_slider_group(self, title, object_name, sliders, *, max_columns=2):
        group, layout = self._section_group(title, object_name)
        grid = _ResponsiveGridWidget(min_column_width=238, max_columns=max_columns, horizontal_spacing=10, vertical_spacing=6)
        grid.setObjectName(f"{object_name}_grid")
        for spec in sliders:
            grid.add_widget(self._slider(*spec))
        layout.addWidget(grid)
        return group

    def _build_reader_settings_card(self):
        group, layout = self._section_group("Read Selected Text", "companion_orb_reader_settings_group")
        hint = QtWidgets.QLabel(
            "Right-click the orb to read clipboard text, read a marked area, or ask the orb to comment on marked text."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(hint)

        layout.addWidget(
            self._checkbox(
                "Exclude selected text from memory",
                "companion_orb_reader_exclude_from_memory_checkbox",
                "companion_orb_reader_exclude_from_memory",
                bool(COMPANION_ORB_READING_DEFAULTS["companion_orb_reader_exclude_from_memory"]),
            )
        )

        drop_guidance_group, drop_guidance_layout = self._section_group(
            "Drop Snapshot Reply",
            "companion_orb_smart_drop_guidance_group",
        )
        drop_guidance_hint = QtWidgets.QLabel(
            "Optional one-shot guidance for the normal spoken reply when you drop the orb on an image or text area."
        )
        drop_guidance_hint.setWordWrap(True)
        drop_guidance_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        drop_guidance_layout.addWidget(drop_guidance_hint)
        drop_guidance_row = QtWidgets.QHBoxLayout()
        drop_guidance_row.setContentsMargins(0, 0, 0, 0)
        drop_guidance_row.setSpacing(8)
        drop_guidance_row.addWidget(
            self._checkbox(
                "Smart drop replies",
                "companion_orb_smart_drop_guidance_enabled_checkbox",
                "companion_orb_smart_drop_guidance_enabled",
                False,
            )
        )
        drop_guidance_row.addWidget(self._compact_label("Mode"))
        drop_guidance_row.addWidget(
            self._combo(
                "companion_orb_smart_drop_guidance_mode_combo",
                COMPANION_ORB_SMART_DROP_GUIDANCE_MODES,
                "companion_orb_smart_drop_guidance_mode",
                "smart",
            ),
            1,
        )
        drop_guidance_layout.addLayout(drop_guidance_row)
        layout.addWidget(drop_guidance_group)

        chunk_row = QtWidgets.QHBoxLayout()
        chunk_row.setContentsMargins(0, 0, 0, 0)
        chunk_row.setSpacing(8)
        chunk_row.addWidget(self._compact_label("Read chunk size"))
        chunk_spin = NoWheelSpinBox()
        chunk_spin.setObjectName("companion_orb_reading_max_chunk_chars_spin")
        chunk_spin.setRange(100, 5000)
        chunk_spin.setSingleStep(100)
        chunk_spin.setValue(self._reading_chunk_size_value())
        chunk_spin.setMinimumHeight(26)
        chunk_spin.setMaximumHeight(30)
        chunk_spin.setMaximumWidth(110)
        chunk_spin.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        self._controls["companion_orb_reading_max_chunk_chars"] = chunk_spin
        chunk_spin.valueChanged.connect(
            lambda value, setting_key="companion_orb_reading_max_chunk_chars": self._on_setting_changed(setting_key, int(value))
        )
        chunk_row.addWidget(chunk_spin)
        chunk_row.addStretch(1)
        layout.addLayout(chunk_row)

        prompt_label = QtWidgets.QLabel("Comment behavior prompt")
        prompt_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
        layout.addWidget(prompt_label)

        editor = QtWidgets.QPlainTextEdit()
        editor.setObjectName("companion_orb_reader_commentary_prompt_edit")
        editor.setMinimumHeight(130)
        editor.setPlaceholderText("Write how the orb should comment on marked text...")
        editor.setStyleSheet(
            "QPlainTextEdit#companion_orb_reader_commentary_prompt_edit {"
            "  background: rgba(3, 9, 17, 0.55);"
            "  border: 1px solid #29445f;"
            "  border-radius: 6px;"
            "  color: #dbeafe;"
            "  selection-background-color: #1d4ed8;"
            "  font-size: 11px;"
            "}"
        )
        self._reader_commentary_prompt_edit = editor
        self._controls["companion_orb_reader_commentary_prompt"] = editor
        editor.installEventFilter(self)
        layout.addWidget(editor)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(8)
        reload_button = QtWidgets.QPushButton("Reload Saved")
        reload_button.setObjectName("btn_companion_orb_reader_commentary_reload")
        default_button = QtWidgets.QPushButton("Use Recommended")
        default_button.setObjectName("btn_companion_orb_reader_commentary_default")
        for button in (reload_button, default_button):
            button.setMinimumHeight(27)
            button.setMaximumHeight(31)
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        status = QtWidgets.QLabel("")
        status.setObjectName("companion_orb_reader_commentary_prompt_status")
        status.setWordWrap(True)
        status.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self._reader_commentary_prompt_status = status
        layout.addWidget(status)

        timer = QtCore.QTimer(editor)
        timer.setSingleShot(True)
        timer.setInterval(450)
        timer.timeout.connect(self._save_reader_commentary_prompt)
        self._reader_commentary_prompt_timer = timer
        editor.textChanged.connect(self._schedule_reader_commentary_prompt_save)
        reload_button.clicked.connect(lambda *_args: self._sync_reader_settings_from_runtime(force_prompt=True))
        default_button.clicked.connect(lambda *_args: self._reset_reader_commentary_prompt())
        self._sync_reader_settings_from_runtime(force_prompt=True)
        return group

    def _eye_tracking_screen_options(self):
        options = [("Primary display", "-1")]
        app = QtWidgets.QApplication.instance()
        screens = list(app.screens() or []) if app is not None else []
        for index, screen in enumerate(screens):
            name = str(screen.name() or f"Display {index + 1}").strip()
            geometry = screen.geometry()
            label = f"Display {index + 1}: {name} ({geometry.width()} x {geometry.height()})"
            options.append((label, str(index)))
        return options

    def _companion_orb_service(self):
        direct_service = getattr(self, "_companion_orb_direct_service", None)
        if direct_service is not None:
            return direct_service
        try:
            return self.context.get_service("ai_presence.companion_orb")
        except Exception:
            return None

    def set_companion_orb_service(self, service) -> None:
        self._companion_orb_direct_service = service
        refresh = getattr(self, "_refresh_eye_tracking_status", None)
        if callable(refresh):
            QtCore.QTimer.singleShot(0, refresh)

    def _browse_eye_tracking_dll(self):
        current = str(_runtime_config().get("companion_orb_eye_tracking_dll_path", "") or "").strip()
        start_dir = str(Path(current).parent) if current else str(Path.home())
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            None,
            "Select Tobii Stream Engine",
            start_dir,
            "Tobii Stream Engine (tobii_stream_engine.dll);;DLL files (*.dll)",
        )
        if not selected:
            return
        edit = self._controls.get("companion_orb_eye_tracking_dll_path")
        if isinstance(edit, QtWidgets.QLineEdit):
            edit.setText(str(selected))
        self._on_setting_changed("companion_orb_eye_tracking_dll_path", str(selected))
        self._reconnect_eye_tracking()

    def _reconnect_eye_tracking(self):
        orb = self._companion_orb_service()
        reconnect = getattr(orb, "reconnect_eye_tracking", None)
        if callable(reconnect):
            try:
                reconnect()
            except Exception:
                pass
        QtCore.QTimer.singleShot(120, self._refresh_eye_tracking_status)

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
                "error": "The Companion Orb eye-tracking service is unavailable.",
            }
        if not bool(result.get("ok")):
            message = str(result.get("error") or "Gaze calibration could not be changed.")
            if self._eye_tracking_calibration_status_label is not None:
                self._eye_tracking_calibration_status_label.setText(message)
                self._eye_tracking_calibration_status_label.setStyleSheet(
                    "color: #ef4444; font-size: 10px; font-weight: 600;"
                )
        QtCore.QTimer.singleShot(0, self._refresh_eye_tracking_status)
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
            _update_runtime_config("companion_orb_eye_tracking_calibration", {})
            self._save_session()
        return result

    def _react_at_gaze(self):
        orb = self._companion_orb_service()
        react = getattr(orb, "react_at_gaze", None)
        result = None
        if callable(react):
            try:
                result = react(force=True)
            except Exception:
                result = None
        if not isinstance(result, dict) or not bool(result.get("ok")):
            message = str((result or {}).get("error") or "No recent eye-tracker focus is available.")
            if self._eye_tracking_status_label is not None:
                self._eye_tracking_status_label.setText(message)
        QtCore.QTimer.singleShot(750, self._refresh_eye_tracking_status)

    def _refresh_eye_tracking_status(self):
        label = self._eye_tracking_status_label
        if label is None:
            return
        orb = self._companion_orb_service()
        getter = getattr(orb, "eye_tracking_status", None)
        try:
            status = dict(getter() or {}) if callable(getter) else {}
        except Exception:
            status = {}
        code = str(status.get("code") or "starting").strip().lower()
        connection_code = str(status.get("connection_code") or code).strip().lower()
        message = str(status.get("message") or "Companion Orb eye tracking is starting...").strip()
        label.setText(message)
        connection_text, color = _eye_tracking_connection_presentation(connection_code)
        label.setStyleSheet("color: #b8c7d9; font-size: 11px;")
        if self._eye_tracking_connection_label is not None:
            self._eye_tracking_connection_label.setText(connection_text)
        if self._eye_tracking_status_indicator is not None:
            self._eye_tracking_status_indicator.setAccessibleName(f"Eye tracking: {connection_text}")
            self._eye_tracking_status_indicator.setToolTip(f"Eye tracking: {connection_text}")
            self._eye_tracking_status_indicator.setStyleSheet(
                "QLabel#companion_orb_eye_tracking_status_indicator {"
                f" background: {color};"
                f" border: 2px solid {color};"
                " border-radius: 6px;"
                "}"
            )
        if self._eye_tracking_runtime_label is not None:
            resolved_path = str(status.get("dll_path") or "").strip()
            configured_path = str(
                _runtime_config().get("companion_orb_eye_tracking_dll_path", "") or ""
            ).strip()
            if resolved_path:
                source = "Selected runtime" if configured_path else "Automatic runtime"
                runtime_text = f"{source}: {resolved_path}"
            elif configured_path:
                runtime_text = f"Selected runtime: {configured_path}"
            else:
                runtime_text = "Automatic runtime: waiting for Stream Engine discovery"
            self._eye_tracking_runtime_label.setText(runtime_text)
            self._eye_tracking_runtime_label.setToolTip(runtime_text)
        if self._eye_tracking_blink_status_label is not None:
            allowed = bool(
                status.get(
                    "blink_click_allowed",
                    _runtime_config().get("companion_orb_eye_tracking_blink_click_allowed", True),
                )
            )
            enabled = bool(status.get("blink_click_enabled", False))
            if not allowed:
                blink_text = "Blink click unavailable"
                blink_color = "#94a3b8"
            elif enabled:
                blink_text = "Blink click enabled - quick blink clicks; two slow blinks disable"
                blink_color = "#22c55e"
            else:
                blink_text = "Blink click disabled - gaze on a radial button, then blink slowly twice"
                blink_color = "#f59e0b"
            self._eye_tracking_blink_status_label.setText(blink_text)
            self._eye_tracking_blink_status_label.setStyleSheet(
                f"color: {blink_color}; font-size: 10px; font-weight: 600;"
            )
        calibration = (
            dict(status.get("calibration") or {})
            if isinstance(status.get("calibration"), dict)
            else {}
        )
        calibration_state = str(
            calibration.get("state") or "not_calibrated"
        ).strip().lower()
        calibration_text, calibration_color = (
            _eye_tracking_calibration_presentation(calibration_state)
        )
        calibration_active = bool(calibration.get("active", False))
        if self._eye_tracking_calibration_indicator is not None:
            self._eye_tracking_calibration_indicator.setAccessibleName(
                f"Gaze calibration: {calibration_text}"
            )
            self._eye_tracking_calibration_indicator.setToolTip(
                f"Gaze calibration: {calibration_text}"
            )
            self._eye_tracking_calibration_indicator.setStyleSheet(
                "QLabel#companion_orb_eye_tracking_calibration_indicator {"
                f" background: {calibration_color};"
                f" border: 2px solid {calibration_color};"
                " border-radius: 5px;"
                "}"
            )
        if self._eye_tracking_calibration_status_label is not None:
            target_index = int(calibration.get("target_index", 0) or 0)
            target_count = int(calibration.get("target_count", 5) or 5)
            message = str(calibration.get("message") or calibration_text)
            if calibration_active and target_index > 0:
                message = f"{calibration_text} {target_index}/{target_count}: {message}"
            self._eye_tracking_calibration_status_label.setText(message)
            self._eye_tracking_calibration_status_label.setStyleSheet(
                f"color: {calibration_color}; font-size: 10px; font-weight: 600;"
            )
        if self._eye_tracking_calibration_result_label is not None:
            quality = str(calibration.get("quality") or "").strip()
            completed_at = str(calibration.get("completed_at") or "").strip()
            try:
                average_error = float(
                    calibration.get("average_error_px", 0.0) or 0.0
                )
            except (TypeError, ValueError):
                average_error = 0.0
            if quality:
                result_parts = [quality, f"{average_error:.1f} px average error"]
                if completed_at:
                    result_parts.append(completed_at)
                result_text = " | ".join(result_parts)
            else:
                result_text = (
                    "Five points, 3 seconds each, centered in the Tobii-supported area."
                )
            self._eye_tracking_calibration_result_label.setText(result_text)
            self._eye_tracking_calibration_result_label.setToolTip(result_text)
        if self._eye_tracking_calibration_start_button is not None:
            self._eye_tracking_calibration_start_button.setEnabled(
                not calibration_active
            )
        if self._eye_tracking_calibration_cancel_button is not None:
            self._eye_tracking_calibration_cancel_button.setEnabled(
                calibration_active
            )
        if self._eye_tracking_calibration_reset_button is not None:
            self._eye_tracking_calibration_reset_button.setEnabled(
                calibration_state == "calibrated"
            )

        pointer_clearance = (
            dict(status.get("pointer_clearance") or {})
            if isinstance(status.get("pointer_clearance"), dict)
            else {}
        )
        clearance_enabled = bool(
            pointer_clearance.get(
                "enabled",
                _runtime_config().get(
                    "companion_orb_eye_tracking_pointer_clearance_enabled",
                    False,
                ),
            )
        )
        clearance_text, clearance_color = (
            _eye_tracking_pointer_clearance_presentation(
                str(pointer_clearance.get("state") or "clear"),
                enabled=clearance_enabled,
            )
        )
        if self._eye_tracking_pointer_clearance_status_label is not None:
            self._eye_tracking_pointer_clearance_status_label.setText(
                clearance_text
            )
            self._eye_tracking_pointer_clearance_status_label.setStyleSheet(
                f"color: {clearance_color}; font-size: 10px; font-weight: 600;"
            )

    def _apply_stable_eye_tracking_movement_preset(self) -> None:
        preset = _stable_eye_tracking_movement_preset(
            _runtime_config().get("companion_orb_size", 92)
        )
        for key, value in preset.items():
            _update_runtime_config(key, self._normalize_setting(key, value))
        self._apply_runtime_config()
        self.refresh_from_runtime()
        self._save_session()
        self._set_status(
            "Stable Gaze preset applied. Idle, aware, mouse-avoidance, and playful-nudge movement are off."
        )
        QtCore.QTimer.singleShot(120, self._refresh_eye_tracking_status)

    def _build_eye_tracking_settings_card(self):
        group, layout = self._section_group("Tobii Eye Tracking", "companion_orb_eye_tracking_group")

        status_row = QtWidgets.QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(8)
        self._eye_tracking_status_indicator = QtWidgets.QLabel()
        self._eye_tracking_status_indicator.setObjectName("companion_orb_eye_tracking_status_indicator")
        self._eye_tracking_status_indicator.setFixedSize(12, 12)
        self._eye_tracking_connection_label = QtWidgets.QLabel("Connecting")
        self._eye_tracking_connection_label.setObjectName("companion_orb_eye_tracking_connection_label")
        self._eye_tracking_connection_label.setStyleSheet("color: #e5edf7; font-size: 12px; font-weight: 700;")
        status_row.addWidget(self._eye_tracking_status_indicator)
        status_row.addWidget(self._eye_tracking_connection_label)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self._eye_tracking_status_label = self._status_label(
            "Companion Orb eye tracking is starting...",
            "companion_orb_eye_tracking_status_label",
        )
        self._eye_tracking_status_label.setWordWrap(True)
        layout.addWidget(self._eye_tracking_status_label)

        self._eye_tracking_runtime_label = QtWidgets.QLabel(
            "Automatic runtime: waiting for Stream Engine discovery"
        )
        self._eye_tracking_runtime_label.setObjectName("companion_orb_eye_tracking_runtime_label")
        self._eye_tracking_runtime_label.setWordWrap(True)
        self._eye_tracking_runtime_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._eye_tracking_runtime_label.setStyleSheet("color: #8ea3b8; font-size: 10px;")
        layout.addWidget(self._eye_tracking_runtime_label)

        action_option = QtWidgets.QWidget()
        action_option.setObjectName("companion_orb_eye_tracking_action_option")
        action_option_layout = QtWidgets.QVBoxLayout(action_option)
        action_option_layout.setContentsMargins(0, 2, 0, 2)
        action_option_layout.setSpacing(2)
        action_checkbox = self._checkbox(
            "Enable Action gaze button",
            "companion_orb_eye_tracking_click_target_checkbox",
            "companion_orb_eye_tracking_click_target_enabled",
            False,
        )
        action_checkbox.setToolTip(
            "Enables system-wide application and browser control selection in the long-gaze radial menu. "
            "UI Automation supplies named controls when available, with visual detection as fallback."
        )
        action_option_layout.addWidget(action_checkbox)
        action_hint = QtWidgets.QLabel(
            "Action uses UI Automation to identify named controls and keeps visual detection as fallback."
        )
        action_hint.setObjectName("companion_orb_eye_tracking_action_hint")
        action_hint.setWordWrap(True)
        action_hint.setStyleSheet("color: #8ea3b8; font-size: 10px;")
        action_option_layout.addWidget(action_hint)
        layout.addWidget(action_option)

        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(8)
        selector_grid.setVerticalSpacing(5)
        selector_grid.addWidget(self._compact_label("Mode"), 0, 0)
        selector_grid.addWidget(
            self._combo(
                "companion_orb_eye_tracking_mode_combo",
                COMPANION_ORB_EYE_TRACKING_MODES,
                "companion_orb_eye_tracking_mode",
                "dwell",
            ),
            0,
            1,
        )
        selector_grid.addWidget(self._compact_label("Auto comments"), 0, 2)
        selector_grid.addWidget(
            self._combo(
                "companion_orb_eye_tracking_reaction_mode_combo",
                COMPANION_ORB_EYE_TRACKING_REACTION_MODES,
                "companion_orb_eye_tracking_reaction_mode",
                "meaningful",
            ),
            0,
            3,
        )
        selector_grid.addWidget(self._compact_label("Display"), 1, 0)
        selector_grid.addWidget(
            self._combo(
                "companion_orb_eye_tracking_screen_combo",
                self._eye_tracking_screen_options(),
                "companion_orb_eye_tracking_screen_index",
                -1,
            ),
            1,
            1,
            1,
            3,
        )
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 1)
        layout.addLayout(selector_grid)

        calibration_header = self._compact_label("Gaze Calibration")
        calibration_header.setStyleSheet(
            "color: #e5edf7; font-size: 11px; font-weight: 700;"
        )
        layout.addWidget(calibration_header)

        calibration_row = QtWidgets.QHBoxLayout()
        calibration_row.setContentsMargins(0, 0, 0, 0)
        calibration_row.setSpacing(8)
        self._eye_tracking_calibration_indicator = QtWidgets.QLabel()
        self._eye_tracking_calibration_indicator.setObjectName(
            "companion_orb_eye_tracking_calibration_indicator"
        )
        self._eye_tracking_calibration_indicator.setFixedSize(10, 10)
        calibration_row.addWidget(self._eye_tracking_calibration_indicator)
        self._eye_tracking_calibration_status_label = QtWidgets.QLabel(
            "No gaze calibration is saved."
        )
        self._eye_tracking_calibration_status_label.setObjectName(
            "companion_orb_eye_tracking_calibration_status_label"
        )
        self._eye_tracking_calibration_status_label.setWordWrap(True)
        calibration_row.addWidget(
            self._eye_tracking_calibration_status_label,
            1,
        )

        self._eye_tracking_calibration_start_button = QtWidgets.QPushButton(
            "Start"
        )
        self._eye_tracking_calibration_start_button.setObjectName(
            "companion_orb_eye_tracking_calibration_start_button"
        )
        self._eye_tracking_calibration_start_button.clicked.connect(
            self._start_eye_tracking_calibration
        )
        self._eye_tracking_calibration_cancel_button = QtWidgets.QPushButton(
            "Cancel"
        )
        self._eye_tracking_calibration_cancel_button.setObjectName(
            "companion_orb_eye_tracking_calibration_cancel_button"
        )
        self._eye_tracking_calibration_cancel_button.clicked.connect(
            self._cancel_eye_tracking_calibration
        )
        self._eye_tracking_calibration_reset_button = QtWidgets.QPushButton(
            "Reset"
        )
        self._eye_tracking_calibration_reset_button.setObjectName(
            "companion_orb_eye_tracking_calibration_reset_button"
        )
        self._eye_tracking_calibration_reset_button.clicked.connect(
            self._reset_eye_tracking_calibration
        )
        for button in (
            self._eye_tracking_calibration_start_button,
            self._eye_tracking_calibration_cancel_button,
            self._eye_tracking_calibration_reset_button,
        ):
            button.setMinimumHeight(26)
            button.setMaximumHeight(30)
            calibration_row.addWidget(button)
        layout.addLayout(calibration_row)

        self._eye_tracking_calibration_result_label = QtWidgets.QLabel(
            "Five points, 3 seconds each, centered in the Tobii-supported area."
        )
        self._eye_tracking_calibration_result_label.setObjectName(
            "companion_orb_eye_tracking_calibration_result_label"
        )
        self._eye_tracking_calibration_result_label.setWordWrap(True)
        self._eye_tracking_calibration_result_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self._eye_tracking_calibration_result_label.setStyleSheet(
            "color: #8ea3b8; font-size: 10px;"
        )
        layout.addWidget(self._eye_tracking_calibration_result_label)

        tuning_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=2, horizontal_spacing=10, vertical_spacing=6)
        for spec in (
            ("companion_orb_eye_tracking_dwell_ms", "companion_orb_eye_tracking_dwell_slider", "Dwell delay (ms)", 300, 2000, 700, True),
            ("companion_orb_eye_tracking_radius_px", "companion_orb_eye_tracking_radius_slider", "Stable radius (px)", 24, 180, 60, True),
            ("companion_orb_eye_tracking_smoothing", "companion_orb_eye_tracking_smoothing_slider", "Smoothing", 0.05, 0.85, 0.28, False),
            (
                "companion_orb_eye_tracking_radial_menu_opacity",
                "companion_orb_eye_tracking_radial_menu_opacity_slider",
                "Radial menu opacity",
                0.35,
                1.00,
                0.90,
                False,
            ),
            (
                "companion_orb_eye_tracking_reaction_cooldown_seconds",
                "companion_orb_eye_tracking_cooldown_slider",
                "Comment cooldown (s)",
                10,
                300,
                45,
                True,
            ),
        ):
            tuning_grid.add_widget(self._slider(*spec))
        layout.addWidget(tuning_grid)

        placement_header = self._compact_label("Orb Placement Offset")
        placement_header.setStyleSheet(
            "color: #e5edf7; font-size: 11px; font-weight: 700;"
        )
        layout.addWidget(placement_header)
        placement_grid = _ResponsiveGridWidget(
            min_column_width=250,
            max_columns=2,
            horizontal_spacing=10,
            vertical_spacing=6,
        )
        for spec in (
            (
                "companion_orb_eye_tracking_offset_x_px",
                "companion_orb_eye_tracking_offset_x_slider",
                "X offset (px)",
                -400,
                400,
                0,
                True,
            ),
            (
                "companion_orb_eye_tracking_offset_y_px",
                "companion_orb_eye_tracking_offset_y_slider",
                "Y offset (px)",
                -400,
                400,
                0,
                True,
            ),
        ):
            placement_grid.add_widget(self._slider(*spec))
        layout.addWidget(placement_grid)

        clearance_header = self._compact_label("Pointer Clearance")
        clearance_header.setStyleSheet(
            "color: #e5edf7; font-size: 11px; font-weight: 700;"
        )
        layout.addWidget(clearance_header)
        clearance_row = QtWidgets.QHBoxLayout()
        clearance_row.setContentsMargins(0, 0, 0, 0)
        clearance_row.setSpacing(10)
        clearance_row.addWidget(
            self._checkbox(
                "Move Orb away from pointer",
                "companion_orb_eye_tracking_pointer_clearance_checkbox",
                "companion_orb_eye_tracking_pointer_clearance_enabled",
                False,
            )
        )
        self._eye_tracking_pointer_clearance_status_label = QtWidgets.QLabel(
            "Off"
        )
        self._eye_tracking_pointer_clearance_status_label.setObjectName(
            "companion_orb_eye_tracking_pointer_clearance_status_label"
        )
        clearance_row.addWidget(
            self._eye_tracking_pointer_clearance_status_label
        )
        clearance_row.addStretch(1)
        layout.addLayout(clearance_row)

        clearance_grid = _ResponsiveGridWidget(
            min_column_width=250,
            max_columns=2,
            horizontal_spacing=10,
            vertical_spacing=6,
        )
        clearance_grid.add_widget(
            self._slider(
                "companion_orb_eye_tracking_pointer_clearance_distance_px",
                "companion_orb_eye_tracking_pointer_clearance_distance_slider",
                "Move distance (px)",
                40,
                400,
                160,
                True,
            )
        )
        clearance_grid.add_widget(
            self._slider(
                "companion_orb_eye_tracking_pointer_clearance_timeout_seconds",
                "companion_orb_eye_tracking_pointer_clearance_timeout_slider",
                "Interference timeout (s)",
                1,
                30,
                8,
                True,
            )
        )
        layout.addWidget(clearance_grid)

        long_gaze_row = QtWidgets.QWidget()
        long_gaze_row.setObjectName("companion_orb_eye_tracking_long_gaze_row")
        long_gaze_layout = QtWidgets.QHBoxLayout(long_gaze_row)
        long_gaze_layout.setContentsMargins(0, 2, 0, 0)
        long_gaze_layout.setSpacing(10)
        long_gaze_layout.addWidget(
            self._checkbox(
                "Enable long-gaze radial menu",
                "companion_orb_eye_tracking_long_gaze_checkbox",
                "companion_orb_eye_tracking_long_gaze_enabled",
                False,
            )
        )
        long_gaze_layout.addWidget(
            self._checkbox(
                "Expand area for text",
                "companion_orb_eye_tracking_expand_read_text_area_checkbox",
                "companion_orb_eye_tracking_expand_read_text_area",
                True,
            )
        )
        long_gaze_layout.addWidget(
            self._checkbox(
                "Charging focus beam",
                "companion_orb_eye_tracking_radial_focus_beam_checkbox",
                "companion_orb_eye_tracking_radial_focus_beam_enabled",
                True,
            )
        )
        long_gaze_layout.addStretch(1)
        layout.addWidget(long_gaze_row)

        gaze_timing_grid = QtWidgets.QGridLayout()
        gaze_timing_grid.setContentsMargins(0, 0, 0, 0)
        gaze_timing_grid.setHorizontalSpacing(8)
        gaze_timing_grid.setVerticalSpacing(5)

        long_gaze_spin = NoWheelSpinBox()
        long_gaze_spin.setObjectName("companion_orb_eye_tracking_long_gaze_ms_spin")
        long_gaze_spin.setRange(1000, 15000)
        long_gaze_spin.setSingleStep(250)
        long_gaze_spin.setSuffix(" ms")
        long_gaze_spin.setKeyboardTracking(False)
        long_gaze_spin.setValue(
            self._normalize_setting(
                "companion_orb_eye_tracking_long_gaze_ms",
                _runtime_config().get("companion_orb_eye_tracking_long_gaze_ms", 3000),
            )
        )
        long_gaze_spin.setMinimumHeight(26)
        long_gaze_spin.setMaximumHeight(30)
        self._controls["companion_orb_eye_tracking_long_gaze_ms"] = long_gaze_spin
        long_gaze_spin.valueChanged.connect(
            lambda value: self._on_setting_changed("companion_orb_eye_tracking_long_gaze_ms", value)
        )

        button_gaze_spin = NoWheelSpinBox()
        button_gaze_spin.setObjectName("companion_orb_eye_tracking_radial_button_gaze_ms_spin")
        button_gaze_spin.setRange(250, 3000)
        button_gaze_spin.setSingleStep(50)
        button_gaze_spin.setSuffix(" ms")
        button_gaze_spin.setKeyboardTracking(False)
        button_gaze_spin.setValue(
            self._normalize_setting(
                "companion_orb_eye_tracking_radial_button_gaze_ms",
                _runtime_config().get("companion_orb_eye_tracking_radial_button_gaze_ms", 650),
            )
        )
        button_gaze_spin.setMinimumHeight(26)
        button_gaze_spin.setMaximumHeight(30)
        self._controls["companion_orb_eye_tracking_radial_button_gaze_ms"] = button_gaze_spin
        button_gaze_spin.valueChanged.connect(
            lambda value: self._on_setting_changed(
                "companion_orb_eye_tracking_radial_button_gaze_ms",
                value,
            )
        )

        gaze_timing_grid.addWidget(self._compact_label("Long gaze"), 0, 0)
        gaze_timing_grid.addWidget(long_gaze_spin, 0, 1)
        gaze_timing_grid.addWidget(self._compact_label("Button gaze"), 0, 2)
        gaze_timing_grid.addWidget(button_gaze_spin, 0, 3)
        gaze_timing_grid.setColumnStretch(1, 1)
        gaze_timing_grid.setColumnStretch(3, 1)
        layout.addLayout(gaze_timing_grid)
        layout.addWidget(
            self._color_setting_row(
                "Gaze timer color",
                "companion_orb_eye_tracking_gaze_timer_color",
                "#facc15",
            )
        )

        blink_header = self._compact_label("Blink click")
        blink_header.setStyleSheet("color: #e5edf7; font-size: 11px; font-weight: 700;")
        layout.addWidget(blink_header)
        blink_state_row = QtWidgets.QHBoxLayout()
        blink_state_row.setContentsMargins(0, 0, 0, 0)
        blink_state_row.setSpacing(10)
        blink_state_row.addWidget(
            self._checkbox(
                "Allow blink and eye commands",
                "companion_orb_eye_tracking_blink_click_allowed_checkbox",
                "companion_orb_eye_tracking_blink_click_allowed",
                True,
            )
        )
        self._eye_tracking_blink_status_label = QtWidgets.QLabel(
            "Blink click disabled - gaze on a radial button, then blink slowly twice"
        )
        self._eye_tracking_blink_status_label.setObjectName(
            "companion_orb_eye_tracking_blink_status_label"
        )
        self._eye_tracking_blink_status_label.setWordWrap(True)
        blink_state_row.addWidget(self._eye_tracking_blink_status_label, 1)
        layout.addLayout(blink_state_row)

        blink_tuning_grid = _ResponsiveGridWidget(
            min_column_width=250,
            max_columns=2,
            horizontal_spacing=10,
            vertical_spacing=6,
        )
        for spec in (
            (
                "companion_orb_eye_tracking_blink_min_ms",
                "companion_orb_eye_tracking_blink_min_ms_slider",
                "Minimum blink (ms)",
                40,
                300,
                80,
                True,
            ),
            (
                "companion_orb_eye_tracking_blink_slow_min_ms",
                "companion_orb_eye_tracking_blink_slow_min_ms_slider",
                "Slow blink (ms)",
                150,
                700,
                260,
                True,
            ),
            (
                "companion_orb_eye_tracking_blink_max_ms",
                "companion_orb_eye_tracking_blink_max_ms_slider",
                "Maximum blink (ms)",
                400,
                1500,
                900,
                True,
            ),
            (
                "companion_orb_eye_tracking_blink_recovery_ms",
                "companion_orb_eye_tracking_blink_recovery_ms_slider",
                "Recovery stability (ms)",
                30,
                300,
                80,
                True,
            ),
            (
                "companion_orb_eye_tracking_blink_double_gap_ms",
                "companion_orb_eye_tracking_blink_double_gap_ms_slider",
                "Double-blink window (ms)",
                400,
                2500,
                1200,
                True,
            ),
            (
                "companion_orb_eye_tracking_blink_click_cooldown_ms",
                "companion_orb_eye_tracking_blink_click_cooldown_ms_slider",
                "Click cooldown (ms)",
                200,
                1500,
                450,
                True,
            ),
        ):
            blink_tuning_grid.add_widget(self._slider(*spec))
        layout.addWidget(blink_tuning_grid)

        command_header = self._compact_label("Eye commands")
        command_header.setStyleSheet("color: #e5edf7; font-size: 11px; font-weight: 700;")
        layout.addWidget(command_header)
        eye_command_grid = _ResponsiveGridWidget(
            min_column_width=250,
            max_columns=2,
            horizontal_spacing=10,
            vertical_spacing=6,
        )
        for spec in (
            (
                "companion_orb_eye_tracking_menu_blink_min_ms",
                "companion_orb_eye_tracking_menu_blink_min_ms_slider",
                "Long-blink minimum (ms)",
                700,
                1800,
                1000,
                True,
            ),
            (
                "companion_orb_eye_tracking_menu_blink_max_ms",
                "companion_orb_eye_tracking_menu_blink_max_ms_slider",
                "Long-blink maximum (ms)",
                1200,
                3000,
                2000,
                True,
            ),
            (
                "companion_orb_eye_tracking_triple_blink_gap_ms",
                "companion_orb_eye_tracking_triple_blink_gap_ms_slider",
                "Triple-blink window (ms)",
                200,
                900,
                450,
                True,
            ),
            (
                "companion_orb_eye_tracking_back_cooldown_ms",
                "companion_orb_eye_tracking_back_cooldown_ms_slider",
                "Back cooldown (ms)",
                500,
                5000,
                1500,
                True,
            ),
            (
                "companion_orb_eye_tracking_scroll_speed",
                "companion_orb_eye_tracking_scroll_speed_slider",
                "Scroll speed",
                1,
                10,
                5,
                True,
            ),
            (
                "companion_orb_eye_tracking_scroll_dead_zone_px",
                "companion_orb_eye_tracking_scroll_dead_zone_px_slider",
                "Scroll dead zone (px)",
                40,
                300,
                100,
                True,
            ),
        ):
            eye_command_grid.add_widget(self._slider(*spec))
        layout.addWidget(eye_command_grid)

        dll_row = QtWidgets.QHBoxLayout()
        dll_row.setContentsMargins(0, 0, 0, 0)
        dll_row.setSpacing(6)
        dll_row.addWidget(self._compact_label("Stream Engine"))
        dll_row.addWidget(
            self._line_edit(
                "companion_orb_eye_tracking_dll_path_edit",
                "companion_orb_eye_tracking_dll_path",
                "",
            ),
            1,
        )
        browse_button = QtWidgets.QPushButton("Browse")
        browse_button.setObjectName("companion_orb_eye_tracking_browse_button")
        browse_button.clicked.connect(self._browse_eye_tracking_dll)
        dll_row.addWidget(browse_button)
        layout.addLayout(dll_row)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        stable_preset_button = QtWidgets.QPushButton("Stable Gaze Preset")
        stable_preset_button.setObjectName("companion_orb_eye_tracking_stable_preset_button")
        stable_preset_button.clicked.connect(self._apply_stable_eye_tracking_movement_preset)
        reconnect_button = QtWidgets.QPushButton("Reconnect")
        reconnect_button.setObjectName("companion_orb_eye_tracking_reconnect_button")
        reconnect_button.clicked.connect(self._reconnect_eye_tracking)
        react_button = QtWidgets.QPushButton("React now")
        react_button.setObjectName("companion_orb_eye_tracking_react_button")
        react_button.clicked.connect(self._react_at_gaze)
        action_row.addWidget(stable_preset_button)
        action_row.addWidget(reconnect_button)
        action_row.addWidget(react_button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self._eye_tracking_status_timer.start()
        QtCore.QTimer.singleShot(0, self._refresh_eye_tracking_status)
        return group

    def _build_companion_orb_section(self):
        group = QtWidgets.QGroupBox("Companion Orb Overlay")
        group.setObjectName("companion_orb_overlay_group")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Small click-through desktop orb for AI state, TTS audio level, mood colors, and targeted hidden sensory focus."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        layout.addWidget(intro)

        tabs, tab_layouts = self._build_companion_orb_main_tabs()
        layout.addWidget(tabs)

        overview_page_layout = tab_layouts["Overview"]
        look_page_layout = tab_layouts["Look"]
        behavior_page_layout = tab_layouts["Behavior"]
        eye_tracking_page_layout = tab_layouts["Eye Tracking"]
        reading_page_layout = tab_layouts["Reading"]
        awareness_page_layout = tab_layouts["Awareness"]
        hotkeys_page_layout = tab_layouts["Hotkeys"]
        advanced_page_layout = tab_layouts["Advanced"]

        display_group, display_layout = self._section_group("Display & Actions", "companion_orb_display_group")
        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(8)
        selector_grid.setVerticalSpacing(4)
        selector_grid.addWidget(self._checkbox("Enable Companion Orb Overlay", "companion_orb_enabled_checkbox", "companion_orb_enabled", False), 0, 0, 1, 2)
        selector_grid.addWidget(self._compact_label("Display"), 0, 2)
        selector_grid.addWidget(self._combo("companion_orb_display_mode_combo", ORB_DISPLAY_MODES, "companion_orb_display_mode", "off"), 0, 3)
        selector_grid.addWidget(self._compact_label("Position"), 1, 0)
        selector_grid.addWidget(self._combo("companion_orb_position_combo", ORB_POSITIONS, "companion_orb_position", "bottom-right"), 1, 1)
        selector_grid.addWidget(self._compact_label("Reply style"), 1, 2)
        reply_style_combo = self._combo("companion_orb_response_style_combo", ORB_RESPONSE_STYLES, "companion_orb_response_style", "friendly")
        reply_style_combo.currentIndexChanged.connect(
            lambda *_args, combo=reply_style_combo: self._sync_reply_style_prompt_editor_from_runtime(combo.currentData())
        )
        selector_grid.addWidget(
            reply_style_combo,
            1,
            3,
            1,
            1,
        )
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 1)
        display_layout.addLayout(selector_grid)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        for label, handler, object_name in (
            ("Show Orb", self._show_companion_orb, "companion_orb_show_button"),
            ("Edit Mode", self._toggle_companion_orb_edit_mode, "companion_orb_edit_mode_button"),
            ("Placement Mode", self._toggle_companion_orb_placement_mode, "companion_orb_placement_mode_button"),
            ("Clear Target", self._clear_companion_orb_target, "companion_orb_clear_target_button"),
            ("Reset Position", self._reset_companion_orb_position, "companion_orb_reset_position_button"),
        ):
            button = QtWidgets.QPushButton(label)
            button.setObjectName(object_name)
            button.setMinimumHeight(27)
            button.setMaximumHeight(31)
            button.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            button.clicked.connect(handler)
            action_row.addWidget(button)
        action_row.addStretch(1)
        display_layout.addLayout(action_row)
        overview_page_layout.addWidget(display_group)

        window_group, window_layout = self._section_group("Window", "companion_orb_window_toggles_group")
        self._add_checkbox_stack(
            window_layout,
            (
                self._checkbox("Always on top", "companion_orb_always_on_top_checkbox", "companion_orb_always_on_top", True),
                self._checkbox("Remember position", "companion_orb_remember_position_checkbox", "companion_orb_remember_position", True),
            ),
        )
        overview_page_layout.addWidget(window_group)

        appearance_group, appearance_layout = self._section_group("Appearance", "companion_orb_appearance_group")
        appearance_grid = QtWidgets.QGridLayout()
        appearance_grid.setContentsMargins(0, 0, 0, 0)
        appearance_grid.setHorizontalSpacing(8)
        appearance_grid.setVerticalSpacing(4)
        appearance_grid.addWidget(self._compact_label("Style"), 0, 0)
        appearance_grid.addWidget(self._combo("companion_orb_visual_style_combo", ORB_VISUAL_STYLES, "companion_orb_visual_style", "neural_spark"), 0, 1)
        appearance_grid.setColumnStretch(1, 1)
        appearance_layout.addLayout(appearance_grid)

        visual_group, visual_layout = self._section_group("Visual Effects", "companion_orb_visual_toggles_group")
        self._add_checkbox_stack(
            visual_layout,
            (
                self._checkbox("Orb voice sync", "companion_orb_voice_sync_enabled_checkbox", "companion_orb_voice_sync_enabled", True),
                self._checkbox("Falling particles", "companion_orb_falling_particles_enabled_checkbox", "companion_orb_falling_particles_enabled", False),
                self._checkbox("Particles", "companion_orb_particles_enabled_checkbox", "companion_orb_particles_enabled", True),
                self._checkbox("Shader effects", "companion_orb_shaders_enabled_checkbox", "companion_orb_shaders_enabled", True),
            ),
        )

        toggle_grid = _ResponsiveGridWidget(min_column_width=235, max_columns=2, horizontal_spacing=10, vertical_spacing=8)
        toggle_grid.setObjectName("companion_orb_toggle_groups_grid")

        behavior_group, behavior_layout = self._section_group("Movement", "companion_orb_behavior_toggles_group")
        self._add_checkbox_stack(
            behavior_layout,
            (
                self._checkbox("Movement enabled", "companion_orb_movement_enabled_checkbox", "companion_orb_movement_enabled", True),
                self._checkbox("Aware motion", "companion_orb_aware_motion_enabled_checkbox", "companion_orb_aware_motion_enabled", True),
                self._checkbox("Avoid center", "companion_orb_avoid_center_checkbox", "companion_orb_avoid_center", True),
                self._checkbox("Avoid mouse", "companion_orb_avoid_mouse_checkbox", "companion_orb_avoid_mouse", False),
                self._checkbox("Mouse-near fade", "companion_orb_mouse_near_fade_checkbox", "companion_orb_mouse_near_fade", False),
            ),
        )

        interaction_group, interaction_layout = self._section_group("Pointer Interaction", "companion_orb_interaction_toggles_group")
        self._add_checkbox_stack(
            interaction_layout,
            (
                self._checkbox("Click-through by default", "companion_orb_click_through_default_checkbox", "companion_orb_click_through_default", False),
            ),
        )

        toggle_grid.add_widgets((behavior_group, interaction_group))
        behavior_page_layout.addWidget(toggle_grid)

        slider_group, slider_group_layout = self._section_group("Orb Tuning", "companion_orb_tuning_group")
        slider_group_layout.addWidget(self._build_companion_orb_color_workbench())

        state_group, state_layout = self._section_group("State Overrides", "companion_orb_state_overrides_group")
        state_toggle_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=2, horizontal_spacing=10, vertical_spacing=6)
        state_toggle_grid.setObjectName("companion_orb_state_override_toggle_grid")
        state_toggle_grid.add_widgets(
            (
                self._checkbox(
                    "State color overrides",
                    "companion_orb_state_colors_enabled_checkbox",
                    "companion_orb_state_colors_enabled",
                    False,
                ),
                self._checkbox(
                    "State animation overrides",
                    "companion_orb_state_animation_enabled_checkbox",
                    "companion_orb_state_animation_enabled",
                    False,
                ),
            )
        )
        state_layout.addWidget(state_toggle_grid)

        state_color_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=3, horizontal_spacing=10, vertical_spacing=6)
        state_color_grid.setObjectName("companion_orb_state_color_grid")
        for label, key, default in (
            ("Idle", "companion_orb_idle_color", "#38bdf8"),
            ("Thinking", "companion_orb_thinking_color", "#a78bfa"),
            ("Speaking", "companion_orb_speaking_color", "#f472b6"),
        ):
            state_color_grid.add_widget(self._color_setting_row(label, key, default))
        state_layout.addWidget(state_color_grid)

        state_animation_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=3, horizontal_spacing=10, vertical_spacing=6)
        state_animation_grid.setObjectName("companion_orb_state_animation_grid")
        for label, key, default in (
            ("Idle animation", "companion_orb_idle_animation", "calm_breathe"),
            ("Thinking animation", "companion_orb_thinking_animation", "thinking_swirl"),
            ("Speaking animation", "companion_orb_speaking_animation", "voice_ripple"),
        ):
            row = QtWidgets.QWidget()
            row.setObjectName(f"{key}_row")
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            row_layout.addWidget(self._compact_label(label))
            row_layout.addWidget(self._combo(f"{key}_combo", ORB_STATE_ANIMATIONS, key, default), 1)
            state_animation_grid.add_widget(row)
        state_layout.addWidget(state_animation_grid)
        slider_group_layout.addWidget(state_group)

        look_tuning_cards = _ResponsiveGridWidget(min_column_width=330, max_columns=2, horizontal_spacing=12, vertical_spacing=8)
        look_tuning_cards.setObjectName("companion_orb_tuning_cards_grid")
        look_tuning_cards.add_widgets(
            (
                self._companion_orb_slider_group(
                    "Size & Visibility",
                    "companion_orb_size_visibility_group",
                    (
                        ("companion_orb_size", "companion_orb_size_slider", "Orb Size", 36, 220, 92, True),
                        ("companion_orb_opacity", "companion_orb_opacity_slider", "Orb Opacity", 0.10, 1.00, 0.82, False),
                    ),
                ),
                self._companion_orb_slider_group(
                    "Visual Texture",
                    "companion_orb_visual_texture_group",
                    (
                        ("companion_orb_trail_length", "companion_orb_trail_length_slider", "Trail Length", 0.00, 1.00, 0.55, False),
                        ("companion_orb_particle_density", "companion_orb_particle_density_slider", "Orb Particles", 0, 120, 30, True),
                        ("companion_orb_falling_particle_density", "companion_orb_falling_particle_density_slider", "Drip Particles", 0, 80, 18, True),
                        ("companion_orb_falling_particle_lifetime", "companion_orb_falling_particle_lifetime_slider", "Drip Lifetime", 0.80, 8.00, 3.8, False),
                        ("companion_orb_smoke_intensity", "companion_orb_smoke_intensity_slider", "Smoke Intensity", 0.00, 1.00, 0.35, False),
                        ("companion_orb_glow_strength", "companion_orb_glow_strength_slider", "Orb Glow", 0.00, 1.75, 1.0, False),
                        ("companion_orb_mood_color_intensity", "companion_orb_mood_intensity_slider", "Orb Mood Color", 0.00, 1.00, 0.85, False),
                    ),
                ),
                self._companion_orb_slider_group(
                    "Voice Sync",
                    "companion_orb_voice_sync_group",
                    (
                        ("companion_orb_speaking_reactivity", "companion_orb_speaking_reactivity_slider", "Orb Voice Reactivity", 0.10, 1.50, 0.85, False),
                    ),
                ),
            )
        )
        slider_group_layout.addWidget(look_tuning_cards)
        look_page_layout.addWidget(slider_group)
        look_basics_grid = _ResponsiveGridWidget(min_column_width=300, max_columns=2, horizontal_spacing=12, vertical_spacing=8)
        look_basics_grid.setObjectName("companion_orb_look_basics_grid")
        look_basics_grid.add_widgets((appearance_group, visual_group))
        look_page_layout.addWidget(look_basics_grid)

        behavior_tuning_cards = _ResponsiveGridWidget(min_column_width=330, max_columns=2, horizontal_spacing=12, vertical_spacing=8)
        behavior_tuning_cards.setObjectName("companion_orb_behavior_tuning_cards_grid")
        behavior_tuning_cards.add_widgets(
            (
                self._companion_orb_slider_group(
                    "Aware Movement",
                    "companion_orb_aware_movement_group",
                    (
                        ("companion_orb_movement_speed", "companion_orb_movement_speed_slider", "Movement Speed", 0.10, 1.50, 0.65, False),
                        ("companion_orb_movement_range", "companion_orb_movement_range_slider", "Movement Range", 0, 90, 18, True),
                        ("companion_orb_return_home_delay", "companion_orb_return_delay_slider", "Return-home Delay", 0.25, 30.00, 2.5, False),
                        ("companion_orb_awareness", "companion_orb_awareness_slider", "Awareness", 0.00, 1.00, 0.55, False),
                        ("companion_orb_focus_pull", "companion_orb_focus_pull_slider", "Focus Pull", 0.00, 1.00, 0.65, False),
                        ("companion_orb_idle_pause", "companion_orb_idle_pause_slider", "Idle Pauses", 0.00, 1.00, 0.45, False),
                    ),
                ),
                self._companion_orb_slider_group(
                    "Pointer & Interaction",
                    "companion_orb_pointer_interaction_group",
                    (
                        ("companion_orb_harassment_timer_seconds", "companion_orb_harassment_timer_slider", "Playful nudge delay", 5, 300, 45, True),
                        ("companion_orb_mouse_near_fade_distance", "companion_orb_mouse_fade_distance_slider", "Mouse Fade Distance", 24, 420, 120, True),
                        ("companion_orb_mouse_near_opacity", "companion_orb_mouse_near_opacity_slider", "Mouse-near Opacity", 0.05, 1.00, 0.28, False),
                    ),
                ),
            )
        )
        behavior_page_layout.addWidget(behavior_tuning_cards)
        eye_tracking_page_layout.addWidget(self._build_eye_tracking_settings_card())

        reading_page_layout.addWidget(self._build_reader_settings_card())
        reading_page_layout.addWidget(self._build_reply_style_prompt_editor())
        awareness_page_layout.addWidget(self._build_companion_orb_sensory_tabs())

        hotkey_group, hotkey_layout = self._section_group("Hotkeys", "companion_orb_hotkeys_group")
        hotkey_layout.addWidget(self._checkbox("Enable Companion Orb hotkeys", "companion_orb_hotkeys_enabled_checkbox", "companion_orb_hotkeys_enabled", True))
        hotkey_grid = _ResponsiveGridWidget(min_column_width=230, max_columns=3, horizontal_spacing=10, vertical_spacing=6)
        hotkey_grid.setObjectName("companion_orb_hotkey_responsive_grid")
        hotkeys = [
            ("Toggle", "companion_orb_toggle_hotkey", "Ctrl+Alt+O"),
            ("Edit", "companion_orb_edit_hotkey", "Ctrl+Alt+Shift+O"),
            ("Placement", "companion_orb_placement_hotkey", "Ctrl+Alt+P"),
            ("Clear Target", "companion_orb_clear_target_hotkey", "Ctrl+Alt+Backspace"),
            ("Click-through", "companion_orb_click_through_hotkey", "Ctrl+Alt+C"),
            ("Reset Position", "companion_orb_reset_position_hotkey", "Ctrl+Alt+R"),
            ("React at gaze", "companion_orb_eye_tracking_hotkey", "Ctrl+Alt+G"),
        ]
        for label, key, default in hotkeys:
            hotkey_row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(hotkey_row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            row_layout.addWidget(self._compact_label(label))
            row_layout.addWidget(self._line_edit(f"{key}_edit", key, default), 1)
            hotkey_grid.add_widget(hotkey_row)
        hotkey_layout.addWidget(hotkey_grid)
        hotkeys_page_layout.addWidget(hotkey_group)

        advanced_page_layout.addWidget(self._build_companion_orb_debug_diagnostics_card())

        runtime_group, runtime_layout = self._section_group("Runtime & Performance", "companion_orb_runtime_performance_group")
        self._add_checkbox_stack(
            runtime_layout,
            (
                self._checkbox("External runtime for orb animation", "companion_orb_external_runtime_enabled_checkbox", "companion_orb_external_runtime_enabled", True),
                self._checkbox("Reduced effects", "companion_orb_reduced_effects_checkbox", "companion_orb_reduced_effects", False),
            ),
        )
        runtime_layout.addWidget(
            self._companion_orb_slider_group(
                "Timing",
                "companion_orb_timing_group",
                (
                    ("companion_orb_frame_rate", "companion_orb_frame_rate_slider", "Orb Frame Rate", 30, 120, 60, True),
                    ("companion_orb_audio_refresh_hz", "companion_orb_audio_refresh_slider", "Orb Sync Rate", 5, 30, 24, True),
                ),
            )
        )
        advanced_page_layout.addWidget(runtime_group)

        for tab_layout in tab_layouts.values():
            tab_layout.addStretch(1)

        self._apply_companion_orb_tooltips(group)
        self._sync_orb_color_source_status()
        return group

    def _companion_orb_settings_tab_page(self, object_name):
        page = QtWidgets.QWidget()
        page.setObjectName(object_name)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)
        return page, layout

    def _build_companion_orb_main_tabs(self):
        tabs = NoWheelTabWidget()
        tabs.setObjectName("companion_orb_main_tabs")
        tab_titles = ("Overview", "Look", "Behavior", "Eye Tracking", "Reading", "Awareness", "Hotkeys", "Advanced")
        tab_layouts = {}
        for title in tab_titles:
            object_name = (
                "companion_orb_eye_tracking_tab"
                if title == "Eye Tracking"
                else f"companion_orb_{title.lower()}_tab"
            )
            page, page_layout = self._companion_orb_settings_tab_page(object_name)
            tabs.addTab(page, title)
            tab_layouts[title] = page_layout
        for index, tooltip in enumerate(
            (
                "Enable, place, and show the Companion Orb.",
                "Orb renderer, palette, mood tint, and visual texture.",
                "Movement, pointer behavior, and focus pull tuning.",
                "Local Tobii connection, gaze modes, reactions, and Stream Engine settings.",
                "Right-click reading, selected-text comments, and reply prompt guidance.",
                "Background capture target and personality rules.",
                "Keyboard shortcuts for common Companion Orb actions.",
                "External runtime and timing/performance controls.",
            )
        ):
            tabs.setTabToolTip(index, tooltip)
        self._apply_companion_orb_main_tab_style(tabs)
        return tabs, tab_layouts

    def _apply_companion_orb_main_tab_style(self, tabs):
        if tabs is None:
            return
        if not isinstance(tabs.tabBar(), _CompanionOrbSensoryTabBar):
            previous_bar = tabs.tabBar()
            current_index = tabs.currentIndex()
            entries = []
            for index in range(tabs.count()):
                entries.append(
                    {
                        "widget": tabs.widget(index),
                        "text": tabs.tabText(index),
                        "icon": tabs.tabIcon(index),
                        "tooltip": tabs.tabToolTip(index),
                        "enabled": tabs.isTabEnabled(index),
                        "data": previous_bar.tabData(index) if previous_bar is not None else None,
                    }
                )
            while tabs.count():
                tabs.removeTab(0)
            tab_bar = _CompanionOrbSensoryTabBar(tabs)
            tabs.setTabBar(tab_bar)
            for entry in entries:
                widget = entry["widget"]
                icon = entry["icon"]
                text = str(entry["text"] or "")
                if isinstance(icon, QtGui.QIcon) and not icon.isNull():
                    index = tabs.addTab(widget, icon, text)
                else:
                    index = tabs.addTab(widget, text)
                tooltip = str(entry["tooltip"] or "")
                if tooltip:
                    tabs.setTabToolTip(index, tooltip)
                tabs.setTabEnabled(index, bool(entry["enabled"]))
                tab_bar.setTabData(index, entry["data"])
            if entries:
                tabs.setCurrentIndex(min(max(0, current_index), len(entries) - 1))

        tabs.setIconSize(QtCore.QSize(36, 36))
        tabs.setUsesScrollButtons(True)
        tab_bar = tabs.tabBar()
        if tab_bar is not None:
            tab_bar.setDrawBase(False)
            tab_bar.setExpanding(False)
            tab_bar.setUsesScrollButtons(True)

        specs = {
            "Overview": ("overview", "#22d3ee"),
            "Look": ("look", "#f472b6"),
            "Behavior": ("behavior", "#22c55e"),
            "Eye Tracking": ("eye_tracking", "#22c55e"),
            "Reading": ("reading", "#f59e0b"),
            "Awareness": ("awareness", "#a78bfa"),
            "Hotkeys": ("hotkeys", "#38bdf8"),
            "Advanced": ("advanced", "#94a3b8"),
        }
        for index in range(tabs.count()):
            title = str(tabs.tabText(index) or "")
            icon_key, accent = specs.get(title, ("fallback", "#60a5fa"))
            tabs.setTabIcon(index, _companion_orb_sensory_tab_icon(icon_key, accent))
            if tab_bar is not None:
                tab_bar.setTabData(index, {"accent": accent, "icon": icon_key})

        style = """
/* nc-companion-orb-main-tabs:start */
QTabWidget#companion_orb_main_tabs::tab-bar {
    left: 4px;
}
QTabWidget#companion_orb_main_tabs QTabBar {
    background: #122033;
    padding-top: 4px;
    padding-bottom: 4px;
}
QTabWidget#companion_orb_main_tabs QTabBar::scroller {
    width: 32px;
}
QTabWidget#companion_orb_main_tabs QTabBar QToolButton {
    background: #1b2b40;
    color: #d8e2ee;
    border: 1px solid #416184;
    border-radius: 8px;
    width: 20px;
    min-width: 20px;
    max-width: 20px;
    padding: 0px;
    margin: 8px 1px 8px 1px;
}
QTabWidget#companion_orb_main_tabs QTabBar QToolButton:hover {
    background: #243956;
}
QTabWidget#companion_orb_main_tabs QTabBar::tab {
    background: transparent;
    color: #d8e2ee;
    font-weight: 700;
    border: none;
    min-width: 0px;
    min-height: 68px;
    padding: 0px;
    margin-right: 5px;
    margin-bottom: 2px;
    border-radius: 9px;
}
QTabWidget#companion_orb_main_tabs QTabBar::tab:selected,
QTabWidget#companion_orb_main_tabs QTabBar::tab:hover {
    background: transparent;
    border: none;
}
QTabWidget#companion_orb_main_tabs::pane {
    top: 0px;
    background: #122033;
    border: 1px solid #2d4561;
    border-top-color: #36506d;
    border-radius: 10px;
    padding: 10px;
}
QTabWidget#companion_orb_main_tabs QStackedWidget {
    background: transparent;
    padding: 6px;
}
/* nc-companion-orb-main-tabs:end */
"""
        current_style = str(tabs.styleSheet() or "")
        if "nc-companion-orb-main-tabs:start" not in current_style:
            tabs.setStyleSheet((current_style + "\n" + style).strip())

    def _set_tooltip_deep(self, widget, text):
        if widget is None or not text:
            return
        widget.setToolTip(str(text))
        for child in widget.findChildren(QtWidgets.QWidget):
            if not child.toolTip():
                child.setToolTip(str(text))

    def _apply_companion_orb_tooltips(self, root):
        for key, widget in list(self._controls.items()):
            tooltip = COMPANION_ORB_TOOLTIPS.get(key)
            if tooltip:
                self._set_tooltip_deep(widget, tooltip)
        for widget in root.findChildren(QtWidgets.QWidget):
            object_name = str(widget.objectName() or "")
            tooltip = COMPANION_ORB_TOOLTIPS.get(object_name)
            if tooltip:
                self._set_tooltip_deep(widget, tooltip)

    def _normalized_hex_color(self, value, default="#38bdf8"):
        text = str(value or default or "#38bdf8").strip()
        if not text.startswith("#"):
            text = "#" + text
        text = text[:7]
        color = QtGui.QColor(text)
        return color.name() if color.isValid() else str(default or "#38bdf8")

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

    def _color_setting_row(self, label, key, default):
        row = QtWidgets.QWidget()
        row.setObjectName(f"{key}_row")
        layout = QtWidgets.QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._compact_label(label))
        swatch = QtWidgets.QLabel()
        swatch.setObjectName(f"{key}_swatch")
        value = self._normalized_hex_color(_runtime_config().get(key, DEFAULT_SETTINGS.get(key, default)), default)
        swatch.setStyleSheet(self._color_swatch_style(value))
        self._orb_color_swatches[key] = swatch
        layout.addWidget(swatch)

        edit = QtWidgets.QLineEdit()
        edit.setObjectName(f"{key}_edit")
        edit.setText(value)
        edit.setMinimumHeight(26)
        edit.setMaximumHeight(30)
        edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._controls[key] = edit

        def commit_color(setting_key=key, widget=edit, chip=swatch, fallback=default):
            color = self._normalized_hex_color(widget.text(), fallback)
            widget.setText(color)
            chip.setStyleSheet(self._color_swatch_style(color))
            self._on_setting_changed(setting_key, color)

        edit.editingFinished.connect(commit_color)
        if key in ORB_COLOR_SETTING_KEYS:
            edit.textChanged.connect(lambda *_args: self._refresh_orb_color_preview())
        layout.addWidget(edit, 1)

        pick_button = QtWidgets.QPushButton("Pick")
        pick_button.setObjectName(f"{key}_pick_button")
        pick_button.setMinimumHeight(26)
        pick_button.setMaximumHeight(30)
        pick_button.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        pick_button.clicked.connect(lambda _checked=False, setting_key=key, widget=edit, chip=swatch, fallback=default: self._pick_orb_color(setting_key, widget, chip, fallback))
        layout.addWidget(pick_button)
        return row

    def _pick_orb_color(self, key, edit, swatch, default):
        initial = QtGui.QColor(self._normalized_hex_color(edit.text(), default))
        color = QtWidgets.QColorDialog.getColor(initial, None, "Choose orb color", QtWidgets.QColorDialog.ShowAlphaChannel)
        if not color.isValid():
            return
        value = color.name()
        edit.setText(value)
        swatch.setStyleSheet(self._color_swatch_style(value))
        self._on_setting_changed(key, value)

    def refresh_from_runtime(self):
        super().refresh_from_runtime()
        for key in (
            "companion_orb_eye_tracking_long_gaze_ms",
            "companion_orb_eye_tracking_radial_button_gaze_ms",
        ):
            spin = self._controls.get(key)
            if not isinstance(spin, QtWidgets.QSpinBox):
                continue
            try:
                spin.blockSignals(True)
                spin.setValue(
                    int(
                        self._normalize_setting(
                            key,
                            _runtime_config().get(key, COMPANION_ORB_EYE_TRACKING_DEFAULTS[key]),
                        )
                    )
                )
            finally:
                spin.blockSignals(False)
        self._sync_reply_style_prompt_editor_from_runtime(
            _runtime_config().get("companion_orb_response_style", "friendly")
        )
        self._sync_reader_settings_from_runtime()
        source_checkbox = self._controls.get("companion_orb_sensory_target_enabled")
        if source_checkbox is not None and hasattr(source_checkbox, "setChecked"):
            checked = bool(_runtime_config().get("companion_orb_sensory_target_enabled", False))
            try:
                source_checkbox.blockSignals(True)
                source_checkbox.setChecked(checked)
            finally:
                source_checkbox.blockSignals(False)
        for key, swatch in list(getattr(self, "_orb_color_swatches", {}).items()):
            widget = self._controls.get(key)
            if widget is not None and hasattr(widget, "text"):
                swatch.setStyleSheet(self._color_swatch_style(widget.text()))
        self._sync_orb_color_source_status()
        self._refresh_orb_color_preview()
        self._refresh_eye_tracking_status()
        self._refresh_companion_orb_supervisor_designer_if_available()
        self._register_companion_orb_supervisor_contributor()

    def _refresh_companion_orb_supervisor_designer_if_available(self):
        refresher = getattr(self, "_refresh_companion_orb_supervisor_designer", None)
        if callable(refresher):
            try:
                refresher()
            except RuntimeError:
                self._refresh_companion_orb_supervisor_designer = None

    def import_session_state(self, session):
        result = super().import_session_state(session)
        self._register_companion_orb_supervisor_contributor()
        return result

    def shutdown(self):
        self._eye_tracking_status_timer.stop()
        self._unregister_companion_orb_supervisor_contributor()
        self._companion_orb_supervisor_expanded_behavior_ids.clear()
        return super().shutdown()

    def _build_companion_orb_sensory_tabs(self):
        group, layout = self._section_group("Background Awareness & Response", "companion_orb_sensory_tabs_group")
        tabs = NoWheelTabWidget()
        tabs.setObjectName("companion_orb_sensory_tabs")
        tabs.addTab(self._build_companion_orb_source_tab(), "What the orb noticed")
        tabs.addTab(self._build_companion_orb_capture_tab(), "Capture target")
        tabs.addTab(self._build_companion_orb_supervisor_tab(), "Orb personality rules")
        tabs.setTabToolTip(0, "Source guidance and declared background-awareness payload for Companion Orb Target.")
        tabs.setTabToolTip(1, "Capture and target settings that decide what the orb sees.")
        tabs.setTabToolTip(2, "Response settings that decide when the orb comments, moves, or takes a snapshot.")
        self._apply_companion_orb_sensory_tab_style(tabs)
        layout.addWidget(tabs)
        return group

    def _apply_companion_orb_sensory_tab_style(self, tabs):
        if tabs is None:
            return
        if not isinstance(tabs.tabBar(), _CompanionOrbSensoryTabBar):
            previous_bar = tabs.tabBar()
            current_index = tabs.currentIndex()
            entries = []
            for index in range(tabs.count()):
                entries.append(
                    {
                        "widget": tabs.widget(index),
                        "text": tabs.tabText(index),
                        "icon": tabs.tabIcon(index),
                        "tooltip": tabs.tabToolTip(index),
                        "enabled": tabs.isTabEnabled(index),
                        "data": previous_bar.tabData(index) if previous_bar is not None else None,
                    }
                )
            while tabs.count():
                tabs.removeTab(0)
            tab_bar = _CompanionOrbSensoryTabBar(tabs)
            tabs.setTabBar(tab_bar)
            for entry in entries:
                widget = entry["widget"]
                icon = entry["icon"]
                text = str(entry["text"] or "")
                if isinstance(icon, QtGui.QIcon) and not icon.isNull():
                    index = tabs.addTab(widget, icon, text)
                else:
                    index = tabs.addTab(widget, text)
                tooltip = str(entry["tooltip"] or "")
                if tooltip:
                    tabs.setTabToolTip(index, tooltip)
                tabs.setTabEnabled(index, bool(entry["enabled"]))
                tab_bar.setTabData(index, entry["data"])
            if entries:
                tabs.setCurrentIndex(min(max(0, current_index), len(entries) - 1))

        tabs.setIconSize(QtCore.QSize(36, 36))
        tabs.setUsesScrollButtons(True)
        tab_bar = tabs.tabBar()
        if tab_bar is not None:
            tab_bar.setDrawBase(False)
            tab_bar.setExpanding(False)
            tab_bar.setUsesScrollButtons(True)

        specs = {
            "What the orb noticed": ("noticed", "#38bdf8"),
            "Capture target": ("capture", "#22c55e"),
            "Orb personality rules": ("personality", "#a78bfa"),
        }
        for index in range(tabs.count()):
            title = str(tabs.tabText(index) or "")
            icon_key, accent = specs.get(title, ("fallback", "#60a5fa"))
            tabs.setTabIcon(index, _companion_orb_sensory_tab_icon(icon_key, accent))
            if tab_bar is not None:
                tab_bar.setTabData(index, {"accent": accent, "icon": icon_key})

        style = """
/* nc-companion-orb-sensory-tabs-polish:start */
QTabWidget#companion_orb_sensory_tabs::tab-bar {
    left: 4px;
}
QTabWidget#companion_orb_sensory_tabs QTabBar {
    background: #122033;
    padding-top: 4px;
    padding-bottom: 4px;
}
QTabWidget#companion_orb_sensory_tabs QTabBar::scroller {
    width: 32px;
}
QTabWidget#companion_orb_sensory_tabs QTabBar QToolButton {
    background: #1b2b40;
    color: #d8e2ee;
    border: 1px solid #416184;
    border-radius: 8px;
    width: 20px;
    min-width: 20px;
    max-width: 20px;
    padding: 0px;
    margin: 8px 1px 8px 1px;
}
QTabWidget#companion_orb_sensory_tabs QTabBar QToolButton:hover {
    background: #243956;
}
QTabWidget#companion_orb_sensory_tabs QTabBar::tab {
    background: transparent;
    color: #d8e2ee;
    font-weight: 700;
    border: none;
    min-width: 0px;
    min-height: 68px;
    padding: 0px;
    margin-right: 5px;
    margin-bottom: 2px;
    border-radius: 9px;
}
QTabWidget#companion_orb_sensory_tabs QTabBar::tab:selected,
QTabWidget#companion_orb_sensory_tabs QTabBar::tab:hover {
    background: transparent;
    border: none;
}
QTabWidget#companion_orb_sensory_tabs::pane {
    top: 0px;
    background: #122033;
    border: 1px solid #2d4561;
    border-top-color: #36506d;
    border-radius: 10px;
    padding: 10px;
}
QTabWidget#companion_orb_sensory_tabs QStackedWidget {
    background: transparent;
    padding: 6px;
}
/* nc-companion-orb-sensory-tabs-polish:end */
""".strip()
        start = "/* nc-companion-orb-sensory-tabs-polish:start */"
        end = "/* nc-companion-orb-sensory-tabs-polish:end */"
        existing = str(tabs.styleSheet() or "").strip()
        if start in existing and end in existing:
            before, rest = existing.split(start, 1)
            _old, after = rest.split(end, 1)
            existing = f"{before.rstrip()}\n{after.lstrip()}".strip()
        next_style = f"{existing}\n{style}".strip() if existing else style
        if str(tabs.styleSheet() or "") != next_style:
            tabs.setStyleSheet(next_style)

    def _build_companion_orb_source_tab(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        source_label = QtWidgets.QLabel("How the orb should interpret its target")
        source_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
        layout.addWidget(source_label)
        layout.addWidget(
            self._read_only_text(
                COMPANION_ORB_TARGET_PINGPONG_PROMPT,
                "companion_orb_source_guidance_preview",
                height=190,
            )
        )

        meta_grid = _ResponsiveGridWidget(min_column_width=260, max_columns=3, horizontal_spacing=10, vertical_spacing=8)
        meta_grid.setObjectName("companion_orb_source_metadata_grid")
        metadata = dict(COMPANION_ORB_TARGET_METADATA or {})

        for title, object_name, text in (
            ("Provider", "companion_orb_source_provider_preview", self._metadata_overview_text()),
            ("What the orb notices", "companion_orb_source_ping_payload_preview", self._metadata_items_text(metadata.get("ping_payload"))),
            ("How notices guide behavior", "companion_orb_source_pong_influence_preview", self._metadata_items_text(metadata.get("pong_influences"))),
        ):
            box, box_layout = self._section_group(title, object_name + "_group")
            box_layout.addWidget(self._read_only_text(text, object_name, height=112))
            meta_grid.add_widget(box)
        layout.addWidget(meta_grid)

        tag_label = QtWidgets.QLabel("Tag subscriptions")
        tag_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
        layout.addWidget(tag_label)
        layout.addWidget(
            self._read_only_text(
                self._metadata_items_text(metadata.get("tag_subscriptions")),
                "companion_orb_source_tag_subscriptions_preview",
                height=56,
            )
        )
        layout.addStretch(1)
        return widget

    def _build_companion_orb_capture_tab(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        capture_intro = QtWidgets.QLabel(
            "Companion Orb Target can use either the selected orb target or an opt-in desktop-wide context map with OCR regions. Returned focus bounds let the orb move toward the thing it is talking about."
        )
        capture_intro.setWordWrap(True)
        capture_intro.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(capture_intro)

        capture_grid = _ResponsiveGridWidget(min_column_width=260, max_columns=3, horizontal_spacing=10, vertical_spacing=8)
        capture_grid.setObjectName("companion_orb_capture_settings_grid")

        source_group, source_layout = self._section_group("What the orb can watch", "companion_orb_capture_source_group")
        source_layout.addWidget(
            self._checkbox(
                "Use Companion Orb Target",
                "companion_orb_sensory_target_enabled_checkbox",
                "companion_orb_sensory_target_enabled",
                False,
            )
        )
        source_layout.addWidget(
            self._checkbox(
                "Run background check-ins",
                "companion_orb_pingpong_enabled_checkbox",
                "sensory_pingpong_enabled",
                False,
            )
        )
        source_layout.addWidget(
            self._checkbox(
                "Full-screen context map",
                "companion_orb_full_screen_context_enabled_checkbox",
                "companion_orb_full_screen_context_enabled",
                False,
            )
        )
        source_hint = QtWidgets.QLabel(
            "This uses the Companion Orb Target source, not the separate HOST Screen source. "
            "Enable the source here, then turn on Full-screen context map when the orb should analyze the desktop-wide map instead of only the selected target."
        )
        source_hint.setWordWrap(True)
        source_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        source_layout.addWidget(source_hint)
        source_layout.addStretch(1)

        target_group, target_layout = self._section_group("Target Selection", "companion_orb_capture_target_group")
        target_grid = QtWidgets.QGridLayout()
        target_grid.setContentsMargins(0, 0, 0, 0)
        target_grid.setHorizontalSpacing(8)
        target_grid.setVerticalSpacing(4)
        target_grid.addWidget(self._compact_label("Target"), 0, 0)
        target_grid.addWidget(self._combo("companion_orb_target_mode_combo", ORB_TARGET_MODES, "companion_orb_target_mode", "window"), 0, 1)
        target_grid.addWidget(
            self._checkbox("Show selected target label", "companion_orb_show_target_label_checkbox", "companion_orb_show_target_label", True),
            1,
            0,
            1,
            2,
        )
        target_grid.addWidget(
            self._checkbox("Require target confirmation", "companion_orb_require_target_confirmation_checkbox", "companion_orb_require_target_confirmation", True),
            2,
            0,
            1,
            2,
        )
        process_checkbox = self._checkbox(
            "Mention process names",
            "companion_orb_include_process_name_checkbox",
            "companion_orb_include_process_name",
            True,
        )
        process_checkbox.setToolTip("When off, Companion Orb Target hides executable/process names from labels and hidden sensory metadata.")
        target_grid.addWidget(process_checkbox, 3, 0, 1, 2)
        target_grid.setColumnStretch(1, 1)
        target_layout.addLayout(target_grid)
        target_layout.addStretch(1)

        region_group, region_layout = self._section_group("Region Capture", "companion_orb_capture_region_group")
        region_layout.addWidget(
            self._slider(
                "companion_orb_target_region_width",
                "companion_orb_target_width_slider",
                "Target Region Width",
                64,
                2560,
                640,
                True,
            )
        )
        region_layout.addWidget(
            self._slider(
                "companion_orb_target_region_height",
                "companion_orb_target_height_slider",
                "Target Region Height",
                64,
                1440,
                420,
                True,
            )
        )
        region_layout.addStretch(1)

        capture_grid.add_widgets((source_group, target_group, region_group))
        layout.addWidget(capture_grid)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        for label, handler, object_name in (
            ("Show Orb", self._show_companion_orb, "companion_orb_capture_show_button"),
            ("Clear Target", self._clear_companion_orb_target, "companion_orb_capture_clear_target_button"),
            ("Reset Position", self._reset_companion_orb_position, "companion_orb_capture_reset_position_button"),
        ):
            button = QtWidgets.QPushButton(label)
            button.setObjectName(object_name)
            button.clicked.connect(handler)
            button.setMinimumHeight(27)
            button.setMaximumHeight(31)
            action_row.addWidget(button)
        action_row.addStretch(1)
        layout.addLayout(action_row)
        layout.addStretch(1)
        return widget

    def _build_companion_orb_supervisor_designer(self):
        group, layout = self._section_group("Orb Personality Rules", "companion_orb_supervisor_behavior_designer")
        layout.addWidget(
            self._checkbox(
                "Enable orb personality rules",
                "companion_orb_supervisor_enabled_checkbox",
                "companion_orb_supervisor_enabled",
                False,
            )
        )

        state_label = QtWidgets.QLabel()
        state_label.setObjectName("companion_orb_supervisor_state_label")
        state_label.setWordWrap(True)
        state_label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(state_label)

        persona_header = QtWidgets.QHBoxLayout()
        persona_header.setContentsMargins(0, 0, 0, 0)
        persona_header.setSpacing(8)
        persona_label = QtWidgets.QLabel("Active orb style")
        persona_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
        persona_header.addWidget(persona_label)
        persona_header.addStretch(1)
        add_persona_button = QtWidgets.QPushButton("Add Orb Style")
        add_persona_button.setObjectName("btn_companion_orb_supervisor_add_persona")
        rename_persona_button = QtWidgets.QPushButton("Rename")
        rename_persona_button.setObjectName("btn_companion_orb_supervisor_rename_persona")
        delete_persona_button = QtWidgets.QPushButton("Delete")
        delete_persona_button.setObjectName("btn_companion_orb_supervisor_delete_persona")
        persona_header.addWidget(add_persona_button)
        persona_header.addWidget(rename_persona_button)
        persona_header.addWidget(delete_persona_button)
        layout.addLayout(persona_header)

        persona_combo = QtWidgets.QComboBox()
        persona_combo.setObjectName("companion_orb_supervisor_persona_combo")
        persona_combo.setMinimumHeight(26)
        persona_combo.setMaximumHeight(30)
        layout.addWidget(persona_combo)

        persona_style_edit = QtWidgets.QLineEdit()
        persona_style_edit.setObjectName("companion_orb_supervisor_persona_style_edit")
        persona_style_edit.setMinimumHeight(26)
        persona_style_edit.setMaximumHeight(30)
        persona_form = QtWidgets.QFormLayout()
        persona_form.setContentsMargins(0, 0, 0, 0)
        persona_form.addRow("Tone", persona_style_edit)
        layout.addLayout(persona_form)

        behavior_header = QtWidgets.QHBoxLayout()
        behavior_header.setContentsMargins(0, 2, 0, 0)
        behavior_label = QtWidgets.QLabel("Behavior rules")
        behavior_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
        behavior_header.addWidget(behavior_label)
        behavior_header.addStretch(1)
        add_behavior_button = QtWidgets.QPushButton("Add Rule")
        add_behavior_button.setObjectName("btn_companion_orb_supervisor_add_behavior")
        behavior_header.addWidget(add_behavior_button)
        layout.addLayout(behavior_header)

        behaviors_widget = QtWidgets.QWidget()
        behaviors_widget.setObjectName("companion_orb_supervisor_behaviors_widget")
        behaviors_layout = QtWidgets.QVBoxLayout(behaviors_widget)
        behaviors_layout.setContentsMargins(0, 0, 0, 0)
        behaviors_layout.setSpacing(8)
        layout.addWidget(behaviors_widget)

        template_group, template_layout = self._section_group("Advanced Prompt Template", "companion_orb_supervisor_template_group")
        template_header = QtWidgets.QHBoxLayout()
        template_header.setContentsMargins(0, 0, 0, 0)
        template_hint = QtWidgets.QLabel("Edit the template that wraps this orb-only behavior guidance before background check-ins.")
        template_hint.setWordWrap(True)
        template_hint.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        template_reset_button = QtWidgets.QPushButton("Use Recommended")
        template_reset_button.setObjectName("btn_companion_orb_supervisor_reset_template")
        template_header.addWidget(template_hint, 1)
        template_header.addWidget(template_reset_button)
        template_layout.addLayout(template_header)
        template_edit = QtWidgets.QPlainTextEdit()
        template_edit.setObjectName("companion_orb_supervisor_template_edit")
        template_edit.setMinimumHeight(150)
        template_layout.addWidget(template_edit)
        layout.addWidget(template_group)

        preview_label = QtWidgets.QLabel("Current orb prompt preview")
        preview_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
        layout.addWidget(preview_label)
        preview_edit = QtWidgets.QPlainTextEdit()
        preview_edit.setObjectName("companion_orb_supervisor_preview_edit")
        preview_edit.setReadOnly(True)
        preview_edit.setMinimumHeight(150)
        layout.addWidget(preview_edit)

        sync = {"active": False}
        debounce_timers: list[QtCore.QTimer] = []

        def clear_layout(target_layout):
            while target_layout.count():
                item = target_layout.takeAt(0)
                child_widget = item.widget()
                child_layout = item.layout()
                if child_widget is not None:
                    child_widget.deleteLater()
                elif child_layout is not None:
                    clear_layout(child_layout)

        def refresh_preview():
            if not bool(_runtime_config().get("companion_orb_supervisor_enabled", False)):
                preview_edit.setPlainText("Disabled. Enable orb personality rules to add these rules to Companion Orb Target background awareness.")
                return
            preview_edit.setPlainText(self._render_companion_orb_supervisor_prompt())

        def publish_personas(personas, *, rebuild=False):
            self._set_companion_orb_supervisor_personas(personas)
            refresh_preview()
            if rebuild:
                refresh_from_state()

        def bind_debounced_plain_text(edit, callback):
            timer = QtCore.QTimer(edit)
            timer.setSingleShot(True)
            timer.setInterval(450)
            timer.timeout.connect(callback)
            edit.textChanged.connect(lambda: None if sync["active"] else timer.start())
            debounce_timers.append(timer)

        def commit_template():
            if sync["active"]:
                return
            text = str(template_edit.toPlainText() or "").strip() or COMPANION_ORB_SUPERVISOR_TEMPLATE
            if text != str(_runtime_config().get("companion_orb_supervisor_prompt_template", "") or ""):
                _update_runtime_config("companion_orb_supervisor_prompt_template", text)
                self._publish_companion_orb_supervisor()
            refresh_preview()

        def reset_template():
            _update_runtime_config("companion_orb_supervisor_prompt_template", COMPANION_ORB_SUPERVISOR_TEMPLATE)
            self._publish_companion_orb_supervisor()
            refresh_from_state()

        def commit_persona_style():
            if sync["active"]:
                return
            personas = self._companion_orb_supervisor_personas()
            selected_id = str(_runtime_config().get("companion_orb_supervisor_selected_persona_id") or "").strip()
            for persona in personas:
                if persona["id"] == selected_id:
                    persona["style"] = str(persona_style_edit.text() or "").strip() or "playful, observant desktop companion"
                    publish_personas(personas)
                    return
            refresh_preview()

        def commit_behavior_change(persona_id, behavior_id, *, trigger=None, action=None, enabled=None, strictness=None, emotion=None, repeat_mode=None, repeat_interval=None):
            if sync["active"]:
                return
            personas = self._companion_orb_supervisor_personas()
            persona = next((item for item in personas if item["id"] == persona_id), None)
            behavior = self._find_companion_orb_supervisor_behavior(persona, behavior_id)
            if persona is None or behavior is None:
                return
            changed = False
            if trigger is not None and str(trigger).strip() != str(behavior.get("trigger") or ""):
                behavior["trigger"] = str(trigger).strip()
                changed = True
            if action is not None and str(action).strip() != str(behavior.get("action") or ""):
                behavior["action"] = str(action).strip()
                changed = True
            if enabled is not None and bool(enabled) != bool(behavior.get("enabled", True)):
                behavior["enabled"] = bool(enabled)
                changed = True
            if strictness is not None:
                value = self._normalize_supervisor_strictness(strictness)
                if value != str(behavior.get("strictness") or SUPERVISOR_DEFAULT_STRICTNESS):
                    behavior["strictness"] = value
                    changed = True
            if emotion is not None:
                value = self._normalize_supervisor_emotion(emotion)
                if value != str(behavior.get("emotion") or SUPERVISOR_DEFAULT_EMOTION):
                    behavior["emotion"] = value
                    changed = True
            if repeat_mode is not None:
                value = self._normalize_supervisor_repeat_mode(repeat_mode)
                if value != str(behavior.get("repeat_mode") or SUPERVISOR_DEFAULT_REPEAT_MODE):
                    behavior["repeat_mode"] = value
                    changed = True
            if repeat_interval is not None:
                value = self._normalize_supervisor_repeat_interval(repeat_interval)
                if value != int(behavior.get("repeat_interval") or SUPERVISOR_DEFAULT_REPEAT_INTERVAL):
                    behavior["repeat_interval"] = value
                    changed = True
            if changed:
                publish_personas(personas)
            else:
                refresh_preview()

        def rebuild_behavior_rows():
            clear_layout(behaviors_layout)
            persona = self._selected_companion_orb_supervisor_persona()
            behavior_items = list(persona.get("behaviors") or [])
            if not behavior_items:
                empty = QtWidgets.QLabel("No behaviors are configured for this persona yet. Add one to teach the orb what to notice and how to react.")
                empty.setWordWrap(True)
                empty.setStyleSheet("color: #8ea3b8; font-size: 11px;")
                behaviors_layout.addWidget(empty)
                return
            for index, behavior in enumerate(behavior_items, start=1):
                box = QtWidgets.QGroupBox(f"Behavior {index}")
                box_layout = QtWidgets.QVBoxLayout(box)
                box_layout.setSpacing(6)

                top_row = QtWidgets.QHBoxLayout()
                enabled_checkbox = QtWidgets.QCheckBox("Enabled")
                enabled_checkbox.setChecked(bool(behavior.get("enabled", True)))
                advanced_button = QtWidgets.QToolButton()
                advanced_button.setText("Advanced")
                advanced_button.setCheckable(True)
                advanced_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
                advanced_button.setChecked(str(behavior.get("id") or "") in self._companion_orb_supervisor_expanded_behavior_ids)
                remove_button = QtWidgets.QPushButton("Remove")
                top_row.addWidget(enabled_checkbox)
                top_row.addStretch(1)
                top_row.addWidget(advanced_button)
                top_row.addWidget(remove_button)
                box_layout.addLayout(top_row)

                trigger_label = QtWidgets.QLabel("Visual Trigger")
                trigger_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
                trigger_edit = QtWidgets.QPlainTextEdit()
                trigger_edit.setMinimumHeight(34)
                trigger_edit.setMaximumHeight(62)
                trigger_edit.setPlainText(str(behavior.get("trigger") or ""))
                box_layout.addWidget(trigger_label)
                box_layout.addWidget(trigger_edit)

                action_label = QtWidgets.QLabel("Action")
                action_label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 700;")
                action_edit = QtWidgets.QPlainTextEdit()
                action_edit.setMinimumHeight(34)
                action_edit.setMaximumHeight(68)
                action_edit.setPlainText(str(behavior.get("action") or ""))
                box_layout.addWidget(action_label)
                box_layout.addWidget(action_edit)

                advanced_panel = QtWidgets.QWidget()
                advanced_layout = QtWidgets.QFormLayout(advanced_panel)
                advanced_layout.setContentsMargins(0, 4, 0, 0)
                strictness_combo = QtWidgets.QComboBox()
                strictness_combo.addItems(SUPERVISOR_STRICTNESS_OPTIONS)
                strictness_combo.setCurrentText(self._normalize_supervisor_strictness(behavior.get("strictness")))
                emotion_combo = QtWidgets.QComboBox()
                emotion_combo.addItems(SUPERVISOR_EMOTION_OPTIONS)
                emotion_combo.setCurrentText(self._normalize_supervisor_emotion(behavior.get("emotion")))
                repeat_mode_combo = QtWidgets.QComboBox()
                repeat_mode_combo.addItems(SUPERVISOR_REPEAT_MODE_OPTIONS)
                repeat_mode_combo.setCurrentText(self._normalize_supervisor_repeat_mode(behavior.get("repeat_mode")))
                repeat_interval_spin = QtWidgets.QSpinBox()
                repeat_interval_spin.setRange(1, 999)
                repeat_interval_spin.setValue(self._normalize_supervisor_repeat_interval(behavior.get("repeat_interval")))
                advanced_layout.addRow("Strictness", strictness_combo)
                advanced_layout.addRow("Emotion override", emotion_combo)
                advanced_layout.addRow("Repeat mode", repeat_mode_combo)
                advanced_layout.addRow("Nth match interval", repeat_interval_spin)

                def sync_repeat_interval_control(mode_text, spin=repeat_interval_spin):
                    spin.setEnabled(str(mode_text or "") == "Every Nth match")

                sync_repeat_interval_control(repeat_mode_combo.currentText())
                advanced_panel.setVisible(advanced_button.isChecked())
                box_layout.addWidget(advanced_panel)

                persona_id = str(persona.get("id") or "")
                behavior_id = str(behavior.get("id") or "")
                enabled_checkbox.toggled.connect(lambda checked, pid=persona_id, bid=behavior_id: commit_behavior_change(pid, bid, enabled=checked))
                bind_debounced_plain_text(trigger_edit, lambda pid=persona_id, bid=behavior_id, edit=trigger_edit: commit_behavior_change(pid, bid, trigger=edit.toPlainText()))
                bind_debounced_plain_text(action_edit, lambda pid=persona_id, bid=behavior_id, edit=action_edit: commit_behavior_change(pid, bid, action=edit.toPlainText()))
                strictness_combo.currentTextChanged.connect(lambda value, pid=persona_id, bid=behavior_id: commit_behavior_change(pid, bid, strictness=value))
                emotion_combo.currentTextChanged.connect(lambda value, pid=persona_id, bid=behavior_id: commit_behavior_change(pid, bid, emotion=value))
                repeat_mode_combo.currentTextChanged.connect(
                    lambda value, pid=persona_id, bid=behavior_id, spin=repeat_interval_spin: (
                        sync_repeat_interval_control(value, spin),
                        commit_behavior_change(pid, bid, repeat_mode=value),
                    )
                )
                repeat_interval_spin.valueChanged.connect(lambda value, pid=persona_id, bid=behavior_id: commit_behavior_change(pid, bid, repeat_interval=value))
                advanced_button.toggled.connect(
                    lambda checked, panel=advanced_panel, bid=behavior_id: (
                        panel.setVisible(bool(checked)),
                        self._companion_orb_supervisor_expanded_behavior_ids.add(bid) if checked else self._companion_orb_supervisor_expanded_behavior_ids.discard(bid),
                    )
                )
                remove_button.clicked.connect(lambda _checked=False, bid=behavior_id: remove_behavior(bid))
                behaviors_layout.addWidget(box)

        def refresh_from_state():
            sync["active"] = True
            try:
                enabled = bool(_runtime_config().get("companion_orb_supervisor_enabled", False))
                personas = self._companion_orb_supervisor_personas()
                active = self._selected_companion_orb_supervisor_persona()
                persona_combo.blockSignals(True)
                persona_combo.clear()
                for item in personas:
                    persona_combo.addItem(str(item.get("name") or "Unnamed Persona"), item.get("id"))
                persona_combo.setCurrentIndex(max(0, persona_combo.findData(active.get("id"))))
                persona_combo.blockSignals(False)
                persona_style_edit.blockSignals(True)
                persona_style_edit.setText(str(active.get("style") or "playful, observant desktop companion"))
                persona_style_edit.blockSignals(False)
                template_edit.blockSignals(True)
                template_edit.setPlainText(self._companion_orb_supervisor_template())
                template_edit.blockSignals(False)
                state_label.setText(
                    f"Active. Persona '{active.get('name')}' owns {len(list(active.get('behaviors') or []))} behavior(s) for Companion Orb Target."
                    if enabled
                    else "Inactive. Enable this supervisor to add these behavior rules to Companion Orb Target hidden sensory prompts."
                )
                for control in (
                    persona_combo,
                    persona_style_edit,
                    add_persona_button,
                    rename_persona_button,
                    add_behavior_button,
                    template_edit,
                    template_reset_button,
                ):
                    control.setEnabled(True)
                delete_persona_button.setEnabled(len(personas) > 1)
                rebuild_behavior_rows()
                refresh_preview()
            finally:
                sync["active"] = False

        self._refresh_companion_orb_supervisor_designer = refresh_from_state

        def on_persona_changed():
            if sync["active"]:
                return
            selected_id = str(persona_combo.currentData() or "").strip()
            if selected_id:
                _update_runtime_config("companion_orb_supervisor_selected_persona_id", selected_id)
                self._publish_companion_orb_supervisor()
            refresh_from_state()

        def add_persona():
            name, accepted = QtWidgets.QInputDialog.getText(group, "Add Companion Orb Supervisor Persona", "Persona name:")
            if not accepted or not str(name or "").strip():
                return
            personas = self._companion_orb_supervisor_personas()
            persona = {
                "id": _new_supervisor_id("orb_persona"),
                "name": str(name).strip(),
                "style": "playful, observant desktop companion",
                "behaviors": [],
            }
            personas.append(persona)
            _update_runtime_config("companion_orb_supervisor_selected_persona_id", persona["id"])
            publish_personas(personas, rebuild=True)

        def rename_persona():
            active = self._selected_companion_orb_supervisor_persona()
            name, accepted = QtWidgets.QInputDialog.getText(
                group,
                "Rename Companion Orb Supervisor Persona",
                "Persona name:",
                text=str(active.get("name") or ""),
            )
            if not accepted or not str(name or "").strip():
                return
            personas = self._companion_orb_supervisor_personas()
            selected_id = str(active.get("id") or "")
            for persona in personas:
                if persona["id"] == selected_id:
                    persona["name"] = str(name).strip()
                    break
            publish_personas(personas, rebuild=True)

        def delete_persona():
            personas = self._companion_orb_supervisor_personas()
            if len(personas) <= 1:
                return
            selected_id = str(_runtime_config().get("companion_orb_supervisor_selected_persona_id") or "")
            personas = [item for item in personas if item["id"] != selected_id]
            _update_runtime_config("companion_orb_supervisor_selected_persona_id", personas[0]["id"])
            publish_personas(personas, rebuild=True)

        def add_behavior():
            personas = self._companion_orb_supervisor_personas()
            selected_id = str(_runtime_config().get("companion_orb_supervisor_selected_persona_id") or "")
            for persona in personas:
                if persona["id"] == selected_id:
                    behavior = {
                        "id": _new_supervisor_id("orb_behavior"),
                        "enabled": True,
                        "trigger": "The orb sees a visible detail worth commenting on.",
                        "action": "Make a short grounded comment about that visible detail and provide focus_bounds when possible.",
                        "strictness": SUPERVISOR_DEFAULT_STRICTNESS,
                        "emotion": SUPERVISOR_DEFAULT_EMOTION,
                        "repeat_mode": SUPERVISOR_DEFAULT_REPEAT_MODE,
                        "repeat_interval": SUPERVISOR_DEFAULT_REPEAT_INTERVAL,
                    }
                    persona.setdefault("behaviors", []).append(behavior)
                    self._companion_orb_supervisor_expanded_behavior_ids.add(behavior["id"])
                    break
            publish_personas(personas, rebuild=True)

        def remove_behavior(behavior_id):
            personas = self._companion_orb_supervisor_personas()
            selected_id = str(_runtime_config().get("companion_orb_supervisor_selected_persona_id") or "")
            for persona in personas:
                if persona["id"] == selected_id:
                    persona["behaviors"] = [item for item in list(persona.get("behaviors") or []) if item.get("id") != behavior_id]
                    break
            self._companion_orb_supervisor_expanded_behavior_ids.discard(str(behavior_id or ""))
            publish_personas(personas, rebuild=True)

        persona_combo.currentIndexChanged.connect(lambda *_args: on_persona_changed())
        persona_style_edit.editingFinished.connect(commit_persona_style)
        bind_debounced_plain_text(template_edit, commit_template)
        template_reset_button.clicked.connect(lambda *_args: reset_template())
        add_persona_button.clicked.connect(lambda *_args: add_persona())
        rename_persona_button.clicked.connect(lambda *_args: rename_persona())
        delete_persona_button.clicked.connect(lambda *_args: delete_persona())
        add_behavior_button.clicked.connect(lambda *_args: add_behavior())
        refresh_from_state()
        return group

    def _build_companion_orb_debug_diagnostics_card(self):
        debug_group, debug_layout = self._section_group("Advanced Debug", "companion_orb_debug_diagnostics_group")
        debug_layout.addWidget(
            self._checkbox("Orb debug log", "companion_orb_debug_enabled_checkbox", "companion_orb_debug_enabled", False)
        )

        diagnostics_group, diagnostics_layout = self._section_group("Reading Diagnostics", "companion_orb_reading_diagnostics_group")
        diagnostics_layout.addWidget(
            self._checkbox(
                "Keep selected-area debug crops",
                "companion_orb_reading_keep_debug_crops_checkbox",
                "companion_orb_reading_keep_debug_crops",
                False,
            )
        )
        diagnostics_layout.addWidget(
            self._read_only_text(
                "When enabled, movement targets, snapshot captures, OCR focus matches, selected-area reading/comment extraction, and background check-ins are written to:\n"
                "runtime/companion_orb/debug/companion_orb_debug.log\n\n"
                "Optional selected-area OCR crops are kept only when both Orb debug log and Keep selected-area debug crops are enabled:\n"
                "runtime/companion_orb/debug/reading_crops",
                "companion_orb_debug_log_path_preview",
                height=116,
            )
        )

        diagnostics_buttons = QtWidgets.QHBoxLayout()
        diagnostics_buttons.setContentsMargins(0, 0, 0, 0)
        diagnostics_buttons.setSpacing(8)
        open_log_folder_button = QtWidgets.QPushButton("Open Debug Log Folder")
        open_log_folder_button.setObjectName("btn_companion_orb_open_debug_log_folder")
        clear_log_button = QtWidgets.QPushButton("Clear Debug Log")
        clear_log_button.setObjectName("btn_companion_orb_clear_debug_log")
        copy_log_path_button = QtWidgets.QPushButton("Copy Debug Log Path")
        copy_log_path_button.setObjectName("btn_companion_orb_copy_debug_log_path")
        for button in (open_log_folder_button, clear_log_button, copy_log_path_button):
            button.setMinimumHeight(27)
            button.setMaximumHeight(31)
            diagnostics_buttons.addWidget(button)
        diagnostics_buttons.addStretch(1)
        diagnostics_layout.addLayout(diagnostics_buttons)

        diagnostics_status = QtWidgets.QLabel("")
        diagnostics_status.setObjectName("companion_orb_reading_diagnostics_status")
        diagnostics_status.setWordWrap(True)
        diagnostics_status.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        self._companion_orb_diagnostics_status = diagnostics_status
        diagnostics_layout.addWidget(diagnostics_status)

        open_log_folder_button.clicked.connect(lambda *_args: self._open_companion_orb_debug_log_folder())
        clear_log_button.clicked.connect(lambda *_args: self._clear_companion_orb_debug_log())
        copy_log_path_button.clicked.connect(lambda *_args: self._copy_companion_orb_debug_log_path())
        debug_layout.addWidget(diagnostics_group)
        return debug_group

    def _build_companion_orb_supervisor_tab(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        response_intro = QtWidgets.QLabel(
            "Orb personality settings decide how background observations become visible behavior: comments, playful nudges, screenshots, and movement toward the returned focus area."
        )
        response_intro.setWordWrap(True)
        response_intro.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(response_intro)
        layout.addWidget(self._build_companion_orb_supervisor_designer())

        response_grid = _ResponsiveGridWidget(min_column_width=260, max_columns=3, horizontal_spacing=10, vertical_spacing=8)
        response_grid.setObjectName("companion_orb_supervisor_settings_grid")

        reply_group, reply_layout = self._section_group("Response Triggers", "companion_orb_supervisor_reply_group")
        self._add_checkbox_stack(
            reply_layout,
            (
                self._checkbox("Playful nudges", "companion_orb_harassment_enabled_checkbox", "companion_orb_harassment_enabled", False),
                self._checkbox("Snapshot at pointer", "companion_orb_snapshot_on_pointer_reached_checkbox", "companion_orb_snapshot_on_pointer_reached", False),
                self._checkbox("Right-click drag changes focus", "companion_orb_right_drag_focus_enabled_checkbox", "companion_orb_right_drag_focus_enabled", True),
            ),
        )

        flow_group, flow_layout = self._section_group("How responses happen", "companion_orb_supervisor_flow_group")
        flow_layout.addWidget(
            self._read_only_text(
                "1. Background check-in captures the selected target or full-screen context map.\n"
                "2. The hidden model returns attention, summary, optional proactive comment, and optional focus area/text.\n"
                "3. The Companion Orb moves toward focus_bounds when present, or tries to match focus_text against OCR regions.\n"
                "4. Spoken proactive replies only happen when HOST hidden proactive replies are enabled and the source says should_speak=true.",
                "companion_orb_supervisor_flow_preview",
                height=122,
            )
        )

        focus_group, focus_layout = self._section_group("Movement focus", "companion_orb_supervisor_focus_group")
        focus_layout.addWidget(
            self._read_only_text(
                "The orb listens for focus_bounds, focus_label, and focus_text from sensory.hidden_pong.parsed. "
                "Full-screen context map gives the model more OCR/object regions, so it can point the orb at text, buttons, images, windows, or alerts across the desktop.",
                "companion_orb_supervisor_focus_preview",
                height=122,
            )
        )

        response_grid.add_widgets((reply_group, flow_group, focus_group))
        layout.addWidget(response_grid)
        layout.addStretch(1)
        return widget
