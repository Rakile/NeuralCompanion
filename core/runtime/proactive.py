"""Lease-bound proactive candidate scheduling and accepted-turn handoff."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
import threading
import time
from types import MappingProxyType
import uuid

from core.runtime.contracts import CommandResult, RuntimeFailure
from core.runtime.identifiers import WorkLease
from core.runtime.lifecycle import WorkerHandle, WorkerSupervisor
from core.runtime.turns import TurnCoordinator, TurnSnapshot, UserInput


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProactiveCandidate:
    candidate_id: str
    deadline: float
    lease: WorkLease
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)
    action: str = "proactive_timeout"

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", str(self.candidate_id or "").strip())
        object.__setattr__(self, "text", str(self.text or "").strip())
        object.__setattr__(self, "action", str(self.action or "proactive_timeout").strip())
        object.__setattr__(self, "metadata", _freeze(dict(self.metadata or {})))


class ProactiveService:
    """Own one scheduler and one exact candidate through turn acceptance."""

    name = "proactive"

    def __init__(
        self,
        *,
        workers: WorkerSupervisor,
        turns: TurnCoordinator | None,
        lease_factory: Callable[[], WorkLease],
        lease_is_current: Callable[[WorkLease], bool],
        on_due: Callable[[ProactiveCandidate], object] | None = None,
        clock: Callable[[], float] = time.monotonic,
        candidate_id_factory: Callable[[], str] | None = None,
        admit_effect: Callable[[WorkLease], object | None] | None = None,
        release_effect: Callable[[object], None] | None = None,
    ) -> None:
        self._workers = workers
        self._turns = turns
        self._lease_factory = lease_factory
        self._lease_is_current = lease_is_current
        self._on_due = on_due
        self._clock = clock
        self._candidate_id_factory = candidate_id_factory or (lambda: uuid.uuid4().hex)
        self._admit_effect = admit_effect
        self._release_effect = release_effect
        self._lock = threading.Lock()
        self._worker_start_lock = threading.Lock()
        self._wake = threading.Event()
        self._candidate: ProactiveCandidate | None = None
        self._ready_candidate_id = ""
        self._worker: WorkerHandle | None = None
        self._accepting = False

    def set_turns(self, turns: TurnCoordinator) -> None:
        """Complete the composition cycle before the service is started."""

        with self._lock:
            if self._accepting:
                raise RuntimeError("Cannot replace TurnCoordinator while proactive is running")
            self._turns = turns

    def start(self) -> CommandResult[None]:
        with self._lock:
            if self._turns is None:
                return _failure(
                    "proactive_turns_unavailable",
                    "Proactive scheduling requires the composed TurnCoordinator.",
                )
            self._accepting = True
        return CommandResult(True)

    def stop(self) -> CommandResult[None]:
        with self._lock:
            self._accepting = False
            self._candidate = None
            self._ready_candidate_id = ""
            worker = self._worker
            self._worker = None
            self._wake.set()
        if worker is not None:
            self._workers.cancel_handles((worker,), "proactive_shutdown")
            self._workers.join_handles((worker,))
            if worker.thread.is_alive():
                return _failure(
                    "proactive_scheduler_stop_timeout",
                    "The proactive scheduler did not stop within its supervisor bound.",
                )
        return CommandResult(True)

    def schedule(
        self,
        lease: WorkLease,
        *,
        silence_seconds: float,
        text: str = "You continue speaking.",
        metadata: Mapping[str, object] | None = None,
        action: str = "proactive_timeout",
    ) -> CommandResult[ProactiveCandidate]:
        content = str(text or "").strip()
        if not content:
            return _failure("proactive_invalid_text", "Proactive text must be non-empty.")
        if not self._lease_is_current(lease):
            return _failure("proactive_stale_lease", "The proactive lease is stale.")
        try:
            deadline = float(self._clock()) + max(0.0, float(silence_seconds or 0.0))
            candidate_id = str(self._candidate_id_factory() or "").strip()
        except BaseException as exc:
            return _failure("proactive_schedule_failed", str(exc) or "Could not schedule proactive work.", exc)
        if not candidate_id:
            return _failure("proactive_invalid_identity", "Proactive candidate identity is empty.")
        candidate = ProactiveCandidate(
            candidate_id=candidate_id,
            deadline=deadline,
            lease=lease,
            text=content,
            metadata=dict(metadata or {}),
            action=action,
        )
        with self._lock:
            if not self._accepting:
                return _failure("proactive_stopped", "Proactive scheduling is not accepting work.")
            self._candidate = candidate
            self._ready_candidate_id = ""
            self._wake.set()
        scheduler = self._ensure_scheduler()
        if not scheduler.accepted:
            self._discard_if_current(candidate.candidate_id)
            return CommandResult(False, failure=scheduler.failure)
        return CommandResult(True, candidate)

    def cancel(self, reason: str) -> CommandResult[None]:
        del reason
        with self._lock:
            self._candidate = None
            self._ready_candidate_id = ""
            self._wake.set()
        return CommandResult(True)

    def current_candidate(self) -> ProactiveCandidate | None:
        with self._lock:
            return self._candidate

    def fire(self, candidate_id: str) -> CommandResult[ProactiveCandidate]:
        key = str(candidate_id or "").strip()
        with self._lock:
            candidate = self._candidate
            if candidate is None or candidate.candidate_id != key:
                return _failure(
                    "proactive_candidate_not_found",
                    "The proactive candidate is no longer current.",
                )
            if self._ready_candidate_id == key:
                return CommandResult(True, candidate)
        if not self._lease_is_current(candidate.lease):
            self._discard_if_current(key)
            return _failure("proactive_stale_lease", "The proactive lease is stale.")
        try:
            now = float(self._clock())
        except BaseException as exc:
            return _failure("proactive_clock_failed", str(exc) or "Proactive clock failed.", exc)
        if now < candidate.deadline:
            return _failure("proactive_not_due", "The proactive candidate is not due yet.")

        admission = None
        if self._admit_effect is not None:
            admission = self._admit_effect(candidate.lease)
            if admission is None:
                self._discard_if_current(key)
                return _failure("proactive_stale_lease", "The proactive lease is stale.")
        try:
            if not self._lease_is_current(candidate.lease):
                self._discard_if_current(key)
                return _failure("proactive_stale_lease", "The proactive lease is stale.")
            with self._lock:
                if self._candidate is not candidate:
                    return _failure(
                        "proactive_candidate_not_found",
                        "The proactive candidate was replaced before delivery.",
                    )
                self._ready_candidate_id = key
            if self._on_due is not None:
                try:
                    self._on_due(candidate)
                except BaseException as exc:
                    self._discard_if_current(key)
                    return _failure(
                        "proactive_callback_failed",
                        str(exc) or "The proactive due callback failed.",
                        exc,
                    )
            return CommandResult(True, candidate)
        finally:
            if admission is not None and self._release_effect is not None:
                self._release_effect(admission)

    def accept(self, candidate_id: str) -> CommandResult[TurnSnapshot]:
        key = str(candidate_id or "").strip()
        with self._lock:
            candidate = self._candidate
            if (
                candidate is None
                or candidate.candidate_id != key
                or self._ready_candidate_id != key
            ):
                return _failure(
                    "proactive_candidate_not_ready",
                    "The exact proactive candidate is not ready for acceptance.",
                )
            self._candidate = None
            self._ready_candidate_id = ""
            self._wake.set()
        if not self._lease_is_current(candidate.lease):
            return _failure("proactive_stale_lease", "The proactive lease is stale.")
        turns = self._turns
        if turns is None:
            return _failure(
                "proactive_turns_unavailable",
                "Proactive turn acceptance is unavailable.",
            )
        return turns.accept(
            UserInput.completed(
                candidate.text,
                metadata=dict(candidate.metadata),
                source="proactive",
                persist=False,
                source_lease=candidate.lease,
            )
        )

    def _run_scheduler(self, token) -> None:
        while not token.cancelled:
            with self._lock:
                candidate = self._candidate
                ready = bool(
                    candidate is not None
                    and self._ready_candidate_id == candidate.candidate_id
                )
                wake = self._wake
                wake.clear()
            if candidate is None or ready:
                wake.wait()
                continue
            try:
                delay = max(0.0, candidate.deadline - float(self._clock()))
            except BaseException:
                delay = 0.0
            if wake.wait(delay):
                continue
            self.fire(candidate.candidate_id)

    def _ensure_scheduler(self) -> CommandResult[None]:
        with self._worker_start_lock:
            with self._lock:
                worker = self._worker
                if worker is not None and worker.thread.is_alive():
                    return CommandResult(True)
                if not self._accepting:
                    return _failure(
                        "proactive_stopped",
                        "Proactive scheduling is not accepting work.",
                    )
                self._wake = threading.Event()
                lease = self._lease_factory()
            try:
                worker = self._workers.spawn(
                    name="nc-proactive-scheduler",
                    lease=lease,
                    target=self._run_scheduler,
                    on_cancel=lambda _reason: self._wake.set(),
                    identity=("proactive", lease.run_id.value),
                )
            except BaseException as exc:
                return _failure(
                    "proactive_scheduler_start_failed",
                    str(exc) or "Could not start proactive scheduler.",
                    exc,
                )
            with self._lock:
                self._worker = worker
                self._wake.set()
            return CommandResult(True)

    def _discard_if_current(self, candidate_id: str) -> None:
        with self._lock:
            if self._candidate is not None and self._candidate.candidate_id == candidate_id:
                self._candidate = None
                self._ready_candidate_id = ""
                self._wake.set()


def _failure(category: str, message: str, cause: BaseException | None = None):
    return CommandResult(False, failure=RuntimeFailure(category, message, cause))


__all__ = ["ProactiveCandidate", "ProactiveService"]
