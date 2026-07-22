from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from addons.audio_story_mode.audio_sources import AudioSourceSlice


class TranscriptionFailure(RuntimeError):
    pass


def _field(value: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value.get(name)
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _segment_payload(
    source_slice: AudioSourceSlice,
    relative_start: float,
    relative_end: float,
    text: str,
) -> dict[str, Any]:
    source_start = source_slice.local_start_seconds + relative_start
    source_end = source_slice.local_start_seconds + relative_end
    return {
        "start": source_slice.source.global_start_seconds + source_start,
        "end": source_slice.source.global_start_seconds + source_end,
        "text": text,
        "source_index": source_slice.source.index,
        "source_path": source_slice.source.path,
        "source_start_seconds": source_start,
        "source_end_seconds": source_end,
    }


def normalize_stt_result(
    segments: Iterable[Any], info: Any, source_slice: AudioSourceSlice
) -> list[dict[str, Any]]:
    span = max(
        0.0,
        source_slice.local_end_seconds - source_slice.local_start_seconds,
    )
    normalized: list[dict[str, Any]] = []
    for segment in list(segments or []):
        text = str(_field(segment, "text", default="") or "").strip()
        if not text:
            continue
        relative_start = max(
            0.0,
            min(
                span,
                float(_field(segment, "start", "start_seconds", default=0.0) or 0.0),
            ),
        )
        relative_end = max(
            relative_start,
            min(
                span,
                float(_field(segment, "end", "end_seconds", default=span) or span),
            ),
        )
        normalized.append(
            _segment_payload(
                source_slice,
                relative_start,
                relative_end,
                text,
            )
        )
    if normalized:
        return normalized
    if info is None:
        raise TranscriptionFailure(
            f"STT is unavailable for {source_slice.source.display_name}."
        )
    full_text = str(_field(info, "text", "transcript", default="") or "").strip()
    if not full_text:
        raise TranscriptionFailure(
            f"No speech was detected in {source_slice.source.display_name}."
        )
    return [_segment_payload(source_slice, 0.0, span, full_text)]


def transcribe_slice(
    source_slice: AudioSourceSlice,
    *,
    transcribe_file: Callable[[str], object],
    extract_range: Callable[[str, float, float], str],
    cleanup: Callable[[str], None],
    progress: Callable[[int, str], None],
    cancelled: Callable[[], bool],
) -> list[dict[str, Any]]:
    if cancelled():
        raise TranscriptionFailure("Transcription was cancelled.")
    progress(0, f"Transcribing file: {source_slice.source.display_name}")
    full_source = (
        source_slice.local_start_seconds <= 0.001
        and source_slice.local_end_seconds
        >= source_slice.source.duration_seconds - 0.001
    )
    transcribe_path = source_slice.source.path
    extracted_path = ""
    try:
        if not full_source:
            extracted_path = str(
                extract_range(
                    source_slice.source.path,
                    source_slice.local_start_seconds,
                    source_slice.local_end_seconds,
                )
                or ""
            )
            if not extracted_path:
                raise TranscriptionFailure(
                    "Could not extract the requested range from "
                    f"{source_slice.source.display_name}."
                )
            transcribe_path = extracted_path
        result = transcribe_file(transcribe_path)
        if isinstance(result, Mapping):
            segments = result.get("segments", ())
            info = result.get("info", result)
        else:
            try:
                segments, info = result  # type: ignore[misc]
            except (TypeError, ValueError):
                segments = _field(result, "segments", default=())
                info = _field(result, "info", default=result)
        if cancelled():
            raise TranscriptionFailure("Transcription was cancelled.")
        return normalize_stt_result(segments, info, source_slice)
    except TranscriptionFailure:
        raise
    except Exception as exc:
        raise TranscriptionFailure(
            f"{source_slice.source.display_name}: {exc}"
        ) from exc
    finally:
        if extracted_path:
            try:
                cleanup(extracted_path)
            except Exception:
                pass


def transcribe_slices(
    slices: Sequence[AudioSourceSlice],
    *,
    transcribe_file: Callable[[str], object],
    extract_range: Callable[[str, float, float], str],
    cleanup: Callable[[str], None],
    progress: Callable[[int, str], None],
    cancelled: Callable[[], bool],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    count = len(slices)
    if not count:
        raise TranscriptionFailure("The selected range contains no playable audio.")
    for index, source_slice in enumerate(slices):
        normalized.extend(
            transcribe_slice(
                source_slice,
                transcribe_file=transcribe_file,
                extract_range=extract_range,
                cleanup=cleanup,
                progress=lambda _percent, _message, index=index, source_slice=source_slice: progress(
                    int((index / count) * 75),
                    f"Transcribing file {index + 1} of {count}: "
                    f"{source_slice.source.display_name}",
                ),
                cancelled=cancelled,
            )
        )
    progress(75, f"Transcribed {count} file(s); building story scenes.")
    return normalized


__all__ = [
    "TranscriptionFailure",
    "normalize_stt_result",
    "transcribe_slice",
    "transcribe_slices",
]
