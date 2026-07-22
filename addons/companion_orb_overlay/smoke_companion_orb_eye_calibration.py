from __future__ import annotations

import math
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import QtCore, QtWidgets

from addons.companion_orb_overlay.companion_orb import gaze_calibration
from addons.companion_orb_overlay.companion_orb import gaze_calibration_overlay
from addons.companion_orb_overlay.companion_orb import pointer_clearance


def _close(left: float, right: float, tolerance: float = 1.0) -> None:
    assert abs(float(left) - float(right)) <= float(tolerance), (left, right)


def test_supported_area_and_targets() -> None:
    rect = gaze_calibration.supported_calibration_rect(
        screen_bounds=(0.0, 0.0, 5120.0, 1440.0),
        physical_size_mm=(1197.0, 337.0),
    )
    left, top, width, height = rect
    assert 2850.0 <= width <= 3050.0
    assert 1220.0 <= height <= 1320.0
    _close(left + width * 0.5, 2560.0, 1.0)
    _close(top + height * 0.5, 720.0, 1.0)

    fallback = gaze_calibration.supported_calibration_rect(
        screen_bounds=(0.0, 0.0, 5120.0, 1440.0),
        physical_size_mm=(0.0, 0.0),
    )
    _close(fallback[3], 1440.0 * 0.88, 1.0)
    _close(fallback[2] / fallback[3], 21.0 / 9.0, 0.01)

    targets = gaze_calibration.calibration_target_points(rect)
    assert len(targets) == 5
    assert targets[0] == (left + width * 0.5, top + height * 0.5)
    assert targets[1] == (left + width * 0.2, top + height * 0.2)
    assert targets[4] == (left + width * 0.2, top + height * 0.8)


def test_sample_reduction_and_affine_recovery() -> None:
    stable = [(102.0 + (index % 3), 198.0 + (index % 2)) for index in range(80)]
    stable.extend([(8000.0, -5000.0), (-9000.0, 7000.0)])
    reduced = gaze_calibration.reduce_target_samples(stable)
    assert reduced is not None
    _close(reduced.point[0], 103.0, 2.0)
    _close(reduced.point[1], 198.5, 2.0)

    area = (100.0, 50.0, 2800.0, 1200.0)
    targets = gaze_calibration.calibration_target_points(area)
    observed = [
        ((target[0] - 140.0) / 1.04, (target[1] + 75.0) / 0.97)
        for target in targets
    ]
    result = gaze_calibration.solve_calibration(
        observed_points=observed,
        target_points=targets,
        display=gaze_calibration.DisplayDescriptor(
            identity="DISPLAY-A",
            geometry=(0, 0, 5120, 1440),
            physical_size_mm=(1197.0, 337.0),
        ),
        calibration_rect=area,
        completed_at="2026-07-16T12:00:00+02:00",
    )
    assert result.accepted
    assert result.transform is not None
    assert result.quality in {"Good", "Usable"}
    corrected = result.transform.apply(observed[0])
    _close(corrected[0], targets[0][0], 2.0)
    _close(corrected[1], targets[0][1], 2.0)


def test_rejection_translation_fallback_and_display_matching() -> None:
    area = (0.0, 0.0, 2800.0, 1200.0)
    targets = gaze_calibration.calibration_target_points(area)
    translated = [(point[0] - 110.0, point[1] + 65.0) for point in targets]
    display = gaze_calibration.DisplayDescriptor(
        identity="DISPLAY-A",
        geometry=(0, 0, 5120, 1440),
        physical_size_mm=(1197.0, 337.0),
    )
    original_solver = gaze_calibration._solve_affine_coefficients
    gaze_calibration._solve_affine_coefficients = lambda *_args, **_kwargs: None
    try:
        fallback = gaze_calibration.solve_calibration(
            observed_points=translated,
            target_points=targets,
            display=display,
            calibration_rect=area,
            completed_at="2026-07-16T12:00:00+02:00",
        )
    finally:
        gaze_calibration._solve_affine_coefficients = original_solver
    assert fallback.accepted
    assert fallback.transform is not None
    assert fallback.quality == "Fair"
    payload = fallback.transform.to_payload()
    restored = gaze_calibration.calibration_from_payload(payload, display=display)
    assert restored is not None
    mismatch = gaze_calibration.calibration_from_payload(
        payload,
        display=gaze_calibration.DisplayDescriptor(
            identity="DISPLAY-B",
            geometry=(0, 0, 5120, 1440),
            physical_size_mm=(1197.0, 337.0),
        ),
    )
    assert mismatch is None

    unsafe = [(point[0] * 0.2, point[1] * 2.4) for point in targets]
    rejected = gaze_calibration.solve_calibration(
        observed_points=unsafe,
        target_points=targets,
        display=display,
        calibration_rect=area,
        completed_at="2026-07-16T12:00:00+02:00",
    )
    assert not rejected.accepted
    assert rejected.transform is None


def _clear_pointer_policy(
    policy: pointer_clearance.PointerClearancePolicy,
    *,
    baseline: tuple[float, float],
    bounds: tuple[float, float, float, float],
    now: float,
) -> None:
    for sample_at in (now, now + 0.3):
        policy.update(
            normal_target=baseline,
            current_top_left=baseline,
            pointer=(1300.0, 800.0),
            screen_bounds=bounds,
            orb_size=92.0,
            move_distance_px=160.0,
            timeout_seconds=8.0,
            now=sample_at,
            enabled=True,
            suspended=False,
        )


