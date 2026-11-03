from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

from addons.audio_story_mode import novel_models


CancelCheck = Callable[[], bool]

_READ_BLOCK_SIZE = 64 * 1024
_MAX_RECORD_CHARACTERS = 2_000_000
_SAMPLE_RECORDS = 25
_MAX_PREVIEW_PARTICIPANTS = 256
_MAX_SPEAKER_CHARACTERS = 160
_MAX_ROLE_CHARACTERS = 80
_MAX_TIMESTAMP_CHARACTERS = 128
_MAX_THREAD_CHARACTERS = 160
_MAX_REPLY_CHARACTERS = 160
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
)
_COMMON_COLLECTION_PATHS = (
    ("messages",),
    ("chatlog",),
    ("items",),
    ("data", "messages"),
    ("data", "items"),
    ("conversation", "messages"),
)
_FIELD_ALIASES = {
    "speaker": ("author", "speaker", "sender", "user", "name", "username"),
    "text": ("content", "text", "message", "body"),
    "role": ("role", "type"),
    "timestamp": ("timestamp", "created_at", "createdAt", "time", "date"),
    "thread": ("thread_id", "thread", "conversation_id", "channel_id", "channel"),
    "reply": ("reply_to", "parent_id", "reply_to_id"),
}


class SourceImportError(RuntimeError):
    pass


class SourceImportCancelled(SourceImportError):
    pass


class AmbiguousChatlogMapping(SourceImportError):
    pass


class SourceRecordTooLarge(SourceImportError):
    pass


@dataclass
class _ScanStats:
    skipped: int = 0


class _BufferedCharReader:
    def __init__(self, handle) -> None:
        self._handle = handle
        self._buffer = ""
        self._index = 0
        self._pushed: list[str] = []

    def get(self) -> str:
        if self._pushed:
            return self._pushed.pop()
        if self._index >= len(self._buffer):
            self._buffer = self._handle.read(_READ_BLOCK_SIZE)
            self._index = 0
            if not self._buffer:
                return ""
        value = self._buffer[self._index]
        self._index += 1
        return value

    def push(self, value: str) -> None:
        if value:
            self._pushed.append(value)

    def non_whitespace(self) -> str:
        while True:
            value = self.get()
            if not value or not value.isspace():
                return value


def _require_not_cancelled(cancel_check: CancelCheck | None) -> None:
    if callable(cancel_check) and bool(cancel_check()):
        raise SourceImportCancelled("Source import was cancelled.")


def fingerprint_path(path: str | Path, cancel_check: CancelCheck | None = None) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            _require_not_cancelled(cancel_check)
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _consume_raw_value(
    reader: _BufferedCharReader,
    first: str,
    *,
    capture: bool,
    max_characters: int = _MAX_RECORD_CHARACTERS,
) -> str:
    if not first:
        raise SourceImportError("Unexpected end of JSON input.")
    output = [first] if capture else []
    captured_characters = len(first) if capture else 0

    def append(value: str) -> None:
        nonlocal captured_characters
        if not capture:
            return
        output.append(value)
        captured_characters += len(value)
        if captured_characters > max_characters:
            raise SourceRecordTooLarge(
                f"A chatlog record exceeds {max_characters:,} characters."
            )

    if first == '"':
        escaped = False
        while True:
            value = reader.get()
            if not value:
                raise SourceImportError("Unterminated JSON string.")
            append(value)
            if escaped:
                escaped = False
            elif value == "\\":
                escaped = True
            elif value == '"':
                break
        return "".join(output)

    if first in "{[":
        stack = ["}" if first == "{" else "]"]
        in_string = False
        escaped = False
        while stack:
            value = reader.get()
            if not value:
                raise SourceImportError("Unterminated JSON value.")
            append(value)
            if in_string:
                if escaped:
                    escaped = False
                elif value == "\\":
                    escaped = True
                elif value == '"':
                    in_string = False
                continue
            if value == '"':
                in_string = True
            elif value == "{":
                stack.append("}")
            elif value == "[":
                stack.append("]")
            elif value in "}]":
                expected = stack.pop()
                if value != expected:
                    raise SourceImportError("Mismatched JSON delimiters.")
        return "".join(output)

    while True:
        value = reader.get()
        if not value or value in ",]}" or value.isspace():
            reader.push(value)
            break
        append(value)
    return "".join(output)


