"""Generation-bound ownership for one active speech controller and its setup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
import time
from typing import Protocol, TypeVar

from core.runtime.contracts import CancellationToken, CommandResult, RuntimeFailure
from core.runtime.identifiers import WorkLease


T = TypeVar("T")


@dataclass(frozen=True, slots=True, init=False)
class ControllerExecutionGeneration:
    _token: object

    @classmethod
    def _new(cls) -> "ControllerExecutionGeneration":
        generation = object.__new__(cls)
        object.__setattr__(generation, "_token", object())
        return generation


@dataclass(frozen=True, slots=True, init=False)
class ControllerSetupGeneration:
    _token: object

    @classmethod
    def _new(cls) -> "ControllerSetupGeneration":
        generation = object.__new__(cls)
        object.__setattr__(generation, "_token", object())
        return generation


@dataclass(frozen=True, slots=True, init=False)
class ControllerRegistrationGeneration:
    _token: object

    @classmethod
    def _new(cls) -> "ControllerRegistrationGeneration":
        generation = object.__new__(cls)
        object.__setattr__(generation, "_token", object())
        return generation


@dataclass(frozen=True, slots=True, init=False)
class ControllerInvalidationGeneration:
    _owner: object
    _binding: WorkLease | None
    _token: object

    @classmethod
    def _new(
        cls,
        owner: object,
        binding: WorkLease | None,
    ) -> "ControllerInvalidationGeneration":
        generation = object.__new__(cls)
        object.__setattr__(generation, "_owner", owner)
        object.__setattr__(generation, "_binding", binding)
        object.__setattr__(generation, "_token", object())
        return generation


class ControllerSetupPhase(str, Enum):
    STAGED = "staged"
    ACTIVE = "active"
    TRANSFERRED = "transferred"
    DRAINING = "draining"
    RETIRED = "retired"


class RouteEffectPhase(str, Enum):
    ACTIVE_ROUTE = "active_route"
    DRAINING = "draining"
    RETIRED = "retired"


class PlaybackOwnerIdentity(Protocol):
    generation: int
    lease: WorkLease


@dataclass(frozen=True, slots=True)
class ControllerCancellationSignal:
    """A narrow cancellation signal made from event flags or one runtime token."""

    _events: tuple[object, ...]
    _token: CancellationToken | None = None

    @classmethod
    def from_events(cls, *events: object) -> "ControllerCancellationSignal":
        return cls(tuple(event for event in events if event is not None))

    @classmethod
    def from_token(
        cls,
        token: CancellationToken,
        *events: object,
    ) -> "ControllerCancellationSignal":
        return cls(tuple(event for event in events if event is not None), token)

    def request(self, reason: str = "controller_cancelled") -> None:
        if self._token is not None:
            self._token.cancel(str(reason or "controller_cancelled"))
        for event in self._events:
            setter = getattr(event, "set", None)
            if not callable(setter):
                continue
            try:
                setter()
            except BaseException:
                continue


@dataclass(slots=True)
class _ControllerSetupTerminal:
    failure: RuntimeFailure | None = None


@dataclass(frozen=True, slots=True)
class ControllerSetupLease:
    execution_generation: ControllerExecutionGeneration
    setup_generation: ControllerSetupGeneration
    binding: WorkLease | None
    _owner: object = field(repr=False, compare=False)
    _terminal: _ControllerSetupTerminal = field(
        default_factory=_ControllerSetupTerminal,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class ControllerRegistrationHandle:
    execution_generation: ControllerExecutionGeneration
    setup_generation: ControllerSetupGeneration
    registration_generation: ControllerRegistrationGeneration
    binding: WorkLease | None
    controller: object
    cancellation: ControllerCancellationSignal


@dataclass(frozen=True, slots=True)
class ControllerRegistrySnapshot:
    setup: ControllerSetupLease | None
    setup_phase: ControllerSetupPhase
    in_flight_steps: int
    registration: ControllerRegistrationHandle | None
    route_phase: RouteEffectPhase
    route_in_flight_steps: int
    route_owner: "RouteEffectOwner | None"


@dataclass(frozen=True, slots=True)
class ControllerBindingInvalidation:
    setup: ControllerSetupLease | None
    registrations: tuple[ControllerRegistrationHandle, ...]


class ControllerSetupFailure(RuntimeError):
    def __init__(self, failure: RuntimeFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class RouteEffectOwner:
    """Exact authority for terminal effects owned by one playback route."""

    __slots__ = (
        "_node",
        "_record",
        "_registry",
        "lease",
        "playback_generation",
        "purpose",
        "registration_generation",
    )

    def __init__(
        self,
        registry: "ControllerSetupRegistry",
        record: "_RouteEffectRecord",
        node: "_RouteEffectNode",
    ) -> None:
        self._registry = registry
        self._record = record
        self._node = node
        self.registration_generation = record.registration.registration_generation
        self.playback_generation = int(record.playback_owner.generation)
        self.lease = record.lease
        self.purpose = node.purpose

    @property
    def cancellation(self) -> CancellationToken:
        return self._node.cancellation

    def run_step(
        self,
        purpose: str,
        operation: Callable[[], T],
    ) -> CommandResult[T]:
        return self._registry.run_route_step(self, purpose, operation)

    def fork(self, purpose: str) -> CommandResult["RouteEffectOwner"]:
        return self._registry.fork_route_owner(self, purpose)

    def close(self) -> None:
        self._registry.close_route_owner(self)

    def matches_playback_owner(self, playback_owner: PlaybackOwnerIdentity) -> bool:
        return self._registry.route_owner_matches_playback(self, playback_owner)


@dataclass(frozen=True, slots=True)
class ControllerSetupTransaction:
    registry: "ControllerSetupRegistry"
    setup: ControllerSetupLease
    registration: ControllerRegistrationHandle

    def run_step(self, operation: Callable[[], T]) -> CommandResult[T]:
        return self.registry.run_step(self.setup, operation)

    def require_step(self, operation: Callable[[], T]) -> T:
        result = self.run_step(operation)
        if not result.accepted:
            raise ControllerSetupFailure(
                result.failure
                or RuntimeFailure(
                    "controller_setup_stale",
                    "The exact controller setup is no longer active.",
                )
            )
        return result.value

    def publish(self) -> CommandResult[ControllerRegistrationHandle]:
        transferred = self.registry.transfer(self.setup, self.registration)
        if not transferred.accepted:
            return CommandResult(False, failure=transferred.failure)
        published = self.registry.publish_transfer(self.setup, self.registration)
        if not published.accepted:
            return CommandResult(False, failure=published.failure)
        return CommandResult(True, self.registration)

    def cancel(self, reason: str) -> CommandResult[None]:
        return self.registry.cancel_setup(self.setup, reason)


@dataclass(slots=True)
class _SetupRecord:
    lease: ControllerSetupLease
    cancellation: ControllerCancellationSignal
    phase: ControllerSetupPhase = ControllerSetupPhase.STAGED
    registration: ControllerRegistrationHandle | None = None
    in_flight_steps: int = 0
    sealed: bool = False


@dataclass(slots=True, eq=False)
class _RouteEffectNode:
    purpose: str
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    parent: "_RouteEffectNode | None" = None
    children: list["_RouteEffectNode"] = field(default_factory=list)
    closed: bool = False


@dataclass(slots=True, eq=False)
class _RouteEffectRecord:
    registration: ControllerRegistrationHandle
    playback_owner: PlaybackOwnerIdentity
    lease: WorkLease
    root: _RouteEffectNode
    phase: RouteEffectPhase = RouteEffectPhase.ACTIVE_ROUTE
    in_flight_steps: int = 0
    drain_owner: object | None = None


@dataclass(slots=True)
class _PendingInvalidationGeneration:
    binding: WorkLease | None
    invalidated: bool = False


class ControllerSetupRegistry:
    """Own setup admission and the exact latest speech-controller registration."""

    def __init__(self, *, drain_timeout_seconds: float = 0.5) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._drain_timeout_seconds = max(0.0, float(drain_timeout_seconds))
        self._setup: _SetupRecord | None = None
        self._last_setup_phase = ControllerSetupPhase.RETIRED
        self._registration: ControllerRegistrationHandle | None = None
        self._route: _RouteEffectRecord | None = None
        self._last_route_phase = RouteEffectPhase.RETIRED
        self._setup_owner = object()
        self._invalidation_owner = object()
        self._pending_invalidation_generations: dict[
            object,
            _PendingInvalidationGeneration,
        ] = {}
        self._replacement_record: _SetupRecord | None = None

    def invalidation_generation(
        self,
        binding: WorkLease | None = None,
    ) -> ControllerInvalidationGeneration:
        with self._condition:
            generation = ControllerInvalidationGeneration._new(
                self._invalidation_owner,
                binding,
            )
            self._pending_invalidation_generations[generation._token] = (
                _PendingInvalidationGeneration(binding)
            )
            return generation

    def retire_invalidation_generation(
        self,
        generation: ControllerInvalidationGeneration,
    ) -> None:
        with self._condition:
            if generation._owner is self._invalidation_owner:
                self._pending_invalidation_generations.pop(generation._token, None)

    def begin(
        self,
        binding: WorkLease | None,
        cancellation: ControllerCancellationSignal | None = None,
    ) -> CommandResult[ControllerSetupLease]:
        with self._condition:
            if self._setup is not None:
                if self._setup.phase is ControllerSetupPhase.DRAINING:
                    return _failure(
                        "controller_setup_draining",
                        "The prior controller setup is still draining admitted steps.",
                    )
                return _failure(
                    "controller_setup_busy",
                    "Another controller setup is already pending.",
                )
            lease = ControllerSetupLease(
                ControllerExecutionGeneration._new(),
                ControllerSetupGeneration._new(),
                binding,
                self._setup_owner,
            )
            self._setup = _SetupRecord(
                lease,
                cancellation or ControllerCancellationSignal.from_events(),
            )
            self._last_setup_phase = ControllerSetupPhase.STAGED
            return CommandResult(True, lease)

    def begin_latest(
        self,
        binding: WorkLease | None,
        cancellation: ControllerCancellationSignal,
        *,
        expected_invalidation_generation: ControllerInvalidationGeneration | None = None,
    ) -> CommandResult[ControllerSetupLease]:
        displaced_setup: ControllerCancellationSignal | None = None
        displaced_registration: ControllerRegistrationHandle | None = None
        draining_record: _SetupRecord | None = None
        with self._condition:
            if (
                expected_invalidation_generation is not None
                and not self._invalidation_generation_is_current_locked(
                    expected_invalidation_generation,
                    binding,
                )
            ):
                self._retire_invalidation_generation_locked(
                    expected_invalidation_generation
                )
                return self._binding_invalidated_failure()
            record = self._setup
            if record is not None:
                if record.phase is ControllerSetupPhase.DRAINING:
                    self._retire_invalidation_generation_locked(
                        expected_invalidation_generation
                    )
                    return _failure(
                        "controller_setup_draining",
                        "The prior controller setup is still draining admitted steps.",
                    )
                record.sealed = True
                displaced_setup = record.cancellation
                displaced_registration = self._detach_record_registration_locked(record)
                if record.in_flight_steps:
                    record.phase = ControllerSetupPhase.DRAINING
                    self._last_setup_phase = ControllerSetupPhase.DRAINING
                    self._replacement_record = record
                    draining_record = record
                else:
                    record.phase = ControllerSetupPhase.RETIRED
                    self._setup = None
                    self._last_setup_phase = ControllerSetupPhase.RETIRED
            if draining_record is None:
                self._retire_invalidation_generation_locked(
                    expected_invalidation_generation
                )
                return_value = self._install_setup_locked(binding, cancellation)
            else:
                return_value = None
        self._request_cancellation(
            displaced_setup,
            displaced_registration,
            "controller_replaced",
        )
        if return_value is not None:
            return return_value

        assert draining_record is not None
        deadline = time.monotonic() + self._drain_timeout_seconds
        with self._condition:
            while (
                self._setup is draining_record
                and draining_record.in_flight_steps
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if self._replacement_record is draining_record:
                        self._replacement_record = None
                    self._retire_invalidation_generation_locked(
                        expected_invalidation_generation
                    )
                    return _failure(
                        "controller_setup_draining",
                        "Controller setup steps did not drain before replacement timed out.",
                    )
                self._condition.wait(remaining)
            if (
                expected_invalidation_generation is not None
                and not self._invalidation_generation_is_current_locked(
                    expected_invalidation_generation,
                    binding,
                )
            ):
                self._retire_invalidation_generation_locked(
                    expected_invalidation_generation
                )
                self._retire_replacement_record_locked(draining_record)
                return self._binding_invalidated_failure()
            if self._setup is draining_record:
                draining_record.phase = ControllerSetupPhase.RETIRED
                self._setup = None
            elif self._setup is not None:
                if self._replacement_record is draining_record:
                    self._replacement_record = None
                self._retire_invalidation_generation_locked(
                    expected_invalidation_generation
                )
                return _failure(
                    "controller_setup_busy",
                    "Another controller setup replaced the draining setup.",
                )
            if self._replacement_record is draining_record:
                self._replacement_record = None
            self._retire_invalidation_generation_locked(
                expected_invalidation_generation
            )
            return self._install_setup_locked(binding, cancellation)

    def activate(
        self,
        setup: ControllerSetupLease,
        controller: object,
        cancellation: ControllerCancellationSignal,
    ) -> CommandResult[ControllerRegistrationHandle]:
        if controller is None:
            return _failure(
                "controller_registration_invalid",
                "A controller is required for setup activation.",
            )
        displaced: ControllerRegistrationHandle | None = None
        displaced_route: _RouteEffectRecord | None = None
        route_drain_owner: object | None = None
        route_cancellations: tuple[CancellationToken, ...] = ()
        with self._condition:
            record = self._exact_setup_locked(setup)
            if record is None or record.phase is not ControllerSetupPhase.STAGED:
                return self._stale_setup_failure_locked(setup)
            current_route = self._route
            if current_route is not None:
                displaced_route = current_route
                displaced = current_route.registration
                if current_route.phase is RouteEffectPhase.DRAINING:
                    if current_route.drain_owner is not None:
                        return self._draining_route_failure()
                    route_drain_owner = object()
                    current_route.drain_owner = route_drain_owner
                else:
                    route_drain_owner, route_cancellations = (
                        self._seal_route_locked(current_route)
                    )
            else:
                displaced = self._registration
                return_value = self._install_registration_locked(
                    record,
                    setup,
                    controller,
                    cancellation,
                )
        if displaced_route is None:
            if displaced is not None:
                displaced.cancellation.request("controller_replaced")
            return return_value

        self._cancel_route_nodes(route_cancellations, "controller_replaced")
        if displaced is not None:
            displaced.cancellation.request("controller_replaced")
        assert route_drain_owner is not None
        drained = self._wait_for_route_drain(
            displaced_route,
            route_drain_owner,
            time.monotonic() + self._drain_timeout_seconds,
        )
        if not drained.accepted:
            return CommandResult(False, failure=drained.failure)
        with self._condition:
            record = self._exact_setup_locked(setup)
            if record is None or record.phase is not ControllerSetupPhase.STAGED:
                return self._stale_setup_failure_locked(setup)
            if (
                self._route is not displaced_route
                or displaced_route.drain_owner is not route_drain_owner
                or self._registration is not displaced
            ):
                return self._stale_route_failure_locked()
            self._retire_route_record_locked(displaced_route)
            return self._install_registration_locked(
                record,
                setup,
                controller,
                cancellation,
            )

    def _install_registration_locked(
        self,
        record: _SetupRecord,
        setup: ControllerSetupLease,
        controller: object,
        cancellation: ControllerCancellationSignal,
    ) -> CommandResult[ControllerRegistrationHandle]:
        handle = ControllerRegistrationHandle(
            setup.execution_generation,
            setup.setup_generation,
            ControllerRegistrationGeneration._new(),
            setup.binding,
            controller,
            cancellation,
        )
        self._registration = handle
        record.registration = handle
        record.phase = ControllerSetupPhase.ACTIVE
        self._last_setup_phase = ControllerSetupPhase.ACTIVE
        return CommandResult(True, handle)

    def run_step(
        self,
        setup: ControllerSetupLease,
        operation: Callable[[], T],
    ) -> CommandResult[T]:
        with self._condition:
            record = self._exact_setup_locked(setup)
            if (
                record is None
                or record.phase is not ControllerSetupPhase.ACTIVE
                or record.sealed
            ):
                return self._stale_setup_failure_locked(setup)
            record.in_flight_steps += 1
        try:
            return CommandResult(True, operation())
        except BaseException as exc:
            return _failure(
                "controller_setup_step_failed",
                str(exc) or "Controller setup step failed.",
                exc,
            )
        finally:
            self._release_step(record)

    def transfer(
        self,
        setup: ControllerSetupLease,
        registration: ControllerRegistrationHandle,
    ) -> CommandResult[None]:
        with self._condition:
            record = self._exact_setup_locked(setup)
            if (
                record is None
                or record.phase is not ControllerSetupPhase.ACTIVE
                or record.registration is not registration
                or record.sealed
            ):
                return self._stale_setup_failure_locked(setup)
            if record.in_flight_steps:
                return _failure(
                    "controller_setup_busy",
                    "Controller setup steps are still in flight.",
                )
            record.sealed = True
            record.phase = ControllerSetupPhase.TRANSFERRED
            self._last_setup_phase = ControllerSetupPhase.TRANSFERRED
            return CommandResult(True)

    def publish_transfer(
        self,
        setup: ControllerSetupLease,
        registration: ControllerRegistrationHandle,
    ) -> CommandResult[None]:
        with self._condition:
            record = self._exact_setup_locked(setup)
            if (
                record is None
                or record.phase is not ControllerSetupPhase.TRANSFERRED
                or record.registration is not registration
            ):
                return self._stale_setup_failure_locked(setup)
            self._setup = None
            self._last_setup_phase = ControllerSetupPhase.TRANSFERRED
            self._condition.notify_all()
            return CommandResult(True)

    def activate_route(
        self,
        registration: ControllerRegistrationHandle,
        playback_owner: PlaybackOwnerIdentity,
    ) -> CommandResult[RouteEffectOwner]:
        owner_lease = getattr(playback_owner, "lease", None)
        playback_generation = getattr(playback_owner, "generation", None)
        if (
            not isinstance(owner_lease, WorkLease)
            or owner_lease != registration.binding
            or owner_lease.turn_id is None
            or owner_lease.route_generation is None
            or isinstance(playback_generation, bool)
            or not isinstance(playback_generation, int)
            or playback_generation < 0
        ):
            return _failure(
                "route_effect_invalid",
                "Route effects require an exact playback owner and turn/route lease.",
            )

        displaced: _RouteEffectRecord | None = None
        drain_owner: object | None = None
        cancellations: tuple[CancellationToken, ...] = ()
        with self._condition:
            if self._registration is not registration:
                return self._stale_route_failure_locked()
            current = self._route
            if current is not None:
                if (
                    current.registration is registration
                    and current.playback_owner is playback_owner
                    and current.lease == owner_lease
                    and current.phase is RouteEffectPhase.ACTIVE_ROUTE
                ):
                    if current.root.closed:
                        return self._stale_route_failure_locked()
                    return CommandResult(
                        True,
                        RouteEffectOwner(self, current, current.root),
                    )
                if current.phase is RouteEffectPhase.DRAINING:
                    return self._draining_route_failure()
                if int(current.playback_owner.generation) >= playback_generation:
                    return _failure(
                        "route_effect_superseded",
                        "A newer playback route already owns terminal effects.",
                    )
                displaced = current
                drain_owner, cancellations = self._seal_route_locked(current)
            else:
                return self._install_route_locked(registration, playback_owner)

        self._cancel_route_nodes(cancellations, "playback_owner_replaced")
        assert displaced is not None and drain_owner is not None
        drained = self._wait_for_route_drain(
            displaced,
            drain_owner,
            time.monotonic() + self._drain_timeout_seconds,
        )
        if not drained.accepted:
            return CommandResult(False, failure=drained.failure)
        with self._condition:
            if (
                self._route is not displaced
                or displaced.drain_owner is not drain_owner
                or self._registration is not registration
            ):
                return self._stale_route_failure_locked()
            self._retire_route_record_locked(displaced)
            return self._install_route_locked(registration, playback_owner)

    def run_route_step(
        self,
        owner: RouteEffectOwner,
        purpose: str,
        operation: Callable[[], T],
    ) -> CommandResult[T]:
        del purpose
        with self._condition:
            record = self._exact_route_owner_locked(owner)
            if record is None:
                return self._stale_route_failure_locked()
            if record.phase is RouteEffectPhase.DRAINING:
                return self._draining_route_failure()
            if record.phase is not RouteEffectPhase.ACTIVE_ROUTE or owner._node.closed:
                return self._stale_route_failure_locked()
            record.in_flight_steps += 1
        try:
            return CommandResult(True, operation())
        except BaseException as exc:
            return _failure(
                "route_effect_step_failed",
                str(exc) or "Route effect step failed.",
                exc,
            )
        finally:
            self._release_route_step(record)

    def fork_route_owner(
        self,
        owner: RouteEffectOwner,
        purpose: str,
    ) -> CommandResult[RouteEffectOwner]:
        resolved_purpose = str(purpose or "route_child")
        with self._condition:
            record = self._exact_route_owner_locked(owner)
            if record is None:
                return self._stale_route_failure_locked()
            if record.phase is RouteEffectPhase.DRAINING:
                return self._draining_route_failure()
            if record.phase is not RouteEffectPhase.ACTIVE_ROUTE or owner._node.closed:
                return self._stale_route_failure_locked()
            node = _RouteEffectNode(resolved_purpose, parent=owner._node)
            owner._node.children.append(node)
            return CommandResult(True, RouteEffectOwner(self, record, node))

    def close_route_owner(self, owner: RouteEffectOwner) -> None:
        cancellations: tuple[CancellationToken, ...] = ()
        with self._condition:
            record = self._exact_route_owner_locked(owner)
            if record is None or owner._node.closed:
                return
            cancellations = self._close_route_node_locked(owner._node)
            self._condition.notify_all()
        self._cancel_route_nodes(cancellations, "route_owner_closed")

    def route_owner_matches_playback(
        self,
        owner: RouteEffectOwner,
        playback_owner: PlaybackOwnerIdentity,
    ) -> bool:
        with self._condition:
            record = self._exact_route_owner_locked(owner)
            return bool(
                record is not None
                and record.phase is RouteEffectPhase.ACTIVE_ROUTE
                and not owner._node.closed
                and record.playback_owner is playback_owner
                and record.lease == playback_owner.lease
            )

    def retire_setup(self, setup: ControllerSetupLease) -> CommandResult[None]:
        with self._condition:
            record = self._exact_setup_locked(setup)
            if record is None or record.phase is not ControllerSetupPhase.STAGED:
                return self._stale_setup_failure_locked(setup)
            record.sealed = True
            record.phase = ControllerSetupPhase.RETIRED
            self._setup = None
            self._last_setup_phase = ControllerSetupPhase.RETIRED
            self._condition.notify_all()
            return CommandResult(True)

    def cancel_setup(
        self,
        setup: ControllerSetupLease,
        reason: str = "controller_setup_cancelled",
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult[None]:
        with self._condition:
            record = self._exact_setup_locked(setup)
            if record is None:
                return self._stale_setup_failure_locked(setup)
            record.sealed = True
            record.phase = ControllerSetupPhase.DRAINING
            self._last_setup_phase = ControllerSetupPhase.DRAINING
            registration = record.registration
            if registration is not None and self._registration is registration:
                self._registration = None
            setup_cancellation = record.cancellation
        self._request_cancellation(setup_cancellation, registration, reason)

        timeout = (
            self._drain_timeout_seconds
            if timeout_seconds is None
            else max(0.0, float(timeout_seconds))
        )
        deadline = time.monotonic() + timeout
        with self._condition:
            while (
                record is not None
                and self._setup is record
                and record.in_flight_steps
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return _failure(
                        "controller_setup_draining",
                        "Controller setup steps did not drain before cancellation timed out.",
                    )
                self._condition.wait(remaining)
            if record is not None and self._setup is record:
                record.phase = ControllerSetupPhase.RETIRED
                self._setup = None
                self._last_setup_phase = ControllerSetupPhase.RETIRED
                self._condition.notify_all()
        return CommandResult(True)

    def invalidate_binding(
        self,
        binding: WorkLease,
        reason: str = "controller_binding_invalidated",
        *,
        include_descendants: bool = False,
        timeout_seconds: float | None = None,
        after_seal: Callable[[], object] | None = None,
    ) -> CommandResult[ControllerBindingInvalidation]:
        setup_cancellation: ControllerCancellationSignal | None = None
        registration: ControllerRegistrationHandle | None = None
        record: _SetupRecord | None = None
        route: _RouteEffectRecord | None = None
        route_drain_owner: object | None = None
        route_cancellations: tuple[CancellationToken, ...] = ()
        timeout = (
            self._drain_timeout_seconds
            if timeout_seconds is None
            else max(0.0, float(timeout_seconds))
        )
        deadline = time.monotonic() + timeout
        with self._condition:
            current_route = self._route
            if current_route is not None and self._binding_matches_scope(
                current_route.lease,
                binding,
                include_descendants,
            ):
                route = current_route
                if route.phase is RouteEffectPhase.DRAINING:
                    if route.drain_owner is not None:
                        return CommandResult(
                            False,
                            ControllerBindingInvalidation(None, ()),
                            self._draining_route_failure().failure,
                        )
                    route_drain_owner = object()
                    route.drain_owner = route_drain_owner
                else:
                    route_drain_owner, route_cancellations = (
                        self._seal_route_locked(route)
                    )
            current = self._setup
            if current is not None and self._binding_matches_scope(
                current.lease.binding,
                binding,
                include_descendants,
            ):
                record = current
                record.sealed = True
                record.phase = ControllerSetupPhase.DRAINING
                self._last_setup_phase = ControllerSetupPhase.DRAINING
                setup_cancellation = record.cancellation
                registration = record.registration
            current_registration = self._registration
            if (
                current_registration is not None
                and self._binding_matches_scope(
                    current_registration.binding,
                    binding,
                    include_descendants,
                )
            ):
                if registration is None:
                    registration = current_registration
            if registration is None and route is not None:
                registration = route.registration
        self._cancel_route_nodes(route_cancellations, reason)
        self._request_cancellation(setup_cancellation, registration, reason)
        if after_seal is not None:
            after_seal()

        invalidation = ControllerBindingInvalidation(
            setup=record.lease if record is not None else None,
            registrations=((registration,) if registration is not None else ()),
        )
        if route is not None:
            assert route_drain_owner is not None
            drained = self._wait_for_route_drain(
                route,
                route_drain_owner,
                deadline,
            )
            if not drained.accepted:
                return CommandResult(False, invalidation, drained.failure)
        with self._condition:
            while (
                record is not None
                and self._setup is record
                and record.in_flight_steps
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return CommandResult(
                        False,
                        invalidation,
                        RuntimeFailure(
                            "controller_setup_draining",
                            "Controller setup steps did not drain before invalidation timed out.",
                        ),
                    )
                self._condition.wait(remaining)
            if route is not None and (
                self._route is not route
                or route.drain_owner is not route_drain_owner
            ):
                return CommandResult(
                    False,
                    invalidation,
                    self._stale_route_failure_locked().failure,
                )
            for pending in self._pending_invalidation_generations.values():
                if self._binding_matches_scope(
                    pending.binding,
                    binding,
                    include_descendants,
                ):
                    pending.invalidated = True
            if route is not None:
                self._retire_route_record_locked(route)
            if record is not None and self._setup is record:
                if record.lease._terminal.failure is None:
                    record.lease._terminal.failure = RuntimeFailure(
                        "controller_binding_invalidated",
                        "The controller binding was invalidated before setup publication.",
                    )
                record.phase = ControllerSetupPhase.RETIRED
                self._setup = None
                self._last_setup_phase = ControllerSetupPhase.RETIRED
            if (
                self._registration is not None
                and self._binding_matches_scope(
                    self._registration.binding,
                    binding,
                    include_descendants,
                )
            ):
                self._registration = None
            self._condition.notify_all()
        return CommandResult(True, invalidation)

    def retire(self, registration: ControllerRegistrationHandle) -> bool:
        route: _RouteEffectRecord | None = None
        route_drain_owner: object | None = None
        route_cancellations: tuple[CancellationToken, ...] = ()
        with self._condition:
            if self._registration is not registration:
                return False
            current_route = self._route
            if current_route is None:
                self._registration = None
                return True
            if current_route.registration is not registration:
                return False
            route = current_route
            if route.phase is RouteEffectPhase.DRAINING:
                if route.drain_owner is not None:
                    return False
                route_drain_owner = object()
                route.drain_owner = route_drain_owner
            else:
                route_drain_owner, route_cancellations = self._seal_route_locked(
                    route
                )
        self._cancel_route_nodes(route_cancellations, "route_retired")
        assert route is not None and route_drain_owner is not None
        drained = self._wait_for_route_drain(
            route,
            route_drain_owner,
            time.monotonic() + self._drain_timeout_seconds,
        )
        if not drained.accepted:
            return False
        with self._condition:
            if (
                self._registration is not registration
                or self._route is not route
                or route.drain_owner is not route_drain_owner
            ):
                return False
            self._retire_route_record_locked(route)
            self._registration = None
            return True

    def snapshot(self) -> ControllerRegistrySnapshot:
        with self._condition:
            record = self._setup
            route = self._route
            return ControllerRegistrySnapshot(
                setup=record.lease if record is not None else None,
                setup_phase=(record.phase if record is not None else self._last_setup_phase),
                in_flight_steps=(record.in_flight_steps if record is not None else 0),
                registration=self._registration,
                route_phase=(
                    route.phase if route is not None else self._last_route_phase
                ),
                route_in_flight_steps=(
                    route.in_flight_steps if route is not None else 0
                ),
                route_owner=(
                    RouteEffectOwner(self, route, route.root)
                    if route is not None
                    else None
                ),
            )

    def registrations(
        self,
        *,
        binding: WorkLease | None = None,
    ) -> tuple[ControllerRegistrationHandle, ...]:
        with self._condition:
            registration = self._registration
            if registration is None:
                return ()
            if binding is not None and registration.binding != binding:
                return ()
            return (registration,)

    def _exact_setup_locked(
        self,
        setup: ControllerSetupLease,
    ) -> _SetupRecord | None:
        record = self._setup
        if record is None or record.lease != setup:
            return None
        return record

    def _exact_route_owner_locked(
        self,
        owner: RouteEffectOwner,
    ) -> _RouteEffectRecord | None:
        record = self._route
        if (
            not isinstance(owner, RouteEffectOwner)
            or owner._registry is not self
            or record is None
            or owner._record is not record
            or owner.registration_generation
            != record.registration.registration_generation
            or owner.playback_generation != int(record.playback_owner.generation)
            or owner.lease != record.lease
            or not self._route_contains_node_locked(record, owner._node)
        ):
            return None
        return record

    def _install_route_locked(
        self,
        registration: ControllerRegistrationHandle,
        playback_owner: PlaybackOwnerIdentity,
    ) -> CommandResult[RouteEffectOwner]:
        root = _RouteEffectNode("route")
        record = _RouteEffectRecord(
            registration,
            playback_owner,
            playback_owner.lease,
            root,
        )
        self._route = record
        self._last_route_phase = RouteEffectPhase.ACTIVE_ROUTE
        return CommandResult(True, RouteEffectOwner(self, record, root))

    def _seal_route_locked(
        self,
        record: _RouteEffectRecord,
    ) -> tuple[object, tuple[CancellationToken, ...]]:
        drain_owner = object()
        record.phase = RouteEffectPhase.DRAINING
        record.drain_owner = drain_owner
        self._last_route_phase = RouteEffectPhase.DRAINING
        cancellations = self._close_route_node_locked(record.root)
        self._condition.notify_all()
        return drain_owner, cancellations

    def _wait_for_route_drain(
        self,
        record: _RouteEffectRecord,
        drain_owner: object,
        deadline: float,
    ) -> CommandResult[None]:
        with self._condition:
            while (
                self._route is record
                and record.drain_owner is drain_owner
                and record.in_flight_steps
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    record.drain_owner = None
                    return self._draining_route_failure()
                self._condition.wait(remaining)
            if self._route is not record or record.drain_owner is not drain_owner:
                return self._stale_route_failure_locked()
            return CommandResult(True)

    def _retire_route_record_locked(self, record: _RouteEffectRecord) -> None:
        if self._route is not record:
            return
        record.phase = RouteEffectPhase.RETIRED
        record.drain_owner = None
        self._route = None
        self._last_route_phase = RouteEffectPhase.RETIRED
        self._condition.notify_all()

    def _close_route_node_locked(
        self,
        node: _RouteEffectNode,
    ) -> tuple[CancellationToken, ...]:
        cancellations: list[CancellationToken] = []
        pending = [node]
        while pending:
            current = pending.pop()
            pending.extend(current.children)
            if current.closed:
                continue
            current.closed = True
            cancellations.append(current.cancellation)
        return tuple(cancellations)

    @staticmethod
    def _cancel_route_nodes(
        cancellations: tuple[CancellationToken, ...],
        reason: str,
    ) -> None:
        for cancellation in cancellations:
            cancellation.cancel(reason)

    @staticmethod
    def _route_contains_node_locked(
        record: _RouteEffectRecord,
        candidate: _RouteEffectNode,
    ) -> bool:
        pending = [record.root]
        while pending:
            node = pending.pop()
            if node is candidate:
                return True
            pending.extend(node.children)
        return False

    @staticmethod
    def _draining_route_failure() -> CommandResult:
        return _failure(
            "route_effect_draining",
            "Route effects did not drain before the operation timed out.",
        )

    @staticmethod
    def _stale_route_failure_locked() -> CommandResult:
        return _failure(
            "route_effect_stale",
            "The exact controller, playback, and route lease no longer own effects.",
        )

    def _stale_setup_failure_locked(
        self,
        setup: ControllerSetupLease | None = None,
    ) -> CommandResult:
        if setup is not None and setup._owner is self._setup_owner:
            terminal_failure = setup._terminal.failure
            if terminal_failure is not None:
                setup._terminal.failure = None
                return CommandResult(False, failure=terminal_failure)
        if self._setup is not None and self._setup.phase is ControllerSetupPhase.DRAINING:
            return _failure(
                "controller_setup_draining",
                "The prior controller setup is still draining admitted steps.",
            )
        return _failure(
            "controller_setup_stale",
            "The exact controller setup generation is no longer active.",
        )

    def _install_setup_locked(
        self,
        binding: WorkLease | None,
        cancellation: ControllerCancellationSignal,
    ) -> CommandResult[ControllerSetupLease]:
        lease = ControllerSetupLease(
            ControllerExecutionGeneration._new(),
            ControllerSetupGeneration._new(),
            binding,
            self._setup_owner,
        )
        self._setup = _SetupRecord(lease, cancellation)
        self._last_setup_phase = ControllerSetupPhase.STAGED
        return CommandResult(True, lease)

    def _detach_record_registration_locked(
        self,
        record: _SetupRecord,
    ) -> ControllerRegistrationHandle | None:
        registration = record.registration
        if registration is not None and self._registration is registration:
            self._registration = None
        return registration

    @staticmethod
    def _request_cancellation(
        setup: ControllerCancellationSignal | None,
        registration: ControllerRegistrationHandle | None,
        reason: str,
    ) -> None:
        if setup is not None:
            setup.request(reason)
        if registration is not None and registration.cancellation is not setup:
            registration.cancellation.request(reason)

    def _retire_replacement_record_locked(self, record: _SetupRecord) -> None:
        if self._replacement_record is record:
            self._replacement_record = None
        if self._setup is record and not record.in_flight_steps:
            record.phase = ControllerSetupPhase.RETIRED
            self._setup = None
            self._last_setup_phase = ControllerSetupPhase.RETIRED
            self._condition.notify_all()

    @staticmethod
    def _binding_matches_scope(
        candidate: WorkLease | None,
        scope: WorkLease,
        include_descendants: bool,
    ) -> bool:
        if candidate is None:
            return False
        if not include_descendants:
            return candidate == scope
        return bool(
            candidate.run_id == scope.run_id
            and (
                scope.session_generation is None
                or candidate.session_generation == scope.session_generation
            )
            and (scope.turn_id is None or candidate.turn_id == scope.turn_id)
            and (
                scope.route_generation is None
                or candidate.route_generation == scope.route_generation
            )
        )

    def _invalidation_generation_is_current_locked(
        self,
        generation: ControllerInvalidationGeneration,
        binding: WorkLease | None,
    ) -> bool:
        if (
            generation._owner is not self._invalidation_owner
            or generation._binding != binding
        ):
            return False
        pending = self._pending_invalidation_generations.get(generation._token)
        return bool(
            pending is not None
            and pending.binding == binding
            and not pending.invalidated
        )

    def _retire_invalidation_generation_locked(
        self,
        generation: ControllerInvalidationGeneration | None,
    ) -> None:
        if generation is not None and generation._owner is self._invalidation_owner:
            self._pending_invalidation_generations.pop(generation._token, None)

    @staticmethod
    def _binding_invalidated_failure() -> CommandResult:
        return _failure(
            "controller_binding_invalidated",
            "The controller binding was invalidated before setup activation.",
        )

    def _release_step(self, record: _SetupRecord) -> None:
        with self._condition:
            record.in_flight_steps = max(0, record.in_flight_steps - 1)
            if (
                self._setup is record
                and record.phase is ControllerSetupPhase.DRAINING
                and not record.in_flight_steps
                and self._replacement_record is not record
            ):
                record.phase = ControllerSetupPhase.RETIRED
                self._setup = None
                self._last_setup_phase = ControllerSetupPhase.RETIRED
            self._condition.notify_all()

    def _release_route_step(self, record: _RouteEffectRecord) -> None:
        with self._condition:
            record.in_flight_steps = max(0, record.in_flight_steps - 1)
            self._condition.notify_all()


def _failure(
    category: str,
    message: str,
    cause: BaseException | None = None,
) -> CommandResult:
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = [
    "ControllerBindingInvalidation",
    "ControllerCancellationSignal",
    "ControllerExecutionGeneration",
    "ControllerInvalidationGeneration",
    "ControllerRegistrationGeneration",
    "ControllerRegistrationHandle",
    "ControllerRegistrySnapshot",
    "ControllerSetupFailure",
    "ControllerSetupGeneration",
    "ControllerSetupLease",
    "ControllerSetupPhase",
    "ControllerSetupRegistry",
    "ControllerSetupTransaction",
    "RouteEffectOwner",
    "RouteEffectPhase",
]
