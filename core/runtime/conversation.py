"""Canonical immutable conversation state and exactly-once turn commits."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from pathlib import Path
import threading
import time
from types import MappingProxyType
from typing import Callable
import uuid

from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.identifiers import (
    RouteGeneration,
    RunId,
    SessionGeneration,
    TurnId,
    WorkLease,
)


class _FrozenList(tuple):
    __slots__ = ()


class _FrozenSet(frozenset):
    __slots__ = ()


def _freeze_mapping(values: Mapping[str, object]) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise TypeError("Conversation metadata must be a mapping")
    return MappingProxyType({str(key): _freeze(value) for key, value in values.items()})


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if type(value) is _FrozenList:
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, list):
        return _FrozenList(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    if type(value) is _FrozenSet:
        return _FrozenSet(_freeze(item) for item in value)
    if isinstance(value, set):
        return _FrozenSet(_freeze(item) for item in value)
    if isinstance(value, frozenset):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, Path):
        return Path(str(value))
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if type(value) is _FrozenList:
        return [_thaw(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw(item) for item in value)
    if type(value) is _FrozenSet:
        return {_thaw(item) for item in value}
    if isinstance(value, frozenset):
        return frozenset(_thaw(item) for item in value)
    if isinstance(value, Path):
        return Path(str(value))
    return value


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    message_id: str
    role: str
    content: str
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ConversationSnapshot:
    session_generation: SessionGeneration
    revision: int
    messages: tuple[ConversationMessage, ...]


@dataclass(frozen=True, slots=True)
class AcceptedTurn:
    turn_id: TurnId
    lease: WorkLease
    message: ConversationMessage


@dataclass(frozen=True, slots=True)
class RegenerateTurn:
    source_turn_id: TurnId
    lease: WorkLease
    commit_kind: str
    source: ConversationMessage


@dataclass(frozen=True, slots=True)
class AssistantCommit:
    source_turn_id: TurnId
    commit_kind: str
    message: ConversationMessage


class SessionTransitionReentrancyError(RuntimeError):
    """Raised when an admitted effect attempts its own session transition."""


class SessionEffectDrainingError(RuntimeError):
    """Raised when reset/load cannot revoke old session effects by its deadline."""

    def __init__(self, failure: RuntimeFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class SessionEffectAdmission:
    admission_id: int
    lease: WorkLease
    thread_id: int


class ConversationService:
    """Own one conversation behind immutable snapshots and work leases."""

    def __init__(
        self,
        *,
        run_id: RunId | None = None,
        session_effect_drain_timeout_seconds: float = 0.5,
    ) -> None:
        self._lock = threading.RLock()
        self._session_effect_condition = threading.Condition(self._lock)
        self._session_transition_registration_lock = threading.Lock()
        self._run_id = run_id or RunId(1)
        self._session_generation = SessionGeneration(0)
        self._session_effect_admission_open = True
        self._next_session_effect_admission_id = 0
        self._session_effect_admissions: dict[int, SessionEffectAdmission] = {}
        self._session_transition_count = 0
        self._session_transition_active = False
        self._session_transition_owner_thread_id: int | None = None
        self._session_effect_drain_timeout_seconds = max(
            0.0,
            float(session_effect_drain_timeout_seconds),
        )
        self._revision = 0
        self._messages: tuple[ConversationMessage, ...] = ()
        self._turn_attempts: dict[TurnId, int] = {}
        self._turn_generations: dict[TurnId, int] = {}
        self._turn_sources: dict[TurnId, ConversationMessage] = {}
        self._transient_turns: dict[TurnId, ConversationMessage] = {}
        self._assistant_sources: dict[str, TurnId] = {}
        self._commits: dict[tuple[SessionGeneration, TurnId, str], CommandResult[AssistantCommit]] = {}
        self._transition_invalidator: Callable[[str], object] | None = None

    def set_transition_invalidator(
        self,
        callback: Callable[[str], object] | None,
    ) -> None:
        with self._lock:
            self._transition_invalidator = callback

    @property
    def run_id(self) -> RunId:
        with self._lock:
            return self._run_id

    def advance_run(self) -> RunId:
        """Invalidate the old runtime scope while preserving visible history."""

        self._begin_session_transition()
        try:
            self._invalidate_transition("runtime_generation_advanced")
            with self._lock:
                visible_ids = {message.message_id for message in self._messages}
                associations = {message_id: source_id for message_id, source_id in self._assistant_sources.items()
                                if message_id in visible_ids}
                retained_sources = {source_id: self._turn_sources[source_id] for source_id in associations.values()
                                    if source_id in self._turn_sources}
                retained_sources.update({TurnId(message.message_id): message for message in self._messages
                                         if message.role.strip().lower() != "assistant"})
                self._run_id = RunId(self._run_id.value + 1)
                self._advance_session_locked()
                # Preserve canonical sources for retained history, never old
                # leases, pending inputs, or sources whose replies were removed.
                self._turn_sources = retained_sources
                self._turn_attempts = {source_id: 0 for source_id in retained_sources}
                self._turn_generations = dict(self._turn_attempts)
                self._assistant_sources = {message_id: source_id for message_id, source_id in associations.items()
                                           if source_id in retained_sources}
                self._revision += 1
                return self._run_id
        finally:
            self._end_session_transition()

    def snapshot(self) -> ConversationSnapshot:
        with self._lock:
            return ConversationSnapshot(
                self._session_generation,
                self._revision,
                self._messages,
            )

    def message_mappings(self) -> tuple[dict[str, object], ...]:
        with self._lock:
            return tuple(_message_mapping(message) for message in self._messages)

    def with_history_snapshot(self, effect):
        """Admit short local cleanup while message image references stay fixed."""
        with self._lock:
            return effect(self.message_mappings())

    def snapshot_with_retirement(self) -> tuple[ConversationSnapshot, int | None]:
        """Return history and its last history-preserving close atomically."""
        with self._lock:
            receipt = getattr(self, '_last_route_retirement', None)
            previous = receipt[0] if receipt and receipt[1] == self._revision else None
            return self._snapshot_locked(), previous

    def latest_user_turn_scope(self) -> dict[str, object]:
        """Read the session and newest accepted real input, including preparation.

        Prompt addons run before publish_accepted_turn, so visible history alone
        cannot identify the input whose prompt is currently being assembled.
        """
        with self._lock:
            candidates = list(self._messages) + list(self._transient_turns.values())
            latest = next((message for message in reversed(candidates)
                if message.role == 'user'
                and not message.metadata.get('hidden_proactive')
                and not message.metadata.get('hidden_proactive_request')
                and message.content.strip() not in {'PING', 'PONG', '__CONTINUE_ASSISTANT__', 'You continue speaking.'}), None)
            return dict(available=True, session_key=f'{self._run_id.value}/{self._session_generation.value}',
                latest_user_key=str(latest.metadata.get('normal_chat_transaction_id') or latest.message_id) if latest else '')

    def session_lease(self) -> WorkLease:
        with self._lock:
            return WorkLease(
                run_id=self._run_id,
                session_generation=self._session_generation,
            )

    def session_lease_is_current(self, lease: WorkLease) -> bool:
        with self._session_transition_registration_lock:
            with self._lock:
                return self._session_lease_is_current_locked(lease)

    def turn_lease_is_current(self, lease: WorkLease) -> bool:
        with self._session_transition_registration_lock:
            with self._lock:
                return self._turn_lease_is_current_locked(lease)

    def admit_session_effect(
        self,
        lease: WorkLease,
    ) -> SessionEffectAdmission | None:
        with self._session_transition_registration_lock:
            with self._session_effect_condition:
                if not self._session_lease_is_current_locked(lease):
                    return None
                self._next_session_effect_admission_id += 1
                admission = SessionEffectAdmission(
                    admission_id=self._next_session_effect_admission_id,
                    lease=lease,
                    thread_id=threading.get_ident(),
                )
                self._session_effect_admissions[admission.admission_id] = admission
                return admission

    def release_session_effect(self, admission: SessionEffectAdmission) -> None:
        with self._session_effect_condition:
            active = self._session_effect_admissions.get(admission.admission_id)
            if active is not admission:
                raise RuntimeError("Session effect admission is not active")
            del self._session_effect_admissions[admission.admission_id]
            self._session_effect_condition.notify_all()

    def accept_user_turn(
        self,
        *,
        role: str,
        content: str,
        metadata: Mapping[str, object],
        persist: bool = True,
    ) -> AcceptedTurn:
        with self._lock:
            return self._accept_user_turn_locked(
                role=role,
                content=content,
                metadata=metadata,
                persist=persist,
            )

    def accept_user_turn_from_source(
        self,
        source_lease: WorkLease,
        *,
        role: str,
        content: str,
        metadata: Mapping[str, object],
        persist: bool = True,
        allow_closed_turn: bool = False,
        expected_revision: int | None = None,
    ) -> CommandResult[AcceptedTurn]:
        """Atomically validate an input source lease and accept its new turn."""

        with self._lock:
            if expected_revision is not None and self._revision != expected_revision:
                return CommandResult(False, failure=RuntimeFailure(
                    "stale_history", "History changed before input acceptance."))
            if source_lease.turn_id is None:
                current = self._session_lease_is_current_locked(source_lease)
            else:
                current = self._turn_lease_is_current_locked(source_lease)
                if not current and allow_closed_turn:
                    current = self._closed_turn_lease_is_current_locked(source_lease)
            if not current:
                return CommandResult(
                    accepted=False,
                    failure=RuntimeFailure(
                        "stale_source_lease",
                        "The input source no longer owns the current runtime route.",
                    ),
                )
            return CommandResult(
                accepted=True,
                value=self._accept_user_turn_locked(
                    role=role,
                    content=content,
                    metadata=metadata,
                    persist=persist,
                ),
            )

    def begin_regenerate(
        self,
        source_turn_id: TurnId | None = None,
        *, expected_target=None,
    ) -> RegenerateTurn:
        with self._lock:
            if expected_target is not None:
                self._require_action_target_locked(expected_target)
            explicit_source = source_turn_id is not None
            if explicit_source and source_turn_id not in self._turn_sources:
                raise RuntimeError("The accepted regeneration source is no longer available")
            messages = list(self._messages)
            removed_assistant = bool(
                messages and messages[-1].role.strip().lower() == "assistant"
                and (
                    not explicit_source
                    or self._assistant_sources.get(messages[-1].message_id) == source_turn_id
                )
            )
            if removed_assistant:
                removed = messages.pop()
                associated_source = self._assistant_sources.pop(
                    removed.message_id,
                    None,
                )
                if source_turn_id is None:
                    source_turn_id = associated_source
            source = (
                self._turn_sources.get(source_turn_id)
                if source_turn_id is not None
                else None
            )
            if source is None:
                source = next(
                    (
                        message
                        for message in reversed(messages)
                        if message.role.strip().lower() != "assistant"
                    ),
                    None,
                )
            if source is None:
                raise RuntimeError("No accepted input turn is available to regenerate")
            turn_id = TurnId(source.message_id)
            self._turn_sources[turn_id] = source
            attempt = self._turn_generations.get(turn_id, 0) + 1
            self._turn_attempts[turn_id] = attempt
            self._turn_generations[turn_id] = attempt
            if removed_assistant:
                self._messages = tuple(messages)
                self._revision += 1
            return RegenerateTurn(
                source_turn_id=turn_id,
                lease=self._turn_lease(turn_id, attempt),
                commit_kind=f"regenerate:{attempt}",
                source=source,
            )

    def _require_action_target_locked(self, target) -> None:
        guard = getattr(target, 'is_current', None)
        if guard is not None and not guard():
            raise RuntimeError('The conversation action caller retired.')
        if (self._revision != target.revision
                or self._session_generation.value != target.session_generation
                or not self._messages or self._messages[-1].message_id != target.message_id):
            raise RuntimeError('The conversation action target changed.')

    def retry_exchange_if_current(self, target) -> None:
        """Remove only the selected final exchange, under the history lock."""
        with self._lock:
            self._require_action_target_locked(target)
            start = len(self._messages) - 1
            if self._messages[start].role.lower() == 'assistant':
                start -= 1
            if start < 0 or self._messages[start].role.lower() != 'user':
                raise RuntimeError('No user exchange is available to retry.')
            self.delete_message_at(slice(start, None))

    def target_after_route_retirement(self, target, lease=None):
        """Allow ONLY a known terminal revision, not a newer input.

        A route closing increments revision even when history did not change.
        The single bounded receipt proves the exact before/after revision and
        lease. A caller without a lease may cross the same recorded retirement
        (e.g. a phone action sent just as playback finishes). Any intervening
        acceptance, edit, reset or other close rejects.
        """
        with self._lock:
            receipt = getattr(self, '_last_route_retirement', None)
            if (receipt is None or receipt[:2] != (target.revision, self._revision)
                    or (lease is not None and receipt[2] != lease)):
                return target
            updated = replace(target, revision=self._revision)
            self._require_action_target_locked(updated)
            return updated

    def snapshot_for_action(self, target):
        """Check the target and history against one lock-consistent revision."""
        with self._lock:
            try:
                target = self.target_after_route_retirement(target)
            except RuntimeError:
                # Preserve invalid identities for the caller's stale check.
                pass
            return target, self._snapshot_locked()

    def commit_assistant(
        self,
        lease: WorkLease,
        *,
        content: str,
        metadata: Mapping[str, object],
    ) -> CommandResult[AssistantCommit]:
        with self._lock:
            if not self._session_lease_is_current_locked(lease):
                return _stale_session_result()
            turn_id = lease.turn_id
            if turn_id is None:
                return CommandResult(
                    accepted=False,
                    failure=RuntimeFailure(
                        "invalid_turn",
                        "Assistant commit requires an accepted turn lease.",
                    ),
                )
            attempt = lease.route_generation.value if lease.route_generation else 0
            commit_kind = "assistant" if attempt == 0 else f"regenerate:{attempt}"
            commit_key = (self._session_generation, turn_id, commit_kind)
            existing = self._commits.get(commit_key)
            if existing is not None:
                return existing
            owns_source = turn_id in self._turn_sources
            if self._turn_attempts.get(turn_id) != attempt or not owns_source:
                return CommandResult(
                    accepted=False,
                    failure=RuntimeFailure(
                        "stale_turn",
                        "Assistant commit no longer owns the current turn attempt.",
                    ),
                )
            message = _new_message(
                role="assistant",
                content=content,
                metadata=metadata,
            )
            self._messages = self._messages + (message,)
            self._assistant_sources[message.message_id] = turn_id
            self._revision += 1
            result = CommandResult(
                accepted=True,
                value=AssistantCommit(turn_id, commit_kind, message),
            )
            self._commits[commit_key] = result
            return result

    def assistant_commit_for(self, lease: WorkLease) -> AssistantCommit | None:
        """Return the exact route's committed assistant, if it still exists."""

        with self._lock:
            if not self._session_lease_is_current_locked(lease):
                return None
            turn_id = lease.turn_id
            if turn_id is None:
                return None
            attempt = lease.route_generation.value if lease.route_generation else 0
            commit_kind = "assistant" if attempt == 0 else f"regenerate:{attempt}"
            result = self._commits.get(
                (self._session_generation, turn_id, commit_kind)
            )
            if result is None or not result.accepted:
                return None
            return result.value

    def append_message(self, message: Mapping[str, object]) -> ConversationSnapshot:
        with self._lock:
            prepared = _message_from_mapping(message)
            self._messages = self._messages + (prepared,)
            if prepared.role.strip().lower() != "assistant":
                turn_id = TurnId(prepared.message_id)
                self._turn_sources[turn_id] = prepared
                self._turn_attempts.setdefault(turn_id, 0)
                self._turn_generations.setdefault(turn_id, 0)
            self._revision += 1
            return self._snapshot_locked()

    def insert_message(
        self,
        index: int,
        message: Mapping[str, object],
    ) -> ConversationSnapshot:
        with self._lock:
            messages = list(self._messages)
            prepared = _message_from_mapping(message)
            messages.insert(index, prepared)
            self._messages = tuple(messages)
            if prepared.role.strip().lower() != "assistant":
                turn_id = TurnId(prepared.message_id)
                self._turn_sources[turn_id] = prepared
                self._turn_attempts.setdefault(turn_id, 0)
                self._turn_generations.setdefault(turn_id, 0)
            self._revision += 1
            return self._snapshot_locked()

    def replace_message_at(
        self,
        index: int,
        message: Mapping[str, object],
        *,
        expected_revision: int | None = None,
    ) -> ConversationSnapshot | None:
        with self._lock:
            if expected_revision is not None and self._revision != int(expected_revision):
                return None
            messages = list(self._messages)
            existing = messages[index]
            messages[index] = _message_from_mapping(
                message,
                message_id=existing.message_id,
            )
            self._messages = tuple(messages)
            turn_id = TurnId(existing.message_id)
            if messages[index].role.strip().lower() == "assistant":
                self._remove_turn_source_locked(turn_id)
            else:
                self._assistant_sources.pop(existing.message_id, None)
                self._turn_sources[turn_id] = messages[index]
                self._turn_attempts.setdefault(turn_id, 0)
                self._turn_generations.setdefault(turn_id, 0)
            self._revision += 1
            return self._snapshot_locked()

    def delete_message_if_current(self, message_id: str, *, expected_revision: int,
                                  expected_session: int, is_busy: Callable[[], bool],
                                  reconcile: Callable[..., Mapping[str, object]]) -> CommandResult:
        """Drain short session effects, validate, reconcile, then publish history.

        Reconciliation owns no provider work. The transition excludes database
        effects without adding an inverse memory/conversation lock order.
        """
        self._begin_session_transition()
        try:
            if is_busy():
                return CommandResult(False, failure=RuntimeFailure('conversation_busy',
                    'Wait for generation and speech playback to finish before deleting a message.'))
            with self._lock:
                position = next((i for i, message in enumerate(self._messages)
                                 if message.message_id == message_id), None)
                if (self._revision != expected_revision or self._session_generation.value != expected_session
                        or position is None):
                    return CommandResult(False, failure=RuntimeFailure('conversation_changed',
                        'The conversation changed. Open Delete on the message again.'))
                if self._messages[position].role.lower() not in {'user', 'assistant'}:
                    return CommandResult(False, failure=RuntimeFailure('invalid_role',
                        'Only user and assistant messages can be deleted.'))
                previous = self.message_mappings()
                replacement = previous[:position] + previous[position + 1:]
                memory = dict(reconcile(previous, replacement, position + 1))
                snapshot = self.delete_message_at(position)
                # Cached commits must not make a deleted reply appear committed.
                self._commits = {key: value for key, value in self._commits.items()
                                 if not (value.accepted and value.value
                                         and value.value.message.message_id == message_id)}
                return CommandResult(True, value=dict(deleted=True, message_id=message_id,
                                                     revision=snapshot.revision, memory=memory))
        finally:
            self._end_session_transition()

    def edit_history_if_current(self, messages, *, expected_revision: int, source_indices,
                                reconcile: Callable[..., Mapping[str, object]]) -> CommandResult:
        """Publish an editor's mapped rows only after local memory repair succeeds."""
        self._begin_session_transition()
        try:
            with self._lock:
                if self._revision != expected_revision:
                    return CommandResult(False, failure=RuntimeFailure('conversation_changed',
                        'The conversation changed while editing. Cancel and try again.'))
                replacements = tuple(_message_from_mapping(message) for message in messages)
                previous = self.message_mappings()
                reconcile(previous, tuple(messages), tuple(source_indices))
                return CommandResult(True, value=self._replace_messages_locked(replacements))
        finally:
            self._end_session_transition()

    def delete_message_at(self, index: int | slice) -> ConversationSnapshot:
        with self._lock:
            messages = list(self._messages)
            selected = messages[index]
            removed = selected if isinstance(selected, list) else [selected]
            del messages[index]
            self._messages = tuple(messages)
            for message in removed:
                if message.role.strip().lower() == "assistant":
                    self._assistant_sources.pop(message.message_id, None)
                else:
                    self._remove_turn_source_locked(TurnId(message.message_id))
            self._prune_turn_attempts_locked()
            self._revision += 1
            return self._snapshot_locked()

    def edit_message(
        self,
        message_id: str | TurnId,
        *,
        role: str | None = None,
        content: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> ConversationSnapshot:
        wanted = message_id.value if isinstance(message_id, TurnId) else str(message_id)
        with self._lock:
            messages = list(self._messages)
            index = next(
                (
                    offset
                    for offset, message in enumerate(messages)
                    if message.message_id == wanted
                ),
                None,
            )
            if index is None:
                transient_id = TurnId(wanted)
                current = self._transient_turns.get(transient_id)
                if current is None:
                    raise KeyError(wanted)
                updated = ConversationMessage(
                    message_id=current.message_id,
                    role=current.role if role is None else str(role),
                    content=current.content if content is None else str(content),
                    metadata=(
                        current.metadata
                        if metadata is None
                        else _clean_metadata(metadata)
                    ),
                )
                self._transient_turns[transient_id] = updated
                self._turn_sources[transient_id] = updated
                self._revision += 1
                return self._snapshot_locked()
            current = messages[index]
            messages[index] = ConversationMessage(
                message_id=current.message_id,
                role=current.role if role is None else str(role),
                content=current.content if content is None else str(content),
                metadata=(
                    current.metadata
                    if metadata is None
                    else _freeze_mapping(metadata)
                ),
            )
            self._messages = tuple(messages)
            turn_id = TurnId(current.message_id)
            if messages[index].role.strip().lower() == "assistant":
                self._remove_turn_source_locked(turn_id)
            else:
                self._assistant_sources.pop(current.message_id, None)
                self._turn_sources[turn_id] = messages[index]
                self._turn_attempts.setdefault(turn_id, 0)
                self._turn_generations.setdefault(turn_id, 0)
            self._revision += 1
            return self._snapshot_locked()

    def publish_accepted_turn(
        self,
        lease: WorkLease,
        *,
        role: str,
        content: str,
        metadata: Mapping[str, object],
        replace_index: int | None = None,
    ) -> CommandResult[ConversationMessage]:
        with self._session_transition_registration_lock:
            with self._lock:
                if not self._turn_lease_is_current_locked(lease):
                    return CommandResult(
                        False,
                        failure=RuntimeFailure(
                            "stale_turn",
                            "The accepted turn no longer owns this conversation route.",
                        ),
                    )
                turn_id = lease.turn_id
                assert turn_id is not None
                prepared = ConversationMessage(
                    message_id=turn_id.value,
                    role=str(role),
                    content=str(content),
                    metadata=_clean_metadata(metadata),
                )
                messages = list(self._messages)
                existing_index = next(
                    (
                        index
                        for index, message in enumerate(messages)
                        if message.message_id == turn_id.value
                    ),
                    None,
                )
                if existing_index is not None:
                    messages[existing_index] = prepared
                elif (
                    isinstance(replace_index, int)
                    and 0 <= replace_index < len(messages)
                ):
                    messages[replace_index] = prepared
                else:
                    messages.append(prepared)
                self._messages = tuple(messages)
                self._transient_turns.pop(turn_id, None)
                self._turn_sources[turn_id] = prepared
                self._turn_generations.setdefault(
                    turn_id,
                    self._turn_attempts.get(turn_id, 0),
                )
                self._prune_turn_attempts_locked()
                self._revision += 1
                return CommandResult(True, value=prepared)

    def release_transient_turn(self, lease: WorkLease) -> None:
        with self._lock:
            turn_id = lease.turn_id
            route = lease.route_generation
            if (
                turn_id is not None
                and route is not None
                and self._turn_attempts.get(turn_id) == route.value
                and self._transient_turns.pop(turn_id, None) is not None
            ):
                self._revision += 1

    def invalidate_turn_route(self, lease: WorkLease) -> bool:
        """Close one exact route while retaining its source association."""

        with self._lock:
            if (
                lease.run_id != self._run_id
                or lease.session_generation != self._session_generation
                or lease.turn_id is None
                or lease.route_generation is None
                or self._turn_attempts.get(lease.turn_id)
                != lease.route_generation.value
            ):
                return False
            self._turn_attempts.pop(lease.turn_id, None)
            self._transient_turns.pop(lease.turn_id, None)
            self._last_route_retirement = (self._revision, self._revision + 1, lease)
            self._revision += 1
            return True

    def rollback_assistant_commit(
        self,
        lease: WorkLease,
        commit: AssistantCommit,
    ) -> bool:
        """Retract a commit that lost its reserved route before publication."""

        with self._lock:
            if commit.source_turn_id != lease.turn_id:
                return False
            attempt = lease.route_generation.value if lease.route_generation else 0
            commit_kind = "assistant" if attempt == 0 else f"regenerate:{attempt}"
            commit_key = (self._session_generation, commit.source_turn_id, commit_kind)
            existing = self._commits.get(commit_key)
            if existing is None or existing.value != commit:
                return False
            messages = tuple(
                message
                for message in self._messages
                if message.message_id != commit.message.message_id
            )
            if len(messages) == len(self._messages):
                return False
            self._messages = messages
            self._assistant_sources.pop(commit.message.message_id, None)
            self._commits.pop(commit_key, None)
            self._revision += 1
            return True

    def publish_conditional_input(self, before: ConversationSnapshot, lease: WorkLease,
                                  publish: Callable[[], None]) -> bool:
        """Publish only our exact unconsumed input against captured history.

        Caller owns the pending-slot lock. publish must only assign that slot;
        no listeners, provider work or UI calls may run in this critical section.
        """
        with self._lock:
            if (self._session_generation != before.session_generation
                    or not self._turn_lease_is_current_locked(lease)
                    # Normal acceptance creates then annotates a transient user
                    # turn (two revisions); the loop publishes its history later.
                    or self._revision != before.revision + 2
                    or self._messages != before.messages
                    or lease.turn_id not in self._transient_turns):
                return False
            publish()
            return True

    def discard_accepted_turn(self, lease: WorkLease) -> bool:
        with self._lock:
            turn_id = lease.turn_id
            route = lease.route_generation
            if (
                turn_id is None
                or route is None
                or self._turn_attempts.get(turn_id) != route.value
            ):
                return False
            messages = tuple(
                message
                for message in self._messages
                if message.message_id != turn_id.value
            )
            removed = (
                len(messages) != len(self._messages)
                or self._transient_turns.pop(turn_id, None) is not None
            )
            if not removed:
                return False
            self._messages = messages
            self._turn_attempts.pop(turn_id, None)
            self._turn_generations.pop(turn_id, None)
            self._turn_sources.pop(turn_id, None)
            self._assistant_sources = {
                message_id: source_turn_id
                for message_id, source_turn_id in self._assistant_sources.items()
                if source_turn_id != turn_id
            }
            self._commits = {
                key: value
                for key, value in self._commits.items()
                if key[1] != turn_id
            }
            self._revision += 1
            return True

    def replace_messages(
        self,
        messages: Sequence[Mapping[str, object]],
    ) -> ConversationSnapshot:
        replacements = tuple(_message_from_mapping(message) for message in messages)
        with self._lock:
            return self._replace_messages_locked(replacements)

    def replace_messages_if_revision(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        expected_revision: int,
    ) -> ConversationSnapshot | None:
        """Replace visible messages only while the captured history is current."""

        replacements = tuple(_message_from_mapping(message) for message in messages)
        with self._lock:
            if self._revision != int(expected_revision):
                return None
            return self._replace_messages_locked(replacements)

    def load_messages(
        self,
        messages: Sequence[Mapping[str, object]],
    ) -> ConversationSnapshot:
        prepared = tuple(_message_from_mapping(message) for message in messages)
        self._begin_session_transition()
        try:
            self._invalidate_transition("conversation_loaded")
            with self._lock:
                self._advance_session_locked()
                self._messages = prepared
                self._turn_sources = {
                    TurnId(message.message_id): message
                    for message in prepared
                    if message.role.strip().lower() != "assistant"
                }
                self._turn_attempts = {
                    turn_id: 0 for turn_id in self._turn_sources
                }
                self._turn_generations = {
                    turn_id: 0 for turn_id in self._turn_sources
                }
                self._revision += 1
                return self._snapshot_locked()
        finally:
            self._end_session_transition()

    def reset(self) -> ConversationSnapshot:
        self._begin_session_transition()
        try:
            self._invalidate_transition("conversation_reset")
            with self._lock:
                self._advance_session_locked()
                self._messages = ()
                self._revision += 1
                return self._snapshot_locked()
        finally:
            self._end_session_transition()

    def _turn_lease(self, turn_id: TurnId, attempt: int) -> WorkLease:
        return WorkLease(
            run_id=self._run_id,
            session_generation=self._session_generation,
            turn_id=turn_id,
            route_generation=RouteGeneration(attempt),
        )

    def _replace_messages_locked(
        self,
        replacements: tuple[ConversationMessage, ...],
    ) -> ConversationSnapshot:
        prepared = _preserve_replacement_message_ids(
            self._messages,
            replacements,
        )
        previous_attempts = dict(self._turn_attempts)
        previous_generations = dict(self._turn_generations)
        transient_attempts = {
            turn_id: previous_attempts.get(turn_id, 0)
            for turn_id in self._transient_turns
        }
        retained_assistant_sources = {
            message_id: source_turn_id
            for message_id, source_turn_id in self._assistant_sources.items()
            if any(message.message_id == message_id for message in prepared)
        }
        retained_source_ids = set(retained_assistant_sources.values())
        retained_source_ids.update(self._transient_turns)
        retained_sources = {
            turn_id: source
            for turn_id, source in self._turn_sources.items()
            if turn_id in retained_source_ids
        }
        visible_sources = {
            TurnId(message.message_id): message
            for message in prepared
            if message.role.strip().lower() != "assistant"
        }
        self._messages = prepared
        self._turn_sources = {**retained_sources, **visible_sources}
        self._assistant_sources = retained_assistant_sources
        self._turn_generations = {
            turn_id: previous_generations.get(
                turn_id,
                previous_attempts.get(turn_id, 0),
            )
            for turn_id in self._turn_sources
        }
        self._turn_attempts = {
            turn_id: previous_attempts.get(turn_id, 0)
            for turn_id in visible_sources
        }
        self._turn_attempts.update(
            {
                turn_id: previous_attempts[turn_id]
                for turn_id in retained_sources
                if turn_id in previous_attempts
            }
        )
        self._turn_attempts.update(transient_attempts)
        self._revision += 1
        return self._snapshot_locked()

    def _accept_user_turn_locked(
        self,
        *,
        role: str,
        content: str,
        metadata: Mapping[str, object],
        persist: bool,
    ) -> AcceptedTurn:
        message = _new_message(role=role, content=content, metadata=metadata)
        turn_id = TurnId(message.message_id)
        self._turn_sources[turn_id] = message
        if persist:
            self._messages = self._messages + (message,)
        else:
            self._transient_turns[turn_id] = message
        self._turn_attempts[turn_id] = 0
        self._turn_generations[turn_id] = 0
        self._revision += 1
        return AcceptedTurn(
            turn_id=turn_id,
            lease=self._turn_lease(turn_id, 0),
            message=message,
        )

    def _snapshot_locked(self) -> ConversationSnapshot:
        return ConversationSnapshot(
            self._session_generation,
            self._revision,
            self._messages,
        )

    def _session_lease_is_current_locked(self, lease: WorkLease) -> bool:
        return (
            self._session_effect_admission_open
            and isinstance(lease, WorkLease)
            and lease.run_id == self._run_id
            and lease.session_generation is not None
            and lease.session_generation == self._session_generation
        )

    def _turn_lease_is_current_locked(self, lease: WorkLease) -> bool:
        if (
            not self._session_lease_is_current_locked(lease)
            or lease.turn_id is None
            or lease.route_generation is None
        ):
            return False
        owns_source = lease.turn_id in self._turn_sources
        return (
            owns_source
            and self._turn_attempts.get(lease.turn_id)
            == lease.route_generation.value
        )

    def _closed_turn_lease_is_current_locked(self, lease: WorkLease) -> bool:
        if (
            not self._session_lease_is_current_locked(lease)
            or lease.turn_id is None
            or lease.route_generation is None
            or lease.turn_id not in self._turn_sources
        ):
            return False
        return (
            lease.turn_id not in self._turn_attempts
            and self._turn_generations.get(lease.turn_id)
            == lease.route_generation.value
        )

    def _advance_session_locked(self) -> None:
        self._session_generation = SessionGeneration(
            self._session_generation.value + 1
        )
        self._turn_attempts.clear()
        self._turn_generations.clear()
        self._turn_sources.clear()
        self._transient_turns.clear()
        self._assistant_sources.clear()
        self._commits.clear()

    def _invalidate_transition(self, reason: str) -> None:
        with self._lock:
            callback = self._transition_invalidator
        if callback is not None:
            result = callback(str(reason or "session_transition"))
            if isinstance(result, CommandResult) and not result.accepted:
                failure = result.failure
                raise SessionEffectDrainingError(
                    RuntimeFailure(
                        "session_effect_draining",
                        (
                            failure.message
                            if failure is not None
                            else "Session effects did not drain before transition."
                        ),
                        failure.cause if failure is not None else None,
                    )
                )

    def _begin_session_transition(self) -> None:
        thread_id = threading.get_ident()
        with self._session_transition_registration_lock:
            with self._session_effect_condition:
                owns_admission = any(
                    admission.thread_id == thread_id
                    for admission in self._session_effect_admissions.values()
                )
                if owns_admission or (
                    self._session_transition_active
                    and self._session_transition_owner_thread_id == thread_id
                ):
                    raise SessionTransitionReentrancyError(
                        "Cannot reset or load from an admitted session effect."
                    )
                self._session_transition_count += 1
                self._session_effect_admission_open = False
                self._session_effect_condition.notify_all()
        try:
            with self._session_effect_condition:
                deadline = (
                    time.monotonic()
                    + self._session_effect_drain_timeout_seconds
                )
                drained = self._session_effect_condition.wait_for(
                    lambda: not self._session_transition_active
                    and not self._session_effect_admissions,
                    timeout=max(0.0, deadline - time.monotonic()),
                )
                if not drained:
                    raise SessionEffectDrainingError(
                        RuntimeFailure(
                            "session_effect_draining",
                            "Session effects did not drain before transition timed out.",
                        )
                    )
                self._session_transition_active = True
                self._session_transition_owner_thread_id = thread_id
        except BaseException:
            self._cancel_session_transition_registration()
            raise

    def _cancel_session_transition_registration(self) -> None:
        with self._session_transition_registration_lock:
            with self._session_effect_condition:
                self._session_transition_count -= 1
                if self._session_transition_count == 0:
                    self._session_effect_admission_open = True
                self._session_effect_condition.notify_all()

    def _end_session_transition(self) -> None:
        thread_id = threading.get_ident()
        with self._session_transition_registration_lock:
            with self._session_effect_condition:
                if (
                    not self._session_transition_active
                    or self._session_transition_owner_thread_id != thread_id
                ):
                    raise RuntimeError("Session transition ownership was lost")
                self._session_transition_active = False
                self._session_transition_owner_thread_id = None
                self._session_transition_count -= 1
                if self._session_transition_count == 0:
                    self._session_effect_admission_open = True
                self._session_effect_condition.notify_all()

    def _prune_turn_attempts_locked(self) -> None:
        retained = {turn_id.value for turn_id in self._turn_sources}
        self._turn_attempts = {
            turn_id: attempt
            for turn_id, attempt in self._turn_attempts.items()
            if turn_id.value in retained
        }
        self._turn_generations = {
            turn_id: generation
            for turn_id, generation in self._turn_generations.items()
            if turn_id.value in retained
        }

    def _remove_turn_source_locked(self, turn_id: TurnId) -> None:
        self._turn_sources.pop(turn_id, None)
        self._transient_turns.pop(turn_id, None)
        self._turn_attempts.pop(turn_id, None)
        self._turn_generations.pop(turn_id, None)
        self._assistant_sources = {
            message_id: source_turn_id
            for message_id, source_turn_id in self._assistant_sources.items()
            if source_turn_id != turn_id
        }
        self._commits = {
            key: result
            for key, result in self._commits.items()
            if key[1] != turn_id
        }


def _new_message(
    *,
    role: str,
    content: str,
    metadata: Mapping[str, object],
) -> ConversationMessage:
    return ConversationMessage(
        message_id=uuid.uuid4().hex,
        role=str(role),
        content=str(content),
        metadata=_clean_metadata(metadata),
    )


def _message_from_mapping(
    message: Mapping[str, object],
    *,
    message_id: str | None = None,
) -> ConversationMessage:
    if not isinstance(message, Mapping):
        raise TypeError("Conversation messages must be mappings")
    metadata = {
        str(key): value
        for key, value in message.items()
        if str(key) not in {"role", "content"}
    }
    return ConversationMessage(
        message_id=message_id or uuid.uuid4().hex,
        role=str(message.get("role", "") or ""),
        content=str(message.get("content", "") or ""),
        metadata=_freeze_mapping(metadata),
    )


def _preserve_replacement_message_ids(
    previous: Sequence[ConversationMessage],
    replacements: tuple[ConversationMessage, ...],
) -> tuple[ConversationMessage, ...]:
    """Reconcile unchanged public history entries without exposing opaque IDs."""

    previous_mappings = tuple(_message_mapping(message) for message in previous)
    replacement_mappings = tuple(
        _message_mapping(message) for message in replacements
    )
    suffix_start = len(previous_mappings) - len(replacement_mappings)
    if suffix_start >= 0 and all(
        previous_mappings[suffix_start + index] == replacement
        for index, replacement in enumerate(replacement_mappings)
    ):
        matching_blocks = ((suffix_start, 0, len(replacements)),)
    else:
        previous_tokens, replacement_tokens = _message_alignment_tokens(
            previous_mappings,
            replacement_mappings,
        )
        matching_blocks = SequenceMatcher(
            None,
            previous_tokens,
            replacement_tokens,
            autojunk=False,
        ).get_matching_blocks()

    reconciled = list(replacements)
    for previous_start, replacement_start, size in matching_blocks:
        for offset in range(size):
            existing = previous[previous_start + offset]
            replacement = replacements[replacement_start + offset]
            reconciled[replacement_start + offset] = ConversationMessage(
                message_id=existing.message_id,
                role=replacement.role,
                content=replacement.content,
                metadata=replacement.metadata,
            )
    # Revision-checked assistant edits retain their transaction tag. Preserve
    # that unique source identity, never guessing from position or content.
    previous_assistants: dict[str, list[ConversationMessage]] = {}
    replacement_assistants: dict[str, list[int]] = {}
    for message in previous:
        transaction_id = str(message.metadata.get("normal_chat_transaction_id") or "")
        if message.role.strip().lower() == "assistant" and transaction_id:
            previous_assistants.setdefault(transaction_id, []).append(message)
    for index, message in enumerate(replacements):
        transaction_id = str(message.metadata.get("normal_chat_transaction_id") or "")
        if message.role.strip().lower() == "assistant" and transaction_id:
            replacement_assistants.setdefault(transaction_id, []).append(index)
    assigned_ids = {message.message_id for message in reconciled}
    for transaction_id, indexes in replacement_assistants.items():
        candidates = previous_assistants.get(transaction_id, ())
        if len(indexes) != 1 or len(candidates) != 1:
            continue
        existing = candidates[0]
        if existing.message_id in assigned_ids:
            continue
        index = indexes[0]
        replacement = reconciled[index]
        reconciled[index] = ConversationMessage(
            message_id=existing.message_id,
            role=replacement.role,
            content=replacement.content,
            metadata=replacement.metadata,
        )
        assigned_ids.add(existing.message_id)
    # A completed transaction retains its accepted input as the exact source for
    # regeneration.  Full-history editing may change that input's content, so it
    # will not align above; its unique transaction tag must preserve the hidden
    # message id that the retained regeneration source owns.
    previous_inputs: dict[str, list[ConversationMessage]] = {}
    replacement_inputs: dict[str, list[int]] = {}
    for message in previous:
        transaction_id = str(message.metadata.get("normal_chat_transaction_id") or "")
        if message.role.strip().lower() != "assistant" and transaction_id:
            previous_inputs.setdefault(transaction_id, []).append(message)
    for index, message in enumerate(replacements):
        transaction_id = str(message.metadata.get("normal_chat_transaction_id") or "")
        if message.role.strip().lower() != "assistant" and transaction_id:
            replacement_inputs.setdefault(transaction_id, []).append(index)
    for transaction_id, indexes in replacement_inputs.items():
        candidates = previous_inputs.get(transaction_id, ())
        if len(indexes) != 1 or len(candidates) != 1:
            continue
        existing = candidates[0]
        if existing.message_id in assigned_ids:
            continue
        index = indexes[0]
        replacement = reconciled[index]
        reconciled[index] = ConversationMessage(
            message_id=existing.message_id,
            role=replacement.role,
            content=replacement.content,
            metadata=replacement.metadata,
        )
        assigned_ids.add(existing.message_id)
    return tuple(reconciled)


def _message_alignment_tokens(
    previous: Sequence[Mapping[str, object]],
    replacements: Sequence[Mapping[str, object]],
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    equivalence_classes: list[Mapping[str, object]] = []

    def token_for(message: Mapping[str, object]) -> int:
        for token, candidate in enumerate(equivalence_classes):
            if candidate == message:
                return token
        equivalence_classes.append(message)
        return len(equivalence_classes) - 1

    return (
        tuple(token_for(message) for message in previous),
        tuple(token_for(message) for message in replacements),
    )


def _clean_metadata(metadata: Mapping[str, object]) -> Mapping[str, object]:
    return _freeze_mapping(
        {
            str(key): value
            for key, value in metadata.items()
            if str(key) not in {"role", "content"}
        }
    )


def _message_mapping(message: ConversationMessage) -> dict[str, object]:
    result = {
        "role": message.role,
        "content": message.content,
    }
    result.update(
        {str(key): _thaw(value) for key, value in message.metadata.items()}
    )
    return result


def _stale_session_result() -> CommandResult[AssistantCommit]:
    return CommandResult(
        accepted=False,
        failure=RuntimeFailure(
            "stale_session",
            "Work lease no longer owns the current conversation session.",
        ),
    )


__all__ = [
    "AcceptedTurn",
    "AssistantCommit",
    "ConversationMessage",
    "ConversationService",
    "ConversationSnapshot",
    "RegenerateTurn",
    "SessionEffectAdmission",
    "SessionEffectDrainingError",
    "SessionTransitionReentrancyError",
]
