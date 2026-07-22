from __future__ import annotations

import ast
import ctypes
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def assert_close(actual: float, expected: float, message: str, tolerance: float = 0.001) -> None:
    if abs(float(actual) - float(expected)) > tolerance:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def method_source(source: str, class_name: str, method_name: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                return ast.get_source_segment(source, child) or ""
    raise AssertionError(f"Missing {class_name}.{method_name}().")


def main() -> None:
    from addons.ai_presence_mode import controller as base_settings_controller
    from addons.companion_orb_overlay.companion_orb import eye_tracking
    from addons.companion_orb_overlay.companion_orb import gaze_calibration
    from addons.companion_orb_overlay.companion_orb import gaze_radial_menu
    from addons.companion_orb_overlay import controller as settings_controller

    expected_defaults = {
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
    if settings_controller.COMPANION_ORB_EYE_TRACKING_DEFAULTS != expected_defaults:
        raise AssertionError(
            "Eye-tracking defaults should remain conservative and session-compatible: "
            f"{settings_controller.COMPANION_ORB_EYE_TRACKING_DEFAULTS!r}"
        )
    manifest_path = ROOT_DIR / "addons" / "companion_orb_overlay" / "addon.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registered_runtime_defaults = dict(manifest.get("runtime_defaults") or {})
    required_runtime_defaults = {
        **settings_controller.COMPANION_ORB_AWARE_MOTION_DEFAULTS,
        **settings_controller.COMPANION_ORB_EYE_TRACKING_DEFAULTS,
    }
    missing_runtime_defaults = {
        key: value
        for key, value in required_runtime_defaults.items()
        if registered_runtime_defaults.get(key) != value
    }
    if missing_runtime_defaults:
        raise AssertionError(
            "Eye-tracking and aware-movement settings must be declared in addon runtime_defaults "
            "or engine.update_runtime_config silently discards their live UI changes: "
            f"{missing_runtime_defaults!r}"
        )
    missing_session_keys = sorted(
        set(expected_defaults) - set(settings_controller.CompanionOrbOverlaySettingsController.SESSION_KEYS)
    )
    if missing_session_keys:
        raise AssertionError(f"Eye-tracking settings are missing from session export: {missing_session_keys!r}")
    normalize_setting = settings_controller.CompanionOrbOverlaySettingsController._normalize_setting
    normalization_cases = (
        ("companion_orb_eye_tracking_mode", "follow", "continuous"),
        ("companion_orb_eye_tracking_reaction_mode", "disabled", "off"),
        ("companion_orb_eye_tracking_dwell_ms", 9999, 2000),
        ("companion_orb_eye_tracking_long_gaze_enabled", "yes", True),
        ("companion_orb_eye_tracking_expand_read_text_area", "yes", True),
        ("companion_orb_eye_tracking_expand_read_text_area", "off", False),
        ("companion_orb_eye_tracking_long_gaze_ms", 99999, 15000),
        ("companion_orb_eye_tracking_radial_button_gaze_ms", 1, 250),
        ("companion_orb_eye_tracking_radial_menu_opacity", 0.1, 0.35),
        ("companion_orb_eye_tracking_radial_menu_opacity", 4.0, 1.0),
        ("companion_orb_eye_tracking_radial_focus_beam_enabled", "yes", True),
        ("companion_orb_eye_tracking_radial_focus_beam_enabled", "off", False),
        ("companion_orb_eye_tracking_gaze_timer_color", "  FFAA00  ", "#ffaa00"),
        ("companion_orb_eye_tracking_radius_px", 1, 24),
        ("companion_orb_eye_tracking_smoothing", 3.0, 0.85),
        ("companion_orb_eye_tracking_reaction_cooldown_seconds", 1, 10),
        ("companion_orb_eye_tracking_screen_index", "3", 3),
        ("companion_orb_eye_tracking_dll_path", "  C:/Tobii/test.dll  ", "C:/Tobii/test.dll"),
        ("companion_orb_eye_tracking_offset_x_px", -999, -400),
        ("companion_orb_eye_tracking_offset_y_px", 999, 400),
        ("companion_orb_eye_tracking_calibration", "invalid", {}),
        (
            "companion_orb_eye_tracking_calibration",
            {"version": 1},
            {"version": 1},
        ),
        ("companion_orb_eye_tracking_pointer_clearance_enabled", "yes", True),
        ("companion_orb_eye_tracking_pointer_clearance_enabled", "off", False),
        ("companion_orb_eye_tracking_pointer_clearance_distance_px", 999, 400),
        ("companion_orb_eye_tracking_pointer_clearance_timeout_seconds", 0, 1),
        ("companion_orb_eye_tracking_blink_click_allowed", "off", False),
        ("companion_orb_eye_tracking_blink_min_ms", 1, 40),
        ("companion_orb_eye_tracking_blink_slow_min_ms", 9999, 700),
        ("companion_orb_eye_tracking_blink_max_ms", 9999, 1500),
        ("companion_orb_eye_tracking_blink_recovery_ms", 1, 30),
        ("companion_orb_eye_tracking_blink_double_gap_ms", 1, 400),
        ("companion_orb_eye_tracking_blink_click_cooldown_ms", 9999, 1500),
    )
    for key, raw, expected in normalization_cases:
        actual = normalize_setting(None, key, raw)
        if actual != expected:
            raise AssertionError(f"Setting {key!r} normalized to {actual!r}, expected {expected!r}.")

    settings_source = Path(settings_controller.__file__).read_text(encoding="utf-8")
    for fragment in (
        "COMPANION_ORB_EYE_TRACKING_MODES",
        "COMPANION_ORB_EYE_TRACKING_REACTION_MODES",
        'tab_layouts["Eye Tracking"]',
        '"Eye Tracking": ("eye_tracking",',
        'elif key == "eye_tracking":',
        "companion_orb_eye_tracking_tab",
        "companion_orb_eye_tracking_status_indicator",
        "companion_orb_eye_tracking_connection_label",
        "companion_orb_eye_tracking_runtime_label",
        'status.get("connection_code")',
        "companion_orb_eye_tracking_mode_combo",
        "companion_orb_eye_tracking_reaction_mode_combo",
        "companion_orb_eye_tracking_dwell_slider",
        "companion_orb_eye_tracking_long_gaze_checkbox",
        "companion_orb_eye_tracking_expand_read_text_area_checkbox",
        '"Expand area for text"',
        "companion_orb_eye_tracking_long_gaze_ms_spin",
        "companion_orb_eye_tracking_radial_button_gaze_ms_spin",
        "companion_orb_eye_tracking_radial_menu_opacity_slider",
        "companion_orb_eye_tracking_radial_focus_beam_checkbox",
        "companion_orb_eye_tracking_gaze_timer_color_edit",
        "companion_orb_eye_tracking_gaze_timer_color_pick_button",
        "companion_orb_eye_tracking_gaze_timer_color_swatch",
        "companion_orb_eye_tracking_radius_slider",
        "companion_orb_eye_tracking_smoothing_slider",
        "companion_orb_eye_tracking_cooldown_slider",
        "companion_orb_eye_tracking_offset_x_slider",
        "companion_orb_eye_tracking_offset_y_slider",
        "companion_orb_eye_tracking_calibration_indicator",
        "companion_orb_eye_tracking_calibration_status_label",
        "companion_orb_eye_tracking_calibration_result_label",
        "companion_orb_eye_tracking_calibration_start_button",
        "companion_orb_eye_tracking_calibration_cancel_button",
        "companion_orb_eye_tracking_calibration_reset_button",
        "companion_orb_eye_tracking_pointer_clearance_checkbox",
        "companion_orb_eye_tracking_pointer_clearance_distance_slider",
        "companion_orb_eye_tracking_pointer_clearance_timeout_slider",
        "companion_orb_eye_tracking_pointer_clearance_status_label",
        "companion_orb_eye_tracking_blink_click_allowed_checkbox",
        "companion_orb_eye_tracking_blink_status_label",
        "companion_orb_eye_tracking_blink_min_ms_slider",
        "companion_orb_eye_tracking_blink_slow_min_ms_slider",
        "companion_orb_eye_tracking_blink_max_ms_slider",
        "companion_orb_eye_tracking_blink_recovery_ms_slider",
        "companion_orb_eye_tracking_blink_double_gap_ms_slider",
        "companion_orb_eye_tracking_blink_click_cooldown_ms_slider",
        "companion_orb_eye_tracking_stable_preset_button",
        "companion_orb_eye_tracking_screen_combo",
        "companion_orb_eye_tracking_dll_path_edit",
        "companion_orb_eye_tracking_browse_button",
        "companion_orb_eye_tracking_reconnect_button",
        "companion_orb_eye_tracking_react_button",
        "companion_orb_eye_tracking_status_label",
        "companion_orb_eye_tracking_hotkey",
        "QtWidgets.QFileDialog.getOpenFileName",
        "reconnect_eye_tracking",
        "react_at_gaze",
        "start_eye_tracking_calibration",
        "cancel_eye_tracking_calibration",
        "reset_eye_tracking_calibration",
    ):
        if fragment not in settings_source:
            raise AssertionError(f"Companion Orb eye-tracking UI is missing {fragment!r}.")

    presentation_cases = {
        "connected": ("Connected", "#22c55e"),
        "connecting": ("Connecting", "#f59e0b"),
        "reconnecting": ("Reconnecting", "#f59e0b"),
        "no_device": ("Tracker not found", "#ef4444"),
        "no_dll": ("Runtime not found", "#ef4444"),
        "error": ("Connection error", "#ef4444"),
        "off": ("Off", "#94a3b8"),
        "orb_disabled": ("Orb inactive", "#94a3b8"),
    }
    for code, expected in presentation_cases.items():
        actual = settings_controller._eye_tracking_connection_presentation(code)
        if actual != expected:
            raise AssertionError(
                f"Eye-tracking connection state {code!r} should present as {expected!r}, got {actual!r}."
            )

    direct_orb_service = object()
    host_orb_service = object()
    service_controller = type("ServiceController", (), {})()
    service_controller.context = type(
        "HostOnlyContext",
        (),
        {"get_service": lambda _self, _name: host_orb_service},
    )()
    settings_controller.CompanionOrbOverlaySettingsController.set_companion_orb_service(
        service_controller,
        direct_orb_service,
    )
    resolved_orb_service = settings_controller.CompanionOrbOverlaySettingsController._companion_orb_service(
        service_controller
    )
    if resolved_orb_service is not direct_orb_service:
        raise AssertionError(
            "Companion Orb settings must use the controller instance injected by its owning addon."
        )

    stable_preset = settings_controller._stable_eye_tracking_movement_preset(92)
    expected_stable_preset = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_dwell_ms": 650,
        "companion_orb_eye_tracking_radius_px": 110,
        "companion_orb_eye_tracking_smoothing": 0.16,
        "companion_orb_eye_tracking_offset_x_px": -110,
        "companion_orb_eye_tracking_offset_y_px": 0,
        "companion_orb_movement_enabled": False,
        "companion_orb_aware_motion_enabled": False,
        "companion_orb_avoid_mouse": False,
        "companion_orb_harassment_enabled": False,
    }
    if stable_preset != expected_stable_preset:
        raise AssertionError(
            "Stable Gaze preset should remove competing movement and center the default-size Orb: "
            f"expected={expected_stable_preset!r}, actual={stable_preset!r}"
        )
    if settings_controller._stable_eye_tracking_movement_preset("invalid") != expected_stable_preset:
        raise AssertionError("Stable Gaze preset should tolerate an invalid saved Orb size.")

    if eye_tracking.normalize_tracking_mode(None) != "dwell":
        raise AssertionError("Missing tracking mode should default to dwell focus.")
    mode_aliases = {
        "dwell_focus": "dwell",
        "follow": "continuous",
        "manual_only": "manual",
        "disabled": "off",
        "unexpected": "dwell",
    }
    for raw, expected in mode_aliases.items():
        actual = eye_tracking.normalize_tracking_mode(raw)
        if actual != expected:
            raise AssertionError(f"Tracking mode {raw!r} normalized to {actual!r}, expected {expected!r}.")

    if eye_tracking.normalize_reaction_mode(None) != "meaningful":
        raise AssertionError("Missing reaction mode should default to meaningful changes.")
    reaction_aliases = {
        "meaningful_changes": "meaningful",
        "every": "every_dwell",
        "disabled": "off",
        "unexpected": "meaningful",
    }
    for raw, expected in reaction_aliases.items():
        actual = eye_tracking.normalize_reaction_mode(raw)
        if actual != expected:
            raise AssertionError(f"Reaction mode {raw!r} normalized to {actual!r}, expected {expected!r}.")

    policy = eye_tracking.GazeFocusPolicy(dwell_ms=700, radius_px=60, smoothing=0.5)
    first = policy.ingest(100.0, 100.0, now=0.0)
    if first.dwell_triggered or first.stable:
        raise AssertionError("A first gaze sample must not immediately complete a dwell.")
    second = policy.ingest(120.0, 100.0, now=0.2)
    assert_close(second.point[0], 110.0, "Gaze smoothing should blend toward the latest point")
    before_dwell = policy.ingest(120.0, 100.0, now=0.69)
    if before_dwell.dwell_triggered:
        raise AssertionError("A dwell must not trigger before the configured delay.")
    completed = policy.ingest(120.0, 100.0, now=0.71)
    if not completed.dwell_triggered or not completed.stable:
        raise AssertionError("A stable gaze should trigger once after 700 ms.")
    held = policy.ingest(121.0, 101.0, now=1.4)
    if held.dwell_triggered or not held.stable:
        raise AssertionError("A held gaze should stay stable without repeatedly triggering.")

    long_policy = eye_tracking.GazeFocusPolicy(
        dwell_ms=700,
        long_dwell_ms=3000,
        radius_px=60,
        smoothing=1.0,
    )
    long_start = long_policy.ingest(320.0, 240.0, now=10.0)
    assert_close(long_start.hold_seconds, 0.0, "A new gaze hold should start at zero")
    assert_close(long_start.dwell_progress, 0.0, "A new gaze hold should start with no timer progress")
    short_complete = long_policy.ingest(320.0, 240.0, now=10.7)
    if not short_complete.dwell_triggered or short_complete.long_dwell_triggered:
        raise AssertionError("The short dwell should complete before the long dwell.")
    assert_close(short_complete.dwell_progress, 0.7 / 3.0, "Timer progress should continue toward long gaze")
    between_dwells = long_policy.ingest(321.0, 240.0, now=12.0)
    if between_dwells.dwell_triggered or between_dwells.long_dwell_triggered:
        raise AssertionError("Holding between thresholds should not repeat either dwell event.")
    assert_close(between_dwells.hold_seconds, 2.0, "A stable gaze should retain its full hold duration")
    long_complete = long_policy.ingest(320.0, 241.0, now=13.0)
    if long_complete.dwell_triggered or not long_complete.long_dwell_triggered:
        raise AssertionError("The long dwell should trigger exactly once at its configured threshold.")
    assert_close(long_complete.dwell_progress, 1.0, "Long dwell completion should fill the timer")
    long_held = long_policy.ingest(320.0, 240.0, now=13.5)
    if long_held.dwell_triggered or long_held.long_dwell_triggered:
        raise AssertionError("A held long gaze should not repeatedly trigger menu actions.")
    long_reset = long_policy.ingest(500.0, 240.0, now=13.6)
    if long_reset.stable or long_reset.dwell_triggered or long_reset.long_dwell_triggered:
        raise AssertionError("Leaving the focus radius should re-arm both dwell thresholds.")
    assert_close(long_reset.hold_seconds, 0.0, "A new focus should restart its hold duration")
    assert_close(long_reset.dwell_progress, 0.0, "A new focus should restart timer progress")

    interrupted_policy = eye_tracking.GazeFocusPolicy(
        dwell_ms=700,
        long_dwell_ms=3000,
        radius_px=60,
        smoothing=1.0,
        sample_gap_seconds=0.5,
    )
    interrupted_policy.ingest(320.0, 240.0, now=30.0)
    interrupted = interrupted_policy.ingest(320.0, 240.0, now=31.0)
    if interrupted.stable or interrupted.dwell_triggered or interrupted.long_dwell_triggered:
        raise AssertionError("A missing gaze stream must not count toward either dwell threshold.")
    assert_close(interrupted.hold_seconds, 0.0, "A resumed gaze should start a fresh hold")
    interrupted_policy.ingest(320.0, 240.0, now=31.4)
    if interrupted_policy.ingest(320.0, 240.0, now=31.69).dwell_triggered:
        raise AssertionError("A resumed gaze triggered before a complete uninterrupted dwell.")
    if not interrupted_policy.ingest(320.0, 240.0, now=31.70).dwell_triggered:
        raise AssertionError("A resumed gaze should trigger after a fresh uninterrupted dwell.")

    assert_close(
        eye_tracking.gaze_timer_visual_progress(
            hold_seconds=0.35,
            dwell_ms=700,
            long_dwell_ms=3000,
            long_gaze_enabled=False,
        ),
        0.5,
        "Short-dwell timer tint should use the full visual range when long gaze is off",
    )
    assert_close(
        eye_tracking.gaze_timer_visual_progress(
            hold_seconds=0.7,
            dwell_ms=700,
            long_dwell_ms=3000,
            long_gaze_enabled=True,
        ),
        0.6,
        "Completing the short dwell should produce a visible first-stage tint",
    )
    assert_close(
        eye_tracking.gaze_timer_visual_progress(
            hold_seconds=1.85,
            dwell_ms=700,
            long_dwell_ms=3000,
            long_gaze_enabled=True,
        ),
        0.8,
        "Long-gaze tint should continue smoothly after the short dwell",
    )
    assert_close(
        eye_tracking.gaze_timer_visual_progress(
            hold_seconds=3.0,
            dwell_ms=700,
            long_dwell_ms=3000,
            long_gaze_enabled=True,
        ),
        1.0,
        "The long-gaze threshold should fill the timer tint",
    )

    radial_action_ids = tuple(action.action_id for action in gaze_radial_menu.MAIN_GAZE_ACTIONS)
    expected_radial_action_ids = (
        "react",
        "describe",
        "explain",
        "summarize",
        "read_text",
        "voice",
        "reply_style",
        "chat",
        "scrolling",
        "action",
    )
    if radial_action_ids != expected_radial_action_ids:
        raise AssertionError(
            "The long-gaze menu must expose every requested action in a stable order: "
            f"{radial_action_ids!r}"
        )
    reserved_action = gaze_radial_menu.MAIN_GAZE_ACTIONS[-1]
    if reserved_action.label != "Action" or reserved_action.enabled:
        raise AssertionError(
            "The Action target must remain visible with its complete label but disabled by default: "
            f"{reserved_action!r}"
        )
    opacity_cases = (
        (None, 0.90),
        ("invalid", 0.90),
        (0.1, 0.35),
        (0.72, 0.72),
        (4.0, 1.0),
    )
    for raw_opacity, expected_opacity in opacity_cases:
        assert_close(
            gaze_radial_menu.normalize_radial_menu_opacity(raw_opacity),
            expected_opacity,
            f"Radial menu opacity should normalize {raw_opacity!r}",
        )
    hit_targets = (
        gaze_radial_menu.RadialHitTarget("react", 100.0, 100.0, 104.0),
    )
    if gaze_radial_menu.radial_hit_test((163.0, 100.0), hit_targets) != "react":
        raise AssertionError("A gaze near a radial button edge should enter its forgiving hit target.")
    if gaze_radial_menu.radial_hit_test((166.0, 100.0), hit_targets) is not None:
        raise AssertionError("A gaze outside the radial entry boundary should not select a button.")
    if (
        gaze_radial_menu.radial_hit_test(
            (176.0, 100.0),
            hit_targets,
            candidate_id="react",
        )
        != "react"
    ):
        raise AssertionError("Small gaze jitter should stay attached to the active radial button.")
    if (
        gaze_radial_menu.radial_hit_test(
            (178.0, 100.0),
            hit_targets,
            candidate_id="react",
        )
        is not None
    ):
        raise AssertionError("Leaving the sticky radial boundary should clear the active button.")
    assert_close(
        gaze_radial_menu.radial_layout_radius(8),
        235.0,
        "The eight-action menu should retain the expanded Orbital Glass radius",
    )
    assert_close(
        gaze_radial_menu.radial_layout_radius(5),
        217.5,
        "Smaller radial pages should also use 25 percent more spacing",
    )
    if gaze_radial_menu.RADIAL_MENU_SIZE < 660:
        raise AssertionError("The expanded radial layout needs enough canvas to avoid clipped buttons.")
    radial_menu_source = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "gaze_radial_menu.py"
    ).read_text(encoding="utf-8")
    radial_button_paint = method_source(radial_menu_source, "_RadialButton", "paintEvent")
    for required_fragment in (
        "QPainterPath",
        "setClipPath",
        "QLinearGradient",
        "fillRect",
        "drawArc",
    ):
        if required_fragment not in radial_button_paint:
            raise AssertionError(
                "Radial gaze progress should combine a clipped illuminated fill with its progress arc: "
                f"missing {required_fragment!r}"
            )
    if radial_button_paint.count("drawEllipse") < 3:
        raise AssertionError("Radial buttons should paint layered glow, surface, and border ellipses.")
    radial_menu_paint = method_source(radial_menu_source, "GazeRadialMenu", "paintEvent")
    for required_fragment in (
        "QRadialGradient",
        "QLinearGradient",
        "DashLine",
        "selection_candidate_id",
        "_focus_beam_enabled",
        "#ef4444",
        "#f59e0b",
        "#facc15",
    ):
        if required_fragment not in radial_menu_paint:
            raise AssertionError(
                "Orbital Glass should paint concentric glass orbits and a focused gaze beam: "
                f"missing {required_fragment!r}"
            )
    radial_mouse_press = method_source(radial_menu_source, "GazeRadialMenu", "mousePressEvent")
    if "_mouse_action_at_global_point" not in radial_mouse_press:
        raise AssertionError("Mouse outside-click handling must not reuse expanded gaze targets.")
    from PySide6 import QtCore, QtWidgets

    qt_app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    expand_setting_key = "companion_orb_eye_tracking_expand_read_text_area"
    isolated_runtime_config = dict(settings_controller.DEFAULT_SETTINGS)
    isolated_runtime_config[expand_setting_key] = True

    def test_runtime_config():
        return isolated_runtime_config

    def test_update_runtime_config(key, value):
        isolated_runtime_config[str(key)] = value
        return value

    class EyeSettingsContext:
        @staticmethod
        def get_service(_name):
            return None

    class EyeSettingsOrb:
        def __init__(self):
            self.calls: list[str] = []
            self.calibration = {
                "state": "not_calibrated",
                "message": "No gaze calibration is saved.",
                "active": False,
                "target_index": 0,
                "target_count": 5,
                "quality": "",
                "average_error_px": 0.0,
                "completed_at": "",
            }

        def eye_tracking_status(self):
            return {
                "code": "connected",
                "message": "Tobii eye tracking is connected.",
                "connection_code": "connected",
                "connection_message": "Tobii eye tracking is connected.",
                "dll_path": "C:/Tobii/tobii_stream_engine.dll",
                "running": True,
                "blink_click_allowed": True,
                "blink_click_enabled": False,
                "calibration": dict(self.calibration),
                "pointer_clearance": {
                    "state": "clear",
                    "enabled": bool(
                        isolated_runtime_config.get(
                            "companion_orb_eye_tracking_pointer_clearance_enabled",
                            False,
                        )
                    ),
                },
            }

        def start_eye_tracking_calibration(self):
            self.calls.append("start")
            self.calibration.update(
                {
                    "state": "calibrating",
                    "message": "Hold your gaze on target 1 of 5.",
                    "active": True,
                    "target_index": 1,
                }
            )
            return {"ok": True, "calibration": dict(self.calibration)}

        def cancel_eye_tracking_calibration(self):
            self.calls.append("cancel")
            self.calibration.update(
                {
                    "state": "not_calibrated",
                    "message": "No gaze calibration is saved.",
                    "active": False,
                    "target_index": 0,
                }
            )
            return {"ok": True, "calibration": dict(self.calibration)}

        def reset_eye_tracking_calibration(self):
            self.calls.append("reset")
            self.calibration.update(
                {
                    "state": "not_calibrated",
                    "message": "No gaze calibration is saved.",
                    "active": False,
                    "target_index": 0,
                    "quality": "",
                    "average_error_px": 0.0,
                    "completed_at": "",
                }
            )
            return {"ok": True, "calibration": dict(self.calibration)}

    eye_settings_orb = EyeSettingsOrb()
    original_runtime_helpers = (
        base_settings_controller._runtime_config,
        base_settings_controller._update_runtime_config,
        settings_controller._runtime_config,
        settings_controller._update_runtime_config,
    )
    live_settings_controller = None
    eye_settings_card = None
    try:
        base_settings_controller._runtime_config = test_runtime_config
        base_settings_controller._update_runtime_config = test_update_runtime_config
        settings_controller._runtime_config = test_runtime_config
        settings_controller._update_runtime_config = test_update_runtime_config
        live_settings_controller = settings_controller.CompanionOrbOverlaySettingsController(EyeSettingsContext())
        live_settings_controller.set_companion_orb_service(eye_settings_orb)
        eye_settings_card = live_settings_controller._build_eye_tracking_settings_card()
        eye_settings_card.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
        eye_settings_card.show()
        qt_app.processEvents()
        action_checkbox = eye_settings_card.findChild(
            QtWidgets.QCheckBox,
            "companion_orb_eye_tracking_click_target_checkbox",
        )
        action_hint = eye_settings_card.findChild(
            QtWidgets.QLabel,
            "companion_orb_eye_tracking_action_hint",
        )
        if (
            action_checkbox is None
            or action_checkbox.text() != "Enable Action gaze button"
            or action_checkbox.isChecked()
            or live_settings_controller._controls.get(
                "companion_orb_eye_tracking_click_target_enabled"
            )
            is not action_checkbox
            or action_hint is None
            or "UI Automation" not in action_hint.text()
        ):
            raise AssertionError(
                "The system-wide Action option is not clearly exposed and bound in the Eye Tracking UI."
            )
        expand_checkbox = eye_settings_card.findChild(
            QtWidgets.QCheckBox,
            "companion_orb_eye_tracking_expand_read_text_area_checkbox",
        )
        if (
            expand_checkbox is None
            or expand_checkbox.text() != "Expand area for text"
            or not expand_checkbox.isChecked()
            or live_settings_controller._controls.get(expand_setting_key) is not expand_checkbox
        ):
            raise AssertionError("The expanded Read text checkbox is not correctly bound in the Eye Tracking UI.")
        opacity_setting_key = "companion_orb_eye_tracking_radial_menu_opacity"
        opacity_slider = eye_settings_card.findChild(
            QtWidgets.QWidget,
            "companion_orb_eye_tracking_radial_menu_opacity_slider",
        )
        if (
            opacity_slider is None
            or live_settings_controller._controls.get(opacity_setting_key) is not opacity_slider
            or abs(float(opacity_slider.value()) - 0.90) > 0.001
        ):
            raise AssertionError("The radial menu opacity slider is not correctly bound in the Eye Tracking UI.")
        opacity_slider.slider.setValue(57)
        qt_app.processEvents()
        if abs(float(isolated_runtime_config.get(opacity_setting_key, 0.0)) - 0.57) > 0.001:
            raise AssertionError("Changing radial menu opacity did not update the live runtime setting.")
        beam_setting_key = "companion_orb_eye_tracking_radial_focus_beam_enabled"
        beam_checkbox = eye_settings_card.findChild(
            QtWidgets.QCheckBox,
            "companion_orb_eye_tracking_radial_focus_beam_checkbox",
        )
        if (
            beam_checkbox is None
            or beam_checkbox.text() != "Charging focus beam"
            or not beam_checkbox.isChecked()
            or live_settings_controller._controls.get(beam_setting_key) is not beam_checkbox
        ):
            raise AssertionError("The charging focus beam option is not correctly bound in the Eye Tracking UI.")
        beam_checkbox.setChecked(False)
        qt_app.processEvents()
        if isolated_runtime_config.get(beam_setting_key) is not False:
            raise AssertionError("Disabling the charging focus beam did not update the live runtime setting.")

        calibration_indicator = eye_settings_card.findChild(
            QtWidgets.QLabel,
            "companion_orb_eye_tracking_calibration_indicator",
        )
        calibration_status = eye_settings_card.findChild(
            QtWidgets.QLabel,
            "companion_orb_eye_tracking_calibration_status_label",
        )
        calibration_result = eye_settings_card.findChild(
            QtWidgets.QLabel,
            "companion_orb_eye_tracking_calibration_result_label",
        )
        calibration_start = eye_settings_card.findChild(
            QtWidgets.QPushButton,
            "companion_orb_eye_tracking_calibration_start_button",
        )
        calibration_cancel = eye_settings_card.findChild(
            QtWidgets.QPushButton,
            "companion_orb_eye_tracking_calibration_cancel_button",
        )
        calibration_reset = eye_settings_card.findChild(
            QtWidgets.QPushButton,
            "companion_orb_eye_tracking_calibration_reset_button",
        )
        if any(
            widget is None
            for widget in (
                calibration_indicator,
                calibration_status,
                calibration_result,
                calibration_start,
                calibration_cancel,
                calibration_reset,
            )
        ):
            raise AssertionError("The compact gaze calibration controls are incomplete.")
        live_settings_controller._refresh_eye_tracking_status()
        if calibration_cancel.isEnabled() or calibration_reset.isEnabled():
            raise AssertionError("Cancel and Reset should be inactive before calibration starts.")
        calibration_start.click()
        qt_app.processEvents()
        live_settings_controller._refresh_eye_tracking_status()
        if eye_settings_orb.calls != ["start"] or not calibration_cancel.isEnabled():
            raise AssertionError(
                "Start calibration did not call the Orb service and enter the active UI state: "
                f"calls={eye_settings_orb.calls!r}"
            )
        calibration_cancel.click()
        qt_app.processEvents()
        live_settings_controller._refresh_eye_tracking_status()
        if eye_settings_orb.calls != ["start", "cancel"] or calibration_cancel.isEnabled():
            raise AssertionError(
                "Cancel calibration did not call the Orb service and leave the active UI state."
            )
        eye_settings_orb.calibration.update(
            {
                "state": "calibrated",
                "message": "Good gaze calibration is active.",
                "active": False,
                "quality": "Good",
                "average_error_px": 18.4,
                "completed_at": "2026-07-16T12:00:00+02:00",
            }
        )
        live_settings_controller._refresh_eye_tracking_status()
        if not calibration_reset.isEnabled() or "Good" not in calibration_result.text():
            raise AssertionError("A saved calibration is not presented as resettable with its quality.")
        calibration_reset.click()
        qt_app.processEvents()
        if eye_settings_orb.calls != ["start", "cancel", "reset"]:
            raise AssertionError(
                f"Reset calibration did not call the Orb service: {eye_settings_orb.calls!r}"
            )

        clearance_checkbox = eye_settings_card.findChild(
            QtWidgets.QCheckBox,
            "companion_orb_eye_tracking_pointer_clearance_checkbox",
        )
        clearance_distance = eye_settings_card.findChild(
            QtWidgets.QWidget,
            "companion_orb_eye_tracking_pointer_clearance_distance_slider",
        )
        clearance_timeout = eye_settings_card.findChild(
            QtWidgets.QWidget,
            "companion_orb_eye_tracking_pointer_clearance_timeout_slider",
        )
        clearance_status = eye_settings_card.findChild(
            QtWidgets.QLabel,
            "companion_orb_eye_tracking_pointer_clearance_status_label",
        )
        if (
            clearance_checkbox is None
            or clearance_checkbox.isChecked()
            or clearance_distance is None
            or clearance_timeout is None
            or clearance_status is None
            or live_settings_controller._controls.get(
                "companion_orb_eye_tracking_pointer_clearance_enabled"
            )
            is not clearance_checkbox
            or live_settings_controller._controls.get(
                "companion_orb_eye_tracking_pointer_clearance_distance_px"
            )
            is not clearance_distance
            or live_settings_controller._controls.get(
                "companion_orb_eye_tracking_pointer_clearance_timeout_seconds"
            )
            is not clearance_timeout
        ):
            raise AssertionError("Pointer Clearance controls are not correctly bound.")
        clearance_checkbox.setChecked(True)
        clearance_distance.slider.setValue(220)
        clearance_timeout.slider.setValue(12)
        qt_app.processEvents()
        if (
            isolated_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_enabled"
            )
            is not True
            or isolated_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_distance_px"
            )
            != 220
            or isolated_runtime_config.get(
                "companion_orb_eye_tracking_pointer_clearance_timeout_seconds"
            )
            != 12
        ):
            raise AssertionError(
                "Pointer Clearance controls did not update live runtime settings."
            )

        expand_checkbox.setChecked(False)
        qt_app.processEvents()
        if isolated_runtime_config.get(expand_setting_key) is not False:
            raise AssertionError("Toggling expanded Read text did not update the live runtime setting.")
        exported_expand_session = live_settings_controller.export_session_state()
        if exported_expand_session.get(expand_setting_key) is not False:
            raise AssertionError("Expanded Read text was not exported with the Companion Orb session.")
        test_update_runtime_config(expand_setting_key, True)
        live_settings_controller.refresh_from_runtime()
        if not expand_checkbox.isChecked():
            raise AssertionError("Expanded Read text did not refresh from the live runtime setting.")
        live_settings_controller.import_session_state({expand_setting_key: False})
        if expand_checkbox.isChecked() or live_settings_controller.export_session_state().get(expand_setting_key) is not False:
            raise AssertionError("Expanded Read text did not restore from the Companion Orb session.")
    finally:
        if eye_settings_card is not None:
            eye_settings_card.close()
        if live_settings_controller is not None:
            live_settings_controller.shutdown()
        (
            base_settings_controller._runtime_config,
            base_settings_controller._update_runtime_config,
            settings_controller._runtime_config,
            settings_controller._update_runtime_config,
        ) = original_runtime_helpers
        qt_app.processEvents()

    mouse_boundary_menu = gaze_radial_menu.GazeRadialMenu()
    mouse_boundary_menu.setAttribute(QtCore.Qt.WA_DontShowOnScreen, True)
    mouse_boundary_menu.show_actions(
        gaze_radial_menu.MAIN_GAZE_ACTIONS,
        anchor=QtCore.QPoint(900, 600),
        dwell_ms=650,
        opacity=0.57,
        focus_beam_enabled=True,
    )
    qt_app.processEvents()
    assert_close(
        mouse_boundary_menu.menu_opacity,
        0.57,
        "The radial menu should retain its configured opacity",
    )
    assert_close(
        mouse_boundary_menu.windowOpacity(),
        0.57,
        "The radial menu should apply configured opacity at window level",
        tolerance=0.02,
    )
    if mouse_boundary_menu._buttons["action"].isEnabled():
        raise AssertionError("Action must be excluded from mouse and gaze selection while disabled.")
    reserved_center = QtCore.QPointF(
        mouse_boundary_menu.mapToGlobal(mouse_boundary_menu._buttons["action"].geometry().center())
    )
    if (
        mouse_boundary_menu._action_at_global_point(reserved_center) is not None
        or mouse_boundary_menu._mouse_action_at_global_point(reserved_center) is not None
    ):
        raise AssertionError("The disabled Action target accepted input before its option was enabled.")
    if not mouse_boundary_menu._is_over_button_global_point(reserved_center):
        raise AssertionError("The disabled Action target should absorb mouse clicks without closing the menu.")
    if not mouse_boundary_menu.focus_beam_enabled:
        raise AssertionError("The radial menu should retain its configured charging focus beam state.")
    geometry_before_visual_settings = {
        action_id: QtCore.QRect(button.geometry())
        for action_id, button in mouse_boundary_menu._buttons.items()
    }
    mouse_boundary_menu.set_menu_opacity(0.35)
    mouse_boundary_menu.set_focus_beam_enabled(False)
    geometry_after_visual_settings = {
        action_id: QtCore.QRect(button.geometry())
        for action_id, button in mouse_boundary_menu._buttons.items()
    }
    if geometry_after_visual_settings != geometry_before_visual_settings:
        raise AssertionError("Opacity or charging-beam settings changed radial gaze geometry.")
    mouse_boundary_menu.set_menu_opacity(0.57)
    mouse_boundary_menu.set_focus_beam_enabled(True)
    react_geometry = mouse_boundary_menu._buttons["react"].geometry()
    inside_points = (
        QtCore.QPoint(react_geometry.left(), react_geometry.center().y()),
        QtCore.QPoint(react_geometry.right(), react_geometry.center().y()),
        QtCore.QPoint(react_geometry.center().x(), react_geometry.top()),
        QtCore.QPoint(react_geometry.center().x(), react_geometry.bottom()),
    )
    outside_points = (
        QtCore.QPoint(react_geometry.left() - 1, react_geometry.center().y()),
        QtCore.QPoint(react_geometry.right() + 1, react_geometry.center().y()),
        QtCore.QPoint(react_geometry.center().x(), react_geometry.top() - 1),
        QtCore.QPoint(react_geometry.center().x(), react_geometry.bottom() + 1),
    )
    for local_point in inside_points:
        global_point = QtCore.QPointF(mouse_boundary_menu.mapToGlobal(local_point))
        if mouse_boundary_menu._mouse_action_at_global_point(global_point) != "react":
            raise AssertionError(f"Mouse boundary missed a point inside the real button: {local_point!r}")
    for local_point in outside_points:
        global_point = QtCore.QPointF(mouse_boundary_menu.mapToGlobal(local_point))
        if mouse_boundary_menu._mouse_action_at_global_point(global_point) is not None:
            raise AssertionError(f"Mouse boundary accepted a point outside the real button: {local_point!r}")
        if mouse_boundary_menu._action_at_global_point(global_point) != "react":
            raise AssertionError("The gaze-only expansion should remain active outside the mouse button.")
    mouse_boundary_menu.close()
    mouse_boundary_menu.deleteLater()
    qt_app.processEvents()
    radial_selector = gaze_radial_menu.GazeSelectionPolicy(dwell_ms=650)
    progress, selected = radial_selector.ingest("react", now=20.0)
    assert_close(progress, 0.0, "Entering a gaze button should start its own timer")
    if selected is not None:
        raise AssertionError("A radial action must not select immediately.")
    progress, selected = radial_selector.ingest("react", now=20.64)
    if selected is not None or progress >= 1.0:
        raise AssertionError("A radial action selected before its configured gaze time.")
    progress, selected = radial_selector.ingest("voice", now=20.65)
    assert_close(progress, 0.0, "Moving to another radial button should restart the button timer")
    if selected is not None:
        raise AssertionError("Switching radial buttons must not carry over dwell progress.")
    if radial_selector.candidate_id != "voice" or radial_selector.progress != 0.0:
        raise AssertionError("Radial selector state should expose the active button and live progress.")
    progress, selected = radial_selector.ingest("voice", now=21.30)
    assert_close(progress, 1.0, "A completed radial button gaze should fill its progress")
    if selected != "voice":
        raise AssertionError(f"The held radial button was not selected: {selected!r}")
    _progress, repeated = radial_selector.ingest("voice", now=22.0)
    if repeated is not None:
        raise AssertionError("A held radial button must emit its selection only once.")
    reset_progress, reset_selection = radial_selector.ingest(None, now=22.1)
    assert_close(reset_progress, 0.0, "Looking away should clear radial button progress")
    if reset_selection is not None:
        raise AssertionError("Looking away from the radial menu should not select anything.")

    interrupted_selector = gaze_radial_menu.GazeSelectionPolicy(
        dwell_ms=650,
        sample_gap_seconds=0.5,
    )
    interrupted_selector.ingest("read_text", now=40.0)
    resumed_progress, resumed_selection = interrupted_selector.ingest("read_text", now=41.0)
    assert_close(resumed_progress, 0.0, "A radial-button gaze gap should restart its timer")
    if resumed_selection is not None:
        raise AssertionError("A gaze dropout must not select a radial action on resume.")
    interrupted_selector.ingest("read_text", now=41.4)
    _progress, resumed_selection = interrupted_selector.ingest("read_text", now=41.65)
    if resumed_selection != "read_text":
        raise AssertionError("A radial action should select after a fresh uninterrupted button gaze.")

    rearm_policy = eye_tracking.GazeFocusPolicy(dwell_ms=700, radius_px=40, smoothing=1.0)
    rearm_policy.ingest(100.0, 100.0, now=0.0)
    if not rearm_policy.ingest(100.0, 100.0, now=0.7).dwell_triggered:
        raise AssertionError("Initial dwell did not trigger.")
    left_focus = rearm_policy.ingest(220.0, 100.0, now=0.8)
    if left_focus.stable or left_focus.dwell_triggered:
        raise AssertionError("Leaving the focus radius should re-arm dwell detection.")
    if rearm_policy.ingest(220.0, 100.0, now=1.49).dwell_triggered:
        raise AssertionError("Re-armed focus triggered too early.")
    if not rearm_policy.ingest(220.0, 100.0, now=1.5).dwell_triggered:
        raise AssertionError("A new stable region should trigger after a full dwell.")

    mapped = eye_tracking.map_normalized_point((0.5, 0.25), (100, 200, 1920, 1080))
    assert_close(mapped[0], 1060.0, "Normalized X should map into the selected display")
    assert_close(mapped[1], 470.0, "Normalized Y should map into the selected display")
    clamped = eye_tracking.map_normalized_point((-0.5, 1.5), (100, 200, 1920, 1080))
    if clamped != (100.0, 1280.0):
        raise AssertionError(f"Normalized gaze should be clamped to display bounds: {clamped!r}")

    near_left = eye_tracking.orb_top_left_for_point(
        (100.0, 100.0),
        (0, 0, 1000, 600),
        orb_size=100,
        offset_px=80,
    )
    if near_left != (180.0, 50.0):
        raise AssertionError(f"Orb should sit to the right of left-side focus: {near_left!r}")
    calibrated = eye_tracking.orb_top_left_for_point(
        (100.0, 100.0),
        (0, 0, 1000, 600),
        orb_size=100,
        offset_px=80,
        offset_x_px=-100,
        offset_y_px=25,
    )
    if calibrated != (80.0, 75.0):
        raise AssertionError(f"Eye-tracking X/Y calibration offsets were not applied: {calibrated!r}")
    near_right = eye_tracking.orb_top_left_for_point(
        (950.0, 500.0),
        (0, 0, 1000, 600),
        orb_size=100,
        offset_px=80,
    )
    if near_right != (770.0, 450.0):
        raise AssertionError(f"Orb should switch sides near the right edge: {near_right!r}")

    if eye_tracking.signature_distance(0b0000, 0b1011) != 3:
        raise AssertionError("Visual signature distance should use Hamming distance.")
    from PIL import Image

    solid_hash = eye_tracking.average_image_hash(Image.new("RGB", (16, 16), "black"))
    bright_solid_hash = eye_tracking.average_image_hash(Image.new("RGB", (16, 16), "white"))
    if eye_tracking.signature_distance(solid_hash, bright_solid_hash) < 8:
        raise AssertionError("Visual signature should distinguish a meaningful uniform brightness transition.")
    split_image = Image.new("RGB", (16, 16), "black")
    for x in range(8, 16):
        for y in range(16):
            split_image.putpixel((x, y), (255, 255, 255))
    split_hash = eye_tracking.average_image_hash(split_image)
    if solid_hash == split_hash or eye_tracking.signature_distance(solid_hash, split_hash) < 16:
        raise AssertionError("Average image hash should distinguish a substantial visual change.")
    gate = eye_tracking.GazeReactionGate(cooldown_seconds=45.0, minimum_signature_distance=8)
    if not gate.accept(0x0000, now=0.0, meaningful=True):
        raise AssertionError("The first meaningful visual focus should be accepted.")
    if gate.accept(0xFFFF, now=10.0, meaningful=True):
        raise AssertionError("Reaction cooldown should reject an early changed focus.")
    if gate.accept(0x0000, now=46.0, meaningful=True):
        raise AssertionError("An unchanged focus should not be accepted after cooldown.")
    if not gate.accept(0xFFFF, now=46.0, meaningful=True):
        raise AssertionError("A meaningfully changed focus should be accepted after cooldown.")
    if not gate.accept(0xFFFF, now=46.1, meaningful=True, force=True):
        raise AssertionError("An explicit manual reaction should bypass automatic gating.")

    with tempfile.TemporaryDirectory(prefix="nc-orb-eye-") as temp_dir:
        root = Path(temp_dir)
        explicit = root / "explicit" / "tobii_stream_engine.dll"
        explicit.parent.mkdir(parents=True)
        explicit.write_bytes(b"test")
        found = eye_tracking.find_stream_engine_dll(str(explicit), environ={}, search_roots=[])
        if found != explicit.resolve():
            raise AssertionError(f"Explicit Stream Engine DLL was not preferred: {found!r}")
        explicit.unlink()

        environment_dll = root / "environment" / "tobii_stream_engine.dll"
        environment_dll.parent.mkdir(parents=True)
        environment_dll.write_bytes(b"test")
        found = eye_tracking.find_stream_engine_dll(
            "",
            environ={"TOBII_STREAM_ENGINE_DLL": str(environment_dll)},
            search_roots=[],
        )
        if found != environment_dll.resolve():
            raise AssertionError(f"Environment Stream Engine DLL was not discovered: {found!r}")
        environment_dll.unlink()

        install_dll = root / "Tobii" / "runtime" / "tobii_stream_engine.dll"
        install_dll.parent.mkdir(parents=True)
        install_dll.write_bytes(b"test")
        found = eye_tracking.find_stream_engine_dll("", environ={}, search_roots=[root])
        if found != install_dll.resolve():
            raise AssertionError(f"Installed Stream Engine DLL was not discovered: {found!r}")

    class FakeSession:
        def __init__(self, readings):
            self.readings = list(readings)
            self.closed = False

        def read_sample(self, _timeout_seconds: float):
            if not self.readings:
                time.sleep(0.005)
                return None
            reading = self.readings.pop(0)
            if isinstance(reading, BaseException):
                raise reading
            return reading

        def close(self) -> None:
            self.closed = True

    statuses: list[str] = []
    samples: list[tuple[float, float]] = []
    sample_received = threading.Event()
    sessions = [
        FakeSession(
            [
                None,
                (float("nan"), 0.5),
                (1.2, 0.5),
                (0.25, 0.75),
                (0.4, 0.6),
                eye_tracking.StreamEngineDisconnected("test disconnect"),
            ]
        )
    ]
    callback_attempts = 0

    def on_sample(x: float, y: float) -> None:
        nonlocal callback_attempts
        callback_attempts += 1
        if callback_attempts == 1:
            raise RuntimeError("test callback failure")
        samples.append((x, y))
        sample_received.set()

    def session_factory(_dll_path: Path):
        if sessions:
            return sessions.pop(0)
        raise eye_tracking.StreamEngineNoDevice("test no device")

    provider = eye_tracking.TobiiStreamEngineProvider(
        on_sample=on_sample,
        on_status=lambda code, _message: statuses.append(code),
        session_factory=session_factory,
        dll_resolver=lambda _path: Path("C:/test/tobii_stream_engine.dll"),
        retry_seconds=0.01,
    )
    if not provider.start(""):
        raise AssertionError("Provider should start its worker thread.")
    if not sample_received.wait(1.0):
        provider.stop()
        raise AssertionError(f"Provider did not deliver a valid sample; statuses={statuses!r}")
    expected_dll_path = str(Path("C:/test/tobii_stream_engine.dll"))
    if provider.resolved_dll_path != expected_dll_path:
        raise AssertionError(
            "Provider should expose the Stream Engine DLL selected by automatic discovery: "
            f"expected={expected_dll_path!r}, actual={provider.resolved_dll_path!r}"
        )
    started_at = time.monotonic()
    provider.stop(timeout_seconds=0.5)
    if time.monotonic() - started_at > 0.75:
        raise AssertionError("Provider shutdown should be bounded.")
    if provider.is_running:
        raise AssertionError("Provider thread should be stopped.")
    if samples != [(0.4, 0.6)]:
        raise AssertionError(f"Provider should filter invalid samples and isolate callback errors: {samples!r}")
    if "connected" not in statuses:
        raise AssertionError(f"Provider did not report a connected state: {statuses!r}")
    if "reconnecting" not in statuses:
        raise AssertionError(f"Provider did not report a reconnecting state: {statuses!r}")
    if provider.status_code != "off":
        raise AssertionError(f"Stopped provider should report off, got {provider.status_code!r}.")

    blocking_entered = threading.Event()
    blocking_release = threading.Event()

    class BlockingSession:
        def __init__(self):
            self.closed = False

        def read_sample(self, _timeout_seconds: float):
            blocking_entered.set()
            blocking_release.wait(1.0)
            return None

        def close(self) -> None:
            self.closed = True

    blocking_session = BlockingSession()
    blocking_provider = eye_tracking.TobiiStreamEngineProvider(
        on_sample=lambda _x, _y: None,
        session_factory=lambda _dll_path: blocking_session,
        dll_resolver=lambda _path: Path("C:/test/tobii_stream_engine.dll"),
        retry_seconds=0.01,
    )
    blocking_provider.start("")
    if not blocking_entered.wait(1.0):
        blocking_release.set()
        blocking_provider.stop(timeout_seconds=0.2)
        raise AssertionError("Blocking provider test did not enter its native callback wait.")
    stopping_started_at = time.monotonic()
    blocking_provider.stop(timeout_seconds=0.0)
    if time.monotonic() - stopping_started_at > 0.1:
        raise AssertionError("Non-blocking provider stop stalled the caller.")
    if blocking_provider.status_code != "stopping" or not blocking_provider.is_running:
        raise AssertionError("Provider should remain Stopping while a native callback wait is still active.")
    blocking_release.set()
    blocking_deadline = time.monotonic() + 1.0
    while blocking_provider.is_running and time.monotonic() < blocking_deadline:
        time.sleep(0.005)
    if blocking_provider.is_running or not blocking_session.closed or blocking_provider.status_code != "off":
        raise AssertionError(
            "Provider did not close its native session after the callback wait finished: "
            f"running={blocking_provider.is_running!r}, closed={blocking_session.closed!r}, "
            f"status={blocking_provider.status_code!r}"
        )

    missing_statuses: list[str] = []
    missing_provider = eye_tracking.TobiiStreamEngineProvider(
        on_sample=lambda _x, _y: None,
        on_status=lambda code, _message: missing_statuses.append(code),
        dll_resolver=lambda _path: None,
        retry_seconds=0.01,
    )
    missing_provider.start("")
    deadline = time.monotonic() + 1.0
    while missing_provider.is_running and time.monotonic() < deadline:
        time.sleep(0.005)
    missing_provider.stop(timeout_seconds=0.2)
    if "no_dll" not in missing_statuses:
        raise AssertionError(f"Missing Stream Engine DLL should be actionable: {missing_statuses!r}")

    class FakeNativeFunction:
        def __init__(self, callback):
            self.callback = callback
            self.argtypes = None
            self.restype = None

        def __call__(self, *args):
            return self.callback(*args)

    class FakeStreamEngineDll:
        def __init__(self):
            self.calls: list[str] = []
            self.gaze_callback = None
            self.tobii_get_api_version = FakeNativeFunction(self._get_api_version)
            self.tobii_api_create = FakeNativeFunction(self._api_create)
            self.tobii_enumerate_local_device_urls = FakeNativeFunction(self._enumerate_urls)
            self.tobii_device_create = FakeNativeFunction(self._device_create)
            self.tobii_gaze_point_subscribe = FakeNativeFunction(self._subscribe)
            self.tobii_wait_for_callbacks = FakeNativeFunction(self._wait_for_callbacks)
            self.tobii_device_process_callbacks = FakeNativeFunction(self._process_callbacks)
            self.tobii_gaze_point_unsubscribe = FakeNativeFunction(self._unsubscribe)
            self.tobii_device_destroy = FakeNativeFunction(self._destroy_device)
            self.tobii_api_destroy = FakeNativeFunction(self._destroy_api)

        def _get_api_version(self, versions):
            self.calls.append("version")
            versions[0] = 4
            versions[1] = 0
            versions[2] = 0
            versions[3] = 0
            return 0

        def _api_create(self, output, _alloc, _free):
            self.calls.append("api_create")
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(101)
            return 0

        def _enumerate_urls(self, api, callback, context):
            self.calls.append("enumerate")
            if int(api.value or 0) != 101:
                raise AssertionError(f"Unexpected fake API handle: {api!r}")
            callback(b"fake://tobii-4c", context)
            return 0

        def _device_create(self, api, url, field_of_use, output):
            self.calls.append("device_create")
            if int(api.value or 0) != 101 or url != b"fake://tobii-4c" or int(field_of_use) != 1:
                raise AssertionError(
                    f"Unexpected Stream Engine v4 device-create arguments: {api!r}, {url!r}, {field_of_use!r}"
                )
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(202)
            return 0

        def _subscribe(self, device, callback, _context):
            self.calls.append("subscribe")
            if int(device.value or 0) != 202:
                raise AssertionError(f"Unexpected fake device handle: {device!r}")
            self.gaze_callback = callback
            return 0

        def _wait_for_callbacks(self, device_count, devices):
            self.calls.append("wait")
            if int(device_count) != 1 or int(devices[0] or 0) != 202:
                raise AssertionError(f"Unexpected Stream Engine callback wait: {device_count!r}, {devices[0]!r}")
            return 0

        def _process_callbacks(self, device):
            self.calls.append("process")
            if int(device.value or 0) != 202 or self.gaze_callback is None:
                raise AssertionError("Stream Engine callback processing was not initialized.")
            gaze = eye_tracking._TobiiGazePoint()
            gaze.validity = eye_tracking._CtypesStreamEngineSession.TOBII_VALIDITY_VALID
            gaze.position_xy[0] = 0.375
            gaze.position_xy[1] = 0.625
            self.gaze_callback(ctypes.pointer(gaze), None)
            return 0

        def _unsubscribe(self, _device):
            self.calls.append("unsubscribe")
            return 0

        def _destroy_device(self, _device):
            self.calls.append("device_destroy")
            return 0

        def _destroy_api(self, _api):
            self.calls.append("api_destroy")
            return 0

    fake_dll = FakeStreamEngineDll()
    original_cdll = eye_tracking.ctypes.CDLL
    native_session = None
    eye_tracking.ctypes.CDLL = lambda _path: fake_dll
    try:
        native_session = eye_tracking._CtypesStreamEngineSession(Path("C:/test/tobii_stream_engine.dll"))
        native_sample = native_session.read_sample(0.25)
        if native_sample != (0.375, 0.625):
            raise AssertionError(f"Native gaze callback was decoded incorrectly: {native_sample!r}")
    finally:
        if native_session is not None:
            native_session.close()
        eye_tracking.ctypes.CDLL = original_cdll
    expected_native_calls = {
        "version",
        "api_create",
        "enumerate",
        "device_create",
        "subscribe",
        "wait",
        "process",
        "unsubscribe",
        "device_destroy",
        "api_destroy",
    }
    if not expected_native_calls.issubset(set(fake_dll.calls)):
        raise AssertionError(f"Stream Engine adapter skipped native lifecycle calls: {fake_dll.calls!r}")

    from PIL import ImageGrab
    from addons.companion_orb_overlay.companion_orb.companion_orb_controller import (
        CompanionOrbController,
        _eye_tracking_context_prompt,
    )
    from addons.companion_orb_overlay.companion_orb.external_runtime_client import (
        ExternalOrbRuntimeClient,
    )
    from addons.companion_orb_overlay.companion_orb import external_runtime_client as external_client_module

    for method_name in (
        "start_eye_tracking_calibration",
        "cancel_eye_tracking_calibration",
        "reset_eye_tracking_calibration",
    ):
        if not hasattr(CompanionOrbController, method_name):
            raise AssertionError(f"Companion Orb controller is missing {method_name}().")

    calibration_samples: list[tuple[tuple[float, float], float]] = []
    calibrating_controller = type("CalibratingGazeController", (), {})()
    calibrating_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
    }
    calibrating_controller._eye_tracking_orb_active = lambda: True
    calibrating_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1280.0, 720.0)
    calibrating_controller._eye_tracking_calibration_active = True
    calibrating_controller._collect_eye_tracking_calibration_sample = (
        lambda point, *, now: calibration_samples.append(
            ((float(point[0]), float(point[1])), float(now))
        )
    )
    calibrating_controller._calibrate_eye_tracking_point = (
        lambda _point: (_ for _ in ()).throw(
            AssertionError("Active calibration must collect raw mapped samples before applying a transform.")
        )
    )
    calibrating_controller._eye_tracking_policy = type(
        "ForbiddenCalibrationPolicy",
        (),
        {
            "ingest": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("Active calibration must pause normal gaze policy ingestion.")
            )
        },
    )()
    CompanionOrbController._handle_eye_tracking_sample(
        calibrating_controller,
        0.25,
        0.25,
    )
    if len(calibration_samples) != 1 or calibration_samples[0][0] != (320.0, 180.0):
        raise AssertionError(
            "Calibration did not intercept the raw mapped gaze sample: "
            f"{calibration_samples!r}"
        )

    class CalibratedSamplePolicy:
        def __init__(self):
            self.calls: list[tuple[float, float]] = []

        def ingest(self, x: float, y: float, *, now: float):
            self.calls.append((float(x), float(y)))
            return eye_tracking.GazeDecision(
                point=(float(x), float(y)),
                stable=True,
                dwell_triggered=False,
            )

    calibrated_policy = CalibratedSamplePolicy()
    calibrated_targets: list[tuple[float, float]] = []
    calibrated_controller = type("CalibratedSampleController", (), {})()
    calibrated_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_reaction_mode": "off",
        "companion_orb_eye_tracking_long_gaze_enabled": False,
    }
    calibrated_controller._eye_tracking_orb_active = lambda: True
    calibrated_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1280.0, 720.0)
    calibrated_controller._eye_tracking_calibration_active = False
    calibrated_controller._calibrate_eye_tracking_point = (
        lambda point: (float(point[0]) + 100.0, float(point[1]) - 50.0)
    )
    calibrated_controller._eye_tracking_policy = calibrated_policy
    calibrated_controller._gaze_radial_menu = None
    calibrated_controller._blink_gesture_detector = None
    calibrated_controller._eye_tracking_latest_point = None
    calibrated_controller._eye_tracking_latest_at = 0.0
    calibrated_controller._eye_tracking_stable_point = None
    calibrated_controller._set_eye_tracking_interaction_target = (
        lambda point, *, duration_seconds: calibrated_targets.append(
            (float(point[0]), float(point[1]))
        )
    )
    calibrated_controller._set_gaze_timer_state = lambda *_args, **_kwargs: None
    calibrated_controller._request_eye_tracking_reaction = lambda _force: None
    CompanionOrbController._handle_eye_tracking_sample(
        calibrated_controller,
        0.25,
        0.25,
    )
    if calibrated_policy.calls != [(420.0, 130.0)] or calibrated_targets != [(420.0, 130.0)]:
        raise AssertionError(
            "Display calibration must run before smoothing, dwell, and Orb side placement: "
            f"policy={calibrated_policy.calls!r}, targets={calibrated_targets!r}"
        )

    calibration_off_controller = type("CalibrationOffController", (), {})()
    calibration_off_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "off",
    }
    calibration_off_controller._eye_tracking_orb_active = lambda: True
    calibration_off_result = CompanionOrbController.start_eye_tracking_calibration(
        calibration_off_controller
    )
    if calibration_off_result.get("ok") is not False or "off" not in str(
        calibration_off_result.get("error") or ""
    ).lower():
        raise AssertionError(
            f"Starting calibration while eye tracking is off should fail clearly: {calibration_off_result!r}"
        )

    calibration_reset_saves: list[tuple[str, object]] = []
    calibration_reset_reapplies: list[str] = []
    calibration_reset_controller = type("CalibrationResetController", (), {})()
    calibration_reset_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_calibration": {
            "version": gaze_calibration.CALIBRATION_SCHEMA_VERSION,
        },
    }
    calibration_reset_controller._eye_tracking_calibration_active = False
    calibration_reset_controller._eye_tracking_calibration_overlay = None
    calibration_reset_controller._eye_tracking_calibration_status = {}
    calibration_reset_controller._eye_tracking_policy = type(
        "CalibrationResetPolicy",
        (),
        {"reset": lambda self: None},
    )()
    calibration_reset_controller._save_runtime_setting = (
        lambda key, value: calibration_reset_saves.append((str(key), value))
    )
    calibration_reset_controller._reapply_eye_tracking_interaction_target = (
        lambda: calibration_reset_reapplies.append("reapplied")
    )
    reset_result = CompanionOrbController.reset_eye_tracking_calibration(
        calibration_reset_controller
    )
    if reset_result.get("ok") is not True:
        raise AssertionError(f"Reset calibration failed: {reset_result!r}")
    if calibration_reset_controller._last_runtime_config.get(
        "companion_orb_eye_tracking_calibration"
    ) != {}:
        raise AssertionError("Reset calibration did not restore the identity transform.")
    if calibration_reset_saves != [("companion_orb_eye_tracking_calibration", {})]:
        raise AssertionError(
            f"Reset calibration persisted unexpected data: {calibration_reset_saves!r}"
        )
    if calibration_reset_reapplies != ["reapplied"]:
        raise AssertionError("Reset calibration did not rebuild the live Orb target.")

    context_prompt_markers = {
        "react": "React",
        "describe": "Describe",
        "explain": "Explain",
        "summarize": "Summarize",
    }
    context_prompts: dict[str, str] = {}
    for action_id, marker in context_prompt_markers.items():
        prompt = _eye_tracking_context_prompt(action_id)
        context_prompts[action_id] = prompt
        if marker.lower() not in prompt.lower():
            raise AssertionError(f"Context action {action_id!r} did not receive a specific prompt: {prompt!r}")
        if "gaze" in prompt.lower() or "eye-track" in prompt.lower():
            raise AssertionError(f"Context action {action_id!r} leaked eye-tracking details: {prompt!r}")
    if len(set(context_prompts.values())) != len(context_prompts):
        raise AssertionError(f"Radial context actions must not collapse to one prompt: {context_prompts!r}")

    dispatched_context_actions: list[tuple[str, tuple[float, float]]] = []
    dispatched_read_text_points: list[tuple[float, float]] = []
    dispatch_controller = type("RadialContextDispatchController", (), {})()
    dispatch_controller._gaze_radial_context_point = None
    dispatch_controller._gaze_radial_payloads = {}
    dispatch_controller._gaze_voice_page = 0
    dispatch_controller._eye_tracking_status_message = ""

    def dismiss_context_menu() -> None:
        dispatch_controller._gaze_radial_context_point = None

    dispatch_controller._dismiss_gaze_radial_menu = dismiss_context_menu
    dispatch_controller._queue_gaze_radial_context_action = (
        lambda action_id, point: dispatched_context_actions.append(
            (str(action_id), (float(point[0]), float(point[1])))
        )
        or {"ok": True, "queued": True}
    )
    dispatch_controller._request_eye_tracking_reaction = (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Radial context actions must use the retryable user-action dispatcher.")
        )
    )
    dispatch_controller._start_gaze_read_text = (
        lambda *, point=None: dispatched_read_text_points.append(
            (float(point[0]), float(point[1]))
        )
        or {"ok": True, "queued": True}
    )
    expected_context_point = (640.0, 360.0)
    dispatch_controller._gaze_radial_context_point = expected_context_point
    CompanionOrbController._handle_gaze_radial_action(dispatch_controller, "read_text")
    if dispatched_read_text_points != [expected_context_point]:
        raise AssertionError(
            "Radial Read text did not preserve and dispatch the original visual context: "
            f"{dispatched_read_text_points!r}"
        )
    for action_id in ("react", "describe", "explain", "summarize"):
        dispatch_controller._gaze_radial_context_point = expected_context_point
        CompanionOrbController._handle_gaze_radial_action(dispatch_controller, action_id)
    expected_dispatches = [
        (action_id, expected_context_point)
        for action_id in ("react", "describe", "explain", "summarize")
    ]
    if dispatched_context_actions != expected_dispatches:
        raise AssertionError(
            "Each radial context action must preserve and dispatch the original visual context: "
            f"{dispatched_context_actions!r}"
        )

    scheduled_context_retries: list[tuple[int, object]] = []
    context_retry_requests: list[tuple[bool, str, tuple[float, float]]] = []
    context_retry_events: list[tuple[str, dict]] = []
    retry_controller = type("RadialContextRetryController", (), {})()
    retry_controller._gaze_context_dispatch_generation = 0
    retry_controller._eye_tracking_reaction_shutting_down = False
    retry_controller._eye_tracking_status_message = ""
    retry_controller._schedule_gaze_context_retry = (
        lambda delay_ms, callback: scheduled_context_retries.append((int(delay_ms), callback))
    )
    retry_controller._debug_event = (
        lambda event, **fields: context_retry_events.append((str(event), dict(fields)))
    )

    def request_context_retry(force=False, *, action_id="react", point_override=None):
        point = (float(point_override[0]), float(point_override[1]))
        context_retry_requests.append((bool(force), str(action_id), point))
        if len(context_retry_requests) == 1:
            return {
                "ok": False,
                "busy": True,
                "error": "An eye-tracker visual reaction is already being prepared.",
            }
        return {"ok": True, "queued": True}

    retry_controller._request_eye_tracking_reaction = request_context_retry
    retry_controller._try_gaze_radial_context_action = (
        lambda action_id, point, generation, attempt: CompanionOrbController._try_gaze_radial_context_action(
            retry_controller,
            action_id,
            point,
            generation,
            attempt,
        )
    )
    retry_result = CompanionOrbController._queue_gaze_radial_context_action(
        retry_controller,
        "describe",
        expected_context_point,
    )
    if retry_result != {"ok": True, "queued": True, "waiting": True}:
        raise AssertionError(f"A busy forced action should remain queued for retry: {retry_result!r}")
    if len(scheduled_context_retries) != 1 or scheduled_context_retries[0][0] != 50:
        raise AssertionError(f"Busy radial action used the wrong retry schedule: {scheduled_context_retries!r}")
    scheduled_context_retries.pop(0)[1]()
    if context_retry_requests != [
        (True, "describe", expected_context_point),
        (True, "describe", expected_context_point),
    ]:
        raise AssertionError(f"Busy radial action did not retry exactly once with preserved context: {context_retry_requests!r}")
    if retry_controller._eye_tracking_status_message:
        raise AssertionError(f"A successful retry left an error status: {retry_controller._eye_tracking_status_message!r}")
    if any("point" in fields or "bounds" in fields for _event, fields in context_retry_events):
        raise AssertionError(f"Radial action retry diagnostics leaked visual coordinates: {context_retry_events!r}")

    def make_pending_context_controller():
        pending_controller = type("PendingRadialContextController", (), {})()
        pending_controller._gaze_context_dispatch_generation = 0
        pending_controller._eye_tracking_reaction_shutting_down = False
        pending_controller._eye_tracking_status_message = ""
        pending_controller.requests = []
        pending_controller.callbacks = []
        pending_controller._debug_event = lambda *_args, **_kwargs: None
        pending_controller._schedule_gaze_context_retry = (
            lambda _delay_ms, callback: pending_controller.callbacks.append(callback)
        )
        pending_controller._request_eye_tracking_reaction = (
            lambda force=False, *, action_id="react", point_override=None: pending_controller.requests.append(
                (bool(force), str(action_id), (float(point_override[0]), float(point_override[1])))
            )
            or {"ok": False, "busy": True, "error": "busy"}
        )
        pending_controller._try_gaze_radial_context_action = (
            lambda action_id, point, generation, attempt: CompanionOrbController._try_gaze_radial_context_action(
                pending_controller,
                action_id,
                point,
                generation,
                attempt,
            )
        )
        return pending_controller

    latest_controller = make_pending_context_controller()
    CompanionOrbController._queue_gaze_radial_context_action(
        latest_controller,
        "react",
        expected_context_point,
    )
    stale_callback = latest_controller.callbacks[-1]
    CompanionOrbController._queue_gaze_radial_context_action(
        latest_controller,
        "summarize",
        expected_context_point,
    )
    latest_callback = latest_controller.callbacks[-1]
    stale_callback()
    if [request[1] for request in latest_controller.requests] != ["react", "summarize"]:
        raise AssertionError(f"A superseded radial action retried unexpectedly: {latest_controller.requests!r}")
    latest_callback()
    if [request[1] for request in latest_controller.requests] != ["react", "summarize", "summarize"]:
        raise AssertionError(f"The newest radial action did not retain retry ownership: {latest_controller.requests!r}")

    reset_controller = make_pending_context_controller()
    reset_controller._eye_tracking_policy = type("ResetPolicy", (), {"reset": lambda self: None})()
    reset_controller._eye_tracking_latest_point = expected_context_point
    reset_controller._eye_tracking_latest_at = time.monotonic()
    reset_controller._eye_tracking_stable_point = expected_context_point
    reset_controller._eye_tracking_interaction_source_point = expected_context_point
    reset_controller._eye_tracking_interaction_target = object()
    reset_controller._eye_tracking_interaction_until = time.monotonic() + 5.0
    reset_controller._eye_tracking_last_external_target = object()
    reset_controller._eye_tracking_last_external_sent_at = time.monotonic()
    reset_controller._gaze_radial_menu = None
    reset_controller._gaze_radial_menu_open = True
    reset_controller._gaze_radial_context_point = expected_context_point
    reset_controller._gaze_radial_payloads = {"react": object()}
    reset_controller._set_gaze_timer_state = lambda *_args, **_kwargs: None
    reset_controller._send_external_runtime = lambda _payload: None
    CompanionOrbController._queue_gaze_radial_context_action(
        reset_controller,
        "react",
        expected_context_point,
    )
    reset_callback = reset_controller.callbacks[-1]
    CompanionOrbController._clear_eye_tracking_state(reset_controller, send_external=False)
    reset_callback()
    if len(reset_controller.requests) != 1:
        raise AssertionError(f"Eye-tracking reset did not cancel a pending radial action: {reset_controller.requests!r}")

    shutdown_controller = make_pending_context_controller()
    CompanionOrbController._queue_gaze_radial_context_action(
        shutdown_controller,
        "explain",
        expected_context_point,
    )
    shutdown_callback = shutdown_controller.callbacks[-1]
    shutdown_controller._eye_tracking_reaction_shutting_down = True
    shutdown_callback()
    if len(shutdown_controller.requests) != 1:
        raise AssertionError(
            f"Companion Orb shutdown did not cancel a pending radial action: {shutdown_controller.requests!r}"
        )

    class FollowWhileDwellingPolicy:
        def __init__(self):
            self.calls = 0

        def ingest(self, _x: float, _y: float, *, now: float):
            self.calls += 1
            return eye_tracking.GazeDecision(
                point=(320.0 + self.calls * 40.0, 240.0),
                stable=self.calls >= 2,
                dwell_triggered=self.calls == 2,
            )

    follow_while_dwelling_moves: list[tuple[tuple[float, float], float]] = []
    follow_while_dwelling_reactions: list[bool] = []
    follow_while_dwelling_controller = type("FollowWhileDwellingController", (), {})()
    follow_while_dwelling_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_reaction_mode": "meaningful",
    }
    follow_while_dwelling_controller._eye_tracking_policy = FollowWhileDwellingPolicy()
    follow_while_dwelling_controller._eye_tracking_orb_active = lambda: True
    follow_while_dwelling_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1280.0, 720.0)
    follow_while_dwelling_controller._set_eye_tracking_interaction_target = (
        lambda point, *, duration_seconds: follow_while_dwelling_moves.append(
            ((float(point[0]), float(point[1])), float(duration_seconds))
        )
    )
    follow_while_dwelling_controller._request_eye_tracking_reaction = (
        lambda force: follow_while_dwelling_reactions.append(bool(force))
    )
    follow_while_dwelling_controller._eye_tracking_latest_point = None
    follow_while_dwelling_controller._eye_tracking_latest_at = 0.0
    follow_while_dwelling_controller._eye_tracking_stable_point = None
    CompanionOrbController._handle_eye_tracking_sample(follow_while_dwelling_controller, 0.25, 0.33)
    if len(follow_while_dwelling_moves) != 1 or follow_while_dwelling_reactions:
        raise AssertionError(
            "Dwell Focus must follow a pre-dwell gaze sample without taking a snapshot: "
            f"moves={follow_while_dwelling_moves!r}, reactions={follow_while_dwelling_reactions!r}"
        )
    CompanionOrbController._handle_eye_tracking_sample(follow_while_dwelling_controller, 0.30, 0.33)
    if len(follow_while_dwelling_moves) != 2 or follow_while_dwelling_reactions != [False]:
        raise AssertionError(
            "Completing the dwell should retain gaze following and trigger exactly one automatic reaction: "
            f"moves={follow_while_dwelling_moves!r}, reactions={follow_while_dwelling_reactions!r}"
        )

    class StableDwellPolicy:
        def ingest(self, _x: float, _y: float, *, now: float):
            return eye_tracking.GazeDecision(
                point=(640.0, 360.0),
                stable=True,
                dwell_triggered=False,
            )

    dwell_target_calls: list[tuple[tuple[float, float], float]] = []
    dwell_controller = type("DwellController", (), {})()
    dwell_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_reaction_mode": "off",
    }
    dwell_controller._eye_tracking_policy = StableDwellPolicy()
    dwell_controller._eye_tracking_orb_active = lambda: True
    dwell_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1280.0, 720.0)
    dwell_controller._set_eye_tracking_interaction_target = (
        lambda point, *, duration_seconds: dwell_target_calls.append(
            ((float(point[0]), float(point[1])), float(duration_seconds))
        )
    )
    dwell_controller._eye_tracking_latest_point = None
    dwell_controller._eye_tracking_latest_at = 0.0
    dwell_controller._eye_tracking_stable_point = None
    CompanionOrbController._handle_eye_tracking_sample(dwell_controller, 0.5, 0.5)
    if len(dwell_target_calls) != 1 or dwell_target_calls[0][1] < 1.5:
        raise AssertionError(
            "Dwell Focus should retain a valid gaze target through brief tracker instability: "
            f"calls={dwell_target_calls!r}"
        )

    class LongGazePolicy:
        def ingest(self, _x: float, _y: float, *, now: float):
            return eye_tracking.GazeDecision(
                point=(720.0, 410.0),
                stable=True,
                dwell_triggered=False,
                hold_seconds=3.0,
                dwell_progress=1.0,
                long_dwell_triggered=True,
            )

    long_menu_calls: list[tuple[float, float]] = []
    long_timer_calls: list[tuple[bool, float]] = []
    long_target_calls: list[tuple[tuple[float, float], float]] = []
    long_controller = type("LongGazeController", (), {})()
    long_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_reaction_mode": "off",
        "companion_orb_eye_tracking_dwell_ms": 700,
        "companion_orb_eye_tracking_long_gaze_enabled": True,
        "companion_orb_eye_tracking_long_gaze_ms": 3000,
    }
    long_controller._eye_tracking_policy = LongGazePolicy()
    long_controller._eye_tracking_orb_active = lambda: True
    long_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1440.0, 900.0)
    long_controller._set_eye_tracking_interaction_target = (
        lambda point, *, duration_seconds, force_external_send=False: long_target_calls.append(
            ((float(point[0]), float(point[1])), float(duration_seconds))
        )
    )
    long_controller._set_gaze_timer_state = (
        lambda active, progress: long_timer_calls.append((bool(active), float(progress)))
    )
    long_controller._show_gaze_radial_main_menu = (
        lambda point: long_menu_calls.append((float(point[0]), float(point[1])))
    )
    long_controller._gaze_radial_menu = None
    long_controller._eye_tracking_latest_point = None
    long_controller._eye_tracking_latest_at = 0.0
    long_controller._eye_tracking_stable_point = None
    CompanionOrbController._handle_eye_tracking_sample(long_controller, 0.5, 0.5)
    if long_menu_calls != [(720.0, 410.0)]:
        raise AssertionError(f"A completed long gaze should open one radial menu: {long_menu_calls!r}")
    if not long_timer_calls or long_timer_calls[-1] != (True, 1.0):
        raise AssertionError(f"Long-gaze completion should fill the Orb timer tint: {long_timer_calls!r}")
    if not long_target_calls or long_target_calls[-1][1] < 8.0:
        raise AssertionError(f"Opening the radial menu should hold the Orb in place: {long_target_calls!r}")

    class MenuOpenPolicy:
        def ingest(self, _x: float, _y: float, *, now: float):
            raise AssertionError("Primary long-gaze policy must pause while selecting radial buttons.")

    class OpenRadialMenu:
        selection_candidate_id = "explain"
        selection_progress = 0.4

        def __init__(self):
            self.points: list[tuple[float, float]] = []

        def isVisible(self) -> bool:
            return True

        def feed_gaze(self, point, *, now: float):
            self.points.append((float(point.x()), float(point.y())))

    open_menu = OpenRadialMenu()
    open_menu_timer_calls: list[tuple[bool, float]] = []
    open_menu_controller = type("OpenMenuController", (), {})()
    open_menu_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_offset_x_px": -95,
        "companion_orb_eye_tracking_offset_y_px": 34,
    }
    open_menu_controller._eye_tracking_policy = MenuOpenPolicy()
    open_menu_controller._eye_tracking_orb_active = lambda: True
    open_menu_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1000.0, 800.0)
    open_menu_controller._gaze_radial_menu = open_menu
    open_menu_controller._eye_tracking_latest_point = (720.0, 410.0)
    open_menu_controller._eye_tracking_latest_at = time.monotonic()
    open_menu_controller._eye_tracking_stable_point = (720.0, 410.0)
    open_menu_controller._set_gaze_timer_state = (
        lambda active, progress: open_menu_timer_calls.append((bool(active), float(progress)))
    )
    CompanionOrbController._handle_eye_tracking_sample(open_menu_controller, 0.20, 0.25)
    if open_menu_controller._eye_tracking_latest_point != (720.0, 410.0):
        raise AssertionError("Radial button selection replaced the original visual context point.")
    if open_menu.points != [(200.0, 200.0)] or open_menu_timer_calls != [(True, 0.4)]:
        raise AssertionError(
            "Open radial menu should use raw mapped gaze independently of Orb placement offsets: "
            f"points={open_menu.points!r}, timers={open_menu_timer_calls!r}"
        )

    read_bounds_controller = type("ReadTextBoundsController", (), {})()
    read_base_bounds = [[400, 170, 640, 480]]
    read_screen_bounds = [[0.0, 0.0, 1920.0, 1080.0]]
    read_bounds_controller._last_runtime_config = {
        "companion_orb_eye_tracking_expand_read_text_area": False,
    }
    read_bounds_controller._eye_tracking_reaction_bounds = lambda _point: list(read_base_bounds[0])
    read_bounds_controller._eye_tracking_screen_bounds = lambda: tuple(read_screen_bounds[0])
    disabled_read_bounds = CompanionOrbController._eye_tracking_read_text_bounds(
        read_bounds_controller,
        (720.0, 410.0),
    )
    if disabled_read_bounds != [400, 170, 640, 480]:
        raise AssertionError(f"Disabled text expansion changed the existing crop: {disabled_read_bounds!r}")

    read_bounds_controller._last_runtime_config["companion_orb_eye_tracking_expand_read_text_area"] = True
    expanded_read_bounds = CompanionOrbController._eye_tracking_read_text_bounds(
        read_bounds_controller,
        (720.0, 410.0),
    )
    if expanded_read_bounds != [400, 170, 1280, 480]:
        raise AssertionError(f"Read text did not double its width toward the right: {expanded_read_bounds!r}")

    read_base_bounds[0] = [1200, 170, 640, 480]
    right_edge_bounds = CompanionOrbController._eye_tracking_read_text_bounds(
        read_bounds_controller,
        (1520.0, 410.0),
    )
    if right_edge_bounds != [640, 170, 1280, 480]:
        raise AssertionError(f"Right-edge Read text expansion was not clamped correctly: {right_edge_bounds!r}")
    if not (
        right_edge_bounds[0] <= read_base_bounds[0][0]
        and right_edge_bounds[0] + right_edge_bounds[2]
        >= read_base_bounds[0][0] + read_base_bounds[0][2]
    ):
        raise AssertionError("Right-edge expansion did not preserve the original gaze crop.")

    read_base_bounds[0] = [0, 170, 720, 480]
    read_screen_bounds[0] = [0.0, 0.0, 1000.0, 800.0]
    screen_limited_bounds = CompanionOrbController._eye_tracking_read_text_bounds(
        read_bounds_controller,
        (360.0, 410.0),
    )
    if screen_limited_bounds != [0, 170, 1000, 480]:
        raise AssertionError(f"Read text expansion exceeded the selected display: {screen_limited_bounds!r}")

    read_base_bounds[0] = [-700, 170, 640, 480]
    read_screen_bounds[0] = [-1920.0, 0.0, 1920.0, 1080.0]
    negative_origin_bounds = CompanionOrbController._eye_tracking_read_text_bounds(
        read_bounds_controller,
        (-380.0, 410.0),
    )
    if negative_origin_bounds != [-1280, 170, 1280, 480]:
        raise AssertionError(
            "Read text expansion did not clamp correctly on a negative-origin display: "
            f"{negative_origin_bounds!r}"
        )

    read_base_bounds[0] = [100, 170, 320, 240]
    read_screen_bounds[0] = [100.0, 0.0, 200.0, 800.0]
    narrow_screen_bounds = CompanionOrbController._eye_tracking_read_text_bounds(
        read_bounds_controller,
        (200.0, 290.0),
    )
    if narrow_screen_bounds != read_base_bounds[0]:
        raise AssertionError(
            "A display narrower than the existing crop must preserve the original Read text bounds: "
            f"{narrow_screen_bounds!r}"
        )

    gaze_read_calls: list[tuple[object, str, list[int], bool]] = []
    gaze_read_controller = type("GazeReadController", (), {})()
    gaze_read_controller._eye_tracking_latest_point = (720.0, 410.0)
    gaze_read_controller._eye_tracking_latest_at = time.monotonic()
    gaze_read_controller._eye_tracking_read_text_bounds = lambda _point: [400, 170, 1280, 480]
    gaze_read_controller._eye_tracking_reaction_bounds = lambda _point: (_ for _ in ()).throw(
        AssertionError("Read text must not call shared visual-reaction bounds directly.")
    )
    gaze_read_controller._begin_reading_job = lambda action_id: action_id == "gaze_read_text"
    gaze_read_controller._start_reading_worker = (
        lambda action, *, selected_text, bounds, private_bounds=False: gaze_read_calls.append(
            (action, str(selected_text), list(bounds), bool(private_bounds))
        )
    )
    read_result = CompanionOrbController._start_gaze_read_text(gaze_read_controller)
    if read_result.get("ok") is not True or len(gaze_read_calls) != 1:
        raise AssertionError(f"Gaze Read text did not enter the existing reading worker: {read_result!r}")
    read_action, initial_text, read_bounds, private_bounds = gaze_read_calls[0]
    if (
        getattr(read_action, "action_id", "") != "gaze_read_text"
        or initial_text
        or read_bounds != [400, 170, 1280, 480]
        or not private_bounds
    ):
        raise AssertionError(
            "Gaze Read text must reuse selected-area OCR/TTS without logging gaze-derived bounds: "
            f"{gaze_read_calls!r}"
        )

    controller_source = Path(
        ROOT_DIR / "addons" / "companion_orb_overlay" / "companion_orb" / "companion_orb_controller.py"
    ).read_text(encoding="utf-8")
    sync_provider_source = method_source(
        controller_source,
        "CompanionOrbController",
        "_sync_eye_tracking_provider",
    )
    if re.search(r"policy_key\s*=\s*\(\s*mode\s*,", sync_provider_source) is None:
        raise AssertionError("Tracking-mode changes must rebuild and clear the active gaze policy/menu.")
    controller_drift_source = method_source(controller_source, "CompanionOrbController", "_on_drift_tick")
    if controller_drift_source.index("eye_interaction_ready:") > controller_drift_source.index("comment_focus_ready:"):
        raise AssertionError("The embedded Orb must prioritize an active gaze target over stale comment/drop focus.")

    external_source = Path(
        ROOT_DIR / "addons" / "companion_orb_overlay" / "companion_orb" / "external_orb_runtime.py"
    ).read_text(encoding="utf-8")
    external_drift_source = method_source(external_source, "ExternalCompanionOrb", "_on_drift_tick")
    if external_drift_source.index("interaction_target_ready:") > external_drift_source.index("self._focus_ready():"):
        raise AssertionError("The external Orb must prioritize an active gaze target over stale comment/drop focus.")
    external_target_source = method_source(external_source, "ExternalCompanionOrb", "_set_interaction_target")
    if "self.return_timer.stop()" not in external_target_source:
        raise AssertionError("A new external gaze target must cancel pending return-home movement.")

    class SnapshotProvider:
        is_running = True
        status_code = "connected"
        status_message = "Tobii eye tracking is connected."
        resolved_dll_path = str(Path("C:/test/tobii_stream_engine.dll"))

    snapshot_controller = type("SnapshotController", (), {})()
    snapshot_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_pointer_clearance_enabled": True,
    }
    snapshot_controller._eye_tracking_status_code = "reaction_error"
    snapshot_controller._eye_tracking_status_message = "The visual comment could not be created."
    snapshot_controller._eye_tracking_provider = SnapshotProvider()
    snapshot_controller._eye_tracking_pointer_clearance_state = "avoiding"
    snapshot_controller._external_pointer_clearance_state = "clear"
    snapshot_controller._external_runtime_enabled = lambda: False
    status_snapshot = CompanionOrbController.eye_tracking_status(snapshot_controller)
    if status_snapshot.get("code") != "reaction_error":
        raise AssertionError("The existing eye-tracking status code contract should remain unchanged.")
    expected_snapshot_details = {
        "connection_code": "connected",
        "connection_message": "Tobii eye tracking is connected.",
        "dll_path": str(Path("C:/test/tobii_stream_engine.dll")),
        "running": True,
    }
    actual_snapshot_details = {key: status_snapshot.get(key) for key in expected_snapshot_details}
    if actual_snapshot_details != expected_snapshot_details:
        raise AssertionError(
            "Eye-tracking status should separate tracker connectivity from reaction errors: "
            f"expected={expected_snapshot_details!r}, actual={actual_snapshot_details!r}"
        )
    if status_snapshot.get("pointer_clearance") != {
        "enabled": True,
        "state": "avoiding",
    }:
        raise AssertionError(
            "Eye-tracking status did not expose aggregate Pointer Clearance state: "
            f"{status_snapshot.get('pointer_clearance')!r}"
        )

    class StoppingProvider:
        is_running = True

        def __init__(self):
            self.stop_timeouts: list[float] = []

        def stop(self, *, timeout_seconds: float = 1.5) -> None:
            self.stop_timeouts.append(float(timeout_seconds))

    stopping_controller = type("StoppingController", (), {})()
    stopping_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "off",
        "companion_orb_eye_tracking_reaction_mode": "meaningful",
        "companion_orb_eye_tracking_dwell_ms": 700,
        "companion_orb_eye_tracking_radius_px": 60,
        "companion_orb_eye_tracking_smoothing": 0.28,
        "companion_orb_eye_tracking_reaction_cooldown_seconds": 45,
        "companion_orb_eye_tracking_screen_index": -1,
        "companion_orb_eye_tracking_dll_path": "",
    }
    stopping_controller._eye_tracking_policy_key = (700, 60, 0.28)
    stopping_controller._eye_tracking_gate_key = (45, 8)
    stopping_controller._eye_tracking_reaction_lifecycle_key = (
        "off",
        True,
        "meaningful",
        "",
        -1,
    )
    stopping_controller._eye_tracking_reaction_lock = threading.Lock()
    stopping_controller._eye_tracking_reaction_generation = 0
    stopping_controller._eye_tracking_connection_key = None
    stopping_controller._eye_tracking_provider = StoppingProvider()
    stopping_controller._eye_tracking_status_code = "connected"
    stopping_controller._eye_tracking_status_message = "Tobii eye tracking is connected."
    stopping_controller._eye_tracking_orb_active = lambda: True
    stopping_controller._clear_eye_tracking_state = lambda *, send_external: None
    CompanionOrbController._sync_eye_tracking_provider(stopping_controller)
    if stopping_controller._eye_tracking_status_code != "stopping":
        raise AssertionError(
            "Eye tracking reported Off before its native worker stopped: "
            f"{stopping_controller._eye_tracking_status_code!r}"
        )
    if stopping_controller._eye_tracking_provider.stop_timeouts != [0.0]:
        raise AssertionError("Disabling eye tracking should request non-blocking provider shutdown.")

    class ManualModePolicy:
        def __init__(self):
            self.calls = 0

        def ingest(self, _x: float, _y: float, *, now: float):
            self.calls += 1
            return eye_tracking.GazeDecision(
                point=(640.0, 360.0),
                stable=True,
                dwell_triggered=True,
            )

    class ManualModeRadialMenu:
        selection_candidate_id = "react"
        selection_progress = 0.5

        def __init__(self):
            self.cancel_calls = 0
            self.feed_calls = 0
            self.visible = True

        def isVisible(self) -> bool:
            return self.visible

        def cancel(self) -> None:
            self.cancel_calls += 1
            self.visible = False

        def feed_gaze(self, _point, *, now: float) -> None:
            self.feed_calls += 1

    manual_moves: list[tuple] = []
    manual_reactions: list[bool] = []
    manual_controller = type("ManualModeController", (), {})()
    manual_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "manual",
        "companion_orb_eye_tracking_reaction_mode": "meaningful",
    }
    manual_policy = ManualModePolicy()
    manual_menu = ManualModeRadialMenu()
    manual_controller._eye_tracking_policy = manual_policy
    manual_controller._eye_tracking_orb_active = lambda: True
    manual_controller._eye_tracking_screen_bounds = lambda: (0.0, 0.0, 1280.0, 720.0)
    manual_controller._gaze_radial_menu = manual_menu
    manual_controller._set_gaze_timer_state = lambda _active, _progress: None
    manual_controller._set_eye_tracking_interaction_target = (
        lambda point, *, duration_seconds: manual_moves.append((point, duration_seconds))
    )
    manual_controller._request_eye_tracking_reaction = lambda force: manual_reactions.append(bool(force))
    manual_controller._eye_tracking_latest_point = None
    manual_controller._eye_tracking_latest_at = 0.0
    manual_controller._eye_tracking_stable_point = None
    CompanionOrbController._handle_eye_tracking_sample(manual_controller, 0.5, 0.5)
    if manual_menu.cancel_calls != 1 or manual_menu.feed_calls:
        raise AssertionError(
            "Switching to Manual Only must dismiss an open gaze menu before processing more samples: "
            f"cancel={manual_menu.cancel_calls}, feed={manual_menu.feed_calls}"
        )
    if manual_policy.calls != 1:
        raise AssertionError("Manual Only should continue tracking focus after dismissing the radial menu.")
    if manual_moves or manual_reactions:
        raise AssertionError(
            "Manual Only must retain focus internally without moving or reacting automatically: "
            f"moves={manual_moves!r}, reactions={manual_reactions!r}"
        )

    class BlockingTimerRuntime:
        def __init__(self):
            self.send_started = threading.Event()
            self.release_first = threading.Event()
            self.sent: list[dict] = []

        def send(self, payload: dict) -> bool:
            self.sent.append(dict(payload or {}))
            if len(self.sent) == 1:
                self.send_started.set()
                self.release_first.wait(timeout=2.0)
            return True

    timer_runtime = BlockingTimerRuntime()
    timer_controller = type("TimerQueueController", (), {})()
    timer_controller._external_runtime = timer_runtime
    timer_controller._external_runtime_enabled = lambda: True
    timer_controller._external_gaze_timer_lock = threading.Lock()
    timer_controller._external_gaze_timer_io_lock = threading.Lock()
    timer_controller._external_gaze_timer_pending = None
    timer_controller._external_gaze_timer_worker_active = False
    timer_controller._external_gaze_timer_generation = 0
    timer_controller._drain_external_gaze_timer_queue = (
        lambda generation: CompanionOrbController._drain_external_gaze_timer_queue(
            timer_controller,
            generation,
        )
    )
    queue_started_at = time.perf_counter()
    CompanionOrbController._queue_external_gaze_timer(
        timer_controller,
        {"type": "gaze_timer", "active": True, "progress": 0.1, "color": "#facc15"},
    )
    queue_elapsed = time.perf_counter() - queue_started_at
    if queue_elapsed >= 0.10:
        raise AssertionError(f"Timer IPC blocked its caller for {queue_elapsed:.3f}s.")
    if not timer_runtime.send_started.wait(timeout=1.0):
        raise AssertionError("The asynchronous timer writer did not start.")
    CompanionOrbController._queue_external_gaze_timer(
        timer_controller,
        {"type": "gaze_timer", "active": True, "progress": 0.3, "color": "#facc15"},
    )
    CompanionOrbController._queue_external_gaze_timer(
        timer_controller,
        {"type": "gaze_timer", "active": True, "progress": 0.7, "color": "#facc15"},
    )
    timer_runtime.release_first.set()
    timer_deadline = time.monotonic() + 1.5
    while len(timer_runtime.sent) < 2 and time.monotonic() < timer_deadline:
        time.sleep(0.01)
    if len(timer_runtime.sent) != 2 or timer_runtime.sent[-1].get("progress") != 0.7:
        raise AssertionError(
            "Timer IPC should coalesce blocked updates to the latest frame: "
            f"{timer_runtime.sent!r}"
        )

    class StopRaceRuntime:
        def __init__(self):
            self.send_started = threading.Event()
            self.stop_requested = threading.Event()
            self.stopped = threading.Event()

        def send(self, _payload: dict) -> bool:
            self.send_started.set()
            self.stop_requested.wait(timeout=0.5)
            return False

        def request_stop(self) -> None:
            self.stop_requested.set()

        def stop(self) -> None:
            self.stopped.set()

    stop_runtime = StopRaceRuntime()
    stop_controller = type("TimerStopController", (), {})()
    stop_controller._external_runtime = stop_runtime
    stop_controller._external_runtime_enabled = lambda: True
    stop_controller._external_gaze_timer_lock = threading.Lock()
    stop_controller._external_gaze_timer_io_lock = threading.Lock()
    stop_controller._external_gaze_timer_pending = None
    stop_controller._external_gaze_timer_worker_active = False
    stop_controller._external_gaze_timer_generation = 0
    stop_controller._drain_external_gaze_timer_queue = (
        lambda generation: CompanionOrbController._drain_external_gaze_timer_queue(
            stop_controller,
            generation,
        )
    )
    stop_controller._cancel_external_gaze_timer_queue = (
        lambda: CompanionOrbController._cancel_external_gaze_timer_queue(stop_controller)
    )
    CompanionOrbController._queue_external_gaze_timer(
        stop_controller,
        {"type": "gaze_timer", "active": True, "progress": 0.4, "color": "#facc15"},
    )
    if not stop_runtime.send_started.wait(timeout=1.0):
        raise AssertionError("The blocked timer send did not start for the stop-race check.")
    stop_started_at = time.perf_counter()
    CompanionOrbController._stop_external_runtime(stop_controller)
    stop_elapsed = time.perf_counter() - stop_started_at
    if stop_elapsed >= 0.10:
        raise AssertionError(f"Stopping during blocked timer IPC froze its caller for {stop_elapsed:.3f}s.")
    if not stop_runtime.stop_requested.is_set():
        raise AssertionError("Stopping should interrupt a blocked external timer write.")
    if not stop_runtime.stopped.wait(timeout=1.0):
        raise AssertionError("External runtime cleanup did not finish after interrupting timer IPC.")

    class InterruptibleProcess:
        stdin = None

        def __init__(self):
            self.terminated = False

        def poll(self):
            return -15 if self.terminated else None

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout=None):
            return -15

    interruptible_process = InterruptibleProcess()
    interruptible_client = ExternalOrbRuntimeClient(ROOT_DIR)
    interruptible_client._process = interruptible_process
    interruptible_client.request_stop()
    if not interruptible_process.terminated or not interruptible_client._stop_requested.is_set():
        raise AssertionError("External runtime request_stop() must terminate the child before waiting on IPC.")
    if interruptible_client.send({"type": "gaze_timer"}):
        raise AssertionError("A stop-requested external runtime must reject queued timer retries.")
    interruptible_client.stop()
    if interruptible_client._stop_requested.is_set():
        raise AssertionError("A completed external runtime stop should remain restartable.")

    class StartRaceProcess(InterruptibleProcess):
        stdout = None

    class BlockingPopen:
        def __init__(self):
            self.entered = threading.Event()
            self.release = threading.Event()
            self.process = StartRaceProcess()

        def __call__(self, *_args, **_kwargs):
            self.entered.set()
            self.release.wait(timeout=1.0)
            return self.process

    blocking_popen = BlockingPopen()
    original_popen = external_client_module.subprocess.Popen
    start_results: list[bool] = []
    start_race_outcome: tuple[list[bool], bool] | None = None
    try:
        external_client_module.subprocess.Popen = blocking_popen
        with tempfile.TemporaryDirectory() as runtime_root:
            start_race_client = ExternalOrbRuntimeClient(Path(runtime_root))
            try:
                start_thread = threading.Thread(
                    target=lambda: start_results.append(start_race_client.start()),
                    daemon=True,
                )
                start_thread.start()
                if not blocking_popen.entered.wait(timeout=1.0):
                    raise AssertionError("The external runtime startup race check did not reach process creation.")
                start_race_client.request_stop()
                blocking_popen.release.set()
                start_thread.join(timeout=1.0)
                if start_thread.is_alive():
                    raise AssertionError("External runtime startup did not finish after a concurrent stop request.")
                start_race_outcome = (list(start_results), bool(blocking_popen.process.terminated))
            finally:
                blocking_popen.release.set()
                start_race_client.stop()
    finally:
        external_client_module.subprocess.Popen = original_popen
    if start_race_outcome != ([False], True):
        raise AssertionError(
            "A stop request during process creation must terminate the new child before startup succeeds: "
            f"outcome={start_race_outcome!r}"
        )

    live_calibration_moves: list[tuple] = []
    live_calibration_controller = type("LiveCalibrationController", (), {})()
    live_calibration_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_offset_x_px": 135,
        "companion_orb_eye_tracking_offset_y_px": -80,
    }
    live_calibration_controller._eye_tracking_interaction_source_point = (640.0, 360.0)
    live_calibration_controller._eye_tracking_orb_active = lambda: True
    live_calibration_controller._eye_tracking_interaction_ready = lambda: True
    live_calibration_controller._set_eye_tracking_interaction_target = (
        lambda point, *, duration_seconds, force_external_send=False: live_calibration_moves.append(
            (point, duration_seconds, force_external_send)
        )
    )
    CompanionOrbController._reapply_eye_tracking_interaction_target(live_calibration_controller)
    if live_calibration_moves != [((640.0, 360.0), 2.0, True)]:
        raise AssertionError(
            "Changing eye-tracking calibration must immediately rebuild and transmit the active gaze target: "
            f"{live_calibration_moves!r}"
        )

    class LiveCalibrationBridge:
        def apply_settings(self, _settings) -> None:
            return None

        def set_target_info(self, _target) -> None:
            return None

    live_apply_calls: list[str] = []
    live_apply_controller = type("LiveCalibrationApplyController", (), {})()
    live_apply_controller._last_runtime_config = {
        "companion_orb_eye_tracking_offset_x_px": 0,
        "companion_orb_eye_tracking_offset_y_px": 0,
        "companion_orb_eye_tracking_click_target_enabled": False,
        "companion_orb_include_process_name": True,
        "companion_orb_target_mode": "window",
        "companion_orb_external_runtime_enabled": False,
    }
    live_apply_controller._gaze_click_target_page_open = False
    live_apply_controller._gaze_radial_menu_open = False
    live_apply_controller.bridge = LiveCalibrationBridge()
    live_apply_controller._target_info = {}
    live_apply_controller._persist_interaction_defaults_migration = lambda: None
    live_apply_controller._sync_eye_tracking_provider = lambda: None
    live_apply_controller._apply_timer_intervals = lambda: None
    live_apply_controller._external_runtime_enabled = lambda: False
    live_apply_controller._stop_external_runtime = lambda: None
    live_apply_controller._debug_event = lambda *_args, **_kwargs: None
    live_apply_controller._target_for_output = lambda target: dict(target or {})
    live_apply_controller._send_external_runtime = lambda _payload: False
    live_apply_controller._refresh_target_for_mode_change = lambda _mode: None
    live_apply_controller._apply_window_settings = lambda: None
    live_apply_controller._refresh_visibility = lambda: None
    live_apply_controller._sync_drift_timer = lambda: None
    live_apply_controller._reapply_eye_tracking_interaction_target = (
        lambda: live_apply_calls.append("reapplied")
    )
    live_apply_controller._gaze_click_target_enabled = lambda: (
        CompanionOrbController._gaze_click_target_enabled(live_apply_controller)
    )
    live_apply_controller._refresh_gaze_radial_menu_after_click_target_disable = lambda previous: (
        CompanionOrbController._refresh_gaze_radial_menu_after_click_target_disable(
            live_apply_controller,
            previous,
        )
    )
    changed_calibration = {
        **live_apply_controller._last_runtime_config,
        "companion_orb_eye_tracking_offset_x_px": 135,
        "companion_orb_eye_tracking_offset_y_px": -80,
    }
    CompanionOrbController.apply_runtime_config(live_apply_controller, changed_calibration)
    if live_apply_calls != ["reapplied"]:
        raise AssertionError(
            "Applying changed X/Y calibration should refresh the active target exactly once: "
            f"{live_apply_calls!r}"
        )
    live_apply_calls.clear()
    CompanionOrbController.apply_runtime_config(live_apply_controller, changed_calibration)
    if live_apply_calls:
        raise AssertionError("Unchanged calibration should not rebuild the current gaze target.")

    preparation_controller = type("ReactionPreparationController", (), {})()
    preparation_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_reaction_mode": "meaningful",
    }
    preparation_controller._eye_tracking_latest_point = (640.0, 360.0)
    preparation_controller._eye_tracking_latest_at = time.monotonic()
    preparation_controller._eye_tracking_reaction_lock = threading.Lock()
    preparation_controller._eye_tracking_reaction_active = False
    preparation_controller._eye_tracking_reaction_generation = 3
    preparation_controller._eye_tracking_reaction_shutting_down = False
    preparation_controller._set_eye_tracking_interaction_target = lambda _point, *, duration_seconds: None
    preparation_controller._eye_tracking_reaction_bounds = (
        lambda _point: (_ for _ in ()).throw(RuntimeError("test geometry failure"))
    )
    preparation_controller._virtual_desktop_rect = lambda: None
    preparation_result = CompanionOrbController._request_eye_tracking_reaction(preparation_controller, True)
    if preparation_result.get("ok") is not False or "test geometry failure" not in str(
        preparation_result.get("error") or ""
    ):
        raise AssertionError(f"Reaction preparation failure was not reported: {preparation_result!r}")
    if preparation_controller._eye_tracking_reaction_active:
        raise AssertionError("Reaction preparation failure left the one-worker guard active.")

    queued_image_turns: list[tuple[str, dict]] = []
    reaction_results: list[tuple[bool, str]] = []

    class FakeImageTurns:
        def queue_image_turn(self, path: str, **kwargs) -> None:
            queued_image_turns.append((path, dict(kwargs)))

    class FakeContext:
        def __init__(self, app_root: Path):
            self.app_root = app_root
            self._image_turns = FakeImageTurns()

        def get_service(self, name: str):
            return self._image_turns if name == "qt.user_image_turns" else None

    class FakeSignal:
        def emit(self, success: bool, message: str) -> None:
            reaction_results.append((bool(success), str(message)))

    class FakeProxy:
        eye_reaction_result_requested = FakeSignal()

    original_grab = ImageGrab.grab
    with tempfile.TemporaryDirectory(prefix="nc-orb-reaction-") as temp_dir:
        fake_controller = type("FakeReactionController", (), {})()
        fake_controller.context = FakeContext(Path(temp_dir))
        fake_controller._proxy = FakeProxy()
        fake_controller._snapshot_capture_lock = threading.Lock()
        fake_controller._eye_tracking_reaction_lock = threading.Lock()
        fake_controller._eye_tracking_reaction_active = True
        fake_controller._eye_tracking_reaction_generation = 7
        fake_controller._eye_tracking_reaction_shutting_down = False
        fake_controller._eye_tracking_reaction_gate = eye_tracking.GazeReactionGate(
            cooldown_seconds=45.0,
            minimum_signature_distance=8,
        )
        fake_controller._last_runtime_config = {
            "companion_orb_eye_tracking_mode": "dwell",
            "companion_orb_eye_tracking_reaction_mode": "meaningful",
        }
        fake_controller._eye_tracking_orb_active = lambda: True
        fake_controller._eye_tracking_reaction_is_current = (
            lambda generation, force: CompanionOrbController._eye_tracking_reaction_is_current(
                fake_controller,
                generation,
                force=force,
            )
        )
        fake_controller._apply_snapshot_cloak_blocking = lambda _enabled: False

        def crop_test_region(desktop, bounds, desktop_rect):
            if bounds != [20, 10, 80, 50] or desktop_rect is not None:
                raise AssertionError(f"Unexpected crop handoff: bounds={bounds!r}, desktop_rect={desktop_rect!r}")
            return desktop.crop((20, 10, 100, 60)), [20, 10, 80, 50]

        fake_controller._crop_desktop_image_to_bounds = crop_test_region
        synthetic_desktop = Image.new("RGB", (160, 100), "black")
        for x in range(80, 160):
            for y in range(100):
                synthetic_desktop.putpixel((x, y), (240, 240, 240))
        grab_calls: list[bool] = []

        def grab_test_desktop(*, all_screens=False):
            grab_calls.append(bool(all_screens))
            return synthetic_desktop.copy()

        ImageGrab.grab = grab_test_desktop
        try:
            CompanionOrbController._capture_eye_tracking_reaction(
                fake_controller,
                [20, 10, 80, 50],
                None,
                True,
                7,
            )
            if len(queued_image_turns) != 1:
                raise AssertionError(f"A forced visual reaction should queue exactly once: {queued_image_turns!r}")
            queued_path, queued_options = queued_image_turns[0]
            if not Path(queued_path).is_file():
                raise AssertionError("The queued Companion Orb crop was not written.")
            with Image.open(queued_path) as queued_image:
                if queued_image.size != (80, 50):
                    raise AssertionError(f"Visual reaction queued an unbounded image: {queued_image.size!r}")
            if queued_options.get("source") != "companion_orb_target":
                raise AssertionError(f"Visual reaction used the wrong Main Chat source: {queued_options!r}")
            if set(queued_options) != {"content", "source"}:
                raise AssertionError(f"Visual reaction added unexpected Main Chat metadata: {queued_options!r}")
            llm_payload = repr(queued_options).lower()
            for forbidden in ("gaze", "eye-tracker", "640", "360"):
                if forbidden in llm_payload:
                    raise AssertionError(f"Visual reaction leaked selection details to Main Chat: {llm_payload!r}")
            if reaction_results != [(True, "Visual reaction queued in Main Chat.")]:
                raise AssertionError(f"Visual reaction did not report success: {reaction_results!r}")
            if fake_controller._eye_tracking_reaction_active:
                raise AssertionError("Visual reaction worker did not release its active guard.")

            grabs_before_cancel = len(grab_calls)

            def grab_then_switch_to_manual(*, all_screens=False):
                grab_calls.append(bool(all_screens))
                fake_controller._last_runtime_config["companion_orb_eye_tracking_mode"] = "manual"
                return synthetic_desktop.copy()

            ImageGrab.grab = grab_then_switch_to_manual
            fake_controller._eye_tracking_reaction_active = True
            fake_controller._last_runtime_config["companion_orb_eye_tracking_mode"] = "dwell"
            CompanionOrbController._capture_eye_tracking_reaction(
                fake_controller,
                [20, 10, 80, 50],
                None,
                False,
                7,
            )
            if len(queued_image_turns) != 1:
                raise AssertionError("Manual Only allowed an in-flight automatic reaction to reach Main Chat.")
            if len(grab_calls) != grabs_before_cancel + 1:
                raise AssertionError("The in-flight mode-change test did not reach screen capture.")
            if fake_controller._eye_tracking_reaction_active:
                raise AssertionError("Canceled visual reaction did not release its active guard.")

            grabs_after_mode_cancel = len(grab_calls)
            ImageGrab.grab = grab_test_desktop
            fake_controller._eye_tracking_reaction_active = True
            fake_controller._last_runtime_config["companion_orb_eye_tracking_mode"] = "dwell"
            fake_controller._eye_tracking_reaction_generation = 8
            CompanionOrbController._capture_eye_tracking_reaction(
                fake_controller,
                [20, 10, 80, 50],
                None,
                True,
                7,
            )
            if len(grab_calls) != grabs_after_mode_cancel or len(queued_image_turns) != 1:
                raise AssertionError("A stale reaction generation was not canceled before screen capture.")
        finally:
            ImageGrab.grab = original_grab

    orb_controller_path = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py"
    )
    orb_controller_source = orb_controller_path.read_text(encoding="utf-8")
    apply_runtime_config_source = method_source(
        orb_controller_source,
        "CompanionOrbController",
        "apply_runtime_config",
    )
    for fragment in ("set_menu_opacity", "set_focus_beam_enabled"):
        if fragment not in apply_runtime_config_source:
            raise AssertionError(
                "An open radial menu must receive live opacity and charging-beam setting changes: "
                f"missing {fragment!r}"
            )
    external_runtime_path = orb_controller_path.with_name("external_orb_runtime.py")
    external_runtime_source = external_runtime_path.read_text(encoding="utf-8")
    for fragment in (
        "eye_sample_requested = QtCore.Signal(float, float)",
        "eye_status_requested = QtCore.Signal(str, str)",
        "eye_tracking.TobiiStreamEngineProvider",
        "def _sync_eye_tracking_provider",
        "def _eye_tracking_orb_active",
        "def _handle_eye_tracking_sample",
        "def _set_eye_tracking_interaction_target",
        "def _eye_tracking_interaction_ready",
        "def eye_tracking_status",
        "def reconnect_eye_tracking",
        '"type": "interaction_target"',
        '"type": "interaction_target_clear"',
        "self._eye_tracking_provider.stop",
        "eye_react_requested = QtCore.Signal(bool)",
        "def react_at_gaze",
        "def _request_eye_tracking_reaction",
        "def _capture_eye_tracking_reaction",
        '("companion_orb_eye_tracking_hotkey", "Ctrl+Alt+G"',
        'self.context.get_service("qt.user_image_turns")',
        'source="companion_orb_target"',
        "ImageGrab.grab(all_screens=True)",
        "self._snapshot_capture_lock.acquire(blocking=False)",
        '"orb_disabled"',
        "gaze_radial_menu.MAIN_GAZE_ACTIONS",
        "def _show_gaze_radial_main_menu",
        "def _handle_gaze_radial_action",
        "def _show_gaze_voice_menu",
        "def _show_gaze_reply_style_menu",
        "def _start_gaze_read_text",
        '"type": "gaze_timer"',
        "pointer_clearance.PointerClearancePolicy",
        "def _apply_eye_tracking_pointer_clearance",
        "def _eye_tracking_pointer_clearance_suspended",
        '"pointer_clearance_suspended":',
        '"orb.pointer_clearance_state"',
    ):
        if fragment not in orb_controller_source:
            raise AssertionError(f"Companion Orb controller is missing eye-tracking integration {fragment!r}.")
    for fragment in (
        "pointer_clearance.PointerClearancePolicy",
        '"pointer_clearance_guard"',
        '"pointer_clearance_suspended"',
        '"orb.pointer_clearance_state"',
        "def _apply_pointer_clearance",
        "self.pointer_clearance_opacity",
    ):
        if fragment not in external_runtime_source:
            raise AssertionError(
                f"External Companion Orb is missing Pointer Clearance integration {fragment!r}."
            )
    external_pointer_event_source = method_source(
        external_runtime_source,
        "ExternalCompanionOrb",
        "_set_pointer_clearance_state",
    )
    if any(
        fragment in external_pointer_event_source
        for fragment in ('"point"', '"top_left"', '"center"', "QCursor")
    ):
        raise AssertionError(
            "External Pointer Clearance status events must not include pointer or Orb coordinates."
        )
    local_drift = method_source(orb_controller_source, "CompanionOrbController", "_on_drift_tick")
    interaction_index = local_drift.find("if eye_interaction_ready:")
    comment_index = local_drift.find("elif comment_focus_ready:")
    harassment_index = local_drift.find("elif harassment_ready:")
    if not (0 <= interaction_index < comment_index < harassment_index):
        raise AssertionError("Eye interaction must outrank stale comment focus and playful idle seeking.")
    for method_name in ("_handle_eye_tracking_sample", "_set_eye_tracking_interaction_target"):
        source = method_source(orb_controller_source, "CompanionOrbController", method_name)
        for forbidden in ("_debug_event", "_save_runtime_setting", "context.events.publish"):
            if forbidden in source:
                raise AssertionError(f"{method_name} must not persist or log gaze-derived positions ({forbidden}).")
    reaction_capture = method_source(
        orb_controller_source,
        "CompanionOrbController",
        "_capture_eye_tracking_reaction",
    )
    for forbidden in (
        "_debug_event",
        "_drop_trace_event",
        "_capture_target_region",
        "_request_hidden_pingpong_cycle_async",
        "extract_snapshot_regions",
        "focus_bounds",
        "QtWidgets.QApplication",
        "_eye_tracking_screen_bounds",
        "_eye_tracking_reaction_bounds(point)",
        "_virtual_desktop_rect()",
        "queue_image_turn(\n                path,\n                content=content + str(point)",
    ):
        if forbidden in reaction_capture:
            raise AssertionError(f"Eye reaction capture crossed the privacy boundary ({forbidden}).")
    gaze_read_source = method_source(
        orb_controller_source,
        "CompanionOrbController",
        "_start_gaze_read_text",
    )
    if (
        "private_bounds=True" not in gaze_read_source
        or "_debug_event" in gaze_read_source
        or "_eye_tracking_read_text_bounds(selected_point)" not in gaze_read_source
        or "_eye_tracking_reaction_bounds(selected_point)" in gaze_read_source
    ):
        raise AssertionError("Gaze Read text must redact focus geometry from diagnostics.")
    read_bounds_source = method_source(
        orb_controller_source,
        "CompanionOrbController",
        "_eye_tracking_read_text_bounds",
    )
    if "_debug_event" in read_bounds_source or "_save_runtime_setting" in read_bounds_source:
        raise AssertionError("Read text expansion must not persist or log gaze-derived bounds.")
    vision_read_source = method_source(
        orb_controller_source,
        "CompanionOrbController",
        "_extract_selected_reading_text_with_vision_llm",
    )
    if "screen_bounds=[] if private_bounds else list(bounds or [])" not in vision_read_source:
        raise AssertionError("Gaze Read text must not send desktop coordinates to the vision OCR provider.")
    reading_ocr_source = method_source(
        orb_controller_source,
        "CompanionOrbController",
        "_extract_selected_reading_ocr",
    )
    if (
        "private_bounds and self._apply_snapshot_cloak_blocking(True)" not in reading_ocr_source
        or "self._apply_snapshot_cloak_blocking(False)" not in reading_ocr_source
    ):
        raise AssertionError("Gaze Read text must cloak the Orb while capturing its private OCR crop.")
    reaction_request = method_source(
        orb_controller_source,
        "CompanionOrbController",
        "_request_eye_tracking_reaction",
    )
    bounds_index = reaction_request.find("capture_bounds = self._eye_tracking_reaction_bounds(point)")
    rect_index = reaction_request.find("virtual_rect = self._virtual_desktop_rect()")
    worker_index = reaction_request.find("worker = threading.Thread(")
    if not (0 <= bounds_index < worker_index and 0 <= rect_index < worker_index):
        raise AssertionError("Eye reaction screen geometry must be copied on the Qt thread before worker startup.")
    worker_argument_fragments = (
        "capture_bounds,",
        "virtual_rect,",
        "bool(force),",
        "reaction_generation,",
        "_eye_tracking_context_prompt(action_id),",
    )
    if any(fragment not in reaction_request for fragment in worker_argument_fragments):
        raise AssertionError(
            "Eye reaction worker did not receive copied geometry, lifecycle state, and the bounded action prompt."
        )
    if reaction_capture.count("_eye_tracking_reaction_is_current") < 3:
        raise AssertionError("Eye reaction worker must recheck cancellation before capture and Main Chat delivery.")

    command_cases = {
        "Orb, comment on where I am looking": True,
        "Companion Orb check my gaze": True,
        "Orb react to what I'm looking at": True,
        "comment on this image": False,
        "where am I looking?": False,
        "Orb change color": False,
    }
    for command, expected in command_cases.items():
        actual = eye_tracking.is_explicit_orb_gaze_command(command)
        if actual is not expected:
            raise AssertionError(f"Unexpected gaze command routing for {command!r}: {actual!r}")

    addon_main_path = ROOT_DIR / "addons" / "companion_orb_overlay" / "main.py"
    addon_main_source = addon_main_path.read_text(encoding="utf-8")
    for fragment in (
        'capability_name == "chat.user_text_command"',
        "def _handle_eye_tracking_user_text_command",
        "eye_tracking.is_explicit_orb_gaze_command",
        "orb.react_at_gaze(force=True)",
        '"use_llm_response": False',
    ):
        if fragment not in addon_main_source:
            raise AssertionError(f"Companion Orb voice/text command routing is missing {fragment!r}.")

    from addons.companion_orb_overlay.main import Addon

    class CommandOrb:
        def __init__(self):
            self.reaction_calls: list[bool] = []

        def react_at_gaze(self, *, force: bool = True):
            self.reaction_calls.append(bool(force))
            return {"ok": True, "queued": True}

    command_addon = Addon.__new__(Addon)
    command_addon.orb_controller = CommandOrb()
    handled_command = command_addon.invoke_capability(
        "chat.user_text_command",
        {"role": "user", "text": "Orb, comment on where I am looking"},
    )
    if not isinstance(handled_command, dict) or not handled_command.get("handled"):
        raise AssertionError(f"Explicit user gaze command was not handled: {handled_command!r}")
    if handled_command.get("use_llm_response") is not False:
        raise AssertionError(f"Gaze command should not send its command text to the LLM: {handled_command!r}")
    if command_addon.orb_controller.reaction_calls != [True]:
        raise AssertionError(
            f"Explicit gaze command should force one reaction: {command_addon.orb_controller.reaction_calls!r}"
        )
    for payload in (
        {"role": "assistant", "text": "Orb, comment on where I am looking"},
        {"role": "user", "text": "Please comment on this image"},
    ):
        if command_addon.invoke_capability("chat.user_text_command", payload) is not None:
            raise AssertionError(f"Unrelated/non-user chat command was consumed: {payload!r}")

    for fragment in (
        'if msg_type == "interaction_target":',
        'if msg_type == "interaction_target_clear":',
        "def _set_interaction_target",
        "def _interaction_target_ready",
        "if interaction_target_ready:",
    ):
        if fragment not in external_runtime_source:
            raise AssertionError(f"External Orb runtime is missing transient interaction handling {fragment!r}.")
    external_target = method_source(external_runtime_source, "ExternalCompanionOrb", "_set_interaction_target")
    for forbidden in ("_log(", "_emit_event(", "self.settings["):
        if forbidden in external_target:
            raise AssertionError(f"External interaction targets must remain transient ({forbidden}).")

    print("Companion Orb eye tracking smoke test passed.")


if __name__ == "__main__":
    main()
