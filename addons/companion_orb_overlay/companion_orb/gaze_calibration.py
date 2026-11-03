from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Mapping, Sequence


CALIBRATION_SCHEMA_VERSION = 1
_MILLIMETERS_PER_INCH = 25.4
_PHYSICAL_SIZE_MIN_MM = 150.0
_PHYSICAL_SIZE_MAX_MM = 3000.0
_GEOMETRY_SIZE_TOLERANCE_PX = 2


def _finite_float(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def _finite_pair(values) -> tuple[float, float] | None:
    try:
        items = list(values or [])[:2]
    except TypeError:
        return None
    if len(items) != 2:
        return None
    left = _finite_float(items[0])
    right = _finite_float(items[1])
    if left is None or right is None:
        return None
    return left, right


def _finite_rect(values) -> tuple[float, float, float, float] | None:
    try:
        items = list(values or [])[:4]
    except TypeError:
        return None
    if len(items) != 4:
        return None
    normalized = tuple(_finite_float(value) for value in items)
    if any(value is None for value in normalized):
        return None
    left, top, width, height = normalized
    if width <= 0.0 or height <= 0.0:
        return None
    return float(left), float(top), float(width), float(height)


def _physical_dimensions_mm(
    diagonal_inches: float,
    aspect_width: float,
    aspect_height: float,
) -> tuple[float, float]:
    diagonal_mm = float(diagonal_inches) * _MILLIMETERS_PER_INCH
    divisor = math.hypot(float(aspect_width), float(aspect_height))
    return (
        diagonal_mm * float(aspect_width) / divisor,
        diagonal_mm * float(aspect_height) / divisor,
    )


@dataclass(frozen=True, slots=True)
class DisplayDescriptor:
    identity: str
    geometry: tuple[int, int, int, int]
    physical_size_mm: tuple[float, float]


@dataclass(frozen=True, slots=True)
class SampleReduction:
    point: tuple[float, float]
    dispersion_px: float
    sample_count: int


@dataclass(frozen=True, slots=True)
class CalibrationTransform:
    coefficients: tuple[float, float, float, float, float, float]
    display: DisplayDescriptor
    calibration_rect: tuple[float, float, float, float]
    quality: str
    median_error_px: float
    maximum_error_px: float
    completed_at: str

    def apply(self, point: Sequence[float]) -> tuple[float, float]:
        normalized = _finite_pair(point)
        if normalized is None:
            raise ValueError("Calibration point must contain two finite coordinates.")
        x, y = normalized
        a, b, c, d, e, f = self.coefficients
        return a * x + b * y + c, d * x + e * y + f

    def to_payload(self) -> dict[str, object]:
        return {
            "version": CALIBRATION_SCHEMA_VERSION,
            "coefficients": [float(value) for value in self.coefficients],
            "display": {
                "identity": str(self.display.identity),
                "geometry": [int(value) for value in self.display.geometry],
                "physical_size_mm": [
                    float(value) for value in self.display.physical_size_mm
                ],
            },
            "calibration_rect": [float(value) for value in self.calibration_rect],
            "quality": str(self.quality),
            "median_error_px": float(self.median_error_px),
            "maximum_error_px": float(self.maximum_error_px),
            "completed_at": str(self.completed_at),
        }


@dataclass(frozen=True, slots=True)
class CalibrationSolveResult:
    accepted: bool
    quality: str
    transform: CalibrationTransform | None
    message: str


def supported_calibration_rect(
    screen_bounds: Sequence[float],
    physical_size_mm: Sequence[float],
) -> tuple[float, float, float, float]:
    bounds = _finite_rect(screen_bounds)
    if bounds is None:
        raise ValueError("Screen bounds must contain four finite positive values.")
    left, top, screen_width, screen_height = bounds
    screen_aspect = screen_width / screen_height
    ultrawide = screen_aspect > 2.0
    target_aspect = 21.0 / 9.0 if ultrawide else 16.0 / 9.0

    physical = _finite_pair(physical_size_mm)
    physical_valid = bool(
        physical is not None
        and _PHYSICAL_SIZE_MIN_MM <= physical[0] <= _PHYSICAL_SIZE_MAX_MM
        and _PHYSICAL_SIZE_MIN_MM <= physical[1] <= _PHYSICAL_SIZE_MAX_MM
    )
    if physical_valid:
        supported_mm = _physical_dimensions_mm(
            30.0 if ultrawide else 27.0,
            21.0 if ultrawide else 16.0,
            9.0,
        )
        width = min(screen_width, supported_mm[0] * screen_width / physical[0])
        height = min(screen_height, supported_mm[1] * screen_height / physical[1])
    else:
        height = screen_height * 0.88
        width = height * target_aspect
        maximum_width = screen_width * 0.88
        if width > maximum_width:
            width = maximum_width
            height = width / target_aspect

    width = max(1.0, min(screen_width, float(width)))
    height = max(1.0, min(screen_height, float(height)))
    return (
        left + (screen_width - width) * 0.5,
        top + (screen_height - height) * 0.5,
        width,
        height,
    )


def calibration_target_points(
    calibration_rect: Sequence[float],
) -> tuple[tuple[float, float], ...]:
    rect = _finite_rect(calibration_rect)
    if rect is None:
        raise ValueError("Calibration rectangle must contain four finite values.")
    left, top, width, height = rect

    def point(x_ratio: float, y_ratio: float) -> tuple[float, float]:
        return left + width * x_ratio, top + height * y_ratio

    return (
        point(0.5, 0.5),
        point(0.2, 0.2),
        point(0.8, 0.2),
        point(0.8, 0.8),
        point(0.2, 0.8),
    )


def reduce_target_samples(
    samples: Sequence[Sequence[float]],
    *,
    minimum_samples: int = 30,
) -> SampleReduction | None:
    valid: list[tuple[float, float]] = []
    for sample in samples or ():
        point = _finite_pair(sample)
        if point is not None:
            valid.append(point)
    required = max(3, int(minimum_samples))
    if len(valid) < required:
        return None

    median_x = float(statistics.median(point[0] for point in valid))
    median_y = float(statistics.median(point[1] for point in valid))
    mad_x = float(statistics.median(abs(point[0] - median_x) for point in valid))
    mad_y = float(statistics.median(abs(point[1] - median_y) for point in valid))
    threshold_x = max(6.0, mad_x * 3.5)
    threshold_y = max(6.0, mad_y * 3.5)
    retained = [
        point
        for point in valid
        if abs(point[0] - median_x) <= threshold_x
        and abs(point[1] - median_y) <= threshold_y
    ]
    if len(retained) < required:
        return None

    reduced_x = float(statistics.median(point[0] for point in retained))
    reduced_y = float(statistics.median(point[1] for point in retained))
    dispersion = float(
        statistics.median(
            math.hypot(point[0] - reduced_x, point[1] - reduced_y)
            for point in retained
        )
    )
    return SampleReduction(
        point=(reduced_x, reduced_y),
        dispersion_px=dispersion,
        sample_count=len(retained),
    )


def _solve_3x3(
    matrix: Sequence[Sequence[float]],
    values: Sequence[float],
) -> tuple[float, float, float] | None:
    rows = [
        [float(matrix[row][column]) for column in range(3)]
        + [float(values[row])]
        for row in range(3)
    ]
    for pivot_index in range(3):
        pivot_row = max(
            range(pivot_index, 3),
            key=lambda row_index: abs(rows[row_index][pivot_index]),
        )
        if abs(rows[pivot_row][pivot_index]) <= 1e-9:
            return None
        if pivot_row != pivot_index:
            rows[pivot_index], rows[pivot_row] = rows[pivot_row], rows[pivot_index]
        pivot = rows[pivot_index][pivot_index]
        rows[pivot_index] = [value / pivot for value in rows[pivot_index]]
        for row_index in range(3):
            if row_index == pivot_index:
                continue
            factor = rows[row_index][pivot_index]
            rows[row_index] = [
                rows[row_index][column] - factor * rows[pivot_index][column]
                for column in range(4)
            ]
    result = tuple(rows[index][3] for index in range(3))
    return result if all(math.isfinite(value) for value in result) else None


def _least_squares_three_columns(
    rows: Sequence[Sequence[float]],
    values: Sequence[float],
) -> tuple[float, float, float] | None:
    normal_matrix = [
        [
            sum(float(row[left]) * float(row[right]) for row in rows)
            for right in range(3)
        ]
        for left in range(3)
    ]
    normal_values = [
        sum(float(row[column]) * float(value) for row, value in zip(rows, values))
        for column in range(3)
    ]
    return _solve_3x3(normal_matrix, normal_values)


def _solve_affine_coefficients(
    observed_points: Sequence[Sequence[float]],
    target_points: Sequence[Sequence[float]],
    calibration_rect: Sequence[float],
) -> tuple[float, float, float, float, float, float] | None:
    rect = _finite_rect(calibration_rect)
    if rect is None:
        return None
    left, top, width, height = rect
    origin_x = left + width * 0.5
    origin_y = top + height * 0.5
    observed = [_finite_pair(point) for point in observed_points]
    targets = [_finite_pair(point) for point in target_points]
    if (
        len(observed) != len(targets)
        or len(observed) < 3
        or any(point is None for point in observed)
        or any(point is None for point in targets)
    ):
        return None
    rows = [
        [point[0] - origin_x, point[1] - origin_y, 1.0]
        for point in observed
    ]
    target_x = [point[0] - origin_x for point in targets]
    target_y = [point[1] - origin_y for point in targets]
    x_solution = _least_squares_three_columns(rows, target_x)
    y_solution = _least_squares_three_columns(rows, target_y)
    if x_solution is None or y_solution is None:
        return None
    a, b, local_c = x_solution
    d, e, local_f = y_solution
    c = origin_x - a * origin_x - b * origin_y + local_c
    f = origin_y - d * origin_x - e * origin_y + local_f
    coefficients = (a, b, c, d, e, f)
    return coefficients if all(math.isfinite(value) for value in coefficients) else None


def _apply_coefficients(
    coefficients: Sequence[float],
    point: Sequence[float],
) -> tuple[float, float]:
    a, b, c, d, e, f = (float(value) for value in coefficients)
    x, y = _finite_pair(point) or (float("nan"), float("nan"))
    return a * x + b * y + c, d * x + e * y + f


def _residuals(
    coefficients: Sequence[float],
    observed_points: Sequence[Sequence[float]],
    target_points: Sequence[Sequence[float]],
) -> list[float]:
    result: list[float] = []
    for observed, target in zip(observed_points, target_points):
        corrected = _apply_coefficients(coefficients, observed)
        expected = _finite_pair(target)
        if expected is None or not all(math.isfinite(value) for value in corrected):
            return []
        result.append(math.hypot(corrected[0] - expected[0], corrected[1] - expected[1]))
    return result


def _affine_within_bounds(
    coefficients: Sequence[float],
    calibration_rect: Sequence[float],
) -> bool:
    rect = _finite_rect(calibration_rect)
    if rect is None:
        return False
    left, top, width, height = rect
    a, b, _c, d, e, _f = (float(value) for value in coefficients)
    if not (0.75 <= a <= 1.25 and 0.75 <= e <= 1.25):
        return False
    if abs(b) > 0.15 or abs(d) > 0.15:
        return False
    center = (left + width * 0.5, top + height * 0.5)
    mapped_center = _apply_coefficients(coefficients, center)
    return (
        abs(mapped_center[0] - center[0]) <= width * 0.25
        and abs(mapped_center[1] - center[1]) <= height * 0.25
    )


def _translation_coefficients(
    observed_points: Sequence[Sequence[float]],
    target_points: Sequence[Sequence[float]],
) -> tuple[float, float, float, float, float, float] | None:
    observed = [_finite_pair(point) for point in observed_points]
    targets = [_finite_pair(point) for point in target_points]
    if (
        len(observed) != len(targets)
        or not observed
        or any(point is None for point in observed)
        or any(point is None for point in targets)
    ):
        return None
    offset_x = float(
        statistics.median(
            target[0] - observed_point[0]
            for observed_point, target in zip(observed, targets)
        )
    )
    offset_y = float(
        statistics.median(
            target[1] - observed_point[1]
            for observed_point, target in zip(observed, targets)
        )
    )
    return 1.0, 0.0, offset_x, 0.0, 1.0, offset_y


def _build_transform(
    *,
    coefficients: Sequence[float],
    display: DisplayDescriptor,
    calibration_rect: Sequence[float],
    quality: str,
    residuals: Sequence[float],
    completed_at: str,
) -> CalibrationTransform:
    return CalibrationTransform(
        coefficients=tuple(float(value) for value in coefficients),
        display=display,
        calibration_rect=tuple(float(value) for value in calibration_rect),
        quality=str(quality),
        median_error_px=float(statistics.median(residuals)),
        maximum_error_px=float(max(residuals)),
        completed_at=str(completed_at),
    )


def solve_calibration(
    *,
    observed_points: Sequence[Sequence[float]],
    target_points: Sequence[Sequence[float]],
    display: DisplayDescriptor,
    calibration_rect: Sequence[float],
    completed_at: str,
) -> CalibrationSolveResult:
    rect = _finite_rect(calibration_rect)
    if (
        rect is None
        or len(observed_points) != len(target_points)
        or len(observed_points) != 5
    ):
        return CalibrationSolveResult(False, "Rejected", None, "Five valid calibration targets are required.")
    diagonal = math.hypot(rect[2], rect[3])
    coefficients = _solve_affine_coefficients(
        observed_points,
        target_points,
        rect,
    )
    if coefficients is not None and _affine_within_bounds(coefficients, rect):
        residuals = _residuals(coefficients, observed_points, target_points)
        if residuals:
            median_error = float(statistics.median(residuals))
            maximum_error = float(max(residuals))
            if (
                median_error <= diagonal * 0.025
                and maximum_error <= diagonal * 0.05
            ):
                quality = "Good" if median_error <= diagonal * 0.015 else "Usable"
                return CalibrationSolveResult(
                    True,
                    quality,
                    _build_transform(
                        coefficients=coefficients,
                        display=display,
                        calibration_rect=rect,
                        quality=quality,
                        residuals=residuals,
                        completed_at=completed_at,
                    ),
                    f"{quality} gaze calibration accepted.",
                )

    translation = _translation_coefficients(observed_points, target_points)
    if translation is not None:
        residuals = _residuals(translation, observed_points, target_points)
        if residuals and float(statistics.median(residuals)) <= diagonal * 0.04:
            return CalibrationSolveResult(
                True,
                "Fair",
                _build_transform(
                    coefficients=translation,
                    display=display,
                    calibration_rect=rect,
                    quality="Fair",
                    residuals=residuals,
                    completed_at=completed_at,
                ),
                "Translation-only gaze calibration accepted.",
            )
    return CalibrationSolveResult(
        False,
        "Rejected",
        None,
        "Calibration was too unstable; the previous calibration was kept.",
    )


def _display_from_payload(value) -> DisplayDescriptor | None:
    if not isinstance(value, Mapping):
        return None
    identity = str(value.get("identity") or "").strip()
    try:
        geometry_values = [int(item) for item in list(value.get("geometry") or [])[:4]]
    except (TypeError, ValueError, OverflowError):
        return None
    physical = _finite_pair(value.get("physical_size_mm"))
    if (
        not identity
        or len(geometry_values) != 4
        or geometry_values[2] <= 0
        or geometry_values[3] <= 0
        or physical is None
    ):
        return None
    return DisplayDescriptor(
        identity=identity,
        geometry=tuple(geometry_values),
        physical_size_mm=physical,
    )


def _display_matches(
    saved: DisplayDescriptor,
    current: DisplayDescriptor,
) -> bool:
    if str(saved.identity) != str(current.identity):
        return False
    saved_geometry = tuple(int(value) for value in saved.geometry)
    current_geometry = tuple(int(value) for value in current.geometry)
    return (
        saved_geometry[0] == current_geometry[0]
        and saved_geometry[1] == current_geometry[1]
        and abs(saved_geometry[2] - current_geometry[2]) <= _GEOMETRY_SIZE_TOLERANCE_PX
        and abs(saved_geometry[3] - current_geometry[3]) <= _GEOMETRY_SIZE_TOLERANCE_PX
    )


def calibration_from_payload(
    payload,
    *,
    display: DisplayDescriptor,
) -> CalibrationTransform | None:
    if not isinstance(payload, Mapping):
        return None
    try:
        version = int(payload.get("version", 0))
    except (TypeError, ValueError, OverflowError):
        return None
    if version != CALIBRATION_SCHEMA_VERSION:
        return None
    try:
        coefficients = tuple(
            float(value) for value in list(payload.get("coefficients") or [])[:6]
        )
    except (TypeError, ValueError, OverflowError):
        return None
    if len(coefficients) != 6 or not all(math.isfinite(value) for value in coefficients):
        return None
    saved_display = _display_from_payload(payload.get("display"))
    rect = _finite_rect(payload.get("calibration_rect"))
    quality = str(payload.get("quality") or "").strip()
    median_error = _finite_float(payload.get("median_error_px"))
    maximum_error = _finite_float(payload.get("maximum_error_px"))
    completed_at = str(payload.get("completed_at") or "").strip()
    if (
        saved_display is None
        or not _display_matches(saved_display, display)
        or rect is None
        or quality not in {"Good", "Usable", "Fair"}
        or median_error is None
        or maximum_error is None
        or median_error < 0.0
        or maximum_error < median_error
        or not completed_at
        or not _affine_within_bounds(coefficients, rect)
    ):
        return None
    diagonal = math.hypot(rect[2], rect[3])
    if quality in {"Good", "Usable"}:
        if median_error > diagonal * 0.025 or maximum_error > diagonal * 0.05:
            return None
    elif median_error > diagonal * 0.04:
        return None
    return CalibrationTransform(
        coefficients=coefficients,
        display=saved_display,
        calibration_rect=rect,
        quality=quality,
        median_error_px=median_error,
        maximum_error_px=maximum_error,
        completed_at=completed_at,
    )
