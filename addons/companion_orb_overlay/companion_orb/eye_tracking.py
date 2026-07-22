from __future__ import annotations

import ctypes
import math
import os
import re
import threading
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence


TRACKING_MODES = ("dwell", "continuous", "manual", "off")
REACTION_MODES = ("meaningful", "every_dwell", "off")

_TRACKING_MODE_ALIASES = {
    "dwell": "dwell",
    "dwell_focus": "dwell",
    "dwell focus": "dwell",
    "continuous": "continuous",
    "continuous_follow": "continuous",
    "continuous follow": "continuous",
    "follow": "continuous",
    "manual": "manual",
    "manual_only": "manual",
    "manual only": "manual",
    "off": "off",
    "disabled": "off",
    "none": "off",
}

_REACTION_MODE_ALIASES = {
    "meaningful": "meaningful",
    "meaningful_changes": "meaningful",
    "meaningful changes": "meaningful",
    "every_dwell": "every_dwell",
    "every dwell": "every_dwell",
    "every": "every_dwell",
    "off": "off",
    "disabled": "off",
    "none": "off",
}


def normalize_tracking_mode(value) -> str:
    key = str(value or "").strip().lower()
    return _TRACKING_MODE_ALIASES.get(key, "dwell")


def normalize_reaction_mode(value) -> str:
    key = str(value or "").strip().lower()
    return _REACTION_MODE_ALIASES.get(key, "meaningful")


def gaze_timer_visual_progress(
    *,
    hold_seconds: float,
    dwell_ms: int,
    long_dwell_ms: int,
    long_gaze_enabled: bool,
) -> float:
    hold = max(0.0, float(hold_seconds))
    short_seconds = max(0.05, float(dwell_ms) / 1000.0)
    if not bool(long_gaze_enabled):
        return min(1.0, hold / short_seconds)
    long_seconds = max(short_seconds + 0.25, float(long_dwell_ms) / 1000.0)
    if hold <= short_seconds:
        return min(0.6, (hold / short_seconds) * 0.6)
    long_progress = (hold - short_seconds) / (long_seconds - short_seconds)
    return min(1.0, 0.6 + max(0.0, long_progress) * 0.4)


@dataclass(frozen=True, slots=True)
class GazeDecision:
    point: tuple[float, float]
    stable: bool
    dwell_triggered: bool
    hold_seconds: float = 0.0
    dwell_progress: float = 0.0
    long_dwell_triggered: bool = False


@dataclass(frozen=True, slots=True)
class BlinkGesture:
    closed_ms: float
    ended_at: float


@dataclass(frozen=True, slots=True)
class BlinkClickDecision:
    action: str
    enabled: bool


@dataclass(frozen=True, slots=True)
class EyeCommandDecision:
    action: str


@dataclass(frozen=True, slots=True)
class GazeStreamEvent:
    valid: bool
    position: tuple[float, float] | None = None
    timestamp_us: int = 0


@dataclass(frozen=True, slots=True)
class ClickTarget:
    label: str
    bounds: tuple[int, int, int, int]
    kind: str = ""
    confidence: float = 0.0
    role: str = ""
    source: str = ""
    semantic: bool = False
    runtime_id: tuple[int, ...] = ()
    click_point: tuple[float, float] | None = None

    def __post_init__(self) -> None:
        normalized: tuple[float, float] | None = None
        value = self.click_point
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            try:
                values = tuple(value)
                if len(values) == 2:
                    point = float(values[0]), float(values[1])
                    if all(math.isfinite(coordinate) for coordinate in point):
                        normalized = point
            except (TypeError, ValueError, OverflowError):
                pass
        object.__setattr__(self, "click_point", None if self.semantic else normalized)

    @property
    def center(self) -> tuple[float, float]:
        if self.click_point is not None:
            return self.click_point
        left, top, width, height = self.bounds
        return left + width * 0.5, top + height * 0.5

    @property
    def display_label(self) -> str:
        name = re.sub(r"\s+", " ", self.label).strip()
        role = re.sub(r"\s+", " ", self.role).strip()
        return f"{role} - {name}" if role and name else name


@dataclass(frozen=True, slots=True)
class ClickTargetSet:
    direct: tuple[ClickTarget, ...] = ()
    visual: tuple[ClickTarget, ...] = ()


def is_semantic_direct_target(target: object) -> bool:
    return (
        isinstance(target, ClickTarget)
        and bool(_normalized_text(target.label))
        and bool(target.semantic)
        and _normalized_text(target.source).casefold() == "uia"
        and bool(target.runtime_id)
        and target.click_point is None
    )


def _target_geometry(
    capture_bounds: Sequence[int],
    focus_point: Sequence[float],
) -> tuple[tuple[int, int, int, int], tuple[float, float]] | None:
    try:
        capture_left, capture_top, capture_width, capture_height = (
            int(value) for value in list(capture_bounds)[:4]
        )
        focus_x, focus_y = (float(value) for value in list(focus_point)[:2])
    except (TypeError, ValueError):
        return None
    if capture_width <= 0 or capture_height <= 0 or not all(
        math.isfinite(value) for value in (focus_x, focus_y)
    ):
        return None
    return (capture_left, capture_top, capture_width, capture_height), (focus_x, focus_y)


def _clip_target_bounds(
    bounds: Sequence[int],
    capture: tuple[int, int, int, int],
) -> tuple[int, int, int, int] | None:
    try:
        left, top, width, height = (int(value) for value in list(bounds)[:4])
    except (TypeError, ValueError):
        return None
    capture_left, capture_top, capture_width, capture_height = capture
    right = min(capture_left + capture_width, left + width)
    bottom = min(capture_top + capture_height, top + height)
    clipped_left = max(capture_left, left)
    clipped_top = max(capture_top, top)
    clipped_width = right - clipped_left
    clipped_height = bottom - clipped_top
    if clipped_width < 8 or clipped_height < 6:
        return None
    return clipped_left, clipped_top, clipped_width, clipped_height


