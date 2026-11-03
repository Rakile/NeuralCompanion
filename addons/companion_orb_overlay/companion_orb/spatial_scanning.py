"""Pure scan admission and single-flight policy for Orb desktop grounding."""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import dataclass


SCAN_MODES = frozenset({"on_demand", "smart_cached", "continuous"})
_REASON_PRIORITY = {
    "timer": 0,
    "coalesced": 1,
    "gaze": 2,
    "conversation": 3,
    "action": 4,
    "manual": 5,
    "diagnostic": 6,
}
_BACKOFF_BYPASS_REASONS = frozenset({"manual", "diagnostic", "action"})


def _boolish(value: object, *, default: bool) -> bool:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return bool(default)
    if value is None:
        return bool(default)
    return bool(value)


def _number(value: object, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        number = float(default)
    if not math.isfinite(number):
        number = float(default)
    return max(float(minimum), min(float(maximum), number))


def _mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SCAN_MODES else "smart_cached"


def _reason(value: object) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in _REASON_PRIORITY else "manual"


@dataclass(frozen=True, slots=True)
class SpatialScanSettings:
    enabled: bool
    mode: str
    interval_seconds: float
    max_age_seconds: float
    change_detection_enabled: bool
    change_threshold: float

    @classmethod
    def from_mapping(cls, settings: Mapping[str, object]) -> "SpatialScanSettings":
        values = settings if isinstance(settings, Mapping) else {}
        return cls(
            enabled=(
                _boolish(
                    values.get("companion_orb_vision_enabled", False),
                    default=False,
                )
                and str(
                    values.get(
                        "companion_orb_spatial_capture_scope",
                        "active_monitor",
                    )
                    or "active_monitor"
                ).strip().lower()
                != "off"
            ),
            mode=_mode(values.get("companion_orb_spatial_scan_mode", "smart_cached")),
            interval_seconds=_number(
                values.get("companion_orb_spatial_scan_interval_seconds", 8.0),
                default=8.0,
                minimum=2.0,
                maximum=300.0,
            ),
            max_age_seconds=_number(
                values.get("companion_orb_spatial_map_max_age_seconds", 20.0),
                default=20.0,
                minimum=2.0,
                maximum=600.0,
            ),
            change_detection_enabled=_boolish(
                values.get(
                    "companion_orb_spatial_change_detection_enabled",
                    True,
                ),
                default=True,
            ),
            change_threshold=_number(
                values.get("companion_orb_spatial_change_threshold", 0.08),
                default=0.08,
                minimum=0.0,
                maximum=1.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class SpatialScanRequest:
    generation: int
    reason: str


class SpatialScanCoordinator:
    """Admit at most one scan and retain only one prioritized pending request."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._generation = 0
        self._inflight_generation: int | None = None
        self._coalesced_reason = ""
        self._last_started_at: float | None = None
        self._retry_after = 0.0
        self._failure_count = 0

    @property
    def inflight_generation(self) -> int | None:
        with self._lock:
            return self._inflight_generation

    @property
    def coalesced(self) -> bool:
        with self._lock:
            return bool(self._coalesced_reason)

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def retry_after(self) -> float:
        with self._lock:
            return self._retry_after

    def _remember_coalesced(self, reason: str) -> None:
        current_priority = _REASON_PRIORITY.get(self._coalesced_reason, -1)
        if _REASON_PRIORITY.get(reason, 0) >= current_priority:
            self._coalesced_reason = reason

    def _new_request(self, reason: str, *, now: float) -> SpatialScanRequest:
        self._generation += 1
        self._inflight_generation = self._generation
        self._last_started_at = float(now)
        return SpatialScanRequest(self._generation, reason)

    def request(
        self,
        *,
        reason: str,
        now: float,
        settings: SpatialScanSettings,
        map_age: float | None,
        change_score: float | None,
    ) -> SpatialScanRequest | None:
        if not isinstance(settings, SpatialScanSettings) or not settings.enabled:
            return None
        normalized_reason = _reason(reason)
        sample_at = float(now)
        with self._lock:
            if normalized_reason == "timer" and settings.mode == "on_demand":
                return None
            if self._inflight_generation is not None:
                self._remember_coalesced(normalized_reason)
                return None
            if (
                sample_at < self._retry_after
                and normalized_reason not in _BACKOFF_BYPASS_REASONS
            ):
                return None
            if normalized_reason == "timer" and settings.mode == "continuous":
                if (
                    self._last_started_at is not None
                    and sample_at - self._last_started_at < settings.interval_seconds
                ):
                    return None
            if normalized_reason == "timer" and settings.mode == "smart_cached":
                stale = map_age is None or float(map_age) >= settings.max_age_seconds
                changed = (
                    not settings.change_detection_enabled
                    or change_score is None
                    or float(change_score) >= settings.change_threshold
                )
                if not stale and not changed:
                    return None
            return self._new_request(normalized_reason, now=sample_at)

    def complete(self, generation: int) -> bool:
        with self._lock:
            if self._inflight_generation != int(generation):
                return False
            self._inflight_generation = None
            self._failure_count = 0
            self._retry_after = 0.0
            return True

    def fail(self, generation: int, *, now: float) -> bool:
        with self._lock:
            if self._inflight_generation != int(generation):
                return False
            self._inflight_generation = None
            self._failure_count = min(6, self._failure_count + 1)
            self._retry_after = float(now) + min(
                60.0,
                2.0 ** self._failure_count,
            )
            return True

    def invalidate(self) -> int:
        with self._lock:
            self._generation += 1
            self._inflight_generation = None
            self._coalesced_reason = ""
            self._retry_after = 0.0
            self._failure_count = 0
            return self._generation

    def consume_coalesced(self, *, now: float) -> SpatialScanRequest | None:
        with self._lock:
            if self._inflight_generation is not None or not self._coalesced_reason:
                return None
            if float(now) < self._retry_after:
                return None
            reason = self._coalesced_reason
            self._coalesced_reason = ""
            return self._new_request(
                "coalesced" if reason == "timer" else reason,
                now=float(now),
            )


__all__ = [
    "SCAN_MODES",
    "SpatialScanCoordinator",
    "SpatialScanRequest",
    "SpatialScanSettings",
]
