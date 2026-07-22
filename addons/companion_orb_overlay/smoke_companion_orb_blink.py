from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def assert_action(decision, expected: str, message: str) -> None:
    actual = str(getattr(decision, "action", "") or "")
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def main() -> None:
    from addons.companion_orb_overlay.companion_orb import eye_tracking
    from addons.companion_orb_overlay.companion_orb import gaze_radial_menu
    from addons.companion_orb_overlay import controller as settings_controller

    detector = eye_tracking.BlinkGestureDetector(
        minimum_closed_ms=80,
        maximum_closed_ms=900,
        recovery_ms=80,
        stable_before_ms=100,
    )
    detector.ingest_validity(True, now=0.0)
    detector.ingest_valid_sample(now=0.12)
    detector.ingest_validity(False, now=0.20)
    detector.ingest_validity(True, now=0.36)
    if detector.ingest_valid_sample(now=0.42) is not None:
        raise AssertionError("A blink must wait for the configured post-blink recovery time.")
    blink = detector.ingest_valid_sample(now=0.45)
    if blink is None or abs(blink.closed_ms - 160.0) > 0.01:
        raise AssertionError(f"A valid blink was not emitted after stable recovery: {blink!r}")
    if detector.ingest_valid_sample(now=0.60) is not None:
        raise AssertionError("One eye closure must emit at most one blink.")

    detector.reset()
    detector.ingest_validity(True, now=1.0)
    detector.ingest_valid_sample(now=1.20)
    detector.ingest_validity(False, now=1.30)
    detector.ingest_validity(True, now=1.34)
    if detector.ingest_valid_sample(now=1.50) is not None:
        raise AssertionError("A tracking dropout shorter than minimum_closed_ms is not a blink.")

    detector.reset()
    detector.ingest_validity(True, now=2.0)
    detector.ingest_valid_sample(now=2.20)
    detector.ingest_validity(False, now=2.30)
    detector.ingest_validity(True, now=3.25)
    if detector.ingest_valid_sample(now=3.40) is not None:
        raise AssertionError("A long tracking loss must not be classified as a blink.")

    detector.reset()
    detector.ingest_validity(True, now=4.0)
    detector.ingest_validity(False, now=4.04)
    detector.ingest_validity(True, now=4.30)
    if detector.ingest_valid_sample(now=4.50) is not None:
        raise AssertionError("A blink without stable tracking before closure must be ignored.")

    click_targets = eye_tracking.rank_click_targets(
        [
            {
                "text": "Open settings",
                "screen_bounds": [430, 300, 150, 42],
                "kind": "control_text",
                "confidence": 0.82,
            },
            {
                "text": "Open settings",
                "screen_bounds": [440, 305, 130, 30],
                "kind": "word",
                "confidence": 0.91,
            },
            {
                "text": "Help",
                "screen_bounds": [700, 350, 90, 34],
                "kind": "line",
                "confidence": 0.76,
            },
            {
                "text": "Entire window",
                "screen_bounds": [100, 100, 900, 650],
                "kind": "window_title",
                "confidence": 0.55,
            },
            {
                "text": "Outside",
                "screen_bounds": [1300, 900, 120, 40],
                "kind": "control_text",
                "confidence": 0.90,
            },
        ],
        focus_point=(500.0, 320.0),
        capture_bounds=(100, 100, 900, 650),
        limit=8,
    )
    if [target.label for target in click_targets] != ["Open settings", "Help"]:
        raise AssertionError(f"Nearby click targets were not ranked and deduplicated safely: {click_targets!r}")
    if click_targets[0].center != (505.0, 321.0):
        raise AssertionError(f"A click target did not preserve its visible control center: {click_targets[0]!r}")
    visual_targets = eye_tracking.rank_click_targets(
        [
            {
                "text": "",
                "screen_bounds": [120, 120, 140, 42],
                "kind": "text_region",
            },
            {
                "text": "",
                "screen_bounds": [720, 570, 120, 38],
                "kind": "text_region",
            },
        ],
        focus_point=(500.0, 350.0),
        capture_bounds=(100, 100, 800, 560),
        limit=8,
    )
    if visual_targets != ():
        raise AssertionError(
            "Legacy ranking must not expose unnamed visual targets as direct choices: "
            f"{visual_targets!r}"
        )
    preview_action = gaze_radial_menu.RadialAction(
        "click_target:0",
        "",
        preview_png=b"preview",
    )
    if preview_action.preview_png != b"preview":
        raise AssertionError("A radial target action did not retain its in-memory preview.")
    main_action_ids = tuple(action.action_id for action in gaze_radial_menu.MAIN_GAZE_ACTIONS)
    if main_action_ids[-1:] != ("action",) or "click_target" in main_action_ids:
        raise AssertionError(
            "The system-wide control workflow should use the existing Action node: "
            f"{main_action_ids!r}"
        )

    validity_events: list[bool] = []
    provider_samples: list[tuple[float, float]] = []
    provider_finished = threading.Event()

    class EventSession:
        def __init__(self):
            self.events = [
                eye_tracking.GazeStreamEvent(valid=False),
                eye_tracking.GazeStreamEvent(valid=True, position=(0.25, 0.75)),
            ]

        def read_event(self, _timeout_seconds: float):
            if self.events:
                return self.events.pop(0)
            provider_finished.set()
            time.sleep(0.005)
            return None

        def close(self) -> None:
            pass

    event_session = EventSession()
    provider = eye_tracking.TobiiStreamEngineProvider(
        on_sample=lambda x, y: provider_samples.append((x, y)),
        on_validity=lambda valid: validity_events.append(bool(valid)),
        session_factory=lambda _dll_path: event_session,
        dll_resolver=lambda _path: Path("C:/test/tobii_stream_engine.dll"),
        retry_seconds=0.01,
    )
    provider.start("")
    if not provider_finished.wait(timeout=1.0):
        raise AssertionError("The event-based gaze provider did not consume its test events.")
    provider.stop(timeout_seconds=1.0)
    if validity_events[:2] != [False, True]:
        raise AssertionError(f"Explicit gaze-validity transitions were not forwarded: {validity_events!r}")
    if provider_samples != [(0.25, 0.75)]:
        raise AssertionError(f"A valid event did not retain its gaze sample: {provider_samples!r}")

    policy = eye_tracking.BlinkClickPolicy(
        slow_blink_minimum_ms=260,
        double_blink_gap_ms=1200,
        click_cooldown_ms=450,
        activation_arm_ms=3500,
    )
    assert_action(
        policy.ingest_blink(320, now=10.0, menu_visible=True),
        "none",
        "An unarmed slow blink must not start activation",
    )
    assert_action(
        policy.ingest_blink(330, now=10.7, menu_visible=True),
        "none",
        "An unarmed slow double blink must not enable click mode",
    )
    policy.arm_activation(now=11.0)
    assert_action(
        policy.ingest_blink(320, now=11.2, menu_visible=True),
        "none",
        "The first armed slow blink should wait for its pair",
    )
    enabled = policy.ingest_blink(340, now=11.9, menu_visible=True)
    assert_action(enabled, "enable", "An armed slow double blink should enable click mode")
    if not enabled.enabled or not policy.enabled:
        raise AssertionError("Blink-click mode did not retain its enabled state.")

    assert_action(
        policy.ingest_blink(120, now=12.6, menu_visible=True),
        "none",
        "A blink must never click through an open gaze menu",
    )
    assert_action(
        policy.ingest_blink(120, now=12.7, menu_visible=False),
        "click",
        "A quick blink should click when the menu is closed and click mode is enabled",
    )
    assert_action(
        policy.ingest_blink(120, now=12.9, menu_visible=False),
        "none",
        "Click cooldown should reject duplicate blink clicks",
    )
    assert_action(
        policy.ingest_blink(320, now=13.4, menu_visible=False),
        "none",
        "A slow blink should be reserved for the disable gesture",
    )
    disabled = policy.ingest_blink(330, now=14.1, menu_visible=False)
    assert_action(disabled, "disable", "A slow double blink should disable click mode")
    if disabled.enabled or policy.enabled:
        raise AssertionError("Blink-click mode remained enabled after its disable gesture.")
    assert_action(
        policy.ingest_blink(120, now=14.8, menu_visible=False),
        "none",
        "A blink must not click after click mode is disabled",
    )

    expected_defaults = {
        "companion_orb_eye_tracking_blink_click_allowed": True,
        "companion_orb_eye_tracking_blink_min_ms": 80,
        "companion_orb_eye_tracking_blink_slow_min_ms": 260,
        "companion_orb_eye_tracking_blink_max_ms": 900,
        "companion_orb_eye_tracking_blink_recovery_ms": 80,
        "companion_orb_eye_tracking_blink_double_gap_ms": 1200,
        "companion_orb_eye_tracking_blink_click_cooldown_ms": 450,
    }
    for key, expected in expected_defaults.items():
        actual = settings_controller.COMPANION_ORB_EYE_TRACKING_DEFAULTS.get(key)
        if actual != expected:
            raise AssertionError(f"Blink setting {key!r} should default to {expected!r}, got {actual!r}.")
        if key not in settings_controller.CompanionOrbOverlaySettingsController.SESSION_KEYS:
            raise AssertionError(f"Blink setting {key!r} is missing from session export.")

    manifest = json.loads(
        (ROOT_DIR / "addons" / "companion_orb_overlay" / "addon.json").read_text(encoding="utf-8")
    )
    runtime_defaults = dict(manifest.get("runtime_defaults") or {})
    for key, expected in expected_defaults.items():
        if runtime_defaults.get(key) != expected:
            raise AssertionError(f"Blink setting {key!r} is missing from addon runtime defaults.")

    settings_source = Path(settings_controller.__file__).read_text(encoding="utf-8")
    for fragment in (
        "companion_orb_eye_tracking_blink_click_allowed_checkbox",
        "companion_orb_eye_tracking_blink_status_label",
        "companion_orb_eye_tracking_blink_min_ms_slider",
        "companion_orb_eye_tracking_blink_slow_min_ms_slider",
        "companion_orb_eye_tracking_blink_max_ms_slider",
        "companion_orb_eye_tracking_blink_recovery_ms_slider",
        "companion_orb_eye_tracking_blink_double_gap_ms_slider",
        "companion_orb_eye_tracking_blink_click_cooldown_ms_slider",
    ):
        if fragment not in settings_source:
            raise AssertionError(f"Eye Tracking blink tuning UI is missing {fragment!r}.")

    radial_source = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "gaze_radial_menu.py"
    ).read_text(encoding="utf-8")
    if "def reset_gaze_selection" not in radial_source:
        raise AssertionError("An eye closure must be able to reset radial dwell progress safely.")

    controller_source = (
        ROOT_DIR
        / "addons"
        / "companion_orb_overlay"
        / "companion_orb"
        / "companion_orb_controller.py"
    ).read_text(encoding="utf-8")
    for fragment in (
        "eye_validity_requested = QtCore.Signal(bool)",
        "def _handle_eye_tracking_validity",
        "def _handle_blink_gesture",
        "def _blink_click_point",
        "def _show_gaze_click_target_menu",
        "def _scan_gaze_click_targets",
        "def _click_target_preview_png",
        "def _serialize_click_target",
        "def _handle_gaze_click_targets_result",
        "def _show_gaze_click_target_direct_page",
        "def _show_gaze_click_target_visual_page",
        "def _handle_gaze_click_candidate_changed",
        "def _queue_gaze_left_click",
        "def _perform_gaze_left_click",
        "def _play_blink_notification",
        "winsound.Beep",
        "user32.mouse_event",
        '"blink_click_enabled"',
        '"blink_click_allowed"',
        '"click_target"',
    ):
        if fragment not in controller_source:
            raise AssertionError(f"Companion Orb blink integration is missing {fragment!r}.")
    click_scan_source = controller_source.split("def _scan_gaze_click_targets", 1)[1].split(
        "def _handle_gaze_click_targets_result",
        1,
    )[0]
    for forbidden_fragment in ("_debug_event", "write_sidecar", "_save_runtime_setting"):
        if forbidden_fragment in click_scan_source:
            raise AssertionError(
                f"Click-target scanning must not persist private screen data via {forbidden_fragment!r}."
            )
    for required_fragment in (
        "discover_semantic_targets",
        "aggregate_click_targets",
        "automation_available",
        "automation_timed_out",
    ):
        if required_fragment not in click_scan_source:
            raise AssertionError(
                f"Smart-hybrid click-target scanning is missing {required_fragment!r}."
            )
    if "automation.error" in click_scan_source:
        raise AssertionError("Raw UI Automation errors must not leave the scan worker.")

    from addons.companion_orb_overlay.companion_orb import companion_orb_controller

    with tempfile.TemporaryDirectory(prefix="nc-orb-click-preview-") as temp_dir:
        from PIL import Image, ImageDraw
        from PySide6 import QtGui

        capture_path = Path(temp_dir) / "capture.png"
        capture = Image.new("RGB", (400, 240), "#101820")
        draw = ImageDraw.Draw(capture)
        draw.rectangle((135, 80, 265, 150), fill="#f8fafc")
        draw.text((150, 102), "Open settings", fill="#111827")
        capture.save(capture_path)
        preview_png = companion_orb_controller.CompanionOrbController._click_target_preview_png(
            capture_path,
            eye_tracking.ClickTarget("Open settings", (235, 180, 130, 70), "control_text", 0.9),
            [100, 100, 400, 240],
        )
        preview_image = QtGui.QImage.fromData(preview_png, "PNG")
        if not preview_png or preview_image.isNull():
            raise AssertionError("Click-target scanning did not produce a decodable in-memory preview.")

    class FakeOrbWindow:
        def frameGeometry(self):
            from PySide6 import QtCore

            return QtCore.QRect(100, 200, 92, 92)

    embedded_controller = type("EmbeddedBlinkController", (), {})()
    embedded_controller._external_runtime_enabled = lambda: False
    embedded_controller._window = FakeOrbWindow()
    embedded_controller._eye_tracking_interaction_target = None
    embedded_controller._external_orb_top_left = None
    embedded_controller._window_size = lambda: 92
    embedded_center = companion_orb_controller.CompanionOrbController._blink_click_point(
        embedded_controller,
        (10.0, 20.0),
    )
    if embedded_center != (146.0, 246.0):
        raise AssertionError(f"Embedded blink click did not use the rendered Orb center: {embedded_center!r}")

    from PySide6 import QtCore

    external_controller = type("ExternalBlinkController", (), {})()
    external_controller._external_runtime_enabled = lambda: True
    external_controller._window = None
    external_controller._eye_tracking_interaction_target = QtCore.QPointF(300.0, 400.0)
    external_controller._external_orb_top_left = QtCore.QPoint(5, 5)
    external_controller._window_size = lambda: 92
    external_center = companion_orb_controller.CompanionOrbController._blink_click_point(
        external_controller,
        (10.0, 20.0),
    )
    if external_center != (346.0, 446.0):
        raise AssertionError(
            f"External blink click used raw gaze or stale home coordinates instead of the Orb target: {external_center!r}"
        )

    class ArmMenu:
        selection_candidate_id = "react"

        def __init__(self):
            self.reset_calls = 0

        def isVisible(self) -> bool:
            return True

        def reset_gaze_selection(self) -> None:
            self.reset_calls += 1

    arm_menu = ArmMenu()
    arm_timer_calls: list[tuple[bool, float]] = []
    arm_controller = type("BlinkArmController", (), {})()
    arm_controller._last_runtime_config = {
        "companion_orb_eye_tracking_mode": "dwell",
        "companion_orb_eye_tracking_blink_click_allowed": True,
    }
    arm_controller._blink_gesture_detector = eye_tracking.BlinkGestureDetector()
    arm_controller._blink_click_policy = eye_tracking.BlinkClickPolicy()
    arm_controller._gaze_radial_menu = arm_menu
    arm_controller._eye_tracking_orb_active = lambda: True
    arm_controller._set_gaze_timer_state = (
        lambda active, progress: arm_timer_calls.append((bool(active), float(progress)))
    )
    companion_orb_controller.CompanionOrbController._handle_eye_tracking_validity(
        arm_controller,
        False,
    )
    if arm_menu.reset_calls != 1 or arm_timer_calls != [(False, 0.0)]:
        raise AssertionError("Starting a blink over a gaze button did not reset its dwell safely.")
    armed_at = time.monotonic()
    arm_controller._blink_click_policy.ingest_blink(320, now=armed_at, menu_visible=True)
    arm_decision = arm_controller._blink_click_policy.ingest_blink(
        330,
        now=armed_at + 0.7,
        menu_visible=True,
    )
    assert_action(arm_decision, "enable", "A radial-button validity gap did not arm activation")

    class FakeUser32:
        def __init__(self):
            self.calls: list[tuple] = []

        def SetCursorPos(self, x: int, y: int) -> int:
            self.calls.append(("move", x, y))
            return 1

        def mouse_event(self, flag: int, dx: int, dy: int, data: int, extra: int) -> None:
            self.calls.append(("mouse", flag, dx, dy, data, extra))

    fake_user32 = FakeUser32()
    original_windll = companion_orb_controller.ctypes.windll
    companion_orb_controller.ctypes.windll = type("FakeWindll", (), {"user32": fake_user32})()
    try:
        clicked = companion_orb_controller.CompanionOrbController._perform_gaze_left_click(
            object(),
            (321.4, 654.6),
        )
    finally:
        companion_orb_controller.ctypes.windll = original_windll
    if not clicked or fake_user32.calls != [
        ("move", 321, 655),
        ("mouse", 0x0002, 0, 0, 0, 0),
        ("mouse", 0x0004, 0, 0, 0, 0),
    ]:
        raise AssertionError(f"Blink click did not dispatch one complete left click: {fake_user32.calls!r}")

    print("Companion Orb blink smoke test passed.")


if __name__ == "__main__":
    main()
