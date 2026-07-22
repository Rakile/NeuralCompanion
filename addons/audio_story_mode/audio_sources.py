from __future__ import annotations

import math
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AudioSource:
    index: int
    path: str
    display_name: str
    duration_seconds: float
    global_start_seconds: float
    global_end_seconds: float
    valid: bool = True
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "index": int(self.index),
            "path": str(self.path),
            "display_name": str(self.display_name),
            "duration_seconds": float(self.duration_seconds),
            "global_start_seconds": float(self.global_start_seconds),
            "global_end_seconds": float(self.global_end_seconds),
            "valid": bool(self.valid),
            "error": str(self.error),
        }


@dataclass(frozen=True, slots=True)
class AudioSourceSlice:
    source: AudioSource
    local_start_seconds: float
    local_end_seconds: float
    global_start_seconds: float
    global_end_seconds: float


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(str(path or "").strip()))


def build_audio_sources(
    paths: Iterable[str], duration_reader: Callable[[str], float]
) -> list[AudioSource]:
    records: list[AudioSource] = []
    seen: set[str] = set()
    offset = 0.0
    for raw_path in paths:
        path = str(raw_path or "").strip()
        if not path:
            continue
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        duration = 0.0
        valid = True
        error = ""
        try:
            duration = float(duration_reader(path) or 0.0)
            if not math.isfinite(duration) or duration <= 0.0:
                raise ValueError("audio duration is unavailable")
        except Exception as exc:
            valid = False
            duration = 0.0
            error = str(exc or "audio file is unreadable").strip()
        records.append(
            AudioSource(
                index=len(records),
                path=path,
                display_name=Path(path).name or path,
                duration_seconds=duration,
                global_start_seconds=offset,
                global_end_seconds=offset + duration,
                valid=valid,
                error=error,
            )
        )
        offset += duration
    return records


def total_duration_seconds(sources: Sequence[AudioSource]) -> float:
    return max(
        (float(item.global_end_seconds) for item in sources if item.valid),
        default=0.0,
    )


def split_global_range(
    sources: Sequence[AudioSource], start_seconds: float, end_seconds: float
) -> list[AudioSourceSlice]:
    total = total_duration_seconds(sources)
    start = max(0.0, min(total, float(start_seconds or 0.0)))
    requested_end = float(end_seconds or 0.0)
    end = total if requested_end <= 0.0 else max(start, min(total, requested_end))
    slices: list[AudioSourceSlice] = []
    for source in sources:
        if not source.valid or source.duration_seconds <= 0.0:
            continue
        global_start = max(start, source.global_start_seconds)
        global_end = min(end, source.global_end_seconds)
        if global_end <= global_start:
            continue
        slices.append(
            AudioSourceSlice(
                source=source,
                local_start_seconds=global_start - source.global_start_seconds,
                local_end_seconds=global_end - source.global_start_seconds,
                global_start_seconds=global_start,
                global_end_seconds=global_end,
            )
        )
    return slices


def locate_global_position(
    sources: Sequence[AudioSource], position_seconds: float
) -> tuple[AudioSource, float]:
    playable = [
        item for item in sources if item.valid and item.duration_seconds > 0.0
    ]
    if not playable:
        raise ValueError("No playable audio source is available.")
    total = total_duration_seconds(playable)
    position = max(0.0, min(total, float(position_seconds or 0.0)))
    for index, source in enumerate(playable):
        if position < source.global_end_seconds or index == len(playable) - 1:
            local = max(
                0.0,
                min(
                    source.duration_seconds,
                    position - source.global_start_seconds,
                ),
            )
            return source, local
    return playable[-1], playable[-1].duration_seconds


__all__ = [
    "AudioSource",
    "AudioSourceSlice",
    "build_audio_sources",
    "locate_global_position",
    "split_global_range",
    "total_duration_seconds",
]
