"""Turn-scoped Identity Relay coordination around addon-owned artifact policy."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
import hashlib
import json
import threading
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from core import chat_providers
from core.runtime.contracts import (
    CancellationToken,
    CommandResult,
    IdentityRelayTurnState,
    RuntimeFailure,
)
from core.runtime.identifiers import (
    RouteGeneration,
    RunId,
    SessionGeneration,
    TurnId,
    WorkLease,
)
from core.runtime.lifecycle import WorkerHandle, WorkerSupervisor
from core.runtime.prompt_assembly import PromptRequest
from core.runtime.providers import ProviderSelection


ArtifactCall = Callable[[Mapping[str, object]], object]
TokenCounter = Callable[[object, Sequence[Mapping[str, object]]], int]
Logger = Callable[[str], None]
PrepareCompletion = Callable[
    [WorkLease, IdentityRelayTurnState, CommandResult["IdentityRelayProjection"]],
    None,
]
ProviderDispatch = Callable[[IdentityRelayTurnState, object, str], None]


class IdentityRelayProviderPort(Protocol):
    def upgrade_selection_for_relay(
        self,
        selection: ProviderSelection,
    ) -> ProviderSelection: ...

    def strict_relay_capability_available(
        self,
        selection: ProviderSelection,
    ) -> bool: ...

    def prepare(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
    ) -> object: ...

    def complete(
        self,
        request: object,
        token: object,
    ) -> CommandResult[str]: ...


@runtime_checkable
class IdentityRelayAddonRuntimeHost(Protocol):
    def set_identity_relay_runtime_service(self, service: object | None) -> None: ...


@dataclass(frozen=True, slots=True)
class IdentityRelayArtifactCapabilities:
    """Narrow addon operations consumed by the host turn coordinator."""

    capture_mode: Callable[[], object] | None = None
    capture_turn: ArtifactCall | None = None
    prepare_turn: ArtifactCall | None = None
    render_judge_request: ArtifactCall | None = None
    finalize_turn: ArtifactCall | None = None
    restore_persisted_snapshot: ArtifactCall | None = None


@dataclass(frozen=True, slots=True)
class IdentityRelayRuntimeCapabilities:
    """Explicit engine operations made available to the Relay addon."""

    _embedding: Callable[..., object]
    _delete_transaction: Callable[[object, object], object]
    _purge_derivatives: Callable[[object], object]
    _artifact_controller: object | None = None

    @property
    def artifact_controller(self) -> object | None:
        return self._artifact_controller

    def embedding(self, *args, **kwargs):
        return self._embedding(*args, **kwargs)

    def delete_transaction(self, artifact_ref, commit):
        return self._delete_transaction(artifact_ref, commit)

    def purge_derivatives(self, artifact_ref):
        return self._purge_derivatives(artifact_ref)


@dataclass(frozen=True, slots=True)
class IdentityRelayNotice:
    failure_category: str
    reason: str
    prominent: bool = True
    provider: str = ""
    model: str = ""
    affected_record_ids: tuple[str, ...] = ()
    redaction_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "affected_record_ids",
            tuple(str(item) for item in self.affected_record_ids if str(item)),
        )


@dataclass(frozen=True, slots=True)
class IdentityRelayProjection:
    status: str
    provider: ProviderSelection
    snapshot: Mapping[str, object] | None = None
    metadata: Mapping[str, object] | None = None
    prompt_text: str = ""
    omitted_record_ids: tuple[str, ...] = ()
    notice: IdentityRelayNotice | None = None
    trace: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", str(self.status or "off"))
        object.__setattr__(self, "snapshot", _freeze_optional_mapping(self.snapshot))
        object.__setattr__(self, "metadata", _freeze_optional_mapping(self.metadata))
        object.__setattr__(self, "prompt_text", str(self.prompt_text or ""))
        object.__setattr__(
            self,
            "omitted_record_ids",
            tuple(str(item) for item in self.omitted_record_ids if str(item)),
        )
        object.__setattr__(self, "trace", _freeze_mapping(self.trace))


@dataclass(frozen=True, slots=True)
class IdentityRelayTurnBinding:
    """Read-only compatibility view of an accepted turn's Relay binding."""

    state: IdentityRelayTurnState
    provider: ProviderSelection
    capture: object = None
    capture_error: str = ""
    restored_snapshot: Mapping[str, object] | None = None
    restored_metadata: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class _AcceptanceOptions:
    restored_snapshot: Mapping[str, object] | None = None
    mode: str = "current"


@dataclass(frozen=True, slots=True)
class _TurnBinding:
    lease: WorkLease
    state: IdentityRelayTurnState
    provider: ProviderSelection
    capture: object = None
    capture_error: str = ""
    restored_snapshot: Mapping[str, object] | None = None
    restored_metadata: Mapping[str, object] | None = None
    query: Mapping[str, object] | None = None
    projection: IdentityRelayProjection | None = None
    token: CancellationToken | None = None
    binding_id: object = field(default_factory=object, compare=False, repr=False)


IDENTITY_RELAY_CAPABILITY_UNAVAILABLE = object()
_MISSING = object()


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return _freeze(dict(value or {}))


def _freeze_optional_mapping(
    value: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    return None if value is None else _freeze_mapping(value)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _field(value: object, name: str, default: object = _MISSING) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _failure(category: str, message: str, cause: BaseException | None = None):
    return CommandResult(
        False,
        failure=RuntimeFailure(str(category), str(message), cause),
    )


_IDENTITY_RELAY_V1_STATES = frozenset({"active", "suspended", "unavailable"})
_IDENTITY_RELAY_V1_FAILURE_CODES = frozenset(
    {"missing", "unreadable", "invalid", "corrupt", "empty_hot_identity"}
)
_IDENTITY_RELAY_V2_SNAPSHOT_FIELDS = (
    "schema_version",
    "projection_kind",
    "status",
    "artifact_ref",
    "artifact_hash",
    "normalizer_revision",
    "attestation_revision",
    "transient_state",
    "effective_use_decisions",
    "kernel_record_ids",
    "prompt_text",
    "selected_record_ids",
    "selection_reasons",
    "signals_considered",
    "unresolved_record_ids",
    "trace",
    "snapshot_hash",
    "authorization_record_id",
    "persistence_mode",
    "failure_code",
)


def _is_sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _strict_artifact_ref(value: object) -> bool:
    text = str(value or "")
    return (
        text.startswith("library/")
        and text.endswith(".json")
        and _is_sha256(text[len("library/") : -len(".json")])
    )


def _legacy_snapshot_hash(
    artifact_ref: object,
    artifact_hash: object,
    hot_identity_text: object,
) -> str:
    serialized = json.dumps(
        {
            "artifact_ref": str(artifact_ref),
            "artifact_hash": str(artifact_hash),
            "hot_identity_text": str(hot_identity_text),
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


@dataclass(frozen=True, slots=True)
class IdentityRelaySnapshotSession:
    """Opaque authority for one registry generation."""

    run_id: RunId
    session_generation: SessionGeneration
    _binding_id: object = field(default_factory=object, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class IdentityRelaySnapshotTurn:
    """Exact turn route authorized to publish a Relay snapshot."""

    session: IdentityRelaySnapshotSession
    turn_id: TurnId
    route_generation: RouteGeneration
    _binding_id: object = field(default_factory=object, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class IdentityRelaySnapshotMetadata:
    """Validated Relay metadata in its durable v1 or v2 shape."""

    schema_version: int
    status: str
    artifact_ref: str
    artifact_hash: str = ""
    snapshot_hash: str = ""
    failure_code: str | None = None

    def as_mapping(self) -> dict[str, object]:
        if self.schema_version == 2:
            value: dict[str, object] = {
                "schema_version": 2,
                "projection_kind": "normalized_projection",
                "status": self.status,
                "artifact_ref": self.artifact_ref,
                "artifact_hash": self.artifact_hash,
            }
            if self.snapshot_hash:
                value["snapshot_hash"] = self.snapshot_hash
            return value
        if self.status == "unavailable":
            return {
                "state": self.status,
                "artifact_ref": self.artifact_ref,
                "failure_code": self.failure_code,
            }
        value = {
            "state": self.status,
            "artifact_ref": self.artifact_ref,
            "artifact_hash": self.artifact_hash,
            "failure_code": self.failure_code,
        }
        if self.snapshot_hash:
            value["snapshot_hash"] = self.snapshot_hash
        return value


@dataclass(frozen=True, slots=True)
class IdentityRelaySnapshotRecord:
    """Deeply immutable validated registry entry."""

    snapshot_hash: str
    artifact_ref: str
    artifact_hash: str
    schema_version: int
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))

    def as_mapping(self) -> dict[str, object]:
        value = _plain(self.payload)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class IdentityRelayCapturedSnapshot:
    """Relay v1 turn metadata and its optional durable registry record."""

    metadata: IdentityRelaySnapshotMetadata | None
    record: IdentityRelaySnapshotRecord | None = None


@dataclass(frozen=True, slots=True)
class IdentityRelayActiveTransactionSource:
    """Only Relay-bearing fields from one active chat transaction."""

    accepted_turn: Mapping[str, object] | None = None
    relay_capture_artifact_ref: str = ""
    relay_snapshot_artifact_ref: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "accepted_turn",
            _freeze_optional_mapping(self.accepted_turn),
        )
        object.__setattr__(
            self,
            "relay_capture_artifact_ref",
            str(self.relay_capture_artifact_ref or ""),
        )
        object.__setattr__(
            self,
            "relay_snapshot_artifact_ref",
            str(self.relay_snapshot_artifact_ref or ""),
        )


@dataclass(frozen=True, slots=True)
class IdentityRelayLoadedSourceRecords:
    """Immutable loaded-chat records used for exact deletion attribution."""

    conversation_history: tuple[Mapping[str, object], ...] = ()
    pending_turn: Mapping[str, object] | None = None
    active_transactions: tuple[IdentityRelayActiveTransactionSource, ...] = ()

    @classmethod
    def capture(
        cls,
        conversation_history: Sequence[Mapping[str, object]],
        pending_turn: Mapping[str, object] | None,
        active_transactions: Sequence[Mapping[str, object]],
    ) -> "IdentityRelayLoadedSourceRecords":
        return cls(
            conversation_history=tuple(
                _freeze_mapping(record) for record in conversation_history
            ),
            pending_turn=_freeze_optional_mapping(pending_turn),
            active_transactions=tuple(
                IdentityRelayActiveTransactionSource(
                    accepted_turn=(
                        transaction.get("accepted_turn")
                        if isinstance(transaction.get("accepted_turn"), Mapping)
                        else None
                    ),
                    relay_capture_artifact_ref=IdentityRelaySnapshotRegistry._artifact_ref(
                        transaction.get("relay_capture")
                    ),
                    relay_snapshot_artifact_ref=IdentityRelaySnapshotRegistry._artifact_ref(
                        transaction.get("relay_snapshot")
                    ),
                )
                for transaction in active_transactions
            ),
        )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "conversation_history",
            tuple(_freeze_mapping(record) for record in self.conversation_history),
        )
        object.__setattr__(
            self,
            "pending_turn",
            _freeze_optional_mapping(self.pending_turn),
        )
        object.__setattr__(
            self,
            "active_transactions",
            tuple(self.active_transactions),
        )


@dataclass(frozen=True, slots=True)
class IdentityRelayPersistenceSnapshot:
    """One atomic, session-bound view of records and referenced snapshots."""

    session: IdentityRelaySnapshotSession
    source_records: tuple[Mapping[str, object], ...]
    snapshots: Mapping[str, Mapping[str, object]]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_records",
            tuple(_freeze_mapping(record) for record in self.source_records),
        )
        object.__setattr__(
            self,
            "snapshots",
            _freeze_mapping(self.snapshots),
        )

    def plain_source_records(self) -> list[dict[str, object]]:
        value = _plain(self.source_records)
        assert isinstance(value, list)
        return value

    def plain_snapshots(self) -> dict[str, object]:
        value = _plain(self.snapshots)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class IdentityRelayDeletionAdmission:
    """Opaque two-phase authorization for one artifact deletion attempt."""

    session: IdentityRelaySnapshotSession
    artifact_ref: str
    blocked_by: tuple[str, ...] = ()
    _binding_id: object = field(default_factory=object, compare=False, repr=False)

    @property
    def admitted(self) -> bool:
        return not self.blocked_by