def test_pointer_clearance_hysteresis_and_timeout() -> None:
    policy = pointer_clearance.PointerClearancePolicy()
    bounds = (0.0, 0.0, 1920.0, 1080.0)
    baseline = (900.0, 450.0)

    first = policy.update(
        normal_target=baseline,
        current_top_left=baseline,
        pointer=(946.0, 496.0),
        screen_bounds=bounds,
        orb_size=92.0,
        move_distance_px=160.0,
        timeout_seconds=8.0,
        now=1.0,
        enabled=True,
        suspended=False,
    )
    assert first.state == "avoiding"
    assert first.target != baseline
    assert math.dist(
        (first.target[0] + 46.0, first.target[1] + 46.0),
        (946.0, 496.0),
    ) > 78.0

    held = policy.update(
        normal_target=baseline,
        current_top_left=first.target,
        pointer=(946.0, 496.0),
        screen_bounds=bounds,
        orb_size=92.0,
        move_distance_px=160.0,
        timeout_seconds=8.0,
        now=1.4,
        enabled=True,
        suspended=False,
    )
    assert held.state == "avoiding"

    _clear_pointer_policy(policy, baseline=baseline, bounds=bounds, now=2.0)
    assert policy.state == "clear"

    for entered_at in (3.0, 5.0):
        decision = policy.update(
            normal_target=baseline,
            current_top_left=baseline,
            pointer=(946.0, 496.0),
            screen_bounds=bounds,
            orb_size=92.0,
            move_distance_px=160.0,
            timeout_seconds=8.0,
            now=entered_at,
            enabled=True,
            suspended=False,
        )
        if entered_at == 3.0:
            assert decision.state == "avoiding"
            _clear_pointer_policy(
                policy,
                baseline=baseline,
                bounds=bounds,
                now=entered_at + 0.1,
            )

    timed_out = policy.update(
        normal_target=baseline,
        current_top_left=baseline,
        pointer=(946.0, 496.0),
        screen_bounds=bounds,
        orb_size=92.0,
        move_distance_px=160.0,
        timeout_seconds=8.0,
        now=6.0,
        enabled=True,
        suspended=False,
    )
    assert timed_out.state == "timeout"
    assert timed_out.opacity == 0.0
    resumed = policy.update(
        normal_target=(1000.0, 500.0),
        current_top_left=timed_out.target,
        pointer=(1300.0, 800.0),
        screen_bounds=bounds,
        orb_size=92.0,
        move_distance_px=160.0,
        timeout_seconds=8.0,
        now=14.1,
        enabled=True,
        suspended=False,
    )
    assert resumed.state == "clear"
    assert resumed.target == (1000.0, 500.0)


class _FakeClock:
    def __init__(self, value: float = 10.0) -> None:
        self.value = float(value)

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += float(seconds)


def test_calibration_overlay_timing_and_shutdown() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    clock = _FakeClock()
    overlay = gaze_calibration_overlay.GazeCalibrationOverlay(clock=clock)
    rect = (300.0, 150.0, 1320.0, 660.0)
    targets = gaze_calibration.calibration_target_points(rect)
    elapsed: list[int] = []
    overlay.target_elapsed.connect(elapsed.append)

    overlay.begin(
        screen_geometry=(0, 0, 1920, 1080),
        calibration_rect=rect,
        targets=targets,
        theme_color="#22d3ee",
    )
    app.processEvents()

    assert overlay.geometry() == QtCore.QRect(0, 0, 1920, 1080)
    assert overlay.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
    assert bool(overlay.windowFlags() & QtCore.Qt.WindowTransparentForInput)
    assert bool(overlay.windowFlags() & QtCore.Qt.FramelessWindowHint)
    assert bool(overlay.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)
    assert overlay.target_index == 0
    assert overlay.target_point == targets[0]
    assert overlay.isVisible()
    assert overlay.settling

    clock.advance(0.5)
    overlay.update_progress()
    assert elapsed == []
    assert overlay.settling
    _close(overlay.progress, 0.5 / 3.0, 0.01)

    clock.advance(2.6)
    overlay.update_progress()
    assert elapsed == [0]
    assert not overlay.settling
    assert overlay.progress == 1.0
    overlay.update_progress()
    assert elapsed == [0]

    overlay.show_target(1)
    assert overlay.target_index == 1
    assert overlay.target_point == targets[1]
    assert overlay.settling
    overlay.restart_target("Hold gaze steady")
    assert overlay.message == "Hold gaze steady"
    assert overlay.target_index == 1
    assert overlay.progress == 0.0

    overlay.finish()
    app.processEvents()
    assert not overlay.isVisible()
    assert not overlay.timer_active
    overlay.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    test_supported_area_and_targets()
    test_sample_reduction_and_affine_recovery()
    test_rejection_translation_fallback_and_display_matching()
    test_pointer_clearance_hysteresis_and_timeout()
    test_calibration_overlay_timing_and_shutdown()
    print("smoke_companion_orb_eye_calibration: ok")
