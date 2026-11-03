from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


NORMALIZED_SCHEMA_VERSION = 1
NORMALIZER_REVISION = "identity-relay-v0.1.3"


def normalized_identity_digest(model: "NormalizedIdentityModel") -> str:
    payload = json.dumps(
        model.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class SubjectClass(str, Enum):
    ASSISTANT_SELF = "assistant_self"
    OTHER_ENTITY = "other_entity"
    RELATIONSHIP = "relationship"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class RuntimeLayer(str, Enum):
    KERNEL = "kernel"
    RETRIEVABLE = "retrievable"
    PROVENANCE = "provenance"
    UNCLASSIFIED = "unclassified"


class ReviewKind(str, Enum):
    SUBJECT_CLASS = "subject_class"
    RUNTIME_LAYER = "runtime_layer"
    UNKNOWN_FIELD = "unknown_field"
    RUNTIME_PERMISSION = "runtime_permission"
    INCOMPATIBLE_PROJECTION = "incompatible_projection"
    TRANSIENT_TTL = "transient_ttl"


class QuarantineReason(str, Enum):
    INTEGRITY = "integrity"
    OWNERSHIP = "ownership"
    POLICY = "policy"
    PRIVACY = "privacy"
    PROVENANCE = "provenance"
    CORRUPTION = "corruption"
    INVALID_ATTRIBUTION = "invalid_attribution"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _tuple(value: Any) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return ()


@dataclass(frozen=True)
class ArtifactEnvelope:
    artifact_hash: str
    format: str
    format_version: str
    export_kind: str
    artifact_mode: str = ""
    default_runtime_context: str = ""
    subject_class: SubjectClass = SubjectClass.UNKNOWN
    artifact_contract: Mapping[str, Any] = field(default_factory=dict)
    source_scope: Mapping[str, Any] = field(default_factory=dict)
    source_registry: Mapping[str, Any] = field(default_factory=dict)
    coverage_assessment: Mapping[str, Any] = field(default_factory=dict)
    exposure_model: Mapping[str, Any] = field(default_factory=dict)
    import_notes: Mapping[str, Any] = field(default_factory=dict)
    artifact_limits: Mapping[str, Any] = field(default_factory=dict)
    mechanical_audit: tuple[str, ...] = ()
    semantic_audit: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "artifact_contract",
            "source_scope",
            "source_registry",
            "coverage_assessment",
            "exposure_model",
            "import_notes",
            "artifact_limits",
            "semantic_audit",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))
        object.__setattr__(self, "mechanical_audit", tuple(self.mechanical_audit))


@dataclass(frozen=True)
class IdentityRecord:
    record_id: str
    source_path: str
    source_text: str
    semantic_role: str
    subject_refs: tuple[str, ...]
    stability: str
    confidence: float | None
    epistemic_qualifier: str
    runtime_layer: RuntimeLayer
    durability: str
    stale_after: str | None
    tags: tuple[str, ...]
    retrieval_hints: tuple[str, ...]
    declared_policy: Mapping[str, Any]
    exposure_policy: Mapping[str, Any]
    privacy_class: str
    runtime_suitability: tuple[str, ...]
    review_state: str
    wording_provenance: Mapping[str, Any]
    provenance: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in ("subject_refs", "tags", "retrieval_hints", "runtime_suitability"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in ("declared_policy", "exposure_policy", "wording_provenance", "provenance"):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True)
class LinkedTension:
    tension_id: str
    record_ids: tuple[str, ...]
    subject_refs: tuple[str, ...] = ()
    scope: str = "identity"
    state: str = "unresolved"
    epistemic_states: tuple[str, ...] = ()
    review_history: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_ids", tuple(self.record_ids))
        object.__setattr__(self, "subject_refs", tuple(self.subject_refs))
        object.__setattr__(self, "epistemic_states", tuple(self.epistemic_states))
        object.__setattr__(self, "review_history", tuple(_freeze(item) for item in self.review_history))


@dataclass(frozen=True)
class ReviewItem:
    review_id: str
    kind: ReviewKind
    record_ids: tuple[str, ...] = ()
    source_paths: tuple[str, ...] = ()
    proposed_value: str = ""
    reason: str = ""
    state: str = "pending"
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_ids", tuple(self.record_ids))
        object.__setattr__(self, "source_paths", tuple(self.source_paths))
        object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True)
class QuarantineItem:
    quarantine_id: str
    reason: QuarantineReason
    record_ids: tuple[str, ...] = ()
    source_path: str = ""
    source_text: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_ids", tuple(self.record_ids))
        object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True)
