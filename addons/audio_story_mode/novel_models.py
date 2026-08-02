from __future__ import annotations

import copy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol


SOURCE_KIND_AUDIO = "audio"
SOURCE_KIND_CHATLOG_JSON = "chatlog_json"
SOURCE_KIND_MARKDOWN = "markdown"
SOURCE_KINDS = frozenset(
    {
        SOURCE_KIND_AUDIO,
        SOURCE_KIND_CHATLOG_JSON,
        SOURCE_KIND_MARKDOWN,
    }
)
ADAPTATION_STYLE_FAITHFUL = "faithful"
ADAPTATION_STYLE_LIGHTLY_NOVELIZED = "lightly_novelized"
ADAPTATION_STYLE_CREATIVE_FICTION = "creative_fiction"
ADAPTATION_STYLES = frozenset(
    {
        ADAPTATION_STYLE_FAITHFUL,
        ADAPTATION_STYLE_LIGHTLY_NOVELIZED,
        ADAPTATION_STYLE_CREATIVE_FICTION,
    }
)


def normalize_source_kind(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in SOURCE_KINDS else SOURCE_KIND_AUDIO


def normalize_adaptation_style(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in ADAPTATION_STYLES else ADAPTATION_STYLE_FAITHFUL


@dataclass(frozen=True)
class SourceReference:
    kind: str
    original_path: str
    fingerprint: str = ""
    import_revision: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": normalize_source_kind(self.kind),
            "original_path": str(self.original_path or ""),
            "fingerprint": str(self.fingerprint or ""),
            "import_revision": max(0, int(self.import_revision or 0)),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourceReference":
        source = dict(value or {})
        try:
            revision = max(0, int(source.get("import_revision", 0) or 0))
        except (TypeError, ValueError):
            revision = 0
        return cls(
            kind=normalize_source_kind(source.get("kind")),
            original_path=str(source.get("original_path") or ""),
            fingerprint=str(source.get("fingerprint") or ""),
            import_revision=revision,
        )


@dataclass(frozen=True)
class ChatlogFieldMap:
    collection_path: tuple[str, ...] = ()
    speaker_field: str = ""
    text_field: str = ""
    role_field: str = ""
    timestamp_field: str = ""
    thread_field: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection_path": list(self.collection_path),
            "speaker_field": self.speaker_field,
            "text_field": self.text_field,
            "role_field": self.role_field,
            "timestamp_field": self.timestamp_field,
            "thread_field": self.thread_field,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ChatlogFieldMap":
        source = dict(value or {})
        raw_path = source.get("collection_path")
        path = (
            tuple(str(item) for item in raw_path if str(item))
            if isinstance(raw_path, (list, tuple))
            else ()
        )
        return cls(
            collection_path=path,
            speaker_field=str(source.get("speaker_field") or ""),
            text_field=str(source.get("text_field") or ""),
            role_field=str(source.get("role_field") or ""),
            timestamp_field=str(source.get("timestamp_field") or ""),
            thread_field=str(source.get("thread_field") or ""),
        )


@dataclass(frozen=True)
class NormalizedMessage:
    source_record_id: str
    sequence: int
    speaker: str
    text: str
    role: str = ""
    timestamp: str = ""
    thread_id: str = ""
    reply_to: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_record_id": self.source_record_id,
            "sequence": int(self.sequence),
            "speaker": self.speaker,
            "text": self.text,
            "role": self.role,
            "timestamp": self.timestamp,
            "thread_id": self.thread_id,
            "reply_to": self.reply_to,
            "metadata": copy.deepcopy(dict(self.metadata or {})),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NormalizedMessage":
        source = dict(value or {})
        return cls(
            source_record_id=str(source.get("source_record_id") or ""),
            sequence=max(0, int(source.get("sequence", 0) or 0)),
            speaker=str(source.get("speaker") or ""),
            text=str(source.get("text") or ""),
            role=str(source.get("role") or ""),
            timestamp=str(source.get("timestamp") or ""),
            thread_id=str(source.get("thread_id") or ""),
            reply_to=str(source.get("reply_to") or ""),
            metadata=copy.deepcopy(dict(source.get("metadata") or {})),
        )


@dataclass(frozen=True)
class NarrationChunk:
    index: int
    text: str
    start_seconds: float
    end_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_index": int(self.index),
            "text": self.text,
            "start_seconds": float(self.start_seconds),
            "end_seconds": float(self.end_seconds),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "NarrationChunk":
        source = dict(value or {})
        return cls(
            index=max(0, int(source.get("chunk_index", source.get("index", 0)) or 0)),
            text=str(source.get("text") or ""),
            start_seconds=max(0.0, float(source.get("start_seconds", 0.0) or 0.0)),
            end_seconds=max(0.0, float(source.get("end_seconds", 0.0) or 0.0)),
        )


@dataclass(frozen=True)
class SourcePreview:
    source_kind: str
    source_path: str
    fingerprint: str
    parser_id: str
    field_map: ChatlogFieldMap = field(default_factory=ChatlogFieldMap)
    record_count: int = 0
    source_size_bytes: int = 0
    participant_count: int = 0
    participants: tuple[str, ...] = ()
    participants_truncated: bool = False
    skipped_count: int = 0
    date_start: str = ""
    date_end: str = ""
    estimated_chunks: int = 0
    ambiguities: tuple[str, ...] = ()
    samples: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_kind": normalize_source_kind(self.source_kind),
            "source_path": self.source_path,
            "fingerprint": self.fingerprint,
            "parser_id": self.parser_id,
            "field_map": self.field_map.to_dict(),
            "record_count": max(0, int(self.record_count)),
            "source_size_bytes": max(0, int(self.source_size_bytes)),
            "participant_count": max(0, int(self.participant_count)),
            "participants": list(self.participants),
            "participants_truncated": bool(self.participants_truncated),
            "skipped_count": max(0, int(self.skipped_count)),
            "date_start": self.date_start,
            "date_end": self.date_end,
            "estimated_chunks": max(0, int(self.estimated_chunks)),
            "ambiguities": list(self.ambiguities),
            "samples": [copy.deepcopy(dict(item)) for item in self.samples],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SourcePreview":
        source = dict(value or {})
        participants = source.get("participants")
        ambiguities = source.get("ambiguities")
        samples = source.get("samples")
        return cls(
            source_kind=normalize_source_kind(source.get("source_kind")),
            source_path=str(source.get("source_path") or ""),
            fingerprint=str(source.get("fingerprint") or ""),
            parser_id=str(source.get("parser_id") or ""),
            field_map=ChatlogFieldMap.from_mapping(source.get("field_map") or {}),
            record_count=max(0, int(source.get("record_count", 0) or 0)),
            source_size_bytes=max(
                0, int(source.get("source_size_bytes", 0) or 0)
            ),
            participant_count=max(0, int(source.get("participant_count", 0) or 0)),
            participants=tuple(str(item) for item in participants or ()),
            participants_truncated=bool(source.get("participants_truncated", False)),
            skipped_count=max(0, int(source.get("skipped_count", 0) or 0)),
            date_start=str(source.get("date_start") or ""),
            date_end=str(source.get("date_end") or ""),
            estimated_chunks=max(0, int(source.get("estimated_chunks", 0) or 0)),
            ambiguities=tuple(str(item) for item in ambiguities or ()),
            samples=tuple(
                copy.deepcopy(dict(item))
                for item in samples or ()
                if isinstance(item, Mapping)
            ),
        )


@dataclass(frozen=True)
class ImportResult:
    project_id: str
    source_fingerprint: str
    chunk_count: int
    record_count: int
    skipped_count: int


@dataclass(frozen=True)
class GenerationResult:
    project_id: str
    completed_scene_ids: tuple[str, ...]
    failed_scene_ids: tuple[str, ...]
    cancelled: bool = False


@dataclass(frozen=True)
class AssemblyResult:
    project_id: str
    novel_ref: str
    chapter_refs: tuple[str, ...]
    novel_text: str
    partial: bool = False


@dataclass(frozen=True)
class NovelProjectState:
    project_id: str
    source_fingerprint: str
    import_status: str
    completed_chunk_refs: tuple[str, ...]
    story_map_status: str = "pending"
    outline_status: str = "pending"
    assembly_status: str = "pending"


class NovelLlmClient(Protocol):
    def request_json(
        self,
        stage: str,
        payload: Mapping[str, Any],
        settings: Any,
        cancel_check=None,
    ) -> Mapping[str, Any]: ...

    def request_text(
        self,
        stage: str,
        payload: Mapping[str, Any],
        settings: Any,
        cancel_check=None,
    ) -> str: ...


@dataclass(frozen=True)
class FrozenNovelSettings:
    provider_id: str
    model: str
    adaptation_style: str
    novel_instructions: str = ""
    prompt_additions: Mapping[str, str] = field(default_factory=dict)
    source_revision: int = 0
    max_batch_records: int = 250
    max_batch_characters: int = 12_000

    def __post_init__(self) -> None:
        additions = {
            str(key): str(value)
            for key, value in dict(self.prompt_additions or {}).items()
            if str(key)
        }
        object.__setattr__(self, "provider_id", str(self.provider_id or "").strip())
        object.__setattr__(self, "model", str(self.model or "").strip())
        object.__setattr__(
            self,
            "adaptation_style",
            normalize_adaptation_style(self.adaptation_style),
        )
        object.__setattr__(
            self, "novel_instructions", str(self.novel_instructions or "").strip()
        )
        object.__setattr__(self, "prompt_additions", MappingProxyType(additions))
        object.__setattr__(self, "source_revision", max(0, int(self.source_revision or 0)))
        object.__setattr__(
            self, "max_batch_records", max(1, int(self.max_batch_records or 1))
        )
        object.__setattr__(
            self,
            "max_batch_characters",
            max(1_000, int(self.max_batch_characters or 1_000)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model": self.model,
            "adaptation_style": self.adaptation_style,
            "novel_instructions": self.novel_instructions,
            "prompt_additions": dict(self.prompt_additions),
            "source_revision": self.source_revision,
            "max_batch_records": self.max_batch_records,
            "max_batch_characters": self.max_batch_characters,
        }
