"""Native QML settings surface for AI Presence Mode."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

from addons.ai_presence_mode.native_controller import (
    VOICE_THREAD_AMBIENT_TARGETS,
    VOICE_THREAD_BUILTIN_PRESETS,
    VOICE_THREAD_MOTION_STYLES,
    VOICE_THREAD_PHYSICS_FEELS,
)
from visual_presence.visual_presence_bridge import resolve_presence_opacities
from ui.qml_bridge.adapters.card_layout import apply_card_layout
from ui.qml_bridge.adapters.config import RuntimeConfigNativeAdapter
from ui.qml_bridge.native_contracts import (
    NativeControl,
    NativeControlKind,
    NativeSurface,
    choices,
)
from ui.qml_bridge.native_registry import NativeSurfaceAdapter


_SCALED_CONTROLS = {
    "ai_presence_fullscreen_opacity": (0, 100, 72, "Fullscreen opacity"),
    "ai_presence_floating_window_opacity": (0, 100, 66, "Floating window opacity"),
    "ai_presence_overlay_opacity": (10, 100, 72, "Overlay opacity"),
    "ai_presence_thinking_pulse": (10, 100, 55, "Thinking pulse"),
    "ai_presence_speaking_reactivity": (10, 150, 85, "Voice reactivity"),
    "ai_presence_floating_opacity": (35, 100, 92, "Floating window opacity"),
    "ai_presence_mood_color_intensity": (0, 100, 85, "Mood color strength"),
    "ai_presence_glow_strength": (0, 175, 100, "Glow strength"),
    "ai_presence_animation_speed": (35, 175, 100, "Animation speed"),
    "ai_presence_idle_motion_strength": (0, 100, 16, "Idle motion"),
    "ai_presence_background_darkness": (0, 100, 100, "Background dimming"),
    "ai_presence_music_reactivity": (0, 400, 280, "Output sensitivity"),
    "ai_presence_primary_color_strength": (0, 150, 100, "Primary color strength"),
    "ai_presence_secondary_color_strength": (0, 150, 100, "Secondary color strength"),
    "ai_presence_halo_thickness": (35, 200, 100, "Halo thickness"),
    "ai_presence_waveform_strength": (20, 200, 100, "Waveform strength"),
    "ai_presence_ring_expansion_speed": (25, 200, 100, "Ring expansion speed"),
    "ai_presence_blur_softness": (0, 100, 35, "Blur / softness"),
    "ai_presence_line_brightness": (20, 200, 100, "Line brightness"),
    "ai_presence_voice_thread_peak_emphasis": (0, 400, 60, "Peak emphasis"),
    "ai_presence_voice_thread_glow_radius": (25, 400, 100, "Glow radius"),
    "ai_presence_voice_thread_reflection_distance": (
        0,
        400,
        25,
        "Reflection distance",
    ),
    "ai_presence_voice_thread_audio_reactivity": (0, 400, 100, "Audio reactivity"),
    "ai_presence_voice_thread_motion_scale": (0, 400, 100, "Motion size"),
    "ai_presence_voice_thread_idle_motion": (0, 300, 16, "Idle movement"),
    "ai_presence_voice_thread_animation_speed": (25, 300, 100, "Animation speed"),
    "ai_presence_voice_thread_response_smoothing": (0, 200, 58, "Response smoothness"),
    "ai_presence_voice_thread_spectrum_smoothing": (0, 200, 45, "Shape smoothness"),
    "ai_presence_voice_thread_spectrum_scale": (0, 400, 100, "Spectrum deformation"),
    "ai_presence_voice_thread_glow_intensity": (0, 400, 100, "Glow intensity"),
    "ai_presence_voice_thread_flux_strength": (0, 400, 100, "Voice impulse strength"),
    "ai_presence_voice_thread_fiber_spread": (25, 400, 100, "Fiber spread"),
    "ai_presence_voice_thread_bendiness": (0, 400, 100, "Bendiness"),
    "ai_presence_voice_thread_organic_variation": (0, 400, 100, "Organic variation"),
    "ai_presence_voice_thread_phrase_motion": (0, 400, 100, "Phrase movement"),
    "ai_presence_voice_thread_gesture_intensity": (0, 400, 100, "Gesture intensity"),
    "ai_presence_voice_thread_motion_memory": (0, 200, 65, "Motion memory"),
    "ai_presence_voice_thread_accent_sensitivity": (0, 400, 55, "Accent sensitivity"),
    "ai_presence_voice_thread_ambient_smoothing": (0, 200, 72, "Spectrum smoothing"),
    "ai_presence_voice_thread_ambient_noise_gate": (
        0,
        25,
        4,
        "Noise gate",
    ),
    "ai_presence_voice_thread_ambient_quiet_detail": (0, 250, 140, "Quiet detail"),
    "ai_presence_voice_thread_ambient_transient_punch": (0, 300, 160, "Transient punch"),
    "ai_presence_voice_thread_ambient_mix": (0, 200, 145, "Desktop audio mix"),
    "ai_presence_voice_thread_ambient_shape_strength": (0, 300, 180, "Shape / bend"),
    "ai_presence_voice_thread_ambient_travel_strength": (0, 300, 135, "Wave travel"),
    "ai_presence_voice_thread_ambient_glow_strength": (0, 300, 165, "Glow response"),
    "ai_presence_voice_thread_ambient_fiber_strength": (0, 300, 125, "Fiber spread response"),
    "ai_presence_voice_thread_ambient_color_strength": (0, 300, 150, "Color energy"),
    "ai_presence_voice_thread_color_vividness": (0, 400, 100, "Color vividness"),
    "ai_presence_voice_thread_color_bass_influence": (0, 400, 100, "Bass color influence"),
    "ai_presence_voice_thread_color_mid_influence": (0, 400, 100, "Mid color influence"),
    "ai_presence_voice_thread_color_high_influence": (0, 400, 100, "High color influence"),
    "ai_presence_voice_thread_color_smoothing": (0, 200, 65, "Color transition smoothness"),
    "ai_presence_voice_thread_ambient_motion_ceiling": (25, 300, 220, "Movement ceiling"),
    "ai_presence_voice_thread_ambient_bass_bend": (0, 400, 55, "Bass bend"),
    "ai_presence_voice_thread_ambient_mid_ripple": (0, 400, 38, "Mid ripple"),
    "ai_presence_voice_thread_ambient_high_shimmer": (0, 400, 42, "High shimmer"),
    "ai_presence_voice_thread_physics_slack": (0, 400, 100, "Physics slack"),
    "ai_presence_voice_thread_interaction_area": (120, 500, 160, "Interaction area"),
    "ai_presence_voice_thread_gravity": (20, 400, 120, "End gravity"),
    "ai_presence_voice_thread_retension_time": (20, 200, 65, "Soft retension"),
    "ai_presence_voice_thread_size": (25, 600, 100, "Overall thread size"),
    "ai_presence_voice_thread_horizontal_span": (100, 400, 100, "Horizontal span"),
}

_INTEGER_CONTROLS = {
    "ai_presence_audio_refresh_hz": (5, 120, 30, "Audio analysis rate"),
    "ai_presence_node_density": (8, 96, 32, "Node count"),
    "ai_presence_particle_density": (0, 120, 28, "Particle count"),
    "ai_presence_voice_thread_strand_multiplier": (
        1,
        5,
        1,
        "Strand count multiplier",
    ),
    "ai_presence_voice_thread_frame_rate": (15, 120, 30, "Thread FPS"),
    "ai_presence_voice_thread_ambient_attack_ms": (5, 250, 35, "Attack (ms)"),
    "ai_presence_voice_thread_ambient_release_ms": (40, 700, 260, "Release (ms)"),
}


_CONTROL_DESCRIPTIONS = {
    "ai_presence_click_through_default": "Pass clicks through the floating visualizer. On Windows, right-drag can still move it when enabled. Live controls and mouse physics temporarily accept input.",
    "ai_presence_right_drag_move_enabled": "Use the right mouse button to move the floating window. On Windows this also works with click-through enabled, while left clicks reach the application underneath.",
    "ai_presence_fullscreen_opacity": "Opacity of the fullscreen visualization only. Independent of floating window opacity. 0 hides it; 1 is fully opaque.",
    "ai_presence_floating_window_opacity": "Opacity of the floating visualization only. Independent of fullscreen opacity. 0 hides it; 1 is fully opaque.",
    "ai_presence_remember_floating_geometry": "Reuse the floating window's saved size and position when it opens, instead of the default placement.",
    "ai_presence_fullscreen": (
        "On covers the whole screen; off covers only NC's window. Works only "
        "in the same process. Turn off Advanced > Run visualizer in a separate "
        "process to use this setting."
    ),
    "ai_presence_reduced_effects": (
        "Reduces GPU and animation work. Silk Threads is capped at 24 FPS while "
        "this is enabled, regardless of the Thread FPS setting."
    ),
    "ai_presence_voice_thread_frame_rate": (
        "Target rate for Silk Threads motion updates. Reduced effects caps it at "
        "24 FPS, and visible output cannot exceed the active display refresh rate."
    ),
    "ai_presence_audio_refresh_hz": (
        "How often voice and desktop-audio level and spectrum data update the "
        "animation (5-120 times per second). This is separate from the audio "
        "device sample rate; higher values use more CPU."
    ),
}


_VOICE_THREAD_CARD_SPECS: tuple[
    tuple[str, str, str, int, tuple[str, ...]], ...
] = (
    (
        "thread_presets",
        "Presets",
        "Load, save, or remove complete Living Voice Thread tuning setups.",
        10,
        (
            "ai_presence_voice_thread_selected_preset",
            "ai_presence_voice_thread_load_preset",
            "ai_presence_voice_thread_save_preset",
            "ai_presence_voice_thread_delete_preset",
        ),
    ),
    (
        "thread_style",
        "Thread style",
        "Choose the strand structure, overall scale, spread, and flexibility.",
        20,
        (
            "ai_presence_voice_thread_variation",
            "ai_presence_voice_thread_strand_multiplier",
            "ai_presence_voice_thread_size",
            "ai_presence_voice_thread_horizontal_span",
            "ai_presence_voice_thread_fiber_spread",
            "ai_presence_voice_thread_ambient_fiber_spread_enabled",
            "ai_presence_voice_thread_ambient_fiber_strength",
            "ai_presence_voice_thread_bendiness",
        ),
    ),
    (
        "thread_color_glow",
        "Color and glow",
        "Set the palette, custom colors, light radius, and light intensity.",
        30,
        (
            "ai_presence_voice_thread_palette",
            "ai_presence_voice_thread_primary_color",
            "ai_presence_voice_thread_accent_color",
            "ai_presence_voice_thread_highlight_color",
            "ai_presence_voice_thread_glow_radius",
            "ai_presence_voice_thread_glow_intensity",
        ),
    ),
    (
        "thread_audio_colors",
        "Audio-reactive colors",
        "Blend several palette colors across the strands from voice and desktop frequency energy.",
        32,
        (
            "ai_presence_voice_thread_audio_colors_enabled",
            "ai_presence_voice_thread_voice_colors_enabled",
            "ai_presence_voice_thread_desktop_colors_enabled",
            "ai_presence_voice_thread_color_vividness",
            "ai_presence_voice_thread_color_bass_influence",
            "ai_presence_voice_thread_color_mid_influence",
            "ai_presence_voice_thread_color_high_influence",
            "ai_presence_voice_thread_color_smoothing",
        ),
    ),
    (
        "thread_reflection",
        "Reflection",
        "Show or hide the mirrored thread and set its gap below the main strand.",
        35,
        (
            "ai_presence_voice_thread_reflection_enabled",
            "ai_presence_voice_thread_reflection_distance",
        ),
    ),
    (
        "thread_voice_response",
        "Voice response",
        "Tune how strongly and how quickly the thread follows spoken audio.",
        40,
        (
            "ai_presence_voice_thread_audio_reactivity",
            "ai_presence_voice_thread_response_smoothing",
            "ai_presence_voice_thread_peak_emphasis",
            "ai_presence_voice_thread_flux_strength",
            "ai_presence_voice_thread_accent_sensitivity",
        ),
    ),
    (
        "thread_motion",
        "Motion character",
        "Shape the large movement, idle life, speed, and organic variation.",
        50,
        (
            "ai_presence_voice_thread_motion_style",
            "ai_presence_voice_thread_motion_scale",
            "ai_presence_voice_thread_animation_speed",
            "ai_presence_voice_thread_organic_variation",
        ),
    ),
    (
        "thread_speech_dynamics",
        "Speech shape and gestures",
        "Control spectral deformation, phrase movement, gestures, and memory.",
        60,
        (
            "ai_presence_voice_thread_spectrum_smoothing",
            "ai_presence_voice_thread_spectrum_scale",
            "ai_presence_voice_thread_phrase_motion",
            "ai_presence_voice_thread_gesture_intensity",
            "ai_presence_voice_thread_motion_memory",
        ),
    ),
    (
        "thread_desktop_audio",
        "Desktop audio sync",
        "Choose how default output audio enters and influences the animation.",
        70,
        (
            "ai_presence_music_reactivity_enabled",
            "ai_presence_voice_thread_ambient_reaction_target",
            "ai_presence_music_reactivity",
            "ai_presence_voice_thread_ambient_quiet_detail",
            "ai_presence_voice_thread_ambient_transient_punch",
            "ai_presence_voice_thread_ambient_noise_gate",
        ),
    ),
    (
        "thread_desktop_timing",
        "Desktop timing and idle blend",
        "Tune response timing and how live output mixes with the thread's idle life.",
        75,
        (
            "ai_presence_voice_thread_ambient_attack_ms",
            "ai_presence_voice_thread_ambient_release_ms",
            "ai_presence_voice_thread_idle_motion",
            "ai_presence_voice_thread_ambient_mix",
            "ai_presence_voice_thread_ambient_motion_ceiling",
        ),
    ),
    (
        "thread_desktop_routing",
        "Desktop animation routing",
        "Send desktop bands into the existing shape, travel, glow, fiber, and color controls.",
        77,
        (
            "ai_presence_voice_thread_ambient_link_main_controls",
            "ai_presence_voice_thread_ambient_shape_strength",
            "ai_presence_voice_thread_ambient_travel_strength",
            "ai_presence_voice_thread_ambient_glow_strength",
            "ai_presence_voice_thread_ambient_color_strength",
        ),
    ),
    (
        "thread_output_bands",
        "Output frequency response",
        "Balance the low, middle, and high-frequency desktop-audio reactions.",
        80,
        (
            "ai_presence_voice_thread_ambient_smoothing",
            "ai_presence_voice_thread_ambient_bass_bend",
            "ai_presence_voice_thread_ambient_mid_ripple",
            "ai_presence_voice_thread_ambient_high_shimmer",
        ),
    ),
    (
        "thread_physics",
        "Mouse physics",
        "Tune how the held thread hangs, sways, and returns after release.",
        90,
        (
            "ai_presence_voice_thread_mouse_physics_enabled",
            "ai_presence_voice_thread_physics_feel",
            "ai_presence_voice_thread_physics_slack",
            "ai_presence_voice_thread_gravity",
            "ai_presence_voice_thread_retension_time",
        ),
    ),
    (
        "thread_placement",
        "Placement and performance",
        "Set the editable area, placement guide, frame rate, or recenter the thread.",
        100,
        (
            "ai_presence_voice_thread_show_placement_guide",
            "ai_presence_voice_thread_interaction_area",
            "ai_presence_audio_refresh_hz",
            "ai_presence_voice_thread_frame_rate",
            "ai_presence_voice_thread_reset_placement",
        ),
    ),
)


def _apply_ai_presence_card_layout(
    controls: tuple[NativeControl, ...] | list[NativeControl],
) -> tuple[NativeControl, ...]:
    """Apply presentation-only cards without changing runtime control contracts."""

    placements: dict[str, tuple[str, str, str, int]] = {}
    for key, title, description, order, control_ids in _VOICE_THREAD_CARD_SPECS:
        for control_id in control_ids:
            placements[control_id] = (key, title, description, order)

    prepared: list[NativeControl] = []
    for control in controls:
        placement = placements.get(control.id)
        if placement is None:
            prepared.append(control)
            continue
        key, title, description, order = placement
        metadata = dict(control.metadata)
        metadata.update(
            groupKey=key,
            groupTitle=title,
            groupDescription=description,
            groupOrder=order,
            groupColumnSpan=1,
        )
        prepared.append(replace(control, metadata=metadata))
    return apply_card_layout(tuple(prepared))


def _voice_thread_preset_choices(settings: Mapping[str, object]):
    options = [
        (preset_id, str(preset.get("label") or preset_id))
        for preset_id, preset in VOICE_THREAD_BUILTIN_PRESETS.items()
    ]
    custom = settings.get("ai_presence_voice_thread_custom_presets")
    if isinstance(custom, Mapping):
        options.extend(
            (
                f"custom:{preset_id}",
                f"Custom: {str(dict(preset).get('label') or preset_id)}",
            )
            for preset_id, preset in sorted(
                custom.items(),
                key=lambda item: str(dict(item[1]).get("label") or item[0]).casefold()
                if isinstance(item[1], Mapping)
                else str(item[0]).casefold(),
            )
            if isinstance(preset, Mapping)
        )
    return choices(tuple(options))


class AIPresenceNativeAdapter(NativeSurfaceAdapter):
    def __init__(
        self,
        application_facade: Any,
        surface: NativeSurface,
        *,
        persist: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(surface.id, surface.addon_id, parent)
        self._application = application_facade
        self._surface = surface
        self._controls = {control.id: control for control in surface.controls}
        self._persist = persist
        self._revision = 0

    def _invoke(self, capability: str, payload=None) -> object:
        result = self._application.addons.invoke_addon_capability(
            self.addon_id,
            capability,
            dict(payload or {}),
        )
        if not result.accepted:
            failure = getattr(result, "failure", None)
            raise RuntimeError(
                str(getattr(failure, "message", "AI Presence is unavailable."))
            )
        return result.value

    def _snapshot_payload(self) -> dict[str, object]:
        value = self._invoke("runtime.ai_presence.snapshot")
        if not isinstance(value, Mapping):
            raise RuntimeError("AI Presence snapshot is not a mapping.")
        return dict(value)

    def snapshot(self) -> NativeSurface:
        payload = self._snapshot_payload()
        settings = dict(payload.get("settings") or {})
        values = {
            "ai_presence_summary": (
                "Fullscreen and floating neural visualizer for thinking, voice, "
                "computer audio, and mood state."
            ),
            "ai_presence_status": str(payload.get("status") or "Ready."),
        }
        fullscreen_opacity, floating_opacity = resolve_presence_opacities(settings)
        opacity_values = {"ai_presence_fullscreen_opacity": fullscreen_opacity,
                          "ai_presence_floating_window_opacity": floating_opacity}
        for key in _SCALED_CONTROLS:
            value = opacity_values[key] if key in opacity_values else float(settings.get(key, 0.0))
            values[key] = round(value * 100)
        selected_preset = str(
            settings.get("ai_presence_voice_thread_selected_preset") or "default"
        )
        preset_options = _voice_thread_preset_choices(settings)
        controls = []
        for control in self._surface.controls:
            updates: dict[str, object] = {
                "value": values.get(
                    control.id,
                    settings.get(control.id, control.default_value),
                )
            }
            if control.id == "ai_presence_voice_thread_selected_preset":
                updates["choices"] = preset_options
                updates["value"] = selected_preset
            elif control.id == "ai_presence_voice_thread_delete_preset":
                updates["enabled"] = selected_preset.startswith("custom:")
            elif control.id == "ai_presence_fullscreen":
                mode = str(settings.get("ai_presence_display_mode", "fullscreen"))
                separate_process = bool(settings.get("ai_presence_external_runtime_enabled", False))
                applies = mode in {"fullscreen", "both"} and not separate_process
                help_text = _CONTROL_DESCRIPTIONS[control.id]
                if separate_process:
                    help_text += " The fullscreen overlay in separate-process mode always covers the whole screen."
                elif not applies:
                    help_text += " Choose Fullscreen or Both in Screen mode to use this setting."
                updates["enabled"] = applies
                updates["metadata"] = {**control.metadata, "description": help_text}
            controls.append(replace(control, **updates))
        self._controls = {control.id: control for control in controls}
        return replace(
            self._surface,
            controls=_apply_ai_presence_card_layout(controls),
            revision=self._revision,
        )

    def _persist_state(self) -> None:
        if callable(self._persist):
            self._persist()

    def set_value(self, control_id: str, value: Any) -> None:
        key, runtime_value = self._runtime_value(control_id, value)
        self._invoke(
            "runtime.ai_presence.update",
            {"key": key, "value": runtime_value, "preview": False},
        )
        self._revision += 1
        self._persist_state()
        self.changed.emit()

    def preview_value(self, control_id: str, value: Any) -> None:
        key, runtime_value = self._runtime_value(control_id, value)
        self._invoke(
            "runtime.ai_presence.update",
            {"key": key, "value": runtime_value, "preview": True},
        )

    def _runtime_value(self, control_id: str, value: Any) -> tuple[str, object]:
        key = str(control_id or "").strip()
        control = self._controls.get(key)
        if control is None or control.kind in {
            NativeControlKind.ACTION,
            NativeControlKind.DISPLAY,
        }:
            raise KeyError(f"Unknown AI Presence setting '{control_id}'.")
        normalized = RuntimeConfigNativeAdapter._normalize(control, value)
        runtime_value: object = normalized
        if key in _SCALED_CONTROLS:
            runtime_value = float(normalized) / 100.0
        return key, runtime_value

    def trigger(self, control_id: str) -> None:
        self.trigger_with_payload(control_id, None)

    def trigger_with_payload(self, control_id: str, payload: Any) -> None:
        actions = {
            "ai_presence_preview_fullscreen": "preview_fullscreen",
            "ai_presence_open_floating": "open_floating",
            "ai_presence_show": "show_presence",
            "ai_presence_activate_silk_threads": "activate_silk_threads",
            "ai_presence_reset_floating": "reset_floating_position",
            "ai_presence_voice_thread_load_preset": "load_voice_thread_preset",
            "ai_presence_voice_thread_save_preset": "save_voice_thread_preset",
            "ai_presence_voice_thread_delete_preset": "delete_voice_thread_preset",
            "ai_presence_voice_thread_reset_placement": "reset_voice_thread_placement",
        }
        action = actions.get(str(control_id or "").strip())
        if action is None:
            raise KeyError(f"Unknown AI Presence action '{control_id}'.")
        self._invoke(
            "runtime.ai_presence.action",
            {"action": action, "payload": payload},
        )
        self._revision += 1
        if action != "preview_fullscreen":
            self._persist_state()
        self.changed.emit()


def _boolean(key: str, label: str, section: str, default: bool) -> NativeControl:
    return NativeControl(
        key,
        label,
        NativeControlKind.BOOLEAN,
        section,
        default_value=default,
    )


def _slider(key: str, section: str) -> NativeControl:
    minimum, maximum, default, label = _SCALED_CONTROLS[key]
    metadata = {
        "displayScale": 100,
        "deferredCommit": True,
        "livePreview": True,
        "livePreviewInterval": 50,
    }
    if key.startswith("ai_presence_voice_thread_"):
        metadata["preciseEditor"] = True
    if key == "ai_presence_voice_thread_ambient_noise_gate":
        metadata["description"] = (
            "Suppress only audio below this actual level. Lower values preserve "
            "more quiet desktop detail; higher values reject background noise."
        )
    elif key == "ai_presence_music_reactivity":
        metadata["description"] = (
            "Amplify the analyzed default-output signal before it drives the thread."
        )
    elif key == "ai_presence_voice_thread_ambient_quiet_detail":
        metadata["description"] = (
            "Lift low-level music detail without forcing loud passages to clip."
        )
    elif key == "ai_presence_voice_thread_ambient_transient_punch":
        metadata["description"] = (
            "Increase the visible impulse from beats and fast level changes."
        )
    elif key == "ai_presence_voice_thread_horizontal_span":
        metadata["description"] = (
            "Widen the transparent floating Presence window. 1.00 keeps the "
            "compact frame; 4.00 uses the monitor's full available width."
        )
    return NativeControl(
        key,
        label,
        NativeControlKind.SLIDER,
        section,
        minimum=minimum,
        maximum=maximum,
        step=1,
        default_value=default,
        metadata=metadata,
    )


def _integer_slider(
    key: str,
    section: str = "Advanced motion and audio",
) -> NativeControl:
    minimum, maximum, default, label = _INTEGER_CONTROLS[key]
    return NativeControl(
        key,
        label,
        NativeControlKind.SLIDER,
        section,
        minimum=minimum,
        maximum=maximum,
        step=1,
        default_value=default,
        metadata={"deferredCommit": True},
    )


def build_ai_presence_adapter(
    application_facade: Any,
    *,
    persist: Callable[[], object] | None = None,
) -> AIPresenceNativeAdapter:
    controls = [
        NativeControl(
            "ai_presence_summary",
            "AI Presence",
            NativeControlKind.DISPLAY,
            "Overview",
        ),
        NativeControl(
            "ai_presence_status",
            "Status",
            NativeControlKind.DISPLAY,
            "Overview",
        ),
        NativeControl(
            "ai_presence_show",
            "Start and show Presence",
            NativeControlKind.ACTION,
            "Overview",
            metadata={"execution": "ui"},
        ),
        NativeControl(
            "ai_presence_activate_silk_threads",
            "Activate Silk Threads",
            NativeControlKind.ACTION,
            "Overview",
            metadata={"execution": "ui"},
        ),
        NativeControl(
            "ai_presence_preview_fullscreen",
            "Preview Fullscreen",
            NativeControlKind.ACTION,
            "Presence preset",
            metadata={"execution": "ui"},
        ),
        NativeControl(
            "ai_presence_open_floating",
            "Open Floating Window",
            NativeControlKind.ACTION,
            "Presence preset",
            metadata={"execution": "ui"},
        ),
        NativeControl(
            "ai_presence_reset_floating",
            "Center Floating Window",
            NativeControlKind.ACTION,
            "Presence preset",
            metadata={"execution": "ui"},
        ),
        NativeControl(
            "ai_presence_display_mode",
            "Screen mode",
            NativeControlKind.CHOICE,
            "Presence preset",
            default_value="fullscreen",
            choices=choices(
                (("off", "Off"), ("fullscreen", "Fullscreen"),
                 ("floating", "Floating Window"), ("both", "Both"))
            ),
        ),
        NativeControl(
            "ai_presence_visual_style",
            "Presence style",
            NativeControlKind.CHOICE,
            "Presence preset",
            default_value="neural_network_pulse",
            choices=choices(
                (
                    ("neural_network_pulse", "Neural Network Pulse"),
                    ("living_voice_thread", "Living Voice Thread"),
                    ("silk_drift", "Silk Drift"),
                )
            ),
        ),
        NativeControl(
            "ai_presence_render_backend",
            "Rendering engine",
            NativeControlKind.CHOICE,
            "Presence preset",
            default_value="gpu_native",
            choices=choices(
                (
                    ("gpu_native", "GPU Native (recommended)"),
                    ("legacy_canvas", "Legacy Canvas (compatibility)"),
                )
            ),
        ),
        _boolean("ai_presence_enabled", "Use AI Presence", "Start behavior", False),
        _boolean("ai_presence_fullscreen", "Cover entire screen", "Start behavior", True),
        _boolean("ai_presence_external_runtime_enabled", "Run visualizer in a separate process", "Start behavior", False),
        _boolean("ai_presence_reduced_effects", "Reduced effects", "Start behavior", False),
        _boolean("ai_presence_space_closes_fullscreen", "Space exits fullscreen", "Start behavior", True),
        _boolean("ai_presence_floating_always_on_top", "Always on top", "Floating window", True),
        _boolean("ai_presence_remember_floating_geometry", "Remember window size and position", "Floating window", True),
        _boolean("ai_presence_click_through_default", "Click-through by default", "Floating window", False),
        _boolean("ai_presence_right_drag_move_enabled", "Right-click drag moves window", "Floating window", False),
        _boolean("ai_presence_transparent_background", "Transparent background", "Floating window", False),
        _boolean("ai_presence_shaders_enabled", "Glow effect", "Advanced visual effects", True),
        _boolean("ai_presence_particles_enabled", "Particle field", "Advanced visual effects", True),
        _boolean(
            "ai_presence_music_reactivity_enabled",
            "Sync default output audio",
            "Living Voice Thread",
            False,
        ),
        _boolean(
            "ai_presence_voice_thread_mouse_physics_enabled",
            "Mouse physics (left-drag thread)",
            "Living Voice Thread",
            False,
        ),
        _boolean(
            "ai_presence_voice_thread_show_placement_guide",
            "Show enlarged placement guide while editing",
            "Living Voice Thread",
            True,
        ),
        _boolean(
            "ai_presence_voice_thread_reflection_enabled",
            "Show reflection",
            "Living Voice Thread",
            True,
        ),
        _boolean(
            "ai_presence_voice_thread_ambient_link_main_controls",
            "Link desktop audio to main thread controls",
            "Living Voice Thread",
            True,
        ),
        _boolean(
            "ai_presence_voice_thread_audio_colors_enabled",
            "Audio-reactive strand colors",
            "Living Voice Thread",
            True,
        ),
        _boolean(
            "ai_presence_voice_thread_voice_colors_enabled",
            "React to NC voice / TTS",
            "Living Voice Thread",
            True,
        ),
        _boolean(
            "ai_presence_voice_thread_desktop_colors_enabled",
            "React to desktop output",
            "Living Voice Thread",
            True,
        ),
        _boolean("ai_presence_mood_colors_enabled", "Use mood colors", "Mood colors", True),
        NativeControl(
            "ai_presence_mood_color_mode",
            "Mode",
            NativeControlKind.CHOICE,
            "Mood colors",
            default_value="automatic",
            choices=choices((("automatic", "Automatic"), ("manual", "Manual"), ("off", "Off"))),
        ),
        NativeControl(
            "ai_presence_manual_mood",
            "Manual mood",
            NativeControlKind.CHOICE,
            "Mood colors",
            default_value="neutral",
            choices=choices(
                tuple(
                    (value, label)
                    for label, value in (
                        ("Neutral", "neutral"), ("Happy", "happy"),
                        ("Sad", "sad"), ("Angry", "angry"),
                        ("Calm", "calm"), ("Curious", "curious"),
                        ("Excited", "excited"), ("Tension", "tension"),
                        ("Story / Fantasy", "story"), ("Focus", "focus"),
                        ("Dark", "dark"), ("Epic", "epic"),
                        ("Energetic", "energetic"),
                    )
                )
            ),
        ),
        _boolean("ai_presence_allow_story_mood_override", "Story mood override", "Mood colors", True),
        _boolean("ai_presence_allow_persona_mood_override", "Persona mood override", "Mood colors", True),
        NativeControl(
            "ai_presence_voice_thread_variation",
            "Thread variation",
            NativeControlKind.CHOICE,
            "Living Voice Thread",
            default_value="silk_ribbon",
            choices=choices(
                (
                    ("silk_ribbon", "Silk ribbon"),
                    ("double_helix", "Double helix"),
                    ("harmonic_threads", "Harmonic threads"),
                )
            ),
        ),
        NativeControl(
            "ai_presence_voice_thread_selected_preset",
            "Animation preset",
            NativeControlKind.CHOICE,
            "Living Voice Thread",
            default_value="default",
            choices=_voice_thread_preset_choices({}),
        ),
        NativeControl(
            "ai_presence_voice_thread_load_preset",
            "Load preset",
            NativeControlKind.ACTION,
            "Living Voice Thread",
            metadata={"execution": "ui", "actionStrip": True},
        ),
        NativeControl(
            "ai_presence_voice_thread_save_preset",
            "Save current",
            NativeControlKind.ACTION,
            "Living Voice Thread",
            metadata={
                "execution": "ui",
                "actionStrip": True,
                "inputPrompt": True,
                "dialogTitle": "Save Living Voice Thread preset",
                "inputLabel": "Preset name",
                "placeholderText": "My voice animation",
            },
        ),
        NativeControl(
            "ai_presence_voice_thread_delete_preset",
            "Delete custom",
            NativeControlKind.ACTION,
            "Living Voice Thread",
            enabled=False,
            metadata={
                "execution": "ui",
                "actionStrip": True,
                "destructive": True,
            },
        ),
        NativeControl(
            "ai_presence_voice_thread_reset_placement",
            "Center thread",
            NativeControlKind.ACTION,
            "Living Voice Thread",
            metadata={"execution": "ui", "actionStrip": True},
        ),
        NativeControl(
            "ai_presence_voice_thread_physics_feel",
            "Physics feel",
            NativeControlKind.CHOICE,
            "Living Voice Thread",
            default_value="natural",
            choices=choices(tuple(
                (value, label) for label, value in VOICE_THREAD_PHYSICS_FEELS
            )),
        ),
        NativeControl(
            "ai_presence_voice_thread_motion_style",
            "Large motion style",
            NativeControlKind.CHOICE,
            "Living Voice Thread",
            default_value="organic_drift",
            choices=choices(tuple(
                (value, label) for label, value in VOICE_THREAD_MOTION_STYLES
            )),
        ),
        NativeControl(
            "ai_presence_voice_thread_ambient_reaction_target",
            "Output reaction target",
            NativeControlKind.CHOICE,
            "Living Voice Thread",
            default_value="shape_glow",
            choices=choices(tuple(
                (value, label) for label, value in VOICE_THREAD_AMBIENT_TARGETS
            )),
        ),
        NativeControl(
            "ai_presence_voice_thread_palette",
            "Color palette",
            NativeControlKind.CHOICE,
            "Living Voice Thread",
            default_value="persona_mood",
            choices=choices(
                (
                    ("persona_mood", "Persona mood"),
                    ("aurora", "Aurora"),
                    ("electric_cyan", "Electric cyan"),
                    ("ember", "Ember"),
                    ("ghost", "Ghost"),
                    ("custom", "Custom"),
                )
            ),
        ),
        NativeControl(
            "ai_presence_voice_thread_primary_color",
            "Custom primary color",
            NativeControlKind.TEXT,
            "Living Voice Thread",
            default_value="#22d3ee",
            metadata={"renderer": "color", "colorWheel": True},
        ),
        NativeControl(
            "ai_presence_voice_thread_accent_color",
            "Custom accent color",
            NativeControlKind.TEXT,
            "Living Voice Thread",
            default_value="#a78bfa",
            metadata={"renderer": "color", "colorWheel": True},
        ),
        NativeControl(
            "ai_presence_voice_thread_highlight_color",
            "Custom highlight color",
            NativeControlKind.TEXT,
            "Living Voice Thread",
            default_value="#ecfeff",
            metadata={"renderer": "color", "colorWheel": True},
        ),
    ]
    controls.extend(
        _slider(key, "Presence look")
        for key in (
            "ai_presence_overlay_opacity",
            "ai_presence_fullscreen_opacity",
            "ai_presence_floating_window_opacity",
            "ai_presence_thinking_pulse",
            "ai_presence_speaking_reactivity",
            "ai_presence_floating_opacity",
            "ai_presence_mood_color_intensity",
            "ai_presence_glow_strength",
            "ai_presence_animation_speed",
            "ai_presence_idle_motion_strength",
            "ai_presence_background_darkness",
        )
    )
    controls.extend(
        _integer_slider(
            key,
            "Living Voice Thread"
            if key in {
                "ai_presence_voice_thread_frame_rate",
                "ai_presence_voice_thread_strand_multiplier",
                "ai_presence_voice_thread_ambient_attack_ms",
                "ai_presence_voice_thread_ambient_release_ms",
            }
            else "Advanced motion and audio",
        )
        for key in _INTEGER_CONTROLS
    )
    for key in (
            "ai_presence_voice_thread_audio_reactivity",
            "ai_presence_voice_thread_motion_scale",
            "ai_presence_voice_thread_idle_motion",
            "ai_presence_voice_thread_animation_speed",
            "ai_presence_voice_thread_response_smoothing",
            "ai_presence_voice_thread_spectrum_smoothing",
            "ai_presence_voice_thread_spectrum_scale",
            "ai_presence_voice_thread_peak_emphasis",
            "ai_presence_voice_thread_glow_radius",
            "ai_presence_voice_thread_reflection_distance",
            "ai_presence_voice_thread_glow_intensity",
            "ai_presence_voice_thread_flux_strength",
            "ai_presence_voice_thread_fiber_spread",
            "ai_presence_voice_thread_bendiness",
            "ai_presence_voice_thread_organic_variation",
            "ai_presence_voice_thread_phrase_motion",
            "ai_presence_voice_thread_gesture_intensity",
            "ai_presence_voice_thread_motion_memory",
            "ai_presence_voice_thread_accent_sensitivity",
            "ai_presence_music_reactivity",
            "ai_presence_voice_thread_ambient_smoothing",
            "ai_presence_voice_thread_ambient_noise_gate",
            "ai_presence_voice_thread_ambient_quiet_detail",
            "ai_presence_voice_thread_ambient_transient_punch",
            "ai_presence_voice_thread_ambient_mix",
            "ai_presence_voice_thread_ambient_shape_strength",
            "ai_presence_voice_thread_ambient_travel_strength",
            "ai_presence_voice_thread_ambient_glow_strength",
            "ai_presence_voice_thread_ambient_color_strength",
            "ai_presence_voice_thread_ambient_motion_ceiling",
            "ai_presence_voice_thread_ambient_bass_bend",
            "ai_presence_voice_thread_ambient_mid_ripple",
            "ai_presence_voice_thread_ambient_high_shimmer",
            "ai_presence_voice_thread_color_vividness",
            "ai_presence_voice_thread_color_bass_influence",
            "ai_presence_voice_thread_color_mid_influence",
            "ai_presence_voice_thread_color_high_influence",
            "ai_presence_voice_thread_color_smoothing",
            "ai_presence_voice_thread_physics_slack",
            "ai_presence_voice_thread_interaction_area",
            "ai_presence_voice_thread_gravity",
            "ai_presence_voice_thread_retension_time",
            "ai_presence_voice_thread_size",
            "ai_presence_voice_thread_horizontal_span",
        ):
        controls.append(_slider(key, "Living Voice Thread"))
        if key == "ai_presence_voice_thread_fiber_spread":
            controls.append(
                _boolean(
                    "ai_presence_voice_thread_ambient_fiber_spread_enabled",
                    "Desktop audio-reactive fiber spread",
                    "Living Voice Thread",
                    True,
                )
            )
            controls.append(
                _slider(
                    "ai_presence_voice_thread_ambient_fiber_strength",
                    "Living Voice Thread",
                )
            )
    controls.extend(
        _slider(key, "Advanced motion and audio")
        for key in (
            "ai_presence_primary_color_strength",
            "ai_presence_secondary_color_strength",
            "ai_presence_halo_thickness",
            "ai_presence_waveform_strength",
            "ai_presence_ring_expansion_speed",
            "ai_presence_blur_softness",
            "ai_presence_line_brightness",
        )
    )
    overview_ids = {
        "ai_presence_summary",
        "ai_presence_status",
        "ai_presence_enabled",
        "ai_presence_show",
        "ai_presence_activate_silk_threads",
        "ai_presence_preview_fullscreen",
        "ai_presence_open_floating",
    }
    display_ids = {
        "ai_presence_display_mode",
        "ai_presence_fullscreen_opacity",
        "ai_presence_floating_window_opacity",
        "ai_presence_reset_floating",
        "ai_presence_fullscreen",
        "ai_presence_space_closes_fullscreen",
        "ai_presence_floating_opacity",
        "ai_presence_floating_always_on_top",
        "ai_presence_remember_floating_geometry",
        "ai_presence_click_through_default",
        "ai_presence_right_drag_move_enabled",
        "ai_presence_transparent_background",
    }
    visual_style_ids = {
        "ai_presence_visual_style",
        "ai_presence_render_backend",
        "ai_presence_reduced_effects",
        "ai_presence_shaders_enabled",
        "ai_presence_particles_enabled",
        "ai_presence_overlay_opacity",
        "ai_presence_thinking_pulse",
        "ai_presence_speaking_reactivity",
        "ai_presence_mood_color_intensity",
        "ai_presence_glow_strength",
        "ai_presence_animation_speed",
        "ai_presence_idle_motion_strength",
        "ai_presence_background_darkness",
    }

    regrouped: list[NativeControl] = []
    for control in controls:
        if control.id in overview_ids:
            section = "Overview"
        elif control.id in display_ids:
            section = "Display"
        elif control.id in visual_style_ids:
            section = "Visual style"
        elif control.id.startswith("ai_presence_voice_thread_") or control.id in {
            "ai_presence_audio_refresh_hz",
            "ai_presence_music_reactivity",
            "ai_presence_music_reactivity_enabled",
        }:
            section = "Silk Threads"
        elif control.section == "Mood colors":
            section = "Mood & color"
        else:
            section = "Advanced"
        metadata = dict(control.metadata)
        description = _CONTROL_DESCRIPTIONS.get(control.id)
        if description:
            metadata["description"] = description
        if control.id in {"ai_presence_overlay_opacity", "ai_presence_floating_opacity"}:
            metadata["presentationHidden"] = True
        elif control.id in {"ai_presence_fullscreen_opacity", "ai_presence_floating_window_opacity"}:
            metadata.update(groupKey="display_opacity", groupTitle="Window opacity",
                            groupDescription="Adjust fullscreen and floating opacity independently.", groupColumnSpan=1)
        elif control.id in {"ai_presence_remember_floating_geometry", "ai_presence_reset_floating",
                            "ai_presence_floating_always_on_top", "ai_presence_click_through_default",
                            "ai_presence_right_drag_move_enabled", "ai_presence_transparent_background"}:
            metadata.update(groupKey="display_floating", groupTitle="Floating window", groupColumnSpan=1)
        regrouped.append(replace(control, section=section, metadata=metadata))

    controls = list(_apply_ai_presence_card_layout(regrouped))
    surface = NativeSurface(
        id="ai_presence_mode_tab",
        title="AI Presence",
        addon_id="nc.ai_presence_mode",
        sections=(
            "Overview",
            "Display",
            "Visual style",
            "Silk Threads",
            "Mood & color",
            "Advanced",
        ),
        description=(
            "Configure AI Presence fullscreen, floating window, visual styles, "
            "transparency, and audio sync."
        ),
        controls=tuple(controls),
    )
    return AIPresenceNativeAdapter(
        application_facade,
        surface,
        persist=persist,
    )


__all__ = ["AIPresenceNativeAdapter", "build_ai_presence_adapter"]