class TransientRecord:
    record_id: str = ""
    source_path: str = ""
    source_text: str = ""
    subject_refs: tuple[str, ...] = ()
    included_item_ids: tuple[str, ...] = ()
    ttl_hint: str = ""
    ttl_seconds: int | None = None
    origin_timestamp: str | None = None
    expiration_notes: tuple[str, ...] = ()
    confidence: float | None = None
    staleness_risk: float | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    active_by_default: bool = False
    semantic_role: str = "transient_continuity"
    runtime_layer: RuntimeLayer = RuntimeLayer.RETRIEVABLE
    epistemic_qualifier: str = "unspecified"
    declared_policy: Mapping[str, Any] = field(default_factory=dict)
    exposure_policy: Mapping[str, Any] = field(default_factory=dict)
    privacy_class: str = "unspecified"
    runtime_suitability: tuple[str, ...] = ()
    review_state: str = "not_required"
    activation_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "subject_refs",
            "included_item_ids",
            "expiration_notes",
            "runtime_suitability",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        for name in (
            "provenance",
            "declared_policy",
            "exposure_policy",
            "activation_metadata",
        ):
            object.__setattr__(self, name, _freeze(getattr(self, name)))


@dataclass(frozen=True)
class NormalizedIdentityModel:
    schema_version: int
    normalizer_revision: str
    envelope: ArtifactEnvelope
    records: tuple[IdentityRecord, ...]
    kernel_record_ids: tuple[str, ...]
    retrievable_record_ids: tuple[str, ...]
    transient_records: tuple[TransientRecord, ...]
    tensions: tuple[LinkedTension, ...]
    review_queue: tuple[ReviewItem, ...]
    quarantine: tuple[QuarantineItem, ...]
    unknown_fields: Mapping[str, Any]

    def __post_init__(self) -> None:
        for name in (
            "records",
            "kernel_record_ids",
            "retrievable_record_ids",
            "transient_records",
            "tensions",
            "review_queue",
            "quarantine",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "unknown_fields", _freeze(self.unknown_fields))
        record_ids = tuple(record.record_id for record in self.records)
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Normalized identity record IDs must be unique")

    @property
    def records_by_id(self) -> Mapping[str, IdentityRecord]:
        return MappingProxyType({record.record_id: record for record in self.records})

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


def normalized_identity_from_dict(payload: Mapping[str, Any]) -> NormalizedIdentityModel:
    envelope_payload = _mapping(payload.get("envelope"))
    envelope = ArtifactEnvelope(
        artifact_hash=str(envelope_payload.get("artifact_hash") or ""),
        format=str(envelope_payload.get("format") or ""),
        format_version=str(envelope_payload.get("format_version") or ""),
        export_kind=str(envelope_payload.get("export_kind") or ""),
        artifact_mode=str(envelope_payload.get("artifact_mode") or ""),
        default_runtime_context=str(envelope_payload.get("default_runtime_context") or ""),
        subject_class=SubjectClass(str(envelope_payload.get("subject_class") or SubjectClass.UNKNOWN.value)),
        artifact_contract=_mapping(envelope_payload.get("artifact_contract")),
        source_scope=_mapping(envelope_payload.get("source_scope")),
        source_registry=_mapping(envelope_payload.get("source_registry")),
        coverage_assessment=_mapping(envelope_payload.get("coverage_assessment")),
        exposure_model=_mapping(envelope_payload.get("exposure_model")),
        import_notes=_mapping(envelope_payload.get("import_notes")),
        artifact_limits=_mapping(envelope_payload.get("artifact_limits")),
        mechanical_audit=tuple(str(item) for item in _tuple(envelope_payload.get("mechanical_audit"))),
        semantic_audit=_mapping(envelope_payload.get("semantic_audit")),
    )
    records = tuple(_identity_record_from_dict(item) for item in _tuple(payload.get("records")))
    transient_records = tuple(_transient_record_from_dict(item) for item in _tuple(payload.get("transient_records")))
    tensions = tuple(_tension_from_dict(item) for item in _tuple(payload.get("tensions")))
    review_queue = tuple(_review_from_dict(item) for item in _tuple(payload.get("review_queue")))
    quarantine = tuple(_quarantine_from_dict(item) for item in _tuple(payload.get("quarantine")))
    return NormalizedIdentityModel(
        schema_version=int(payload.get("schema_version") or NORMALIZED_SCHEMA_VERSION),
        normalizer_revision=str(payload.get("normalizer_revision") or ""),
        envelope=envelope,
        records=records,
        kernel_record_ids=tuple(str(item) for item in _tuple(payload.get("kernel_record_ids"))),
        retrievable_record_ids=tuple(str(item) for item in _tuple(payload.get("retrievable_record_ids"))),
        transient_records=transient_records,
        tensions=tensions,
        review_queue=review_queue,
        quarantine=quarantine,
        unknown_fields=_mapping(payload.get("unknown_fields")),
    )


