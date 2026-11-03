from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence

from addons.identity_artifacts.normalized_model import IdentityRecord, NormalizedIdentityModel
from addons.identity_artifacts.policy import EffectiveUseDecision


IDENTITY_INDEX_SCHEMA_VERSION = 1
IDENTITY_INDEX_REVISION = "identity-relay-index-v1"
SEMANTIC_THRESHOLD_REVISION = "identity-relay-semantic-v1"
DEFAULT_SEMANTIC_THRESHOLD = 0.72
_EMBEDDING_BATCH_SIZE = 32
_ARTIFACT_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")


class IdentityEmbeddingAdapter(Protocol):
    def embed(
        self, texts: Sequence[str], *, model: str, context: int
    ) -> Sequence[Sequence[float]]:
        ...


@dataclass(frozen=True)
class SemanticIndexMetadata:
    artifact_hash: str
    normalizer_revision: str
    normalized_schema_version: int
    index_schema_version: int
    index_revision: str
    embedding_provider: str
    endpoint_identity: str
    embedding_model: str
    embedding_context: int
    vector_dimension: int
    authorized_record_ids: tuple[str, ...] = ()
    text_hashes: Mapping[str, str] = field(default_factory=dict)
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD
    semantic_threshold_revision: str = SEMANTIC_THRESHOLD_REVISION

    def __post_init__(self) -> None:
        if any(
            not isinstance(record_id, str) or not record_id
            for record_id in self.authorized_record_ids
        ):
            raise ValueError("authorized record IDs must be non-empty strings")
        object.__setattr__(
            self,
            "authorized_record_ids",
            tuple(sorted(set(self.authorized_record_ids))),
        )
        object.__setattr__(
            self,
            "text_hashes",
            MappingProxyType(
                {
                    str(record_id): str(text_hash)
                    for record_id, text_hash in sorted(self.text_hashes.items())
                }
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_hash": self.artifact_hash,
            "normalizer_revision": self.normalizer_revision,
            "normalized_schema_version": self.normalized_schema_version,
            "index_schema_version": self.index_schema_version,
            "index_revision": self.index_revision,
            "embedding_provider": self.embedding_provider,
            "endpoint_identity": self.endpoint_identity,
            "embedding_model": self.embedding_model,
            "embedding_context": self.embedding_context,
            "vector_dimension": self.vector_dimension,
            "authorized_record_ids": list(self.authorized_record_ids),
            "text_hashes": dict(self.text_hashes),
            "semantic_threshold": self.semantic_threshold,
            "semantic_threshold_revision": self.semantic_threshold_revision,
        }


@dataclass(frozen=True)
class SemanticIndexEntry:
    record_id: str
    source_path: str
    semantic_role: str
    subject_refs: tuple[str, ...]
    tags: tuple[str, ...]
    retrieval_hints: tuple[str, ...]
    durability: str
    text_hash: str
    vector: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_refs", tuple(self.subject_refs))
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "retrieval_hints", tuple(self.retrieval_hints))
        object.__setattr__(self, "vector", tuple(float(value) for value in self.vector))


@dataclass(frozen=True)
class SemanticIndexBuildResult:
    status: str
    metadata: SemanticIndexMetadata
    entries: tuple[SemanticIndexEntry, ...] = ()
    cancelled: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))


@dataclass(frozen=True)
class SemanticIndexWriteResult:
    published: bool
    reason: str


@dataclass(frozen=True)
class SemanticIndexSnapshot:
    metadata: SemanticIndexMetadata
    entries: tuple[SemanticIndexEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))


@dataclass(frozen=True)
class SemanticIndexReadResult:
    snapshot: SemanticIndexSnapshot | None
    semantic_available: bool
    reason: str
    rebuild_required: bool


@dataclass(frozen=True)
class SemanticHit:
    record_id: str
    score: float


@dataclass(frozen=True)
class SemanticSearchResult:
    hits: tuple[SemanticHit, ...]
    semantic_available: bool
    reason: str
    rebuild_required: bool
    semantic_threshold: float
    semantic_threshold_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "hits", tuple(self.hits))


