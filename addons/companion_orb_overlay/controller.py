from __future__ import annotations

import json

from PySide6 import QtWidgets

from ui.widgets.basic import NoWheelTabWidget

from addons.ai_presence_mode.controller import (
    AIPresenceModeController,
    COMPANION_ORB_SESSION_KEYS,
    ORB_DISPLAY_MODES,
    ORB_POSITIONS,
    ORB_RESPONSE_STYLES,
    ORB_TARGET_MODES,
    ORB_VISUAL_STYLES,
    _ResponsiveGridWidget,
)
from addons.companion_orb_overlay.companion_orb.sensory_source import (
    COMPANION_ORB_TARGET_METADATA,
    COMPANION_ORB_TARGET_PINGPONG_PROMPT,
)


class CompanionOrbOverlaySettingsController(AIPresenceModeController):
    SESSION_KEYS = COMPANION_ORB_SESSION_KEYS
    APPLY_STATUS_MESSAGE = "Companion Orb Overlay settings applied."

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
        selector_grid.addWidget(self._combo("companion_orb_visual_style_combo", ORB_VISUAL_STYLES, "companion_orb_visual_style", "soft_plasma"), 1, 1)
        selector_grid.addWidget(self._compact_label("Position"), 1, 2)
        selector_grid.addWidget(self._combo("companion_orb_position_combo", ORB_POSITIONS, "companion_orb_position", "bottom-right"), 1, 3)
        selector_grid.addWidget(self._compact_label("Reply style"), 2, 0)
        selector_grid.addWidget(
            self._combo("companion_orb_response_style_combo", ORB_RESPONSE_STYLES, "companion_orb_response_style", "friendly"),
            2,
            1,
            1,
            3,
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
            ),
        )

        behavior_group, behavior_layout = self._section_group("Movement", "companion_orb_behavior_toggles_group")
        self._add_checkbox_stack(
            behavior_layout,
            (
                self._checkbox("Movement enabled", "companion_orb_movement_enabled_checkbox", "companion_orb_movement_enabled", True),
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
        layout.addWidget(self._build_companion_orb_sensory_tabs())

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

    def _build_companion_orb_sensory_tabs(self):
        group, layout = self._section_group("Hidden Sensory & Response", "companion_orb_sensory_tabs_group")
        tabs = NoWheelTabWidget()
        tabs.setObjectName("companion_orb_sensory_tabs")
        tabs.addTab(self._build_companion_orb_source_tab(), "Source")
        tabs.addTab(self._build_companion_orb_capture_tab(), "Capture")
        tabs.addTab(self._build_companion_orb_supervisor_tab(), "Supervisor")
        tabs.setTabToolTip(0, "Source guidance and declared PING/PONG payload for Companion Orb Target.")
        tabs.setTabToolTip(1, "Capture and target settings that decide what the orb sees.")
        tabs.setTabToolTip(2, "Response settings that decide when the orb comments, moves, or takes a snapshot.")
        layout.addWidget(tabs)
        return group

    def _build_companion_orb_source_tab(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        source_label = QtWidgets.QLabel("Source guidance for Companion Orb Target")
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
            ("PING payload", "companion_orb_source_ping_payload_preview", self._metadata_items_text(metadata.get("ping_payload"))),
            ("PONG influence", "companion_orb_source_pong_influence_preview", self._metadata_items_text(metadata.get("pong_influences"))),
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
            "Companion Orb Target can send either the selected orb target or an opt-in desktop-wide context map with OCR regions. The returned focus bounds are what let the orb move to the thing it is talking about."
        )
        capture_intro.setWordWrap(True)
        capture_intro.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(capture_intro)

        capture_grid = _ResponsiveGridWidget(min_column_width=260, max_columns=3, horizontal_spacing=10, vertical_spacing=8)
        capture_grid.setObjectName("companion_orb_capture_settings_grid")

        source_group, source_layout = self._section_group("Source Include", "companion_orb_capture_source_group")
        source_layout.addWidget(
            self._checkbox(
                "Use orb as sensory focus target",
                "companion_orb_sensory_target_enabled_checkbox",
                "companion_orb_sensory_target_enabled",
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
        source_hint = QtWidgets.QLabel("Enable this source in HOST > Vision hidden sensory feedback, then use the map option when the orb should explore the whole desktop.")
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

    def _build_companion_orb_supervisor_tab(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(8)

        response_intro = QtWidgets.QLabel(
            "Supervisor-style settings decide how hidden Companion Orb Target feedback becomes visible behavior: comments, playful pointer seeking, screenshots, and movement toward PONG focus bounds."
        )
        response_intro.setWordWrap(True)
        response_intro.setStyleSheet("color: #8ea3b8; font-size: 11px;")
        layout.addWidget(response_intro)

        response_grid = _ResponsiveGridWidget(min_column_width=260, max_columns=3, horizontal_spacing=10, vertical_spacing=8)
        response_grid.setObjectName("companion_orb_supervisor_settings_grid")

        reply_group, reply_layout = self._section_group("Reply Triggers", "companion_orb_supervisor_reply_group")
        self._add_checkbox_stack(
            reply_layout,
            (
                self._checkbox("Harassment", "companion_orb_harassment_enabled_checkbox", "companion_orb_harassment_enabled", False),
                self._checkbox("Snapshot at pointer", "companion_orb_snapshot_on_pointer_reached_checkbox", "companion_orb_snapshot_on_pointer_reached", False),
                self._checkbox("Right-click drag changes focus", "companion_orb_right_drag_focus_enabled_checkbox", "companion_orb_right_drag_focus_enabled", False),
            ),
        )

        debug_group, debug_layout = self._section_group("Debug", "companion_orb_supervisor_debug_group")
        debug_layout.addWidget(
            self._checkbox("Movement and snapshot debug log", "companion_orb_debug_enabled_checkbox", "companion_orb_debug_enabled", False)
        )
        debug_layout.addWidget(
            self._read_only_text(
                "When enabled, snapshot captures, OCR focus matches, movement targets, and hidden PING attempts are written to:\n"
                "runtime/companion_orb/debug/companion_orb_debug.log",
                "companion_orb_debug_log_path_preview",
                height=76,
            )
        )

        flow_group, flow_layout = self._section_group("Response Flow", "companion_orb_supervisor_flow_group")
        flow_layout.addWidget(
            self._read_only_text(
                "1. Hidden PING captures the selected target or full-screen context map.\n"
                "2. The hidden model returns attention, summary, optional proactive_candidate, and optional focus_bounds/focus_text.\n"
                "3. The Companion Orb moves toward focus_bounds when present, or tries to match focus_text against OCR regions.\n"
                "4. Spoken proactive replies only happen when HOST hidden proactive replies are enabled and the source says should_speak=true.",
                "companion_orb_supervisor_flow_preview",
                height=122,
            )
        )

        focus_group, focus_layout = self._section_group("Focus Output", "companion_orb_supervisor_focus_group")
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
