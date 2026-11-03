from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any


def compute_audio_fingerprint(
    path: str | Path,
    duration_reader: Callable[[str], float],
    *,
    sample_bytes: int = 1024 * 1024,
    progress: Callable[[int, str], None] | None = None,
) -> dict:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(str(source))
    size = source.stat().st_size
    width = max(4096, min(int(sample_bytes), max(4096, size)))
    offsets = sorted({0, max(0, (size - width) // 2), max(0, size - width)})
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for index, offset in enumerate(offsets):
            stream.seek(offset)
            digest.update(str(offset).encode("ascii") + b"\0")
            digest.update(stream.read(width))
            if callable(progress):
                progress(int(((index + 1) / len(offsets)) * 100), f"Fingerprinting {source.name}")
    duration_ms = int(round(max(0.0, float(duration_reader(str(source)) or 0.0)) * 1000.0))
    if duration_ms <= 0:
        raise ValueError("audio duration is unavailable")
    return {
        "algorithm": "sha256-sampled-v1",
        "digest": digest.hexdigest(),
        "size_bytes": size,
        "duration_ms": duration_ms,
    }


def fingerprint_matches(left: Mapping, right: Mapping) -> bool:
    if not isinstance(left, Mapping) or not isinstance(right, Mapping):
        return False
    required_fields = ("algorithm", "digest", "size_bytes", "duration_ms")
    if any(field not in left or field not in right for field in required_fields):
        return False
    if (
        left["algorithm"] != right["algorithm"]
        or left["digest"] != right["digest"]
        or left["size_bytes"] != right["size_bytes"]
    ):
        return False
    try:
        return abs(int(left["duration_ms"]) - int(right["duration_ms"])) <= 50
    except (TypeError, ValueError):
        return False
