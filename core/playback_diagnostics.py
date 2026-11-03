"""Small, privacy-safe helpers for local playback timing diagnostics."""

from __future__ import annotations

import json
import math
import statistics


def latency_summary(values_ms: list[float]) -> dict[str, float]:
    values = sorted(float(value) for value in values_ms)
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Expected nonempty finite nonnegative latencies")
    return dict(
        count=len(values),
        median_ms=statistics.median(values),
        p95_ms=values[math.ceil(.95 * len(values)) - 1],
        max_ms=values[-1],
    )


def case_metric_summaries(records: list[dict]) -> list[dict]:
    """Keep unlike cases, backends, units and observation bases separate."""
    groups = {}
    for record in records:
        for name, metric in record.get("metrics", {}).items():
            key = (record["backend"], record["case"], name, metric["unit"], metric["basis"])
            values, reasons = groups.setdefault(key, ([], set()))
            value = metric.get("value")
            if value is None:
                reasons.add(metric.get("reason") or "unavailable")
            elif isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                values.append(value)
            else:
                reasons.add("invalid_numeric_observation")
    result = []
    for (backend, case, name, unit, basis), (values, reasons) in groups.items():
        summary = latency_summary(values) if values else None
        result.append(dict(event="metric_summary", backend=backend, case=case,
            metric=name, unit=unit, basis=basis, count=len(values),
            median=summary["median_ms"] if summary else None,
            p95=summary["p95_ms"] if summary else None,
            max=summary["max_ms"] if summary else None,
            status="measured" if values else "unavailable", unavailable_reasons=sorted(reasons)))
    return result


TIMING_FIELDS = frozenset({
    "index", "generation", "queue_depth", "sample_rate", "frames",
    "output_frame", "media_frame", "monotonic_time", "stream_time", "dac_time",
    "request_at", "ready_at", "submitted_at", "started_at", "ended_at",
    "command_at", "revoked_at", "paused_at", "resumed_at", "returned_at", "latency_ms",
    "submitted_ahead_ms", "block_size", "zero_frames", "underflow",
    "interrupted", "device_index", "timing_estimated", "cold", "trial", "device_latency_ms",
})


def write_timing_record(stream, event: str, fields: dict[str, object]) -> None:
    """Write numeric timing data only; never serialize spoken or file content."""
    record = {"event": event}
    for key, value in fields.items():
        if key in TIMING_FIELDS and isinstance(value, (bool, int, float)):
            if math.isfinite(float(value)):
                record[key] = value
    try:
        stream.write(json.dumps(record, allow_nan=False) + "\n")
    except (OSError, ValueError):
        return
