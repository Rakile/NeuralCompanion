from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from addons.identity_artifacts.normalized_model import (
    NORMALIZER_REVISION,
    SubjectClass,
    TransientRecord,
    normalized_identity_digest,
)


_ARTIFACT_HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
ATTESTATION_SCHEMA_VERSION = 1
SNAPSHOT_AUTHORIZATION_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class SubjectAttestation:
    artifact_hash: str
    normalizer_revision: str
    subject_class: SubjectClass
    approved: bool
    revision: int
    reviewed_at: str
    normalized_digest: str = ""


@dataclass(frozen=True)
class ReviewDecision:
    review_id: str
    choice: str
    reason: str
    approved: bool = True
    revision: int = 1
    reviewed_at: str = ""


@dataclass(frozen=True)
class TransientActivation:
    record_id: str = ""
    active: bool = False
    activated_at: str | float | int | None = None
    session_token: str = ""
    revision: int = 1
    reviewed_at: str = ""


@dataclass(frozen=True)
class SubjectClassificationProposal:
    proposed_class: SubjectClass
    reason: str
    evidence_paths: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_paths", tuple(self.evidence_paths))


@dataclass(frozen=True)
class AttestationState:
    artifact_hash: str = ""
    normalizer_revision: str = ""
    subject_attestation: SubjectAttestation | None = None
    review_decisions: tuple[ReviewDecision, ...] = ()
    transient_activations: tuple[TransientActivation, ...] = ()
    pending_proposal: SubjectClassificationProposal | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "review_decisions", tuple(self.review_decisions))
        object.__setattr__(self, "transient_activations", tuple(self.transient_activations))


@dataclass(frozen=True)
class PersistentSnapshotAuthorization:
    snapshot_hash: str
    artifact_ref: str
    artifact_hash: str
    normalizer_revision: str
    attestation_revision: int
    subject_class: str
    subject_approved: bool
    persistence_allowed: bool
    provider_is_remote: bool
    authorization_record_id: str = ""
    provider_name: str = ""
    provider_endpoint: str = ""
    record_ids: tuple[str, ...] = ()
    authorized_operations: tuple[str, ...] = ()
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_ids", tuple(self.record_ids))
        object.__setattr__(
            self,
            "authorized_operations",
            tuple(self.authorized_operations),
        )


@dataclass(frozen=True)
class SnapshotAuthorizationDeleteResult:
    removed_count: int = 0
    failure_details: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_details", tuple(self.failure_details))


@dataclass(frozen=True)
class TransientActivationState:
    active: bool
    review_required: bool
    reason_code: str
    expires_at: float | None = None


def empty_attestation_state(
    artifact_hash: str = "", normalizer_revision: str = ""
) -> AttestationState:
    return AttestationState(
        artifact_hash=artifact_hash,
        normalizer_revision=normalizer_revision,
    )


def apply_classification_proposal(
    state: AttestationState, proposal: SubjectClassificationProposal
) -> AttestationState:
    return replace(state, pending_proposal=proposal)


def evaluate_transient_activation(
    *,
    transient: TransientRecord,
    saved_activation: TransientActivation,
    now: str | float | int | datetime,
    current_session_token: str = "",
) -> TransientActivationState:
    if not saved_activation.active:
        return TransientActivationState(False, False, "inactive")

    if transient.ttl_hint == "session":
        if not saved_activation.session_token or not current_session_token:
            return TransientActivationState(False, True, "session_scope_required")
        if saved_activation.session_token != current_session_token:
            return TransientActivationState(False, False, "session_mismatch")
        if transient.ttl_seconds is None:
            return TransientActivationState(True, False, "active_for_session")

    if transient.ttl_seconds is None:
        if transient.ttl_hint:
            return TransientActivationState(False, True, "ambiguous_expiration")
        return TransientActivationState(True, False, "active")

    if transient.ttl_seconds <= 0:
        return TransientActivationState(False, True, "invalid_ttl")

    origin_value = (
        saved_activation.activated_at
        if saved_activation.activated_at is not None
        else transient.origin_timestamp
    )
    origin = _timestamp(origin_value)
    if origin is None:
        return TransientActivationState(False, True, "ambiguous_expiration")
    current = _timestamp(now)
    if current is None:
        raise ValueError("now must be a numeric timestamp or an ISO-8601 datetime")
    expires_at = origin + transient.ttl_seconds
    if current >= expires_at:
        return TransientActivationState(False, False, "expired", expires_at)
    return TransientActivationState(True, False, "active", expires_at)


