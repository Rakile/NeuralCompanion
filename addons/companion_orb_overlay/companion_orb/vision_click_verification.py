from __future__ import annotations

import difflib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


INTERACTIVE_LFM_KINDS = frozenset({"button", "link", "field", "control"})


@dataclass(frozen=True, slots=True)
class VerificationThresholds:
    label_similarity: float = 0.80
    bounds_overlap: float = 0.35
    score_margin: float = 0.15


@dataclass(frozen=True, slots=True)
class FrozenLfmClickTarget:
    label: str
    kind: str
    bounds: tuple[int, int, int, int]
    confidence: float
    source: str
    backend: str
    capture_bounds: tuple[int, int, int, int]
    capture_fingerprint: str


@dataclass(frozen=True, slots=True)
class PendingLfmClickConfirmation:
    target: FrozenLfmClickTarget
    selected_index: int
    scan_generation: int
    window_hwnd: int
    provider_id: str
    model_id: str
    base_url: str
    model_handling: str
    minimum_confidence: float
    thresholds: VerificationThresholds
    timeout_seconds: float
    confirmation_method: str
    sound_enabled: bool
    confirmation_dwell_ms: int = 1200
    confirmation_generation: int = 0
    endpoint_identity: str = ""
    preview_png: bytes = b""
    preview_crosshair: tuple[float, float] = (0.5, 0.5)


@dataclass(frozen=True, slots=True)
class LfmClickVerification:
    accepted: bool
    reason: str
    click_point: tuple[float, float] | None = None
    fresh_bounds: tuple[int, int, int, int] | None = None


