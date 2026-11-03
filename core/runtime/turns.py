"""Accepted-turn snapshots, cancellation, and exactly-once terminal status."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import threading
from types import MappingProxyType
from typing import Protocol

from core import chat_providers
from core.persona_overrides import apply_persona_overrides, read_persona_overrides
from core.runtime.config import RuntimeConfigService, RuntimeConfigSnapshot
from core.runtime.contracts import (
    CancellationToken,
    CommandResult,
    IdentityRelayTurnState,
    RuntimeFailure,
)
from core.runtime.conversation import (
    AcceptedTurn,
    AssistantCommit,
    ConversationService,
)
from core.runtime.identifiers import RunId, TurnId, WorkLease
from core.runtime.providers import ProviderSelection


class TurnTerminalStatus(str, Enum):
    COMPLETED = "completed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class UserInput:
    """One completed input ready to cross the accepted-turn boundary."""

    text: str
    role: str
    metadata: Mapping[str, object]
    source: str
    persist: bool
    source_lease: WorkLease | None = None
    expected_history_revision: int | None = None

    @classmethod
    def completed(
        cls,
        text: str,
        *,
        role: str = "user",
        metadata: Mapping[str, object] | None = None,
        source: str = "typed",
        persist: bool = True,
        source_lease: WorkLease | None = None,
        expected_history_revision: int | None = None,
    ) -> UserInput:
        return cls(
            text=str(text or ""),
            role=str(role or "user"),
            metadata=MappingProxyType(dict(metadata or {})),
            source=str(source or "typed"),
            persist=bool(persist),
            source_lease=source_lease,
            expected_history_revision=expected_history_revision,
        )


@dataclass(frozen=True, slots=True)
class TurnSnapshot:
    lease: WorkLease
    accepted_turn: AcceptedTurn
    config: RuntimeConfigSnapshot
    provider: ProviderSelection
    identity_relay: IdentityRelayTurnState
    cancellation: CancellationToken


@dataclass(frozen=True, slots=True)
class TurnTerminal:
    turn_id: TurnId
    lease: WorkLease
    status: TurnTerminalStatus
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TurnEffectAdmission:
    """Irrevocable authority captured from one exact active turn route."""

    lease: WorkLease
    purpose: str


@dataclass(frozen=True, slots=True)
class _TerminalTransition:
    snapshot: TurnSnapshot
    terminal: TurnTerminal


class ProviderSelectionPort(Protocol):
    def capture_selection(
        self,
        config: RuntimeConfigSnapshot,
    ) -> ProviderSelection: ...


class IdentityRelayFreezePort(Protocol):
    def freeze_for_turn(
        self,
        lease: WorkLease,
        provider: ProviderSelection,
    ) -> IdentityRelayTurnState: ...

    def discard_turn(
        self,
        turn_id: TurnId,
        *,
        lease: WorkLease | None = None,
    ) -> None: ...


class RuntimeLeaseSource(Protocol):
    @property
    def run_id(self) -> RunId: ...


TerminalCallback = Callable[[TurnTerminal], None]
InvalidationCallback = Callable[[TurnTerminal], None]
PreInvalidationGuard = Callable[[TurnTerminal], CommandResult[object] | None]


class TurnCoordinator:
    """Own active accepted turns without executing provider or speech policy."""

    def __init__(
        self,
        *,
        config: RuntimeConfigService,
        conversation: ConversationService,
        providers: ProviderSelectionPort,
        identity_relay: IdentityRelayFreezePort,
        runtime: RuntimeLeaseSource,
        on_terminal: TerminalCallback | None = None,
        on_invalidate: InvalidationCallback | None = None,
        pre_invalidation_guard: PreInvalidationGuard | None = None,
        persona_root: str | Path | None = None,
    ) -> None:
        self._config = config
        self._persona_root = Path(persona_root) if persona_root is not None else None
        self._conversation = conversation
        self._providers = providers
        self._identity_relay = identity_relay
        self._runtime = runtime
        self._on_terminal = on_terminal
        self._on_invalidate = on_invalidate
        self._pre_invalidation_guard = pre_invalidation_guard
        self._lock = threading.RLock()
        self._active: dict[TurnId, TurnSnapshot] = {}
        self._terminals: dict[tuple[TurnId, object], TurnTerminal] = {}
        self._reservations: dict[tuple[TurnId, object], object] = {}
        self._conversation.set_transition_invalidator(self.invalidate_all)

    def capture_detached_selection(self) -> tuple[RuntimeConfigSnapshot, ProviderSelection]:
        """Read the same provider selection as acceptance without taking a turn."""
        config = self._capture_request_config()
        return config, self._capture_provider_selection(config)

    def _capture_provider_selection(self, config: RuntimeConfigSnapshot) -> ProviderSelection:
        selection = self._providers.capture_selection(config)
        expected = config.values.get("_persona_llm_provider")
        if expected and selection.provider_id != expected:
            raise ValueError(f"Persona language model provider {expected!r} is unavailable.")
        return selection

    def _capture_request_config(self) -> RuntimeConfigSnapshot:
        config = self._config.snapshot()
        if self._persona_root is None:
            return config
        overrides = read_persona_overrides(self._persona_root, active=True)
        values = apply_persona_overrides(config.values, overrides)
        if overrides["llm_enabled"] and chat_providers.get_provider(overrides["llm_provider"]) is None:
            raise ValueError(
                f"Persona language model provider {overrides['llm_provider']!r} is unavailable."
            )
        if values == dict(config.values):
            return config
        # RuntimeConfigService freezes nested containers without publishing a
        # configuration update or notifying subscribers of request-only policy.
        frozen = RuntimeConfigService(values).snapshot()
        return RuntimeConfigSnapshot(config.revision, frozen.values)

    def accept(self, completed_input: UserInput) -> CommandResult[TurnSnapshot]:
        text = str(completed_input.text or "").strip()
        if not text:
            return _failure("invalid_input", "A completed turn requires non-empty text.")
        coherent = self._coherent_run_failure()
        if coherent is not None:
            return CommandResult(False, failure=coherent)

        if completed_input.source_lease is None and completed_input.expected_history_revision is None:
            accepted_turn = self._conversation.accept_user_turn(
                role=completed_input.role,
                content=text,
                metadata=dict(completed_input.metadata),
                persist=completed_input.persist,
            )
        else:
            source_lease = completed_input.source_lease or self._conversation.session_lease()
            source_key = (
                source_lease.turn_id,
                source_lease.route_generation,
            )
            with self._lock:
                source_terminal = self._terminals.get(source_key)
                allow_closed_turn = (
                    source_terminal is not None
                    and source_terminal.lease == source_lease
                    and source_terminal.status is TurnTerminalStatus.INTERRUPTED
                )
            source_acceptance = self._conversation.accept_user_turn_from_source(
                source_lease,
                role=completed_input.role,
                content=text,
                metadata=dict(completed_input.metadata),
                persist=completed_input.persist,
                allow_closed_turn=allow_closed_turn,
                expected_revision=completed_input.expected_history_revision,
            )
            if not source_acceptance.accepted or source_acceptance.value is None:
                return CommandResult(False, failure=source_acceptance.failure)
            accepted_turn = source_acceptance.value
        admission = self._conversation.admit_session_effect(accepted_turn.lease)
        if admission is None:
            self._conversation.discard_accepted_turn(accepted_turn.lease)
            return _failure(
                "stale_turn",
                "The conversation changed while the turn was accepted.",
            )

        try:
            if self._runtime.run_id != accepted_turn.lease.run_id:
                self._conversation.discard_accepted_turn(accepted_turn.lease)
                return _failure(
                    "stale_runtime",
                    "The runtime changed while the turn was accepted.",
                )
            config = self._capture_request_config()
            provider = self._capture_provider_selection(config)
        except BaseException as exc:
            self._conversation.discard_accepted_turn(accepted_turn.lease)
            return _failure(
                "provider_freeze_failed",
                str(exc) or "The provider selection could not be frozen.",
                exc,
            )
        else:
            try:
                relay = self._identity_relay.freeze_for_turn(
                    accepted_turn.lease,
                    provider,
                )
            except BaseException as exc:
                self._conversation.discard_accepted_turn(accepted_turn.lease)
                return _failure(
                    "identity_relay_freeze_failed",
                    str(exc) or "Identity Relay state could not be frozen.",
                    exc,
                )
            snapshot = TurnSnapshot(
                lease=accepted_turn.lease,
                accepted_turn=accepted_turn,
                config=config,
                provider=provider,
                identity_relay=relay,
                cancellation=CancellationToken(),
            )
            prior_transition = None
            with self._lock:
                prior = self._active.get(accepted_turn.turn_id)
                if prior is not None:
                    prior_transition = self._terminalize_locked(
                        prior,
                        TurnTerminalStatus.SUPERSEDED,
                        "new_attempt",
                    )
                self._active[accepted_turn.turn_id] = snapshot
        finally:
            self._conversation.release_session_effect(admission)
        self._apply_terminal_transition(prior_transition)
        return CommandResult(True, value=snapshot)

    def regenerate(self, *, source_turn_id: TurnId | None = None, expected_target=None) -> CommandResult[TurnSnapshot]:
        coherent = self._coherent_run_failure()
        if coherent is not None:
            return CommandResult(False, failure=coherent)
        try:
            regeneration = self._conversation.begin_regenerate(source_turn_id,
                **({'expected_target': expected_target} if expected_target is not None else {}))
        except RuntimeError as exc:
            return _failure("regenerate_unavailable", str(exc), exc)

        admission = self._conversation.admit_session_effect(regeneration.lease)
        if admission is None:
            return _failure(
                "stale_turn",
                "The conversation changed while regeneration was accepted.",
            )
        failure = None
        snapshot = None
        try:
            if self._runtime.run_id != regeneration.lease.run_id:
                failure = RuntimeFailure(
                    "stale_runtime",
                    "The runtime changed while regeneration was accepted.",
                )
            else:
                config = self._capture_request_config()
                provider = self._capture_provider_selection(config)
                relay = self._identity_relay.freeze_for_turn(
                    regeneration.lease,
                    provider,
                )
                accepted_turn = AcceptedTurn(
                    turn_id=regeneration.source_turn_id,
                    lease=regeneration.lease,
                    message=regeneration.source,
                )
                snapshot = TurnSnapshot(
                    lease=regeneration.lease,
                    accepted_turn=accepted_turn,
                    config=config,
                    provider=provider,
                    identity_relay=relay,
                    cancellation=CancellationToken(),
                )
        except BaseException as exc:
            failure = RuntimeFailure(
                "turn_freeze_failed",
                str(exc) or "The regenerated turn could not be frozen.",
                exc,
            )
        finally:
            prior_transition = None
            with self._lock:
                prior = self._active.get(regeneration.source_turn_id)
                if prior is not None:
                    prior_transition = self._terminalize_locked(
                        prior,
                        TurnTerminalStatus.SUPERSEDED,
                        "regenerate",
                    )
                if snapshot is not None:
                    self._active[regeneration.source_turn_id] = snapshot
            self._conversation.release_session_effect(admission)
        self._apply_terminal_transition(prior_transition)
        if failure is not None:
            return CommandResult(False, failure=failure)
        assert snapshot is not None
        return CommandResult(True, value=snapshot)

    def cancel(
        self,
        turn_id: TurnId,
        reason: str,
        *,
        lease: WorkLease,
    ) -> CommandResult[None]:
        with self._lock:
            snapshot = self._active.get(turn_id)
            if snapshot is None:
                return _failure(
                    "turn_not_active",
                    "The turn is no longer active.",
                )
            expected = self._expected_lease_failure(snapshot, lease)
            if expected is not None:
                return CommandResult(False, failure=expected)
        stale = self._stale_failure(snapshot)
        status = (
            TurnTerminalStatus.SUPERSEDED
            if stale is not None
            else TurnTerminalStatus.CANCELED
        )
        terminal_reason = stale.category if stale is not None else str(
            reason or "cancelled"
        )
        guarded = self._guard_pre_invalidation(snapshot, status, terminal_reason)
        if not guarded.accepted:
            return CommandResult(False, failure=guarded.failure)
        with self._lock:
            if self._active.get(turn_id) is not snapshot:
                return _failure(
                    "superseded_route",
                    "The turn route changed while cancellation was validated.",
                )
            transition = self._terminalize_locked(
                snapshot,
                status,
                terminal_reason,
            )
        result = (
            CommandResult(False, failure=stale)
            if stale is not None
            else CommandResult(True)
        )
        self._apply_terminal_transition(transition)
        return result

    def cancel_current(
        self,
        turn_id: TurnId,
        reason: str,
    ) -> CommandResult[None]:
        """Cancel the route currently owned by a user command, if one exists."""

        with self._lock:
            snapshot = self._active.get(turn_id)
            if snapshot is None:
                return _failure("turn_not_active", "The turn is no longer active.")
            lease = snapshot.lease
        return self.cancel(turn_id, reason, lease=lease)

    def invalidate(
        self,
        *,
        reason: str,
        lease: WorkLease | None = None,
        status: TurnTerminalStatus = TurnTerminalStatus.CANCELED,
    ) -> CommandResult[tuple[TurnTerminal, ...]]:
        """Synchronously invalidate one exact route or the current runtime scope."""

        if status is TurnTerminalStatus.COMPLETED:
            return _failure(
                "invalid_terminal_status",
                "Invalidation requires a non-completed terminal status.",
            )
        transitions: list[_TerminalTransition] = []
        with self._lock:
            if lease is None:
                snapshots = tuple(self._active.values())
            else:
                turn_id = lease.turn_id
                snapshot = self._active.get(turn_id) if turn_id is not None else None
                if snapshot is None:
                    return _failure("turn_not_active", "The turn is no longer active.")
                expected = self._expected_lease_failure(snapshot, lease)
                if expected is not None:
                    return CommandResult(False, failure=expected)
                snapshots = (snapshot,)
        terminal_reason = str(reason or "invalidated")
        for snapshot in snapshots:
            guarded = self._guard_pre_invalidation(
                snapshot,
                status,
                terminal_reason,
            )
            if not guarded.accepted:
                return CommandResult(False, failure=guarded.failure)
        with self._lock:
            for snapshot in snapshots:
                if self._active.get(snapshot.accepted_turn.turn_id) is not snapshot:
                    return _failure(
                        "superseded_route",
                        "A turn route changed while invalidation was guarded.",
                    )
            for snapshot in snapshots:
                transition = self._terminalize_locked(
                    snapshot,
                    status,
                    terminal_reason,
                )
                if transition is not None:
                    transitions.append(transition)
        for transition in transitions:
            self._apply_terminal_transition(transition)
        return CommandResult(
            True,
            value=tuple(transition.terminal for transition in transitions),
        )

    def invalidate_all(self, reason: str) -> CommandResult[tuple[TurnTerminal, ...]]:
        return self.invalidate(
            reason=str(reason or "session_transition"),
            status=TurnTerminalStatus.SUPERSEDED,
        )

    def finish(
        self,
        turn_id: TurnId,
        status: TurnTerminalStatus,
        *,
        lease: WorkLease,
    ) -> CommandResult[None]:
        if not isinstance(status, TurnTerminalStatus):
            return _failure("invalid_terminal_status", "Unknown turn terminal status.")
        transition = None
        with self._lock:
            snapshot = self._active.get(turn_id)
            if snapshot is None:
                return _failure(
                    "turn_not_active",
                    "The turn is no longer active.",
                )
            expected = self._expected_lease_failure(snapshot, lease)
            if expected is not None:
                return CommandResult(False, failure=expected)
        stale = self._stale_failure(snapshot)
        terminal_status = (
            TurnTerminalStatus.SUPERSEDED if stale is not None else status
        )
        terminal_reason = stale.category if stale is not None else status.value
        guarded = self._guard_pre_invalidation(
            snapshot,
            terminal_status,
            terminal_reason,
        )
        if not guarded.accepted:
            return CommandResult(False, failure=guarded.failure)
        with self._lock:
            if self._active.get(turn_id) is not snapshot:
                return _failure(
                    "superseded_route",
                    "The turn route changed while completion was validated.",
                )
            transition = self._terminalize_locked(
                snapshot,
                terminal_status,
                terminal_reason,
            )
        result = (
            CommandResult(False, failure=stale)
            if stale is not None
            else CommandResult(True)
        )
        self._apply_terminal_transition(transition)
        return result

    def complete_provider(
        self,
        turn_id: TurnId,
        text: str,
        *,
        metadata: Mapping[str, object] | None = None,
        lease: WorkLease,
    ) -> CommandResult[AssistantCommit]:
        transition = None
        reservation = None
        reservation_key = None
        with self._lock:
            snapshot = self._active.get(turn_id)
            if snapshot is None:
                return _failure(
                    "turn_not_active",
                    "The provider result no longer owns an active turn.",
                )
            expected = self._expected_lease_failure(snapshot, lease)
            if expected is not None:
                return CommandResult(False, failure=expected)
        stale = self._stale_failure(snapshot)
        with self._lock:
            if self._active.get(turn_id) is not snapshot:
                return _failure(
                    "superseded_route",
                    "The provider route changed while its result was validated.",
                )
            if stale is not None:
                transition = self._terminalize_locked(
                    snapshot,
                    TurnTerminalStatus.SUPERSEDED,
                    stale.category,
                )
                result = CommandResult(False, failure=stale)
            elif snapshot.cancellation.cancelled:
                result = _failure(
                    "turn_cancelled",
                    "The provider result belongs to a cancelled turn.",
                )
            else:
                reservation_key = (turn_id, snapshot.lease.route_generation)
                if reservation_key in self._reservations:
                    return _failure(
                        "completion_in_progress",
                        "The exact turn route already owns a provider completion.",
                    )
                reservation = object()
                self._reservations[reservation_key] = reservation
                result = None
        if reservation is None:
            self._apply_terminal_transition(transition)
            return result

        try:
            result = self._conversation.commit_assistant(
                snapshot.lease,
                content=str(text or ""),
                metadata=dict(metadata or {}),
            )
        except BaseException:
            with self._lock:
                if self._reservations.get(reservation_key) is reservation:
                    self._reservations.pop(reservation_key, None)
            raise

        rollback_commit = None
        with self._lock:
            owns_reservation = (
                self._reservations.get(reservation_key) is reservation
            )
            if owns_reservation:
                self._reservations.pop(reservation_key, None)
            if not owns_reservation or self._active.get(turn_id) is not snapshot:
                if result.accepted:
                    rollback_commit = result.value
                result = _failure(
                    "superseded_route",
                    "The provider result lost ownership of its exact turn route.",
                )
            elif not result.accepted and result.failure is not None:
                transition = self._terminalize_locked(
                        snapshot,
                        TurnTerminalStatus.SUPERSEDED,
                        result.failure.category,
                    )
        if rollback_commit is not None:
            self._conversation.rollback_assistant_commit(
                snapshot.lease,
                rollback_commit,
            )
        self._apply_terminal_transition(transition)
        return result

    def has_active_turns(self) -> bool:
        with self._lock:
            return bool(self._active)

    def snapshot(self, turn_id: TurnId) -> TurnSnapshot | None:
        with self._lock:
            return self._active.get(turn_id)

    def admit_effect(
        self,
        lease: WorkLease,
        *,
        purpose: str,
    ) -> TurnEffectAdmission | None:
        """Commit one exact active route as eligible for a downstream effect."""

        with self._lock:
            turn_id = lease.turn_id
            snapshot = self._active.get(turn_id) if turn_id is not None else None
            if (
                snapshot is None
                or snapshot.lease is not lease
                or snapshot.cancellation.cancelled
            ):
                return None
            return TurnEffectAdmission(
                lease=lease,
                purpose=str(purpose or "turn_effect"),
            )

    def committed_effect_lease_is_valid(self, lease: WorkLease) -> bool:
        """Validate an effect against an exact active or completed committed route."""

        with self._lock:
            if not self._committed_effect_route_allowed_locked(lease):
                return False
        commit = self._conversation.assistant_commit_for(lease)
        if commit is None:
            return False
        with self._lock:
            return self._committed_effect_route_allowed_locked(lease)

    def _committed_effect_route_allowed_locked(self, lease: WorkLease) -> bool:
        turn_id = lease.turn_id
        if turn_id is None:
            return False
        active = self._active.get(turn_id)
        if active is not None:
            return active.lease == lease and not active.cancellation.cancelled
        terminal = self._terminals.get((turn_id, lease.route_generation))
        return bool(
            terminal is not None
            and terminal.lease == lease
            and terminal.status is TurnTerminalStatus.COMPLETED
        )

    def _coherent_run_failure(self) -> RuntimeFailure | None:
        runtime_run_id = self._runtime.run_id
        conversation_run_id = self._conversation.run_id
        if runtime_run_id == conversation_run_id:
            return None
        return RuntimeFailure(
            "runtime_generation_mismatch",
            "Runtime and conversation run generations are not coherent.",
        )

    def _stale_failure(self, snapshot: TurnSnapshot) -> RuntimeFailure | None:
        if self._runtime.run_id != snapshot.lease.run_id:
            return RuntimeFailure(
                "stale_runtime",
                "The turn belongs to an older runtime generation.",
            )
        if not self._conversation.turn_lease_is_current(snapshot.lease):
            return RuntimeFailure(
                "stale_turn",
                "The turn belongs to an older conversation route.",
            )
        return None

    @staticmethod
    def _expected_lease_failure(
        snapshot: TurnSnapshot,
        lease: WorkLease,
    ) -> RuntimeFailure | None:
        if lease == snapshot.lease:
            return None
        return RuntimeFailure(
            "superseded_route",
            "A newer route owns this accepted turn.",
        )

    def _guard_pre_invalidation(
        self,
        snapshot: TurnSnapshot,
        status: TurnTerminalStatus,
        reason: str,
    ) -> CommandResult[TurnTerminal]:
        terminal = TurnTerminal(
            turn_id=snapshot.accepted_turn.turn_id,
            lease=snapshot.lease,
            status=status,
            reason=str(reason or ""),
        )
        callback = self._pre_invalidation_guard
        if callback is None:
            return CommandResult(True, terminal)
        try:
            guarded = callback(terminal)
        except BaseException as exc:
            return _failure(
                "route_effect_guard_failed",
                str(exc) or "Route effect invalidation guard failed.",
                exc,
            )
        if isinstance(guarded, CommandResult) and not guarded.accepted:
            return CommandResult(False, failure=guarded.failure)
        return CommandResult(True, terminal)

    def _terminalize_locked(
        self,
        snapshot: TurnSnapshot,
        status: TurnTerminalStatus,
        reason: str,
    ) -> _TerminalTransition | None:
        key = (snapshot.accepted_turn.turn_id, snapshot.lease.route_generation)
        existing = self._terminals.get(key)
        if existing is not None:
            return None
        if status is not TurnTerminalStatus.COMPLETED:
            snapshot.cancellation.cancel(reason)
        terminal = TurnTerminal(
            turn_id=snapshot.accepted_turn.turn_id,
            lease=snapshot.lease,
            status=status,
            reason=str(reason or ""),
        )
        self._terminals[key] = terminal
        self._reservations.pop(key, None)
        if self._active.get(snapshot.accepted_turn.turn_id) is snapshot:
            del self._active[snapshot.accepted_turn.turn_id]
        return _TerminalTransition(snapshot, terminal)

    def _apply_terminal_transition(
        self,
        transition: _TerminalTransition | None,
    ) -> None:
        if transition is None:
            return
        self._identity_relay.discard_turn(
            transition.terminal.turn_id,
            lease=transition.snapshot.lease,
        )
        self._conversation.release_transient_turn(transition.snapshot.lease)
        self._conversation.invalidate_turn_route(transition.snapshot.lease)
        if transition.terminal.status is not TurnTerminalStatus.COMPLETED:
            callback = self._on_invalidate
            if callback is not None:
                callback(transition.terminal)
        self._notify_terminal(transition.terminal)

    def _notify_terminal(self, terminal: TurnTerminal | None) -> None:
        callback = self._on_terminal
        if terminal is not None and callback is not None:
            callback(terminal)


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(
        False,
        failure=RuntimeFailure(category, message, cause),
    )


__all__ = [
    "IdentityRelayFreezePort",
    "ProviderSelectionPort",
    "RuntimeLeaseSource",
    "TurnCoordinator",
    "TurnEffectAdmission",
    "TurnSnapshot",
    "TurnTerminal",
    "TurnTerminalStatus",
    "UserInput",
]