@dataclass(frozen=True, slots=True)
class IdentityRelayPurgeResult:
    purged: bool
    blocked_by: tuple[str, ...]
    removed_snapshot_count: int

    def as_mapping(self) -> dict[str, object]:
        return {
            "purged": self.purged,
            "blocked_by": self.blocked_by,
            "removed_snapshot_count": self.removed_snapshot_count,
        }


class IdentityRelaySnapshotRegistry:
    """Own Relay compatibility snapshots for exactly one bound chat session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session: IdentityRelaySnapshotSession | None = None
        self._turns: dict[TurnId, IdentityRelaySnapshotTurn] = {}
        self._records: dict[str, IdentityRelaySnapshotRecord] = {}
        self._deletions: dict[str, IdentityRelayDeletionAdmission] = {}

    def begin_session(self, lease: WorkLease) -> IdentityRelaySnapshotSession:
        if lease.session_generation is None:
            raise TypeError("Identity Relay snapshot sessions require a session lease.")
        session = IdentityRelaySnapshotSession(
            run_id=lease.run_id,
            session_generation=lease.session_generation,
        )
        with self._lock:
            self._session = session
            self._turns.clear()
            self._records.clear()
            self._deletions.clear()
        return session

    def bind_turn(
        self,
        session: IdentityRelaySnapshotSession,
        lease: WorkLease,
    ) -> CommandResult[IdentityRelaySnapshotTurn]:
        if lease.turn_id is None:
            raise TypeError("Identity Relay snapshot publication requires a turn lease.")
        route_generation = lease.route_generation or RouteGeneration(0)
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None or not self._lease_matches_session(lease, session):
                return stale or self._stale_session_failure()
            turn = IdentityRelaySnapshotTurn(
                session=session,
                turn_id=lease.turn_id,
                route_generation=route_generation,
            )
            self._turns[turn.turn_id] = turn
            return CommandResult(accepted=True, value=turn)

    def discard_turn(self, turn: IdentityRelaySnapshotTurn) -> bool:
        with self._lock:
            current = self._turns.get(turn.turn_id)
            if current is None or current._binding_id is not turn._binding_id:
                return False
            self._turns.pop(turn.turn_id, None)
            return True

    def capture_legacy_snapshot(
        self,
        turn: IdentityRelaySnapshotTurn,
        snapshot: object,
    ) -> CommandResult[IdentityRelayCapturedSnapshot]:
        captured = self._freeze_legacy_snapshot(snapshot)
        with self._lock:
            stale = self._stale_turn_failure_locked(turn)
            if stale is not None:
                return stale
            if captured.record is not None:
                deleting = self._deletion_failure_locked(captured.record.artifact_ref)
                if deleting is not None:
                    return deleting
                self._records.setdefault(captured.record.snapshot_hash, captured.record)
        return CommandResult(accepted=True, value=captured)

    def store_projection(
        self,
        turn: IdentityRelaySnapshotTurn,
        snapshot: object,
    ) -> CommandResult[IdentityRelaySnapshotRecord | None]:
        payload = self._v2_snapshot_payload(snapshot)
        persistence_mode = str((payload or {}).get("persistence_mode") or "").strip().lower()
        snapshot_hash = str((payload or {}).get("snapshot_hash") or "")
        if (
            payload is None
            or persistence_mode != "persistent"
            or not snapshot_hash
        ):
            with self._lock:
                stale = self._stale_turn_failure_locked(turn)
            if stale is not None:
                return stale
            return CommandResult(accepted=True, value=None)
        record = self._record_from_entry(snapshot_hash, payload)
        if record is None or record.schema_version != 2:
            return _failure(
                "identity_relay_invalid_snapshot",
                "Persistent Identity Relay projection is invalid.",
            )
        with self._lock:
            stale = self._stale_turn_failure_locked(turn)
            if stale is not None:
                return stale
            deleting = self._deletion_failure_locked(record.artifact_ref)
            if deleting is not None:
                return deleting
            self._records[snapshot_hash] = record
        return CommandResult(accepted=True, value=record)

    def restore_session(
        self,
        session: IdentityRelaySnapshotSession,
        snapshots: object,
    ) -> CommandResult[int]:
        restored = self._sanitize_registry(snapshots)
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
            if any(
                record.artifact_ref in self._deletions
                for record in restored.values()
            ):
                return _failure(
                    "identity_relay_deletion_in_progress",
                    "Identity Relay snapshots cannot be restored during artifact deletion.",
                )
            self._records.update(restored)
        return CommandResult(accepted=True, value=len(restored))

    def export_session(
        self,
        session: IdentityRelaySnapshotSession,
    ) -> CommandResult[Mapping[str, Mapping[str, object]]]:
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
            exported = {
                snapshot_hash: record.as_mapping()
                for snapshot_hash, record in self._records.items()
            }
        return CommandResult(accepted=True, value=_freeze_mapping(exported))

    def persisted_snapshot_for_turn(
        self,
        session: IdentityRelaySnapshotSession,
        source_record: Mapping[str, object],
    ) -> CommandResult[Mapping[str, object] | None]:
        metadata = self.metadata_from_turn(source_record)
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
            record = self._matching_record_locked(metadata)
            if (
                record is None
                or metadata is None
                or metadata.schema_version != 2
                or metadata.status != "ready"
                or str(record.payload.get("persistence_mode") or "") != "persistent"
            ):
                return CommandResult(accepted=True, value=None)
            return CommandResult(accepted=True, value=record.payload)

    def expand_for_request(
        self,
        session: IdentityRelaySnapshotSession,
        source_record: Mapping[str, object],
    ) -> CommandResult[Mapping[str, object] | None]:
        metadata = self.metadata_from_turn(source_record)
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
            if metadata is None:
                return CommandResult(accepted=True, value=None)
            metadata_value = metadata.as_mapping()
            if metadata.schema_version == 2:
                if metadata.status != "ready":
                    return CommandResult(
                        accepted=True,
                        value=_freeze_mapping(metadata_value),
                    )
                record = self._matching_record_locked(metadata)
                if record is None:
                    return CommandResult(
                        accepted=True,
                        value=_freeze_mapping(
                            {
                                **metadata_value,
                                "status": "blocked",
                                "failure_code": "missing",
                                "prompt_text": "",
                            }
                        ),
                    )
                return CommandResult(accepted=True, value=record.payload)
            if metadata.status != "active":
                return CommandResult(
                    accepted=True,
                    value=_freeze_mapping({**metadata_value, "hot_identity_text": ""}),
                )
            record = self._matching_record_locked(metadata)
            if record is None:
                return CommandResult(
                    accepted=True,
                    value=_freeze_mapping(
                        {
                            "state": "unavailable",
                            "artifact_ref": metadata.artifact_ref,
                            "failure_code": "missing",
                            "hot_identity_text": "",
                        }
                    ),
                )
            return CommandResult(
                accepted=True,
                value=_freeze_mapping(
                    {
                        **metadata_value,
                        "hot_identity_text": record.payload["hot_identity_text"],
                    }
                ),
            )

    def freeze_persistence(
        self,
        session: IdentityRelaySnapshotSession,
        source_records: Sequence[Mapping[str, object]],
    ) -> CommandResult[IdentityRelayPersistenceSnapshot]:
        frozen_sources = tuple(_freeze_mapping(record) for record in source_records)
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
            referenced: dict[str, Mapping[str, object]] = {}
            for source_record in frozen_sources:
                metadata = self.metadata_from_turn(source_record)
                if metadata is None or not (
                    (metadata.schema_version == 1 and metadata.status == "active")
                    or (metadata.schema_version == 2 and metadata.status == "ready")
                ):
                    continue
                record = self._matching_record_locked(metadata)
                if record is not None:
                    referenced[record.snapshot_hash] = record.payload
            snapshot = IdentityRelayPersistenceSnapshot(
                session=session,
                source_records=frozen_sources,
                snapshots=referenced,
            )
        return CommandResult(accepted=True, value=snapshot)

    def deletion_blockers(
        self,
        session: IdentityRelaySnapshotSession,
        artifact_ref: object,
        sources: IdentityRelayLoadedSourceRecords,
    ) -> CommandResult[tuple[str, ...]]:
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
        return CommandResult(
            accepted=True,
            value=self._loaded_reference_reasons(artifact_ref, sources),
        )

    def begin_deletion(
        self,
        session: IdentityRelaySnapshotSession,
        artifact_ref: object,
        sources: IdentityRelayLoadedSourceRecords,
    ) -> CommandResult[IdentityRelayDeletionAdmission]:
        target_ref = str(artifact_ref or "")
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
            if target_ref in self._deletions:
                return _failure(
                    "identity_relay_deletion_in_progress",
                    "Identity Relay artifact deletion is already in progress.",
                )
            blockers = self._loaded_reference_reasons(target_ref, sources)
            admission = IdentityRelayDeletionAdmission(
                session=session,
                artifact_ref=target_ref,
                blocked_by=blockers,
            )
            if admission.admitted:
                self._deletions[target_ref] = admission
            return CommandResult(accepted=True, value=admission)

    def finish_deletion(
        self,
        admission: IdentityRelayDeletionAdmission,
        *,
        committed: bool,
    ) -> CommandResult[int]:
        with self._lock:
            stale = self._stale_session_failure_locked(admission.session)
            if stale is not None:
                return stale
            if not admission.admitted:
                return _failure(
                    "identity_relay_deletion_blocked",
                    "Blocked Identity Relay deletion admission cannot be completed.",
                )
            current = self._deletions.get(admission.artifact_ref)
            if current is None or current._binding_id is not admission._binding_id:
                return _failure(
                    "identity_relay_stale_deletion",
                    "Identity Relay deletion admission is no longer active.",
                )
            self._deletions.pop(admission.artifact_ref, None)
            if not committed:
                return CommandResult(accepted=True, value=0)
            matching = tuple(
                snapshot_hash
                for snapshot_hash, record in self._records.items()
                if record.artifact_ref == admission.artifact_ref
            )
            for snapshot_hash in matching:
                self._records.pop(snapshot_hash, None)
            return CommandResult(accepted=True, value=len(matching))

    def purge_derivatives(
        self,
        session: IdentityRelaySnapshotSession,
        artifact_ref: object,
        sources: IdentityRelayLoadedSourceRecords,
    ) -> CommandResult[IdentityRelayPurgeResult]:
        target_ref = str(artifact_ref or "")
        with self._lock:
            stale = self._stale_session_failure_locked(session)
            if stale is not None:
                return stale
            deleting = self._deletion_failure_locked(target_ref)
            if deleting is not None:
                return deleting
            blockers = self._loaded_reference_reasons(target_ref, sources)
            if blockers:
                return CommandResult(
                    accepted=True,
                    value=IdentityRelayPurgeResult(False, blockers, 0),
                )
            matching = tuple(
                snapshot_hash
                for snapshot_hash, record in self._records.items()
                if record.artifact_ref == target_ref
            )
            for snapshot_hash in matching:
                self._records.pop(snapshot_hash, None)
            return CommandResult(
                accepted=True,
                value=IdentityRelayPurgeResult(True, (), len(matching)),
            )

    @classmethod
    def sanitize_metadata(
        cls,
        value: object,
    ) -> IdentityRelaySnapshotMetadata | None:
        if not isinstance(value, Mapping):
            return None
        if value.get("schema_version") == 2:
            projection_kind = str(value.get("projection_kind") or "").strip()
            status = str(value.get("status") or "").strip().lower()
            artifact_ref = str(value.get("artifact_ref") or "").strip()
            artifact_hash = str(value.get("artifact_hash") or "").strip()
            snapshot_hash = str(value.get("snapshot_hash") or "").strip()
            if (
                projection_kind != "normalized_projection"
                or status not in {"ready", "suspended"}
                or not IdentityRelayService.ref_matches_hash(artifact_ref, artifact_hash)
                or (status == "ready" and not _is_sha256(snapshot_hash))
                or (status == "suspended" and bool(snapshot_hash))
            ):
                return None
            return IdentityRelaySnapshotMetadata(
                schema_version=2,
                status=status,
                artifact_ref=artifact_ref,
                artifact_hash=artifact_hash,
                snapshot_hash=snapshot_hash,
            )
        status = str(value.get("state") or "").strip().lower()
        artifact_ref = str(value.get("artifact_ref") or "").strip()
        artifact_hash = str(value.get("artifact_hash") or "").strip()
        if status not in _IDENTITY_RELAY_V1_STATES:
            return None
        raw_failure_code = value.get("failure_code")
        failure_code = (
            None
            if raw_failure_code is None
            else str(raw_failure_code or "").strip().lower()
        )
        if failure_code is not None and failure_code not in _IDENTITY_RELAY_V1_FAILURE_CODES:
            return None
        if status == "unavailable":
            if not _strict_artifact_ref(artifact_ref) or failure_code is None:
                return None
            return IdentityRelaySnapshotMetadata(
                schema_version=1,
                status=status,
                artifact_ref=artifact_ref,
                failure_code=failure_code,
            )
        if not IdentityRelayService.ref_matches_hash(artifact_ref, artifact_hash):
            return None
        snapshot_hash = str(value.get("snapshot_hash") or "").strip()
        if snapshot_hash and not _is_sha256(snapshot_hash):
            return None
        if status == "active" and (not snapshot_hash or failure_code is not None):
            return None
        if status == "suspended" and (snapshot_hash or failure_code is not None):
            return None
        return IdentityRelaySnapshotMetadata(
            schema_version=1,
            status=status,
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            snapshot_hash=snapshot_hash,
            failure_code=failure_code,
        )

    @classmethod
    def metadata_from_turn(
        cls,
        source_record: Mapping[str, object],
    ) -> IdentityRelaySnapshotMetadata | None:
        return cls.sanitize_metadata(source_record.get("identity_relay"))

    @classmethod
    def _freeze_legacy_snapshot(cls, snapshot: object) -> IdentityRelayCapturedSnapshot:
        if not isinstance(snapshot, Mapping):
            return IdentityRelayCapturedSnapshot(None)
        status = str(snapshot.get("state") or "").strip().lower()
        artifact_ref = str(snapshot.get("artifact_ref") or "").strip()
        artifact_hash = str(snapshot.get("artifact_hash") or "").strip()
        failure_code = snapshot.get("failure_code")
        if status == "active":
            hot_identity_text = str(snapshot.get("hot_identity_text") or "")
            if not hot_identity_text.strip():
                status = "unavailable"
                failure_code = "empty_hot_identity"
            else:
                snapshot_hash = _legacy_snapshot_hash(
                    artifact_ref,
                    artifact_hash,
                    hot_identity_text,
                )
                metadata = cls.sanitize_metadata(
                    {
                        "state": status,
                        "artifact_ref": artifact_ref,
                        "artifact_hash": artifact_hash,
                        "snapshot_hash": snapshot_hash,
                        "failure_code": failure_code,
                    }
                )
                if metadata is None:
                    return IdentityRelayCapturedSnapshot(None)
                record = IdentityRelaySnapshotRecord(
                    snapshot_hash=snapshot_hash,
                    artifact_ref=artifact_ref,
                    artifact_hash=artifact_hash,
                    schema_version=1,
                    payload={
                        "artifact_ref": artifact_ref,
                        "artifact_hash": artifact_hash,
                        "hot_identity_text": hot_identity_text,
                    },
                )
                return IdentityRelayCapturedSnapshot(metadata, record)
        metadata = cls.sanitize_metadata(
            {
                "state": status,
                "artifact_ref": artifact_ref,
                "artifact_hash": artifact_hash,
                "failure_code": failure_code,
            }
        )
        return IdentityRelayCapturedSnapshot(metadata)

    @staticmethod
    def _v2_snapshot_payload(snapshot: object) -> dict[str, object] | None:
        schema_version = _field(snapshot, "schema_version", 0)
        if snapshot is None or int(schema_version or 0) != 2:
            return None
        return {
            name: _plain(_field(snapshot, name, None))
            for name in _IDENTITY_RELAY_V2_SNAPSHOT_FIELDS
        }

    @classmethod
    def _record_from_entry(
        cls,
        snapshot_hash: object,
        raw_entry: object,
    ) -> IdentityRelaySnapshotRecord | None:
        normalized_hash = str(snapshot_hash or "").strip()
        if not _is_sha256(normalized_hash) or not isinstance(raw_entry, Mapping):
            return None
        if raw_entry.get("schema_version") == 2:
            payload = cls._v2_snapshot_payload(raw_entry)
            metadata = cls.sanitize_metadata(payload)
            if (
                payload is None
                or metadata is None
                or metadata.status != "ready"
                or metadata.snapshot_hash != normalized_hash
                or IdentityRelayService.snapshot_hash(payload) != normalized_hash
                or not str(payload.get("prompt_text") or "").strip()
                or str(payload.get("persistence_mode") or "").strip().lower()
                != "persistent"
            ):
                return None
            payload.update(metadata.as_mapping())
            payload["prompt_text"] = str(payload.get("prompt_text") or "")
            payload["persistence_mode"] = "persistent"
            return IdentityRelaySnapshotRecord(
                snapshot_hash=normalized_hash,
                artifact_ref=metadata.artifact_ref,
                artifact_hash=metadata.artifact_hash,
                schema_version=2,
                payload=payload,
            )
        artifact_ref = str(raw_entry.get("artifact_ref") or "").strip()
        artifact_hash = str(raw_entry.get("artifact_hash") or "").strip()
        hot_identity_text = str(raw_entry.get("hot_identity_text") or "")
        if (
            not hot_identity_text.strip()
            or not IdentityRelayService.ref_matches_hash(artifact_ref, artifact_hash)
            or _legacy_snapshot_hash(artifact_ref, artifact_hash, hot_identity_text)
            != normalized_hash
        ):
            return None
        return IdentityRelaySnapshotRecord(
            snapshot_hash=normalized_hash,
            artifact_ref=artifact_ref,
            artifact_hash=artifact_hash,
            schema_version=1,
            payload={
                "artifact_ref": artifact_ref,
                "artifact_hash": artifact_hash,
                "hot_identity_text": hot_identity_text,
            },
        )

    @classmethod
    def _sanitize_registry(
        cls,
        snapshots: object,
    ) -> dict[str, IdentityRelaySnapshotRecord]:
        if not isinstance(snapshots, Mapping):
            return {}
        sanitized: dict[str, IdentityRelaySnapshotRecord] = {}
        for snapshot_hash, raw_entry in snapshots.items():
            record = cls._record_from_entry(snapshot_hash, raw_entry)
            if record is not None:
                sanitized[record.snapshot_hash] = record
        return sanitized

    @classmethod
    def _loaded_reference_reasons(
        cls,
        artifact_ref: object,
        sources: IdentityRelayLoadedSourceRecords,
    ) -> tuple[str, ...]:
        target_ref = str(artifact_ref or "")
        reasons: list[str] = []
        if any(
            cls._turn_artifact_ref(turn) == target_ref
            for turn in sources.conversation_history
        ):
            reasons.append("loaded_chat:conversation_history")
        if cls._turn_artifact_ref(sources.pending_turn) == target_ref:
            reasons.append("loaded_chat:pending_turn")
        if any(
            candidate == target_ref
            for transaction in sources.active_transactions
            for candidate in (
                cls._turn_artifact_ref(transaction.accepted_turn),
                transaction.relay_capture_artifact_ref,
                transaction.relay_snapshot_artifact_ref,
            )
        ):
            reasons.append("loaded_chat:active_transaction")
        return tuple(reasons)

    @classmethod
    def _turn_artifact_ref(cls, turn: object) -> str:
        if not isinstance(turn, Mapping):
            return ""
        metadata = cls.sanitize_metadata(turn.get("identity_relay"))
        return metadata.artifact_ref if metadata is not None else ""

    @staticmethod
    def _artifact_ref(value: object) -> str:
        return str(_field(value, "artifact_ref", "") or "")

    def _matching_record_locked(
        self,
        metadata: IdentityRelaySnapshotMetadata | None,
    ) -> IdentityRelaySnapshotRecord | None:
        if metadata is None or not metadata.snapshot_hash:
            return None
        record = self._records.get(metadata.snapshot_hash)
        if (
            record is None
            or record.artifact_ref != metadata.artifact_ref
            or record.artifact_hash != metadata.artifact_hash
        ):
            return None
        return record

    def _deletion_failure_locked(self, artifact_ref: str):
        if artifact_ref not in self._deletions:
            return None
        return _failure(
            "identity_relay_deletion_in_progress",
            "Identity Relay artifact deletion is in progress.",
        )

    def _stale_session_failure_locked(
        self,
        session: IdentityRelaySnapshotSession,
    ):
        current = self._session
        if current is None or current._binding_id is not session._binding_id:
            return self._stale_session_failure()
        return None

    def _stale_turn_failure_locked(self, turn: IdentityRelaySnapshotTurn):
        stale_session = self._stale_session_failure_locked(turn.session)
        if stale_session is not None:
            return stale_session
        current = self._turns.get(turn.turn_id)
        if current is None or current._binding_id is not turn._binding_id:
            return _failure(
                "stale_turn",
                "Identity Relay snapshot work no longer owns the current turn route.",
            )
        return None

    @staticmethod
    def _lease_matches_session(
        lease: WorkLease,
        session: IdentityRelaySnapshotSession,
    ) -> bool:
        return (
            lease.run_id == session.run_id
            and lease.session_generation == session.session_generation
        )

    @staticmethod
    def _stale_session_failure():
        return _failure(
            "stale_session",
            "Identity Relay snapshot work no longer owns the current chat session.",
        )


class IdentityRelayService:
    """Own exact accepted-turn Relay bindings and provider projections."""

    def __init__(
        self,
        *,
        providers: IdentityRelayProviderPort,
        workers: WorkerSupervisor,
        artifacts: IdentityRelayArtifactCapabilities | None = None,
        count_tokens: TokenCounter | None = None,
        provider_dispatch: ProviderDispatch | None = None,
        logger: Logger | None = None,
        runtime_embedding: Callable[..., object] | None = None,
        runtime_delete_transaction: Callable[[object, object], object] | None = None,
        runtime_derivative_purge: Callable[[object], object] | None = None,
        runtime_artifact_controller: object | None = None,
    ) -> None:
        self._providers = providers
        self._workers = workers
        self._artifacts = artifacts or IdentityRelayArtifactCapabilities()
        self._count_tokens = count_tokens
        self._provider_dispatch = provider_dispatch
        self._logger = logger
        self._lock = threading.RLock()
        self._bindings: dict[tuple[int, int, str, int], _TurnBinding] = {}
        self._acceptance_options = threading.local()
        self._unknown_capacity_warnings: set[tuple[str, str]] = set()
        runtime_callbacks = (
            runtime_embedding,
            runtime_delete_transaction,
            runtime_derivative_purge,
        )
        if any(callback is not None for callback in runtime_callbacks) and not all(
            callable(callback) for callback in runtime_callbacks
        ):
            raise TypeError(
                "Identity Relay addon runtime capabilities must be supplied together."
            )
        self._addon_runtime = (
            IdentityRelayRuntimeCapabilities(
                runtime_embedding,
                runtime_delete_transaction,
                runtime_derivative_purge,
                runtime_artifact_controller,
            )
            if all(callable(callback) for callback in runtime_callbacks)
            else None
        )

    def detached_staging_allowed(self) -> bool:
        """A provisional request cannot safely stage an enabled Relay turn."""
        capture = self._artifacts.capture_mode
        if capture is None:
            return True
        try:
            return self._classify_mode(capture()) in {"unconnected", "connected-off"}
        except Exception:
            return False

    @property
    def workers(self) -> WorkerSupervisor:
        return self._workers

    def install_addon_runtime(self, host: object) -> bool:
        if not isinstance(host, IdentityRelayAddonRuntimeHost):
            return False
        host.set_identity_relay_runtime_service(self._addon_runtime)
        return True

    def clear_capacity_warnings(self) -> None:
        with self._lock:
            self._unknown_capacity_warnings.clear()

    @contextmanager
    def acceptance(
        self,
        *,
        restored_snapshot: Mapping[str, object] | None = None,
        mode: str = "current",
    ):
        previous = getattr(self._acceptance_options, "value", None)
        self._acceptance_options.value = _AcceptanceOptions(
            restored_snapshot=(
                _freeze_mapping(restored_snapshot)
                if isinstance(restored_snapshot, Mapping)
                else None
            ),
            mode=str(mode or "current"),
        )
        try:
            yield
        finally:
            if previous is None:
                try:
                    del self._acceptance_options.value
                except AttributeError:
                    pass
            else:
                self._acceptance_options.value = previous

    def freeze_for_turn(
        self,
        lease: WorkLease,
        provider: ProviderSelection,
    ) -> IdentityRelayTurnState:
        if not isinstance(lease, WorkLease) or lease.turn_id is None:
            raise TypeError("Identity Relay freeze requires a turn-scoped WorkLease.")
        if not isinstance(provider, ProviderSelection):
            raise TypeError("Identity Relay freeze requires ProviderSelection.")
        options = getattr(
            self._acceptance_options,
            "value",
            _AcceptanceOptions(),
        )
        owner_override = provider.config.values.get(
            "identity_relay_owner_override",
            False,
        ) is True
        restored_snapshot, restored_metadata, capture_error = (
            self._validated_restored_snapshot(options.restored_snapshot)
        )
        capture = None
        if restored_snapshot is None and not capture_error and options.mode != "off":
            capture, capture_error = self._capture(provider, owner_override)

        source = restored_snapshot if restored_snapshot is not None else capture
        runtime_use = _field(source, "runtime_use", {})
        if not isinstance(runtime_use, Mapping):
            runtime_use = {}
        enabled = restored_snapshot is not None or _field(source, "enabled", False) is True
        artifact_ref = _field(source, "artifact_ref", "")
        artifact_hash = _field(source, "artifact_hash", "")
        connection_revision = _field(source, "connection_revision", 0)
        subject_kind = _field(source, "subject_kind", _MISSING)
        if subject_kind is _MISSING:
            subject_kind = runtime_use.get("subject_class")
        artifact_revision = _field(source, "artifact_revision", _MISSING)
        if artifact_revision is _MISSING:
            artifact_revision = _field(source, "normalizer_revision", _MISSING)
        if artifact_revision is _MISSING:
            artifact_revision = artifact_hash
        route_generation = (
            lease.route_generation.value if lease.route_generation is not None else 0
        )
        state = IdentityRelayTurnState(
            enabled=bool(enabled),
            artifact_ref=(
                str(artifact_ref) if isinstance(artifact_ref, str) and artifact_ref else None
            ),
            connection_revision=(
                connection_revision if type(connection_revision) is int else 0
            ),
            subject_kind=(
                str(subject_kind) if isinstance(subject_kind, str) and subject_kind else None
            ),
            artifact_revision=(
                str(artifact_revision)
                if isinstance(artifact_revision, str) and artifact_revision
                else None
            ),
            owner_override=owner_override,
            provider_id=provider.provider_id,
            model_id=provider.model_id,
            run_generation=lease.run_id.value,
            session_generation=(
                lease.session_generation.value
                if lease.session_generation is not None
                else 0
            ),
            turn_id=lease.turn_id.value,
            route_generation=route_generation,
        )
        binding = _TurnBinding(
            lease=lease,
            state=state,
            provider=provider,
            capture=capture,
            capture_error=capture_error,
            restored_snapshot=restored_snapshot,
            restored_metadata=restored_metadata,
        )
        with self._lock:
            self._bindings[self._key_for_lease(lease)] = binding
        return state

    def bind_request(
        self,
        state: IdentityRelayTurnState,
        query: Mapping[str, object],
    ) -> CommandResult[None]:
        if not isinstance(query, Mapping):
            return _failure(
                "identity_relay_query_invalid",
                "Identity Relay requires an immutable query mapping.",
            )
        with self._lock:
            key = self._key_for_state(state)
            binding = self._bindings.get(key)
            if binding is None or binding.state != state:
                return _failure(
                    "identity_relay_turn_discarded",
                    "The Identity Relay turn binding is no longer active.",
                )
            self._bindings[key] = replace(binding, query=_freeze_mapping(query))
        return CommandResult(True)

    def prepare(
        self,
        state: IdentityRelayTurnState,
        token: CancellationToken,
    ) -> CommandResult[IdentityRelayProjection]:
        if not isinstance(state, IdentityRelayTurnState):
            return _failure(
                "identity_relay_state_invalid",
                "Identity Relay preparation requires IdentityRelayTurnState.",
            )
        if not isinstance(token, CancellationToken):
            return _failure(
                "identity_relay_token_invalid",
                "Identity Relay preparation requires CancellationToken.",
            )
        if token.cancelled:
            return self._cancelled(token)
        with self._lock:
            key = self._key_for_state(state)
            binding = self._bindings.get(key)
            if binding is None or binding.state != state:
                return _failure(
                    "identity_relay_turn_discarded",
                    "The Identity Relay turn binding is no longer active.",
                )
            if binding.projection is not None:
                self._bindings[key] = replace(binding, token=token)
                return CommandResult(True, value=binding.projection)
            self._bindings[key] = replace(binding, token=token)
        if binding.capture_error:
            return _failure(
                "identity_relay_capture_failed",
                binding.capture_error,
            )
        if binding.restored_snapshot is not None:
            result = self._prepare_restored(binding, token)
        elif binding.capture is None:
            result = CommandResult(
                True,
                value=IdentityRelayProjection("off", binding.provider),
            )
        elif _field(binding.capture, "enabled", False) is not True:
            result = self._prepare_suspended(binding)
        elif binding.query is None:
            result = _failure(
                "identity_relay_query_unbound",
                "Identity Relay request state was not bound before preparation.",
            )
        else:
            result = self._prepare_active(binding, token)
        if not result.accepted or result.value is None:
            return result
        if token.cancelled:
            return self._cancelled(token)
        with self._lock:
            current = self._bindings.get(key)
            if (
                current is None
                or current.binding_id is not binding.binding_id
                or current.lease != binding.lease
                or current.state != state
                or current.token is not token
            ):
                return _failure(
                    "identity_relay_turn_discarded",
                    "The Identity Relay turn was discarded during preparation.",
                )
            self._bindings[key] = replace(
                current,
                provider=result.value.provider,
                projection=result.value,
                token=token,
            )
        return result

    def schedule_prepare(
        self,
        state: IdentityRelayTurnState,
        token: CancellationToken,
        on_complete: PrepareCompletion,
    ) -> CommandResult[WorkerHandle]:
        if not callable(on_complete):
            return _failure(
                "identity_relay_completion_invalid",
                "Identity Relay preparation requires a completion callback.",
            )
        with self._lock:
            binding = self._bindings.get(self._key_for_state(state))
        if binding is None or binding.state != state:
            return _failure(
                "identity_relay_turn_discarded",
                "The Identity Relay turn binding is no longer active.",
            )

        def work(supervisor_token: CancellationToken) -> None:
            if supervisor_token.cancelled:
                token.cancel(supervisor_token.reason)
            result = self.prepare(state, token)
            if self._binding_admission_failure(
                binding,
                token,
                require_token=True,
            ) is None:
                on_complete(binding.lease, binding.state, result)

        try:
            handle = self._workers.spawn(
                name="nc-identity-relay-turn",
                lease=binding.lease,
                target=work,
                on_cancel=lambda reason: token.cancel(reason),
                identity=("identity_relay", state.turn_id, state.route_generation),
            )
        except BaseException as exc:
            token.cancel("worker_start_failed")
            return _failure(
                "identity_relay_worker_start_failed",
                str(exc) or "Identity Relay preparation worker could not start.",
                exc,
            )
        return CommandResult(True, value=handle)

    def discard_turn(
        self,
        turn_id: TurnId,
        *,
        lease: WorkLease | None = None,
    ) -> None:
        if not isinstance(turn_id, TurnId):
            raise TypeError("Identity Relay discard requires TurnId.")
        tokens: list[CancellationToken] = []
        with self._lock:
            for key, binding in tuple(self._bindings.items()):
                if binding.lease.turn_id != turn_id:
                    continue
                if lease is not None and binding.lease != lease:
                    continue
                self._bindings.pop(key, None)
                if binding.token is not None:
                    tokens.append(binding.token)
        for token in tokens:
            token.cancel("identity_relay_turn_discarded")

    def projection_for(
        self,
        state: IdentityRelayTurnState,
    ) -> IdentityRelayProjection | None:
        with self._lock:
            binding = self._bindings.get(self._key_for_state(state))
            return binding.projection if binding is not None else None

    def binding_for(
        self,
        state: IdentityRelayTurnState,
    ) -> IdentityRelayTurnBinding | None:
        with self._lock:
            binding = self._bindings.get(self._key_for_state(state))
            if binding is None or binding.state != state:
                return None
            return IdentityRelayTurnBinding(
                state=binding.state,
                provider=binding.provider,
                capture=binding.capture,
                capture_error=binding.capture_error,
                restored_snapshot=binding.restored_snapshot,
                restored_metadata=binding.restored_metadata,
            )

    def _capture(
        self,
        provider: ProviderSelection,
        owner_override: bool,
    ) -> tuple[object, str]:
        mode_snapshot = IDENTITY_RELAY_CAPABILITY_UNAVAILABLE
        capture_mode = self._artifacts.capture_mode
        if capture_mode is not None:
            try:
                mode_snapshot = capture_mode()
            except BaseException as exc:
                return None, str(exc) or "Identity Relay mode capture failed."
        mode_state = None
        if mode_snapshot is not IDENTITY_RELAY_CAPABILITY_UNAVAILABLE:
            mode_state = self._classify_mode(mode_snapshot)
            if mode_state == "invalid":
                return None, "Identity Relay returned an invalid mode snapshot."
            if mode_state == "unconnected":
                return None, ""
        capture_turn = self._artifacts.capture_turn
        if capture_turn is None:
            if mode_state == "connected-off":
                return mode_snapshot, ""
            return None, ""
        payload: dict[str, object] = {
            "schema_version": 2,
            "frozen_provider": self._provider_payload(provider),
            "owner_override": owner_override,
        }
        if mode_snapshot is not IDENTITY_RELAY_CAPABILITY_UNAVAILABLE:
            payload["mode_snapshot"] = mode_snapshot
        try:
            capture = capture_turn(MappingProxyType(payload))
        except BaseException as exc:
            if mode_state == "connected-off":
                return mode_snapshot, ""
            return None, str(exc) or "Identity Relay capture failed."
        if mode_state == "connected-off":
            return mode_snapshot, ""
        if mode_state == "connected-on" and not self._capture_matches_mode(
            capture,
            mode_snapshot,
        ):
            return None, "Identity Relay returned an invalid active capture."
        return capture, ""

    def _prepare_suspended(
        self,
        binding: _TurnBinding,
    ) -> CommandResult[IdentityRelayProjection]:
        capture = binding.capture
        metadata = {
            "schema_version": 2,
            "projection_kind": "normalized_projection",
            "status": "suspended",
            "artifact_ref": str(_field(capture, "artifact_ref", "") or ""),
            "artifact_hash": str(_field(capture, "artifact_hash", "") or ""),
        }
        if self.metadata(metadata) is None:
            return _failure(
                "identity_relay_suspended_invalid",
                "Identity Relay returned an invalid suspended capture.",
            )
        return CommandResult(
            True,
            value=IdentityRelayProjection(
                "suspended",
                binding.provider,
                metadata=metadata,
            ),
        )

    def _prepare_active(
        self,
        binding: _TurnBinding,
        token: CancellationToken,
    ) -> CommandResult[IdentityRelayProjection]:
        admission_failure = self._binding_admission_failure(
            binding,
            token,
            require_token=True,
        )
        if admission_failure is not None:
            return admission_failure
        provider = self._providers.upgrade_selection_for_relay(binding.provider)
        admission_failure = self._binding_admission_failure(
            binding,
            token,
            require_token=True,
        )
        if admission_failure is not None:
            return admission_failure
        if not self._providers.strict_relay_capability_available(provider):
            return _failure(
                "identity_relay_provider_not_strict",
                "Identity Relay requires strict frozen provider token counting.",
            )
        context_limit = self.exact_context_limit(provider)
        if context_limit is None:
            self._warn_unknown_capacity(provider)
        prepare_turn = self._artifacts.prepare_turn
        finalize_turn = self._artifacts.finalize_turn
        if prepare_turn is None or finalize_turn is None:
            return _failure(
                "identity_relay_artifact_service_unavailable",
                "Identity Relay artifact preparation is unavailable.",
            )

        def judge_token_counter(messages: Sequence[Mapping[str, object]]) -> int:
            if self._count_tokens is None:
                raise RuntimeError("strict Relay token counting is unavailable")
            return int(self._count_tokens(provider.context, messages))

        admission_failure = self._binding_admission_failure(
            binding,
            token,
            require_token=True,
        )
        if admission_failure is not None:
            return admission_failure
        try:
            prepared = prepare_turn(
                MappingProxyType(
                    {
                        "schema_version": 2,
                        "capture": binding.capture,
                        "query": binding.query,
                        "judge_capacity": MappingProxyType(
                            {
                                "context_limit": context_limit,
                                "token_counter": judge_token_counter,
                                "output_budget": self.judge_output_budget,
                            }
                        ),
                    }
                )
            )
        except BaseException as exc:
            return _failure(
                "identity_relay_prepare_failed",
                str(exc) or "Identity Relay artifact preparation failed.",
                exc,
            )
        admission_failure = self._binding_admission_failure(
            binding,
            token,
            require_token=True,
        )
        if admission_failure is not None:
            return admission_failure
        status = str(_field(prepared, "status", "") or "")
        if prepared is None or status == "blocked":
            failure_code = str(
                _field(prepared, "failure_code", "prepare_failed")
                or "prepare_failed"
            )
            return _failure(
                "identity_relay_blocked",
                f"Identity Relay blocked the turn: {failure_code}.",
            )
        judge_payload = None
        if status == "judge_required":
            judge_payload = self._run_judge_batches(
                binding,
                provider,
                prepared,
                token,
                context_limit,
            )
            if isinstance(judge_payload, CommandResult):
                return judge_payload
        elif status not in {"ready_without_judge", "suspended"}:
            return _failure(
                "identity_relay_prepare_status_invalid",
                f"Identity Relay returned unsupported prepare status {status!r}.",
            )
        admission_failure = self._binding_admission_failure(
            binding,
            token,
            require_token=True,
        )
        if admission_failure is not None:
            return admission_failure
        try:
            snapshot = finalize_turn(
                MappingProxyType(
                    {
                        "schema_version": 2,
                        "prepared": prepared,
                        "judge_payload": judge_payload,
                    }
                )
            )
        except BaseException as exc:
            return _failure(
                "identity_relay_finalize_failed",
                str(exc) or "Identity Relay artifact finalization failed.",
                exc,
            )
        if token.cancelled:
            return self._cancelled(token)
        snapshot_payload = self.snapshot_payload(snapshot)
        snapshot_status = str((snapshot_payload or {}).get("status") or "")
        if snapshot_payload is None or snapshot_status != "ready":
            failure_code = str(
                (snapshot_payload or {}).get("failure_code") or "finalize_failed"
            )
            return _failure(
                "identity_relay_blocked",
                f"Identity Relay blocked the turn: {failure_code}.",
            )
        prompt_text = str(snapshot_payload.get("prompt_text") or "")
        if not prompt_text.strip():
            return _failure(
                "identity_relay_projection_empty",
                "Identity Relay returned an empty v2 projection.",
            )
        metadata = self.metadata(snapshot_payload)
        if metadata is None:
            return _failure(
                "identity_relay_metadata_invalid",
                "Identity Relay returned invalid v2 snapshot metadata.",
            )
        trace = snapshot_payload.get("trace")
        trace_mapping = dict(trace) if isinstance(trace, Mapping) else {}
        notice = self._notice_from_trace(trace_mapping)
        omitted = tuple(
            str(item)
            for item in tuple(
                _field(prepared, "omitted_kernel_record_ids", ()) or ()
            )
            if str(item)
        )
        return CommandResult(
            True,
            value=IdentityRelayProjection(
                "ready",
                provider,
                snapshot=snapshot_payload,
                metadata=metadata,
                prompt_text=prompt_text,
                omitted_record_ids=omitted,
                notice=notice,
                trace=trace_mapping,
            ),
        )

    def _prepare_restored(
        self,
        binding: _TurnBinding,
        token: CancellationToken,
    ) -> CommandResult[IdentityRelayProjection]:
        restore = self._artifacts.restore_persisted_snapshot
        snapshot = binding.restored_snapshot
        metadata = binding.restored_metadata
        if restore is None or snapshot is None or metadata is None:
            return _failure(
                "identity_relay_restore_unavailable",
                "Persisted Identity Relay authorization is unavailable.",
            )
        provider_payload = self._provider_payload(binding.provider)
        provider_is_remote = provider_payload.get("provider_is_remote")
        if type(provider_is_remote) is not bool:
            return _failure(
                "identity_relay_provider_locality_required",
                "Persisted Identity Relay provider authorization requires explicit locality.",
            )
        admission_failure = self._binding_admission_failure(
            binding,
            token,
            require_token=True,
        )
        if admission_failure is not None:
            return admission_failure
        try:
            authorization = restore(
                MappingProxyType(
                    {
                        "schema_version": 2,
                        "snapshot": snapshot,
                        "frozen_provider": MappingProxyType(provider_payload),
                    }
                )
            )
        except BaseException as exc:
            return _failure(
                "identity_relay_restore_failed",
                str(exc) or "Persisted Identity Relay authorization failed.",
                exc,
            )
        if token.cancelled:
            return self._cancelled(token)
        authorized = dict(authorization) if isinstance(authorization, Mapping) else {}
        if (
            authorized.get("authorized") is not True
            or str(authorized.get("snapshot_hash") or "")
            != str(snapshot.get("snapshot_hash") or "")
            or str(authorized.get("authorization_record_id") or "")
            != str(snapshot.get("authorization_record_id") or "")
            or authorized.get("provider_is_remote") is not provider_is_remote
        ):
            failure_code = str(
                authorized.get("failure_code")
                or "persisted_snapshot_authorization_required"
            )
            return _failure(
                "identity_relay_restore_not_authorized",
                f"Persisted Identity Relay authorization failed: {failure_code}.",
            )
        provider = self._providers.upgrade_selection_for_relay(binding.provider)
        if not self._providers.strict_relay_capability_available(provider):
            return _failure(
                "identity_relay_provider_not_strict",
                "Identity Relay requires strict frozen provider token counting.",
            )
        if self.exact_context_limit(provider) is None:
            self._warn_unknown_capacity(provider)
        trace = snapshot.get("trace")
        trace_mapping = dict(trace) if isinstance(trace, Mapping) else {}
        return CommandResult(
            True,
            value=IdentityRelayProjection(
                "ready",
                provider,
                snapshot=snapshot,
                metadata=metadata,
                prompt_text=str(snapshot.get("prompt_text") or ""),
                notice=self._notice_from_trace(trace_mapping),
                trace=trace_mapping,
            ),
        )

    def _run_judge_batches(
        self,
        binding: _TurnBinding,
        provider: ProviderSelection,
        prepared: object,
        token: CancellationToken,
        context_limit: int | None,
    ) -> Mapping[str, object] | CommandResult[IdentityRelayProjection]:
        render = self._artifacts.render_judge_request
        if render is None:
            batches = tuple(_field(prepared, "judge_batches", ()) or ())
        else:
            admission_failure = self._binding_admission_failure(
                binding,
                token,
                require_token=True,
            )
            if admission_failure is not None:
                return admission_failure
            try:
                batches = tuple(
                    render(
                        MappingProxyType(
                            {"schema_version": 2, "prepared": prepared}
                        )
                    )
                    or ()
                )
            except BaseException as exc:
                return _failure(
                    "identity_relay_judge_render_failed",
                    str(exc) or "Identity Relay judge rendering failed.",
                    exc,
                )
        candidate_total = sum(
            len(tuple(_field(batch, "candidate_ids", ()) or ()))
            for batch in batches
        )
        self._log(
            "[Identity Relay] Judge batching: "
            f"{candidate_total} candidate(s) -> {len(batches)} batch(es), "
            f"context={context_limit if context_limit is not None else 'unknown'}."
        )
        results: dict[str, object] = {}
        for batch in batches:
            if token.cancelled:
                return self._cancelled(token)
            batch_id = str(_field(batch, "batch_id", "") or "")
            candidate_ids = tuple(
                str(item)
                for item in tuple(_field(batch, "candidate_ids", ()) or ())
                if str(item)
            )
            output_budget = self.judge_output_budget(len(candidate_ids))
            try:
                admission_failure = self._binding_admission_failure(
                    binding,
                    token,
                    require_token=True,
                )
                if admission_failure is not None:
                    return admission_failure
                request = self._providers.prepare(
                    provider,
                    PromptRequest.from_payload(
                        {
                            "model": provider.model_id,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": str(
                                        _field(batch, "system_prompt", "")
                                        or "Return only the requested Identity Relay JSON decision."
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": str(
                                        _field(batch, "prompt_text", "") or ""
                                    ),
                                },
                            ],
                            "max_tokens": output_budget,
                        },
                        {
                            chat_providers.FROZEN_OUTPUT_TOKEN_BUDGET_OVERRIDE: (
                                output_budget
                            )
                        },
                    ),
                )
                messages, prepared_budget = self.prepared_request_details(request)
                if prepared_budget is None:
                    raise RuntimeError(
                        "Identity Relay judge request lost its bounded output budget."
                    )
                if self._count_tokens is None:
                    raise RuntimeError("strict Relay token counting is unavailable")
                input_tokens = int(self._count_tokens(provider.context, messages))
                if (
                    context_limit is not None
                    and input_tokens + prepared_budget > context_limit
                ):
                    raise OverflowError(
                        "Identity Relay judge batch exceeds the loaded model context capacity."
                    )
                dispatch = self._provider_dispatch
                if dispatch is not None:
                    admission_failure = self._binding_admission_failure(
                        binding,
                        token,
                        require_token=True,
                    )
                    if admission_failure is not None:
                        return admission_failure
                    dispatch(binding.state, request, "judge")
                admission_failure = self._binding_admission_failure(
                    binding,
                    token,
                    require_token=True,
                )
                if admission_failure is not None:
                    return admission_failure
                completed = self._providers.complete(request, token)
                if not completed.accepted:
                    failure = completed.failure
                    if failure is not None and failure.cause is not None:
                        raise failure.cause
                    raise RuntimeError(
                        failure.message
                        if failure is not None
                        else "Identity Relay judge provider execution failed."
                    )
                results[batch_id] = str(completed.value or "")
            except BaseException as exc:
                detail = " ".join(
                    str(exc or type(exc).__name__)
                    .replace("\r", " ")
                    .replace("\n", " ")
                    .split()
                )[:240]
                results[batch_id] = {
                    "failure_category": (
                        "capacity_validation_failed"
                        if isinstance(exc, (OverflowError, ValueError))
                        else "provider_exception"
                    ),
                    "reason": f"{type(exc).__name__}: {detail}",
                    "affected_record_ids": candidate_ids,
                }
        return MappingProxyType(results)

    def validate_prepared_request(
        self,
        state: IdentityRelayTurnState,
        prepared_request: object,
    ) -> CommandResult[None]:
        with self._lock:
            binding = self._bindings.get(self._key_for_state(state))
        if binding is None or binding.state != state:
            return _failure(
                "identity_relay_turn_discarded",
                "The Identity Relay turn binding is no longer active.",
            )
        projection = binding.projection
        if projection is None or projection.snapshot is None:
            return CommandResult(True)
        try:
            messages, output_budget = self.prepared_request_details(prepared_request)
            if self._count_tokens is None:
                raise RuntimeError("strict Relay token counting is unavailable")
            input_tokens = int(self._count_tokens(binding.provider.context, messages))
        except BaseException as exc:
            return _failure(
                "identity_relay_capacity_count_failed",
                f"Identity Relay strict capacity counting failed: {exc}",
                exc,
            )
        context_limit = self.exact_context_limit(binding.provider)
        if output_budget is None and context_limit is not None:
            output_budget = max(0, context_limit - input_tokens)
        if (
            context_limit is not None
            and output_budget is not None
            and input_tokens + output_budget > context_limit
        ):
            return _failure(
                "identity_relay_capacity_exceeded",
                "Identity Relay projection exceeds the exact prepared request capacity.",
            )
        return CommandResult(True)

    @staticmethod
    def prepared_request_details(
        prepared_request: object,
    ) -> tuple[list[Mapping[str, object]], int | None]:
        params_copy = getattr(prepared_request, "params_copy", None)
        additional_copy = getattr(prepared_request, "additional_params_copy", None)
        if not callable(params_copy) or not callable(additional_copy):
            raise TypeError(
                "Identity Relay capacity validation requires an inspectable frozen request."
            )
        params = dict(params_copy() or {})
        additional = dict(additional_copy() or {})
        messages = params.get("messages")
        output_budget = None
        nested = params.get("lmstudio_responses_payload")
        if isinstance(nested, Mapping):
            messages = nested.get("input")
            output_budget = nested.get("max_output_tokens")
        elif isinstance(params.get("input"), list):
            messages = params.get("input")
            output_budget = params.get("max_output_tokens")
        elif "system" in params and isinstance(params.get("messages"), list):
            messages = list(params.get("messages") or [])
            system_text = str(params.get("system") or "").strip()
            if system_text:
                messages.insert(0, {"role": "system", "content": system_text})
        for source in (params, additional):
            if output_budget is not None:
                break
            for name in ("max_output_tokens", "max_completion_tokens", "max_tokens"):
                if source.get(name) is not None:
                    output_budget = source.get(name)
                    break
        if not isinstance(messages, (list, tuple)):
            raise TypeError("Identity Relay requires an exact prepared request.")
        if output_budget is None:
            return list(messages), None
        output_budget = int(output_budget)
        if output_budget <= 0:
            raise ValueError(
                "Identity Relay requires a valid prepared-request output budget."
            )
        return list(messages), output_budget

    @staticmethod
    def exact_context_limit(provider: ProviderSelection) -> int | None:
        value = getattr(
            getattr(provider.context, "capabilities", None),
            "context_limit",
            None,
        )
        return value if type(value) is int and value > 0 else None

    @staticmethod
    def judge_output_budget(candidate_count: int) -> int:
        try:
            count = max(0, int(candidate_count))
        except (TypeError, ValueError):
            count = 0
        return max(1200, 512 + (320 * count))

    @staticmethod
    def snapshot_hash(snapshot_payload: Mapping[str, object]) -> str:
        payload = _plain(snapshot_payload)
        if not isinstance(payload, dict):
            raise TypeError("Identity Relay snapshot payload must be a mapping.")
        payload.pop("snapshot_hash", None)
        payload.pop("authorization_record_id", None)
        serialized = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(serialized).hexdigest()

    @staticmethod
    def snapshot_payload(snapshot: object) -> dict[str, object] | None:
        if snapshot is None:
            return None
        schema_version = _field(snapshot, "schema_version", 0)
        if int(schema_version or 0) != 2:
            return None
        fields = (
            "schema_version",
            "projection_kind",
            "status",
            "artifact_ref",
            "artifact_hash",
            "normalizer_revision",
            "attestation_revision",
            "transient_state",
            "effective_use_decisions",
            "kernel_record_ids",
            "prompt_text",
            "selected_record_ids",
            "selection_reasons",
            "signals_considered",
            "unresolved_record_ids",
            "trace",
            "snapshot_hash",
            "authorization_record_id",
            "persistence_mode",
            "failure_code",
        )
        return {
            name: _plain(_field(snapshot, name, None))
            for name in fields
        }

    @classmethod
    def metadata(
        cls,
        snapshot_payload: Mapping[str, object],
    ) -> dict[str, object] | None:
        if not isinstance(snapshot_payload, Mapping):
            return None
        status = str(snapshot_payload.get("status") or "")
        if status not in {"ready", "suspended"}:
            return None
        artifact_ref = str(snapshot_payload.get("artifact_ref") or "")
        artifact_hash = str(snapshot_payload.get("artifact_hash") or "")
        if not cls.ref_matches_hash(artifact_ref, artifact_hash):
            return None
        snapshot_hash = str(snapshot_payload.get("snapshot_hash") or "")
        if status == "ready":
            if len(snapshot_hash) != 64 or any(
                character not in "0123456789abcdef"
                for character in snapshot_hash
            ):
                return None
        elif snapshot_hash:
            return None
        metadata: dict[str, object] = {
            "schema_version": 2,
            "projection_kind": "normalized_projection",
            "status": status,
            "artifact_ref": artifact_ref,
            "artifact_hash": artifact_hash,
        }
        if snapshot_hash:
            metadata["snapshot_hash"] = snapshot_hash
        return metadata

    @staticmethod
    def ref_matches_hash(artifact_ref: object, artifact_hash: object) -> bool:
        digest = str(artifact_hash or "")
        return bool(
            len(digest) == 64
            and all(character in "0123456789abcdef" for character in digest)
            and str(artifact_ref or "") == f"library/{digest}.json"
        )

    def _validated_restored_snapshot(
        self,
        value: Mapping[str, object] | None,
    ) -> tuple[
        Mapping[str, object] | None,
        Mapping[str, object] | None,
        str,
    ]:
        if value is None:
            return None, None, ""
        payload = self.snapshot_payload(value)
        metadata = self.metadata(payload or {})
        if (
            payload is None
            or metadata is None
            or metadata.get("status") != "ready"
            or str(payload.get("persistence_mode") or "").strip().lower()
            != "persistent"
            or str(payload.get("snapshot_hash") or "")
            != self.snapshot_hash(payload)
        ):
            return None, None, "Persisted Identity Relay projection is invalid."
        return _freeze_mapping(payload), _freeze_mapping(metadata), ""

    @staticmethod
    def _classify_mode(snapshot: object) -> str:
        connected = _field(snapshot, "connected", _MISSING)
        enabled = _field(snapshot, "enabled", _MISSING)
        artifact_ref = _field(snapshot, "artifact_ref", _MISSING)
        artifact_hash = _field(snapshot, "artifact_hash", _MISSING)
        revision = _field(snapshot, "connection_revision", _MISSING)
        if (
            type(connected) is not bool
            or type(enabled) is not bool
            or type(revision) is not int
            or revision < 0
            or not isinstance(artifact_ref, str)
            or not isinstance(artifact_hash, str)
        ):
            return "invalid"
        if not connected:
            return (
                "unconnected"
                if not enabled and not artifact_ref and not artifact_hash
                else "invalid"
            )
        if not IdentityRelayService.ref_matches_hash(artifact_ref, artifact_hash):
            return "invalid"
        return "connected-on" if enabled else "connected-off"

    @staticmethod
    def _capture_matches_mode(capture: object, mode_snapshot: object) -> bool:
        return bool(
            capture is not None
            and _field(capture, "enabled", _MISSING) is True
            and _field(capture, "artifact_ref", _MISSING)
            == _field(mode_snapshot, "artifact_ref", _MISSING)
            and _field(capture, "artifact_hash", _MISSING)
            == _field(mode_snapshot, "artifact_hash", _MISSING)
            and _field(capture, "connection_revision", _MISSING)
            == _field(mode_snapshot, "connection_revision", _MISSING)
            and IdentityRelayService.ref_matches_hash(
                _field(capture, "artifact_ref", ""),
                _field(capture, "artifact_hash", ""),
            )
        )

    @staticmethod
    def _provider_payload(provider: ProviderSelection) -> dict[str, object]:
        context = provider.context
        summary = getattr(context, "to_summary", None)
        payload = dict(summary() or {}) if callable(summary) else {}
        provider_config = dict(getattr(context, "provider_config", {}) or {})
        provider_is_remote = provider_config.get("provider_is_remote")
        payload.update(
            {
                "provider_name": str(getattr(context, "provider_name", "") or ""),
                "model_name": str(getattr(context, "model_name", "") or ""),
                "provider_is_remote": (
                    provider_is_remote
                    if type(provider_is_remote) is bool
                    else None
                ),
                "provider_config": provider_config,
                "generation_fields": dict(
                    getattr(context, "generation_fields", {}) or {}
                ),
            }
        )
        return payload

    @staticmethod
    def _notice_from_trace(
        trace: Mapping[str, object],
    ) -> IdentityRelayNotice | None:
        value = trace.get("degradation_notice") or trace.get("persistence_notice")
        if not isinstance(value, Mapping):
            return None
        return IdentityRelayNotice(
            failure_category=str(value.get("failure_category") or ""),
            reason=str(value.get("reason") or ""),
            prominent=bool(value.get("prominent", True)),
            provider=str(value.get("provider") or ""),
            model=str(value.get("model") or ""),
            affected_record_ids=tuple(value.get("affected_record_ids") or ()),
            redaction_reason=str(value.get("redaction_reason") or ""),
        )

    def _warn_unknown_capacity(self, provider: ProviderSelection) -> None:
        key = (provider.provider_id, provider.model_id)
        with self._lock:
            if key in self._unknown_capacity_warnings:
                return
            self._unknown_capacity_warnings.add(key)
        self._log(
            "[Identity Relay/Normal Chat] Exact context limit is unavailable "
            f"for provider {provider.provider_id!r}, model {provider.model_id!r}. "
            "Exact frozen token counting remains active, but NC cannot preflight "
            "context overflow; continuing with the frozen request."
        )

    def _log(self, message: str) -> None:
        logger = self._logger
        if logger is not None:
            logger(str(message))

    def _binding_admission_failure(
        self,
        binding: _TurnBinding,
        token: CancellationToken,
        *,
        require_token: bool = False,
    ) -> CommandResult[IdentityRelayProjection] | None:
        if token.cancelled:
            return self._cancelled(token)
        with self._lock:
            current = self._bindings.get(self._key_for_lease(binding.lease))
            if (
                current is None
                or current.binding_id is not binding.binding_id
                or current.lease != binding.lease
                or current.state != binding.state
                or (require_token and current.token is not token)
            ):
                return _failure(
                    "identity_relay_turn_discarded",
                    "The Identity Relay turn binding is no longer active.",
                )
        return None

    @staticmethod
    def _cancelled(token: CancellationToken):
        return _failure(
            "identity_relay_cancelled",
            token.reason or "Identity Relay preparation was cancelled.",
        )

    @staticmethod
    def _key_for_lease(lease: WorkLease) -> tuple[int, int, str, int]:
        if lease.turn_id is None:
            raise TypeError("Identity Relay requires a turn-scoped lease.")
        return (
            lease.run_id.value,
            lease.session_generation.value
            if lease.session_generation is not None
            else 0,
            lease.turn_id.value,
            lease.route_generation.value
            if lease.route_generation is not None
            else 0,
        )

    @staticmethod
    def _key_for_state(
        state: IdentityRelayTurnState,
    ) -> tuple[int, int, str, int]:
        return (
            int(state.run_generation),
            int(state.session_generation),
            str(state.turn_id),
            int(state.route_generation),
        )


__all__ = [
    "IDENTITY_RELAY_CAPABILITY_UNAVAILABLE",
    "IdentityRelayActiveTransactionSource",
    "IdentityRelayArtifactCapabilities",
    "IdentityRelayCapturedSnapshot",
    "IdentityRelayDeletionAdmission",
    "IdentityRelayLoadedSourceRecords",
    "IdentityRelayNotice",
    "IdentityRelayPersistenceSnapshot",
    "IdentityRelayProjection",
    "IdentityRelayProviderPort",
    "IdentityRelayPurgeResult",
    "IdentityRelayService",
    "IdentityRelaySnapshotMetadata",
    "IdentityRelaySnapshotRecord",
    "IdentityRelaySnapshotRegistry",
    "IdentityRelaySnapshotSession",
    "IdentityRelaySnapshotTurn",
    "IdentityRelayTurnBinding",
]