def _normalized_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _region_target(
    region: Mapping,
    bounds: tuple[int, int, int, int],
    *,
    visual: bool,
) -> ClickTarget:
    kind = _normalized_text(region.get("kind")).lower()
    label = _normalized_text(region.get("text"))[:34].strip()
    role = _normalized_text(region.get("role"))
    source = _normalized_text(region.get("source")).lower()
    if not source:
        source = "win32" if kind in {"button", "link", "control", "control_text"} else "ocr"
    try:
        confidence = max(0.0, min(1.0, float(region.get("confidence", 0.0) or 0.0)))
    except (TypeError, ValueError):
        confidence = 0.0
    return ClickTarget(
        label=label,
        bounds=bounds,
        kind=kind,
        confidence=confidence,
        role=role,
        source=source,
        semantic=bool(region.get("semantic", False)) and not visual,
    )


def _bounds_overlap(first: ClickTarget, second: ClickTarget) -> bool:
    first_left, first_top, first_width, first_height = first.bounds
    second_left, second_top, second_width, second_height = second.bounds
    intersection_width = max(
        0,
        min(first_left + first_width, second_left + second_width) - max(first_left, second_left),
    )
    intersection_height = max(
        0,
        min(first_top + first_height, second_top + second_height) - max(first_top, second_top),
    )
    intersection = intersection_width * intersection_height
    if not intersection:
        return False
    first_area = first_width * first_height
    second_area = second_width * second_height
    return intersection / float(min(first_area, second_area)) >= 0.6


def _target_duplicate(first: ClickTarget, second: ClickTarget) -> bool:
    first_label = _normalized_text(first.label).casefold()
    second_label = _normalized_text(second.label).casefold()
    if not first_label or first_label != second_label:
        return first.bounds == second.bounds and not first_label and not second_label
    first_role = _normalized_text(first.role).casefold()
    second_role = _normalized_text(second.role).casefold()
    if first_role and second_role and first_role != second_role:
        return False
    return _bounds_overlap(first, second)