def _read_json_string(reader: _BufferedCharReader, first: str) -> str:
    if first != '"':
        raise SourceImportError("Expected a JSON object key.")
    try:
        return str(json.loads(_consume_raw_value(reader, first, capture=True)))
    except json.JSONDecodeError as exc:
        raise SourceImportError("Invalid JSON object key.") from exc


def _seek_in_object(reader: _BufferedCharReader, path: Sequence[str]) -> bool:
    while True:
        key_start = reader.non_whitespace()
        if key_start == "}":
            return False
        key = _read_json_string(reader, key_start)
        if reader.non_whitespace() != ":":
            raise SourceImportError("Expected ':' after JSON object key.")
        value_start = reader.non_whitespace()
        if key == path[0]:
            if len(path) == 1 and value_start == "[":
                return True
            if len(path) > 1 and value_start == "{":
                if _seek_in_object(reader, path[1:]):
                    return True
            else:
                _consume_raw_value(reader, value_start, capture=False)
        else:
            _consume_raw_value(reader, value_start, capture=False)
        separator = reader.non_whitespace()
        if separator == "}":
            return False
        if separator != ",":
            raise SourceImportError("Expected ',' or '}' in JSON object.")


def _seek_collection(reader: _BufferedCharReader, path: Sequence[str]) -> bool:
    first = reader.non_whitespace()
    if not path:
        if first != "[":
            raise SourceImportError("Expected a top-level JSON array.")
        return True
    if first != "{":
        return False
    return _seek_in_object(reader, path)


def _iter_document_array(
    path: Path,
    collection_path: Sequence[str],
    stats: _ScanStats,
    cancel_check: CancelCheck | None,
) -> Iterator[tuple[int, Mapping]]:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        reader = _BufferedCharReader(handle)
        if not _seek_collection(reader, collection_path):
            raise SourceImportError(
                "The selected JSON message collection was not found."
            )
        sequence = 0
        while True:
            _require_not_cancelled(cancel_check)
            value_start = reader.non_whitespace()
            if value_start == "]":
                return
            sequence += 1
            try:
                raw = _consume_raw_value(reader, value_start, capture=True)
                value = json.loads(raw)
            except (json.JSONDecodeError, SourceRecordTooLarge):
                stats.skipped += 1
                value = None
                valid_json = False
            else:
                valid_json = True
            if isinstance(value, Mapping):
                yield sequence, dict(value)
            elif valid_json:
                stats.skipped += 1
            separator = reader.non_whitespace()
            if separator == "]":
                return
            if separator != ",":
                raise SourceImportError("Expected ',' or ']' in JSON message array.")


def _iter_json_lines(
    path: Path,
    stats: _ScanStats,
    cancel_check: CancelCheck | None,
) -> Iterator[tuple[int, Mapping]]:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        sequence = 0
        for line in handle:
            _require_not_cancelled(cancel_check)
            if not line.strip():
                continue
            sequence += 1
            if len(line) > _MAX_RECORD_CHARACTERS:
                stats.skipped += 1
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                stats.skipped += 1
                continue
            if isinstance(value, Mapping):
                yield sequence, dict(value)
            else:
                stats.skipped += 1


