from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ui.widgets.basic import LabeledSlider, NoWheelComboBox


DISPLAY_MODES = [
    ("Off", "off"),
    ("Fullscreen", "fullscreen"),
    ("Floating Window", "floating"),
    ("Both", "both"),
]

VISUAL_STYLES = [
    ("Original Neural Orb", "classic_neural_orb"),
    ("Breathing Orb", "breathing_orb"),
    ("Neural Network Pulse", "neural_network_pulse"),
    ("Blue Flame Smoke", "blue_flame_smoke"),
    ("Neural Face - Male", "neural_face_male"),
    ("Neural Face - Female", "neural_face_female"),
    ("Neural Face - Auto Persona", "neural_face_auto"),
    ("Vector Voice Orb", "vector_voice_orb"),
    ("Circular Audio Waveform", "circular_audio_waveform"),
    ("Halo Rings", "halo_rings"),
    ("Minimal Dot", "minimal_dot"),
    ("Hologram Core", "hologram_core"),
    ("Signal Bloom", "signal_bloom"),
    ("Crystal Prism", "crystal_prism"),
]

CORE_VISUAL_STYLES = [
    item for item in VISUAL_STYLES if not str(item[1]).startswith("neural_face_")
]

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

FACE_VARIANTS = [
    ("Auto Persona", "auto"),
    ("Male", "male"),
    ("Female", "female"),
]

ORB_DISPLAY_MODES = [
    ("Off", "off"),
    ("Docked only", "docked"),
    ("During interaction only", "interaction"),
    ("Always visible", "always"),
]

ORB_POSITIONS = [
    ("Bottom right", "bottom-right"),
    ("Bottom left", "bottom-left"),
    ("Top right", "top-right"),
    ("Top left", "top-left"),
    ("Custom", "custom"),
]

ORB_VISUAL_STYLES = [
    ("Soft Plasma Orb", "soft_plasma"),
    ("Neural Spark Orb", "neural_spark"),
    ("Smoke Wisp Orb", "smoke_wisp"),
    ("Hologram Drone Orb", "hologram_drone"),
    ("Mood Orb", "mood_orb"),
]

ORB_TARGET_MODES = [
    ("Window under orb", "window"),
    ("Region around orb", "region"),
]

ORB_RESPONSE_STYLES = [
    ("Very friendly", "friendly"),
    ("Very loving", "loving"),
    ("Sarcastic / ironic", "sarcastic"),
    ("Roast mode", "roast"),
    ("Sensual / non-explicit", "sensual_non_explicit"),
]

BOOL_SETTINGS = {
    "ai_presence_enabled",
    "ai_presence_fullscreen",
    "ai_presence_floating_always_on_top",
    "ai_presence_remember_floating_geometry",
    "ai_presence_click_through_default",
    "ai_presence_right_drag_move_enabled",
    "ai_presence_transparent_background",
    "ai_presence_reduced_effects",
    "ai_presence_shaders_enabled",
    "ai_presence_particles_enabled",
    "ai_presence_space_closes_fullscreen",
    "ai_presence_music_reactivity_enabled",
    "ai_presence_mood_colors_enabled",
    "ai_presence_allow_story_mood_override",
    "ai_presence_allow_persona_mood_override",
    "ai_presence_neural_face_enabled",
    "ai_presence_neural_face_eye_movement_enabled",
    "ai_presence_neural_face_blink_enabled",
    "ai_presence_neural_face_glow_enabled",
    "ai_presence_neural_face_emotion_enabled",
    "ai_presence_neural_face_use_tts_emotion",
    "ai_presence_neural_face_audio_lipsync_enabled",
    "ai_presence_neural_face_reduced_animation",
    "ai_presence_female_neural_face_enabled",
    "ai_presence_female_reference_nodes",
    "ai_presence_female_show_wire_nodes",
    "ai_presence_female_show_wire_lines",
    "ai_presence_female_node_glow_enabled",
    "ai_presence_female_wire_pulse_enabled",
    "ai_presence_female_depth_enabled",
    "companion_orb_enabled",
    "companion_orb_always_on_top",
    "companion_orb_click_through_default",
    "companion_orb_right_drag_focus_enabled",
    "companion_orb_remember_position",
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
    "companion_orb_sensory_target_enabled",
    "companion_orb_full_screen_context_enabled",
    "companion_orb_show_target_label",
    "companion_orb_include_process_name",
    "companion_orb_require_target_confirmation",
    "companion_orb_hotkeys_enabled",
}