def _normalized_limit(value, maximum: int, default: int) -> int:
    try:
        return max(1, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _target_score(target: ClickTarget, focus: tuple[float, float], *, direct: bool) -> float:
    distance = math.hypot(target.center[0] - focus[0], target.center[1] - focus[1])
    area = float(target.bounds[2] * target.bounds[3])
    kind_bonus = {
        "control_text": 220.0,
        "button": 210.0,
        "link": 200.0,
        "line": 140.0,
        "text_region": 80.0,
        "word": 30.0,
        "window_title": 10.0,
    }.get(target.kind, 60.0)
    source_bonus = {
        "uia": 420.0,
        "win32": 220.0,
        "native": 220.0,
        "ocr": 80.0,
    }.get(target.source, 0.0)
    semantic_bonus = 180.0 if target.semantic else 0.0
    role_bonus = 55.0 if target.role else 0.0
    return (
        source_bonus
        + semantic_bonus
        + role_bonus
        + kind_bonus
        + target.confidence * 80.0
        + min(90.0, area / 260.0)
        - min(260.0, distance * 0.42)
        if direct
        else kind_bonus + target.confidence * 80.0 + min(90.0, area / 260.0) - min(260.0, distance * 0.42)
    )


def _select_targets(
    candidates: Sequence[ClickTarget],
    focus: tuple[float, float],
    limit: int,
    *,
    direct: bool,
) -> tuple[ClickTarget, ...]:
    ranked = sorted(
        candidates,
        key=lambda target: (
            -_target_score(target, focus, direct=direct),
            target.center[1],
            target.center[0],
            target.label.casefold(),
        ),
    )
    selected: list[ClickTarget] = []
    target_limit = _normalized_limit(limit, 12 if not direct else 8, 12 if not direct else 8)
    for target in ranked:
        if any(_target_duplicate(target, existing) for existing in selected):
            continue
        selected.append(target)
        if len(selected) >= target_limit:
            break
    return tuple(selected)


def _rank_visual_targets(
    regions,
    *,
    focus_point: Sequence[float],
    capture_bounds: Sequence[int],
    limit: int = 8,
) -> tuple[ClickTarget, ...]:
    geometry = _target_geometry(capture_bounds, focus_point)
    if geometry is None:
        return ()
    capture, focus = geometry
    capture_area = float(capture[2] * capture[3])
    candidates: list[ClickTarget] = []
    for region in list(regions or []):
        if not isinstance(region, Mapping):
            continue
        bounds = _clip_target_bounds(region.get("screen_bounds") or (), capture)
        if bounds is None:
            continue
        area = float(bounds[2] * bounds[3])
        kind = _normalized_text(region.get("kind")).lower()
        if area >= capture_area * 0.45 or (kind == "window_title" and area >= capture_area * 0.12):
            continue
        candidates.append(_region_target(region, bounds, visual=True))
    return _select_targets(candidates, focus, limit, direct=False)


def _target_contains_point(target: ClickTarget, point: tuple[float, float]) -> bool:
    left, top, width, height = target.bounds
    return left <= point[0] <= left + width and top <= point[1] <= top + height


def _zoom_tiles(
    capture: tuple[int, int, int, int],
    focus: tuple[float, float],
    limit: int,
) -> tuple[ClickTarget, ...]:
    capture_left, capture_top, capture_width, capture_height = capture
    if capture_width < 8 or capture_height < 6:
        return ()
    tile_width = min(capture_width, max(8, (capture_width + 1) // 2))
    tile_height = min(capture_height, max(6, (capture_height + 1) // 2))
    x_positions = (
        capture_left,
        capture_left + (capture_width - tile_width) // 2,
        capture_left + capture_width - tile_width,
    )
    y_positions = (
        capture_top,
        capture_top + (capture_height - tile_height) // 2,
        capture_top + capture_height - tile_height,
    )
    tiles: list[ClickTarget] = []
    seen_bounds: set[tuple[int, int, int, int]] = set()
    for top in dict.fromkeys(y_positions):
        for left in dict.fromkeys(x_positions):
            bounds = _clip_target_bounds((left, top, tile_width, tile_height), capture)
            if bounds is None or bounds in seen_bounds:
                continue
            seen_bounds.add(bounds)
            tiles.append(ClickTarget(label="", bounds=bounds, kind="zoom_tile", source="visual"))
    return tuple(
        sorted(
            tiles,
            key=lambda target: (
                not _target_contains_point(target, focus),
                math.hypot(target.center[0] - focus[0], target.center[1] - focus[1]),
                target.center[1],
                target.center[0],
            ),
        )[: _normalized_limit(limit, 12, 12)]
    )


def aggregate_click_targets(
    *,
    semantic_targets: Sequence[ClickTarget] | None = None,
    regions=None,
    focus_point: Sequence[float],
    capture_bounds: Sequence[int],
    direct_limit: int = 8,
    visual_limit: int = 12,
) -> ClickTargetSet:
    geometry = _target_geometry(capture_bounds, focus_point)
    if geometry is None:
        return ClickTargetSet()
    capture, focus = geometry
    direct_cap = _normalized_limit(direct_limit, 8, 8)
    visual_cap = _normalized_limit(visual_limit, 12, 12)
    direct_candidates: list[ClickTarget] = []
    visual_candidates: list[ClickTarget] = []
    for target in list(semantic_targets or []):
        if not isinstance(target, ClickTarget):
            continue
        try:
            bounds = tuple(int(value) for value in target.bounds)
        except (TypeError, ValueError):
            continue
        if len(bounds) != 4 or bounds[2] <= 0 or bounds[3] <= 0:
            continue
        left, top, width, height = bounds
        capture_left, capture_top, capture_width, capture_height = capture
        if not (
            left < capture_left + capture_width
            and capture_left < left + width
            and top < capture_top + capture_height
            and capture_top < top + height
        ):
            continue
        center_x, center_y = target.center
        if not (
            capture_left <= center_x < capture_left + capture_width
            and capture_top <= center_y < capture_top + capture_height
        ):
            continue
        if is_semantic_direct_target(target):
            direct_candidates.append(target)
        else:
            visual_candidates.append(replace(target, semantic=False))

    capture_area = float(capture[2] * capture[3])
    for region in list(regions or []):
        if not isinstance(region, Mapping):
            continue
        bounds = _clip_target_bounds(region.get("screen_bounds") or (), capture)
        if bounds is None:
            continue
        target = _region_target(region, bounds, visual=False)
        area = float(bounds[2] * bounds[3])
        kind = target.kind
        if area >= capture_area * 0.45 or (kind == "window_title" and area >= capture_area * 0.12):
            continue
        visual_candidates.append(replace(target, semantic=False))

    direct = _select_targets(direct_candidates, focus, direct_cap, direct=True)
    visual_candidates = [
        target
        for target in visual_candidates
        if not any(_target_duplicate(target, direct_target) for direct_target in direct)
    ]
    visual = list(_select_targets(visual_candidates, focus, visual_cap, direct=False))
    focus_visual_index = next(
        (index for index, target in enumerate(visual) if _target_contains_point(target, focus)),
        None,
    )
    if focus_visual_index is not None:
        visual[focus_visual_index] = replace(
            visual[focus_visual_index],
            click_point=focus,
        )
    neighborhood_radius = max(160.0, max(capture[2], capture[3]) * 0.4)
    add_nearby_tiles = not visual or not any(
        math.hypot(target.center[0] - focus[0], target.center[1] - focus[1]) <= neighborhood_radius
        for target in visual
    )
    add_focus_tile = focus_visual_index is None
    if add_focus_tile or add_nearby_tiles:
        fallback_tiles = _zoom_tiles(capture, focus, visual_cap)
        focus_tile = next(
            (tile for tile in fallback_tiles if _target_contains_point(tile, focus)),
            None,
        )
        if focus_tile is not None:
            focus_tile = replace(focus_tile, click_point=focus)
        if add_focus_tile and focus_tile is not None and not any(
            focus_tile.bounds == existing.bounds for existing in visual
        ):
            if len(visual) >= visual_cap:
                visual.pop()
            visual.append(focus_tile)
        if add_nearby_tiles:
            for tile in fallback_tiles:
                if len(visual) >= visual_cap:
                    break
                if (
                    (focus_tile is not None and tile.bounds == focus_tile.bounds)
                    or any(tile.bounds == existing.bounds for existing in visual)
                ):
                    continue
                visual.append(tile)
    return ClickTargetSet(direct=direct, visual=tuple(visual))


def rank_click_targets(
    regions,
    *,
    focus_point: Sequence[float],
    capture_bounds: Sequence[int],
    limit: int = 8,
) -> tuple[ClickTarget, ...]:
    """Return the legacy visual ranking result for unmigrated callers."""
    named_regions = [
        region
        for region in list(regions or [])
        if isinstance(region, Mapping) and _normalized_text(region.get("text"))
    ]
    return _rank_visual_targets(
        named_regions,
        focus_point=focus_point,
        capture_bounds=capture_bounds,
        limit=limit,
    )


class BlinkGestureDetector:
    """Classify short explicit validity gaps without treating stream loss as a blink."""

    def __init__(
        self,
        *,
        minimum_closed_ms: int = 80,
        maximum_closed_ms: int = 900,
        recovery_ms: int = 80,
        stable_before_ms: int = 100,
    ):
        self.minimum_closed_seconds = max(0.02, float(minimum_closed_ms) / 1000.0)
        self.maximum_closed_seconds = max(
            self.minimum_closed_seconds + 0.02,
            float(maximum_closed_ms) / 1000.0,
        )
        self.recovery_seconds = max(0.02, float(recovery_ms) / 1000.0)
        self.stable_before_seconds = max(0.02, float(stable_before_ms) / 1000.0)
        self.reset()

    def reset(self) -> None:
        self._valid: bool | None = None
        self._valid_since: float | None = None
        self._closed_at: float | None = None
        self._pending_closed_seconds: float | None = None
        self._pending_ended_at: float | None = None

    def ingest_validity(self, valid: bool, *, now: float) -> None:
        sample_at = float(now)
        current = bool(valid)
        if current == self._valid:
            return
        previous = self._valid
        self._valid = current
        if current:
            self._valid_since = sample_at
            if previous is False and self._closed_at is not None:
                closed_seconds = max(0.0, sample_at - self._closed_at)
                if self.minimum_closed_seconds <= closed_seconds <= self.maximum_closed_seconds:
                    self._pending_closed_seconds = closed_seconds
                    self._pending_ended_at = sample_at
                else:
                    self._pending_closed_seconds = None
                    self._pending_ended_at = None
            self._closed_at = None
            return

        stable_before = (
            previous is True
            and self._valid_since is not None
            and sample_at - self._valid_since + 1e-9 >= self.stable_before_seconds
        )
        self._closed_at = sample_at if stable_before else None
        self._valid_since = None
        self._pending_closed_seconds = None
        self._pending_ended_at = None

    def ingest_valid_sample(self, *, now: float) -> BlinkGesture | None:
        sample_at = float(now)
        if self._valid is not True or self._valid_since is None:
            return None
        closed_seconds = self._pending_closed_seconds
        ended_at = self._pending_ended_at
        if closed_seconds is None or ended_at is None:
            return None
        if sample_at - self._valid_since + 1e-9 < self.recovery_seconds:
            return None
        self._pending_closed_seconds = None
        self._pending_ended_at = None
        return BlinkGesture(
            closed_ms=closed_seconds * 1000.0,
            ended_at=ended_at,
        )


class BlinkClickPolicy:
    """Keep blink-click disabled until an armed slow double blink enables it."""

    def __init__(
        self,
        *,
        slow_blink_minimum_ms: int = 260,
        double_blink_gap_ms: int = 1200,
        click_cooldown_ms: int = 450,
        activation_arm_ms: int = 3500,
    ):
        self.slow_blink_minimum_ms = max(80.0, float(slow_blink_minimum_ms))
        self.double_blink_gap_seconds = max(0.20, float(double_blink_gap_ms) / 1000.0)
        self.click_cooldown_seconds = max(0.10, float(click_cooldown_ms) / 1000.0)
        self.activation_arm_seconds = max(0.50, float(activation_arm_ms) / 1000.0)
        self.enabled = False
        self._activation_armed_until = 0.0
        self._pending_slow_blink_at: float | None = None
        self._last_click_at: float | None = None

    def reset(self) -> None:
        self.enabled = False
        self._activation_armed_until = 0.0
        self._pending_slow_blink_at = None
        self._last_click_at = None

    def arm_activation(self, *, now: float) -> None:
        if not self.enabled:
            self._activation_armed_until = max(
                self._activation_armed_until,
                float(now) + self.activation_arm_seconds,
            )

    def ingest_blink(
        self,
        closed_ms: float,
        *,
        now: float,
        menu_visible: bool,
    ) -> BlinkClickDecision:
        sample_at = float(now)
        slow = float(closed_ms) + 1e-9 >= self.slow_blink_minimum_ms
        if not slow:
            self._pending_slow_blink_at = None
            if not self.enabled or bool(menu_visible):
                return BlinkClickDecision("none", self.enabled)
            if (
                self._last_click_at is not None
                and sample_at - self._last_click_at < self.click_cooldown_seconds
            ):
                return BlinkClickDecision("none", self.enabled)
            self._last_click_at = sample_at
            return BlinkClickDecision("click", True)

        activation_armed = sample_at <= self._activation_armed_until
        if not self.enabled and not activation_armed:
            self._pending_slow_blink_at = None
            return BlinkClickDecision("none", False)

        previous = self._pending_slow_blink_at
        if previous is None or sample_at - previous > self.double_blink_gap_seconds:
            self._pending_slow_blink_at = sample_at
            return BlinkClickDecision("none", self.enabled)

        self._pending_slow_blink_at = None
        self._activation_armed_until = 0.0
        self.enabled = not self.enabled
        self._last_click_at = sample_at if self.enabled else None
        return BlinkClickDecision("enable" if self.enabled else "disable", self.enabled)


class EyeCommandPolicy:
    """Classify named eye commands before blink-click handling."""

    def __init__(
        self,
        *,
        fast_blink_maximum_ms: int = 260,
        blink_maximum_ms: int = 900,
        menu_toggle_minimum_ms: int = 1000,
        menu_toggle_maximum_ms: int = 2000,
        triple_blink_gap_ms: int = 450,
        back_cooldown_ms: int = 1500,
    ):
        self.fast_blink_maximum_ms = max(80.0, float(fast_blink_maximum_ms))
        self.blink_maximum_ms = max(
            self.fast_blink_maximum_ms + 20.0,
            float(blink_maximum_ms),
        )
        self.menu_toggle_minimum_ms = max(
            self.blink_maximum_ms + 20.0,
            float(menu_toggle_minimum_ms),
        )
        self.menu_toggle_maximum_ms = max(
            self.menu_toggle_minimum_ms + 20.0,
            float(menu_toggle_maximum_ms),
        )
        self.triple_blink_gap_seconds = max(0.15, float(triple_blink_gap_ms) / 1000.0)
        self.back_cooldown_seconds = max(0.25, float(back_cooldown_ms) / 1000.0)
        self.reset()

    def reset(self) -> None:
        self._pending_quick_blinks: list[BlinkGesture] = []
        self._last_back_at: float | None = None

    @property
    def pending_quick_deadline(self) -> float | None:
        if not self._pending_quick_blinks:
            return None
        return self._pending_quick_blinks[-1].ended_at + self.triple_blink_gap_seconds

    def ingest_blink(
        self,
        gesture: BlinkGesture,
        *,
        now: float,
        menu_visible: bool,
    ) -> EyeCommandDecision:
        sample_at = float(now)
        closed_ms = float(gesture.closed_ms)
        if self.menu_toggle_minimum_ms <= closed_ms <= self.menu_toggle_maximum_ms:
            self._pending_quick_blinks.clear()
            return EyeCommandDecision("long_gaze_toggle")

        if closed_ms > self.blink_maximum_ms:
            self._pending_quick_blinks.clear()
            return EyeCommandDecision("none")

        if closed_ms + 1e-9 >= self.fast_blink_maximum_ms:
            self._pending_quick_blinks.clear()
            return EyeCommandDecision("passthrough")

        pending = self._pending_quick_blinks
        if pending and sample_at - pending[-1].ended_at > self.triple_blink_gap_seconds:
            pending.clear()
        pending.append(BlinkGesture(closed_ms=closed_ms, ended_at=sample_at))
        if len(pending) < 3:
            return EyeCommandDecision("quick_pending")

        pending.clear()
        if (
            self._last_back_at is not None
            and sample_at - self._last_back_at < self.back_cooldown_seconds
        ):
            return EyeCommandDecision("none")
        self._last_back_at = sample_at
        return EyeCommandDecision("browser_back")

    def release_pending_quick(self, *, now: float) -> BlinkGesture | None:
        pending = self._pending_quick_blinks
        if not pending:
            return None
        sample_at = float(now)
        if sample_at - pending[-1].ended_at + 1e-9 < self.triple_blink_gap_seconds:
            return None
        released = pending[0] if len(pending) == 1 else None
        pending.clear()
        return released


class GazeScrollPolicy:
    """Convert vertical gaze displacement into rate-limited wheel movement."""

    def __init__(self, *, speed: int = 5, dead_zone_px: int = 100):
        self.speed = max(1, min(10, int(speed)))
        self.dead_zone_px = max(20.0, min(400.0, float(dead_zone_px)))
        self.reset()

    def reset(self) -> None:
        self._last_sample_at: float | None = None
        self._wheel_notch_remainder = 0.0

    def ingest(self, gaze_y: float, *, anchor_y: float, now: float) -> int:
        sample_at = float(now)
        previous_at = self._last_sample_at
        self._last_sample_at = sample_at
        displacement = float(gaze_y) - float(anchor_y)
        distance = abs(displacement)
        if distance <= self.dead_zone_px:
            self._wheel_notch_remainder = 0.0
            return 0
        if previous_at is None:
            return 0

        elapsed = max(0.0, min(0.5, sample_at - previous_at))
        intensity = min(1.0, (distance - self.dead_zone_px) / max(120.0, self.dead_zone_px * 2.5))
        notches_per_second = (1.5 + self.speed * 1.75) * max(0.18, intensity)
        self._wheel_notch_remainder += elapsed * notches_per_second
        whole_notches = int(self._wheel_notch_remainder)
        if whole_notches <= 0:
            return 0
        self._wheel_notch_remainder -= whole_notches
        direction = -1 if displacement > 0.0 else 1
        return direction * whole_notches * 120


class GazeFocusPolicy:
    """Smooth transient gaze samples and emit one event per stable focus."""

    def __init__(
        self,
        *,
        dwell_ms: int = 700,
        long_dwell_ms: int = 3000,
        radius_px: float = 60.0,
        smoothing: float = 0.28,
        sample_gap_seconds: float | None = None,
    ):
        self.dwell_seconds = max(0.05, float(dwell_ms) / 1000.0)
        requested_long_dwell = max(0.10, float(long_dwell_ms) / 1000.0)
        self.long_dwell_seconds = max(self.dwell_seconds + 0.25, requested_long_dwell)
        self.radius_px = max(1.0, float(radius_px))
        self.smoothing = max(0.01, min(1.0, float(smoothing)))
        self.sample_gap_seconds = (
            None
            if sample_gap_seconds is None
            else max(0.10, min(2.0, float(sample_gap_seconds)))
        )
        self._point: tuple[float, float] | None = None
        self._candidate_anchor: tuple[float, float] | None = None
        self._candidate_started_at = 0.0
        self._stable_anchor: tuple[float, float] | None = None
        self._dwell_triggered = False
        self._long_dwell_triggered = False
        self._last_sample_at: float | None = None

    @property
    def latest_point(self) -> tuple[float, float] | None:
        return self._point

    @property
    def stable(self) -> bool:
        return self._stable_anchor is not None

    def reset(self) -> None:
        self._point = None
        self._candidate_anchor = None
        self._candidate_started_at = 0.0
        self._stable_anchor = None
        self._dwell_triggered = False
        self._long_dwell_triggered = False
        self._last_sample_at = None

    def _decision(
        self,
        point: tuple[float, float],
        *,
        now: float,
        stable: bool,
        dwell_triggered: bool = False,
        long_dwell_triggered: bool = False,
    ) -> GazeDecision:
        hold_seconds = (
            max(0.0, float(now) - self._candidate_started_at)
            if self._candidate_anchor is not None
            else 0.0
        )
        progress = min(1.0, hold_seconds / self.long_dwell_seconds)
        return GazeDecision(
            point=point,
            stable=bool(stable),
            dwell_triggered=bool(dwell_triggered),
            hold_seconds=hold_seconds,
            dwell_progress=progress,
            long_dwell_triggered=bool(long_dwell_triggered),
        )

    def _restart_candidate(self, point: tuple[float, float], *, now: float) -> GazeDecision:
        self._stable_anchor = None
        self._candidate_anchor = point
        self._candidate_started_at = float(now)
        self._dwell_triggered = False
        self._long_dwell_triggered = False
        return self._decision(point, now=now, stable=False)

    def ingest(self, x: float, y: float, *, now: float) -> GazeDecision:
        sample_at = float(now)
        if (
            self._last_sample_at is not None
            and self.sample_gap_seconds is not None
            and sample_at - self._last_sample_at > self.sample_gap_seconds
        ):
            self.reset()
        self._last_sample_at = sample_at
        sample = (float(x), float(y))
        if not all(math.isfinite(value) for value in sample):
            point = self._point or (0.0, 0.0)
            return self._decision(point, now=sample_at, stable=self.stable)

        if self._point is None:
            point = sample
        else:
            point = (
                self._point[0] + (sample[0] - self._point[0]) * self.smoothing,
                self._point[1] + (sample[1] - self._point[1]) * self.smoothing,
            )
        self._point = point

        if self._stable_anchor is not None:
            rearm_radius = self.radius_px * 1.5
            if _distance(point, self._stable_anchor) <= rearm_radius:
                long_triggered = False
                if (
                    not self._long_dwell_triggered
                    and sample_at - self._candidate_started_at + 1e-9 >= self.long_dwell_seconds
                ):
                    self._long_dwell_triggered = True
                    long_triggered = True
                return self._decision(
                    point,
                    now=sample_at,
                    stable=True,
                    long_dwell_triggered=long_triggered,
                )
            return self._restart_candidate(point, now=sample_at)

        if self._candidate_anchor is None:
            return self._restart_candidate(point, now=sample_at)

        if _distance(point, self._candidate_anchor) > self.radius_px:
            return self._restart_candidate(point, now=sample_at)

        if not self._dwell_triggered and sample_at - self._candidate_started_at + 1e-9 >= self.dwell_seconds:
            self._stable_anchor = point
            self._dwell_triggered = True
            return self._decision(point, now=sample_at, stable=True, dwell_triggered=True)
        return self._decision(point, now=sample_at, stable=False)


def _distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(left[0] - right[0], left[1] - right[1])


def map_normalized_point(
    point: Sequence[float],
    screen_bounds: Sequence[float],
) -> tuple[float, float]:
    x, y = (float(value) for value in list(point)[:2])
    left, top, width, height = (float(value) for value in list(screen_bounds)[:4])
    x = max(0.0, min(1.0, x))
    y = max(0.0, min(1.0, y))
    return left + x * max(0.0, width), top + y * max(0.0, height)


def orb_top_left_for_point(
    point: Sequence[float],
    screen_bounds: Sequence[float],
    *,
    orb_size: float,
    offset_px: float = 80.0,
    offset_x_px: float = 0.0,
    offset_y_px: float = 0.0,
) -> tuple[float, float]:
    gaze_x, gaze_y = (float(value) for value in list(point)[:2])
    left, top, width, height = (float(value) for value in list(screen_bounds)[:4])
    size = max(1.0, float(orb_size))
    offset = max(0.0, float(offset_px))
    right = left + max(0.0, width)
    bottom = top + max(0.0, height)

    target_x = gaze_x + offset
    if target_x + size > right:
        target_x = gaze_x - offset - size
    target_y = gaze_y - size * 0.5
    target_x += float(offset_x_px)
    target_y += float(offset_y_px)
    target_x = max(left, min(target_x, max(left, right - size)))
    target_y = max(top, min(target_y, max(top, bottom - size)))
    return target_x, target_y


def signature_distance(left: int, right: int) -> int:
    return int(int(left) ^ int(right)).bit_count()


def average_image_hash(image, *, hash_size: int = 8) -> int:
    size = max(2, min(32, int(hash_size)))
    grayscale = image.convert("L").resize((size, size))
    values = [int(value) for value in grayscale.getdata()]
    average = sum(values) / max(1, len(values))
    signature = 0
    for index, value in enumerate(values):
        if value > average:
            signature |= 1 << index
    brightness_level = max(0, min(16, int(round((average / 255.0) * 16.0))))
    signature |= ((1 << brightness_level) - 1) << (size * size)
    return signature


def is_explicit_orb_gaze_command(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not normalized or re.search(r"\b(?:companion\s+orb|orb)\b", normalized) is None:
        return False
    if re.search(r"\b(?:comment|react|check|inspect|look|describe|tell)\b", normalized) is None:
        return False
    return bool(
        re.search(
            r"(?:where\s+i(?:\s+am|'m|m)\s+look(?:ing)?|"
            r"what\s+i(?:\s+am|'m|m)\s+look(?:ing)?\s+at|"
            r"my\s+gaze|gaze\s+point|my\s+eye\s+focus)",
            normalized,
        )
    )


class GazeReactionGate:
    def __init__(self, *, cooldown_seconds: float = 45.0, minimum_signature_distance: int = 8):
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.minimum_signature_distance = max(0, int(minimum_signature_distance))
        self._last_signature: int | None = None
        self._last_reaction_at = float("-inf")

    def reset(self) -> None:
        self._last_signature = None
        self._last_reaction_at = float("-inf")

    def accept(self, signature: int, *, now: float, meaningful: bool, force: bool = False) -> bool:
        normalized_signature = int(signature)
        timestamp = float(now)
        if not force:
            if timestamp - self._last_reaction_at < self.cooldown_seconds:
                return False
            if (
                meaningful
                and self._last_signature is not None
                and signature_distance(self._last_signature, normalized_signature) < self.minimum_signature_distance
            ):
                return False
        self._last_signature = normalized_signature
        self._last_reaction_at = timestamp
        return True


class StreamEngineError(RuntimeError):
    pass


class StreamEngineUnavailable(StreamEngineError):
    pass


class StreamEngineNoDevice(StreamEngineError):
    pass


class StreamEngineDisconnected(StreamEngineError):
    pass


class _StreamEngineSession(Protocol):
    def read_sample(self, timeout_seconds: float) -> tuple[float, float] | None: ...

    def close(self) -> None: ...


class TobiiStreamEngineProvider:
    """Run Stream Engine callbacks off the UI thread without retaining gaze history."""

    def __init__(
        self,
        *,
        on_sample: Callable[[float, float], None],
        on_validity: Callable[[bool], None] | None = None,
        on_status: Callable[[str, str], None] | None = None,
        session_factory: Callable[[Path], _StreamEngineSession] | None = None,
        dll_resolver: Callable[[str], Path | None] | None = None,
        retry_seconds: float = 2.0,
    ):
        self._on_sample = on_sample
        self._on_validity = on_validity
        self._on_status = on_status
        self._session_factory = session_factory or _CtypesStreamEngineSession
        self._dll_resolver = dll_resolver or (lambda path: find_stream_engine_dll(path))
        self._retry_seconds = max(0.01, float(retry_seconds))
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._dll_path = ""
        self._resolved_dll_path = ""
        self._status_code = "off"
        self._status_message = "Eye tracking is off."
        self._last_validity: bool | None = None

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    @property
    def status_code(self) -> str:
        with self._lock:
            return self._status_code

    @property
    def status_message(self) -> str:
        with self._lock:
            return self._status_message

    @property
    def resolved_dll_path(self) -> str:
        with self._lock:
            return self._resolved_dll_path

    def start(self, dll_path: str = "") -> bool:
        with self._lock:
            if self.is_running:
                return True
            self._dll_path = str(dll_path or "").strip()
            self._resolved_dll_path = ""
            self._stop_event = threading.Event()
            self._thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="companion-orb-tobii-gaze",
            )
            self._emit_status("connecting", "Connecting to Tobii eye tracking...")
            self._thread.start()
            return True

    def stop(self, *, timeout_seconds: float = 1.5) -> None:
        with self._lock:
            thread = self._thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, float(timeout_seconds)))
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None
        if thread is not None and thread.is_alive():
            self._emit_status("stopping", "Eye tracker is finishing its current callback wait.")
        else:
            self._emit_status("off", "Eye tracking is off.")

    def _run(self) -> None:
        try:
            dll_path = self._dll_resolver(self._dll_path)
            if dll_path is None:
                self._emit_status(
                    "no_dll",
                    "Tobii Stream Engine was not found. Select the official tobii_stream_engine.dll in Companion Orb settings.",
                )
                return
            with self._lock:
                self._resolved_dll_path = str(Path(dll_path))
            while not self._stop_event.is_set():
                self._emit_status("connecting", "Connecting to the Tobii eye tracker...")
                session: _StreamEngineSession | None = None
                try:
                    session = self._session_factory(Path(dll_path))
                    self._last_validity = None
                    self._emit_status("connected", "Tobii eye tracking is connected.")
                    while not self._stop_event.is_set():
                        read_event = getattr(session, "read_event", None)
                        if callable(read_event):
                            event = read_event(0.25)
                            if event is None:
                                continue
                            valid = bool(getattr(event, "valid", False))
                            self._emit_validity(valid)
                            if not valid:
                                continue
                            sample = getattr(event, "position", None)
                        else:
                            sample = session.read_sample(0.25)
                            if sample is None:
                                continue
                            self._emit_validity(True)
                        try:
                            x, y = float(sample[0]), float(sample[1])
                        except (TypeError, ValueError, IndexError):
                            continue
                        if not (math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                            continue
                        try:
                            self._on_sample(x, y)
                        except Exception:
                            continue
                except StreamEngineNoDevice:
                    self._emit_status("no_device", "No compatible Tobii eye tracker is available. Connect and calibrate the device.")
                except StreamEngineDisconnected:
                    self._emit_status("reconnecting", "Tobii eye tracking was interrupted; reconnecting...")
                except StreamEngineUnavailable as exc:
                    self._emit_status("no_dll", str(exc) or "Tobii Stream Engine is unavailable.")
                    return
                except Exception as exc:
                    self._emit_status("error", f"Tobii eye tracking error: {exc}")
                finally:
                    if session is not None:
                        try:
                            session.close()
                        except Exception:
                            pass
                if not self._stop_event.wait(self._retry_seconds):
                    continue
        finally:
            if self._stop_event.is_set():
                self._emit_status("off", "Eye tracking is off.")
            with self._lock:
                if self._thread is threading.current_thread():
                    self._thread = None

    def _emit_status(self, code: str, message: str) -> None:
        normalized_code = str(code or "error").strip().lower() or "error"
        normalized_message = str(message or "").strip()
        with self._lock:
            self._status_code = normalized_code
            self._status_message = normalized_message
        callback = self._on_status
        if callback is not None:
            try:
                callback(normalized_code, normalized_message)
            except Exception:
                pass

    def _emit_validity(self, valid: bool) -> None:
        current = bool(valid)
        if current == self._last_validity:
            return
        self._last_validity = current
        callback = self._on_validity
        if callback is not None:
            try:
                callback(current)
            except Exception:
                pass


class _TobiiGazePoint(ctypes.Structure):
    _fields_ = [
        ("timestamp_us", ctypes.c_int64),
        ("validity", ctypes.c_uint32),
        ("position_xy", ctypes.c_float * 2),
    ]


_DEVICE_URL_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_void_p)
_GAZE_POINT_CALLBACK = ctypes.CFUNCTYPE(None, ctypes.POINTER(_TobiiGazePoint), ctypes.c_void_p)


class _CtypesStreamEngineSession:
    TOBII_ERROR_NO_ERROR = 0
    TOBII_ERROR_CONNECTION_FAILED = 5
    TOBII_ERROR_TIMED_OUT = 6
    TOBII_VALIDITY_VALID = 1
    TOBII_FIELD_OF_USE_INTERACTIVE = 1

    def __init__(self, dll_path: Path):
        self._dll = None
        self._api = ctypes.c_void_p()
        self._device = ctypes.c_void_p()
        self._subscribed = False
        self._api_major = 0
        self._latest_sample: tuple[float, float] | None = None
        self._pending_events: deque[GazeStreamEvent] = deque(maxlen=64)
        self._url_callback = None
        self._gaze_callback = None
        try:
            self._open(Path(dll_path))
        except Exception:
            self.close()
            raise

    def _open(self, dll_path: Path) -> None:
        if os.name != "nt":
            raise StreamEngineUnavailable("Tobii Stream Engine is supported only on Windows in this addon.")
        try:
            self._dll = ctypes.CDLL(str(dll_path))
        except OSError as exc:
            raise StreamEngineUnavailable(f"Could not load the selected Tobii Stream Engine DLL: {exc}") from exc

        versions = (ctypes.c_int32 * 4)()
        get_version = self._function("tobii_get_api_version")
        get_version.argtypes = [ctypes.POINTER(ctypes.c_int32)]
        get_version.restype = ctypes.c_int
        self._check(get_version(versions), "read Stream Engine version")
        self._api_major = int(versions[0])

        api_create = self._function("tobii_api_create")
        api_create.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_void_p]
        api_create.restype = ctypes.c_int
        self._check(api_create(ctypes.byref(self._api), None, None), "create Stream Engine API")

        urls: list[str] = []

        @_DEVICE_URL_CALLBACK
        def receive_url(url, _context):
            if url:
                urls.append(url.decode("utf-8", errors="replace"))

        self._url_callback = receive_url
        enumerate_urls = self._function("tobii_enumerate_local_device_urls")
        enumerate_urls.argtypes = [ctypes.c_void_p, _DEVICE_URL_CALLBACK, ctypes.c_void_p]
        enumerate_urls.restype = ctypes.c_int
        self._check(enumerate_urls(self._api, self._url_callback, None), "enumerate Tobii devices")
        if not urls:
            raise StreamEngineNoDevice("No compatible Tobii eye tracker was found.")

        device_create = self._function("tobii_device_create")
        device_create.restype = ctypes.c_int
        encoded_url = urls[0].encode("utf-8")
        if self._api_major < 4:
            device_create.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
            result = device_create(self._api, encoded_url, ctypes.byref(self._device))
        else:
            device_create.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
            result = device_create(
                self._api,
                encoded_url,
                self.TOBII_FIELD_OF_USE_INTERACTIVE,
                ctypes.byref(self._device),
            )
        self._check(result, "connect to Tobii device")

        @_GAZE_POINT_CALLBACK
        def receive_gaze(gaze_point, _context):
            if not gaze_point:
                return
            value = gaze_point.contents
            if int(value.validity) != self.TOBII_VALIDITY_VALID:
                self._pending_events.append(
                    GazeStreamEvent(
                        valid=False,
                        timestamp_us=int(value.timestamp_us),
                    )
                )
                return
            position = (float(value.position_xy[0]), float(value.position_xy[1]))
            self._latest_sample = position
            self._pending_events.append(
                GazeStreamEvent(
                    valid=True,
                    position=position,
                    timestamp_us=int(value.timestamp_us),
                )
            )

        self._gaze_callback = receive_gaze
        subscribe = self._function("tobii_gaze_point_subscribe")
        subscribe.argtypes = [ctypes.c_void_p, _GAZE_POINT_CALLBACK, ctypes.c_void_p]
        subscribe.restype = ctypes.c_int
        self._check(subscribe(self._device, self._gaze_callback, None), "subscribe to Tobii gaze point")
        self._subscribed = True

    def read_event(self, _timeout_seconds: float) -> GazeStreamEvent | None:
        if self._pending_events:
            return self._pending_events.popleft()
        if not self._device.value:
            raise StreamEngineDisconnected("Tobii device is not connected.")
        devices = (ctypes.c_void_p * 1)(self._device.value)
        wait_for_callbacks = self._function("tobii_wait_for_callbacks")
        wait_for_callbacks.restype = ctypes.c_int
        if self._api_major < 3:
            wait_for_callbacks.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
            result = wait_for_callbacks(None, 1, devices)
        else:
            wait_for_callbacks.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
            result = wait_for_callbacks(1, devices)
        if int(result) == self.TOBII_ERROR_TIMED_OUT:
            return None
        self._check(result, "wait for Tobii gaze callback")

        process_callbacks = self._function("tobii_device_process_callbacks")
        process_callbacks.argtypes = [ctypes.c_void_p]
        process_callbacks.restype = ctypes.c_int
        self._check(process_callbacks(self._device), "process Tobii gaze callback")
        if self._pending_events:
            return self._pending_events.popleft()
        return None

    def read_sample(self, timeout_seconds: float) -> tuple[float, float] | None:
        event = self.read_event(timeout_seconds)
        if event is None or not event.valid:
            return None
        if event.position is not None:
            return event.position
        sample = self._latest_sample
        self._latest_sample = None
        return sample

    def close(self) -> None:
        dll = self._dll
        if dll is None:
            return
        if self._subscribed and self._device.value:
            try:
                unsubscribe = getattr(dll, "tobii_gaze_point_unsubscribe")
                unsubscribe.argtypes = [ctypes.c_void_p]
                unsubscribe.restype = ctypes.c_int
                unsubscribe(self._device)
            except Exception:
                pass
        self._subscribed = False
        if self._device.value:
            try:
                destroy_device = getattr(dll, "tobii_device_destroy")
                destroy_device.argtypes = [ctypes.c_void_p]
                destroy_device.restype = ctypes.c_int
                destroy_device(self._device)
            except Exception:
                pass
            self._device = ctypes.c_void_p()
        if self._api.value:
            try:
                destroy_api = getattr(dll, "tobii_api_destroy")
                destroy_api.argtypes = [ctypes.c_void_p]
                destroy_api.restype = ctypes.c_int
                destroy_api(self._api)
            except Exception:
                pass
            self._api = ctypes.c_void_p()
        self._gaze_callback = None
        self._url_callback = None
        self._dll = None

    def _function(self, name: str):
        dll = self._dll
        if dll is None:
            raise StreamEngineUnavailable("Tobii Stream Engine DLL is not loaded.")
        try:
            return getattr(dll, name)
        except AttributeError as exc:
            raise StreamEngineUnavailable(f"Selected Tobii Stream Engine DLL is missing {name}.") from exc

    def _check(self, result: int, action: str) -> None:
        code = int(result)
        if code == self.TOBII_ERROR_NO_ERROR:
            return
        message = self._error_message(code)
        detail = f"Could not {action}: {message} (error {code})."
        if code == self.TOBII_ERROR_CONNECTION_FAILED:
            raise StreamEngineDisconnected(detail)
        raise StreamEngineError(detail)

    def _error_message(self, code: int) -> str:
        try:
            error_message = self._function("tobii_error_message")
            error_message.argtypes = [ctypes.c_int]
            error_message.restype = ctypes.c_char_p
            value = error_message(int(code))
            return value.decode("utf-8", errors="replace") if value else "unknown Stream Engine error"
        except Exception:
            return "unknown Stream Engine error"


def find_stream_engine_dll(
    explicit_path: str | os.PathLike[str] = "",
    *,
    environ: Mapping[str, str] | None = None,
    search_roots: Sequence[str | os.PathLike[str]] | None = None,
) -> Path | None:
    environment = os.environ if environ is None else environ
    direct_candidates = [explicit_path, environment.get("TOBII_STREAM_ENGINE_DLL", "")]
    for candidate in direct_candidates:
        resolved = _resolve_dll_candidate(candidate)
        if resolved is not None:
            return resolved

    roots = list(search_roots) if search_roots is not None else _default_stream_engine_roots(environment)
    for raw_root in roots:
        root = Path(raw_root).expanduser()
        if not root.is_dir():
            continue
        direct = _resolve_dll_candidate(root)
        if direct is not None:
            return direct
        try:
            matches = sorted(root.rglob("tobii_stream_engine.dll"), key=lambda path: str(path).lower())
        except (OSError, PermissionError):
            continue
        for match in matches:
            if match.is_file():
                return match.resolve()
    return None


def _resolve_dll_candidate(value) -> Path | None:
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_dir():
        path = path / "tobii_stream_engine.dll"
    if path.is_file() and path.name.lower() == "tobii_stream_engine.dll":
        return path.resolve()
    return None


def _default_stream_engine_roots(environment: Mapping[str, str]) -> list[Path]:
    roots = [Path(__file__).resolve().parent]
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "LOCALAPPDATA"):
        value = str(environment.get(variable, "") or "").strip()
        if value:
            roots.append(Path(value) / "Tobii")
    return roots
