"""Dependency-free records for runtime baseline measurements."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import os
import threading
import time
from types import MappingProxyType


MonotonicClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RuntimeMetricSample:
    """One named baseline measurement."""

    name: str
    value: float
    unit: str = "ms"
    labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """Aggregate values for samples with a shared metric name."""

    count: int
    minimum: float
    maximum: float
    mean: float
    unit: str


@dataclass(frozen=True, slots=True)
class RuntimeMeasurementStatus:
    """An explicitly unavailable measurement, never a synthetic zero."""

    name: str
    reason: str
    labels: tuple[tuple[str, str], ...] = ()


class RuntimeBaseline:
    """In-memory sink for deterministic baseline reports."""

    def __init__(self) -> None:
        self._samples: list[RuntimeMetricSample] = []
        self._not_measured: list[RuntimeMeasurementStatus] = []
        self._sample_signatures: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {}

    def record(self, sample: RuntimeMetricSample) -> None:
        signature = (sample.unit, sample.labels)
        previous_signature = self._sample_signatures.get(sample.name)
        if previous_signature is not None and previous_signature != signature:
            raise ValueError(
                f"Metric '{sample.name}' must keep one unit and label set per baseline."
            )
        self._sample_signatures[sample.name] = signature
        self._samples.append(sample)

    def mark_not_measured(
        self,
        name: str,
        reason: str,
        *,
        labels: tuple[tuple[str, str], ...] = (),
    ) -> None:
        self._not_measured.append(RuntimeMeasurementStatus(name, reason, labels))

    def summary(self) -> Mapping[str, MetricSummary]:
        values: dict[str, list[RuntimeMetricSample]] = defaultdict(list)
        for sample in self._samples:
            values[sample.name].append(sample)

        summaries = {
            name: MetricSummary(
                count=len(samples),
                minimum=min(sample.value for sample in samples),
                maximum=max(sample.value for sample in samples),
                mean=sum(sample.value for sample in samples) / len(samples),
                unit=samples[0].unit,
            )
            for name, samples in sorted(values.items())
        }
        return MappingProxyType(summaries)

    def to_json(self) -> dict[str, object]:
        return {
            "measurements": {
                name: {
                    "count": summary.count,
                    "maximum": summary.maximum,
                    "mean": summary.mean,
                    "minimum": summary.minimum,
                    "unit": summary.unit,
                }
                for name, summary in self.summary().items()
            },
            "not_measured": [
                {
                    "labels": dict(sorted(status.labels)),
                    "name": status.name,
                    "reason": status.reason,
                }
                for status in sorted(
                    self._not_measured,
                    key=lambda status: (status.name, status.reason, status.labels),
                )
            ],
        }


@contextmanager
def timing_span(
    sink: RuntimeBaseline | None,
    name: str,
    *,
    clock: MonotonicClock = time.perf_counter,
    unit: str = "ms",
    labels: tuple[tuple[str, str], ...] = (),
) -> Iterator[None]:
    """Record an elapsed span only when a baseline sink is configured."""

    if sink is None:
        yield
        return

    started = clock()
    try:
        yield
    finally:
        sink.record(RuntimeMetricSample(name, (clock() - started) * 1000.0, unit, labels))


def capture_runtime_snapshot() -> dict[str, int | float]:
    """Return a lightweight snapshot without importing the application runtime."""

    return {
        "active_thread_count": threading.active_count(),
        "process_cpu_ms": round(time.process_time() * 1000.0, 3),
        "process_id": os.getpid(),
    }
