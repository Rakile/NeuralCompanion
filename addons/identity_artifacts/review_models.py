"""Typed, presentation-neutral Identity Relay connection-review contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from addons.identity_artifacts.attestations import (
    ReviewDecision,
    SubjectClassificationProposal,
)
from addons.identity_artifacts.normalized_model import (
    ReviewItem,
    ReviewKind,
    RuntimeLayer,
    SubjectClass,
    TransientRecord,
)

REVIEW_CONTRACT_VERSION = 1
REVIEW_ACTIONS = ("approve", "reclassify", "narrow_use", "quarantine")
PROPOSAL_STATUSES = ("not_needed", "pending", "ready", "unavailable")

_SELECTABLE_SUBJECTS = (
    SubjectClass.ASSISTANT_SELF,
    SubjectClass.OTHER_ENTITY,
    SubjectClass.RELATIONSHIP,
    SubjectClass.MIXED,
)
_ACTION_LABELS = {
    "approve": "Approve",
    "reclassify": "Reclassify",
    "narrow_use": "Narrow Use",
    "quarantine": "Quarantine",
}


@dataclass(frozen=True, slots=True)
class ReviewItemDecision:
    review_id: str
    action: str
    proposed_value: str = ""
    replacement_value: str = ""
    allowed_scope: str = ""
    source_reason: str = ""
    prior_state: str = "pending"


@dataclass(frozen=True, slots=True)
class ConnectionReviewResult:
    artifact_ref: str
    artifact_hash: str
    subject_class: SubjectClass
    approved: bool
    item_decisions: tuple[ReviewItemDecision, ...] = ()
    transient_active: bool | None = None


@dataclass(frozen=True, slots=True)
class ConnectionReviewModel:
    artifact_ref: str
    artifact_hash: str
    identity_label: str
    normalizer_revision: str
    schema_version: int
    subject_class: SubjectClass = SubjectClass.UNKNOWN
    proposal: SubjectClassificationProposal | None = None
    proposal_status: str = "not_needed"
    proposal_message: str = ""
    review_items: tuple[ReviewItem, ...] = ()
    transient_records: tuple[TransientRecord, ...] = ()
    migration_messages: tuple[str, ...] = ()
    policy_narrowing: tuple[str, ...] = ()
    index_status: str = ""
    trace_ids: tuple[str, ...] = ()
    source_text_by_record: Mapping[str, str] = field(default_factory=dict)
    attestation_normalizer_revision: str = ""
    attestation_approved: bool = False
    attestation_status: str = "not reviewed"
    prior_review_decisions: tuple[ReviewDecision, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_class", SubjectClass(self.subject_class))
        status = str(self.proposal_status)
        if status not in PROPOSAL_STATUSES:
            raise ValueError(f"Unsupported proposal status: {status!r}")
        object.__setattr__(self, "proposal_status", status)
        object.__setattr__(self, "proposal_message", str(self.proposal_message))
        for name in (
            "review_items",
            "transient_records",
            "migration_messages",
            "policy_narrowing",
            "trace_ids",
            "prior_review_decisions",
        ):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        source_text = {
            str(record_id): str(text)
            for record_id, text in dict(self.source_text_by_record).items()
        }
        object.__setattr__(self, "source_text_by_record", MappingProxyType(source_text))


def _plain_value(value: Any) -> object:
    if isinstance(value, Enum):
        return _plain_value(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Identity Relay review mapping keys must be strings.")
            result[key] = _plain_value(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_plain_value(item) for item in value]
    raise TypeError(
        f"Identity Relay review value is not QML-safe: {type(value).__name__}."
    )


def _choice(value: str) -> dict[str, str]:
    return {
        "label": value.replace("_", " ").title(),
        "value": value,
    }


def _string_choices(value: object, *, field_name: str) -> list[dict[str, str]]:
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{field_name} must be a sequence of strings.")
    choices: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise TypeError(f"{field_name} must contain only non-empty strings.")
        choices.append(_choice(item))
    return choices


def _review_reclassification_values(item: ReviewItem) -> tuple[str, ...]:
    if item.kind == ReviewKind.SUBJECT_CLASS:
        return tuple(subject.value for subject in _SELECTABLE_SUBJECTS)
    if item.kind == ReviewKind.RUNTIME_LAYER:
        return (RuntimeLayer.KERNEL.value, RuntimeLayer.RETRIEVABLE.value)
    values = item.details.get("supported_reclassifications", ())
    if not isinstance(values, (tuple, list)):
        raise TypeError("supported_reclassifications must be a sequence.")
    return tuple(values)


def _serialize_review_item(item: ReviewItem) -> dict[str, object]:
    narrow_values = item.details.get("supported_runtime_use_scopes", ())
    reason = item.details.get("narrow_use_unavailable_reason", "")
    if not isinstance(reason, str):
        raise TypeError("narrow_use_unavailable_reason must be a string.")
    return {
        "reviewId": str(item.review_id),
        "kind": item.kind.value,
        "recordIds": list(item.record_ids),
        "sourcePaths": list(item.source_paths),
        "proposedValue": str(item.proposed_value),
        "reason": str(item.reason),
        "state": str(item.state),
        "supportedReclassifications": _string_choices(
            _review_reclassification_values(item),
            field_name="supported_reclassifications",
        ),
        "supportedRuntimeUseScopes": _string_choices(
            narrow_values,
            field_name="supported_runtime_use_scopes",
        ),
        "narrowUseUnavailableReason": reason,
    }


def _serialize_transient(record: TransientRecord) -> dict[str, object]:
    return {
        "recordId": str(record.record_id),
        "sourcePath": str(record.source_path),
        "sourceText": str(record.source_text),
        "subjectRefs": list(record.subject_refs),
        "includedItemIds": list(record.included_item_ids),
        "ttlHint": str(record.ttl_hint),
        "ttlSeconds": record.ttl_seconds,
        "originTimestamp": record.origin_timestamp,
        "expirationNotes": list(record.expiration_notes),
        "confidence": record.confidence,
        "stalenessRisk": record.staleness_risk,
        "provenance": _plain_value(record.provenance),
        "activeByDefault": bool(record.active_by_default),
        "semanticRole": str(record.semantic_role),
        "runtimeLayer": record.runtime_layer.value,
        "epistemicQualifier": str(record.epistemic_qualifier),
        "declaredPolicy": _plain_value(record.declared_policy),
        "exposurePolicy": _plain_value(record.exposure_policy),
        "privacyClass": str(record.privacy_class),
        "runtimeSuitability": list(record.runtime_suitability),
        "reviewState": str(record.review_state),
        "activationMetadata": _plain_value(record.activation_metadata),
    }


def _serialize_proposal(
    proposal: SubjectClassificationProposal | None,
) -> dict[str, object] | None:
    if proposal is None:
        return None
    return {
        "proposedClass": proposal.proposed_class.value,
        "reason": str(proposal.reason),
        "evidencePaths": list(proposal.evidence_paths),
        "provider": str(proposal.provider),
        "model": str(proposal.model),
    }


def _serialize_prior_decision(decision: ReviewDecision) -> dict[str, object]:
    return {
        "reviewId": str(decision.review_id),
        "choice": str(decision.choice),
        "reason": str(decision.reason),
        "approved": bool(decision.approved),
        "revision": int(decision.revision),
        "reviewedAt": str(decision.reviewed_at),
    }


def serialize_connection_review(model: ConnectionReviewModel) -> dict[str, object]:
    """Return a versioned QML-safe mapping for a prepared review."""

    ref_empty = not bool(model.artifact_ref)
    hash_empty = not bool(model.artifact_hash)
    if ref_empty != hash_empty:
        raise ValueError(
            "Identity Relay review requires artifact ref and hash together."
        )
    disconnect = ref_empty
    if disconnect and (
        model.proposal_status != "not_needed" or model.proposal_message
    ):
        raise ValueError("Disconnect review cannot carry proposal state.")
    if disconnect and (
        model.proposal is not None
        or model.review_items
        or model.transient_records
        or model.prior_review_decisions
    ):
        raise ValueError("Disconnect review cannot contain identity decisions.")

    return {
        "reviewContractVersion": REVIEW_CONTRACT_VERSION,
        "artifactRef": str(model.artifact_ref),
        "artifactHash": str(model.artifact_hash),
        "identityLabel": str(model.identity_label),
        "normalizerRevision": str(model.normalizer_revision),
        "schemaVersion": int(model.schema_version),
        "subjectClass": model.subject_class.value,
        "isDisconnect": disconnect,
        "requiresSubjectChoice": bool(
            not disconnect and model.subject_class == SubjectClass.UNKNOWN
        ),
        "subjectChoices": (
            [] if disconnect else [_choice(subject.value) for subject in _SELECTABLE_SUBJECTS]
        ),
        "reviewActions": (
            []
            if disconnect
            else [
                {"label": _ACTION_LABELS[action], "value": action}
                for action in REVIEW_ACTIONS
            ]
        ),
        "proposal": None if disconnect else _serialize_proposal(model.proposal),
        "proposalStatus": str(model.proposal_status),
        "proposalMessage": str(model.proposal_message),
        "reviewItems": (
            []
            if disconnect
            else [_serialize_review_item(item) for item in model.review_items]
        ),
        "transientRecords": (
            []
            if disconnect
            else [_serialize_transient(item) for item in model.transient_records]
        ),
        "migrationMessages": _plain_value(model.migration_messages),
        "policyNarrowing": _plain_value(model.policy_narrowing),
        "indexStatus": str(model.index_status),
        "traceIds": _plain_value(model.trace_ids),
        "sourceTextByRecord": _plain_value(model.source_text_by_record),
        "attestationNormalizerRevision": str(model.attestation_normalizer_revision),
        "attestationApproved": bool(model.attestation_approved),
        "attestationStatus": str(model.attestation_status),
        "priorReviewDecisions": (
            []
            if disconnect
            else [
                _serialize_prior_decision(item)
                for item in model.prior_review_decisions
            ]
        ),
    }


def _required_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid_review_value(f"{name} must be a mapping.")
    return value


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise _invalid_review_value(f"{name} must be a string.")
    return value


def _required_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a boolean.")
    return value


def _invalid_review_value(message: str) -> ValueError:
    return ValueError(message)


def _parse_review_decision(value: object) -> ReviewItemDecision:
    payload = _required_mapping(value, "item decision")
    review_id = _required_string(payload.get("reviewId"), "reviewId")
    if not review_id:
        raise ValueError("reviewId must not be empty.")
    action = _required_string(payload.get("action"), "action")
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"Unsupported review action: {action!r}")
    values = {
        key: _required_string(payload.get(key, default), key)
        for key, default in (
            ("proposedValue", ""),
            ("replacementValue", ""),
            ("allowedScope", ""),
            ("sourceReason", ""),
            ("priorState", "pending"),
        )
    }
    return ReviewItemDecision(
        review_id=review_id,
        action=action,
        proposed_value=values["proposedValue"],
        replacement_value=values["replacementValue"],
        allowed_scope=values["allowedScope"],
        source_reason=values["sourceReason"],
        prior_state=values["priorState"],
    )


def parse_connection_review_result(payload: object) -> ConnectionReviewResult:
    """Parse a structurally valid QML review result into typed data."""

    values = _required_mapping(payload, "review result")
    version = values.get("reviewContractVersion")
    # QML Number values can arrive through QVariantMap as 1.0. Accept the
    # exact numeric version while rejecting booleans, strings and fractions.
    if type(version) not in (int, float) or version != REVIEW_CONTRACT_VERSION:
        raise ValueError(f"Unsupported review contract version: {version!r}")
    disconnect = _required_bool(values.get("isDisconnect"), "isDisconnect")
    artifact_ref = _required_string(values.get("artifactRef"), "artifactRef")
    artifact_hash = _required_string(values.get("artifactHash"), "artifactHash")
    approved = _required_bool(values.get("approved"), "approved")
    raw_decisions = values.get("itemDecisions")
    if not isinstance(raw_decisions, list):
        raise _invalid_review_value("itemDecisions must be a list.")
    decisions = tuple(_parse_review_decision(item) for item in raw_decisions)
    review_ids = tuple(item.review_id for item in decisions)
    if len(set(review_ids)) != len(review_ids):
        raise ValueError("Review decision IDs must be unique.")
    transient_active = values.get("transientActive")
    if transient_active is not None and type(transient_active) is not bool:
        raise ValueError("transientActive must be a boolean or null.")

    ref_empty = not artifact_ref
    hash_empty = not artifact_hash
    if disconnect:
        if not ref_empty or not hash_empty:
            raise ValueError("Disconnect review must have an empty ref and hash.")
        if decisions or transient_active is not None:
            raise ValueError("Disconnect review cannot contain identity decisions.")
        subject_value = values.get("subjectClass")
        if subject_value not in (None, "", SubjectClass.ASSISTANT_SELF.value):
            raise ValueError("Disconnect review cannot select an identity subject.")
        subject_class = SubjectClass.ASSISTANT_SELF
    else:
        if ref_empty or hash_empty:
            raise ValueError("Identity review requires a non-empty ref and hash.")
        subject_value = _required_string(values.get("subjectClass"), "subjectClass")
        if subject_value not in {
            subject.value for subject in _SELECTABLE_SUBJECTS
        }:
            raise ValueError(f"Unsupported subject class: {subject_value!r}")
        subject_class = SubjectClass(subject_value)

    return ConnectionReviewResult(
        artifact_ref=artifact_ref,
        artifact_hash=artifact_hash,
        subject_class=subject_class,
        approved=approved,
        item_decisions=decisions,
        transient_active=transient_active,
    )


__all__ = [
    "PROPOSAL_STATUSES",
    "REVIEW_ACTIONS",
    "REVIEW_CONTRACT_VERSION",
    "ConnectionReviewModel",
    "ConnectionReviewResult",
    "ReviewItemDecision",
    "parse_connection_review_result",
    "serialize_connection_review",
]