class IdentityRelayDecisionStore:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.attestations_dir = self.root_dir / "attestations"
        self.attestations_dir.mkdir(parents=True, exist_ok=True)

    def load(self, artifact_hash: str) -> AttestationState:
        path = self._path(artifact_hash)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            state = _state_from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return empty_attestation_state(artifact_hash)
        if state.artifact_hash != artifact_hash:
            return empty_attestation_state(artifact_hash)
        return state

    def save(self, state: AttestationState) -> AttestationState:
        path = self._path(state.artifact_hash)
        payload = _state_to_dict(state)
        _atomic_write_json(path, payload)
        return state

    def save_subject_attestation(
        self,
        *,
        artifact_hash: str,
        normalizer_revision: str,
        subject_class: SubjectClass,
        approved: bool,
        reviewed_at: str | None = None,
        normalized_digest: str | None = None,
    ) -> SubjectAttestation:
        state = self.load(artifact_hash)
        if state.normalizer_revision and state.normalizer_revision != normalizer_revision:
            state = empty_attestation_state(artifact_hash, normalizer_revision)
        previous = state.subject_attestation
        revision = previous.revision + 1 if previous is not None else 1
        attestation = SubjectAttestation(
            artifact_hash=artifact_hash,
            normalizer_revision=normalizer_revision,
            subject_class=SubjectClass(subject_class),
            approved=bool(approved),
            revision=revision,
            reviewed_at=reviewed_at or _utc_now(),
            normalized_digest=(
                str(normalized_digest or "")
                or self._canonical_normalized_digest(
                    artifact_hash,
                    normalizer_revision,
                )
            ),
        )
        self.save(
            replace(
                state,
                artifact_hash=artifact_hash,
                normalizer_revision=normalizer_revision,
                subject_attestation=attestation,
                pending_proposal=None,
            )
        )
        return attestation

    def _canonical_normalized_digest(
        self,
        artifact_hash: str,
        normalizer_revision: str,
    ) -> str:
        if normalizer_revision != NORMALIZER_REVISION:
            return ""
        try:
            from addons.identity_artifacts.importer import import_identity_artifact
            from addons.identity_artifacts.normalizer import normalize_identity_artifact

            raw_bytes = (self.root_dir / "library" / f"{artifact_hash}.json").read_bytes()
            result = import_identity_artifact(
                raw_bytes,
                source_type="file",
                source_path=f"library/{artifact_hash}.json",
            )
            return normalized_identity_digest(normalize_identity_artifact(result))
        except (OSError, TypeError, ValueError, UnicodeDecodeError):
            return ""

    def invalidate_for_revision(
        self, artifact_hash: str, normalizer_revision: str
    ) -> AttestationState:
        state = self.load(artifact_hash)
        if state.normalizer_revision == normalizer_revision:
            return state
        invalidated = empty_attestation_state(artifact_hash, normalizer_revision)
        self.save(invalidated)
        return invalidated

    def delete(self, artifact_hash: str) -> bool:
        path = self._path(artifact_hash)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def _path(self, artifact_hash: str) -> Path:
        if _ARTIFACT_HASH_RE.fullmatch(str(artifact_hash or "")) is None:
            raise ValueError("artifact_hash must be a full lowercase SHA-256 hash")
        return self.attestations_dir / f"{artifact_hash}.json"


