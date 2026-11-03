from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence


SEGMENT_SCHEMA_VERSION = 1
TARGET_SEGMENT_SECONDS = 25.0
MAX_SEGMENT_SECONDS = 30.0
_OFFSET_DURATION_TOLERANCE_SECONDS = 0.25
_MAX_STABLE_PROJECT_TOKEN_LENGTH = 80
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_SCHEDULING_SETTING_KEYS = frozenset(
    {
        "bufferseconds",
        "startupbufferseconds",
        "renderaheadseconds",
    }
)


@dataclass(frozen=True)
class TtsSegmentPlan:
    index: int
    signature: str
    text: str
    window_indices: tuple[int, ...]
    estimated_seconds: float
    audio_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class TtsReadySegment:
    plan: TtsSegmentPlan
    duration_seconds: float
    chunk_offsets: tuple[tuple[int, float, float], ...]


@dataclass(frozen=True)
class TtsQueuePlan:
    signature: str
    project_id: str
    segments: tuple[TtsSegmentPlan, ...]


def normalized_tts_settings_snapshot(settings_snapshot: Mapping) -> dict:
    """Return the canonical render-affecting settings used by queue signatures."""
    def without_scheduling_preferences(value):
        if isinstance(value, Mapping):
            return {
                key: without_scheduling_preferences(item)
                for key, item in value.items()
                if re.sub(r"[^a-z0-9]+", "", str(key).casefold())
                not in _SCHEDULING_SETTING_KEYS
            }
        if isinstance(value, (list, tuple)):
            return [without_scheduling_preferences(item) for item in value]
        return value

    return json.loads(
        json.dumps(
            without_scheduling_preferences(dict(settings_snapshot or {})),
            sort_keys=True,
            default=str,
        )
    )


def _safe_project_cache_token(project_id: str) -> str:
    """Keep ordinary IDs stable and hash every filesystem-ambiguous value."""
    raw = str(project_id or "legacy")
    base_name = raw.split(".", 1)[0].upper()
    stable = bool(
        raw not in {".", ".."}
        and len(raw) <= _MAX_STABLE_PROJECT_TOKEN_LENGTH
        and raw == raw.rstrip(". ")
        and re.fullmatch(r"[A-Za-z0-9._-]+", raw)
        and base_name not in _WINDOWS_RESERVED_NAMES
    )
    if stable:
        return raw
    digest = hashlib.sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()
    return f"project_{digest[:24]}"


