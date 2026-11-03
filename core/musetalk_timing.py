"""Opt-in console timings for MuseTalk handoffs; never writes session state."""

import os
import time


def start_musetalk_timing():
    if os.environ.get("NC_MUSETALK_PREVIEW_LOG", "").strip().lower() in {"1", "true", "yes", "on"}:
        return time.perf_counter()
    return None


def trace_musetalk_timing(stage, started_at, *, chunk, **fields):
    if started_at is None:
        return
    # Cumulative phase timings expose where time was spent, including waits.
    # Only callers' chunk IDs/counts/times belong here, never speech or paths.
    try:
        details = " ".join(f"{key}={value}" for key, value in fields.items())
        print(
            f"[MuseTalkTiming] {stage} at={time.time():.6f} chunk={chunk} "
            f"elapsed_ms={(time.perf_counter() - started_at) * 1000:.1f} {details}",
            flush=True,
        )
    except (OSError, ValueError):
        # A closed console must not interrupt audio or a Qt preview timer.
        pass
