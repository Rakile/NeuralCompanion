from __future__ import annotations

import sys
import json
from pathlib import Path

from PySide6 import QtCore

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from addons.ai_presence_mode.mood_color_resolver import normalize_mood_name, resolve_mood_colors
from addons.ai_presence_mode.controller import (
    AI_PRESENCE_CORE_SESSION_KEYS,
    COMPANION_ORB_SESSION_KEYS,
    DEFAULT_SETTINGS,
    NEURAL_FACE_SESSION_KEYS,
    ORB_RESPONSE_STYLES,
    VISUAL_STYLES,
    AIPresenceModeController,
    NeuralFacePresenceController,
)
from addons.companion_orb_overlay.controller import CompanionOrbOverlaySettingsController
from addons.companion_orb_overlay.companion_orb.companion_orb_bridge import CompanionOrbBridge
from addons.companion_orb_overlay.companion_orb.companion_orb_controller import (
    COMPANION_ORB_TARGET_METADATA,
    CompanionOrbController,
    DROP_ACK_MESSAGES,
    DROP_FOCUS_SECONDS,
    FOCUS_GRID_COLUMNS,
    FOCUS_GRID_ROWS,
    FULL_SCREEN_CONTEXT_THUMBNAIL_SIZE,
    MANUAL_INSPECTION_SECONDS,
    ORB_COMMAND_MENU_ACTIONS,
)
from addons.companion_orb_overlay.companion_orb import snapshot_ocr
from addons.companion_orb_overlay.companion_orb.snapshot_ocr import best_region_for_text
from addons.companion_orb_overlay.companion_orb.window_target_resolver import resolve_target_at, target_bounds, target_is_available
from visual_presence import runtime as presence_runtime
from visual_presence.visual_presence_controller import FLOATING_STYLE_CYCLE, VisualPresenceController, _next_visual_style
from visual_presence.visual_presence_bridge import VisualPresenceBridge


