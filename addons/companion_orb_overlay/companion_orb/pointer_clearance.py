from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Sequence


_INTERFERENCE_WINDOW_SECONDS = 8.0
_INTERFERENCE_LIMIT = 3
_RELEASE_HOLD_SECONDS = 0.25


def _point(values: Sequence[float]) -> tuple[float, float] | None:
    try:
        items = list(values or [])[:2]
        result = float(items[0]), float(items[1])
    except (IndexError, TypeError, ValueError, OverflowError):
        return None
    return result if all(math.isfinite(value) for value in result) else None


def _bounds(values: Sequence[float]) -> tuple[float, float, float, float] | None:
    try:
        items = list(values or [])[:4]
        result = tuple(float(value) for value in items)
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        len(result) != 4
        or not all(math.isfinite(value) for value in result)
        or result[2] <= 0.0
        or result[3] <= 0.0
    ):
        return None
    return result


@dataclass(frozen=True, slots=True)
class PointerClearanceDecision:
    target: tuple[float, float]
    state: str
    opacity: float
    changed: bool


class PointerClearancePolicy:
    def __init__(self) -> None:
        self._state = "clear"
        self._avoid_target: tuple[float, float] | None = None
        self._release_started_at: float | None = None
        self._interference_times: deque[float] = deque()
        self._timeout_until = 0.0

    @property
    def state(self) -> str:
        return self._state

    def reset(self) -> None:
        self._state = "clear"
        self._avoid_target = None
        self._release_started_at = None
        self._interference_times.clear()
        self._timeout_until = 0.0

    def _decision(
        self,
        target: tuple[float, float],
        *,
        previous_state: str,
        opacity: float = 1.0,
    ) -> PointerClearanceDecision:
        return PointerClearanceDecision(
            target=target,
            state=self._state,
            opacity=max(0.0, min(1.0, float(opacity))),
            changed=self._state != previous_state,
        )

    @staticmethod
    def _clamp_target(
        target: tuple[float, float],
        *,
        screen_bounds: tuple[float, float, float, float],
        orb_size: float,
    ) -> tuple[float, float]:
        left, top, width, height = screen_bounds
        size = max(1.0, float(orb_size))
        right = left + width
        bottom = top + height
        return (
            max(left, min(float(target[0]), max(left, right - size))),
            max(top, min(float(target[1]), max(top, bottom - size))),
        )

    @classmethod
    def _avoidance_target(
        cls,
        normal_target: tuple[float, float],
        *,
        pointer: tuple[float, float],
        screen_bounds: tuple[float, float, float, float],
        orb_size: float,
        move_distance_px: float,
    ) -> tuple[float, float]:
        size = max(1.0, float(orb_size))
        distance_limit = max(0.0, min(1000.0, float(move_distance_px)))
        normal_center = (
            normal_target[0] + size * 0.5,
            normal_target[1] + size * 0.5,
        )
        dx = normal_center[0] - pointer[0]
        dy = normal_center[1] - pointer[1]
        if math.hypot(dx, dy) <= 1e-6:
            base_angle = -math.pi * 0.5
        else:
            base_angle = math.atan2(dy, dx)
        angle_offsets = (
            0.0,
            math.pi * 0.25,
            -math.pi * 0.25,
            math.pi * 0.5,
            -math.pi * 0.5,
            math.pi * 0.75,
            -math.pi * 0.75,
            math.pi,
        )
        candidates: list[tuple[float, float]] = []
        for offset in angle_offsets:
            angle = base_angle + offset
            candidate = (
                normal_target[0] + math.cos(angle) * distance_limit,
                normal_target[1] + math.sin(angle) * distance_limit,
            )
            candidates.append(
                cls._clamp_target(
                    candidate,
                    screen_bounds=screen_bounds,
                    orb_size=size,
                )
            )

        def score(candidate: tuple[float, float]) -> tuple[float, float]:
            center = candidate[0] + size * 0.5, candidate[1] + size * 0.5
            pointer_distance = math.hypot(
                center[0] - pointer[0],
                center[1] - pointer[1],
            )
            displacement = math.hypot(
                candidate[0] - normal_target[0],
                candidate[1] - normal_target[1],
            )
            return pointer_distance, -displacement

        return max(candidates, key=score)

    def _prune_interference_times(self, now: float) -> None:
        threshold = float(now) - _INTERFERENCE_WINDOW_SECONDS
        while self._interference_times and self._interference_times[0] < threshold:
            self._interference_times.popleft()

    def update(
        self,
        *,
        normal_target: Sequence[float],
        current_top_left: Sequence[float],
        pointer: Sequence[float],
        screen_bounds: Sequence[float],
        orb_size: float,
        move_distance_px: float,
        timeout_seconds: float,
        now: float,
        enabled: bool,
        suspended: bool,
    ) -> PointerClearanceDecision:
        normal = _point(normal_target)
        current = _point(current_top_left)
        cursor = _point(pointer)
        bounds = _bounds(screen_bounds)
        try:
            sample_at = float(now)
            size = max(1.0, float(orb_size))
            move_distance = max(0.0, min(1000.0, float(move_distance_px)))
            timeout = max(0.1, min(300.0, float(timeout_seconds)))
        except (TypeError, ValueError, OverflowError):
            normal = None
        if (
            normal is None
            or current is None
            or cursor is None
            or bounds is None
            or not math.isfinite(sample_at)
        ):
            previous = self._state
            self.reset()
            fallback = normal or current or (0.0, 0.0)
            return self._decision(fallback, previous_state=previous)

        normal = self._clamp_target(normal, screen_bounds=bounds, orb_size=size)
        current = self._clamp_target(current, screen_bounds=bounds, orb_size=size)
        previous_state = self._state
        if not bool(enabled) or bool(suspended):
            self.reset()
            return self._decision(normal, previous_state=previous_state)

        if self._state == "timeout":
            if sample_at < self._timeout_until:
                return self._decision(
                    current,
                    previous_state=previous_state,
                    opacity=0.0,
                )
            self.reset()
            return self._decision(normal, previous_state=previous_state)

        trigger_radius = size * 0.5 + 32.0
        release_radius = trigger_radius + max(24.0, move_distance * 0.15)
        current_center = current[0] + size * 0.5, current[1] + size * 0.5
        normal_center = normal[0] + size * 0.5, normal[1] + size * 0.5
        current_distance = math.hypot(
            current_center[0] - cursor[0],
            current_center[1] - cursor[1],
        )
        normal_distance = math.hypot(
            normal_center[0] - cursor[0],
            normal_center[1] - cursor[1],
        )

        if self._state == "clear" and current_distance < trigger_radius:
            self._prune_interference_times(sample_at)
            self._interference_times.append(sample_at)
            if len(self._interference_times) >= _INTERFERENCE_LIMIT:
                self._state = "timeout"
                self._timeout_until = sample_at + timeout
                self._avoid_target = None
                self._release_started_at = None
                return self._decision(
                    current,
                    previous_state=previous_state,
                    opacity=0.0,
                )
            self._state = "avoiding"
            self._release_started_at = None

        if self._state == "avoiding":
            if normal_distance > release_radius:
                if self._release_started_at is None:
                    self._release_started_at = sample_at
                elif sample_at - self._release_started_at >= _RELEASE_HOLD_SECONDS:
                    self._state = "clear"
                    self._avoid_target = None
                    self._release_started_at = None
                    return self._decision(normal, previous_state=previous_state)
            else:
                self._release_started_at = None
            self._avoid_target = self._avoidance_target(
                normal,
                pointer=cursor,
                screen_bounds=bounds,
                orb_size=size,
                move_distance_px=move_distance,
            )
            return self._decision(
                self._avoid_target,
                previous_state=previous_state,
            )

        self._state = "clear"
        self._avoid_target = None
        self._release_started_at = None
        return self._decision(normal, previous_state=previous_state)
