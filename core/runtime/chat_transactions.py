"""Typed ownership for accepted Normal Chat transactions.

The service keeps mutable lifecycle state private.  Callers exchange immutable
snapshots carrying exact work leases, so an old request can never address a
new route for the same conversational turn.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
import threading
from typing import Protocol
import uuid

from core.runtime.config import RuntimeConfigSnapshot
from core.runtime.contracts import (
    CancellationToken,
    CommandResult,
    IdentityRelayTurnState,
    RuntimeFailure,
)
from core.runtime.conversation import AcceptedTurn, AssistantCommit, ConversationMessage
from core.runtime.identifiers import TurnId, WorkLease
from core.runtime.identity_relay import (
    IdentityRelayProjection,
    IdentityRelayTurnBinding,
)
from core.runtime.lifecycle import WorkerHandle
from core.runtime.prompt_assembly import PromptRequest
from core.runtime.providers import FrozenTurnRequest, ProviderSelection
from core.runtime.turns import TurnSnapshot, TurnTerminalStatus, UserInput
from core.runtime.visual import (
    normalize_persona_appearance_freedom,
    persona_visual_identity_available,
    resolve_persona_visual_reply_policy,
    user_visual_identity_available,
    visual_generation_instruction,
)
from addons.visual_reply.comfyui_prompting import rules_for_config
from core.runtime.continuous_next_reply import ContinuousStageBinding


class NormalChatTransactionStatus(str, Enum):
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"
    SUPERSEDED = "superseded"
    FAILED = "failed"


_TERMINAL_STATUSES = frozenset(
    {
        NormalChatTransactionStatus.COMPLETED,
        NormalChatTransactionStatus.CANCELED,
        NormalChatTransactionStatus.INTERRUPTED,
        NormalChatTransactionStatus.SUPERSEDED,
        NormalChatTransactionStatus.FAILED,
    }
)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    return value


def _freeze_mapping(value: Mapping[str, object] | None) -> Mapping[str, object]:
    return _freeze(dict(value or {}))  # type: ignore[return-value]


def _freeze_optional_mapping(
    value: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    return None if value is None else _freeze_mapping(value)


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, frozenset):
        return {_thaw(item) for item in value}
    return value


@dataclass(frozen=True, slots=True)
class NormalChatPersonaSnapshot:
    """Persona and prompt policy frozen at accepted-turn time."""

    values: Mapping[str, object]

    def __post_init__(self) -> None:
        values = dict(self.values or {})
        values["_accepted_turn_frozen"] = True
        object.__setattr__(self, "values", _freeze_mapping(values))

    @classmethod
    def from_config(
        cls,
        config: RuntimeConfigSnapshot,
        overrides: Mapping[str, object] | None = None,
    ) -> NormalChatPersonaSnapshot:
        values = config.values
        captured = {
            "active_quick_persona_id": str(values.get("active_quick_persona_id", "") or ""),
            "persona_mood_tags": dict(values.get("persona_mood_tags") or {}),
            "active_preset_name": str(values.get("active_preset_name", "") or ""),
            "emotional_instructions": str(
                values.get("emotional_instructions", "") or ""
            ),
            "system_prompt": str(values.get("system_prompt", "") or ""),
            "persona_prompt_type": str(values.get("persona_prompt_type", "") or ""),
            "model_name": str(values.get("model_name", "") or ""),
            "active_quick_persona_name": str(
                values.get("active_quick_persona_name", "") or ""
            ),
            "persona_visual_identity_prompt": str(
                values.get("persona_visual_identity_prompt", "") or ""
            ),
            "persona_visual_reference_path": str(
                values.get("persona_visual_reference_path", "") or ""
            ),
            "persona_self_image_mode": str(
                values.get("persona_self_image_mode", "hybrid") or "hybrid"
            ),
            "persona_appearance_freedom": normalize_persona_appearance_freedom(
                values.get("persona_appearance_freedom")
            ),
            "persona_visual_reference_strength": values.get(
                "persona_visual_reference_strength", 0.75
            ),
            "user_identity_enabled": bool(
                values.get("user_identity_enabled", False)
            ),
            "user_identity_name": str(
                values.get("user_identity_name", "") or ""
            ),
            "user_identity_visual_identity_prompt": str(
                values.get("user_identity_visual_identity_prompt", "") or ""
            ),
            "user_identity_visual_reference_path": str(
                values.get("user_identity_visual_reference_path", "") or ""
            ),
            "user_identity_visual_policy": str(
                values.get("user_identity_visual_policy", "requested")
                or "requested"
            ),
            "user_identity_visual_reference_strength": values.get(
                "user_identity_visual_reference_strength", 0.52
            ),
        }
        visual_policy = resolve_persona_visual_reply_policy(values)
        visual_enabled = bool(values.get("visual_replies_enabled", True)) and (
            str(values.get("visual_reply_mode", "off") or "off").strip().lower()
            != "off"
        )
        captured.update(
            {
                "visual_reply_policy": visual_policy,
                "visual_reply_instruction": visual_generation_instruction(
                    enabled=visual_enabled and visual_policy != "off",
                    automatic_allowed=visual_policy == "spontaneous",
                    persona_identity_available=persona_visual_identity_available(values),
                    user_identity_available=user_visual_identity_available(values),
                    user_visual_policy=str(
                        values.get("user_identity_visual_policy", "requested")
                        or "requested"
                    ),
                    comfyui_rules=rules_for_config(values),
                ),
            }
        )
        captured.update(dict(overrides or {}))
        from core.provider_prompt_rules import resolve_rules
        rule_config = dict(values)
        rule_config.update(dict(overrides or {}))
        captured['emotional_instructions'] = resolve_rules(rule_config)
        return cls(captured)


@dataclass(frozen=True, slots=True)
class NormalChatAcceptance:
    """One input and all caller-owned state captured at its acceptance boundary."""

    content: str
    role: str = "user"
    metadata: Mapping[str, object] = field(default_factory=dict)
    source: str = "typed"
    persist_user_turn: bool = True
    source_lease: WorkLease | None = None
    persona: NormalChatPersonaSnapshot | None = None
    persona_overrides: Mapping[str, object] = field(default_factory=dict)
    relay_query_state: Mapping[str, object] = field(default_factory=dict)
    memory_work_context: object = None
    restored_relay_snapshot: Mapping[str, object] | None = None
    identity_relay_mode: str = "current"
    history_anchor_index: int | None = None
    expected_history_revision: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", str(self.content or ""))
        object.__setattr__(self, "role", str(self.role or "user"))
        object.__setattr__(self, "source", str(self.source or "typed"))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(
            self,
            "persona_overrides",
            _freeze_mapping(self.persona_overrides),
        )
        object.__setattr__(
            self,
            "relay_query_state",
            _freeze_mapping(self.relay_query_state),
        )
        object.__setattr__(
            self,
            "restored_relay_snapshot",
            _freeze_optional_mapping(self.restored_relay_snapshot),
        )
        object.__setattr__(
            self,
            "identity_relay_mode",
            str(self.identity_relay_mode or "current"),
        )


@dataclass(frozen=True, slots=True)
class NormalChatAcceptedTurnSnapshot:
    transaction_id: str
    source_transaction_id: str | None
    turn: TurnSnapshot
    role: str
    content: str
    metadata: Mapping[str, object]
    persist_user_turn: bool
    persona: NormalChatPersonaSnapshot
    relay_query_state: Mapping[str, object]
    memory_work_context: object
    relay_binding: IdentityRelayTurnBinding
    history_anchor_index: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(
            self,
            "relay_query_state",
            _freeze_mapping(self.relay_query_state),
        )

    @property
    def lease(self) -> WorkLease:
        return self.turn.lease

    @property
    def config(self) -> RuntimeConfigSnapshot:
        return self.turn.config

    @property
    def accepted_provider(self) -> ProviderSelection:
        return self.turn.provider

    @property
    def identity_relay(self) -> IdentityRelayTurnState:
        return self.turn.identity_relay

    def message_mapping(self) -> Mapping[str, object]:
        return _freeze_mapping(
            {
                "role": self.role,
                "content": self.content,
                **dict(self.metadata),
                "normal_chat_transaction_id": self.transaction_id,
            }
        )


@dataclass(frozen=True, slots=True)
class NormalChatRequestSnapshot:
    request_id: str
    transaction_id: str
    lease: WorkLease
    history: tuple[Mapping[str, object], ...]
    request_only_continue_cue: bool
    relay_query: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "history",
            tuple(_freeze_mapping(item) for item in self.history),
        )
        object.__setattr__(self, "relay_query", _freeze_mapping(self.relay_query))


@dataclass(frozen=True, slots=True)
class NormalChatPreparationSnapshot:
    accepted: NormalChatAcceptedTurnSnapshot
    request: NormalChatRequestSnapshot
    provider: ProviderSelection
    relay_projection: IdentityRelayProjection


@dataclass(frozen=True, slots=True)
class NormalChatDispatchClaim:
    transaction_id: str
    request_id: str
    lease: WorkLease
    sequence: int
    kind: str
    provider_request_identity: int
    selected_request: FrozenTurnRequest | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class PreparedDetachedNormalChatRequest:
    request: FrozenTurnRequest
    document_free_request: FrozenTurnRequest | None = None
    document_tickets: tuple[object, ...] = field(default=(), repr=False, compare=False)

    def select_for_dispatch(self) -> FrozenTurnRequest:
        # Ephemeral capabilities live until the actual provider dispatch boundary.
        if self.document_tickets and any(not ticket.current() for ticket in self.document_tickets):
            if self.document_free_request is None:
                raise RuntimeError('Detached document-free request is unavailable.')
            return self.document_free_request
        return self.request


@dataclass(frozen=True, slots=True)
class PreparedNormalChatRequest:
    transaction_id: str
    request_id: str
    lease: WorkLease
    provider: ProviderSelection
    request: FrozenTurnRequest


@dataclass(frozen=True, slots=True)
class NormalChatRegenerationSource:
    transaction_id: str
    turn_id: TurnId
    role: str
    content: str
    metadata: Mapping[str, object]
    persist_user_turn: bool
    identity_relay_enabled: bool
    relay_snapshot: Mapping[str, object] | None
    relay_metadata: Mapping[str, object] | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))
        object.__setattr__(
            self,
            "relay_snapshot",
            _freeze_optional_mapping(self.relay_snapshot),
        )
        object.__setattr__(
            self,
            "relay_metadata",
            _freeze_optional_mapping(self.relay_metadata),
        )


@dataclass(frozen=True, slots=True)
class NormalChatTerminalReceipt:
    transaction_id: str
    lease: WorkLease
    status: NormalChatTransactionStatus
    reason: str
    cleanup_count: int
    regeneration_source: NormalChatRegenerationSource | None = None


@dataclass(frozen=True, slots=True)
class NormalChatCommitReceipt:
    assistant: AssistantCommit
    terminal: NormalChatTerminalReceipt


@dataclass(frozen=True, slots=True)
class NormalChatTransactionSnapshot:
    accepted: NormalChatAcceptedTurnSnapshot
    status: NormalChatTransactionStatus
    request: NormalChatRequestSnapshot | None
    provider: ProviderSelection
    relay_snapshot: Mapping[str, object] | None
    relay_metadata: Mapping[str, object] | None
    relay_notice: object
    relay_trace: Mapping[str, object]
    prepared: PreparedNormalChatRequest | None
    dispatch_claims: tuple[NormalChatDispatchClaim, ...]
    worker_started: bool
    worker_ready: bool
    history_committed: bool
    error: RuntimeFailure | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "relay_snapshot",
            _freeze_optional_mapping(self.relay_snapshot),
        )
        object.__setattr__(
            self,
            "relay_metadata",
            _freeze_optional_mapping(self.relay_metadata),
        )
        object.__setattr__(self, "relay_trace", _freeze_mapping(self.relay_trace))

    @property
    def transaction_id(self) -> str:
        return self.accepted.transaction_id

    @property
    def lease(self) -> WorkLease:
        return self.accepted.lease


class NormalChatTurnPort(Protocol):
    def accept(self, completed_input: UserInput) -> CommandResult[TurnSnapshot]: ...

    def regenerate(self, *, source_turn_id: TurnId | None = None) -> CommandResult[TurnSnapshot]: ...

    def snapshot(self, turn_id: TurnId) -> TurnSnapshot | None: ...

    def cancel(
        self,
        turn_id: TurnId,
        reason: str,
        *,
        lease: WorkLease,
    ) -> CommandResult[None]: ...

    def finish(
        self,
        turn_id: TurnId,
        status: TurnTerminalStatus,
        *,
        lease: WorkLease,
    ) -> CommandResult[None]: ...

    def complete_provider(
        self,
        turn_id: TurnId,
        text: str,
        *,
        metadata: Mapping[str, object] | None = None,
        lease: WorkLease,
    ) -> CommandResult[AssistantCommit]: ...


class NormalChatConversationPort(Protocol):
    def session_lease_is_current(self, lease: WorkLease) -> bool: ...

    def edit_message(
        self,
        message_id: str | TurnId,
        *,
        role: str | None = None,
        content: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> object: ...

    def publish_accepted_turn(
        self,
        lease: WorkLease,
        *,
        role: str,
        content: str,
        metadata: Mapping[str, object],
        replace_index: int | None = None,
    ) -> CommandResult[ConversationMessage]: ...

    def rollback_assistant_commit(
        self,
        lease: WorkLease,
        commit: AssistantCommit,
    ) -> bool: ...


class NormalChatProviderPort(Protocol):
    def prepare(
        self,
        selection: ProviderSelection,
        request: PromptRequest,
    ) -> FrozenTurnRequest: ...

    def frozen_execution_available(
        self,
        selection: ProviderSelection,
        *,
        stream: bool = False,
    ) -> bool: ...

    def prepare_model(
        self,
        selection: ProviderSelection,
        *,
        reason: str,
        force_unload: bool = False,
    ) -> bool: ...


class NormalChatIdentityRelayPort(Protocol):
    def acceptance(
        self,
        *,
        restored_snapshot: Mapping[str, object] | None = None,
        mode: str = "current",
    ) -> AbstractContextManager[None]: ...

    def binding_for(
        self,
        state: IdentityRelayTurnState,
    ) -> IdentityRelayTurnBinding | None: ...

    def bind_request(
        self,
        state: IdentityRelayTurnState,
        query: Mapping[str, object],
    ) -> CommandResult[None]: ...

    def prepare(
        self,
        state: IdentityRelayTurnState,
        token: CancellationToken,
    ) -> CommandResult[IdentityRelayProjection]: ...

    def validate_prepared_request(
        self,
        state: IdentityRelayTurnState,
        request: FrozenTurnRequest,
    ) -> CommandResult[object]: ...

    def discard_turn(
        self,
        turn_id: TurnId,
        *,
        lease: WorkLease | None = None,
    ) -> None: ...


class NormalChatWorkerPort(Protocol):
    def spawn(
        self,
        *,
        name: str,
        lease: WorkLease,
        target: Callable[[CancellationToken], None],
        daemon: bool = True,
        on_cancel: Callable[[str], None] | None = None,
        identity: object = None,
        owner_token: object = None,
    ) -> WorkerHandle: ...


class NormalChatRequestAssembler(Protocol):
    """Composition-owned typed adapter from frozen turn state to a prompt."""

    def build(self, state: NormalChatPreparationSnapshot) -> PromptRequest: ...


@dataclass(slots=True)
class _TransactionEntry:
    accepted: NormalChatAcceptedTurnSnapshot
    status: NormalChatTransactionStatus = NormalChatTransactionStatus.ACCEPTED
    request: NormalChatRequestSnapshot | None = None
    provider: ProviderSelection | None = None
    relay_projection: IdentityRelayProjection | None = None
    prepared_request: FrozenTurnRequest | None = None
    document_free_request: FrozenTurnRequest | None = None
    document_tickets: tuple[object, ...] = ()
    document_revoked: bool = False
    dispatch_claims: list[NormalChatDispatchClaim] = field(default_factory=list)
    worker_started: bool = False
    worker_handle: WorkerHandle | None = None
    history_committed: bool = False
    error: RuntimeFailure | None = None
    ready: threading.Event = field(default_factory=threading.Event)


class NormalChatTransactionService:
    """Own Normal Chat transaction identity, preparation, and termination."""

    def __init__(
        self,
        *,
        conversation: NormalChatConversationPort,
        turns: NormalChatTurnPort,
        providers: NormalChatProviderPort,
        identity_relay: NormalChatIdentityRelayPort,
        workers: NormalChatWorkerPort,
        assembler: NormalChatRequestAssembler,
    ) -> None:
        self._conversation = conversation
        self._turns = turns
        self._providers = providers
        self._identity_relay = identity_relay
        self._workers = workers
        self._assembler = assembler
        self._lock = threading.RLock()
        self._transition_lock = threading.RLock()
        self._entries: dict[str, _TransactionEntry] = {}
        self._terminal_receipts: dict[str, NormalChatTerminalReceipt] = {}
        self._regeneration_sources: dict[str, NormalChatRegenerationSource] = {}

    def begin(
        self,
        acceptance: NormalChatAcceptance,
        *,
        accepted_turn: TurnSnapshot | None = None,
    ) -> CommandResult[NormalChatTransactionSnapshot]:
        return self._begin(
            acceptance,
            accepted_turn=accepted_turn,
            regenerate=False,
            source_transaction_id=None,
        )

    def prepare_detached(
        self,
        proposed_user: Mapping[str, object],
        binding: ContinuousStageBinding,
        token: CancellationToken,
        *,
        stage_id: str | None = None,
        memory_work_context: object = None,
    ) -> PreparedDetachedNormalChatRequest | None:
        """Build the next provider request without accepting or publishing a turn.

        Continuous Mode alone uses this read-only path. A live Relay projection
        needs an accepted turn, so that case falls back to ordinary generation.
        """
        text = str(proposed_user.get("content") or "").strip()
        if not text or token.cancelled or len(text) > 8000:
            return None
        allowed = getattr(self._identity_relay, "detached_staging_allowed", None)
        if not callable(allowed) or not allowed():
            return None
        before = self._conversation.snapshot()
        if (before.session_generation.value != binding.session_generation
                or before.revision != binding.conversation_revision
                or not before.messages or before.messages[-1].message_id != binding.source_turn_id):
            return None
        captured = getattr(self._turns, "capture_detached_selection", None)
        if not callable(captured):
            return None
        config, provider = captured()
        if (provider.provider_id != binding.provider_id or provider.model_id != binding.model_id
                or not self._providers.frozen_execution_available(provider)):
            return None
        if provider.provider_id == "lmstudio" and config.values.get("companion_orb_enabled"):
            return None  # Conversational tools require an admitted turn and may have effects.
        has_lifecycle = getattr(provider.context, 'model_lifecycle_available', False)
        if (provider.provider_id == "lmstudio" or has_lifecycle) and not self._providers.prepare_model(
                provider, reason="Continuous next reply", force_unload=False,
                **({'cancel_token': token} if has_lifecycle else {})):
            return None
        stage_id = stage_id or uuid.uuid4().hex
        lease = self._conversation.session_lease()
        turn_id = TurnId(stage_id)
        metadata = {str(key): value for key, value in proposed_user.items()
                    if key not in {"content", "role", "normal_chat_transaction_id"}}
        metadata["normal_chat_transaction_id"] = stage_id
        relay_state = IdentityRelayTurnState(
            enabled=False, artifact_ref=None, connection_revision=0, subject_kind=None,
            artifact_revision=None, owner_override=False, provider_id=provider.provider_id,
            model_id=provider.model_id, run_generation=lease.run_id.value,
            session_generation=before.session_generation.value, turn_id=stage_id)
        turn = TurnSnapshot(lease, AcceptedTurn(turn_id, lease,
            ConversationMessage(stage_id, "user", text, metadata)), config, provider,
            relay_state, token)
        accepted = NormalChatAcceptedTurnSnapshot(
            stage_id, None, turn, "user", text, metadata, True,
            NormalChatPersonaSnapshot.from_config(config), {}, memory_work_context,
            IdentityRelayTurnBinding(relay_state, provider))
        request = NormalChatRequestSnapshot(stage_id, stage_id, lease,
            tuple(self._conversation.message_mappings()) + (accepted.message_mapping(),), False, {})
        state = NormalChatPreparationSnapshot(accepted, request, provider,
            IdentityRelayProjection("off", provider))
        prompt = self._assembler.build(state)
        if not isinstance(prompt, PromptRequest) or token.cancelled:
            return None
        prepared = self._providers.prepare(provider, prompt)
        from core.runtime.document_context import DocumentContextTicket
        tickets = tuple(message.document_ticket for message in prompt.messages
                        if isinstance(message.document_ticket, DocumentContextTicket))
        document_free = (self._providers.prepare(provider, prompt.without_document_context())
                         if tickets else None)
        after = self._conversation.snapshot()
        if (token.cancelled or after.session_generation != before.session_generation
                or after.revision != before.revision):
            return None
        return PreparedDetachedNormalChatRequest(prepared, document_free, tickets)

    def regenerate(
        self,
        source_transaction_id: str,
        *,
        persona: NormalChatPersonaSnapshot | None = None,
        persona_overrides: Mapping[str, object] | None = None,
        relay_query_state: Mapping[str, object] | None = None,
        memory_work_context: object = None,
        history_anchor_index: int | None = None,
        expected_target=None,
    ) -> CommandResult[NormalChatTransactionSnapshot]:
        source_id = str(source_transaction_id or "")
        with self._transition_lock:
            with self._lock:
                entry = self._entries.get(source_id)
                source = (
                    self._source_for_entry(entry)
                    if entry is not None
                    else self._regeneration_sources.get(source_id)
                )
            if source is None:
                return _failure(
                    "regeneration_source_missing",
                    "The requested Normal Chat regeneration source is unavailable.",
                )
            relay_enabled = source.identity_relay_enabled
            if relay_enabled and source.relay_snapshot is None:
                return _failure(
                    "regeneration_relay_snapshot_missing",
                    "The regeneration source has no exact persisted Relay snapshot.",
                )
            # Volatile projections may be reused only by recapturing the still-
            # connected identity; passing one through the persisted restore path
            # would both violate its policy and fail snapshot validation.
            restored_relay_snapshot = _persistent_relay_snapshot(
                source.relay_snapshot
            )
            metadata = dict(source.metadata)
            metadata.pop("normal_chat_transaction_id", None)
            acceptance = NormalChatAcceptance(
                source.content,
                role=source.role,
                metadata=metadata,
                source="regenerate",
                persist_user_turn=source.persist_user_turn,
                persona=persona,
                persona_overrides=dict(persona_overrides or {}),
                relay_query_state=dict(relay_query_state or {}),
                memory_work_context=memory_work_context,
                restored_relay_snapshot=restored_relay_snapshot,
                identity_relay_mode="current" if relay_enabled else "off",
                history_anchor_index=history_anchor_index,
            )
            result = self._begin(
                acceptance,
                accepted_turn=None,
                regenerate=True,
                source_transaction_id=source_id,
                source_turn_id=source.turn_id,
                expected_target=expected_target,
            )
            if (
                result.accepted
                and result.value is not None
                and result.value.accepted.turn.accepted_turn.turn_id != source.turn_id
            ):
                self.cancel(
                    result.value,
                    reason="regeneration_source_changed",
                )
                return _failure(
                    "regeneration_source_changed",
                    "The conversation regeneration source changed during acceptance.",
                )
            if result.accepted:
                self._retire_superseded_source(source_id)
            return result

    def freeze_request(
        self,
        transaction: str | NormalChatTransactionSnapshot,
        history: Sequence[Mapping[str, object]],
        *,
        request_only_continue_cue: bool = False,
        relay_query: Mapping[str, object] | None = None,
    ) -> CommandResult[NormalChatRequestSnapshot]:
        transaction_id = _transaction_id(transaction)
        with self._transition_lock:
            with self._lock:
                entry = self._entries.get(transaction_id)
                current_failure = self._current_failure_locked(entry)
                if current_failure is not None:
                    return CommandResult(False, failure=current_failure)
                assert entry is not None
                if entry.request is not None:
                    if entry.request.request_only_continue_cue != bool(
                        request_only_continue_cue
                    ):
                        return _failure(
                            "request_semantics_changed",
                            "A frozen Normal Chat request cannot change continuation semantics.",
                        )
                    return CommandResult(True, value=entry.request)
                query = _freeze_mapping(
                    relay_query
                    if relay_query is not None
                    else entry.accepted.relay_query_state
                )
                frozen_history = tuple(history)
                accepted = entry.accepted
                represented = any(
                    str(item.get("normal_chat_transaction_id") or "")
                    == transaction_id
                    for item in frozen_history
                ) or accepted.history_anchor_index is not None
                if accepted.persist_user_turn and not represented:
                    frozen_history += (accepted.message_mapping(),)
                request = NormalChatRequestSnapshot(
                    request_id=uuid.uuid4().hex,
                    transaction_id=transaction_id,
                    lease=entry.accepted.lease,
                    history=frozen_history,
                    request_only_continue_cue=bool(request_only_continue_cue),
                    relay_query=query,
                )
                bound = self._identity_relay.bind_request(
                    entry.accepted.identity_relay,
                    query,
                )
                if not bound.accepted:
                    return CommandResult(False, failure=bound.failure)
                if self._entries.get(transaction_id) is not entry:
                    return _failure(
                        "superseded_transaction",
                        "The Normal Chat transaction changed during request freeze.",
                    )
                entry.request = request
                return CommandResult(True, value=request)

    def start_preparation(
        self,
        request: NormalChatRequestSnapshot,
    ) -> CommandResult[WorkerHandle | None]:
        with self._transition_lock:
            with self._lock:
                entry, failure = self._entry_for_request_locked(request)
                if failure is not None:
                    return CommandResult(False, failure=failure)
                assert entry is not None
                if entry.prepared_request is not None:
                    return CommandResult(True, value=entry.worker_handle)
                if entry.worker_started:
                    return CommandResult(True, value=entry.worker_handle)
                entry.worker_started = True
                entry.status = NormalChatTransactionStatus.PREPARING
                entry.error = None
                entry.ready.clear()
                request_token = entry.accepted.turn.cancellation
            try:
                handle = self._workers.spawn(
                    name="nc-normal-chat-transaction",
                    lease=request.lease,
                    target=lambda supervisor_token: self._prepare_worker(
                        request,
                        supervisor_token,
                    ),
                    on_cancel=lambda reason: request_token.cancel(reason),
                    identity=(
                        "normal_chat",
                        request.transaction_id,
                        request.lease.route_generation,
                    ),
                    owner_token=self,
                )
            except BaseException as exc:
                failure = RuntimeFailure(
                    "transaction_worker_start_failed",
                    str(exc) or "Normal Chat preparation worker could not start.",
                    exc,
                )
                self._block(request, failure)
                return CommandResult(False, failure=failure)
            with self._lock:
                current = self._entries.get(request.transaction_id)
                if current is entry and current.request == request:
                    current.worker_handle = handle
            return CommandResult(True, value=handle)

    def ensure_ready(
        self,
        request: NormalChatRequestSnapshot,
        *,
        timeout: float | None = None,
    ) -> CommandResult[PreparedNormalChatRequest]:
        started = self.start_preparation(request)
        if not started.accepted:
            return CommandResult(False, failure=started.failure)
        with self._lock:
            entry, failure = self._entry_for_request_locked(request)
            if failure is not None:
                return CommandResult(False, failure=failure)
            assert entry is not None
            ready = entry.ready
        if not ready.wait(timeout):
            return _failure(
                "transaction_prepare_timeout",
                "Normal Chat request preparation did not finish before the deadline.",
            )
        with self._lock:
            entry, failure = self._entry_for_request_locked(request)
            if failure is not None:
                return CommandResult(False, failure=failure)
            assert entry is not None
            if entry.error is not None:
                return CommandResult(False, failure=entry.error)
            if entry.prepared_request is None or entry.provider is None:
                return _failure(
                    "transaction_prepare_failed",
                    "Normal Chat request preparation did not publish a request.",
                )
            return CommandResult(
                True,
                value=PreparedNormalChatRequest(
                    request.transaction_id,
                    request.request_id,
                    request.lease,
                    entry.provider,
                    entry.prepared_request,
                ),
            )

    def claim_dispatch(
        self,
        request: NormalChatRequestSnapshot,
        provider_request: FrozenTurnRequest,
        *,
        kind: str,
    ) -> CommandResult[NormalChatDispatchClaim]:
        with self._lock:
            entry, failure = self._entry_for_request_locked(request)
            if failure is not None:
                return CommandResult(False, failure=failure)
            assert entry is not None
            if entry.status is not NormalChatTransactionStatus.READY:
                return _failure(
                    "transaction_not_ready",
                    "Normal Chat provider dispatch requires a ready transaction.",
                )
            if entry.prepared_request is not provider_request:
                return _failure(
                    "prepared_request_mismatch",
                    "Provider dispatch does not own the transaction's prepared request.",
                )
            selected = None
            if entry.document_tickets:
                entry.document_revoked = entry.document_revoked or any(not ticket.current() for ticket in entry.document_tickets)
                selected = entry.document_free_request if entry.document_revoked else provider_request
            claim = NormalChatDispatchClaim(
                request.transaction_id,
                request.request_id,
                request.lease,
                len(entry.dispatch_claims) + 1,
                str(kind or "provider"),
                id(provider_request),
                selected,
            )
            entry.dispatch_claims.append(claim)
            return CommandResult(True, value=claim)

    def finish(
        self,
        request: NormalChatRequestSnapshot,
        status: TurnTerminalStatus,
        *,
        reason: str = "",
    ) -> CommandResult[NormalChatTerminalReceipt]:
        if not isinstance(status, TurnTerminalStatus):
            return _failure("invalid_terminal_status", "Unknown turn terminal status.")
        with self._transition_lock:
            with self._lock:
                entry, failure = self._entry_for_request_locked(request)
                if failure is not None:
                    return CommandResult(False, failure=failure)
                assert entry is not None
            result = self._turns.finish(
                entry.accepted.turn.accepted_turn.turn_id,
                status,
                lease=request.lease,
            )
            if not result.accepted:
                self._cleanup(
                    entry,
                    NormalChatTransactionStatus.SUPERSEDED,
                    _failure_message(result.failure, "stale_completion"),
                    retain_source=False,
                )
                return CommandResult(False, failure=result.failure)
            terminal_status = _transaction_status(status)
            receipt = self._cleanup(
                entry,
                terminal_status,
                str(reason or status.value),
                retain_source=status is TurnTerminalStatus.COMPLETED,
            )
            return CommandResult(True, value=receipt)

    def commit_assistant(
        self,
        request: NormalChatRequestSnapshot,
        content: str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[NormalChatCommitReceipt]:
        """Commit and terminalize one exact prepared route as one transaction."""

        with self._transition_lock:
            with self._lock:
                entry, failure = self._entry_for_request_locked(request)
                if failure is not None:
                    return CommandResult(False, failure=failure)
                assert entry is not None
                if entry.status is not NormalChatTransactionStatus.READY:
                    return _failure(
                        "transaction_not_ready",
                        "Assistant commit requires a ready Normal Chat transaction.",
                    )
            committed = self._turns.complete_provider(
                entry.accepted.turn.accepted_turn.turn_id,
                str(content or ""),
                metadata=dict(metadata or {}),
                lease=request.lease,
            )
            if not committed.accepted or committed.value is None:
                self._cleanup(
                    entry,
                    NormalChatTransactionStatus.SUPERSEDED,
                    _failure_message(committed.failure, "stale_completion"),
                    retain_source=False,
                )
                return CommandResult(False, failure=committed.failure)
            terminal = self._turns.finish(
                entry.accepted.turn.accepted_turn.turn_id,
                TurnTerminalStatus.COMPLETED,
                lease=request.lease,
            )
            if not terminal.accepted:
                self._conversation.rollback_assistant_commit(
                    request.lease,
                    committed.value,
                )
                self._cleanup(
                    entry,
                    NormalChatTransactionStatus.SUPERSEDED,
                    _failure_message(terminal.failure, "stale_completion"),
                    retain_source=False,
                )
                return CommandResult(False, failure=terminal.failure)
            receipt = self._cleanup(
                entry,
                NormalChatTransactionStatus.COMPLETED,
                TurnTerminalStatus.COMPLETED.value,
                retain_source=True,
            )
            return CommandResult(
                True,
                value=NormalChatCommitReceipt(committed.value, receipt),
            )

    def publish_assistant(
        self,
        request: NormalChatRequestSnapshot,
        content: str,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> CommandResult[AssistantCommit]:
        """Publish assistant history while retaining the live turn for speech.

        Normal Chat playback uses the accepted turn lease.  Terminalizing that
        turn at the history publication boundary makes queued audio stale before
        playback can consume it, so application-driven chat keeps the transaction
        ready until its speech route has finished.
        """

        with self._transition_lock:
            with self._lock:
                entry, failure = self._entry_for_request_locked(request)
                if failure is not None:
                    return CommandResult(False, failure=failure)
                assert entry is not None
                if entry.status is not NormalChatTransactionStatus.READY:
                    return _failure(
                        "transaction_not_ready",
                        "Assistant publication requires a ready Normal Chat transaction.",
                    )
            published = self._turns.complete_provider(
                entry.accepted.turn.accepted_turn.turn_id,
                str(content or ""),
                metadata=dict(metadata or {}),
                lease=request.lease,
            )
            if not published.accepted or published.value is None:
                self._cleanup(
                    entry,
                    NormalChatTransactionStatus.SUPERSEDED,
                    _failure_message(published.failure, "stale_completion"),
                    retain_source=False,
                )
                return CommandResult(False, failure=published.failure)
            return CommandResult(True, value=published.value)

    def cancel(
        self,
        transaction: str | NormalChatRequestSnapshot | NormalChatTransactionSnapshot,
        *,
        reason: str = "cancelled",
    ) -> CommandResult[NormalChatTerminalReceipt]:
        transaction_id = _transaction_id(transaction)
        with self._transition_lock:
            with self._lock:
                entry = self._entries.get(transaction_id)
                if entry is None:
                    return _missing_or_terminal_failure(
                        transaction_id,
                        self._terminal_receipts,
                    )
            result = self._turns.cancel(
                entry.accepted.turn.accepted_turn.turn_id,
                str(reason or "cancelled"),
                lease=entry.accepted.lease,
            )
            status = (
                NormalChatTransactionStatus.CANCELED
                if result.accepted
                else NormalChatTransactionStatus.SUPERSEDED
            )
            receipt = self._cleanup(
                entry,
                status,
                str(reason or "cancelled"),
                retain_source=False,
            )
            if not result.accepted:
                return CommandResult(False, failure=result.failure)
            return CommandResult(True, value=receipt)

    def invalidate_all(
        self,
        reason: str,
    ) -> tuple[NormalChatTerminalReceipt, ...]:
        with self._transition_lock:
            with self._lock:
                entries = tuple(self._entries.values())
            receipts = []
            for entry in entries:
                self._turns.cancel(
                    entry.accepted.turn.accepted_turn.turn_id,
                    str(reason or "invalidated"),
                    lease=entry.accepted.lease,
                )
                receipts.append(
                    self._cleanup(
                        entry,
                        NormalChatTransactionStatus.SUPERSEDED,
                        str(reason or "invalidated"),
                        retain_source=False,
                    )
                )
            return tuple(receipts)

    def prune_stale(self, reason: str = "stale_runtime") -> tuple[str, ...]:
        with self._transition_lock:
            with self._lock:
                stale = tuple(
                    entry
                    for entry in self._entries.values()
                    if self._current_failure_locked(entry) is not None
                )
            for entry in stale:
                self._cleanup(
                    entry,
                    NormalChatTransactionStatus.SUPERSEDED,
                    str(reason or "stale_runtime"),
                    retain_source=False,
                )
            return tuple(entry.accepted.transaction_id for entry in stale)

    def snapshot(
        self,
        transaction: str | NormalChatRequestSnapshot | NormalChatTransactionSnapshot,
    ) -> NormalChatTransactionSnapshot | None:
        transaction_id = _transaction_id(transaction)
        with self._lock:
            entry = self._entries.get(transaction_id)
            return self._snapshot_locked(entry) if entry is not None else None

    def snapshots(self) -> tuple[NormalChatTransactionSnapshot, ...]:
        with self._lock:
            return tuple(self._snapshot_locked(entry) for entry in self._entries.values())

    def terminal_receipt(self, transaction_id: str) -> NormalChatTerminalReceipt | None:
        with self._lock:
            return self._terminal_receipts.get(str(transaction_id or ""))

    def regeneration_source(
        self,
        transaction_id: str,
    ) -> NormalChatRegenerationSource | None:
        with self._lock:
            return self._regeneration_sources.get(str(transaction_id or ""))

    def cancellation_token(
        self,
        transaction: str | NormalChatRequestSnapshot | NormalChatTransactionSnapshot,
    ) -> CancellationToken | None:
        transaction_id = _transaction_id(transaction)
        with self._lock:
            entry = self._entries.get(transaction_id)
            return entry.accepted.turn.cancellation if entry is not None else None

    def _begin(
        self,
        acceptance: NormalChatAcceptance,
        *,
        accepted_turn: TurnSnapshot | None,
        regenerate: bool,
        source_transaction_id: str | None,
        source_turn_id: TurnId | None = None,
        expected_target=None,
    ) -> CommandResult[NormalChatTransactionSnapshot]:
        if not isinstance(acceptance, NormalChatAcceptance):
            return _failure(
                "acceptance_invalid",
                "Normal Chat transactions require NormalChatAcceptance.",
            )
        with self._transition_lock:
            if accepted_turn is not None:
                if regenerate:
                    return _failure(
                        "regeneration_snapshot_invalid",
                        "Regeneration cannot adopt an existing accepted-turn snapshot.",
                    )
                if not self._turn_snapshot_is_current(accepted_turn):
                    return _failure(
                        "accepted_turn_stale",
                        "The adopted accepted turn is no longer current.",
                    )
                accepted_result = CommandResult(True, value=accepted_turn)
            else:
                try:
                    with self._identity_relay.acceptance(
                        restored_snapshot=acceptance.restored_relay_snapshot,
                        mode=acceptance.identity_relay_mode,
                    ):
                        accepted_result = (
                            self._turns.regenerate(source_turn_id=source_turn_id,
                                **({'expected_target': expected_target} if expected_target is not None else {}))
                            if regenerate
                            else self._turns.accept(
                                UserInput.completed(
                                    acceptance.content,
                                    role=acceptance.role,
                                    metadata=dict(acceptance.metadata),
                                    source=acceptance.source,
                                    persist=False,
                                    source_lease=acceptance.source_lease,
                                    expected_history_revision=acceptance.expected_history_revision,
                                )
                            )
                        )
                except BaseException as exc:
                    return _failure(
                        "turn_acceptance_failed",
                        str(exc) or "Normal Chat turn acceptance failed.",
                        exc,
                    )
            if not accepted_result.accepted or accepted_result.value is None:
                return CommandResult(False, failure=accepted_result.failure)
            turn = accepted_result.value
            if not isinstance(turn, TurnSnapshot):
                return _failure(
                    "turn_snapshot_invalid",
                    "Normal Chat acceptance returned an invalid turn snapshot.",
                )
            canonical = turn.accepted_turn.message if regenerate else None
            role = str(canonical.role if canonical is not None else acceptance.role)
            content = str(
                canonical.content if canonical is not None else acceptance.content
            )
            metadata = dict(
                canonical.metadata if canonical is not None else acceptance.metadata
            )
            transaction_id = uuid.uuid4().hex
            metadata["normal_chat_transaction_id"] = transaction_id
            binding = self._identity_relay.binding_for(turn.identity_relay)
            if binding is None:
                self._turns.cancel(
                    turn.accepted_turn.turn_id,
                    "identity_relay_binding_missing",
                    lease=turn.lease,
                )
                return _failure(
                    "identity_relay_binding_missing",
                    "Normal Chat acceptance lost its Identity Relay binding.",
                )
            persona = acceptance.persona or NormalChatPersonaSnapshot.from_config(
                turn.config,
                acceptance.persona_overrides,
            )
            accepted = NormalChatAcceptedTurnSnapshot(
                transaction_id=transaction_id,
                source_transaction_id=source_transaction_id,
                turn=turn,
                role=role,
                content=content,
                metadata=metadata,
                persist_user_turn=bool(acceptance.persist_user_turn),
                persona=persona,
                relay_query_state=acceptance.relay_query_state,
                memory_work_context=acceptance.memory_work_context,
                relay_binding=binding,
                history_anchor_index=acceptance.history_anchor_index,
            )
            entry = _TransactionEntry(accepted=accepted, provider=turn.provider)
            with self._lock:
                if not self._turn_snapshot_is_current(turn):
                    self._turns.cancel(
                        turn.accepted_turn.turn_id,
                        "accepted_turn_stale",
                        lease=turn.lease,
                    )
                    return _failure(
                        "accepted_turn_stale",
                        "The Normal Chat turn changed before transaction publication.",
                    )
                self._entries[transaction_id] = entry
            if acceptance.persist_user_turn:
                try:
                    self._conversation.edit_message(
                        turn.accepted_turn.turn_id,
                        role=role,
                        content=content,
                        metadata=metadata,
                    )
                except (KeyError, RuntimeError):
                    self.cancel(transaction_id, reason="accepted_turn_edit_failed")
                    return _failure(
                        "accepted_turn_edit_failed",
                        "The accepted Normal Chat turn could not be frozen.",
                    )
            with self._lock:
                current = self._entries.get(transaction_id)
                current_failure = self._current_failure_locked(entry)
                if current is entry and current_failure is None:
                    return CommandResult(True, value=self._snapshot_locked(entry))
            self._cleanup(
                entry,
                NormalChatTransactionStatus.SUPERSEDED,
                "accepted_turn_stale",
                retain_source=False,
            )
            return _failure(
                "accepted_turn_stale",
                "The Normal Chat turn changed during accepted-state publication.",
            )

    def _prepare_worker(
        self,
        request: NormalChatRequestSnapshot,
        supervisor_token: CancellationToken,
    ) -> None:
        with self._lock:
            entry, failure = self._entry_for_request_locked(request)
            if failure is not None or entry is None:
                return
            token = entry.accepted.turn.cancellation
        if supervisor_token.cancelled:
            token.cancel(supervisor_token.reason)
        try:
            provider = entry.accepted.accepted_provider
            has_lifecycle = getattr(provider.context, 'model_lifecycle_available', False)
            if (provider.provider_id == "lmstudio" or has_lifecycle) and not self._providers.prepare_model(
                provider,
                reason="LM Studio model switch",
                force_unload=False,
                **({'cancel_token': token} if has_lifecycle else {}),
            ):
                raise RuntimeError(
                    f"The frozen chat model {provider.model_id!r} could not be prepared."
                )
            self._raise_if_not_current(entry, "provider model preparation")
            projected = self._identity_relay.prepare(
                entry.accepted.identity_relay,
                token,
            )
            if not projected.accepted or projected.value is None:
                raise _PreparationBlocked(
                    projected.failure
                    or RuntimeFailure(
                        "identity_relay_prepare_failed",
                        "Identity Relay preparation failed.",
                    )
                )
            projection = projected.value
            provider = projection.provider
            self._raise_if_not_current(entry, "Relay projection")
            if not self._providers.frozen_execution_available(provider):
                raise RuntimeError(
                    "Frozen completion is unavailable for the accepted provider."
                )
            state = NormalChatPreparationSnapshot(
                entry.accepted,
                request,
                provider,
                projection,
            )
            prompt = self._assembler.build(state)
            if not isinstance(prompt, PromptRequest):
                raise TypeError("Normal Chat request assembler returned an invalid prompt.")
            prepared = self._providers.prepare(provider, prompt)
            from core.runtime.document_context import DocumentContextTicket
            document_tickets = tuple(m.document_ticket for m in prompt.messages if isinstance(m.document_ticket, DocumentContextTicket))
            document_free = None
            if document_tickets:
                document_free = self._providers.prepare(provider, prompt.without_document_context())
                alternate_validated = self._identity_relay.validate_prepared_request(entry.accepted.identity_relay, document_free)
                if not alternate_validated.accepted:
                    raise _PreparationBlocked(alternate_validated.failure or RuntimeFailure("prepared_request_rejected", "Identity Relay rejected the document-free request."))
            validated = self._identity_relay.validate_prepared_request(
                entry.accepted.identity_relay,
                prepared,
            )
            if not validated.accepted:
                raise _PreparationBlocked(
                    validated.failure
                    or RuntimeFailure(
                        "prepared_request_rejected",
                        "Identity Relay rejected the prepared request.",
                    )
                )
            self._raise_if_not_current(entry, "prepared request")
            if entry.accepted.persist_user_turn:
                metadata = dict(entry.accepted.metadata)
                if projection.metadata is not None:
                    metadata["identity_relay"] = _thaw(projection.metadata)
                published = self._conversation.publish_accepted_turn(
                    request.lease,
                    role=entry.accepted.role,
                    content=entry.accepted.content,
                    metadata=metadata,
                    replace_index=entry.accepted.history_anchor_index,
                )
                if not published.accepted:
                    raise _PreparationBlocked(
                        published.failure
                        or RuntimeFailure(
                            "accepted_turn_publish_failed",
                            "The accepted turn was superseded before history commit.",
                        )
                    )
            with self._lock:
                current_failure = self._current_failure_locked(entry)
                if (
                    current_failure is not None
                    or self._entries.get(request.transaction_id) is not entry
                    or entry.request != request
                ):
                    raise _PreparationBlocked(
                        current_failure
                        or RuntimeFailure(
                            "superseded_transaction",
                            "The transaction changed before request publication.",
                        )
                    )
                entry.provider = provider
                entry.relay_projection = projection
                entry.prepared_request = prepared
                entry.document_free_request = document_free
                entry.document_tickets = document_tickets
                entry.history_committed = entry.accepted.persist_user_turn
                entry.status = NormalChatTransactionStatus.READY
                entry.error = None
        except _PreparationBlocked as exc:
            self._block(request, exc.failure)
        except BaseException as exc:
            self._block(
                request,
                RuntimeFailure(
                    "transaction_prepare_failed",
                    str(exc) or "Normal Chat request preparation failed.",
                    exc,
                ),
            )
        finally:
            entry.ready.set()

    def _block(
        self,
        request: NormalChatRequestSnapshot,
        failure: RuntimeFailure,
    ) -> None:
        with self._lock:
            entry = self._entries.get(request.transaction_id)
            if entry is None or entry.request != request:
                return
            entry.prepared_request = None
            entry.document_free_request = None
            entry.document_tickets = ()
            entry.error = failure
            if entry.status not in _TERMINAL_STATUSES:
                entry.status = NormalChatTransactionStatus.BLOCKED
            entry.ready.set()

    def _raise_if_not_current(self, entry: _TransactionEntry, stage: str) -> None:
        with self._lock:
            failure = self._current_failure_locked(entry)
        if failure is not None:
            raise _PreparationBlocked(
                RuntimeFailure(
                    failure.category,
                    f"Normal Chat turn was cancelled or superseded during {stage}.",
                    failure.cause,
                )
            )

    def _retire_superseded_source(self, transaction_id: str) -> None:
        with self._lock:
            entry = self._entries.get(transaction_id)
            self._regeneration_sources.pop(transaction_id, None)
        if entry is not None:
            self._cleanup(
                entry,
                NormalChatTransactionStatus.SUPERSEDED,
                "regenerate",
                retain_source=False,
            )

    def _cleanup(
        self,
        entry: _TransactionEntry,
        status: NormalChatTransactionStatus,
        reason: str,
        *,
        retain_source: bool,
    ) -> NormalChatTerminalReceipt:
        transaction_id = entry.accepted.transaction_id
        with self._lock:
            existing = self._terminal_receipts.get(transaction_id)
            if existing is not None:
                return existing
            if self._entries.get(transaction_id) is entry:
                del self._entries[transaction_id]
            source = self._source_for_entry(entry) if retain_source else None
            if source is not None:
                self._regeneration_sources[transaction_id] = source
            if status is not NormalChatTransactionStatus.COMPLETED:
                entry.accepted.turn.cancellation.cancel(str(reason or status.value))
            entry.status = status
            entry.request = None
            entry.provider = None
            entry.relay_projection = None
            entry.prepared_request = None
            entry.document_free_request = None
            entry.document_tickets = ()
            entry.worker_handle = None
            entry.error = None
            entry.ready.set()
            receipt = NormalChatTerminalReceipt(
                transaction_id,
                entry.accepted.lease,
                status,
                str(reason or status.value),
                cleanup_count=1,
                regeneration_source=source,
            )
            self._terminal_receipts[transaction_id] = receipt
            return receipt

    def _source_for_entry(
        self,
        entry: _TransactionEntry | None,
    ) -> NormalChatRegenerationSource | None:
        if entry is None:
            return None
        projection = entry.relay_projection
        return NormalChatRegenerationSource(
            transaction_id=entry.accepted.transaction_id,
            turn_id=entry.accepted.turn.accepted_turn.turn_id,
            role=entry.accepted.role,
            content=entry.accepted.content,
            metadata=entry.accepted.metadata,
            persist_user_turn=entry.accepted.persist_user_turn,
            identity_relay_enabled=entry.accepted.identity_relay.enabled,
            relay_snapshot=(projection.snapshot if projection is not None else None),
            relay_metadata=(projection.metadata if projection is not None else None),
        )

    def _snapshot_locked(self, entry: _TransactionEntry) -> NormalChatTransactionSnapshot:
        projection = entry.relay_projection
        prepared = (
            PreparedNormalChatRequest(
                entry.accepted.transaction_id,
                entry.request.request_id,
                entry.accepted.lease,
                entry.provider,
                entry.prepared_request,
            )
            if (
                entry.request is not None
                and entry.provider is not None
                and entry.prepared_request is not None
            )
            else None
        )
        return NormalChatTransactionSnapshot(
            accepted=entry.accepted,
            status=entry.status,
            request=entry.request,
            provider=entry.provider or entry.accepted.accepted_provider,
            relay_snapshot=(projection.snapshot if projection is not None else None),
            relay_metadata=(projection.metadata if projection is not None else None),
            relay_notice=(projection.notice if projection is not None else None),
            relay_trace=(projection.trace if projection is not None else {}),
            prepared=prepared,
            dispatch_claims=tuple(entry.dispatch_claims),
            worker_started=entry.worker_started,
            worker_ready=entry.ready.is_set(),
            history_committed=entry.history_committed,
            error=entry.error,
        )

    def _entry_for_request_locked(
        self,
        request: NormalChatRequestSnapshot,
    ) -> tuple[_TransactionEntry | None, RuntimeFailure | None]:
        if not isinstance(request, NormalChatRequestSnapshot):
            return None, RuntimeFailure(
                "request_invalid",
                "Normal Chat operations require NormalChatRequestSnapshot.",
            )
        entry = self._entries.get(request.transaction_id)
        if entry is None:
            return None, RuntimeFailure(
                "transaction_not_active",
                "The Normal Chat transaction is no longer active.",
            )
        if entry.request != request or entry.accepted.lease != request.lease:
            return None, RuntimeFailure(
                "request_lease_mismatch",
                "The request does not own this Normal Chat transaction route.",
            )
        return entry, self._current_failure_locked(entry)

    def _current_failure_locked(
        self,
        entry: _TransactionEntry | None,
    ) -> RuntimeFailure | None:
        if entry is None:
            return RuntimeFailure(
                "transaction_not_active",
                "The Normal Chat transaction is no longer active.",
            )
        if self._entries.get(entry.accepted.transaction_id) is not entry:
            return RuntimeFailure(
                "superseded_transaction",
                "A newer transaction owns this accepted turn.",
            )
        turn = entry.accepted.turn
        if turn.cancellation.cancelled:
            return RuntimeFailure(
                "transaction_cancelled",
                "The Normal Chat transaction was cancelled.",
            )
        if not self._conversation.session_lease_is_current(turn.lease):
            return RuntimeFailure(
                "stale_session",
                "The Normal Chat transaction belongs to an older session.",
            )
        if self._turns.snapshot(turn.accepted_turn.turn_id) is not turn:
            return RuntimeFailure(
                "superseded_route",
                "A newer route owns this accepted turn.",
            )
        return None

    def _turn_snapshot_is_current(self, turn: TurnSnapshot) -> bool:
        return (
            isinstance(turn, TurnSnapshot)
            and not turn.cancellation.cancelled
            and self._conversation.session_lease_is_current(turn.lease)
            and self._turns.snapshot(turn.accepted_turn.turn_id) is turn
        )


class _PreparationBlocked(RuntimeError):
    def __init__(self, failure: RuntimeFailure) -> None:
        self.failure = failure
        super().__init__(failure.message)


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult[object]:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


def _failure_message(failure: RuntimeFailure | None, fallback: str) -> str:
    return failure.message if failure is not None else str(fallback)


def _transaction_id(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, NormalChatRequestSnapshot):
        return value.transaction_id
    if isinstance(value, NormalChatTransactionSnapshot):
        return value.transaction_id
    return ""


def _missing_or_terminal_failure(
    transaction_id: str,
    receipts: Mapping[str, NormalChatTerminalReceipt],
) -> CommandResult[object]:
    if transaction_id in receipts:
        return _failure(
            "transaction_terminal",
            "The Normal Chat transaction has already completed terminal cleanup.",
        )
    return _failure(
        "transaction_not_active",
        "The Normal Chat transaction is no longer active.",
    )


def _transaction_status(status: TurnTerminalStatus) -> NormalChatTransactionStatus:
    return {
        TurnTerminalStatus.COMPLETED: NormalChatTransactionStatus.COMPLETED,
        TurnTerminalStatus.CANCELED: NormalChatTransactionStatus.CANCELED,
        TurnTerminalStatus.INTERRUPTED: NormalChatTransactionStatus.INTERRUPTED,
        TurnTerminalStatus.SUPERSEDED: NormalChatTransactionStatus.SUPERSEDED,
        TurnTerminalStatus.FAILED: NormalChatTransactionStatus.FAILED,
    }[status]


def _persistent_relay_snapshot(
    snapshot: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if snapshot is None:
        return None
    persistence_mode = str(snapshot.get("persistence_mode") or "").strip().lower()
    return snapshot if persistence_mode == "persistent" else None


__all__ = [
    "NormalChatAcceptance",
    "NormalChatAcceptedTurnSnapshot",
    "NormalChatCommitReceipt",
    "NormalChatConversationPort",
    "NormalChatDispatchClaim",
    "NormalChatIdentityRelayPort",
    "NormalChatPersonaSnapshot",
    "NormalChatPreparationSnapshot",
    "NormalChatProviderPort",
    "NormalChatRegenerationSource",
    "NormalChatRequestAssembler",
    "NormalChatRequestSnapshot",
    "NormalChatTerminalReceipt",
    "NormalChatTransactionService",
    "NormalChatTransactionSnapshot",
    "NormalChatTransactionStatus",
    "NormalChatTurnPort",
    "NormalChatWorkerPort",
    "PreparedNormalChatRequest",
]