def build_tts_queue_plan(
    transcript_chunks: Sequence[Mapping],
    settings_snapshot: Mapping,
    cache_root: Path,
    project_id: str,
    *,
    target_seconds: float = TARGET_SEGMENT_SECONDS,
    max_seconds: float = MAX_SEGMENT_SECONDS,
) -> TtsQueuePlan:
    """Build deterministic, window-preserving TTS work units for one project."""
    cache_root = Path(cache_root).resolve()
    tts_root = (cache_root / "tts_segments").resolve()
    safe_project = _safe_project_cache_token(str(project_id or "legacy"))
    settings = normalized_tts_settings_snapshot(settings_snapshot)
    windows = []
    for index, source in enumerate(transcript_chunks):
        chunk = dict(source or {})
        start = max(0.0, float(chunk.get("start_seconds", 0.0) or 0.0))
        end = max(start, float(chunk.get("end_seconds", start) or start))
        windows.append((index, str(chunk.get("text", "") or "").strip(), start, end))

    groups: list[list[tuple[int, str, float, float]]] = []
    current: list[tuple[int, str, float, float]] = []
    current_seconds = 0.0
    for window in windows:
        estimated = max(0.25, window[3] - window[2])
        if current and current_seconds + estimated > max_seconds:
            groups.append(current)
            current = []
            current_seconds = 0.0
        current.append(window)
        current_seconds += estimated
        if current_seconds >= target_seconds:
            groups.append(current)
            current = []
            current_seconds = 0.0
    if current:
        groups.append(current)

    identities = []
    for group in groups:
        identity = {
            "schema_version": SEGMENT_SCHEMA_VERSION,
            "settings": settings,
            "windows": [
                {"index": index, "text": text, "start": start, "end": end}
                for index, text, start, end in group
            ],
        }
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        identities.append((group, hashlib.sha256(encoded).hexdigest()))

    queue_payload = {
        "schema_version": SEGMENT_SCHEMA_VERSION,
        "project_id": str(project_id or ""),
        "segments": [signature for _group, signature in identities],
    }
    queue_signature = hashlib.sha256(
        json.dumps(queue_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    queue_root = (tts_root / safe_project / queue_signature).resolve()
    if not _is_strict_descendant(tts_root, queue_root):
        raise ValueError(f"Refusing TTS queue path outside {tts_root}")
    segments = []
    for index, (group, signature) in enumerate(identities):
        segments.append(
            TtsSegmentPlan(
                index=index,
                signature=signature,
                text="\n".join(item[1] for item in group if item[1]),
                window_indices=tuple(item[0] for item in group),
                estimated_seconds=sum(max(0.25, item[3] - item[2]) for item in group),
                audio_path=queue_root / f"segment_{index:05d}_{signature[:16]}.wav",
                metadata_path=queue_root / f"segment_{index:05d}_{signature[:16]}.json",
            )
        )
    return TtsQueuePlan(
        signature=queue_signature,
        project_id=str(project_id or ""),
        segments=tuple(segments),
    )


def load_ready_segment(
    plan: TtsSegmentPlan,
    duration_probe: Callable[[Path], float],
) -> TtsReadySegment | None:
    """Return a validated cache entry, or ``None`` when it is stale or invalid."""
    if not plan.audio_path.is_file() or not plan.metadata_path.is_file():
        return None
    try:
        payload = json.loads(plan.metadata_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            return None
        if int(payload.get("schema_version", 0) or 0) != SEGMENT_SCHEMA_VERSION:
            return None
        if str(payload.get("signature", "") or "") != plan.signature:
            return None
        probed_duration = float(duration_probe(plan.audio_path) or 0.0)
        stored_duration = float(payload.get("duration_seconds", 0.0) or 0.0)
        if not math.isfinite(probed_duration) or not math.isfinite(stored_duration):
            return None
        duration = max(0.0, probed_duration)
        stored_duration = max(0.0, stored_duration)
        if duration <= 0.0 or abs(duration - stored_duration) > 0.25:
            return None
        offsets = _validated_chunk_offsets(
            payload.get("chunk_offsets", []), duration
        )
        if offsets is None:
            return None
    except (IndexError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return TtsReadySegment(plan=plan, duration_seconds=duration, chunk_offsets=offsets)


def publish_ready_segment(
    plan: TtsSegmentPlan,
    temporary_audio_path: Path,
    duration_seconds: float,
    chunk_offsets: Sequence[tuple[int, float, float]],
) -> TtsReadySegment:
    """Atomically publish a rendered segment and its matching metadata sidecar."""
    duration = max(0.0, float(duration_seconds or 0.0))
    if duration <= 0.0 or not Path(temporary_audio_path).is_file():
        raise ValueError("A rendered TTS segment must contain valid audio.")
    plan.audio_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(temporary_audio_path), str(plan.audio_path))
    payload = {
        "schema_version": SEGMENT_SCHEMA_VERSION,
        "signature": plan.signature,
        "duration_seconds": duration,
        "chunk_offsets": [list(item) for item in chunk_offsets],
    }
    temporary_metadata = plan.metadata_path.with_suffix(".json.tmp")
    temporary_metadata.write_text(
        json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8"
    )
    os.replace(str(temporary_metadata), str(plan.metadata_path))
    return TtsReadySegment(
        plan=plan,
        duration_seconds=duration,
        chunk_offsets=tuple(chunk_offsets),
    )


def ready_seconds_from(
    ready_by_index: Mapping[int, TtsReadySegment],
    start_index: int,
    local_offset_seconds: float = 0.0,
) -> float:
    """Measure contiguous ready audio from a queue index, less a local offset."""
    total = 0.0
    for index in range(
        max(0, int(start_index)), max(ready_by_index.keys(), default=-1) + 1
    ):
        ready = ready_by_index.get(index)
        if ready is None:
            break
        total += ready.duration_seconds
    return max(0.0, total - max(0.0, float(local_offset_seconds or 0.0)))


def clear_audio_story_tts_cache(cache_root: Path) -> tuple[int, int]:
    """Remove only Audio Story TTS artifacts beneath the supplied cache root."""
    root = Path(cache_root).resolve()
    targets = [root / "tts_segments"]
    targets.extend(root.glob("tts_story_*.wav"))
    targets.extend(root.glob("tts_story_*.json"))
    file_count = 0
    directory_count = 0
    for target in targets:
        if _is_link_or_junction(target):
            raise ValueError(f"Refusing to clear linked TTS cache target {target}")
        resolved = target.resolve()
        if not _is_strict_descendant(root, resolved):
            raise ValueError(f"Refusing to clear TTS cache outside {root}")
        if resolved.is_dir():
            file_count += sum(1 for item in resolved.rglob("*") if item.is_file())
            shutil.rmtree(resolved)
            directory_count += 1
        elif resolved.is_file():
            resolved.unlink()
            file_count += 1
    return file_count, directory_count


def _is_strict_descendant(root: Path, target: Path) -> bool:
    """Return whether a resolved deletion target is below, never equal to, root."""
    return root in target.parents


def _is_link_or_junction(target: Path) -> bool:
    """Treat filesystem links as unsafe cache-clear targets on every platform."""
    try:
        if target.is_symlink():
            return True
        is_junction = getattr(target, "is_junction", None)
        return bool(is_junction()) if callable(is_junction) else False
    except OSError:
        return True


def _validated_chunk_offsets(
    raw_offsets: object,
    duration_seconds: float,
) -> tuple[tuple[int, float, float], ...] | None:
    if not isinstance(raw_offsets, list):
        return None
    offsets = []
    for item in raw_offsets:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            return None
        index, start, end = item
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            return None
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
        ):
            return None
        start_seconds = float(start)
        end_seconds = float(end)
        if (
            not math.isfinite(start_seconds)
            or not math.isfinite(end_seconds)
            or start_seconds < 0.0
            or end_seconds < start_seconds
            or end_seconds > duration_seconds + _OFFSET_DURATION_TOLERANCE_SECONDS
        ):
            return None
        offsets.append((index, start_seconds, end_seconds))
    return tuple(offsets)
