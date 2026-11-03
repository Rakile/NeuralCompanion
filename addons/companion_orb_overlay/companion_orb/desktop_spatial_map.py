"""Immutable desktop grounding snapshots and deterministic target resolution."""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from .vision_grounding import GroundingResult


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "at",
        "in",
        "near",
        "of",
        "on",
        "over",
        "that",
        "the",
        "this",
        "to",
    }
)
_DIRECTION_WORDS = frozenset({"left", "right", "top", "bottom", "center", "middle"})
_TOKEN_ALIASES = {
    "photo": "image",
    "photograph": "image",
    "picture": "image",
    "screenshot": "image",
    "headline": "title",
    "heading": "title",
}


def _clean_text(value: object, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _bounds(value: Sequence[object]) -> tuple[int, int, int, int]:
    try:
        values = tuple(int(round(float(item))) for item in list(value)[:4])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Bounds must contain four finite numbers.") from exc
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError("Bounds must have positive dimensions.")
    return values


def _tokens(value: object) -> tuple[str, ...]:
    return tuple(
        _TOKEN_ALIASES.get(token, token)
        for token in _WORD_RE.findall(str(value or "").casefold())
    )


def _contains(bounds: tuple[int, int, int, int], point: tuple[float, float]) -> bool:
    left, top, width, height = bounds
    return left <= point[0] <= left + width and top <= point[1] <= top + height


def _expanded(
    bounds: tuple[int, int, int, int],
    amount: float,
) -> tuple[int, int, int, int]:
    padding = max(0, int(round(float(amount))))
    left, top, width, height = bounds
    return left - padding, top - padding, width + padding * 2, height + padding * 2


@dataclass(frozen=True, slots=True)
class SpatialRegion:
    region_id: str
    label: str
    kind: str
    screen_bounds: tuple[int, int, int, int]
    confidence: float
    action_hint: str = ""
    ocr_text: str = ""
    source: str = "lfm_vision"
    backend: str = "lfm_vision"

    def __post_init__(self) -> None:
        region_id = _clean_text(self.region_id, limit=80)
        label = _clean_text(self.label, limit=160)
        if not region_id or not label:
            raise ValueError("Spatial regions require an ID and label.")
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Spatial region confidence must be finite.") from exc
        if not math.isfinite(confidence):
            raise ValueError("Spatial region confidence must be finite.")
        object.__setattr__(self, "region_id", region_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "kind", _clean_text(self.kind, limit=32).lower() or "object")
        object.__setattr__(self, "screen_bounds", _bounds(self.screen_bounds))
        object.__setattr__(self, "confidence", max(0.0, min(1.0, confidence)))
        object.__setattr__(self, "action_hint", _clean_text(self.action_hint, limit=160))
        object.__setattr__(self, "ocr_text", _clean_text(self.ocr_text, limit=1200))
        object.__setattr__(self, "source", _clean_text(self.source, limit=40) or "lfm_vision")
        object.__setattr__(self, "backend", _clean_text(self.backend, limit=40) or "lfm_vision")

    @property
    def center(self) -> tuple[float, float]:
        left, top, width, height = self.screen_bounds
        return left + width * 0.5, top + height * 0.5

    @property
    def area(self) -> int:
        return self.screen_bounds[2] * self.screen_bounds[3]


@dataclass(frozen=True, slots=True)
class SpatialMapSnapshot:
    generation: int
    captured_at: float
    capture_bounds: tuple[int, int, int, int]
    topology_signature: str
    scene_summary: str
    regions: tuple[SpatialRegion, ...]
    endpoint: str = ""
    model_id: str = ""
    capture_path: str = ""
    raw_response: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            generation = max(0, int(self.generation))
            captured_at = float(self.captured_at)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Spatial snapshot metadata is invalid.") from exc
        if not math.isfinite(captured_at):
            raise ValueError("Spatial snapshot time must be finite.")
        regions = tuple(region for region in self.regions if isinstance(region, SpatialRegion))
        raw = dict(self.raw_response) if isinstance(self.raw_response, Mapping) else {}
        object.__setattr__(self, "generation", generation)
        object.__setattr__(self, "captured_at", captured_at)
        object.__setattr__(self, "capture_bounds", _bounds(self.capture_bounds))
        object.__setattr__(self, "topology_signature", _clean_text(self.topology_signature, limit=320))
        object.__setattr__(self, "scene_summary", _clean_text(self.scene_summary, limit=320))
        object.__setattr__(self, "regions", regions)
        object.__setattr__(self, "endpoint", _clean_text(self.endpoint, limit=320))
        object.__setattr__(self, "model_id", _clean_text(self.model_id, limit=160))
        object.__setattr__(self, "capture_path", str(self.capture_path or "").strip())
        object.__setattr__(self, "raw_response", MappingProxyType(raw))

    def age(self, *, now: float | None = None) -> float:
        current = time.monotonic() if now is None else float(now)
        return max(0.0, current - self.captured_at)

    def is_fresh(
        self,
        *,
        now: float | None = None,
        max_age_seconds: float,
        topology_signature: str | None = None,
    ) -> bool:
        try:
            maximum_age = max(0.0, float(max_age_seconds))
        except (TypeError, ValueError, OverflowError):
            return False
        if topology_signature is not None and str(topology_signature) != self.topology_signature:
            return False
        return self.age(now=now) <= maximum_age


@dataclass(frozen=True, slots=True)
class SpatialTargetResolution:
    region: SpatialRegion | None
    score: float = 0.0
    ambiguous: bool = False
    reason: str = ""


def build_snapshot(
    grounding: GroundingResult,
    *,
    generation: int,
    captured_at: float,
    capture_bounds: Sequence[object],
    topology_signature: str,
    endpoint: str = "",
    model_id: str = "",
    capture_path: str = "",
    raw_response: Mapping[str, object] | None = None,
    max_regions: int = 96,
) -> SpatialMapSnapshot:
    if not isinstance(grounding, GroundingResult):
        raise TypeError("A normalized grounding result is required.")
    try:
        limit = max(1, min(96, int(max_regions)))
    except (TypeError, ValueError, OverflowError):
        limit = 96
    safe_generation = max(0, int(generation))
    regions = tuple(
        SpatialRegion(
            region_id=f"g{safe_generation}-r{index}",
            label=region.label,
            kind=region.kind,
            screen_bounds=region.screen_bounds,
            confidence=region.confidence,
            action_hint=region.action_hint,
        )
        for index, region in enumerate(grounding.regions[:limit])
    )
    return SpatialMapSnapshot(
        generation=safe_generation,
        captured_at=captured_at,
        capture_bounds=_bounds(capture_bounds),
        topology_signature=topology_signature,
        scene_summary=grounding.scene_summary,
        regions=regions,
        endpoint=endpoint,
        model_id=model_id,
        capture_path=capture_path,
        raw_response=dict(raw_response or {}),
    )


def _direction_bonus(
    query_tokens: set[str],
    region: SpatialRegion,
    capture_bounds: tuple[int, int, int, int],
) -> float:
    directions = query_tokens & _DIRECTION_WORDS
    if not directions:
        return 0.0
    left, top, width, height = capture_bounds
    center_x, center_y = region.center
    x_ratio = max(0.0, min(1.0, (center_x - left) / width))
    y_ratio = max(0.0, min(1.0, (center_y - top) / height))
    scores: list[float] = []
    if "left" in directions:
        scores.append(1.0 - x_ratio)
    if "right" in directions:
        scores.append(x_ratio)
    if "top" in directions:
        scores.append(1.0 - y_ratio)
    if "bottom" in directions:
        scores.append(y_ratio)
    if directions & {"center", "middle"}:
        scores.append(1.0 - min(1.0, math.hypot(x_ratio - 0.5, y_ratio - 0.5) * 2.0))
    return 0.22 * (sum(scores) / len(scores) if scores else 0.0)


def _region_match_score(
    target_text: str,
    region: SpatialRegion,
    capture_bounds: tuple[int, int, int, int],
) -> float:
    query_all = set(_tokens(target_text))
    semantic_query = query_all - _STOP_WORDS - _DIRECTION_WORDS
    region_tokens = set(_tokens(f"{region.label} {region.kind}"))
    if not semantic_query:
        semantic_score = 0.0
    else:
        overlap = semantic_query & region_tokens
        coverage = len(overlap) / len(semantic_query)
        precision = len(overlap) / max(1, len(region_tokens))
        semantic_score = coverage * 0.57 + precision * 0.18
    canonical_query = " ".join(_tokens(target_text))
    canonical_label = " ".join(_tokens(region.label))
    exact_bonus = 0.18 if canonical_query and canonical_query == canonical_label else 0.0
    substring_bonus = (
        0.08
        if canonical_query
        and canonical_label
        and (canonical_query in canonical_label or canonical_label in canonical_query)
        else 0.0
    )
    return min(
        1.0,
        semantic_score
        + exact_bonus
        + substring_bonus
        + region.confidence * 0.12
        + _direction_bonus(query_all, region, capture_bounds),
    )


def resolve_target(
    snapshot: SpatialMapSnapshot | None,
    *,
    target_text: str = "",
    region_id: str = "",
    min_confidence: float = 0.0,
    minimum_match_score: float = 0.36,
    ambiguity_margin: float = 0.06,
    allowed_kinds: Sequence[str] | None = None,
) -> SpatialTargetResolution:
    if not isinstance(snapshot, SpatialMapSnapshot):
        return SpatialTargetResolution(None, reason="missing_map")
    threshold = max(0.0, min(1.0, float(min_confidence)))
    kinds = {str(kind or "").strip().lower() for kind in (allowed_kinds or ()) if str(kind or "").strip()}
    candidates = tuple(
        region
        for region in snapshot.regions
        if (not kinds or region.kind in kinds)
    )
    wanted_id = str(region_id or "").strip()
    if wanted_id:
        exact = next((region for region in candidates if region.region_id == wanted_id), None)
        if exact is None:
            return SpatialTargetResolution(None, reason="missing_region")
        if exact.confidence < threshold:
            return SpatialTargetResolution(None, score=exact.confidence, reason="below_confidence")
        return SpatialTargetResolution(exact, score=1.0)

    query = _clean_text(target_text, limit=240)
    if not query:
        return SpatialTargetResolution(None, reason="missing_target")
    scored = sorted(
        (
            (_region_match_score(query, region, snapshot.capture_bounds), region)
            for region in candidates
            if region.confidence >= threshold
        ),
        key=lambda item: (-item[0], -item[1].confidence, item[1].area, item[1].region_id),
    )
    if not scored or scored[0][0] < max(0.0, float(minimum_match_score)):
        return SpatialTargetResolution(None, reason="no_match")
    top_score, top_region = scored[0]
    if len(scored) > 1 and top_score - scored[1][0] <= max(0.0, float(ambiguity_margin)):
        return SpatialTargetResolution(None, score=top_score, ambiguous=True, reason="ambiguous")
    return SpatialTargetResolution(top_region, score=top_score)


def region_at_point(
    snapshot: SpatialMapSnapshot | None,
    point: Sequence[object],
    *,
    min_confidence: float = 0.0,
    previous_region_id: str = "",
    hysteresis_px: float = 8.0,
    allowed_kinds: Sequence[str] | None = None,
) -> SpatialRegion | None:
    if not isinstance(snapshot, SpatialMapSnapshot):
        return None
    try:
        values = tuple(float(value) for value in list(point)[:2])
    except (TypeError, ValueError, OverflowError):
        return None
    if len(values) != 2 or not all(math.isfinite(value) for value in values):
        return None
    threshold = max(0.0, min(1.0, float(min_confidence)))
    kinds = {str(kind or "").strip().lower() for kind in (allowed_kinds or ()) if str(kind or "").strip()}
    eligible = tuple(
        region
        for region in snapshot.regions
        if region.confidence >= threshold and (not kinds or region.kind in kinds)
    )
    previous_id = str(previous_region_id or "").strip()
    if previous_id:
        previous = next((region for region in eligible if region.region_id == previous_id), None)
        if previous is not None and _contains(_expanded(previous.screen_bounds, hysteresis_px), values):
            return previous
    containing = [region for region in eligible if _contains(region.screen_bounds, values)]
    if not containing:
        return None
    return min(containing, key=lambda region: (region.area, -region.confidence, region.region_id))


def compact_scene_context(
    snapshot: SpatialMapSnapshot | None,
    *,
    max_regions: int = 16,
    max_chars: int = 1800,
) -> str:
    if not isinstance(snapshot, SpatialMapSnapshot):
        return ""
    region_limit = max(1, min(48, int(max_regions)))
    char_limit = max(80, min(8000, int(max_chars)))
    lines = []
    if snapshot.scene_summary:
        lines.append(f"Scene: {snapshot.scene_summary}")
    for region in snapshot.regions[:region_limit]:
        lines.append(
            f"- {region.region_id} | {region.kind} | {region.label} | confidence={region.confidence:.2f}"
        )
    output = "\n".join(lines)
    return output if len(output) <= char_limit else output[:char_limit].rstrip()


class DesktopSpatialMapStore:
    """Thread-safe publication with one deferred snapshot during gaze locking."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._current: SpatialMapSnapshot | None = None
        self._pending: SpatialMapSnapshot | None = None
        self._locked_region_id = ""

    @property
    def pending_generation(self) -> int | None:
        with self._lock:
            return None if self._pending is None else self._pending.generation

    @property
    def locked_region_id(self) -> str:
        with self._lock:
            return self._locked_region_id

    def current(
        self,
        *,
        now: float | None = None,
        max_age_seconds: float | None = None,
        topology_signature: str | None = None,
        allow_stale: bool = False,
    ) -> SpatialMapSnapshot | None:
        with self._lock:
            snapshot = self._current
        if snapshot is None or allow_stale:
            return snapshot
        if max_age_seconds is not None and not snapshot.is_fresh(
            now=now,
            max_age_seconds=max_age_seconds,
            topology_signature=topology_signature,
        ):
            return None
        if topology_signature is not None and topology_signature != snapshot.topology_signature:
            return None
        return snapshot

    def publish(self, snapshot: SpatialMapSnapshot) -> bool:
        if not isinstance(snapshot, SpatialMapSnapshot):
            raise TypeError("A spatial map snapshot is required.")
        with self._lock:
            latest_generation = max(
                self._current.generation if self._current is not None else -1,
                self._pending.generation if self._pending is not None else -1,
            )
            if snapshot.generation < latest_generation:
                return False
            if self._locked_region_id:
                self._pending = snapshot
                return False
            self._current = snapshot
            self._pending = None
            return True

    def lock_region(self, region_id: str) -> bool:
        wanted = str(region_id or "").strip()
        if not wanted:
            return False
        with self._lock:
            if self._current is None or not any(
                region.region_id == wanted for region in self._current.regions
            ):
                return False
            if self._locked_region_id and self._locked_region_id != wanted:
                return False
            self._locked_region_id = wanted
            return True

    def unlock_region(self, region_id: str = "") -> bool:
        wanted = str(region_id or "").strip()
        with self._lock:
            if not self._locked_region_id:
                return False
            if wanted and wanted != self._locked_region_id:
                return False
            self._locked_region_id = ""
            if self._pending is not None:
                self._current = self._pending
                self._pending = None
            return True

    def invalidate(self) -> None:
        with self._lock:
            self._current = None
            self._pending = None
            self._locked_region_id = ""


__all__ = [
    "DesktopSpatialMapStore",
    "SpatialMapSnapshot",
    "SpatialRegion",
    "SpatialTargetResolution",
    "build_snapshot",
    "compact_scene_context",
    "region_at_point",
    "resolve_target",
]