AI_PRESENCE_SESSION_KEYS = [
    "ai_presence_enabled",
    "ai_presence_display_mode",
    "ai_presence_visual_style",
    "ai_presence_fullscreen",
    "ai_presence_overlay_opacity",
    "ai_presence_floating_opacity",
    "ai_presence_floating_always_on_top",
    "ai_presence_remember_floating_geometry",
    "ai_presence_click_through_default",
    "ai_presence_right_drag_move_enabled",
    "ai_presence_transparent_background",
    "ai_presence_floating_geometry",
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
    "ai_presence_primary_color_strength",
    "ai_presence_secondary_color_strength",
    "ai_presence_background_darkness",
    "ai_presence_halo_thickness",
    "ai_presence_waveform_strength",
    "ai_presence_ring_expansion_speed",
    "ai_presence_blur_softness",
    "ai_presence_line_brightness",
    "ai_presence_live_controls_visible",
    "ai_presence_neural_face_enabled",
    "ai_presence_neural_face_variant",
    "ai_presence_neural_face_size",
    "ai_presence_neural_face_opacity",
    "ai_presence_neural_face_animation_intensity",
    "ai_presence_neural_face_lipsync_strength",
    "ai_presence_neural_face_eye_movement_enabled",
    "ai_presence_neural_face_blink_enabled",
    "ai_presence_neural_face_glow_enabled",
    "ai_presence_neural_face_emotion_enabled",
    "ai_presence_neural_face_use_tts_emotion",
    "ai_presence_neural_face_audio_lipsync_enabled",
    "ai_presence_neural_face_reduced_animation",
    "ai_presence_female_neural_face_enabled",
    "ai_presence_female_reference_nodes",
    "ai_presence_female_show_wire_nodes",
    "ai_presence_female_show_wire_lines",
    "ai_presence_female_node_glow_enabled",
    "ai_presence_female_wire_pulse_enabled",
    "ai_presence_female_depth_enabled",
    "companion_orb_enabled",
    "companion_orb_display_mode",
    "companion_orb_position",
    "companion_orb_size",
    "companion_orb_opacity",
    "companion_orb_always_on_top",
    "companion_orb_click_through_default",
    "companion_orb_right_drag_focus_enabled",
    "companion_orb_remember_position",
    "companion_orb_custom_position",
    "companion_orb_movement_enabled",
    "companion_orb_movement_speed",
    "companion_orb_movement_range",
    "companion_orb_return_home_delay",
    "companion_orb_harassment_enabled",
    "companion_orb_response_style",
    "companion_orb_harassment_timer_seconds",
    "companion_orb_snapshot_on_pointer_reached",
    "companion_orb_debug_enabled",
    "companion_orb_avoid_center",
    "companion_orb_avoid_mouse",
    "companion_orb_mouse_near_fade",
    "companion_orb_mouse_near_fade_distance",
    "companion_orb_mouse_near_opacity",
    "companion_orb_visual_style",
    "companion_orb_trail_length",
    "companion_orb_particle_density",
    "companion_orb_falling_particles_enabled",
    "companion_orb_falling_particle_density",
    "companion_orb_falling_particle_lifetime",
    "companion_orb_smoke_intensity",
    "companion_orb_glow_strength",
    "companion_orb_mood_color_intensity",
    "companion_orb_speaking_reactivity",
    "companion_orb_voice_sync_enabled",
    "companion_orb_audio_refresh_hz",
    "companion_orb_reduced_effects",
    "companion_orb_particles_enabled",
    "companion_orb_shaders_enabled",
    "companion_orb_sensory_target_enabled",
    "companion_orb_full_screen_context_enabled",
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

NEURAL_FACE_SESSION_KEYS = [
    key
    for key in AI_PRESENCE_SESSION_KEYS
    if key.startswith("ai_presence_neural_face_") or key.startswith("ai_presence_female_")
]

COMPANION_ORB_SESSION_KEYS = [
    key for key in AI_PRESENCE_SESSION_KEYS if key.startswith("companion_orb_")
]

AI_PRESENCE_CORE_SESSION_KEYS = [
    key
    for key in AI_PRESENCE_SESSION_KEYS
    if key not in set(NEURAL_FACE_SESSION_KEYS) | set(COMPANION_ORB_SESSION_KEYS)
]

DEFAULT_SETTINGS = {
    "ai_presence_enabled": False,
    "ai_presence_display_mode": "fullscreen",
    "ai_presence_visual_style": "breathing_orb",
    "ai_presence_fullscreen": True,
    "ai_presence_overlay_opacity": 0.72,
    "ai_presence_floating_opacity": 0.92,
    "ai_presence_floating_always_on_top": True,
    "ai_presence_remember_floating_geometry": True,
    "ai_presence_click_through_default": False,
    "ai_presence_right_drag_move_enabled": False,
    "ai_presence_transparent_background": False,
    "ai_presence_floating_geometry": [],
    "ai_presence_thinking_pulse": 0.55,
    "ai_presence_speaking_reactivity": 0.85,
    "ai_presence_audio_refresh_hz": 30,
    "ai_presence_node_density": 32,
    "ai_presence_particle_density": 28,
    "ai_presence_reduced_effects": False,
    "ai_presence_shaders_enabled": True,
    "ai_presence_particles_enabled": True,
    "ai_presence_space_closes_fullscreen": True,
    "ai_presence_music_reactivity_enabled": False,
    "ai_presence_music_reactivity": 0.65,
    "ai_presence_mood_colors_enabled": True,
    "ai_presence_mood_color_mode": "automatic",
    "ai_presence_manual_mood": "neutral",
    "ai_presence_mood_color_intensity": 0.85,
    "ai_presence_allow_story_mood_override": True,
    "ai_presence_allow_persona_mood_override": True,
    "ai_presence_glow_strength": 1.0,
    "ai_presence_animation_speed": 1.0,
    "ai_presence_primary_color_strength": 1.0,
    "ai_presence_secondary_color_strength": 1.0,
    "ai_presence_background_darkness": 1.0,
    "ai_presence_halo_thickness": 1.0,
    "ai_presence_waveform_strength": 1.0,
    "ai_presence_ring_expansion_speed": 1.0,
    "ai_presence_blur_softness": 0.35,
    "ai_presence_line_brightness": 1.0,
    "ai_presence_live_controls_visible": False,
    "ai_presence_neural_face_enabled": True,
    "ai_presence_neural_face_variant": "auto",
    "ai_presence_neural_face_size": 1.0,
    "ai_presence_neural_face_opacity": 0.92,
    "ai_presence_neural_face_animation_intensity": 0.78,
    "ai_presence_neural_face_lipsync_strength": 1.0,
    "ai_presence_neural_face_eye_movement_enabled": True,
    "ai_presence_neural_face_blink_enabled": True,
    "ai_presence_neural_face_glow_enabled": True,
    "ai_presence_neural_face_emotion_enabled": True,
    "ai_presence_neural_face_use_tts_emotion": True,
    "ai_presence_neural_face_audio_lipsync_enabled": True,
    "ai_presence_neural_face_reduced_animation": False,
    "ai_presence_female_neural_face_enabled": True,
    "ai_presence_female_reference_nodes": True,
    "ai_presence_female_show_wire_nodes": True,
    "ai_presence_female_show_wire_lines": True,
    "ai_presence_female_node_glow_enabled": True,
    "ai_presence_female_wire_pulse_enabled": True,
    "ai_presence_female_depth_enabled": True,
    "companion_orb_enabled": False,
    "companion_orb_display_mode": "off",
    "companion_orb_position": "bottom-right",
    "companion_orb_size": 92,
    "companion_orb_opacity": 0.82,
    "companion_orb_always_on_top": True,
    "companion_orb_click_through_default": True,
    "companion_orb_right_drag_focus_enabled": False,
    "companion_orb_remember_position": True,
    "companion_orb_custom_position": [],
    "companion_orb_movement_enabled": True,
    "companion_orb_movement_speed": 0.65,
    "companion_orb_movement_range": 18,
    "companion_orb_return_home_delay": 2.5,
    "companion_orb_harassment_enabled": False,
    "companion_orb_response_style": "friendly",
    "companion_orb_harassment_timer_seconds": 45,
    "companion_orb_snapshot_on_pointer_reached": False,
    "companion_orb_debug_enabled": False,
    "companion_orb_avoid_center": True,
    "companion_orb_avoid_mouse": False,
    "companion_orb_mouse_near_fade": False,
    "companion_orb_mouse_near_fade_distance": 120,
    "companion_orb_mouse_near_opacity": 0.28,
    "companion_orb_visual_style": "soft_plasma",
    "companion_orb_trail_length": 0.55,
    "companion_orb_particle_density": 30,
    "companion_orb_falling_particles_enabled": False,
    "companion_orb_falling_particle_density": 18,
    "companion_orb_falling_particle_lifetime": 3.8,
    "companion_orb_smoke_intensity": 0.35,
    "companion_orb_glow_strength": 1.0,
    "companion_orb_mood_color_intensity": 0.85,
    "companion_orb_speaking_reactivity": 0.85,
    "companion_orb_voice_sync_enabled": True,
    "companion_orb_audio_refresh_hz": 24,
    "companion_orb_reduced_effects": False,
    "companion_orb_particles_enabled": True,
    "companion_orb_shaders_enabled": True,
    "companion_orb_sensory_target_enabled": False,
    "companion_orb_full_screen_context_enabled": False,
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


def _runtime_config():
    try:
        from ui.runtime.engine_access import RUNTIME_CONFIG

        return RUNTIME_CONFIG
    except Exception:
        return {}


def _setting(key):
    return _runtime_config().get(key, DEFAULT_SETTINGS.get(key))


def _update_runtime_config(key, value):
    try:
        from ui.runtime.engine_access import update_runtime_config

        return update_runtime_config(key, value)
    except Exception:
        _runtime_config()[str(key)] = value
        return value


class _ResponsiveGridWidget(QtWidgets.QWidget):
    """Compact width-aware grid for addon settings pages."""

    def __init__(self, *, min_column_width=260, max_columns=3, horizontal_spacing=12, vertical_spacing=8, parent=None):
        super().__init__(parent)
        self._items: list[QtWidgets.QWidget] = []
        self._min_column_width = max(120, int(min_column_width))
        self._max_columns = max(1, int(max_columns))
        self._last_columns = 0
        self._layout = QtWidgets.QGridLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setHorizontalSpacing(int(horizontal_spacing))
        self._layout.setVerticalSpacing(int(vertical_spacing))
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

    def add_widget(self, widget):
        if widget is None:
            return
        widget.setParent(self)
        self._items.append(widget)
        self._relayout(force=True)

    def add_widgets(self, widgets):
        for widget in widgets:
            self.add_widget(widget)

    def _column_count(self):
        available = max(1, int(self.contentsRect().width() or self.width() or self._min_column_width * self._max_columns))
        columns = max(1, min(self._max_columns, available // self._min_column_width))
        return columns

    def _relayout(self, *, force=False):
        columns = self._column_count()
        if not force and columns == self._last_columns:
            return
        self._last_columns = columns
        while self._layout.count():
            self._layout.takeAt(0)
        for index, widget in enumerate(self._items):
            self._layout.addWidget(widget, index // columns, index % columns)
        for column in range(self._max_columns):
            self._layout.setColumnStretch(column, 1 if column < columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self._relayout(force=True)


class AIPresenceModeController(QtCore.QObject):
    SESSION_KEYS = AI_PRESENCE_CORE_SESSION_KEYS
    APPLY_STATUS_MESSAGE = "AI Presence settings applied."

    def __init__(self, context):
        super().__init__()
        self.context = context
        self._widgets: list[QtWidgets.QWidget] = []
        self._controls: dict[str, QtWidgets.QWidget] = {}
        self._preview_timer = None

    def _build_card_shell(self, tab_object_name, content_object_name, card_object_name, title_text):
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName(tab_object_name)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

        content = QtWidgets.QWidget()
        content.setObjectName(content_object_name)
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        card = QtWidgets.QFrame()
        card.setObjectName(card_object_name)
        card.setStyleSheet(
            f"QFrame#{card_object_name} {{"
            "  background: rgba(10, 18, 30, 0.72);"
            "  border: 1px solid #2f4b68;"
            "  border-radius: 8px;"
            "}"
        )
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(10)

        title = QtWidgets.QLabel(title_text)
        title.setObjectName(f"{card_object_name}_title")
        title.setStyleSheet("font-size: 14px; font-weight: 800; color: #ecfeff;")
        card_layout.addWidget(title)

        layout.addWidget(card)
        layout.addStretch(1)
        scroll.setWidget(content)
        self._widgets.append(scroll)
        return scroll, card_layout

    def _status_label(self, text, object_name):
        label = QtWidgets.QLabel(text)
        label.setObjectName(object_name)
        label.setWordWrap(True)
        label.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        return label

    def _compact_label(self, text):
        label = QtWidgets.QLabel(str(text or ""))
        label.setStyleSheet("color: #9fb3c8; font-size: 11px; font-weight: 600;")
        label.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        return label

    def _section_group(self, title, object_name):
        group = QtWidgets.QGroupBox(title)
        group.setObjectName(object_name)
        group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        group.setStyleSheet(
            f"QGroupBox#{object_name} {{"
            "  border: 1px solid #29445f;"
            "  border-radius: 7px;"
            "  margin-top: 8px;"
            "  background: rgba(6, 13, 23, 0.34);"
            "}"
            f"QGroupBox#{object_name}::title {{"
            "  subcontrol-origin: margin;"
            "  left: 8px;"
            "  padding: 0 4px;"
            "  color: #c8d7e8;"
            "  font-size: 11px;"
            "  font-weight: 700;"
            "}"
        )
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 9)
        layout.setSpacing(7)
        return group, layout

    def _add_checkbox_stack(self, layout, checkboxes):
        for checkbox in checkboxes:
            checkbox.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            layout.addWidget(checkbox)
        layout.addStretch(1)

    def build_tab(self):
        scroll, card_layout = self._build_card_shell(
            "ai_presence_mode_addon_tab",
            "ai_presence_mode_content",
            "ai_presence_mode_card",
            "AI PRESENCE MODE",
        )

        display_group, display_layout = self._section_group("Display & Preview", "ai_presence_display_group")
        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(8)
        selector_grid.setVerticalSpacing(4)
        self.display_mode_combo = self._combo("ai_presence_display_mode_combo", DISPLAY_MODES, "ai_presence_display_mode", "fullscreen")
        self.visual_style_combo = self._combo("ai_presence_visual_style_combo", CORE_VISUAL_STYLES, "ai_presence_visual_style", "breathing_orb")
        selector_grid.addWidget(self._compact_label("Display"), 0, 0)
        selector_grid.addWidget(self.display_mode_combo, 0, 1)
        selector_grid.addWidget(self._compact_label("Style"), 0, 2)
        selector_grid.addWidget(self.visual_style_combo, 0, 3)
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 1)
        display_layout.addLayout(selector_grid)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.preview_button = QtWidgets.QPushButton("Show Fullscreen")
        self.preview_button.setObjectName("ai_presence_preview_button")
        self.preview_button.clicked.connect(self._show_fullscreen_preview)
        self.floating_button = QtWidgets.QPushButton("Show Floating")
        self.floating_button.setObjectName("ai_presence_floating_button")
        self.floating_button.clicked.connect(self._show_floating)
        self.reset_floating_button = QtWidgets.QPushButton("Reset Floating Position")
        self.reset_floating_button.setObjectName("ai_presence_reset_floating_position_button")
        self.reset_floating_button.setToolTip("Center the AI Presence floating window on the current screen.")
        self.reset_floating_button.clicked.connect(self._reset_floating_position)
        for button in (
            self.preview_button,
            self.floating_button,
            self.reset_floating_button,
        ):
            button.setMinimumHeight(27)
            button.setMaximumHeight(31)
            button.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
            action_row.addWidget(button)
        action_row.addStretch(1)
        display_layout.addLayout(action_row)
        card_layout.addWidget(display_group)

        toggle_grid = _ResponsiveGridWidget(min_column_width=235, max_columns=3, horizontal_spacing=10, vertical_spacing=8)
        toggle_grid.setObjectName("ai_presence_toggle_groups_grid")

        mode_group, mode_layout = self._section_group("Mode", "ai_presence_mode_toggles_group")
        self.enabled_checkbox = self._checkbox("Enable AI Presence Mode", "ai_presence_enabled_checkbox", "ai_presence_enabled", False)
        self.fullscreen_checkbox = self._checkbox("Fullscreen overlay", "ai_presence_fullscreen_checkbox", "ai_presence_fullscreen", True)
        self.reduced_checkbox = self._checkbox("Reduced effects", "ai_presence_reduced_effects_checkbox", "ai_presence_reduced_effects", False)
        self._add_checkbox_stack(
            mode_layout,
            (
                self.enabled_checkbox,
                self.fullscreen_checkbox,
                self.reduced_checkbox,
                self._checkbox("Space exits fullscreen", "ai_presence_space_closes_fullscreen_checkbox", "ai_presence_space_closes_fullscreen", True),
            ),
        )

        floating_group, floating_layout = self._section_group("Floating Window", "ai_presence_floating_toggles_group")
        self._add_checkbox_stack(
            floating_layout,
            (
                self._checkbox("Always on top", "ai_presence_floating_always_on_top_checkbox", "ai_presence_floating_always_on_top", True),
                self._checkbox("Remember size", "ai_presence_remember_floating_geometry_checkbox", "ai_presence_remember_floating_geometry", True),
                self._checkbox("Click-through by default", "ai_presence_click_through_default_checkbox", "ai_presence_click_through_default", False),
                self._checkbox("Right-click drag moves window", "ai_presence_right_drag_move_enabled_checkbox", "ai_presence_right_drag_move_enabled", False),
                self._checkbox("Transparent background", "ai_presence_transparent_background_checkbox", "ai_presence_transparent_background", False),
            ),
        )

        visual_group, visual_layout = self._section_group("Visual Inputs", "ai_presence_visual_toggles_group")
        self._add_checkbox_stack(
            visual_layout,
            (
                self._checkbox("Soft glow", "ai_presence_shaders_enabled_checkbox", "ai_presence_shaders_enabled", True),
                self._checkbox("Particles", "ai_presence_particles_enabled_checkbox", "ai_presence_particles_enabled", True),
                self._checkbox("Computer audio sync", "ai_presence_music_reactivity_enabled_checkbox", "ai_presence_music_reactivity_enabled", False),
            ),
        )

        mood_group, mood_layout = self._section_group("Mood Colors", "ai_presence_mood_group")
        mood_grid = QtWidgets.QGridLayout()
        mood_grid.setContentsMargins(0, 0, 0, 0)
        mood_grid.setHorizontalSpacing(8)
        mood_grid.setVerticalSpacing(4)
        self.mood_colors_checkbox = self._checkbox("Enable Mood Colors", "ai_presence_mood_colors_enabled_checkbox", "ai_presence_mood_colors_enabled", True)
        self.mood_mode_combo = self._combo("ai_presence_mood_color_mode_combo", MOOD_COLOR_MODES, "ai_presence_mood_color_mode", "automatic")
        self.manual_mood_combo = self._combo("ai_presence_manual_mood_combo", MOOD_CHOICES, "ai_presence_manual_mood", "neutral")
        self.story_mood_checkbox = self._checkbox("Story mood override", "ai_presence_allow_story_mood_override_checkbox", "ai_presence_allow_story_mood_override", True)
        self.persona_mood_checkbox = self._checkbox("Persona mood override", "ai_presence_allow_persona_mood_override_checkbox", "ai_presence_allow_persona_mood_override", True)
        mood_grid.addWidget(self.mood_colors_checkbox, 0, 0, 1, 2)
        mood_grid.addWidget(self._compact_label("Mode"), 1, 0)
        mood_grid.addWidget(self.mood_mode_combo, 1, 1)
        mood_grid.addWidget(self._compact_label("Manual"), 2, 0)
        mood_grid.addWidget(self.manual_mood_combo, 2, 1)
        mood_grid.addWidget(self.story_mood_checkbox, 3, 0, 1, 2)
        mood_grid.addWidget(self.persona_mood_checkbox, 4, 0, 1, 2)
        mood_grid.setColumnStretch(1, 1)
        mood_layout.addLayout(mood_grid)

        toggle_grid.add_widgets((mode_group, floating_group, visual_group, mood_group))
        card_layout.addWidget(toggle_grid)

        slider_group, slider_group_layout = self._section_group("Visual Tuning", "ai_presence_visual_tuning_group")
        slider_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=3, horizontal_spacing=12, vertical_spacing=7)
        slider_grid.setObjectName("ai_presence_slider_responsive_grid")
        sliders = [
            ("ai_presence_overlay_opacity", "ai_presence_opacity_slider", "Opacity", 0.10, 1.00, 0.72, False),
            ("ai_presence_thinking_pulse", "ai_presence_thinking_slider", "Thinking Pulse", 0.10, 1.00, 0.55, False),
            ("ai_presence_speaking_reactivity", "ai_presence_speaking_slider", "Speaking Reactivity", 0.10, 1.50, 0.85, False),
            ("ai_presence_audio_refresh_hz", "ai_presence_audio_refresh_slider", "Audio Sync Rate", 5, 30, 30, True),
            ("ai_presence_node_density", "ai_presence_density_slider", "Neural Node Density", 8, 96, 32, True),
            ("ai_presence_particle_density", "ai_presence_particle_density_slider", "Particle Density", 0, 120, 28, True),
            ("ai_presence_floating_opacity", "ai_presence_floating_opacity_slider", "Floating Opacity", 0.35, 1.00, 0.92, False),
            ("ai_presence_music_reactivity", "ai_presence_music_reactivity_slider", "Music Reactivity", 0.00, 1.50, 0.65, False),
            ("ai_presence_mood_color_intensity", "ai_presence_mood_color_intensity_slider", "Mood Color Intensity", 0.00, 1.00, 0.85, False),
            ("ai_presence_glow_strength", "ai_presence_glow_strength_slider", "Glow Strength", 0.00, 1.75, 1.0, False),
            ("ai_presence_animation_speed", "ai_presence_animation_speed_slider", "Animation Speed", 0.35, 1.75, 1.0, False),
            ("ai_presence_primary_color_strength", "ai_presence_primary_color_strength_slider", "Primary Color Strength", 0.00, 1.50, 1.0, False),
            ("ai_presence_secondary_color_strength", "ai_presence_secondary_color_strength_slider", "Secondary Color Strength", 0.00, 1.50, 1.0, False),
            ("ai_presence_background_darkness", "ai_presence_background_darkness_slider", "Background Darkness", 0.00, 1.00, 1.0, False),
            ("ai_presence_halo_thickness", "ai_presence_halo_thickness_slider", "Halo Thickness", 0.35, 2.00, 1.0, False),
            ("ai_presence_waveform_strength", "ai_presence_waveform_strength_slider", "Waveform Strength", 0.20, 2.00, 1.0, False),
            ("ai_presence_ring_expansion_speed", "ai_presence_ring_expansion_speed_slider", "Ring Expansion Speed", 0.25, 2.00, 1.0, False),
            ("ai_presence_blur_softness", "ai_presence_blur_softness_slider", "Blur / Softness", 0.00, 1.00, 0.35, False),
            ("ai_presence_line_brightness", "ai_presence_line_brightness_slider", "Line Brightness", 0.20, 2.00, 1.0, False),
        ]
        for spec in sliders:
            slider = self._slider(*spec)
            slider_grid.add_widget(slider)
        slider_group_layout.addWidget(slider_grid)
        card_layout.addWidget(slider_group)

        split_hint = QtWidgets.QLabel(
            "Neural Face Presence and Companion Orb Overlay now have their own addon tabs, so their settings are saved separately from this AI Presence overlay tab. Right double-click the floating AI Presence window to cycle visual styles when click-through is off."
        )
        split_hint.setWordWrap(True)
        split_hint.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        card_layout.addWidget(split_hint)

        self.status_label = self._status_label("AI Presence addon controls are ready.", "ai_presence_status_label")
        card_layout.addWidget(self.status_label)

        self.refresh_from_runtime()
        return scroll

    def _combo(self, object_name, items, key, default):
        combo = NoWheelComboBox()
        combo.setObjectName(object_name)
        for label, value in items:
            combo.addItem(label, value)
        combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(12)
        combo.setMinimumHeight(26)
        combo.setMaximumHeight(30)
        combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._controls[key] = combo
        self._set_combo_value(combo, _runtime_config().get(key, DEFAULT_SETTINGS.get(key, default)))
        combo.currentIndexChanged.connect(lambda _index, setting_key=key, widget=combo: self._on_combo_changed(setting_key, widget))
        return combo

    def _checkbox(self, label, object_name, key, default):
        checkbox = QtWidgets.QCheckBox(label)
        checkbox.setObjectName(object_name)
        checkbox.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        checkbox.setChecked(bool(_runtime_config().get(key, DEFAULT_SETTINGS.get(key, default))))
        self._controls[key] = checkbox
        checkbox.toggled.connect(lambda checked, setting_key=key: self._on_setting_changed(setting_key, bool(checked)))
        return checkbox

    def _slider(self, key, object_name, title, minimum, maximum, default, is_int):
        slider = LabeledSlider(title, minimum, maximum, _runtime_config().get(key, DEFAULT_SETTINGS.get(key, default)), is_int=is_int)
        slider.setObjectName(object_name)
        slider.setMinimumWidth(210)
        slider.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        slider_layout = slider.layout()
        if slider_layout is not None:
            slider_layout.setSpacing(3)
        label = getattr(slider, "label", None)
        if label is not None:
            label.setStyleSheet("font-weight: 600; color: #d8dee9; font-size: 11px;")
        self._controls[key] = slider
        slider.value_changed.connect(lambda value, setting_key=key, int_value=is_int: self._on_setting_changed(setting_key, int(value) if int_value else float(value)))
        return slider

    def _line_edit(self, object_name, key, default):
        edit = QtWidgets.QLineEdit()
        edit.setObjectName(object_name)
        edit.setText(str(_runtime_config().get(key, DEFAULT_SETTINGS.get(key, default)) or default))
        edit.setMinimumHeight(26)
        edit.setMaximumHeight(30)
        edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._controls[key] = edit
        edit.editingFinished.connect(lambda setting_key=key, widget=edit: self._on_setting_changed(setting_key, widget.text()))
        return edit

    def _build_neural_face_section(self):
        group = QtWidgets.QGroupBox("Neural Face Presence")
        group.setObjectName("ai_presence_neural_face_group")
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)

        intro = QtWidgets.QLabel(
            "Wireframe face styles for the main AI Presence overlay, with TTS lip sync, blink, gaze, emotion response, and vector glow."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        layout.addWidget(intro)

        selector_grid = QtWidgets.QGridLayout()
        selector_grid.setContentsMargins(0, 0, 0, 0)
        selector_grid.setHorizontalSpacing(10)
        selector_grid.setVerticalSpacing(6)
        selector_grid.addWidget(self._checkbox("Enable Neural Face Presence", "ai_presence_neural_face_enabled_checkbox", "ai_presence_neural_face_enabled", True), 0, 0, 1, 2)
        selector_grid.addWidget(QtWidgets.QLabel("Face style"), 0, 2)
        selector_grid.addWidget(self._combo("ai_presence_neural_face_variant_combo", FACE_VARIANTS, "ai_presence_neural_face_variant", "auto"), 0, 3)
        selector_grid.setColumnStretch(3, 1)
        layout.addLayout(selector_grid)

        option_grid = QtWidgets.QGridLayout()
        option_grid.setContentsMargins(0, 0, 0, 0)
        option_grid.setHorizontalSpacing(10)
        option_grid.setVerticalSpacing(4)
        option_boxes = [
            self._checkbox("Enable Female Neural Face", "ai_presence_female_neural_face_enabled_checkbox", "ai_presence_female_neural_face_enabled", True),
            self._checkbox("Reference orange nodes", "ai_presence_female_reference_nodes_checkbox", "ai_presence_female_reference_nodes", True),
            self._checkbox("Show wire nodes", "ai_presence_female_show_nodes_checkbox", "ai_presence_female_show_wire_nodes", True),
            self._checkbox("Show wire lines", "ai_presence_female_show_lines_checkbox", "ai_presence_female_show_wire_lines", True),
            self._checkbox("Female node glow", "ai_presence_female_node_glow_checkbox", "ai_presence_female_node_glow_enabled", True),
            self._checkbox("Female wire pulse", "ai_presence_female_wire_pulse_checkbox", "ai_presence_female_wire_pulse_enabled", True),
            self._checkbox("Female depth/parallax", "ai_presence_female_depth_checkbox", "ai_presence_female_depth_enabled", True),
            self._checkbox("Eye movement", "ai_presence_neural_face_eye_movement_checkbox", "ai_presence_neural_face_eye_movement_enabled", True),
            self._checkbox("Blink", "ai_presence_neural_face_blink_checkbox", "ai_presence_neural_face_blink_enabled", True),
            self._checkbox("Neural glow", "ai_presence_neural_face_glow_checkbox", "ai_presence_neural_face_glow_enabled", True),
            self._checkbox("Emotion reaction", "ai_presence_neural_face_emotion_checkbox", "ai_presence_neural_face_emotion_enabled", True),
            self._checkbox("Use TTS emotion metadata", "ai_presence_neural_face_tts_emotion_checkbox", "ai_presence_neural_face_use_tts_emotion", True),
            self._checkbox("Fallback audio lip-sync", "ai_presence_neural_face_audio_lipsync_checkbox", "ai_presence_neural_face_audio_lipsync_enabled", True),
            self._checkbox("Reduced face animation", "ai_presence_neural_face_reduced_checkbox", "ai_presence_neural_face_reduced_animation", False),
        ]
        for index, checkbox in enumerate(option_boxes):
            option_grid.addWidget(checkbox, index // 3, index % 3)
        layout.addLayout(option_grid)

        slider_grid = QtWidgets.QGridLayout()
        slider_grid.setContentsMargins(0, 0, 0, 0)
        slider_grid.setHorizontalSpacing(12)
        slider_grid.setVerticalSpacing(8)
        sliders = [
            ("ai_presence_neural_face_size", "ai_presence_neural_face_size_slider", "Face Size", 0.55, 1.35, 1.0, False),
            ("ai_presence_neural_face_opacity", "ai_presence_neural_face_opacity_slider", "Face Opacity", 0.15, 1.00, 0.92, False),
            ("ai_presence_neural_face_animation_intensity", "ai_presence_neural_face_animation_slider", "Face Animation", 0.00, 1.50, 0.78, False),
            ("ai_presence_neural_face_lipsync_strength", "ai_presence_neural_face_lipsync_slider", "Lip Sync Strength", 0.00, 1.75, 1.0, False),
        ]
        for index, spec in enumerate(sliders):
            slider_grid.addWidget(self._slider(*spec), index // 2, index % 2)
        layout.addLayout(slider_grid)
        return group

    def _build_companion_orb_section(self):
        group = QtWidgets.QGroupBox("Companion Orb Overlay")
        group.setObjectName("ai_presence_companion_orb_group")
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
        selector_grid.addWidget(self._combo("companion_orb_visual_style_combo", ORB_VISUAL_STYLES, "companion_orb_visual_style", "soft_plasma"), 1, 1)
        selector_grid.addWidget(self._compact_label("Position"), 1, 2)
        selector_grid.addWidget(self._combo("companion_orb_position_combo", ORB_POSITIONS, "companion_orb_position", "bottom-right"), 1, 3)
        selector_grid.setColumnStretch(1, 1)
        selector_grid.setColumnStretch(3, 1)
        display_layout.addLayout(selector_grid)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        for label, handler in (
            ("Show Orb", self._show_companion_orb),
            ("Edit Mode", self._toggle_companion_orb_edit_mode),
            ("Placement Mode", self._toggle_companion_orb_placement_mode),
            ("Clear Target", self._clear_companion_orb_target),
            ("Reset Position", self._reset_companion_orb_position),
        ):
            button = QtWidgets.QPushButton(label)
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
                self._checkbox("Right-click drag changes focus", "companion_orb_right_drag_focus_enabled_checkbox", "companion_orb_right_drag_focus_enabled", False),
                self._checkbox("Remember position", "companion_orb_remember_position_checkbox", "companion_orb_remember_position", True),
            ),
        )

        behavior_group, behavior_layout = self._section_group("Movement & Behavior", "companion_orb_behavior_toggles_group")
        self._add_checkbox_stack(
            behavior_layout,
            (
                self._checkbox("Movement enabled", "companion_orb_movement_enabled_checkbox", "companion_orb_movement_enabled", True),
                self._checkbox("Harassment", "companion_orb_harassment_enabled_checkbox", "companion_orb_harassment_enabled", False),
                self._checkbox("Snapshot at pointer", "companion_orb_snapshot_on_pointer_reached_checkbox", "companion_orb_snapshot_on_pointer_reached", False),
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

        sensory_group, sensory_layout = self._section_group("Sensory Focus", "companion_orb_sensory_group")
        sensory_grid = QtWidgets.QGridLayout()
        sensory_grid.setContentsMargins(0, 0, 0, 0)
        sensory_grid.setHorizontalSpacing(8)
        sensory_grid.setVerticalSpacing(4)
        sensory_grid.addWidget(self._checkbox("Use orb as sensory focus target", "companion_orb_sensory_target_enabled_checkbox", "companion_orb_sensory_target_enabled", False), 0, 0, 1, 2)
        sensory_grid.addWidget(self._compact_label("Target"), 1, 0)
        sensory_grid.addWidget(self._combo("companion_orb_target_mode_combo", ORB_TARGET_MODES, "companion_orb_target_mode", "window"), 1, 1)
        sensory_grid.addWidget(self._checkbox("Show selected target label", "companion_orb_show_target_label_checkbox", "companion_orb_show_target_label", True), 2, 0, 1, 2)
        process_checkbox = self._checkbox(
            "Mention process names",
            "companion_orb_include_process_name_checkbox",
            "companion_orb_include_process_name",
            True,
        )
        process_checkbox.setToolTip("When off, Companion Orb Target hides executable/process names from labels and hidden sensory metadata.")
        sensory_grid.addWidget(process_checkbox, 3, 0, 1, 2)
        sensory_grid.addWidget(self._checkbox("Require target confirmation", "companion_orb_require_target_confirmation_checkbox", "companion_orb_require_target_confirmation", True), 4, 0, 1, 2)
        full_context_checkbox = self._checkbox(
            "Full-screen context map",
            "companion_orb_full_screen_context_enabled_checkbox",
            "companion_orb_full_screen_context_enabled",
            False,
        )
        full_context_checkbox.setToolTip(
            "Opt-in: capture a full desktop screenshot for hidden sensory context so the orb can map text regions across the screen."
        )
        sensory_grid.addWidget(full_context_checkbox, 5, 0, 1, 2)
        sensory_grid.setColumnStretch(1, 1)
        sensory_layout.addLayout(sensory_grid)

        toggle_grid.add_widgets((window_group, behavior_group, visual_group, sensory_group))
        layout.addWidget(toggle_grid)

        slider_group, slider_group_layout = self._section_group("Orb Tuning", "companion_orb_tuning_group")
        slider_grid = _ResponsiveGridWidget(min_column_width=250, max_columns=3, horizontal_spacing=12, vertical_spacing=7)
        slider_grid.setObjectName("companion_orb_slider_responsive_grid")
        sliders = [
            ("companion_orb_size", "companion_orb_size_slider", "Orb Size", 36, 220, 92, True),
            ("companion_orb_opacity", "companion_orb_opacity_slider", "Orb Opacity", 0.10, 1.00, 0.82, False),
            ("companion_orb_movement_speed", "companion_orb_movement_speed_slider", "Movement Speed", 0.10, 1.50, 0.65, False),
            ("companion_orb_movement_range", "companion_orb_movement_range_slider", "Movement Range", 0, 90, 18, True),
            ("companion_orb_return_home_delay", "companion_orb_return_delay_slider", "Return-home Delay", 0.25, 30.00, 2.5, False),
            ("companion_orb_harassment_timer_seconds", "companion_orb_harassment_timer_slider", "Harassment Timer", 5, 300, 45, True),
            ("companion_orb_mouse_near_fade_distance", "companion_orb_mouse_fade_distance_slider", "Mouse Fade Distance", 24, 420, 120, True),
            ("companion_orb_mouse_near_opacity", "companion_orb_mouse_near_opacity_slider", "Mouse-near Opacity", 0.05, 1.00, 0.28, False),
            ("companion_orb_trail_length", "companion_orb_trail_length_slider", "Trail Length", 0.00, 1.00, 0.55, False),
            ("companion_orb_particle_density", "companion_orb_particle_density_slider", "Orb Particles", 0, 120, 30, True),
            ("companion_orb_falling_particle_density", "companion_orb_falling_particle_density_slider", "Drip Particles", 0, 80, 18, True),
            ("companion_orb_falling_particle_lifetime", "companion_orb_falling_particle_lifetime_slider", "Drip Lifetime", 0.80, 8.00, 3.8, False),
            ("companion_orb_smoke_intensity", "companion_orb_smoke_intensity_slider", "Smoke Intensity", 0.00, 1.00, 0.35, False),
            ("companion_orb_glow_strength", "companion_orb_glow_strength_slider", "Orb Glow", 0.00, 1.75, 1.0, False),
            ("companion_orb_mood_color_intensity", "companion_orb_mood_intensity_slider", "Orb Mood Color", 0.00, 1.00, 0.85, False),
            ("companion_orb_speaking_reactivity", "companion_orb_speaking_reactivity_slider", "Orb Voice Reactivity", 0.10, 1.50, 0.85, False),
            ("companion_orb_audio_refresh_hz", "companion_orb_audio_refresh_slider", "Orb Sync Rate", 5, 30, 24, True),
            ("companion_orb_target_region_width", "companion_orb_target_width_slider", "Target Region Width", 64, 2560, 640, True),
            ("companion_orb_target_region_height", "companion_orb_target_height_slider", "Target Region Height", 64, 1440, 420, True),
        ]
        for spec in sliders:
            slider_grid.add_widget(self._slider(*spec))
        slider_group_layout.addWidget(slider_grid)
        layout.addWidget(slider_group)

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
        return group

    def _set_combo_value(self, combo, value):
        target = str(value or "").strip().lower()
        for index in range(combo.count()):
            if str(combo.itemData(index) or "").strip().lower() == target:
                combo.setCurrentIndex(index)
                return

    def _on_combo_changed(self, key, combo):
        value = str(combo.currentData() or "").strip()
        if key == "ai_presence_display_mode":
            _update_runtime_config("ai_presence_enabled", value != "off")
            self._sync_checkbox("ai_presence_enabled", value != "off")
        if key == "companion_orb_display_mode":
            _update_runtime_config("companion_orb_enabled", value != "off")
            self._sync_checkbox("companion_orb_enabled", value != "off")
        self._on_setting_changed(key, value)

    def _on_setting_changed(self, key, value):
        key = str(key or "").strip()
        if not key:
            return
        normalized = self._normalize_setting(key, value)
        _update_runtime_config(key, normalized)
        self._apply_runtime_config()
        self._save_session()

    def _normalize_setting(self, key, value):
        if key in BOOL_SETTINGS:
            return bool(value)
        if key == "ai_presence_display_mode":
            mode = str(value or "fullscreen").strip().lower()
            return mode if mode in {item[1] for item in DISPLAY_MODES} else "fullscreen"
        if key == "ai_presence_visual_style":
            style = str(value or "breathing_orb").strip().lower()
            return style if style in {item[1] for item in VISUAL_STYLES} else "breathing_orb"
        if key == "companion_orb_display_mode":
            mode = str(value or "off").strip().lower()
            return mode if mode in {item[1] for item in ORB_DISPLAY_MODES} else "off"
        if key == "companion_orb_position":
            position = str(value or "bottom-right").strip().lower()
            return position if position in {item[1] for item in ORB_POSITIONS} else "bottom-right"
        if key == "companion_orb_visual_style":
            style = str(value or "soft_plasma").strip().lower()
            return style if style in {item[1] for item in ORB_VISUAL_STYLES} else "soft_plasma"
        if key == "companion_orb_target_mode":
            mode = str(value or "window").strip().lower()
            return mode if mode in {item[1] for item in ORB_TARGET_MODES} else "window"
        if key == "ai_presence_mood_color_mode":
            mode = str(value or "automatic").strip().lower()
            return mode if mode in {item[1] for item in MOOD_COLOR_MODES} else "automatic"
        if key == "ai_presence_manual_mood":
            mood = str(value or "neutral").strip().lower()
            return mood if mood in {item[1] for item in MOOD_CHOICES} else "neutral"
        if key == "ai_presence_neural_face_variant":
            variant = str(value or "auto").strip().lower()
            return variant if variant in {item[1] for item in FACE_VARIANTS} else "auto"
        if key == "ai_presence_audio_refresh_hz":
            return max(5, min(30, int(value)))
        if key == "ai_presence_node_density":
            return max(8, min(96, int(value)))
        if key == "ai_presence_particle_density":
            return max(0, min(120, int(value)))
        if key == "ai_presence_speaking_reactivity":
            return max(0.10, min(1.50, float(value)))
        if key == "ai_presence_music_reactivity":
            return max(0.00, min(1.50, float(value)))
        if key == "ai_presence_glow_strength":
            return max(0.00, min(1.75, float(value)))
        if key == "ai_presence_animation_speed":
            return max(0.35, min(1.75, float(value)))
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
        if key == "ai_presence_neural_face_size":
            return max(0.55, min(1.35, float(value)))
        if key == "ai_presence_neural_face_opacity":
            return max(0.15, min(1.00, float(value)))
        if key == "ai_presence_neural_face_animation_intensity":
            return max(0.00, min(1.50, float(value)))
        if key == "ai_presence_neural_face_lipsync_strength":
            return max(0.00, min(1.75, float(value)))
        if key == "companion_orb_size":
            return max(36, min(220, int(value)))
        if key in {"companion_orb_target_region_width", "companion_orb_target_region_height"}:
            return max(64, min(2560, int(value)))
        if key == "companion_orb_particle_density":
            return max(0, min(120, int(value)))
        if key == "companion_orb_falling_particle_density":
            return max(0, min(80, int(value)))
        if key == "companion_orb_falling_particle_lifetime":
            return max(0.80, min(8.00, float(value)))
        if key == "companion_orb_movement_range":
            return max(0, min(90, int(value)))
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
        if key.endswith("_hotkey"):
            return str(value or DEFAULT_SETTINGS.get(key, "") or "").strip()
        if key == "companion_orb_custom_position":
            return list(value or []) if isinstance(value, (list, tuple)) else []
        if key == "companion_orb_target_info":
            return dict(value or {}) if isinstance(value, dict) else {}
        if key in {"ai_presence_overlay_opacity", "ai_presence_thinking_pulse"}:
            return max(0.10, min(1.00, float(value)))
        return value

    def _sync_checkbox(self, key, checked):
        widget = self._controls.get(key)
        if widget is None or not hasattr(widget, "setChecked"):
            return
        try:
            widget.blockSignals(True)
            widget.setChecked(bool(checked))
        finally:
            widget.blockSignals(False)

    def _apply_runtime_config(self):
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.apply_settings(dict(_runtime_config()))
        except Exception as exc:
            self._set_status(f"AI Presence settings could not be applied: {exc}")
            return
        self._set_status(self.APPLY_STATUS_MESSAGE)

    def _show_fullscreen_preview(self):
        _update_runtime_config("ai_presence_enabled", True)
        _update_runtime_config("ai_presence_display_mode", "fullscreen")
        _update_runtime_config("ai_presence_fullscreen", True)
        self.refresh_from_runtime()
        self._apply_runtime_config()
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_ai_state("speaking")
            visual_presence_runtime.set_audio_level(0.58)
            QtCore.QTimer.singleShot(7000, self._finish_preview)
            self._set_status("Fullscreen preview running.")
        except Exception as exc:
            self._set_status(f"AI Presence preview failed: {exc}")
        self._save_session()

    def _show_floating(self):
        _update_runtime_config("ai_presence_enabled", True)
        _update_runtime_config("ai_presence_display_mode", "floating")
        self.refresh_from_runtime()
        self._apply_runtime_config()
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_ai_state("idle")
            visual_presence_runtime.set_audio_level(0.0)
            self._set_status("Floating AI Presence window opened.")
        except Exception as exc:
            self._set_status(f"Floating AI Presence failed: {exc}")
        self._save_session()

    def _reset_floating_position(self):
        _update_runtime_config("ai_presence_enabled", True)
        _update_runtime_config("ai_presence_display_mode", "floating")
        self.refresh_from_runtime()
        self._apply_runtime_config()
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.reset_ai_presence_floating_position()
            self._set_status("AI Presence floating window centered.")
        except Exception as exc:
            self._set_status(f"AI Presence floating position reset failed: {exc}")
        self._save_session()

    def _show_companion_orb(self):
        _update_runtime_config("companion_orb_enabled", True)
        if str(_runtime_config().get("companion_orb_display_mode", "off") or "off") == "off":
            _update_runtime_config("companion_orb_display_mode", "docked")
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
        _update_runtime_config("companion_orb_target_info", {})
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.clear_companion_orb_target()
        except Exception:
            pass
        self._set_status("Companion Orb sensory target cleared.")
        self._save_session()

    def _reset_companion_orb_position(self):
        _update_runtime_config("companion_orb_custom_position", [])
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.reset_companion_orb_position()
        except Exception:
            pass
        self._set_status("Companion Orb position reset.")
        self._save_session()

    def _finish_preview(self):
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_audio_level(0.0)
            visual_presence_runtime.set_ai_state("idle")
        except Exception:
            pass

    def refresh_from_runtime(self):
        config = _runtime_config()
        for key, widget in list(self._controls.items()):
            value = config.get(key, DEFAULT_SETTINGS.get(key))
            if value is None:
                value = DEFAULT_SETTINGS.get(key)
            try:
                widget.blockSignals(True)
                if isinstance(widget, QtWidgets.QCheckBox):
                    widget.setChecked(bool(value))
                elif isinstance(widget, QtWidgets.QComboBox):
                    self._set_combo_value(widget, value)
                elif hasattr(widget, "set_value"):
                    widget.set_value(value)
            finally:
                try:
                    widget.blockSignals(False)
                except Exception:
                    pass

    def _save_session(self):
        app = QtWidgets.QApplication.instance()
        if app is None:
            return
        for widget in list(app.topLevelWidgets() or []):
            callback = getattr(widget, "save_session", None)
            if callable(callback):
                try:
                    callback()
                    return
                except Exception:
                    return

    def _set_status(self, text):
        label = getattr(self, "status_label", None)
        if label is not None:
            label.setText(str(text or ""))

    def export_session_state(self):
        config = _runtime_config()
        return {key: config.get(key) for key in self.SESSION_KEYS if key in config}

    def import_session_state(self, session):
        payload = dict(session or {})
        for key in self.SESSION_KEYS:
            if key in payload:
                _update_runtime_config(key, payload.get(key))
        self.refresh_from_runtime()
        self._apply_runtime_config()
        return None

    def shutdown(self):
        self._widgets.clear()
        self._controls.clear()
        return None


class NeuralFacePresenceController(AIPresenceModeController):
    SESSION_KEYS = NEURAL_FACE_SESSION_KEYS
    APPLY_STATUS_MESSAGE = "Neural Face Presence settings applied."

    def build_tab(self):
        scroll, card_layout = self._build_card_shell(
            "neural_face_presence_addon_tab",
            "neural_face_presence_content",
            "neural_face_presence_card",
            "NEURAL FACE PRESENCE",
        )

        intro = QtWidgets.QLabel(
            "Own settings for the wireframe face presence. These controls adjust face topology, lip sync, blink, gaze, glow, and female reference rendering without changing Companion Orb settings."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #9fb3c8; font-size: 11px;")
        card_layout.addWidget(intro)

        action_row = QtWidgets.QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        for label, handler in (
            ("Use Face Fullscreen", self._show_neural_face_fullscreen),
            ("Use Face Floating", self._show_neural_face_floating),
        ):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(handler)
            action_row.addWidget(button)
        action_row.addStretch(1)
        card_layout.addLayout(action_row)

        card_layout.addWidget(self._build_neural_face_section())

        self.status_label = self._status_label("Neural Face Presence controls are ready.", "neural_face_presence_status_label")
        card_layout.addWidget(self.status_label)
        self.refresh_from_runtime()
        return scroll

    def _active_face_style(self):
        variant = str(_runtime_config().get("ai_presence_neural_face_variant", "auto") or "auto").strip().lower()
        if variant == "male":
            return "neural_face_male"
        if variant == "female":
            return "neural_face_female"
        return "neural_face_auto"

    def _activate_neural_face(self, display_mode):
        _update_runtime_config("ai_presence_enabled", True)
        _update_runtime_config("ai_presence_neural_face_enabled", True)
        _update_runtime_config("ai_presence_visual_style", self._active_face_style())
        _update_runtime_config("ai_presence_display_mode", display_mode)
        if display_mode == "fullscreen":
            _update_runtime_config("ai_presence_fullscreen", True)
        self.refresh_from_runtime()
        self._apply_runtime_config()
        self._save_session()

    def _show_neural_face_fullscreen(self):
        self._activate_neural_face("fullscreen")
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_ai_state("speaking")
            visual_presence_runtime.set_audio_level(0.58)
            QtCore.QTimer.singleShot(7000, self._finish_preview)
            self._set_status("Neural Face fullscreen preview running.")
        except Exception as exc:
            self._set_status(f"Neural Face fullscreen failed: {exc}")

    def _show_neural_face_floating(self):
        self._activate_neural_face("floating")
        try:
            from visual_presence import runtime as visual_presence_runtime

            visual_presence_runtime.set_ai_state("idle")
            visual_presence_runtime.set_audio_level(0.0)
            self._set_status("Neural Face floating window opened.")
        except Exception as exc:
            self._set_status(f"Neural Face floating window failed: {exc}")