def main():
    core_keys = set(AI_PRESENCE_CORE_SESSION_KEYS)
    face_keys = set(NEURAL_FACE_SESSION_KEYS)
    orb_keys = set(COMPANION_ORB_SESSION_KEYS)
    assert core_keys
    assert face_keys
    assert orb_keys
    assert not core_keys.intersection(face_keys)
    assert not core_keys.intersection(orb_keys)
    assert not face_keys.intersection(orb_keys)
    assert AIPresenceModeController.SESSION_KEYS == AI_PRESENCE_CORE_SESSION_KEYS
    assert NeuralFacePresenceController.SESSION_KEYS == NEURAL_FACE_SESSION_KEYS
    assert CompanionOrbOverlaySettingsController.SESSION_KEYS == COMPANION_ORB_SESSION_KEYS
    assert "companion_orb_harassment_enabled" in orb_keys
    assert "companion_orb_harassment_timer_seconds" in orb_keys
    assert "companion_orb_snapshot_on_pointer_reached" in orb_keys
    assert "companion_orb_debug_enabled" in orb_keys
    assert "companion_orb_full_screen_context_enabled" in orb_keys
    assert "companion_orb_include_process_name" in orb_keys
    assert "companion_orb_response_style" in orb_keys
    assert DEFAULT_SETTINGS["companion_orb_harassment_enabled"] is False
    assert DEFAULT_SETTINGS["companion_orb_harassment_timer_seconds"] == 45
    assert DEFAULT_SETTINGS["companion_orb_snapshot_on_pointer_reached"] is False
    assert DEFAULT_SETTINGS["companion_orb_debug_enabled"] is False
    assert DEFAULT_SETTINGS["companion_orb_full_screen_context_enabled"] is False
    assert DEFAULT_SETTINGS["companion_orb_include_process_name"] is True
    assert DEFAULT_SETTINGS["companion_orb_response_style"] == "friendly"
    assert ("Sensual / non-explicit", "sensual_non_explicit") in ORB_RESPONSE_STYLES
    assert ORB_COMMAND_MENU_ACTIONS == ("Change Voice", "Response Style", "Chat text input")
    assert "INITIALIZE" not in ORB_COMMAND_MENU_ACTIONS
    assert "TERMINATE" not in ORB_COMMAND_MENU_ACTIONS
    assert DROP_ACK_MESSAGES
    assert any("something else to look at" in message for message in DROP_ACK_MESSAGES)
    assert DROP_FOCUS_SECONDS > 20.0
    assert MANUAL_INSPECTION_SECONDS >= 45.0
    assert FOCUS_GRID_COLUMNS == 12
    assert FOCUS_GRID_ROWS == 8
    assert FULL_SCREEN_CONTEXT_THUMBNAIL_SIZE[0] >= 1920
    assert FULL_SCREEN_CONTEXT_THUMBNAIL_SIZE[1] >= 1440
    assert "focus_bounds" in COMPANION_ORB_TARGET_METADATA["pingpong_prompt"]
    assert "Full-screen context map" in COMPANION_ORB_TARGET_METADATA["pingpong_prompt"]
    assert "actual visible content" in COMPANION_ORB_TARGET_METADATA["pingpong_prompt"]
    assert "manual_inspection.focus_bounds" in COMPANION_ORB_TARGET_METADATA["pingpong_prompt"]
    assert "Do not describe the selection action" in COMPANION_ORB_TARGET_METADATA["pingpong_prompt"]
    assert "Never mention \"dropped\"" in COMPANION_ORB_TARGET_METADATA["pingpong_prompt"]
    assert any(item.get("field") == "metadata.ocr_regions" for item in COMPANION_ORB_TARGET_METADATA["ping_payload"])
    assert any(item.get("field") == "metadata.manual_inspection" for item in COMPANION_ORB_TARGET_METADATA["ping_payload"])
    assert any(item.get("field") == "metadata.manual_inspection_primary" for item in COMPANION_ORB_TARGET_METADATA["ping_payload"])
    assert any(item.get("field") == "metadata.drop_focus_bounds" for item in COMPANION_ORB_TARGET_METADATA["ping_payload"])
    assert hasattr(snapshot_ocr, "_extract_with_win32_window_text")
    assert ("Blue Flame Smoke", "blue_flame_smoke") in VISUAL_STYLES
    assert "blue_flame_smoke" in FLOATING_STYLE_CYCLE
    assert _next_visual_style("breathing_orb") in FLOATING_STYLE_CYCLE
    assert _next_visual_style(FLOATING_STYLE_CYCLE[-1]) == FLOATING_STYLE_CYCLE[0]
    assert not _next_visual_style("neural_face_female").startswith("neural_face_")

    assert normalize_mood_name("happy") == "happy"
    assert normalize_mood_name("shy") == "curious"
    assert normalize_mood_name("surprised") == "excited"
    assert normalize_mood_name("unknown-mood") == "neutral"
    happy = resolve_mood_colors("happy")
    neutral = resolve_mood_colors("unknown-mood")
    assert happy["moodName"] == "happy"
    assert neutral["moodName"] == "neutral"
    assert "primaryColor" in happy
    presence_runtime.set_presence_mood("curious")
    presence_runtime.set_presence_mood("unknown-mood")
    assert hasattr(presence_runtime, "set_companion_orb_comment_focus")
    presence_runtime.set_companion_orb_comment_focus({"bounds": [10, 20, 120, 90], "label": "smoke focus"})
    ocr_match = best_region_for_text(
        "Should I investigate run_neural_companion.bat?",
        [
            {"text": "Other text", "screen_bounds": [4, 5, 60, 20]},
            {"text": "run_neural_companion.bat", "screen_bounds": [10, 20, 180, 26]},
        ],
        fallback_bounds=[1, 2, 300, 240],
    )
    assert ocr_match["screen_bounds"] == [10, 20, 180, 26]
    blank_ocr_match = best_region_for_text(
        "snapshot",
        [{"text": "", "kind": "text_region", "screen_bounds": [200, 71, 587, 43], "backend": "opencv_text_regions"}],
        fallback_bounds=[0, -78, 787, 528],
    )
    assert blank_ocr_match["kind"] == "fallback"
    assert blank_ocr_match["screen_bounds"] == [0, -78, 787, 528]

    style_bridge = VisualPresenceBridge()
    style_bridge.apply_settings({"ai_presence_enabled": True, "ai_presence_visual_style": "blue_flame_smoke"})
    assert style_bridge.visualStyle == "blue_flame_smoke"

    presence_bridge = VisualPresenceBridge()
    presence_bridge.apply_settings(
        {
            "ai_presence_enabled": True,
            "ai_presence_display_mode": "floating",
            "ai_presence_visual_style": "neural_face_female",
            "ai_presence_neural_face_enabled": True,
            "ai_presence_neural_face_variant": "female",
            "ai_presence_click_through_default": True,
            "ai_presence_right_drag_move_enabled": True,
            "ai_presence_neural_face_size": 1.12,
            "ai_presence_neural_face_opacity": 0.86,
            "ai_presence_neural_face_lipsync_strength": 1.25,
            "ai_presence_neural_face_blink_enabled": True,
            "ai_presence_neural_face_eye_movement_enabled": True,
            "ai_presence_female_neural_face_enabled": True,
            "ai_presence_female_reference_nodes": True,
            "ai_presence_female_show_wire_nodes": True,
            "ai_presence_female_show_wire_lines": True,
            "ai_presence_female_node_glow_enabled": True,
            "ai_presence_female_wire_pulse_enabled": True,
            "ai_presence_female_depth_enabled": True,
        }
    )
    assert presence_bridge.enabled is True
    assert presence_bridge.displayMode == "floating"
    assert presence_bridge.visualStyle == "neural_face_female"
    assert presence_bridge.clickThroughDefault is True
    assert presence_bridge.rightDragMoveEnabled is True
    assert presence_bridge.neuralFaceEnabled is True
    assert presence_bridge.neuralFaceVariant == "female"
    assert presence_bridge.neuralFaceSize > 1.0
    assert presence_bridge.neuralFaceOpacity < 0.9
    assert presence_bridge.neuralFaceLipSyncStrength > 1.0
    assert presence_bridge.femaleNeuralFaceEnabled is True
    assert presence_bridge.femaleReferenceNodes is True
    assert presence_bridge.femaleShowWireNodes is True
    assert presence_bridge.femaleShowWireLines is True
    assert presence_bridge.femaleNodeGlowEnabled is True
    assert presence_bridge.femaleWirePulseEnabled is True
    assert presence_bridge.femaleDepthEnabled is True
    topology_path = ROOT / "addons" / "ai_presence_mode" / "assets" / "neural_face" / "female" / "reference_female_topology.json"
    cutout_path = ROOT / "addons" / "ai_presence_mode" / "assets" / "neural_face" / "female" / "reference_female_avatar_cutout.png"
    topology = json.loads(topology_path.read_text(encoding="utf-8"))
    assert len(topology.get("nodes", [])) >= 180
    assert len(topology.get("edges", [])) >= 500
    assert cutout_path.exists()
    overlay_qml = (ROOT / "visual_presence" / "visual_overlay.qml").read_text(encoding="utf-8")
    assert "renderTarget: Canvas.Image" in overlay_qml
    assert 'globalCompositeOperation = "copy"' in overlay_qml
    assert "drawBlueFlameSmoke" in overlay_qml
    presence_controller_source = (ROOT / "visual_presence" / "visual_presence_controller.py").read_text(encoding="utf-8")
    assert "CompositionMode_Source" in presence_controller_source
    assert "def _ensure_floating_renderer" in presence_controller_source
    assert "def _resolved_palette" in presence_controller_source
    assert "glowStrength" in presence_controller_source
    assert "lineBrightness" in presence_controller_source
    assert "haloThickness" in presence_controller_source
    assert "ringExpansionSpeed" in presence_controller_source
    assert "waveformStrength" in presence_controller_source
    assert "def _draw_transparent_style" in presence_controller_source
    assert "def _draw_vector_voice_orb" in presence_controller_source
    assert "def _draw_blue_flame_smoke" in presence_controller_source
    assert "def _draw_transparent_rings" in presence_controller_source
    assert "def _smooth_level" in presence_controller_source
    assert "base = min(width, height) * (0.075 if style == \"minimal_dot\" else 0.19)" in presence_controller_source
    assert "orb_radius=radius * 0.74" in presence_controller_source
    assert "radius * 0.48" in presence_controller_source
    assert "radius * 0.62" in presence_controller_source
    assert "radius * 0.56" in presence_controller_source
    ai_presence_controller_source = (ROOT / "addons" / "ai_presence_mode" / "controller.py").read_text(encoding="utf-8")
    assert "class _ResponsiveGridWidget" in ai_presence_controller_source
    assert "ai_presence_slider_responsive_grid" in ai_presence_controller_source
    assert "ai_presence_toggle_groups_grid" in ai_presence_controller_source
    assert "Visual Tuning" in ai_presence_controller_source
    companion_overlay_controller_source = (ROOT / "addons" / "companion_orb_overlay" / "controller.py").read_text(encoding="utf-8")
    companion_overlay_main_source = (ROOT / "addons" / "companion_orb_overlay" / "main.py").read_text(encoding="utf-8")
    companion_orb_source = (ROOT / "addons" / "companion_orb_overlay" / "companion_orb" / "sensory_source.py").read_text(encoding="utf-8")
    engine_source = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert "companion_orb_slider_responsive_grid" in companion_overlay_controller_source
    assert "companion_orb_toggle_groups_grid" in companion_overlay_controller_source
    assert "companion_orb_hotkey_responsive_grid" in companion_overlay_controller_source
    assert "companion_orb_sensory_tabs" in companion_overlay_controller_source
    assert "Source guidance for Companion Orb Target" in companion_overlay_controller_source
    assert "companion_orb_capture_settings_grid" in companion_overlay_controller_source
    assert "companion_orb_supervisor_settings_grid" in companion_overlay_controller_source
    assert "companion_orb_debug_enabled_checkbox" in companion_overlay_controller_source
    assert "companion_orb_debug_log_path_preview" in companion_overlay_controller_source
    assert "Full-screen context map" in companion_overlay_controller_source
    assert "Mention process names" in companion_overlay_controller_source
    assert "Orb Tuning" in companion_overlay_controller_source
    assert 'Always set should_generate_image=false and visual_candidate=""' in companion_orb_source
    assert "_hidden_sensory_snapshots_include_source" in engine_source
    assert "Suppressed Companion Orb Target visual generation request" in engine_source
    assert "orb.request_comment_focus" in companion_overlay_main_source
    assert "\"focus_bounds\": data.get(\"focus_bounds\")" in companion_overlay_main_source
    for style_name in (
        "vector_voice_orb",
        "circular_audio_waveform",
        "halo_rings",
        "minimal_dot",
        "hologram_core",
        "signal_bloom",
        "crystal_prism",
        "blue_flame_smoke",
    ):
        assert f'style == "{style_name}"' in presence_controller_source
    renderer_probe = VisualPresenceController.__new__(VisualPresenceController)
    renderer_probe.bridge = type("BridgeProbe", (), {"transparentBackground": True})()
    assert VisualPresenceController._floating_prefers_widget_renderer(renderer_probe)
    renderer_probe.bridge.transparentBackground = False
    assert not VisualPresenceController._floating_prefers_widget_renderer(renderer_probe)

    bridge = CompanionOrbBridge()
    bridge.apply_settings(
        {
            "companion_orb_enabled": True,
            "companion_orb_display_mode": "docked",
            "companion_orb_visual_style": "neural_spark",
            "companion_orb_size": 84,
            "companion_orb_sensory_target_enabled": True,
            "companion_orb_voice_sync_enabled": True,
            "companion_orb_falling_particles_enabled": True,
            "companion_orb_falling_particle_density": 22,
            "companion_orb_falling_particle_lifetime": 4.6,
        }
    )
    bridge.setAiState("listening")
    bridge.setAudioLevel(0.42)
    assert bridge.enabled is True
    assert bridge.displayMode == "docked"
    assert bridge.visualStyle == "neural_spark"
    assert bridge.aiState == "listening"
    assert bridge.audioLevel > 0.4
    assert bridge.voiceSyncEnabled is True
    assert bridge.fallingParticlesEnabled is True
    assert bridge.fallingParticleDensity == 22
    assert bridge.fallingParticleLifetime > 4.5
    bridge.set_target_info({"target_type": "window", "title": "Story Window", "process_name": "nc.exe", "bounds": [1, 2, 300, 240]})
    assert bridge.targetTitle == "Story Window - nc.exe"
    bridge.apply_settings({"companion_orb_voice_sync_enabled": False})
    bridge.setAudioLevel(0.9)
    assert bridge.audioLevel == 0.0
    companion_orb_source = (ROOT / "addons" / "companion_orb_overlay" / "companion_orb" / "companion_orb_controller.py").read_text(encoding="utf-8")
    assert "def _show_chat_input_popup" in companion_orb_source
    assert "def _send_orb_chat_message" in companion_orb_source
    assert "companion_orb_chat_input_popup" in companion_orb_source
    assert "send_typed_chat_message" in companion_orb_source
    assert "explicit_bounds = self._normalize_bounds(data.get(\"focus_bounds\"))" in companion_orb_source
    assert "fallback_bounds = self._normalize_bounds(data.get(\"bounds\"))" in companion_orb_source
    assert "\"focus_bounds\": list(explicit_bounds or [])" in companion_orb_source
    assert "def _debug_event" in companion_orb_source
    assert "companion_orb_debug.log" in companion_orb_source
    assert "snapshot_target_saved" in companion_orb_source
    assert "requested_screen_bounds" in companion_orb_source
    assert "bounds_were_clipped" in companion_orb_source
    assert "movement_step" in companion_orb_source
    assert "screenAt(target_center)" in companion_orb_source
    assert "def _focus_grid_for_bounds" in companion_orb_source
    assert "def _comment_focus_grid_target" in companion_orb_source
    assert "focus_grid_target" in companion_orb_source
    assert "focus_grid=dict(self._comment_focus_grid" in companion_orb_source
    assert "def _visual_focus_region_for_text" in companion_orb_source
    assert "def _announce_drop_inspection" in companion_orb_source
    assert "drop_ack_started" in companion_orb_source
    assert "drop_ack_speech_skipped" in companion_orb_source
    assert "snapshots_override" in companion_orb_source
    assert "max_attempts = 40 if snapshot_payload else 8" in companion_orb_source
    assert "drop_audio_interrupted" in companion_orb_source
    assert "inspect the visible content inside the selected focus area" in companion_orb_source
    assert "manual_drop_region" in companion_orb_source
    assert "stale_drop_inspection_text" in companion_orb_source
    assert "def _grab_desktop_without_orb" in companion_orb_source
    assert "snapshot_cloak_enabled" in companion_orb_source
    assert "required_response_focus" in companion_orb_source
    assert "drop_focus_bounds" in companion_orb_source
    assert "thumbnail_limit" in companion_orb_source
    assert "def _populate_response_style_menu" in companion_orb_source
    assert "companion_orb_response_style" in companion_orb_source
    assert "def _style_orb_canned_message" in companion_orb_source
    assert "Use the Companion Orb response style" in companion_orb_source
    assert "def _screen_source_capture_index" in companion_orb_source
    assert "capture_mode = \"selected_screen\"" in companion_orb_source
    assert "screen_source_capture_screen_index" in companion_orb_source
    qt_host_services_source = (ROOT / "core" / "addons" / "qt_host_services.py").read_text(encoding="utf-8")
    assert "def send_typed_chat_message" in qt_host_services_source
    engine_source = (ROOT / "engine.py").read_text(encoding="utf-8")
    assert "def _compact_sensory_text_payload" in engine_source
    assert "def _mark_hidden_sensory_ping_attempt" in engine_source
    assert "def _hidden_sensory_should_use_fallback_request" in engine_source
    assert "fallback_params.pop(\"response_format\", None)" in engine_source
    assert "Hidden PONG retrying with text-only sensory context" in engine_source
    assert "\"focus_bounds\": [number, number, number, number]" in engine_source
    assert "companion_orb_include_process_name" in engine_source
    assert "def _companion_orb_response_style_instruction" in engine_source
    assert "def _companion_orb_response_style_label" in engine_source
    assert "def _companion_orb_source_uses_response_style" in engine_source
    assert "hard style instruction" in engine_source
    assert "Make the style clearly recognizable" in engine_source
    assert "sensual_non_explicit" in engine_source
    assert "Selected response style" in engine_source
    assert "manual_inspection" in engine_source
    assert "def _manual_priority_sensory_snapshots" in engine_source
    assert "def _manual_companion_orb_focus_from_snapshots" in engine_source
    assert "snapshots_override" in engine_source
    assert "allow_audio_playback=manual_override" in engine_source
    assert "def _sanitize_companion_orb_manual_candidate" in engine_source
    assert "Move me a little closer to the detail" in engine_source
    assert "manual_inspection_primary" in engine_source
    assert "\"focus_bounds\": list(focus_bounds)" in engine_source
    assert "\"focus_text\": focus_text or proactive_candidate or summary" in engine_source

    region = resolve_target_at(100, 100, region_width=320, region_height=200, mode="region")
    assert region["target_type"] == "region"
    assert target_bounds(region) == region["bounds"]
    assert target_is_available(region)
    target_probe = CompanionOrbController.__new__(CompanionOrbController)
    target_probe._last_runtime_config = {"companion_orb_require_target_confirmation": True}
    target_probe._target_info = {}
    target_probe._last_runtime_config["companion_orb_include_process_name"] = False
    target_label = CompanionOrbController._target_title_from_info(
        target_probe,
        {"target_type": "window", "title": "Story Window", "process_name": "nc.exe", "bounds": [1, 2, 3, 4]},
    )
    assert target_label == "Story Window"
    sanitized_target = CompanionOrbController._target_for_output(
        target_probe,
        {"target_type": "window", "title": "Story Window", "process_name": "nc.exe", "bounds": [1, 2, 3, 4]},
    )
    assert sanitized_target["process_name"] == ""
    target_probe._last_runtime_config["companion_orb_response_style"] = "sarcastic"
    styled_message = CompanionOrbController._style_orb_canned_message(target_probe, "Hello, are you there?")
    assert "extremely normal" in styled_message
    assert CompanionOrbController._target_requires_confirmation(
        target_probe,
        {"target_type": "window", "window_id": "0x1234", "title": "Other", "bounds": [1, 2, 3, 4]},
    )
    assert CompanionOrbController._target_requires_confirmation(
        target_probe,
        {"target_type": "region", "title": "Region around Companion Orb", "bounds": [1, 2, 300, 240]},
    )
    target_probe._window = None
    target_probe._last_runtime_config = {"companion_orb_avoid_center": True}
    target_probe._last_snapshot_ocr_regions = [
        {"text": "", "kind": "text_region", "screen_bounds": [220, 100, 160, 120], "backend": "opencv_text_regions"}
    ]
    target_probe._last_snapshot_bounds = [0, 0, 640, 480]
    target_probe._manual_inspection_bounds = []
    target_probe._manual_inspection_until = 0.0
    target_probe._debug_event = lambda *_args, **_kwargs: None
    grid = CompanionOrbController._focus_grid_for_bounds(target_probe, [100, 100, 120, 80])
    assert grid["columns"] == FOCUS_GRID_COLUMNS
    assert grid["rows"] == FOCUS_GRID_ROWS
    assert len(grid["cell"]) == 2
    assert len(grid["cell_bounds"]) == 4
    target_probe._window = type("FakeOrbWindow", (), {"width": lambda self: 180, "height": lambda self: 180})()
    grid_target = CompanionOrbController._comment_focus_grid_target(target_probe, grid)
    assert isinstance(grid_target, QtCore.QPointF)
    target_probe._window = None
    visual_focus = CompanionOrbController._ocr_focus_bounds_for_text(
        target_probe,
        "comment on the image in this area",
        fallback_bounds=[180, 70, 260, 180],
    )
    assert visual_focus == [220, 100, 160, 120]
    target_probe._drift_target_point = None
    target_probe._drift_target_kind = ""
    first_target = CompanionOrbController._stable_drift_target(
        target_probe,
        "harassment",
        QtCore.QPointF(100.0, 100.0),
        deadzone=20.0,
        blend=0.2,
    )
    held_target = CompanionOrbController._stable_drift_target(
        target_probe,
        "harassment",
        QtCore.QPointF(108.0, 105.0),
        deadzone=20.0,
        blend=0.2,
    )
    moved_target = CompanionOrbController._stable_drift_target(
        target_probe,
        "harassment",
        QtCore.QPointF(200.0, 100.0),
        deadzone=20.0,
        blend=0.2,
    )
    assert held_target == first_target
    assert first_target.x() < moved_target.x() < 200.0
    print("AI Presence and Companion Orb smoke checks passed.")


if __name__ == "__main__":
    main()
