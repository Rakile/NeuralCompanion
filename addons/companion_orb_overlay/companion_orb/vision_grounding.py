"""Strict normalization for Companion Orb vision-grounding results."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


_ALLOWED_KINDS = frozenset(
    {
        "button",
        "link",
        "field",
        "text",
        "image",
        "icon",
        "panel",
        "window",
        "media",
        "control",
        "object",
    }
)


def _clean_text(value: object, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _capture_rectangle(
    capture_bounds: Sequence[object],
) -> tuple[int, int, int, int]:
    try:
        values = tuple(int(value) for value in list(capture_bounds)[:4])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Capture bounds must contain four integers.") from exc
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise ValueError("Capture bounds must have positive dimensions.")
    return values


@dataclass(frozen=True, slots=True)
class GroundedRegion:
    label: str
    kind: str
    normalized_bounds: tuple[int, int, int, int]
    screen_bounds: tuple[int, int, int, int]
    confidence: float
    action_hint: str = ""


@dataclass(frozen=True, slots=True)
class GroundingResult:
    scene_summary: str
    regions: tuple[GroundedRegion, ...]
    limitations: str = ""


def normalize_grounding_result(
    payload: Mapping[str, object],
    *,
    capture_bounds: Sequence[object],
    max_regions: int = 48,
) -> GroundingResult:
    """Validate a provider payload and map normalized boxes to desktop pixels."""

    if not isinstance(payload, Mapping):
        raise ValueError("Grounding payload must be a mapping.")
    left, top, width, height = _capture_rectangle(capture_bounds)
    try:
        limit = max(1, min(96, int(max_regions)))
    except (TypeError, ValueError, OverflowError):
        limit = 48

    normalized_regions: list[GroundedRegion] = []
    raw_regions = payload.get("regions")
    if not isinstance(raw_regions, Sequence) or isinstance(raw_regions, (str, bytes)):
        raw_regions = ()
    for item in raw_regions:
        if len(normalized_regions) >= limit:
            break
        if not isinstance(item, Mapping):
            continue
        label = _clean_text(item.get("label"), limit=160)
        if not label:
            continue
        try:
            raw_box = list(item.get("bbox") or ())[:4]
            box = tuple(int(round(float(value))) for value in raw_box)
            confidence = float(item.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError, OverflowError):
            continue
        if len(box) != 4 or not math.isfinite(confidence):
            continue
        x1, y1, x2, y2 = tuple(max(0, min(1000, value)) for value in box)
        if x2 <= x1 or y2 <= y1:
            continue

        screen_left = left + int(round(width * x1 / 1000.0))
        screen_top = top + int(round(height * y1 / 1000.0))
        screen_right = left + int(round(width * x2 / 1000.0))
        screen_bottom = top + int(round(height * y2 / 1000.0))
        if screen_right <= screen_left or screen_bottom <= screen_top:
            continue

        kind = _clean_text(item.get("kind"), limit=24).lower() or "object"
        normalized_regions.append(
            GroundedRegion(
                label=label,
                kind=kind if kind in _ALLOWED_KINDS else "object",
                normalized_bounds=(x1, y1, x2, y2),
                screen_bounds=(
                    screen_left,
                    screen_top,
                    screen_right - screen_left,
                    screen_bottom - screen_top,
                ),
                confidence=max(0.0, min(1.0, confidence)),
                action_hint=_clean_text(item.get("action_hint"), limit=160),
            )
        )

    return GroundingResult(
        scene_summary=_clean_text(payload.get("scene_summary"), limit=320),
        regions=tuple(normalized_regions),
        limitations=_clean_text(payload.get("limitations"), limit=320),
    )


def region_payloads(result: GroundingResult) -> list[dict[str, Any]]:
    """Project grounded regions into the existing click-target region contract."""

    if not isinstance(result, GroundingResult):
        raise TypeError("Grounding result is required.")
    return [
        {
            "text": region.label,
            "kind": region.kind,
            "screen_bounds": list(region.screen_bounds),
            "confidence": region.confidence,
            "source": "vision",
            "backend": "lfm_vision",
        }
        for region in result.regions
    ]


__all__ = [
    "GroundedRegion",
    "GroundingResult",
    "normalize_grounding_result",
    "region_payloads",
]
