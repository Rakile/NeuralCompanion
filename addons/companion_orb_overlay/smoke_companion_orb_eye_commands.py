from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def assert_action(decision, expected: str, message: str) -> None:
    actual = str(getattr(decision, "action", "") or "")
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def main() -> None:
    from addons.companion_orb_overlay import controller as settings_controller
    from addons.companion_orb_overlay.companion_orb import companion_orb_controller
    from addons.companion_orb_overlay.companion_orb import eye_tracking
    from addons.companion_orb_overlay.companion_orb import gaze_radial_menu

    detector = eye_tracking.BlinkGestureDetector(
        minimum_closed_ms=80,
        maximum_closed_ms=2000,
        recovery_ms=80,
        stable_before_ms=100,
    )
    detector.ingest_validity(True, now=0.0)
    detector.ingest_valid_sample(now=0.15)
    detector.ingest_validity(False, now=0.20)
    detector.ingest_validity(True, now=1.70)
    menu_blink = detector.ingest_valid_sample(now=1.80)
    if menu_blink is None or abs(menu_blink.closed_ms - 1500.0) > 0.01:
        raise AssertionError(f"A configured long menu closure was not detected: {menu_blink!r}")

    commands = eye_tracking.EyeCommandPolicy(
        fast_blink_maximum_ms=260,
        blink_maximum_ms=900,
        menu_toggle_minimum_ms=1000,
        menu_toggle_maximum_ms=2000,
        triple_blink_gap_ms=450,
        back_cooldown_ms=1500,
    )
    assert_action(
        commands.ingest_blink(menu_blink, now=1.80, menu_visible=False),
        "long_gaze_toggle",
        "A long eye closure should toggle the long-gaze radial-menu setting",
    )
    assert_action(
        commands.ingest_blink(
            eye_tracking.BlinkGesture(1500.0, 2.0),
            now=2.0,
            menu_visible=True,
        ),
        "long_gaze_toggle",
        "A long eye closure must toggle the setting rather than close an open menu",
    )
    assert_action(
        commands.ingest_blink(
            eye_tracking.BlinkGesture(950.0, 2.4),
            now=2.4,
            menu_visible=False,
        ),
        "none",
        "A closure between the normal and menu ranges must not trigger either gesture",
    )

    first = commands.ingest_blink(
        eye_tracking.BlinkGesture(120.0, 3.0),
        now=3.0,
        menu_visible=False,
    )
    assert_action(first, "quick_pending", "A quick blink must wait for a possible triple blink")
    if commands.release_pending_quick(now=3.30) is not None:
        raise AssertionError("A quick blink was released before the triple-blink window ended.")
    released = commands.release_pending_quick(now=3.46)
    if released is None or abs(released.closed_ms - 120.0) > 0.01:
        raise AssertionError(f"A single quick blink was not released after its window: {released!r}")

    for index, sample_at in enumerate((4.0, 4.25, 4.50), start=1):
        decision = commands.ingest_blink(
            eye_tracking.BlinkGesture(110.0, sample_at),
            now=sample_at,
            menu_visible=False,
        )
        expected = "browser_back" if index == 3 else "quick_pending"
        assert_action(decision, expected, "Three fast blinks should dispatch one Back command")
    if commands.release_pending_quick(now=5.0) is not None:
        raise AssertionError("A triple blink must not leak a delayed single-click gesture.")

    for sample_at in (4.8, 5.0, 5.2):
        cooldown_decision = commands.ingest_blink(
            eye_tracking.BlinkGesture(100.0, sample_at),
            now=sample_at,
            menu_visible=False,
        )
    assert_action(cooldown_decision, "none", "Back cooldown should reject repeated triple blinks")

    scroll = eye_tracking.GazeScrollPolicy(speed=5, dead_zone_px=100)
    if scroll.ingest(500.0, anchor_y=500.0, now=10.0) != 0:
        raise AssertionError("Gaze inside the scroll dead zone must not move the page.")
    scroll.ingest(760.0, anchor_y=500.0, now=10.1)
    down = scroll.ingest(760.0, anchor_y=500.0, now=10.4)
    if down >= 0:
        raise AssertionError(f"Looking below the anchor should scroll down, got {down!r}.")
    scroll.reset()
    scroll.ingest(240.0, anchor_y=500.0, now=11.0)
    up = scroll.ingest(240.0, anchor_y=500.0, now=11.3)
    if up <= 0:
        raise AssertionError(f"Looking above the anchor should scroll up, got {up!r}.")
    slow = eye_tracking.GazeScrollPolicy(speed=2, dead_zone_px=100)
    fast = eye_tracking.GazeScrollPolicy(speed=9, dead_zone_px=100)
    slow.ingest(800.0, anchor_y=500.0, now=20.0)
    fast.ingest(800.0, anchor_y=500.0, now=20.0)
    slow_delta = abs(slow.ingest(800.0, anchor_y=500.0, now=20.5))
    fast_delta = abs(fast.ingest(800.0, anchor_y=500.0, now=20.5))
    if fast_delta <= slow_delta:
        raise AssertionError("The scroll speed setting did not increase the generated wheel movement.")

    expected_defaults = {
        "companion_orb_eye_tracking_menu_blink_min_ms": 1000,
        "companion_orb_eye_tracking_menu_blink_max_ms": 2000,
        "companion_orb_eye_tracking_triple_blink_gap_ms": 450,
        "companion_orb_eye_tracking_back_cooldown_ms": 1500,
        "companion_orb_eye_tracking_scroll_speed": 5,
        "companion_orb_eye_tracking_scroll_dead_zone_px": 100,
    }
    manifest = json.loads(
        (ROOT_DIR / "addons" / "companion_orb_overlay" / "addon.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_defaults = dict(manifest.get("runtime_defaults") or {})
    for key, expected in expected_defaults.items():
        if settings_controller.COMPANION_ORB_EYE_TRACKING_DEFAULTS.get(key) != expected:
            raise AssertionError(f"Eye-command setting {key!r} has the wrong default.")
        if key not in settings_controller.CompanionOrbOverlaySettingsController.SESSION_KEYS:
            raise AssertionError(f"Eye-command setting {key!r} is missing from session export.")
        if runtime_defaults.get(key) != expected:
            raise AssertionError(f"Eye-command setting {key!r} is missing from addon defaults.")

    settings_source = Path(settings_controller.__file__).read_text(encoding="utf-8")
    for fragment in (
        "companion_orb_eye_tracking_menu_blink_min_ms_slider",
        "companion_orb_eye_tracking_menu_blink_max_ms_slider",
        "companion_orb_eye_tracking_triple_blink_gap_ms_slider",
        "companion_orb_eye_tracking_back_cooldown_ms_slider",
        "companion_orb_eye_tracking_scroll_speed_slider",
        "companion_orb_eye_tracking_scroll_dead_zone_px_slider",
    ):
        if fragment not in settings_source:
            raise AssertionError(f"Eye-command tuning UI is missing {fragment!r}.")

    main_action_ids = tuple(action.action_id for action in gaze_radial_menu.MAIN_GAZE_ACTIONS)
    if "scrolling" not in main_action_ids:
        raise AssertionError("The radial menu is missing its Scrolling action.")

    controller_source = Path(companion_orb_controller.__file__).read_text(encoding="utf-8")
    for fragment in (
        "def _start_gaze_scrolling",
        "def _stop_gaze_scrolling",
        "def _perform_gaze_scroll",
        "def _perform_browser_back",
        'command.action == "long_gaze_toggle"',
        "def _toggle_long_gaze_radial_menu",
        'command.action == "browser_back"',
        "_play_blink_notification(True)",
        "_play_blink_notification(False)",
    ):
        if fragment not in controller_source:
            raise AssertionError(f"Companion Orb eye-command integration is missing {fragment!r}.")

    class FakeScrollPolicy:
        def __init__(self):
            self.reset_calls = 0

        def reset(self) -> None:
            self.reset_calls += 1

    scroll_controller = type("ScrollController", (), {})()
    scroll_controller._gaze_radial_context_point = (640.0, 480.0)
    scroll_controller._gaze_radial_scroll_target_point = (700.0, 520.0)
    scroll_controller._eye_tracking_latest_point = None
    scroll_controller._gaze_radial_anchor = type(
        "Anchor",
        (),
        {"x": lambda self: 640, "y": lambda self: 480},
    )()
    scroll_controller._gaze_radial_context_hwnd = 123
    scroll_controller._gaze_scroll_policy = FakeScrollPolicy()
    scroll_controller._dismiss_calls = 0
    scroll_controller._dismiss_gaze_radial_menu = lambda: setattr(
        scroll_controller,
        "_dismiss_calls",
        scroll_controller._dismiss_calls + 1,
    )
    scroll_controller._play_blink_notification = lambda _enabled: None
    started = companion_orb_controller.CompanionOrbController._start_gaze_scrolling(
        scroll_controller
    )
    if not started or scroll_controller._dismiss_calls != 1:
        raise AssertionError("Starting gaze scrolling must close the radial menu immediately.")
    if not scroll_controller._gaze_scroll_active or scroll_controller._gaze_scroll_target_hwnd != 123:
        raise AssertionError("Hidden gaze scrolling did not retain its target window.")
    if scroll_controller._gaze_scroll_target_point != (700.0, 520.0):
        raise AssertionError("Gaze scrolling did not retain the Orb-center target point.")

    toggle_controller = type("LongGazeToggleController", (), {})()
    toggle_controller._last_runtime_config = {
        "companion_orb_eye_tracking_long_gaze_enabled": False,
    }
    saved_settings: list[tuple[str, bool]] = []
    toggle_controller._save_runtime_setting = (
        lambda key, value: saved_settings.append((str(key), bool(value)))
    )
    enabled = companion_orb_controller.CompanionOrbController._toggle_long_gaze_radial_menu(
        toggle_controller
    )
    disabled = companion_orb_controller.CompanionOrbController._toggle_long_gaze_radial_menu(
        toggle_controller
    )
    if enabled is not True or disabled is not False or saved_settings != [
        ("companion_orb_eye_tracking_long_gaze_enabled", True),
        ("companion_orb_eye_tracking_long_gaze_enabled", False),
    ]:
        raise AssertionError("Long eye closure did not persist the existing long-gaze setting toggle.")

    class FakeUser32:
        def __init__(self):
            self.calls: list[tuple] = []
            self.cursor = (900, 700)

        def keybd_event(self, key: int, scan: int, flags: int, extra: int) -> None:
            self.calls.append(("key", key, scan, flags, extra))

        def PostMessageW(self, hwnd: int, message: int, w_param: int, l_param: int) -> int:
            self.calls.append(("post", hwnd, message, w_param, l_param))
            return 1

        def IsWindow(self, hwnd: int) -> int:
            self.calls.append(("is_window", hwnd))
            return 1

        def GetCursorPos(self, pointer) -> int:
            pointer._obj.x, pointer._obj.y = self.cursor
            self.calls.append(("get_cursor",))
            return 1

        def SetCursorPos(self, x: int, y: int) -> int:
            self.cursor = (x, y)
            self.calls.append(("set_cursor", x, y))
            return 1

        def mouse_event(self, flags: int, dx: int, dy: int, data: int, extra: int) -> None:
            self.calls.append(("mouse", flags, dx, dy, data, extra))

    fake_user32 = FakeUser32()
    original_windll = companion_orb_controller.ctypes.windll
    companion_orb_controller.ctypes.windll = type("FakeWindll", (), {"user32": fake_user32})()
    try:
        backed = companion_orb_controller.CompanionOrbController._perform_browser_back(object())
        scrolled = companion_orb_controller.CompanionOrbController._perform_gaze_scroll(
            object(),
            123,
            -240,
            (640.0, 480.0),
        )
    finally:
        companion_orb_controller.ctypes.windll = original_windll
    if not backed or fake_user32.calls[:4] != [
        ("key", 0x12, 0, 0, 0),
        ("key", 0x25, 0, 0, 0),
        ("key", 0x25, 0, 0x0002, 0),
        ("key", 0x12, 0, 0x0002, 0),
    ]:
        raise AssertionError(f"Triple-blink Back did not send Alt+Left safely: {fake_user32.calls!r}")
    if not scrolled or fake_user32.calls[4:] != [
        ("is_window", 123),
        ("get_cursor",),
        ("set_cursor", 640, 480),
        ("mouse", 0x0800, 0, 0, (-240 & 0xFFFFFFFF), 0),
        ("set_cursor", 900, 700),
    ]:
        raise AssertionError(
            "Gaze scrolling did not inject one wheel event at the saved Orb target and restore "
            f"the cursor: {fake_user32.calls!r}"
        )

    class FakeKeyFallbackUser32:
        def __init__(self):
            self.calls: list[tuple] = []

        def IsWindow(self, _hwnd: int) -> int:
            return 1

        def GetCursorPos(self, _pointer) -> int:
            return 0

        def GetForegroundWindow(self) -> int:
            return 777

        def SetForegroundWindow(self, hwnd: int) -> int:
            self.calls.append(("foreground", hwnd))
            return 1

        def keybd_event(self, key: int, scan: int, flags: int, extra: int) -> None:
            self.calls.append(("key", key, scan, flags, extra))

    fallback_user32 = FakeKeyFallbackUser32()
    companion_orb_controller.ctypes.windll = type(
        "FallbackWindll",
        (),
        {"user32": fallback_user32},
    )()
    try:
        fallback_scrolled = companion_orb_controller.CompanionOrbController._perform_gaze_scroll(
            object(),
            123,
            -240,
            (640.0, 480.0),
        )
    finally:
        companion_orb_controller.ctypes.windll = original_windll
    if not fallback_scrolled or fallback_user32.calls != [
        ("foreground", 123),
        ("key", 0x28, 0, 0, 0),
        ("key", 0x28, 0, 0x0002, 0),
        ("key", 0x28, 0, 0, 0),
        ("key", 0x28, 0, 0x0002, 0),
        ("foreground", 777),
    ]:
        raise AssertionError(
            f"Gaze scrolling did not fall back to targeted Down keys: {fallback_user32.calls!r}"
        )

    print("Companion Orb eye-command smoke test passed.")


if __name__ == "__main__":
    main()
