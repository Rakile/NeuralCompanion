from __future__ import annotations

import json
import uuid

from PySide6 import QtCore, QtGui, QtWidgets

from core import companion_orb_reply_styles
from ui.widgets.basic import NoWheelComboBox, NoWheelTabBar, NoWheelTabWidget

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
    _HORIZONTAL_PADDING = 7
    _TOP_PADDING = 5
    _TITLE_HEIGHT = 20
    _ICON_TEXT_GAP = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("_companion_orb_mprc_tab_style", True)
        self.setDrawBase(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(QtCore.Qt.ElideNone)
        self.setIconSize(QtCore.QSize(36, 36))

    def tabSizeHint(self, index):
        text_width = self.fontMetrics().horizontalAdvance(self.tabText(index))
        icon_width = 0 if self.tabIcon(index).isNull() else self.iconSize().width()
        width = max(self._MIN_WIDTH, max(text_width, icon_width) + (self._HORIZONTAL_PADDING * 2))
        return QtCore.QSize(width, self._HEIGHT)

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
        title_font = QtGui.QFont(self.font())
        title_font.setBold(True)
        for index in range(self.count()):
            rect = self.tabRect(index).adjusted(0, 0, -1, -2)
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
    "companion_orb_visual_style": "Chooses the Companion Orb renderer: glass, plasma ring, wisp, firetrail, or neural spark.",
    "companion_orb_visual_style_combo": "Chooses the Companion Orb renderer: glass, plasma ring, wisp, firetrail, or neural spark.",
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
    "companion_orb_debug_enabled": "Writes movement, target, snapshot, OCR, and hidden sensory debug events to the runtime log.",
    "companion_orb_debug_enabled_checkbox": "Writes movement, target, snapshot, OCR, and hidden sensory debug events to the runtime log.",
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
}


