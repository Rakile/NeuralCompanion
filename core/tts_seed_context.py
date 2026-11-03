"""Apply explicit seeds and hand off each provider's own events to its worker."""
import threading

_lock = threading.Lock()
_serial = 0
_seed = None
_provider_events: dict[str, tuple[int, int]] = {}


def record_seed(seed: int, provider_id: str = 'chatterbox') -> None:
    global _serial, _seed
    with _lock:
        _serial += 1
        _seed = int(seed)
        _provider_events[str(provider_id).strip().lower().replace('-', '_')] = (_serial, _seed)


def seed_event_for(provider_id: str) -> tuple[int, int | None]:
    """An unrelated provider cannot replace a provider's last explicit seed."""
    with _lock:
        return _provider_events.get(str(provider_id).strip().lower().replace('-', '_'), (0, None))


def apply_seed(seed: int, *, provider_id: str = 'chatterbox',
               torch_runtime=None, numpy_runtime=None) -> None:
    """Use NC's existing seed primitive, recording its provider at the source."""
    value = int(seed)
    if not 0 <= value <= 2**32 - 1:
        raise ValueError(f"Seed must be between 0 and 2**32 - 1, got {value}")
    if torch_runtime is None:
        import torch as torch_runtime
    if numpy_runtime is None:
        import numpy as numpy_runtime
    import random
    torch_runtime.manual_seed(value)
    if torch_runtime.cuda.is_available():
        torch_runtime.cuda.manual_seed(value)
        torch_runtime.cuda.manual_seed_all(value)
    random.seed(value)
    numpy_runtime.random.seed(value)
    record_seed(value, provider_id=provider_id)


def seed_event() -> tuple[int, int | None]:
    # NC seeds Python/NumPy/Torch process-wide before asynchronous dispatch.
    # A process provider applies each event once, retaining normal RNG progress
    # between chunks. ContextVar state would be lost at that thread boundary.
    with _lock:
        return _serial, _seed