def build_identity_semantic_index(
    model: NormalizedIdentityModel,
    adapter: IdentityEmbeddingAdapter,
    metadata: SemanticIndexMetadata,
    *,
    policy_decisions: Mapping[str, EffectiveUseDecision] | None = None,
    cancel_token: Any,
) -> SemanticIndexBuildResult:
    validation_reason = _validate_build_metadata(model, metadata)
    if validation_reason:
        return SemanticIndexBuildResult("failed", metadata, reason=validation_reason)
    if policy_decisions is None:
        return SemanticIndexBuildResult(
            "failed", metadata, reason="authorization_required"
        )
    if _is_cancelled(cancel_token):
        return _cancelled_build(metadata)

    quarantined_ids = {
        record_id
        for item in model.quarantine
        for record_id in item.record_ids
    }
    records: list[tuple[IdentityRecord, str]] = []
    for record_id in sorted(set(model.retrievable_record_ids)):
        if record_id in quarantined_ids:
            continue
        decision = policy_decisions.get(record_id)
        if decision is None or not decision.allowed:
            continue
        record = model.records_by_id.get(record_id)
        if record is None:
            return SemanticIndexBuildResult(
                "failed", metadata, reason="retrievable_record_missing"
            )
        records.append((record, _embedding_text(record)))

    text_hashes = {
        record.record_id: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for record, text in records
    }
    built_metadata = replace(
        metadata,
        authorized_record_ids=tuple(record.record_id for record, _text in records),
        text_hashes=text_hashes,
    )
    entries: list[SemanticIndexEntry] = []
    try:
        for start in range(0, len(records), _EMBEDDING_BATCH_SIZE):
            if _is_cancelled(cancel_token):
                return _cancelled_build(built_metadata)
            batch = records[start : start + _EMBEDDING_BATCH_SIZE]
            vectors = adapter.embed(
                tuple(text for _record, text in batch),
                model=metadata.embedding_model,
                context=metadata.embedding_context,
            )
            if _is_cancelled(cancel_token):
                return _cancelled_build(built_metadata)
            vector_rows = tuple(vectors)
            if len(vector_rows) != len(batch):
                return SemanticIndexBuildResult(
                    "failed", built_metadata, reason="embedding_count_mismatch"
                )
            for (record, _text), vector in zip(batch, vector_rows):
                normalized = _validated_vector(vector, metadata.vector_dimension)
                if normalized is None:
                    return SemanticIndexBuildResult(
                        "failed",
                        built_metadata,
                        reason="embedding_vector_dimension_mismatch",
                    )
                entries.append(
                    SemanticIndexEntry(
                        record_id=record.record_id,
                        source_path=record.source_path,
                        semantic_role=record.semantic_role,
                        subject_refs=record.subject_refs,
                        tags=record.tags,
                        retrieval_hints=record.retrieval_hints,
                        durability=record.durability,
                        text_hash=text_hashes[record.record_id],
                        vector=normalized,
                    )
                )
    except Exception:
        return SemanticIndexBuildResult(
            "failed", built_metadata, reason="embedding_provider_failure"
        )

    if _is_cancelled(cancel_token):
        return _cancelled_build(built_metadata)
    return SemanticIndexBuildResult(
        "complete",
        built_metadata,
        entries=tuple(sorted(entries, key=lambda item: item.record_id)),
    )