class CompanionOrbOverlaySettingsController(AIPresenceModeController):
    SESSION_KEYS = list(dict.fromkeys([*COMPANION_ORB_SESSION_KEYS, *COMPANION_ORB_AWARE_MOTION_SESSION_KEYS]))
    APPLY_STATUS_MESSAGE = "Companion Orb Overlay settings applied."

    def __init__(self, context):
        super().__init__(context)
        self._orb_color_swatches: dict[str, QtWidgets.QLabel] = {}
        self._companion_orb_supervisor_expanded_behavior_ids: set[str] = set()
        self._reply_style_prompt_combo: NoWheelComboBox | None = None
        self._reply_style_prompt_edit: QtWidgets.QPlainTextEdit | None = None
        self._reply_style_prompt_status: QtWidgets.QLabel | None = None
        self._refresh_companion_orb_supervisor_designer = None
        self._syncing_reply_style_prompt = False
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

    def _on_setting_changed(self, key, value):
        key = str(key or "").strip()
        super()._on_setting_changed(key, value)
        if key == "companion_orb_sensory_target_enabled":
            self._set_companion_orb_source_included(bool(value))
        elif key == "companion_orb_full_screen_context_enabled" and bool(value):
            if not bool(_runtime_config().get("companion_orb_sensory_target_enabled", False)):
                _update_runtime_config("companion_orb_sensory_target_enabled", True)
                self._sync_checkbox("companion_orb_sensory_target_enabled", True)
            self._set_companion_orb_source_included(True)
        elif key == "companion_orb_supervisor_enabled":
            if bool(value):
                if not bool(_runtime_config().get("companion_orb_sensory_target_enabled", False)):
                    _update_runtime_config("companion_orb_sensory_target_enabled", True)
                    self._sync_checkbox("companion_orb_sensory_target_enabled", True)
                self._set_companion_orb_source_included(True)
            self._publish_companion_orb_supervisor()
            self._refresh_companion_orb_supervisor_designer_if_available()
        elif key == "sensory_pingpong_enabled":
            self._notify_host_settings_changed()
        if key in {
            "companion_orb_sensory_target_enabled",
            "companion_orb_full_screen_context_enabled",
            "companion_orb_supervisor_enabled",
            "sensory_pingpong_enabled",
        }:
            self._save_session()

    def build_tab(self):
        scroll, card_layout = self._build_card_shell(
            "companion_orb_overlay_addon_tab",
            "companion_orb_overlay_content",
            "companion_orb_overlay_card",
            "COMPANION ORB OVERLAY",
        )

        intro = QtWidgets.QLabel(
            "Own settings for the desktop Companion Orb. These controls manage the orb overlay, movement, particles, voice sync, sensory target, and hotkeys without changing Neural Face controls."
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

        display_group, display_layout = self._section_group("Display & Actions", "companion_orb_display_group")
        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(8)
        selector_grid.setVerticalSpacing(4)
        selector_grid.addWidget(self._checkbox("Enable Companion Orb Overlay", "companion_orb_enabled_checkbox", "companion_orb_enabled", False), 0, 0, 1, 2)
        selector_grid.addWidget(self._compact_label("Display"), 0, 2)
        selector_grid.addWidget(self._combo("companion_orb_display_mode_combo", ORB_DISPLAY_MODES, "companion_orb_display_mode", "off"), 0, 3)
        selector_grid.addWidget(self._compact_label("Style"), 1, 0)
        selector_grid.addWidget(self._combo("companion_orb_visual_style_combo", ORB_VISUAL_STYLES, "companion_orb_visual_style", "neural_spark"), 1, 1)
        selector_grid.addWidget(self._compact_label("Position"), 1, 2)
        selector_grid.addWidget(self._combo("companion_orb_position_combo", ORB_POSITIONS, "companion_orb_position", "bottom-right"), 1, 3)
        selector_grid.addWidget(self._compact_label("Reply style"), 2, 0)
        reply_style_combo = self._combo("companion_orb_response_style_combo", ORB_RESPONSE_STYLES, "companion_orb_response_style", "friendly")
        reply_style_combo.currentIndexChanged.connect(
            lambda *_args, combo=reply_style_combo: self._sync_reply_style_prompt_editor_from_runtime(combo.currentData())
        )
        selector_grid.addWidget(
            reply_style_combo,
            2,
            1,
            1,
            3,
        )
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 1)
        display_layout.addLayout(selector_grid)
        display_layout.addWidget(self._build_reply_style_prompt_editor())

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
        layout.addWidget(display_group)

        toggle_grid = _ResponsiveGridWidget(min_column_width=235, max_columns=3, horizontal_spacing=10, vertical_spacing=8)
        toggle_grid.setObjectName("companion_orb_toggle_groups_grid")

        window_group, window_layout = self._section_group("Window", "companion_orb_window_toggles_group")
        self._add_checkbox_stack(
            window_layout,
            (
                self._checkbox("Always on top", "companion_orb_always_on_top_checkbox", "companion_orb_always_on_top", True),
                self._checkbox("Click-through by default", "companion_orb_click_through_default_checkbox", "companion_orb_click_through_default", True),
                self._checkbox("Remember position", "companion_orb_remember_position_checkbox", "companion_orb_remember_position", True),
                self._checkbox("External runtime for orb animation", "companion_orb_external_runtime_enabled_checkbox", "companion_orb_external_runtime_enabled", True),
            ),
        )

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

        visual_group, visual_layout = self._section_group("Visual Effects", "companion_orb_visual_toggles_group")
        self._add_checkbox_stack(
            visual_layout,
            (
                self._checkbox("Orb voice sync", "companion_orb_voice_sync_enabled_checkbox", "companion_orb_voice_sync_enabled", True),
                self._checkbox("Falling particles", "companion_orb_falling_particles_enabled_checkbox", "companion_orb_falling_particles_enabled", False),
                self._checkbox("Reduced effects", "companion_orb_reduced_effects_checkbox", "companion_orb_reduced_effects", False),
                self._checkbox("Particles", "companion_orb_particles_enabled_checkbox", "companion_orb_particles_enabled", True),
                self._checkbox("Shader effects", "companion_orb_shaders_enabled_checkbox", "companion_orb_shaders_enabled", True),
            ),
        )

        toggle_grid.add_widgets((window_group, behavior_group, visual_group))
        layout.addWidget(toggle_grid)

        slider_group, slider_group_layout = self._section_group("Orb Tuning", "companion_orb_tuning_group")
        color_group, color_layout = self._section_group("Custom Colors", "companion_orb_custom_colors_group")
        color_layout.addWidget(
            self._checkbox(
                "Custom orb colors",
                "companion_orb_custom_colors_enabled_checkbox",
                "companion_orb_custom_colors_enabled",
                False,
            )
        )
        color_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=4, horizontal_spacing=10, vertical_spacing=6)
        color_grid.setObjectName("companion_orb_custom_color_grid")
        for label, key, default in (
            ("Primary", "companion_orb_primary_color", "#22d3ee"),
            ("Secondary", "companion_orb_secondary_color", "#38bdf8"),
            ("Accent", "companion_orb_accent_color", "#a78bfa"),
            ("Glow", "companion_orb_glow_color", "#67e8f9"),
        ):
            color_grid.add_widget(self._color_setting_row(label, key, default))
        color_layout.addWidget(color_grid)
        slider_group_layout.addWidget(color_group)

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

        tuning_cards = _ResponsiveGridWidget(min_column_width=330, max_columns=2, horizontal_spacing=12, vertical_spacing=8)
        tuning_cards.setObjectName("companion_orb_tuning_cards_grid")
        tuning_cards.add_widgets(
            (
                self._companion_orb_slider_group(
                    "Size & Visibility",
                    "companion_orb_size_visibility_group",
                    (
                        ("companion_orb_size", "companion_orb_size_slider", "Orb Size", 36, 220, 92, True),
                        ("companion_orb_opacity", "companion_orb_opacity_slider", "Orb Opacity", 0.10, 1.00, 0.82, False),
                        ("companion_orb_frame_rate", "companion_orb_frame_rate_slider", "Orb Frame Rate", 30, 120, 60, True),
                    ),
                ),
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
                        ("companion_orb_audio_refresh_hz", "companion_orb_audio_refresh_slider", "Orb Sync Rate", 5, 30, 24, True),
                    ),
                ),
            )
        )
        slider_group_layout.addWidget(tuning_cards)
        layout.addWidget(slider_group)
        layout.addWidget(self._build_companion_orb_sensory_tabs())

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
        layout.addWidget(hotkey_group)
        self._apply_companion_orb_tooltips(group)
        return group

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
        self._sync_reply_style_prompt_editor_from_runtime(
            _runtime_config().get("companion_orb_response_style", "friendly")
        )
        source_checkbox = self._controls.get("companion_orb_sensory_target_enabled")
        if source_checkbox is not None and hasattr(source_checkbox, "setChecked"):
            checked = bool(_runtime_config().get("companion_orb_sensory_target_enabled", False)) or self._companion_orb_source_included()
            try:
                source_checkbox.blockSignals(True)
                source_checkbox.setChecked(checked)
            finally:
                source_checkbox.blockSignals(False)
        for key, swatch in list(getattr(self, "_orb_color_swatches", {}).items()):
            widget = self._controls.get(key)
            if widget is not None and hasattr(widget, "text"):
                swatch.setStyleSheet(self._color_swatch_style(widget.text()))
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
        if bool(_runtime_config().get("companion_orb_supervisor_enabled", False)):
            if not bool(_runtime_config().get("companion_orb_sensory_target_enabled", False)):
                _update_runtime_config("companion_orb_sensory_target_enabled", True)
            self._set_companion_orb_source_included(True)
        self._register_companion_orb_supervisor_contributor()
        return result

    def shutdown(self):
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
    left: 0px;
}
QTabWidget#companion_orb_sensory_tabs QTabBar {
    background: #122033;
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
                self._checkbox("Right-click drag changes focus", "companion_orb_right_drag_focus_enabled_checkbox", "companion_orb_right_drag_focus_enabled", False),
            ),
        )

        debug_group, debug_layout = self._section_group("Advanced Debug", "companion_orb_supervisor_debug_group")
        debug_layout.addWidget(
            self._checkbox("Movement and snapshot debug log", "companion_orb_debug_enabled_checkbox", "companion_orb_debug_enabled", False)
        )
        debug_layout.addWidget(
            self._read_only_text(
                "When enabled, snapshot captures, OCR focus matches, movement targets, and background check-ins are written to:\n"
                "runtime/companion_orb/debug/companion_orb_debug.log",
                "companion_orb_debug_log_path_preview",
                height=76,
            )
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

        response_grid.add_widgets((reply_group, debug_group, flow_group, focus_group))
        layout.addWidget(response_grid)
        layout.addStretch(1)
        return widget