def _identity_record_from_dict(value: Any) -> IdentityRecord:
    item = _mapping(value)
    confidence = item.get("confidence")
    return IdentityRecord(
        record_id=str(item.get("record_id") or ""),
        source_path=str(item.get("source_path") or ""),
        source_text=str(item.get("source_text") or ""),
        semantic_role=str(item.get("semantic_role") or ""),
        subject_refs=tuple(str(entry) for entry in _tuple(item.get("subject_refs"))),
        stability=str(item.get("stability") or ""),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        epistemic_qualifier=str(item.get("epistemic_qualifier") or ""),
        runtime_layer=RuntimeLayer(str(item.get("runtime_layer") or RuntimeLayer.UNCLASSIFIED.value)),
        durability=str(item.get("durability") or ""),
        stale_after=str(item["stale_after"]) if item.get("stale_after") is not None else None,
        tags=tuple(str(entry) for entry in _tuple(item.get("tags"))),
        retrieval_hints=tuple(str(entry) for entry in _tuple(item.get("retrieval_hints"))),
        declared_policy=_mapping(item.get("declared_policy")),
        exposure_policy=_mapping(item.get("exposure_policy")),
        privacy_class=str(item.get("privacy_class") or ""),
        runtime_suitability=tuple(str(entry) for entry in _tuple(item.get("runtime_suitability"))),
        review_state=str(item.get("review_state") or ""),
        wording_provenance=_mapping(item.get("wording_provenance")),
        provenance=_mapping(item.get("provenance")),
    )


def _transient_record_from_dict(value: Any) -> TransientRecord:
    item = _mapping(value)
    confidence = item.get("confidence")
    risk = item.get("staleness_risk")
    ttl = item.get("ttl_seconds")
    return TransientRecord(
        record_id=str(item.get("record_id") or ""),
        source_path=str(item.get("source_path") or ""),
        source_text=str(item.get("source_text") or ""),
        subject_refs=tuple(str(entry) for entry in _tuple(item.get("subject_refs"))),
        included_item_ids=tuple(str(entry) for entry in _tuple(item.get("included_item_ids"))),
        ttl_hint=str(item.get("ttl_hint") or ""),
        ttl_seconds=int(ttl) if isinstance(ttl, (int, float)) else None,
        origin_timestamp=str(item["origin_timestamp"]) if item.get("origin_timestamp") is not None else None,
        expiration_notes=tuple(str(entry) for entry in _tuple(item.get("expiration_notes"))),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        staleness_risk=float(risk) if isinstance(risk, (int, float)) else None,
        provenance=_mapping(item.get("provenance")),
        active_by_default=bool(item.get("active_by_default", False)),
        semantic_role=str(item.get("semantic_role") or "transient_continuity"),
        runtime_layer=RuntimeLayer(
            str(item.get("runtime_layer") or RuntimeLayer.RETRIEVABLE.value)
        ),
        epistemic_qualifier=str(item.get("epistemic_qualifier") or "unspecified"),
        declared_policy=_mapping(item.get("declared_policy")),
        exposure_policy=_mapping(item.get("exposure_policy")),
        privacy_class=str(item.get("privacy_class") or "unspecified"),
        runtime_suitability=tuple(
            str(entry) for entry in _tuple(item.get("runtime_suitability"))
        ),
        review_state=str(item.get("review_state") or "not_required"),
        activation_metadata=_mapping(item.get("activation_metadata")),
    )


def _tension_from_dict(value: Any) -> LinkedTension:
    item = _mapping(value)
    return LinkedTension(
        tension_id=str(item.get("tension_id") or ""),
        record_ids=tuple(str(entry) for entry in _tuple(item.get("record_ids"))),
        subject_refs=tuple(str(entry) for entry in _tuple(item.get("subject_refs"))),
        scope=str(item.get("scope") or "identity"),
        state=str(item.get("state") or "unresolved"),
        epistemic_states=tuple(str(entry) for entry in _tuple(item.get("epistemic_states"))),
        review_history=tuple(_mapping(entry) for entry in _tuple(item.get("review_history"))),
    )


def _review_from_dict(value: Any) -> ReviewItem:
    item = _mapping(value)
    return ReviewItem(
        review_id=str(item.get("review_id") or ""),
        kind=ReviewKind(str(item.get("kind") or ReviewKind.RUNTIME_LAYER.value)),
        record_ids=tuple(str(entry) for entry in _tuple(item.get("record_ids"))),
        source_paths=tuple(str(entry) for entry in _tuple(item.get("source_paths"))),
        proposed_value=str(item.get("proposed_value") or ""),
        reason=str(item.get("reason") or ""),
        state=str(item.get("state") or "pending"),
        details=_mapping(item.get("details")),
    )


def _quarantine_from_dict(value: Any) -> QuarantineItem:
    item = _mapping(value)
    return QuarantineItem(
        quarantine_id=str(item.get("quarantine_id") or ""),
        reason=QuarantineReason(str(item.get("reason") or QuarantineReason.INTEGRITY.value)),
        record_ids=tuple(str(entry) for entry in _tuple(item.get("record_ids"))),
        source_path=str(item.get("source_path") or ""),
        source_text=str(item.get("source_text") or ""),
        details=_mapping(item.get("details")),
    )