def _first_non_whitespace(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        while True:
            value = handle.read(1)
            if not value or not value.isspace():
                return value


def _looks_like_json_lines(path: Path) -> bool:
    valid = 0
    with path.open("r", encoding="utf-8-sig", errors="strict") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                return False
            if not isinstance(value, Mapping):
                return False
            valid += 1
            if valid >= 2:
                return True
    return False


def _collection_exists(path: Path, collection_path: Sequence[str]) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            return _seek_collection(_BufferedCharReader(handle), collection_path)
    except (OSError, UnicodeError, SourceImportError):
        return False


def _optional_field(samples: Sequence[Mapping], aliases: Sequence[str]) -> str:
    present = [alias for alias in aliases if any(alias in sample for sample in samples)]
    return present[0] if len(present) == 1 else ""


def _required_field(
    samples: Sequence[Mapping],
    aliases: Sequence[str],
    label: str,
    ambiguities: list[str],
) -> str:
    present = [alias for alias in aliases if any(alias in sample for sample in samples)]
    if len(present) == 1:
        return present[0]
    if not present:
        ambiguities.append(f"No {label} field was detected.")
    else:
        ambiguities.append(
            f"Multiple {label} fields were detected: {', '.join(present)}."
        )
    return ""


def _normalized_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _bounded_scalar(value, maximum: int) -> str:
    return _normalized_text(value)[: max(0, int(maximum))]


def _safe_preview_sample(raw: Mapping) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in raw.items():
        normalized_key = str(key or "")[:64]
        lowered = normalized_key.casefold()
        if not normalized_key or any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            continue
        normalized_value = _bounded_scalar(value, 240)
        if normalized_value:
            result[normalized_key] = normalized_value
        if len(result) >= 12:
            break
    return result


def _normalize_record(
    raw: Mapping,
    sequence: int,
    fingerprint: str,
    field_map: novel_models.ChatlogFieldMap,
) -> novel_models.NormalizedMessage | None:
    text = _normalized_text(raw.get(field_map.text_field))
    if not text:
        return None
    role = (
        _bounded_scalar(raw.get(field_map.role_field), _MAX_ROLE_CHARACTERS)
        if field_map.role_field
        else ""
    )
    speaker = (
        _bounded_scalar(raw.get(field_map.speaker_field), _MAX_SPEAKER_CHARACTERS)
        if field_map.speaker_field
        else role
    )
    if not speaker:
        speaker = "Unknown"
    timestamp = (
        _bounded_scalar(raw.get(field_map.timestamp_field), _MAX_TIMESTAMP_CHARACTERS)
        if field_map.timestamp_field
        else ""
    )
    thread_id = (
        _bounded_scalar(raw.get(field_map.thread_field), _MAX_THREAD_CHARACTERS)
        if field_map.thread_field
        else ""
    )
    reply_field = _optional_field((raw,), _FIELD_ALIASES["reply"])
    reply_to = (
        _bounded_scalar(raw.get(reply_field), _MAX_REPLY_CHARACTERS)
        if reply_field
        else ""
    )
    record_id = hashlib.sha256(
        f"{fingerprint}:{sequence}".encode("utf-8")
    ).hexdigest()[:24]
    metadata = {
        "source_sequence": sequence,
    }
    return novel_models.NormalizedMessage(
        source_record_id=record_id,
        sequence=sequence,
        speaker=speaker,
        text=text,
        role=role,
        timestamp=timestamp,
        thread_id=thread_id,
        reply_to=reply_to,
        metadata=metadata,
    )


def _split_oversized_message(
    message: novel_models.NormalizedMessage,
    max_serialized_characters: int,
) -> tuple[novel_models.NormalizedMessage, ...]:
    encoded = json.dumps(message.to_dict(), ensure_ascii=False)
    if len(encoded) <= max_serialized_characters:
        return (message,)
    parts: list[str] = []
    offset = 0
    while offset < len(message.text):
        part_index = len(parts) + 1
        low = 1
        high = len(message.text) - offset
        accepted = 0
        while low <= high:
            midpoint = (low + high) // 2
            candidate = replace(
                message,
                source_record_id=f"{message.source_record_id}-p{part_index}",
                text=message.text[offset:offset + midpoint],
                metadata={
                    **dict(message.metadata),
                    "source_record_id": message.source_record_id,
                    "part_index": part_index,
                    "part_count": 9_999_999,
                },
            )
            if len(json.dumps(candidate.to_dict(), ensure_ascii=False)) <= max_serialized_characters:
                accepted = midpoint
                low = midpoint + 1
            else:
                high = midpoint - 1
        if accepted <= 0:
            raise SourceImportError(
                "Mapped chatlog metadata is too large for the configured batch limit."
            )
        parts.append(message.text[offset:offset + accepted])
        offset += accepted
    return tuple(
        replace(
            message,
            source_record_id=f"{message.source_record_id}-p{index + 1}",
            text=part,
            metadata={
                **dict(message.metadata),
                "source_record_id": message.source_record_id,
                "part_index": index + 1,
                "part_count": len(parts),
            },
        )
        for index, part in enumerate(parts)
    )


def _update_date_bounds(start: str, end: str, value: str) -> tuple[str, str]:
    if not value:
        return start, end
    if not start:
        return value, value
    try:
        numeric_value = float(value)
        start_key = float(start)
        end_key = float(end)
    except (TypeError, ValueError):
        return min(start, value), max(end, value)
    return (
        value if numeric_value < start_key else start,
        value if numeric_value > end_key else end,
    )


class ChatlogSourceAdapter:
    def inspect(
        self,
        path: str | Path,
        field_map: novel_models.ChatlogFieldMap | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> novel_models.SourcePreview:
        source_path = Path(path)
        if not source_path.is_file():
            raise SourceImportError(f"Chatlog file does not exist: {source_path}")
        _require_not_cancelled(cancel_check)
        fingerprint = fingerprint_path(source_path, cancel_check)
        parser_id, collection_path = self._detect_parser(source_path, field_map)
        raw_stats = _ScanStats()
        samples: list[Mapping] = []
        raw_record_count = 0
        for _sequence, raw in self._iter_raw(
            source_path, parser_id, collection_path, raw_stats, cancel_check
        ):
            raw_record_count += 1
            if len(samples) < _SAMPLE_RECORDS:
                samples.append(raw)
        selected_map, ambiguities = self._resolve_field_map(
            samples, collection_path, field_map
        )
        if ambiguities:
            return novel_models.SourcePreview(
                source_kind=novel_models.SOURCE_KIND_CHATLOG_JSON,
                source_path=str(source_path.resolve()),
                fingerprint=fingerprint,
                parser_id=parser_id,
                field_map=selected_map,
                record_count=raw_record_count,
                source_size_bytes=source_path.stat().st_size,
                skipped_count=raw_stats.skipped,
                ambiguities=tuple(ambiguities),
                samples=tuple(_safe_preview_sample(item) for item in samples[:5]),
            )

        stats = _ScanStats()
        records = 0
        participants: set[str] = set()
        participants_truncated = False
        date_start = ""
        date_end = ""
        normalized_samples: list[Mapping] = []
        for sequence, raw in self._iter_raw(
            source_path, parser_id, collection_path, stats, cancel_check
        ):
            message = _normalize_record(raw, sequence, fingerprint, selected_map)
            if message is None:
                stats.skipped += 1
                continue
            records += 1
            if message.speaker in participants:
                pass
            elif len(participants) < _MAX_PREVIEW_PARTICIPANTS:
                participants.add(message.speaker)
            else:
                participants_truncated = True
            if message.timestamp:
                date_start, date_end = _update_date_bounds(
                    date_start, date_end, message.timestamp
                )
            if len(normalized_samples) < 5:
                normalized_samples.append(message.to_dict())
        ordered_participants = tuple(sorted(participants, key=str.casefold))
        return novel_models.SourcePreview(
            source_kind=novel_models.SOURCE_KIND_CHATLOG_JSON,
            source_path=str(source_path.resolve()),
            fingerprint=fingerprint,
            parser_id=parser_id,
            field_map=selected_map,
            record_count=records,
            source_size_bytes=source_path.stat().st_size,
            participant_count=len(ordered_participants),
            participants=ordered_participants,
            participants_truncated=participants_truncated,
            skipped_count=stats.skipped,
            date_start=date_start,
            date_end=date_end,
            estimated_chunks=int(math.ceil(records / 250.0)) if records else 0,
            samples=tuple(normalized_samples),
        )

    def iter_batches(
        self,
        path: str | Path,
        preview: novel_models.SourcePreview,
        *,
        max_records: int = 250,
        max_serialized_chars: int = 12_000,
        cancel_check: CancelCheck | None = None,
    ) -> Iterator[tuple[novel_models.NormalizedMessage, ...]]:
        if preview.ambiguities:
            raise AmbiguousChatlogMapping("Confirm the chatlog field mapping first.")
        if not preview.field_map.text_field:
            raise AmbiguousChatlogMapping("A chatlog text field is required.")
        source_path = Path(path)
        if fingerprint_path(source_path, cancel_check) != preview.fingerprint:
            raise SourceImportError("Chatlog changed after it was inspected.")
        record_limit = max(1, int(max_records))
        character_limit = max(1_000, int(max_serialized_chars))
        stats = _ScanStats()
        batch: list[novel_models.NormalizedMessage] = []
        batch_characters = 2
        for sequence, raw in self._iter_raw(
            source_path,
            preview.parser_id,
            preview.field_map.collection_path,
            stats,
            cancel_check,
        ):
            message = _normalize_record(
                raw, sequence, preview.fingerprint, preview.field_map
            )
            if message is None:
                continue
            for part in _split_oversized_message(message, character_limit - 2):
                serialized = json.dumps(part.to_dict(), ensure_ascii=False)
                addition = len(serialized) + (2 if batch else 0)
                if batch and (
                    len(batch) >= record_limit
                    or batch_characters + addition > character_limit
                ):
                    yield tuple(batch)
                    batch = []
                    batch_characters = 2
                    addition = len(serialized)
                if batch_characters + addition > character_limit:
                    raise SourceImportError(
                        "A normalized chatlog message exceeds the batch limit."
                    )
                batch.append(part)
                batch_characters += addition
        if batch:
            yield tuple(batch)

    def _detect_parser(
        self,
        path: Path,
        field_map: novel_models.ChatlogFieldMap | None,
    ) -> tuple[str, tuple[str, ...]]:
        suffix = path.suffix.casefold()
        if suffix in {".jsonl", ".ndjson"}:
            return "json_lines", ()
        first = _first_non_whitespace(path)
        if first == "[":
            return "json_array", ()
        if first != "{":
            raise SourceImportError("Chatlog must contain JSON objects or an array.")
        if field_map is not None and field_map.collection_path:
            path_value = tuple(field_map.collection_path)
            if not _collection_exists(path, path_value):
                raise SourceImportError("The mapped chatlog collection was not found.")
            return "json_object_array", path_value
        for candidate in _COMMON_COLLECTION_PATHS:
            if _collection_exists(path, candidate):
                return "json_object_array", candidate
        if _looks_like_json_lines(path):
            return "json_lines", ()
        raise SourceImportError(
            "No supported message array was found; choose the collection fields manually."
        )

    def _iter_raw(
        self,
        path: Path,
        parser_id: str,
        collection_path: Sequence[str],
        stats: _ScanStats,
        cancel_check: CancelCheck | None,
    ) -> Iterator[tuple[int, Mapping]]:
        if parser_id == "json_lines":
            yield from _iter_json_lines(path, stats, cancel_check)
            return
        if parser_id in {"json_array", "json_object_array"}:
            yield from _iter_document_array(
                path, collection_path, stats, cancel_check
            )
            return
        raise SourceImportError(f"Unsupported chatlog parser: {parser_id}")

    @staticmethod
    def _resolve_field_map(
        samples: Sequence[Mapping],
        collection_path: Sequence[str],
        requested: novel_models.ChatlogFieldMap | None,
    ) -> tuple[novel_models.ChatlogFieldMap, list[str]]:
        ambiguities: list[str] = []
        requested = requested or novel_models.ChatlogFieldMap()
        text_field = requested.text_field or _required_field(
            samples, _FIELD_ALIASES["text"], "text", ambiguities
        )
        speaker_field = requested.speaker_field or _required_field(
            samples, _FIELD_ALIASES["speaker"], "speaker", ambiguities
        )
        role_field = requested.role_field or _optional_field(
            samples, _FIELD_ALIASES["role"]
        )
        if not speaker_field and role_field:
            speaker_field = role_field
            ambiguities[:] = [
                item for item in ambiguities if "speaker field" not in item
            ]
        return (
            novel_models.ChatlogFieldMap(
                collection_path=tuple(collection_path),
                speaker_field=speaker_field,
                text_field=text_field,
                role_field=role_field,
                timestamp_field=requested.timestamp_field
                or _optional_field(samples, _FIELD_ALIASES["timestamp"]),
                thread_field=requested.thread_field
                or _optional_field(samples, _FIELD_ALIASES["thread"]),
            ),
            ambiguities,
        )
