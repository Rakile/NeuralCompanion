from __future__ import annotations

from .models import LedPoint


def normalize_layout(points: tuple[LedPoint, ...]) -> tuple[LedPoint, ...]:
    if not points:
        return ()
    min_x = min(point.x for point in points)
    max_x = max(point.x for point in points)
    min_y = min(point.y for point in points)
    max_y = max(point.y for point in points)
    span_x = max_x - min_x
    span_y = max_y - min_y
    return tuple(
        LedPoint(
            point.led_id,
            (point.x - min_x) / span_x if span_x > 0.0 else 0.5,
            (point.y - min_y) / span_y if span_y > 0.0 else 0.5,
        )
        for point in points
    )


def group_k55_zones(points: tuple[LedPoint, ...]) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]:
    zones: list[list[int]] = [[], [], []]
    for point in points:
        zone = min(2, max(0, int(point.x * 3.0)))
        zones[zone].append(point.led_id)
    return tuple(tuple(zone) for zone in zones)  # type: ignore[return-value]