class IdentitySemanticIndex:
    def __init__(self, indexes_dir: str | Path):
        self.indexes_dir = Path(indexes_dir)
        self.indexes_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, artifact_hash: str) -> Path:
        _require_artifact_hash(artifact_hash)
        return self.indexes_dir / f"{artifact_hash}.json"

    def delete(self, artifact_hash: str) -> bool:
        path = self.path_for(artifact_hash)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def replace(self, build: SemanticIndexBuildResult) -> SemanticIndexWriteResult:
        if build.status != "complete" or build.cancelled:
            return SemanticIndexWriteResult(False, build.reason or build.status)
        reason = _validate_snapshot(build.metadata, build.entries)
        if reason:
            return SemanticIndexWriteResult(False, reason)

        path = self.path_for(build.metadata.artifact_hash)
        payload = {
            "metadata": build.metadata.to_dict(),
            "entries": [
                {
                    "record_id": entry.record_id,
                    "source_path": entry.source_path,
                    "semantic_role": entry.semantic_role,
                    "subject_refs": list(entry.subject_refs),
                    "tags": list(entry.tags),
                    "retrieval_hints": list(entry.retrieval_hints),
                    "durability": entry.durability,
                    "text_hash": entry.text_hash,
                    "vector": list(entry.vector),
                }
                for entry in build.entries
            ],
        }
        temporary_path: Path | None = None
        try:
            serialized = json.dumps(payload, indent=2, ensure_ascii=False)
            descriptor, temporary_name = tempfile.mkstemp(
                dir=str(self.indexes_dir),
                prefix=f".{build.metadata.artifact_hash}.",
                suffix=".tmp",
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        except OSError:
            return SemanticIndexWriteResult(False, "index_publish_failure")
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
        return SemanticIndexWriteResult(True, "published")

    def read(
        self,
        artifact_hash: str,
        *,
        expected_metadata: SemanticIndexMetadata | None = None,
    ) -> SemanticIndexReadResult:
        path = self.path_for(artifact_hash)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            snapshot = _snapshot_from_dict(payload)
        except FileNotFoundError:
            return SemanticIndexReadResult(None, False, "index_missing", True)
        except (OSError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return SemanticIndexReadResult(None, False, "index_corrupt", True)

        if snapshot.metadata.artifact_hash != artifact_hash:
            return SemanticIndexReadResult(None, False, "artifact_hash_mismatch", True)
        validation_reason = _validate_snapshot(snapshot.metadata, snapshot.entries)
        if validation_reason:
            return SemanticIndexReadResult(None, False, validation_reason, True)
        if expected_metadata is not None:
            mismatch = _metadata_mismatch(snapshot.metadata, expected_metadata)
            if mismatch:
                return SemanticIndexReadResult(None, False, mismatch, True)
        return SemanticIndexReadResult(snapshot, True, "available", False)

    def search(
        self,
        artifact_hash: str,
        query_vector: Sequence[float],
        *,
        expected_metadata: SemanticIndexMetadata | None = None,
        authorized_record_ids: (
            Sequence[str] | set[str] | frozenset[str] | None
        ) = None,
    ) -> SemanticSearchResult:
        threshold = (
            expected_metadata.semantic_threshold
            if expected_metadata is not None
            else DEFAULT_SEMANTIC_THRESHOLD
        )
        threshold_revision = (
            expected_metadata.semantic_threshold_revision
            if expected_metadata is not None
            else SEMANTIC_THRESHOLD_REVISION
        )
        if authorized_record_ids is None:
            return SemanticSearchResult(
                (),
                False,
                "authorization_required",
                False,
                threshold,
                threshold_revision,
            )
        authorized = frozenset(
            record_id
            for record_id in authorized_record_ids
            if isinstance(record_id, str)
        )
        read_result = self.read(artifact_hash, expected_metadata=expected_metadata)
        if not read_result.semantic_available or read_result.snapshot is None:
            return SemanticSearchResult(
                (),
                False,
                read_result.reason,
                read_result.rebuild_required,
                threshold,
                threshold_revision,
            )

        metadata = read_result.snapshot.metadata
        indexed_authorization = frozenset(metadata.authorized_record_ids)
        if not authorized.issubset(indexed_authorization):
            return SemanticSearchResult(
                (),
                False,
                "authorization_scope_expanded",
                True,
                metadata.semantic_threshold,
                metadata.semantic_threshold_revision,
            )
        normalized_query = _validated_vector(query_vector, metadata.vector_dimension)
        if normalized_query is None:
            return SemanticSearchResult(
                (),
                False,
                "query_vector_dimension_mismatch",
                False,
                metadata.semantic_threshold,
                metadata.semantic_threshold_revision,
            )
        query_norm = math.sqrt(sum(value * value for value in normalized_query))
        hits: list[SemanticHit] = []
        if query_norm:
            for entry in read_result.snapshot.entries:
                if entry.record_id not in authorized:
                    continue
                vector_norm = math.sqrt(sum(value * value for value in entry.vector))
                if not vector_norm:
                    continue
                score = sum(
                    left * right for left, right in zip(normalized_query, entry.vector)
                ) / (query_norm * vector_norm)
                if score >= metadata.semantic_threshold:
                    hits.append(SemanticHit(entry.record_id, score))
        hits.sort(key=lambda item: (-item.score, item.record_id))
        return SemanticSearchResult(
            tuple(hits),
            True,
            "available",
            False,
            metadata.semantic_threshold,
            metadata.semantic_threshold_revision,
        )


def _embedding_text(record: Any) -> str:
    fields = (
        record.source_text,
        record.semantic_role,
        " ".join(record.subject_refs),
        " ".join(record.tags),
        " ".join(record.retrieval_hints),
    )
    return "\n".join(value for value in fields if value)


def _validate_build_metadata(
    model: NormalizedIdentityModel, metadata: SemanticIndexMetadata
) -> str:
    try:
        _require_artifact_hash(metadata.artifact_hash)
    except ValueError:
        return "invalid_artifact_hash"
    if metadata.artifact_hash != model.envelope.artifact_hash:
        return "artifact_hash_mismatch"
    if metadata.normalizer_revision != model.normalizer_revision:
        return "normalizer_revision_mismatch"
    if metadata.normalized_schema_version != model.schema_version:
        return "normalized_schema_version_mismatch"
    if metadata.index_schema_version != IDENTITY_INDEX_SCHEMA_VERSION:
        return "index_schema_version_mismatch"
    if metadata.index_revision != IDENTITY_INDEX_REVISION:
        return "index_revision_mismatch"
    if metadata.semantic_threshold_revision != SEMANTIC_THRESHOLD_REVISION:
        return "semantic_threshold_revision_mismatch"
    if not metadata.embedding_provider or not metadata.endpoint_identity or not metadata.embedding_model:
        return "embedding_identity_missing"
    if metadata.embedding_context <= 0 or metadata.vector_dimension <= 0:
        return "embedding_configuration_invalid"
    if not -1.0 <= metadata.semantic_threshold <= 1.0:
        return "semantic_threshold_invalid"
    return ""


def _validate_snapshot(
    metadata: SemanticIndexMetadata, entries: Sequence[SemanticIndexEntry]
) -> str:
    if metadata.index_schema_version != IDENTITY_INDEX_SCHEMA_VERSION:
        return "index_schema_version_mismatch"
    if metadata.index_revision != IDENTITY_INDEX_REVISION:
        return "index_revision_mismatch"
    if metadata.semantic_threshold_revision != SEMANTIC_THRESHOLD_REVISION:
        return "semantic_threshold_revision_mismatch"
    entry_ids = {entry.record_id for entry in entries}
    if set(metadata.authorized_record_ids) != entry_ids:
        return "authorization_scope_mismatch"
    if set(metadata.text_hashes) != {entry.record_id for entry in entries}:
        return "text_hash_set_mismatch"
    for entry in entries:
        if not all(
            isinstance(value, str)
            for value in (
                entry.record_id,
                entry.source_path,
                entry.semantic_role,
                entry.durability,
                entry.text_hash,
                *entry.subject_refs,
                *entry.tags,
                *entry.retrieval_hints,
            )
        ):
            return "deterministic_activation_fields_invalid"
        if metadata.text_hashes.get(entry.record_id) != entry.text_hash:
            return "text_hash_mismatch"
        if _validated_vector(entry.vector, metadata.vector_dimension) is None:
            return "stored_vector_dimension_mismatch"
    return ""


def _metadata_mismatch(
    actual: SemanticIndexMetadata, expected: SemanticIndexMetadata
) -> str:
    fields = (
        "artifact_hash",
        "normalizer_revision",
        "normalized_schema_version",
        "index_schema_version",
        "index_revision",
        "embedding_provider",
        "endpoint_identity",
        "embedding_model",
        "embedding_context",
        "vector_dimension",
        "semantic_threshold",
        "semantic_threshold_revision",
    )
    for field_name in fields:
        if getattr(actual, field_name) != getattr(expected, field_name):
            return f"{field_name}_mismatch"
    if expected.text_hashes and dict(actual.text_hashes) != dict(expected.text_hashes):
        return "text_hashes_mismatch"
    if (
        expected.authorized_record_ids
        and actual.authorized_record_ids != expected.authorized_record_ids
    ):
        return "authorized_record_ids_mismatch"
    return ""


def _snapshot_from_dict(value: Any) -> SemanticIndexSnapshot:
    if not isinstance(value, Mapping):
        raise ValueError("index must be an object")
    metadata = _metadata_from_dict(value.get("metadata"))
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("index entries must be an array")
    entries: list[SemanticIndexEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("index entry must be an object")
        vector = raw_entry.get("vector")
        if not isinstance(vector, list):
            raise ValueError("index vector must be an array")
        entries.append(
            SemanticIndexEntry(
                record_id=_required_string(raw_entry, "record_id"),
                source_path=_required_string(raw_entry, "source_path"),
                semantic_role=_required_string(raw_entry, "semantic_role"),
                subject_refs=_required_string_tuple(raw_entry, "subject_refs"),
                tags=_required_string_tuple(raw_entry, "tags"),
                retrieval_hints=_required_string_tuple(raw_entry, "retrieval_hints"),
                durability=_required_string(raw_entry, "durability"),
                text_hash=_required_string(raw_entry, "text_hash"),
                vector=tuple(vector),
            )
        )
    if len({entry.record_id for entry in entries}) != len(entries):
        raise ValueError("index record IDs must be unique")
    return SemanticIndexSnapshot(metadata, tuple(entries))


def _metadata_from_dict(value: Any) -> SemanticIndexMetadata:
    if not isinstance(value, Mapping):
        raise ValueError("index metadata must be an object")
    text_hashes = value.get("text_hashes")
    if not isinstance(text_hashes, Mapping):
        raise ValueError("text hashes must be an object")
    authorized_record_ids = value.get("authorized_record_ids")
    if (
        not isinstance(authorized_record_ids, list)
        or any(
            not isinstance(record_id, str) or not record_id
            for record_id in authorized_record_ids
        )
        or len(set(authorized_record_ids)) != len(authorized_record_ids)
        or authorized_record_ids != sorted(authorized_record_ids)
    ):
        raise ValueError("authorized record IDs must be a sorted unique string array")
    return SemanticIndexMetadata(
        artifact_hash=str(value.get("artifact_hash") or ""),
        normalizer_revision=str(value.get("normalizer_revision") or ""),
        normalized_schema_version=int(value.get("normalized_schema_version")),
        index_schema_version=int(value.get("index_schema_version")),
        index_revision=str(value.get("index_revision") or ""),
        embedding_provider=str(value.get("embedding_provider") or ""),
        endpoint_identity=str(value.get("endpoint_identity") or ""),
        embedding_model=str(value.get("embedding_model") or ""),
        embedding_context=int(value.get("embedding_context")),
        vector_dimension=int(value.get("vector_dimension")),
        authorized_record_ids=tuple(authorized_record_ids),
        text_hashes={str(key): str(item) for key, item in text_hashes.items()},
        semantic_threshold=float(value.get("semantic_threshold")),
        semantic_threshold_revision=str(value.get("semantic_threshold_revision") or ""),
    )


def _validated_vector(value: Sequence[float], dimension: int) -> tuple[float, ...] | None:
    try:
        vector = tuple(float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if len(vector) != dimension or any(not math.isfinite(item) for item in vector):
        return None
    return vector


def _required_string(value: Mapping[str, Any], field_name: str) -> str:
    item = value.get(field_name)
    if not isinstance(item, str):
        raise ValueError(f"{field_name} must be a string")
    return item


def _required_string_tuple(value: Mapping[str, Any], field_name: str) -> tuple[str, ...]:
    items = value.get(field_name)
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        raise ValueError(f"{field_name} must be an array of strings")
    return tuple(items)


def _cancelled_build(metadata: SemanticIndexMetadata) -> SemanticIndexBuildResult:
    return SemanticIndexBuildResult(
        "cancelled", metadata, cancelled=True, reason="cancelled"
    )


def _is_cancelled(cancel_token: Any) -> bool:
    if cancel_token is None:
        return False
    method = getattr(cancel_token, "is_cancelled", None)
    if callable(method):
        return bool(method())
    value = getattr(cancel_token, "cancelled", False)
    return bool(value() if callable(value) else value)


def _require_artifact_hash(artifact_hash: str) -> None:
    if _ARTIFACT_HASH_RE.fullmatch(str(artifact_hash or "")) is None:
        raise ValueError("artifact_hash must be a full lowercase SHA-256 hash")