class IdentityRelaySnapshotAuthorizationStore:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.authorizations_dir = self.root_dir / "snapshot_authorizations"
        self.authorizations_dir.mkdir(parents=True, exist_ok=True)

    def load(
        self,
        authorization_record_id: str,
    ) -> PersistentSnapshotAuthorization | None:
        try:
            path = self._path(authorization_record_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            authorization = _snapshot_authorization_from_dict(payload)
        except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if (
            authorization.authorization_record_id != authorization_record_id
            or persistent_snapshot_authorization_record_id(authorization)
            != authorization_record_id
        ):
            return None
        return authorization

    def save(
        self,
        authorization: PersistentSnapshotAuthorization,
    ) -> PersistentSnapshotAuthorization:
        if not isinstance(authorization, PersistentSnapshotAuthorization):
            raise TypeError("authorization must be a PersistentSnapshotAuthorization")
        expected_id = persistent_snapshot_authorization_record_id(authorization)
        if authorization.authorization_record_id != expected_id:
            raise ValueError("authorization record identity does not match its envelope")
        path = self._path(authorization.authorization_record_id)
        _atomic_write_json(path, _snapshot_authorization_to_dict(authorization))
        return authorization

    def delete(self, authorization_record_id: str) -> bool:
        path = self._path(authorization_record_id)
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed

    def delete_for_artifact(self, artifact_hash: str) -> int:
        return self.delete_for_artifact_with_report(artifact_hash).removed_count

    def delete_for_artifact_with_report(
        self,
        artifact_hash: str,
    ) -> SnapshotAuthorizationDeleteResult:
        if _ARTIFACT_HASH_RE.fullmatch(str(artifact_hash or "")) is None:
            raise ValueError("artifact_hash must be a full lowercase SHA-256 hash")
        removed = 0
        failure_details: list[str] = []
        for path in self.authorizations_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            try:
                authorization = _snapshot_authorization_from_dict(payload)
            except (ValueError, TypeError):
                authorization = None
            if authorization is not None:
                valid_identity = (
                    authorization.authorization_record_id == path.stem
                    and persistent_snapshot_authorization_record_id(authorization)
                    == path.stem
                )
                if valid_identity:
                    if authorization.artifact_hash == artifact_hash:
                        path.unlink(missing_ok=True)
                        removed += 1
                    continue

            if not _snapshot_authorization_declares_artifact(payload, artifact_hash):
                continue
            try:
                legacy_artifact_hash = (
                    _legacy_snapshot_authorization_artifact_hash_for_delete(
                        payload,
                        path.stem,
                    )
                )
            except (ValueError, TypeError):
                failure_details.append(f"{path.name}:unsafe_owned_record")
                continue
            if legacy_artifact_hash == artifact_hash:
                path.unlink(missing_ok=True)
                removed += 1
        return SnapshotAuthorizationDeleteResult(
            removed_count=removed,
            failure_details=tuple(failure_details),
        )

    def _path(self, authorization_record_id: str) -> Path:
        if _ARTIFACT_HASH_RE.fullmatch(str(authorization_record_id or "")) is None:
            raise ValueError(
                "authorization_record_id must be a full lowercase SHA-256 hash"
            )
        return self.authorizations_dir / f"{authorization_record_id}.json"


def persistent_snapshot_authorization_record_id(
    authorization: PersistentSnapshotAuthorization,
) -> str:
    payload = {
        "snapshot_hash": authorization.snapshot_hash,
        "artifact_ref": authorization.artifact_ref,
        "artifact_hash": authorization.artifact_hash,
        "normalizer_revision": authorization.normalizer_revision,
        "attestation_revision": authorization.attestation_revision,
        "subject_class": authorization.subject_class,
        "subject_approved": authorization.subject_approved,
        "persistence_allowed": authorization.persistence_allowed,
        "provider_is_remote": authorization.provider_is_remote,
        "provider_name": authorization.provider_name,
        "provider_endpoint": authorization.provider_endpoint,
        "record_ids": list(authorization.record_ids),
        "authorized_operations": list(authorization.authorized_operations),
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp(value: str | float | int | datetime | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


def _state_to_dict(state: AttestationState) -> dict[str, Any]:
    return {
        "schema_version": ATTESTATION_SCHEMA_VERSION,
        "artifact_hash": state.artifact_hash,
        "normalizer_revision": state.normalizer_revision,
        "subject_attestation": _subject_to_dict(state.subject_attestation),
        "review_decisions": [
            {
                "review_id": item.review_id,
                "choice": item.choice,
                "reason": item.reason,
                "approved": item.approved,
                "revision": item.revision,
                "reviewed_at": item.reviewed_at,
            }
            for item in state.review_decisions
        ],
        "transient_activations": [
            {
                "record_id": item.record_id,
                "active": item.active,
                "activated_at": item.activated_at,
                "session_token": item.session_token,
                "revision": item.revision,
                "reviewed_at": item.reviewed_at,
            }
            for item in state.transient_activations
        ],
        "pending_proposal": _proposal_to_dict(state.pending_proposal),
    }


def _state_from_dict(value: Any) -> AttestationState:
    if not isinstance(value, Mapping):
        raise ValueError("attestation state must be an object")
    if value.get("schema_version") != ATTESTATION_SCHEMA_VERSION:
        raise ValueError("unsupported attestation schema")
    artifact_hash = str(value.get("artifact_hash") or "")
    if _ARTIFACT_HASH_RE.fullmatch(artifact_hash) is None:
        raise ValueError("invalid attestation artifact hash")
    return AttestationState(
        artifact_hash=artifact_hash,
        normalizer_revision=str(value.get("normalizer_revision") or ""),
        subject_attestation=_subject_from_dict(value.get("subject_attestation")),
        review_decisions=tuple(
            _review_from_dict(item) for item in _sequence(value.get("review_decisions"))
        ),
        transient_activations=tuple(
            _transient_from_dict(item)
            for item in _sequence(value.get("transient_activations"))
        ),
        pending_proposal=_proposal_from_dict(value.get("pending_proposal")),
    )


def _snapshot_authorization_to_dict(
    value: PersistentSnapshotAuthorization,
) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_AUTHORIZATION_SCHEMA_VERSION,
        "authorization_record_id": value.authorization_record_id,
        "snapshot_hash": value.snapshot_hash,
        "artifact_ref": value.artifact_ref,
        "artifact_hash": value.artifact_hash,
        "normalizer_revision": value.normalizer_revision,
        "attestation_revision": value.attestation_revision,
        "subject_class": value.subject_class,
        "subject_approved": value.subject_approved,
        "persistence_allowed": value.persistence_allowed,
        "provider_is_remote": value.provider_is_remote,
        "provider_name": value.provider_name,
        "provider_endpoint": value.provider_endpoint,
        "record_ids": list(value.record_ids),
        "authorized_operations": list(value.authorized_operations),
        "created_at": value.created_at,
    }


def _snapshot_authorization_from_dict(
    value: Any,
) -> PersistentSnapshotAuthorization:
    item = _mapping(value)
    if item.get("schema_version") != SNAPSHOT_AUTHORIZATION_SCHEMA_VERSION:
        raise ValueError("unsupported snapshot authorization schema")
    snapshot_hash = str(item.get("snapshot_hash") or "")
    authorization_record_id = str(item.get("authorization_record_id") or "")
    artifact_hash = str(item.get("artifact_hash") or "")
    artifact_ref = str(item.get("artifact_ref") or "")
    if _ARTIFACT_HASH_RE.fullmatch(snapshot_hash) is None:
        raise ValueError("invalid authorized snapshot hash")
    if _ARTIFACT_HASH_RE.fullmatch(authorization_record_id) is None:
        raise ValueError("invalid snapshot authorization record identity")
    if _ARTIFACT_HASH_RE.fullmatch(artifact_hash) is None:
        raise ValueError("invalid authorized artifact hash")
    if artifact_ref != f"library/{artifact_hash}.json":
        raise ValueError("authorized artifact reference does not match its hash")
    provider_is_remote = item.get("provider_is_remote")
    if type(provider_is_remote) is not bool:
        raise ValueError("authorized provider locality must be explicit")
    return PersistentSnapshotAuthorization(
        authorization_record_id=authorization_record_id,
        snapshot_hash=snapshot_hash,
        artifact_ref=artifact_ref,
        artifact_hash=artifact_hash,
        normalizer_revision=str(item.get("normalizer_revision") or ""),
        attestation_revision=int(item.get("attestation_revision") or 0),
        subject_class=str(item.get("subject_class") or ""),
        subject_approved=bool(item.get("subject_approved", False)),
        persistence_allowed=bool(item.get("persistence_allowed", False)),
        provider_is_remote=provider_is_remote,
        provider_name=str(item.get("provider_name") or ""),
        provider_endpoint=str(item.get("provider_endpoint") or ""),
        record_ids=tuple(str(entry) for entry in _sequence(item.get("record_ids"))),
        authorized_operations=tuple(
            str(entry) for entry in _sequence(item.get("authorized_operations"))
        ),
        created_at=str(item.get("created_at") or ""),
    )


def _snapshot_authorization_declares_artifact(
    value: Any,
    artifact_hash: str,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    return value.get("artifact_hash") == artifact_hash or value.get(
        "artifact_ref"
    ) == f"library/{artifact_hash}.json"


def _legacy_snapshot_authorization_artifact_hash_for_delete(
    value: Any,
    path_stem: str,
) -> str:
    item = _mapping(value)
    if type(item.get("schema_version")) is not int or item["schema_version"] != 1:
        raise ValueError("unsupported legacy snapshot authorization schema")
    snapshot_hash = str(item.get("snapshot_hash") or "")
    artifact_hash = str(item.get("artifact_hash") or "")
    artifact_ref = str(item.get("artifact_ref") or "")
    if (
        _ARTIFACT_HASH_RE.fullmatch(snapshot_hash) is None
        or snapshot_hash != path_stem
    ):
        raise ValueError("legacy snapshot authorization identity mismatch")
    if _ARTIFACT_HASH_RE.fullmatch(artifact_hash) is None:
        raise ValueError("invalid legacy authorized artifact hash")
    if artifact_ref != f"library/{artifact_hash}.json":
        raise ValueError("legacy authorized artifact reference mismatch")
    if type(item.get("provider_is_remote")) is not bool:
        raise ValueError("legacy authorized provider locality must be explicit")
    return artifact_hash


def _subject_to_dict(value: SubjectAttestation | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "artifact_hash": value.artifact_hash,
        "normalizer_revision": value.normalizer_revision,
        "subject_class": value.subject_class.value,
        "approved": value.approved,
        "revision": value.revision,
        "reviewed_at": value.reviewed_at,
        "normalized_digest": value.normalized_digest,
    }


def _subject_from_dict(value: Any) -> SubjectAttestation | None:
    if value is None:
        return None
    item = _mapping(value)
    return SubjectAttestation(
        artifact_hash=str(item.get("artifact_hash") or ""),
        normalizer_revision=str(item.get("normalizer_revision") or ""),
        subject_class=SubjectClass(str(item.get("subject_class") or SubjectClass.UNKNOWN.value)),
        approved=bool(item.get("approved", False)),
        revision=int(item.get("revision") or 1),
        reviewed_at=str(item.get("reviewed_at") or ""),
        normalized_digest=str(item.get("normalized_digest") or ""),
    )


def _review_from_dict(value: Any) -> ReviewDecision:
    item = _mapping(value)
    return ReviewDecision(
        review_id=str(item.get("review_id") or ""),
        choice=str(item.get("choice") or ""),
        reason=str(item.get("reason") or ""),
        approved=bool(item.get("approved", False)),
        revision=int(item.get("revision") or 1),
        reviewed_at=str(item.get("reviewed_at") or ""),
    )


def _transient_from_dict(value: Any) -> TransientActivation:
    item = _mapping(value)
    activated_at = item.get("activated_at")
    if not isinstance(activated_at, (str, int, float)) or isinstance(activated_at, bool):
        activated_at = None
    return TransientActivation(
        record_id=str(item.get("record_id") or ""),
        active=bool(item.get("active", False)),
        activated_at=activated_at,
        session_token=str(item.get("session_token") or ""),
        revision=int(item.get("revision") or 1),
        reviewed_at=str(item.get("reviewed_at") or ""),
    )


def _proposal_to_dict(value: SubjectClassificationProposal | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "proposed_class": value.proposed_class.value,
        "reason": value.reason,
        "evidence_paths": list(value.evidence_paths),
        "provider": value.provider,
        "model": value.model,
    }


def _proposal_from_dict(value: Any) -> SubjectClassificationProposal | None:
    if value is None:
        return None
    item = _mapping(value)
    return SubjectClassificationProposal(
        proposed_class=SubjectClass(str(item.get("proposed_class") or SubjectClass.UNKNOWN.value)),
        reason=str(item.get("reason") or ""),
        evidence_paths=tuple(str(entry) for entry in _sequence(item.get("evidence_paths"))),
        provider=str(item.get("provider") or ""),
        model=str(item.get("model") or ""),
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("attestation entry must be an object")
    return value


def _sequence(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("attestation collection must be an array")
    return tuple(value)


def _atomic_write_json(path: Path, value: Any) -> None:
    serialized = json.dumps(value, indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f"{path.name}.tmp")
    temporary_path.write_text(serialized, encoding="utf-8", newline="\n")
    os.replace(temporary_path, path)
