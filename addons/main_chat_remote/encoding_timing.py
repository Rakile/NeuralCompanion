"""Optional scalar phase measurements; persistence stays with the shared logger."""
from contextlib import contextmanager
import time


@contextmanager
def measure(timings, phase):
    if timings is None:
        yield
        return
    started = time.perf_counter_ns()
    try:
        yield
    finally:
        timings[phase] = timings.get(phase, 0.0)+(time.perf_counter_ns()-started)/1000000


def timed(timings, phase, work, /, *args, **kwargs):
    if timings is None:
        return work(*args, **kwargs)
    with measure(timings, phase):
        return work(*args, **kwargs)