def _normalized_label(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalized_rectangle(value: object) -> tuple[int, ...]:
    if isinstance(value, (str, bytes)):
        return ()
    try:
        return tuple(int(item) for item in list(value or ())[:4])
    except (TypeError, ValueError, OverflowError):
        return ()


def _normalized_minimum_confidence(value: object) -> float | None:
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(normalized):
        return None
    return max(0.0, min(1.0, normalized))


def lfm_click_eligible(payload: object, *, minimum_confidence: float) -> bool:
    if not isinstance(payload, Mapping):
        return False
    minimum = _normalized_minimum_confidence(minimum_confidence)
    if minimum is None:
        return False
    label = _normalized_label(payload.get("label"))
    kind = str(payload.get("kind") or "").strip().lower()
    source = str(payload.get("source") or "").strip().lower()
    backend = str(payload.get("backend") or "").strip().lower()
    bounds = _normalized_rectangle(payload.get("bounds"))
    capture = _normalized_rectangle(payload.get("capture_bounds"))
    try:
        confidence = float(payload.get("confidence") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return False
    fingerprint = str(payload.get("capture_fingerprint") or "").strip().lower()
    inside_capture = bool(
        len(bounds) == 4
        and len(capture) == 4
        and bounds[0] >= capture[0]
        and bounds[1] >= capture[1]
        and bounds[0] + bounds[2] <= capture[0] + capture[2]
        and bounds[1] + bounds[3] <= capture[1] + capture[3]
    )
    area_ok = bool(
        len(bounds) == 4
        and len(capture) == 4
        and bounds[2] * bounds[3] < capture[2] * capture[3] * 0.45
    )
    return bool(
        label
        and kind in INTERACTIVE_LFM_KINDS
        and source == "vision"
        and backend == "lfm_vision"
        and len(bounds) == 4
        and bounds[2] > 0
        and bounds[3] > 0
        and len(capture) == 4
        and capture[2] > 0
        and capture[3] > 0
        and inside_capture
        and area_ok
        and len(fingerprint) == 64
        and all(character in "0123456789abcdef" for character in fingerprint)
        and math.isfinite(confidence)
        and confidence >= minimum
    )


def freeze_lfm_click_target(
    payload: object,
    *,
    minimum_confidence: float,
) -> FrozenLfmClickTarget:
    if not lfm_click_eligible(payload, minimum_confidence=minimum_confidence):
        raise ValueError("The LFM target is not eligible for clicking.")
    assert isinstance(payload, Mapping)
    return FrozenLfmClickTarget(
        label=_normalized_label(payload.get("label")),
        kind=str(payload.get("kind") or "").strip().lower(),
        bounds=tuple(_normalized_rectangle(payload.get("bounds"))),
        confidence=max(0.0, min(1.0, float(payload.get("confidence") or 0.0))),
        source=str(payload.get("source") or "").strip().lower(),
        backend=str(payload.get("backend") or "").strip().lower(),
        capture_bounds=tuple(_normalized_rectangle(payload.get("capture_bounds"))),
        capture_fingerprint=str(payload.get("capture_fingerprint") or "").strip().lower(),
    )


def verify_lfm_click_target(
    frozen: FrozenLfmClickTarget,
    candidates: Sequence[object],
    *,
    thresholds: VerificationThresholds,
    minimum_confidence: float,
) -> LfmClickVerification:
    if not isinstance(frozen, FrozenLfmClickTarget):
        raise TypeError("A frozen LFM click target is required.")
    ranked: list[tuple[float, FrozenLfmClickTarget]] = []
    kind_seen = False
    label_seen = False
    original_left, original_top, original_width, original_height = frozen.bounds
    original_right = original_left + original_width
    original_bottom = original_top + original_height
    tolerance_x = min(48, max(12, round(original_width * 0.25)))
    tolerance_y = min(48, max(12, round(original_height * 0.25)))
    for payload in candidates:
        try:
            fresh = freeze_lfm_click_target(
                payload,
                minimum_confidence=minimum_confidence,
            )
        except (TypeError, ValueError):
            continue
        if fresh.kind != frozen.kind:
            continue
        kind_seen = True
        label_score = difflib.SequenceMatcher(
            None,
            frozen.label.casefold(),
            fresh.label.casefold(),
        ).ratio()
        if label_score < thresholds.label_similarity:
            continue
        label_seen = True
        fresh_left, fresh_top, fresh_width, fresh_height = fresh.bounds
        fresh_right = fresh_left + fresh_width
        fresh_bottom = fresh_top + fresh_height
        intersection_width = max(
            0,
            min(original_right, fresh_right) - max(original_left, fresh_left),
        )
        intersection_height = max(
            0,
            min(original_bottom, fresh_bottom) - max(original_top, fresh_top),
        )
        intersection = intersection_width * intersection_height
        union = (
            original_width * original_height
            + fresh_width * fresh_height
            - intersection
        )
        overlap = intersection / float(union) if union > 0 else 0.0
        fresh_center = (
            fresh_left + fresh_width * 0.5,
            fresh_top + fresh_height * 0.5,
        )
        center_ok = bool(
            original_left - tolerance_x
            <= fresh_center[0]
            <= original_right + tolerance_x
            and original_top - tolerance_y
            <= fresh_center[1]
            <= original_bottom + tolerance_y
        )
        if overlap < thresholds.bounds_overlap or not center_ok:
            continue
        score = 0.50 * label_score + 0.35 * overlap + 0.15 * fresh.confidence
        ranked.append((score, fresh))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        reason = (
            "Target moved."
            if label_seen
            else "Target changed."
            if kind_seen
            else "Could not verify target."
        )
        return LfmClickVerification(False, reason)
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < thresholds.score_margin:
        return LfmClickVerification(False, "Target was ambiguous.")
    fresh = ranked[0][1]
    left, top, width, height = fresh.bounds
    return LfmClickVerification(
        True,
        "",
        click_point=(left + width * 0.5, top + height * 0.5),
        fresh_bounds=fresh.bounds,
    )


class DoubleBlinkConfirmationPolicy:
    def __init__(
        self,
        *,
        maximum_gap_ms: int = 1200,
        minimum_closed_ms: int = 80,
        maximum_closed_ms: int = 900,
    ) -> None:
        self.maximum_gap_seconds = max(0.20, float(maximum_gap_ms) / 1000.0)
        self.minimum_closed_ms = max(20.0, float(minimum_closed_ms))
        self.maximum_closed_ms = max(
            self.minimum_closed_ms + 20.0,
            float(maximum_closed_ms),
        )
        self._first_blink_at: float | None = None

    def reset(self) -> None:
        self._first_blink_at = None

    def ingest(self, *, closed_ms: float, ended_at: float) -> bool:
        duration = float(closed_ms)
        sample_at = float(ended_at)
        if not self.minimum_closed_ms <= duration <= self.maximum_closed_ms:
            self.reset()
            return False
        previous = self._first_blink_at
        if previous is None or sample_at - previous > self.maximum_gap_seconds:
            self._first_blink_at = sample_at
            return False
        self.reset()
        return True
